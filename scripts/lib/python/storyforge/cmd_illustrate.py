"""storyforge illustrate — plan, art-direct, ingest, and embed interior illustrations.

Every phase is its own flag:

  --direction  Write the book-level art direction: format, visual promise,
               recurring visual language, content limits, continuity anchors.
               Authored once; constrains every illustration.
  --plan       Decide where illustrations belong. Deterministic pre-pass, then
               an LLM pass that argues against those findings.
  --state      Write the visual-state transition log: what changes on schedule,
               as opposed to the canon tier for what must never change.
  --audit      Read the prose against that matrix and report contradictions.
               Read-only with respect to the prose and the log.
  --sequence   Assign each illustration a distinct treatment — camera
               distance and height, time of day, framing — so twenty
               independent generation calls stop converging on one shot.
  --prompts    Turn planned rows into image-generation prompts.
  --package    Assemble manuscript/illustration-packet/ — the shared files a
               long-running generation session uploads once, plus
               image-prompts/<id>.md, the file uploaded per illustration.
               Assembly only, no API calls.
  --export     Removed in 1.57.0. Exits 2 with a pointer to --package, which
               absorbed it; --anchor-batch retired with it.
  --ingest     Bring rendered files in, record digests, embed markers.
  --embed      (Re)insert markers from the plan, without ingesting.
  --diagnose   Read-only plan health report, with the recommended render
               order. Exclusive — when passed, no other phase runs.
  --review     Whole-sequence continuity checklist for the rendered set.

The command emits art direction; the author renders externally and ingests.
That split is deliberate — image generation is iterative and visual, and a
human looking at four candidates beats an autonomous loop guessing which one
landed.

See benjaminsnorris/storyforge#278.
"""

import argparse
import os
import re
import sys
import time
from datetime import date
from typing import Literal, NamedTuple, TypedDict

from storyforge.api import (
    calculate_cost_from_usage, extract_text, extract_usage, invoke,
)
from storyforge.common import (
    CoachingLevel, detect_project_root, get_coaching_level, get_medium,
    install_signal_handlers, log, read_yaml_field, select_model,
)
from storyforge.costs import log_operation
from storyforge import illustrations as ill
from storyforge import packet
from storyforge import prompts_illustrate as pi
from storyforge import prompts_packet as pp
from storyforge import visual_state as vs

#: What to actually do, per cause. The whole point of keying the unpositioned
#: warning on a cause was to give the right fix — the first cut distinguished the
#: causes and then printed only the reason, two of which state no fix at all, so a
#: distinction was drawn in order to say nothing with it. One clause per cause,
#: the `_STALE_KIND_CLAUSES` pattern.
_UNPOSITIONED_FIXES: dict[ill.SplitCause, str] = {
    'invalid_placement': 'set placement to before_anchor, after_anchor, '
                         'scene_open, or scene_close',
    'no_anchor': 'quote a short phrase from the scene into the anchor cell, or '
                 'use scene_open / scene_close',
    'anchor_drift': 're-anchor the plan row to a phrase in the revised prose',
    'anchor_ambiguous': 'lengthen the anchor until it is unique in the scene',
    'block_unresolved': 'the anchor matched but its paragraph did not resolve — '
                        'report this, it should not happen',
    'scene_missing': 'fix scene_id, or add the missing scene file',
    'scene_unreadable': 'fix the scene file — it exists but could not be read',
    'scene_empty': 'draft the scene before directing its illustration',
    '': 'no cause recorded — report this',
}


def parse_args(argv):
    parser = argparse.ArgumentParser(
        prog='storyforge illustrate',
        description='Plan, art-direct, ingest, and embed interior illustrations.',
    )
    phase = parser.add_argument_group('phases')
    phase.add_argument('--direction', action='store_true',
                       help='Write the book-level art-direction document')
    phase.add_argument('--plan', action='store_true',
                       help='Propose illustration moments into the plan CSV')
    phase.add_argument('--prompts', action='store_true',
                       help='Write art-direction prompts for planned rows')
    phase.add_argument('--sequence', action='store_true',
                       help='Assign each illustration a distinct treatment so '
                            'the set does not converge on one shot')
    phase.add_argument('--package', action='store_true',
                       help='Assemble the handoff packet in '
                            'manuscript/illustration-packet/ (no API calls)')
    phase.add_argument('--export', action='store_true',
                       help=argparse.SUPPRESS)
    phase.add_argument('--ingest', metavar='PATH', default=None,
                       help='Ingest rendered illustration file(s) from a file '
                            'or directory')
    phase.add_argument('--embed', action='store_true',
                       help='(Re)insert markers into scene files from the plan')
    phase.add_argument('--diagnose', action='store_true',
                       help='Read-only plan health report + render order')
    phase.add_argument('--review', action='store_true',
                       help='Write the whole-sequence continuity checklist')
    phase.add_argument('--state', action='store_true',
                       help='Write the visual-state transition log — what '
                            'changes on schedule, as opposed to the canon tier '
                            'for what must never change')
    phase.add_argument('--audit', action='store_true',
                       help='Read the prose against the state matrix and report '
                            'contradictions. Read-only.')

    parser.add_argument('--count', type=int, default=None,
                        help='Target illustration count for --plan '
                             '(default: recommended from book length)')
    parser.add_argument('--ids', type=str, default=None,
                        help='Comma-separated illustration ids to limit '
                             '--prompts or --embed to')
    parser.add_argument('--no-prior-refs', action='store_true',
                        help='For --prompts: reference the cover only, never '
                             'prior ingested illustrations. Use when '
                             're-rendering a set whose existing art no longer '
                             'matches the canon.')
    parser.add_argument('--coaching', choices=['full', 'coach', 'strict'],
                        default=None,
                        help='Override coaching level (default: project setting)')
    parser.add_argument('--dry-run', action='store_true',
                        help='Print what would happen without calling the LLM '
                             'or writing files')
    return parser.parse_args(argv)


def main(argv=None):
    args = parse_args(argv if argv is not None else sys.argv[1:])
    install_signal_handlers()
    project_dir = detect_project_root()

    medium = get_medium(project_dir) or 'novel'
    if medium == 'graphic-novel':
        log('ERROR: `illustrate` is for prose books. Graphic-novel projects '
            'use the page pipeline instead: `storyforge elaborate --stage '
            'page-architecture` and `--stage prompts`.')
        return 1

    coaching = args.coaching or get_coaching_level(project_dir)

    if args.export:
        # Retired in #306, kept for one version as a sentence rather than a bare
        # argparse "unrecognized argument". The export's per-illustration file
        # now lives in the packet as `image-prompts/<id>.md`, and its reference
        # copies are gone: every unit held the same four images, so a
        # twenty-illustration book spent 167 MB carrying 9 MB of distinct bytes.
        log('ERROR: --export was removed in 1.57.0. Its per-illustration upload '
            'file is now part of the packet: run `storyforge illustrate '
            '--package` and upload '
            f'{packet.PACKET_DIR}/{packet.IMAGE_PROMPTS_SUBDIR}/<id>.md. '
            'Reference images are listed in the packet README and uploaded from '
            'their project paths, never copied.')
        return 2

    phases = [args.direction, args.plan, args.prompts, bool(args.ingest),
              args.embed, args.diagnose, args.review, args.state, args.audit,
              args.package, args.sequence]
    if not any(phases):
        log('Nothing to do. Pick a phase: --direction, --plan, --sequence, '
            '--prompts, --package, --ingest PATH, --embed, --state, '
            '--audit, --diagnose, or --review.')
        return 1

    if args.diagnose:
        return run_diagnose(project_dir)

    exit_code = 0
    if args.direction:
        exit_code = run_direction(project_dir, coaching,
                                  args.dry_run) or exit_code
    if args.plan:
        exit_code = run_plan(project_dir, coaching, args.count,
                             args.dry_run) or exit_code
    if args.sequence:
        # Before --prompts, deliberately: the treatment is an input to the
        # art-direction request, so staging after prompting would leave every
        # prompt file built from the staging that did not exist yet.
        exit_code = run_sequence(project_dir, coaching,
                                 args.dry_run) or exit_code
    if args.prompts:
        exit_code = run_prompts(project_dir, coaching, _id_filter(args.ids),
                                args.dry_run,
                                no_prior_refs=args.no_prior_refs) or exit_code
    if args.package:
        # `--diagnose` owns the anchor-batch report when both are asked for.
        # Provably always True below while the early return above stands; see
        # `run_package`'s docstring for why it is wired anyway.
        exit_code = run_package(project_dir, args.dry_run,
                                report_batch=not args.diagnose) or exit_code
    if args.ingest:
        exit_code = run_ingest(project_dir, args.ingest,
                               args.dry_run) or exit_code
    if args.embed:
        exit_code = run_embed(project_dir, _id_filter(args.ids),
                              args.dry_run) or exit_code
    if args.state:
        exit_code = run_state(project_dir, coaching, args.dry_run) or exit_code
    if args.audit:
        exit_code = run_audit(project_dir, args.dry_run) or exit_code
    if args.review:
        exit_code = run_review(project_dir, args.dry_run) or exit_code
    return exit_code


def _id_filter(raw: str | None) -> set[str] | None:
    """Parse a --ids value into a set, or None when unfiltered.

    An all-whitespace or all-commas value yields no ids, which must mean
    "unfiltered" rather than "match nothing" — an empty set would silently
    filter every row away and report success having done nothing.
    """
    if not raw:
        return None
    return {part.strip() for part in raw.split(',') if part.strip()} or None


def _reference_tier_gaps(
        project_dir: str) -> tuple[list[str], list[str]]:
    """Split ill.missing_reference_sections into (absent, placeholder).

    The two need different fixes and different advice: an absent canon_id
    has no file at all, so `--direction` is exactly right for it; a
    placeholder one already exists as a TODO scaffold, so re-running
    `--direction` is a silent no-op (it never overwrites an existing file —
    see run_direction) and the real fix is editing the file directly.
    Conflating them told an author who had just run `--direction` to run it
    again, which is the milder recurrence of this task's own defect.
    """
    from storyforge import canon as canon_mod
    missing = ill.missing_reference_sections(project_dir)
    absent = [c for c in missing
              if canon_mod.resolve_canon_path(project_dir, c) is None]
    placeholder = [c for c in missing if c not in absent]
    return absent, placeholder


# ============================================================================
# --diagnose
# ============================================================================

def run_diagnose(project_dir: str) -> int:
    """Report plan state and every incoherence, without writing anything."""
    from storyforge import canon as canon_mod
    # One read of the canon tree for the whole report, threaded into every
    # consumer below, so an unparseable `canon_updated` is reported once rather
    # than once per consumer — which read as several broken files.
    canon_cutoff = canon_mod.newest_canon_updated(project_dir)
    rows = ill.read_plan(project_dir)
    if not rows:
        log('No illustration plan yet. Run `storyforge illustrate --plan` to '
            'propose one.')
        # The state rung *and its findings* are reported even with no plan: the
        # transition log is about the book, not about the illustrations, and the
        # skill now tells authors to build it before the plan. Returning 0 here
        # hid a `state_unknown_scene` error entirely.
        findings = ill.validate_plan(project_dir, canon_cutoff=canon_cutoff)
        _report_style_reference(project_dir, canon_cutoff=canon_cutoff)
        _report_state_rung(project_dir, findings)
        return _report_findings(findings)

    needs = packet.needs_render(project_dir, plan=rows,
                                canon_cutoff=canon_cutoff)
    report = ill.plan_report(project_dir, needs=needs)
    log(f'Illustration plan: {report["total"]} rows')
    for status in sorted(report['by_status']):
        log(f'  {status}: {report["by_status"][status]}')
    log(f'  embedded in scenes: {len(report["embedded"])}')
    if report['unembedded']:
        log(f'  not yet embedded: {", ".join(report["unembedded"])}')
    if report['next_unrendered']:
        log(f'  next to render: {report["next_unrendered"]}')

    absent_ref, placeholder_ref = _reference_tier_gaps(project_dir)
    if absent_ref or placeholder_ref:
        parts = []
        if absent_ref:
            parts.append(f'missing: {", ".join(absent_ref)} (run '
                         f'`storyforge illustrate --direction`)')
        if placeholder_ref:
            parts.append(f'unfilled: {", ".join(placeholder_ref)} (edit '
                         f'directly)')
        log(f'  reference tier incomplete — {"; ".join(parts)} — --prompts '
            f'will warn until these are filled')

    steps = ill.render_order(project_dir)
    if steps:
        log('Recommended render order:')
        for i, step in enumerate(steps, 1):
            # `~`, not `*`, for art the canon has outgrown: it is ingested, so
            # it ships, and it still has to be rendered again.
            mark = ('~' if needs.get(step['id'])
                    else ' ' if step['id'] in needs else '*')
            key = '  <- visual key' if step['is_visual_key'] else ''
            locks = (f'  locks: {", ".join(step["locks"])}'
                     if step['locks'] else '')
            log(f'  {mark} {i:2}. {step["id"]}{key}{locks}')
    findings = ill.validate_plan(project_dir, canon_cutoff=canon_cutoff)
    _report_canon_stale_renders(findings, len(rows))
    _report_anchor_batch(packet.anchor_batch(project_dir), needs)

    _report_style_reference(project_dir, canon_cutoff=canon_cutoff)
    _report_state_rung(project_dir, findings)
    _report_packet_rung(project_dir, findings, needs)
    return _report_findings(findings)


def _report_canon_stale_renders(
        findings: list[ill.IllustrationFinding], total: int) -> None:
    """Say how much of the set needs re-rendering, or that it could not be told.

    The whole-plan summary of what `_report_anchor_batch` says about four rows: a
    book can have twenty stale renders with none of them in the batch, and
    `--diagnose` is the health gate, so it has to be the place that says how much
    of the set needs redoing.

    **Silence here has to mean "checked, all current" and nothing else.** With no
    parseable `canon_updated` anywhere, nothing can be judged and every render
    reads as current — so `canon_staleness_unchecked` is surfaced first and
    separately, the way `--audit` renders "Not assessed" rather than "None
    found".

    Read off *findings* rather than recomputed from `needs`, following
    `_report_state_rung`: `validate_plan` has already produced one per row with
    its reason, and stating each reason here too made `--diagnose` say the same
    sentence five times for a four-row book — the noise pattern
    `_warn_unanchored_rows` fixed once already. This is the count; the findings
    list below is the itemisation.
    """
    for finding in findings:
        if finding['kind'] == 'canon_staleness_unchecked':
            log(f'  WARNING: {finding["detail"]}')
    stale = [f for f in findings if f['kind'] == 'canon_stale_render']
    if not stale:
        return
    log(f'  {len(stale)} of {total} illustration(s) predate the current canon '
        f'and need re-rendering — they still ship, but they are not usable '
        f'references for anything rendered now. Re-render and re-ingest them '
        f'(never demote `status`); see the findings below for each.')


def _report_style_reference(project_dir: str, *,
                            canon_cutoff: str | None = None) -> None:
    """Name the artwork setting the house style, and anything wrong with it.

    `--diagnose` is the health gate, and a stale, mis-declared, or absent style
    reference is a pure-function health fact about the most influential image in
    the book — free to compute, and previously reachable only by starting a run
    that spends money or opening the packet's README by hand.
    """
    style = resolve_style_reference(project_dir, canon_cutoff=canon_cutoff)
    headline = describe_style_reference(style)
    log(f'  {headline}' if headline else '  Style reference: none resolved')
    for warning in style_reference_warnings(style):
        log(f'  WARNING: {warning}')


def _report_findings(findings: list[ill.IllustrationFinding]) -> int:
    """Log every finding and return the exit code. 1 iff any is blocking.

    Warning-only findings are normal in-flight state (a drifted anchor after a
    revision, a file mid-rename), so they must not fail the command — matching
    how cmd_validate gates on `errors` alone.
    """
    if not findings:
        log('No problems found.')
        return 0

    errors = [f for f in findings if ill.severity_of(f['kind']) == 'error']
    log(f'{len(findings)} finding(s), {len(errors)} blocking:')
    for finding in findings:
        target = finding.get('id') or finding.get('file') or ''
        prefix = 'WARNING: ' if ill.severity_of(finding['kind']) == 'warning' else ''
        log(f'  {prefix}[{finding["kind"]}] {target}: {finding["detail"]}')
    return 1 if errors else 0


def _report_state_rung(project_dir: str,
                       findings: list[ill.IllustrationFinding]) -> None:
    """Log the visual-state and audit rungs, for `--diagnose`.

    Three questions, in the order the author acts on them: does the transition
    log exist, how much does it track, and does the audit still cover the prose.

    Staleness is read off *findings* rather than by calling `digest_drift` again:
    `validate_plan` has already run it, and hashing every audited scene twice per
    diagnose also printed each of its WARNING lines twice.
    """
    transitions = vs.read_transitions(project_dir)
    if not transitions:
        log('Visual state: no transition log. Run '
            '`storyforge illustrate --state` — canon covers what must never '
            'change, this covers what changes on schedule.')
        return

    tracked = sorted({t['entity'] for t in transitions})
    log(f'Visual state: {len(transitions)} transition(s) across '
        f'{len(tracked)} entity(ies) — {", ".join(tracked)}')

    provenance = vs.read_provenance(project_dir)
    if not provenance:
        log('  audit: never run. Run `storyforge illustrate --audit` to read '
            'the prose against the matrix.')
        return

    stale = [f['scene_id'] for f in findings if f['kind'] == 'audit_stale']
    last = max((p['audited_at'] for p in provenance if p['audited_at']),
               default='')
    covered = f'{len(provenance)} scene(s)'
    if stale:
        log(f'  audit: stale — last run {last or "(date not recorded)"} over '
            f'{covered}; {len(stale)} since revised: {", ".join(sorted(stale))}')
    else:
        log(f'  audit: current — last run {last or "(date not recorded)"} over '
            f'{covered}')


def _report_packet_rung(project_dir: str,
                        findings: list[ill.IllustrationFinding],
                        needs_render: packet.RenderNeeds) -> None:
    """Log the staging and packet rungs, for `--diagnose`.

    Read off `findings` rather than by re-running `packet_stale` and
    `anchor_copy_drift`: `validate_plan` has already run both, and computing
    them twice would print each of their WARNING lines twice — the defect
    `_report_state_rung` documents for `digest_drift`.
    """
    rows = packet.rows_in_reading_order(project_dir)
    if rows:
        staged = [r['id'].strip() for r in rows
                  if (r.get('treatment') or '').strip()]
        if len(staged) == len(rows):
            log(f'Sequence staging: all {len(rows)} illustration(s) carry a '
                f'treatment')
        else:
            log(f'Sequence staging: {len(staged)} of {len(rows)} '
                f'illustration(s) carry a treatment. Run `storyforge '
                f'illustrate --sequence` — an unstaged set converges on one '
                f'shot, because no generation call can see the others.')

    if not packet.is_built(project_dir):
        log('Packet: not built. Run `storyforge illustrate --package` to '
            'assemble the handoff bundle a generation session works from.')
        return

    stale = [f for f in findings if f['kind'] == 'packet_stale']
    drift = [f for f in findings if f['kind'] == 'anchor_copy_drift']
    state = 'stale' if stale else 'current'
    log(f'Packet: built and {state} — {packet.PACKET_DIR}/')
    if stale:
        log(f'  {stale[0]["detail"]}')
    if drift:
        log(f'  {len(drift)} anchor copy problem(s) — see the findings below. '
            f'Regenerate rather than editing the packet.')
    # "Ready to hand over" is a go/no-go on a paid render run, so it is derived
    # from `needs_render` rather than from `status`: a batch of four ingested
    # rows that all predated the canon reported ready, and a session trusting it
    # would have skipped phase 1 and run the churn against a cover-only
    # reference list (#300). Both messages can print — the mid-flight batch (some
    # rendered, then a canon edit) is the normal state, not an either/or.
    batch = packet.anchor_batch(project_dir)
    batch_ids = list(packet.slots_by_id(batch))
    pending = sorted(packet.ids_in_state(needs_render, 'pending', batch_ids))
    stale = sorted(packet.ids_in_state(needs_render, 'stale', batch_ids))
    if pending:
        log(f'  anchor batch: {len(pending)} row(s) not yet ingested '
            f'({", ".join(pending)}) — render and ingest those before handing '
            f'the packet over, so the churn has real references.')
    if stale:
        log(f'  anchor batch: {len(stale)} row(s) are ingested but predate the '
            f'current canon ({", ".join(stale)}) — re-render and re-ingest '
            f'those. `--prompts` already excludes pre-canon renders from the '
            f'reference chain, so leaving them is what makes the churn '
            f'reference nothing but the cover.')
    if not pending and not stale:
        log('  anchor batch: every row is ingested from the current canon — '
            'the packet is ready to hand over.')


# ============================================================================
# --direction
# ============================================================================

def run_direction(project_dir: str, coaching: CoachingLevel,
                  dry_run: bool) -> int:
    """Write the book-level and continuity-anchor canon files.

    One file per `pi.CANON_PLAN` entry plus one per continuity-anchor
    candidate from the character/location registries. A canon_id that
    already resolves anywhere in reference/canon/ is left alone — a rendered
    illustration may already depend on its exact text, the same discipline
    `append_anchor_stubs` uses.
    """
    from storyforge import canon

    plan: list[tuple[str, str, str]] = list(pi.CANON_PLAN)
    for canon_id, canon_type, name in _anchor_candidates(project_dir):
        plan.append((canon_id, canon_type,
                     f'A continuity anchor for {name}, reused verbatim in '
                     f'every prompt that shows {name}. Include measurable '
                     f'facts: height, age, exact colors, specific garments '
                     f'(or exact materials and layout for a place).'))

    rel_dir = canon.CANON_DIR

    if dry_run:
        log(f'[dry-run] would write up to {len(plan)} canon file(s) under '
            f'{rel_dir}/')
        return 0

    existing_ids = canon.canon_id_index(project_dir)
    to_write: list[tuple[str, str, str, str]] = []
    for canon_id, canon_type, purpose in plan:
        rel_path = pi.canon_rel_path(canon_type, canon_id)
        if canon_id in existing_ids:
            existing_rel = existing_ids[canon_id]
            if existing_rel == rel_path:
                # The plain steady-state skip: a re-run finds the file it
                # would have written already sitting exactly where expected.
                # This is the common case on every run after the first, so
                # it is not a WARNING — only a mismatch below (a different
                # path claiming this id) or a malformed file at the
                # candidate path (below that) indicates a real problem.
                log(f'{rel_path} already exists; left alone rather than '
                    f'risk overwriting it')
            else:
                log(f'WARNING: canon_id {canon_id!r} already exists at '
                    f'{existing_rel} (expected {rel_path}); left alone '
                    f'rather than risk overwriting or shadowing it')
            continue
        path = os.path.join(project_dir, rel_path)
        if os.path.exists(path):
            # canon_id_index only sees files whose frontmatter it could parse
            # a canon_id out of — a malformed file sitting at this exact
            # path is invisible to it, so this second check is not
            # redundant (same two-check discipline as append_anchor_stubs).
            log(f'WARNING: {rel_path} already exists at that path; left '
                f'alone rather than overwrite it')
            continue
        to_write.append((canon_id, canon_type, purpose, rel_path))

    book_level_ids = {c for c, _t, _p in pi.CANON_PLAN}
    filled: dict[str, str] = {}
    if coaching == 'full':
        needs_fill = [c for c, _t, _p, _r in to_write if c in book_level_ids]
        if needs_fill:
            if not os.environ.get('ANTHROPIC_API_KEY'):
                log('ERROR: ANTHROPIC_API_KEY is not set. Drafting art '
                    'direction in full coaching requires an API key. Set it '
                    'and re-run, or use --coaching coach for a template to '
                    'fill in yourself.')
                return 1
            prompt = pi.build_canon_direction_request(
                title=read_yaml_field('project.title', project_dir)
                or 'Untitled',
                genre=read_yaml_field('project.genre', project_dir) or '',
                audience=read_yaml_field('project.audience', project_dir)
                or '',
                canon_context=_canon_context(project_dir),
                story_context=_story_context(project_dir),
            )
            body = _invoke(project_dir, prompt, 'illustrate-direction',
                           task_type='synthesis', max_tokens=4096)
            if not body:
                log('ERROR: no response from the API.')
                return 1
            filled = pi.parse_canon_direction_response(body)

    for canon_id, canon_type, purpose, rel_path in to_write:
        body = filled.get(canon_id)
        if body:
            content = pi.render_filled_canon(
                canon_id=canon_id, canon_type=canon_type, body=body)
        else:
            content = pi.render_canon_template(
                canon_id=canon_id, canon_type=canon_type, purpose=purpose,
                coaching=coaching)
        path = os.path.join(project_dir, rel_path)
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, 'w', encoding='utf-8') as f:
            f.write(content)
        log(f'Wrote {rel_path}')

    # Resolve every plan entry — written this run OR already on disk from an
    # earlier run — to its real path, so the placeholder check below covers
    # the whole reference tier rather than only what this run happened to
    # write. A canon_id skipped as malformed-at-candidate-path has no
    # resolvable path and is left out; that case is already flagged above.
    resolved_paths: dict[str, str] = {
        canon_id: existing_ids[canon_id]
        for canon_id, _canon_type, _purpose in plan
        if canon_id in existing_ids
    }
    resolved_paths.update(
        (canon_id, rel_path)
        for canon_id, _canon_type, _purpose, rel_path in to_write
    )

    # canon._section_body_is_placeholder is the same TODO-detection rule
    # anchor_texts and is_canon_block_populated use — a file that is still
    # TODO scaffolding, whether written just now or left over from an
    # earlier run, must be reported every time, not just the run that wrote
    # it — a later no-op re-run over an all-placeholder reference tier must
    # not read as an all-clear.
    needs_input = [
        resolved_paths[canon_id] for canon_id, _canon_type, _purpose in plan
        if canon_id in resolved_paths
        and canon._section_body_is_placeholder(
            canon.embeddable_block_text(
                os.path.join(project_dir, resolved_paths[canon_id])) or '')
    ]
    if not to_write and not needs_input:
        log(f'Every canon file already exists under {rel_dir}/. Edit them '
            f'directly, or delete one to regenerate it.')
    if needs_input:
        log(f'  needs your input: {", ".join(needs_input)}')
    if coaching == 'full':
        log('Read the canon files before running --prompts — every '
            'illustration inherits whatever is in there, including anything '
            'it got wrong.')
    return 0


def _anchor_candidates(project_dir: str) -> list[tuple[str, str, str]]:
    """Suggest continuity-anchor canon files to stub, from the project's
    registries. Returns (canon_id, canon_type, display_name) tuples.

    Characters and locations come from their registries; both matter because
    art has to keep a place consistent as much as a face. The author adds
    creatures and signature props the registries don't model. Uses each
    registry row's own `id` — not a re-slugified name — so the stub's
    filename always matches the id `canon_missing_registry_entry` cross-checks
    against.
    """
    entities: list[tuple[str, str, str]] = []
    seen: set[str] = set()
    for filename, canon_type, limit in (
        ('characters.csv', 'character', 12),
        ('locations.csv', 'location', 6),
    ):
        rows = ill._read_ref_csv(project_dir, filename)
        for row in rows[:limit]:
            canon_id = (row.get('id') or '').strip()
            if not canon_id:
                log(f'WARNING: a row in {filename} has no id; skipped as a '
                    f'continuity-anchor candidate (the canon filename must '
                    f'equal the registry id)')
                continue
            name = (row.get('name') or canon_id).strip()
            if canon_id not in seen:
                seen.add(canon_id)
                entities.append((canon_id, canon_type, name))
    return entities


# ============================================================================
# --review
# ============================================================================

def run_review(project_dir: str, dry_run: bool) -> int:
    """Write the whole-sequence continuity review checklist."""
    steps = ill.render_order(project_dir)
    if not steps:
        log('No illustration plan to review. Run `--plan` first.')
        return 1

    rel = os.path.join('working', 'illustration-sequence-review.md')
    if dry_run:
        log(f'[dry-run] would write {rel} ({len(steps)} illustration(s))')
        return 0

    content = pi.render_sequence_review(
        title=read_yaml_field('project.title', project_dir) or 'Untitled',
        steps=steps,
        anchors=pi.anchors_for_prompt(project_dir),
        direction=pi.book_level_direction(project_dir),
    )
    path = os.path.join(project_dir, rel)
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, 'w', encoding='utf-8') as f:
        f.write(content)

    rendered = sum(1 for s in steps if s['status'] == 'ingested')
    log(f'Wrote {rel} — {rendered} of {len(steps)} rendered')
    if rendered < len(steps):
        log('Reviewing before the set is complete is the cheap moment: every '
            'later illustration references the earlier ones.')
    return 0


# ============================================================================
# --state
# ============================================================================

#: Per-scene prose cap for the state-proposal prompt. The pass reads the whole
#: book once, so the cap is what keeps a 90-scene novel inside one call.
_STATE_SCENE_CHARS = 3000


def run_state(project_dir: str, coaching: CoachingLevel,
              dry_run: bool) -> int:
    """Write the visual-state transition log. Output depends on coaching level.

    - `full` — one LLM call proposes transitions from the prose, each with its
      evidence quote. Written to the CSV with **existing rows preserved**: a
      transition the author wrote is an authorial decision about the book, and
      the model has no standing to revise it.
    - `coach` — a brief of per-entity questions. No API call; see
      `pi.render_state_brief` for why proposing here would be the creative work
      itself rather than a surfacing of it.
    - `strict` — a constraint checklist plus the CSV itself (header, existing
      rows), so the author has a file to fill in. No API call.
    """
    existing = vs.read_transitions(project_dir)
    hints = _state_entity_hints(project_dir)
    order = ill._scene_order(project_dir)
    scene_ids = [sid for sid, _pos in sorted(order.items(),
                                             key=lambda kv: (kv[1], kv[0]))]

    log(f'Visual state: {len(existing)} transition(s) across '
        f'{len({r["entity"] for r in existing})} entity(ies); '
        f'{len(scene_ids)} scene(s) in reading order; '
        f'{len(hints)} candidate entity(ies) from canon and the registries')

    if coaching == 'strict':
        # Strict may do structural and file work — it may not propose content, and
        # it must not touch a file the author is already keeping. Writing the
        # header only when the log does not exist gives the author the file the
        # checklist describes; rewriting an existing one through read/write would
        # silently drop any row with an empty `entity` and any column the author
        # added beyond STATE_COLUMNS.
        if not dry_run and not os.path.isfile(vs.state_path(project_dir)):
            vs.write_transitions(project_dir, [])
            log(f'Wrote {vs.STATE_FILE} (header only — fill it in)')
        elif not dry_run:
            log(f'{vs.STATE_FILE} already exists ({len(existing)} row(s)) — '
                f'left untouched')
        return _write_coaching_file(
            project_dir, 'visual-state-checklist.md',
            pi.render_state_checklist(hints=hints, existing=existing,
                                      scene_ids=scene_ids),
            dry_run,
        )

    if coaching == 'coach':
        return _write_coaching_file(
            project_dir, 'visual-state-brief.md',
            pi.render_state_brief(hints=hints, existing=existing,
                                  scene_ids=scene_ids),
            dry_run,
        )

    if dry_run:
        log(f'[dry-run] would propose transitions from {len(scene_ids)} scene(s) '
            f'(coaching={coaching})')
        return 0

    if not os.environ.get('ANTHROPIC_API_KEY'):
        log('ERROR: ANTHROPIC_API_KEY is not set. Proposing transitions in '
            f'{coaching} coaching requires an API key. Set it and re-run, or '
            'use --dry-run / --coaching coach / --coaching strict.')
        return 1

    prose, read_count = _state_scene_prose(project_dir, scene_ids)
    if not read_count:
        log('No drafted scenes to read. Transitions are extracted from prose, '
            'so there is nothing to propose yet.')
        return 1
    log(f'Reading {read_count} of {len(scene_ids)} scene(s), capped at '
        f'{_STATE_SCENE_CHARS} characters each')

    prompt = pi.build_state_request(
        story_context=_story_context(project_dir), scene_prose=prose,
        hints=hints, existing=existing, coaching=coaching,
    )
    text = _invoke(project_dir, prompt, 'illustrate-state',
                   task_type='synthesis', max_tokens=8192)
    if not text:
        log('ERROR: no response from the API.')
        return 1

    proposed, status = pi.parse_state_response(text)
    if status == 'empty':
        # A model that read the book and found nothing whose visible state
        # changes is answering, not failing. Reporting it as a parse error told
        # the author their response was unreadable and exited non-zero.
        log('The model proposed no transitions — it found nothing whose visible '
            'state changes. Nothing was written.')
        return 0
    if status != 'ok':
        log(f'ERROR: could not parse transitions from the response ({status}).')
        return 1
    log(f'Received {len(proposed)} proposed transition(s)')

    merged, added = _merge_transitions(project_dir, existing, proposed)
    vs.write_transitions(project_dir, merged)
    log(f'Wrote {vs.STATE_FILE} — {len(existing)} kept, {added} added')

    findings = [f for f in vs.prepass(project_dir)['findings']
                if f['kind'] in ('state_unknown_scene', 'state_unmapped_scene',
                                 'evidence_not_found')]
    if findings:
        log(f'WARNING: {len(findings)} transition(s) need attention:')
        for finding in findings:
            log(f'  [{finding["kind"]}] {finding.get("id", "")}: '
                f'{finding["detail"]}')
    return 0


def _merge_transitions(
    project_dir: str,
    existing: list[vs.Transition],
    proposed: list[dict[str, str]],
) -> tuple[list[vs.Transition], int]:
    """Append proposals the log does not already cover, preserving every row.

    Keyed on `(entity, from_scene)`. Existing rows keep their order and their
    text — never revise a transition the author wrote — and new rows are
    appended after them. Row order is not resolution order (that comes from the
    chapter map), but it *is* the tiebreak between two transitions at one scene,
    so appending rather than interleaving keeps existing resolutions stable.

    A proposal naming a scene that does not exist is **refused**, not written and
    then warned about. That row is the model's, not the author's, so the
    never-revise-author-text rule does not protect it — and writing it would put
    a `state_unknown_scene` error into the log on purpose, which this command
    then reports and exits 0 on.
    """
    known = vs.known_scene_ids(project_dir)
    seen = {(row['entity'], row['from_scene']) for row in existing}
    merged: list[vs.Transition] = list(existing)
    added = 0
    for row in proposed:
        key = (row['entity'], row['from_scene'])
        if key in seen:
            log(f'  keeping the recorded state for {row["entity"]!r} at '
                f'{row["from_scene"]} — the proposal was discarded')
            continue
        if row['from_scene'] not in known:
            log(f'WARNING: discarding the proposal for {row["entity"]!r} — '
                f'from_scene {row["from_scene"]!r} is not an active scene in '
                f'scenes.csv, so the transition would never apply')
            continue
        seen.add(key)
        merged.append({
            'entity': _sanitize_cell(row['entity']),
            'from_scene': _sanitize_cell(row['from_scene']),
            'state': _sanitize_cell(row['state']),
            'evidence': _sanitize_cell(row['evidence']),
        })
        added += 1
    return merged, added


def _state_entity_hints(project_dir: str) -> list[pi.EntityHint]:
    """Candidate tracked entities, from the canon tier then the registries.

    Canon first because a canon file is the strongest statement that an entity
    matters to the art, and because its `canon_id` is the slug the log must
    match. Registry rows fill in entities that have no canon file yet.
    """
    from storyforge import canon as canon_mod

    hints: list[pi.EntityHint] = []
    seen: set[str] = set()

    for canon_id, label in sorted(
            canon_mod.anchor_display_names(project_dir).items()):
        seen.add(canon_id)
        hints.append({'canon_id': canon_id, 'label': label['label'],
                      'source': 'canon'})

    for filename, source in (('characters.csv', 'characters.csv'),
                             ('locations.csv', 'locations.csv'),
                             ('motif-taxonomy.csv', 'motif-taxonomy.csv')):
        for row in ill._read_ref_csv(project_dir, filename):
            canon_id = (row.get('id') or '').strip()
            if not canon_id or canon_id in seen:
                continue
            seen.add(canon_id)
            hints.append({'canon_id': canon_id,
                          'label': (row.get('name') or canon_id).strip(),
                          'source': source})
    return hints


def _state_scene_prose(project_dir: str,
                       scene_ids: list[str]) -> tuple[str, int]:
    """Assemble the prose the state pass reads, and how many scenes it found.

    Markers are stripped — a marker is not prose, and the model would otherwise
    be invited to quote one as evidence. An undrafted scene is skipped with a log
    line rather than sent as an empty block, which would read to the model as a
    scene in which nothing is visible.
    """
    blocks: list[str] = []
    found = 0
    for scene_id in scene_ids:
        text = ill._read_scene(project_dir, scene_id)
        if text is None:
            log(f'  {scene_id} has no file in scenes/ — not read')
            continue
        found += 1
        prose = ill.strip_markers(text).strip()[:_STATE_SCENE_CHARS]
        blocks.append(f'### `{scene_id}`\n\n{prose}')
    return '\n\n'.join(blocks), found


# ============================================================================
# --audit
# ============================================================================

#: Per-scene prose cap for the audit prompt. A contradiction can sit anywhere in
#: a scene, so truncating is how a real finding gets missed — which is why this
#: is well above any plausible scene (the templates target 80,000 words at
#: 1,500-2,000 words per scene, so ~7,000-11,000 characters is typical and 24,000
#: covers a 4,000-word outlier) and why a scene that still exceeds it is named in
#: the report and kept out of the provenance file. Silent truncation would let
#: the report claim coverage it does not have, and the only product of this pass
#: is trust.
_AUDIT_SCENE_CHARS = 24000

AUDIT_REPORT_FILE = os.path.join('working', 'illustration-contradictions.md')


def run_audit(project_dir: str, dry_run: bool) -> int:
    """Read the prose against the state matrix and report contradictions.

    Read-only with respect to the prose and the log: it writes a report and a
    provenance file, and nothing else. An audit that edits prose is a far worse
    bug than one that misses a contradiction.

    Cost discipline: no deterministic findings **and** no candidate scenes means
    no LLM call, and the report says so rather than implying a clean pass.
    """
    prepass = vs.prepass(project_dir)
    findings = prepass['findings']
    candidates = prepass['candidate_scenes']
    transitions = vs.read_transitions(project_dir)

    log(f'Audit pre-pass: selected {len(candidates)} of '
        f'{prepass["scene_count"]} scenes as candidates across '
        f'{len(prepass["tracked_entities"])} tracked entities; '
        f'{len(findings)} deterministic finding(s)')
    for entity, terms in sorted(prepass['search_terms'].items()):
        log(f'  {entity}: matched on {", ".join(repr(t) for t in terms)}')
    if prepass['undrafted_scenes']:
        log(f'  {len(prepass["undrafted_scenes"])} scene(s) have no file in '
            f'scenes/ and were not read: '
            f'{", ".join(prepass["undrafted_scenes"])}')
    if prepass['unmapped_scenes']:
        log(f'WARNING: {len(prepass["unmapped_scenes"])} drafted scene(s) are '
            f'absent from the chapter map, so they have no reading position and '
            f'this audit never examines them: '
            f'{", ".join(prepass["unmapped_scenes"])}. Add them to '
            f'reference/chapter-map.csv and re-run.')

    if dry_run:
        log(f'[dry-run] would audit {len(candidates)} scene(s) and write '
            f'{AUDIT_REPORT_FILE}')
        return 0

    contradictions: list[dict[str, str]] = []
    skipped = _audit_skip_reason(transitions, findings, candidates)
    scenes_read: list[str] = []
    truncated: list[str] = []
    dropped = 0

    if skipped:
        log(f'No contradiction pass: {skipped}')
    else:
        prose, scenes_read, truncated = _audit_scene_prose(project_dir,
                                                           candidates)
        if not scenes_read:
            skipped = ('Every candidate scene turned out to have no file in '
                       '`scenes/`, so there was no prose to read.')
            log(f'No contradiction pass: {skipped}')
        elif not os.environ.get('ANTHROPIC_API_KEY'):
            log('ERROR: ANTHROPIC_API_KEY is not set. The contradiction pass '
                'needs it. Set it and re-run, or use --dry-run.')
            return 1
        else:
            contradictions, skipped, dropped = _audit_llm_pass(
                project_dir, transitions, scenes_read, prose)
            if skipped == '__error__':
                return _write_audit_failure(
                    project_dir,
                    'The model\'s response could not be read, so no findings '
                    'were recorded.')

    report = pi.render_audit_report(
        title=read_yaml_field('project.title', project_dir) or 'Untitled',
        transitions=transitions, findings=findings,
        contradictions=contradictions, scenes_read=scenes_read,
        scene_count=prepass['scene_count'],
        tracked_entities=prepass['tracked_entities'],
        undrafted_scenes=prepass['undrafted_scenes'],
        llm_skipped_reason=skipped,
        truncated_scenes=truncated,
        unmapped_scenes=prepass['unmapped_scenes'],
        dropped_rows=dropped,
    )
    path = os.path.join(project_dir, AUDIT_REPORT_FILE)
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, 'w', encoding='utf-8') as f:
        f.write(report)
    log(f'Wrote {AUDIT_REPORT_FILE} — {len(contradictions)} contradiction(s), '
        f'{len(findings)} deterministic finding(s)')
    if dropped:
        log(f'WARNING: {dropped} row(s) the model returned could not be read '
            f'and are not in the report\'s findings list — the report says so '
            f'under Coverage.')

    # Provenance covers exactly the scenes whose prose was read **in full**.
    # Recording a scene the pass never read would make a later run report it as
    # audited; recording a *truncated* one is the same lie with a longer fuse,
    # because the digest covers the whole scene, so the unread tail could never
    # come back as `audit_stale`.
    fully_read = [s for s in scenes_read if s not in set(truncated)]
    if fully_read:
        today = date.today().isoformat()
        vs.write_provenance(project_dir, [
            {'scene_id': scene_id,
             'digest': ill.scene_prose_digest(project_dir, scene_id),
             'audited_at': today}
            for scene_id in fully_read
        ])
        log(f'Wrote {vs.PROVENANCE_FILE} — {len(fully_read)} scene(s)')
    if truncated:
        log(f'WARNING: {len(truncated)} scene(s) were read only in part and are '
            f'not recorded as audited: {", ".join(truncated)}')
    return 0


def _audit_skip_reason(transitions: list[vs.Transition],
                       findings: list[dict],
                       candidates: list[str]) -> str:
    """Why no LLM call is warranted, or '' when one is. Author-facing prose.

    Every branch must be true of the run it describes. Having deterministic
    findings does not give a model anything to read, so the no-candidates case is
    a skip either way — it just reports differently, because "we found problems
    and called nothing" and "we found nothing at all" are different states.
    """
    if not transitions:
        return ('There is no visual-state log yet, so there is nothing for the '
                'prose to contradict. Run `storyforge illustrate --state` '
                'first.')
    if not candidates:
        if findings:
            return (f'No scene sits inside a tracked entity\'s span while '
                    f'mentioning it, so there was no prose for a model to read. '
                    f'The {len(findings)} deterministic finding(s) below still '
                    f'stand — fix those and re-run.')
        return ('The pre-pass found no problems and no scene sits inside a '
                'tracked entity\'s span while mentioning it, so no scene could '
                'disagree with the log. No model was called.')
    return ''


def _write_audit_failure(project_dir: str, reason: str) -> int:
    """Replace the report with a failure stub and return exit code 1.

    Not "write nothing": a report left over from an earlier run would say
    "None found" under a stale date while looking like the latest result.
    """
    path = os.path.join(project_dir, AUDIT_REPORT_FILE)
    os.makedirs(os.path.dirname(path), exist_ok=True)
    existed = os.path.isfile(path)
    with open(path, 'w', encoding='utf-8') as f:
        f.write(pi.render_audit_failure(reason))
    log(f'{"Replaced" if existed else "Wrote"} {AUDIT_REPORT_FILE} with a '
        f'failure stub — no findings were recorded'
        + (', and the previous report was removed so it cannot be read as this '
           'run\'s result' if existed else ''))
    return 1


def _audit_llm_pass(project_dir: str, transitions: list[vs.Transition],
                    scenes_read: list[str],
                    prose: str) -> tuple[list[dict[str, str]], str, int]:
    """Run the one contradiction call.

    Returns `(contradictions, skip_reason, dropped)`. A skip reason of
    `'__error__'` means the caller must fail rather than write a report that
    would read as a clean pass; `dropped` counts rows the model returned that
    could not be read, which the *report* has to disclose — stdout is not enough
    when the skill tells the author to read the report first. Sonnet, not Opus:
    this is analytical reading against a table, not creative work.
    """
    order = ill._scene_order(project_dir)
    resolved = [(scene_id, vs._resolve(order, transitions, order[scene_id]))
                for scene_id in scenes_read if scene_id in order]

    prompt = pi.build_audit_request(
        story_context=_story_context(project_dir),
        transitions=transitions, resolved_by_scene=resolved, scene_prose=prose,
    )
    text = _invoke(project_dir, prompt, 'illustrate-audit',
                   task_type='evaluator', max_tokens=8192)
    if not text:
        log('ERROR: no response from the API. No findings were recorded — an '
            'empty report would read as a clean audit.')
        return [], '__error__', 0

    contradictions, status, dropped = pi.parse_audit_response(text)
    if status in ('no_json', 'unusable'):
        # 'unusable' means the model *did* find contradictions and every row was
        # malformed. Writing a report then would affirm agreement, which is the
        # exact opposite of what the response said.
        log(f'ERROR: the audit response could not be used ({status}). No '
            f'findings were recorded — an empty report would read as a clean '
            f'audit.')
        return [], '__error__', dropped
    log(f'Contradiction pass returned {len(contradictions)} finding(s)'
        + (f'; {dropped} further row(s) could not be read' if dropped else ''))
    return contradictions, '', dropped


def _audit_scene_prose(
    project_dir: str, scene_ids: list[str],
) -> tuple[str, list[str], list[str]]:
    """Assemble the candidate prose, the scenes read, and the ones cut short.

    Markers are stripped: the model is asked to quote the scene verbatim, and a
    marker is not prose the author can find by searching the manuscript.

    Truncation is reported, never silent. The scene text is what the whole pass
    is checking, so a cap that quietly removes the second half of a scene turns
    "no contradictions found" into a claim the run cannot support.
    """
    blocks: list[str] = []
    read: list[str] = []
    truncated: list[str] = []
    for scene_id in scene_ids:
        text = ill._read_scene(project_dir, scene_id)
        if text is None:
            log(f'  {scene_id} has no file in scenes/ — not read')
            continue
        read.append(scene_id)
        prose = ill.strip_markers(text).strip()
        if len(prose) > _AUDIT_SCENE_CHARS:
            truncated.append(scene_id)
            log(f'WARNING: {scene_id} is {len(prose)} characters; only the '
                f'first {_AUDIT_SCENE_CHARS} were sent. A contradiction in the '
                f'remaining {len(prose) - _AUDIT_SCENE_CHARS} will not be '
                f'found, and the scene is not recorded as audited.')
            prose = prose[:_AUDIT_SCENE_CHARS]
        blocks.append(f'### `{scene_id}`\n\n{prose}')
    return '\n\n'.join(blocks), read, truncated


# ============================================================================
# --plan
# ============================================================================

def run_plan(project_dir: str, coaching: CoachingLevel, count: int | None,
             dry_run: bool) -> int:
    """Propose illustration moments. Output depends on coaching level."""
    prepass = ill.selection_prepass(project_dir)
    target = count if count and count > 0 else prepass['recommended_count']

    log(f'Pre-pass: {prepass["scene_count"]} scenes, '
        f'{prepass["chapter_count"]} chapters, '
        f'{prepass["planned_count"]} already planned; '
        f'recommending {target} illustrations')
    log(f'  uncovered spine events: {len(prepass["uncovered_spine_events"])}')
    log(f'  turning-point scenes: {len(prepass["turning_point_scenes"])}')
    log(f'  motif payoffs: {len(prepass["motif_payoffs"])}')
    if prepass['uncovered_chapters']:
        log(f'  chapters with no illustration: '
            f'{", ".join(prepass["uncovered_chapters"])}')

    if coaching == 'strict':
        return _write_coaching_file(
            project_dir, 'illustration-checklist.md',
            pi.render_strict_checklist(prepass=prepass, target_count=target),
            dry_run,
        )

    if ill.prepass_is_empty(prepass) and prepass['planned_count'] > 0:
        log('Pre-pass found no gaps and the plan is already populated — '
            'skipping the LLM pass. Use --count to plan more anyway.')
        return 0

    if dry_run:
        log(f'[dry-run] would propose {target} illustrations '
            f'(coaching={coaching})')
        return 0

    if not os.environ.get('ANTHROPIC_API_KEY'):
        log('ERROR: ANTHROPIC_API_KEY is not set. Planning in '
            f'{coaching} coaching requires an API key. Set it and re-run, or '
            'use --dry-run / --coaching strict.')
        return 1

    prompt = pi.build_selection_prompt(
        prepass=prepass, target_count=target,
        story_context=_story_context(project_dir), coaching=coaching,
    )
    text = _invoke(project_dir, prompt, 'illustrate-plan',
                   task_type='synthesis', max_tokens=8192)
    if not text:
        log('ERROR: no response from the API.')
        return 1

    proposals, status = pi.parse_selection_response(text)
    if status != 'ok':
        log(f'ERROR: could not parse proposals from the response ({status}).')
        return 1
    log(f'Received {len(proposals)} proposal(s)')

    if coaching == 'coach':
        brief = pi.render_coach_brief(prepass=prepass, target_count=target)
        brief += '\n## Candidates\n\n' + _format_proposals(proposals) + '\n'
        return _write_coaching_file(project_dir, 'illustration-brief.md',
                                    brief, dry_run)

    written = _merge_proposals(project_dir, proposals)
    log(f'Wrote {written} row(s) to reference/{ill.PLAN_FILENAME}')

    findings = [f for f in ill.validate_plan(project_dir)
                if f['kind'] in ('anchor_drift', 'anchor_ambiguous',
                                 'unknown_scene', 'missing_scene')]
    if findings:
        log(f'WARNING: {len(findings)} proposed row(s) need attention before '
            f'embedding:')
        for finding in findings:
            log(f'  [{finding["kind"]}] {finding.get("id", "")}: '
                f'{finding["detail"]}')
    return 0


def _merge_proposals(project_dir: str, proposals: list[dict]) -> int:
    """Merge LLM proposals into the plan CSV without clobbering author edits."""
    incoming = []
    for proposal in proposals:
        row = ill.blank_row(_slugify(str(proposal.get('id', ''))))
        for col in ill.PLAN_COLUMNS:
            # `id` is already slugified above — copying the raw proposal value
            # over it would let a title-cased id like "Lantern Vigil" through,
            # and the id is the marker key and the Bookshelf asset key.
            if col == 'id':
                continue
            val = proposal.get(col)
            if val:
                row[col] = _sanitize_cell(str(val))
        # `avoid` is real art direction the model was asked for, but the plan
        # has no column for it — fold it into the rationale rather than drop it.
        avoid = str(proposal.get('avoid', '')).strip()
        if avoid:
            row['rationale'] = (
                f'{row.get("rationale", "")} Must not show: {avoid}'.strip()
            )
            row['rationale'] = _sanitize_cell(row['rationale'])
        if not row.get('placement'):
            row['placement'] = 'after_anchor'
        row['status'] = 'planned'
        incoming.append(row)

    merged = ill.upsert_rows(ill.read_plan(project_dir), incoming)
    ill.write_plan(project_dir, merged)
    return len(incoming)


def _format_proposals(proposals: list[dict]) -> str:
    """Render proposals as a readable list for a coaching brief."""
    lines = []
    for proposal in proposals:
        lines.append(f'### {proposal.get("id", "(no id)")}')
        lines.append('')
        lines.append(f'- **Scene:** `{proposal.get("scene_id", "")}`')
        for key in ('beat', 'rationale', 'subject', 'composition', 'palette',
                    'mood', 'avoid'):
            val = str(proposal.get(key, '')).strip()
            if val:
                lines.append(f'- **{key.replace("_", " ").title()}:** {val}')
        anchor = str(proposal.get('anchor', '')).strip()
        if anchor:
            lines.append(f'- **Anchor:** "{anchor}"')
        lines.append('')
    return '\n'.join(lines)


# ============================================================================
# --prompts
# ============================================================================

def run_prompts(project_dir: str, coaching: CoachingLevel,
                ids: set[str] | None, dry_run: bool,
                no_prior_refs: bool = False) -> int:
    """Write an art-direction prompt file per planned illustration.

    The API calls fan out (see `_PROMPT_WORKERS`); everything that writes —
    canon stubs, prompt files, plan rows — runs sequentially afterwards in
    plan order, so two rows proposing the same anchor cannot race on the same
    canon file and the log still reads top-to-bottom.
    """
    plan = ill.read_plan(project_dir)
    if ids is not None:
        # An explicit id list means "re-prompt these", which is what the skill
        # and the --ids help text both promise. Applying the status filter first
        # made an already-prompted row unreachable, so the hint told the author
        # to use the exact flag they had just used.
        #
        # A named `superseded` row is included, and re-prompting revives it as
        # far as `prompted` (see _status_after_prompt). Naming a retired row by
        # id is an unambiguous request to work on it; the unfiltered path below
        # still never touches one, so a bulk run cannot resurrect retired art.
        rows = [r for r in plan if r['id'].strip() in ids]
        unknown = ids - {r['id'].strip() for r in plan}
        if unknown:
            log(f'WARNING: --ids named {len(unknown)} illustration(s) with no '
                f'plan row: {", ".join(sorted(unknown))}. Nothing was written '
                f'for them.')
    else:
        rows = [r for r in plan
                if (r.get('status') or '').strip() in ('', 'planned')]

    if not rows:
        if ids is not None:
            log('None of the named ids match a plan row that can be prompted.')
            return 1
        log('No rows at status=planned need prompts. '
            '(Use --ids to re-prompt a specific illustration.)')
        return 0

    log(f'Writing art direction for {len(rows)} illustration(s)')

    absent, placeholder = _reference_tier_gaps(project_dir)
    if absent:
        log(f'WARNING: reference/canon/ is missing book-level file(s) for: '
            f'{", ".join(absent)} — these prompts will carry no house '
            f'style for them, and the illustrations will not look like '
            f'they belong to one book. Run `storyforge illustrate '
            f'--direction` first.')
    if placeholder:
        log(f'WARNING: reference/canon/ has unfilled book-level file(s) '
            f'for: {", ".join(placeholder)} — these already exist as '
            f'TODO scaffolds; edit them directly (re-running --direction '
            f'is a no-op once the files exist).')
    direction = pi.book_level_direction(project_dir)

    if coaching == 'strict':
        log('Coaching is strict — art direction is creative work. Writing the '
            'prompt scaffold with your constraints; fill in the four sections '
            'yourself (the Constraints section is appended for you).')

    needs_api = coaching in ('full', 'coach')

    # Everything below to the end of phase 1 is file reads. It runs before the
    # dry-run return on purpose: "which cover is about to direct twenty calls,
    # and which rows have no stated visual state?" are exactly the questions a
    # pre-flight mode exists to answer, and the mode that reported neither was
    # the one an author would reach for first.
    from storyforge import canon as canon_mod
    canon_cutoff = canon_mod.newest_canon_updated(project_dir)
    cutoff = _reference_cutoff(project_dir, no_prior_refs, canon_cutoff)
    # Resolved once for the run and logged before the fan-out (#299). The run's
    # own `canon_cutoff` is passed rather than recomputed, so the canon tree is
    # walked once and its unparseable-date WARNING logged once.
    style = resolve_style_reference(project_dir, canon_cutoff=canon_cutoff)
    headline = describe_style_reference(style)
    if headline:
        log(headline)
    for warning in style_reference_warnings(style):
        log(f'WARNING: {warning}')

    # Read once for the whole run. Every request is built before any call is
    # made, so a stub a later row's response proposes cannot reach the others
    # — which is exactly why _warn_unanchored_rows runs first, while the author
    # can still fix it for free.
    anchors = pi.anchors_for_prompt(project_dir)
    labels = _anchor_labels(project_dir)
    canon_ctx = _canon_context(project_dir)
    style_note = _style_note(project_dir)
    # Not gated on `needs_api`. A `canon_refs` entry with no anchor is a plan
    # defect whoever writes the prose, and strict coaching is where the author is
    # hand-authoring the direction and most needs to know. It was gated, and
    # `state_for_row`'s suppression of the same finding was not — so in strict the
    # accurate warning vanished and `state_unspecified` fired in its place,
    # telling the author to add a transition row when the fix is to author the
    # canon anchor.
    _warn_unanchored_rows(rows, anchors)
    if needs_api:
        _warn_truncated_anchors(project_dir)

    # Read once; resolved per row through the same function `--package` uses
    # (#297). The whole plan, never the --ids subset — see `state_context`.
    state_ctx = packet.state_context(project_dir, plan=plan)
    # Derived once and threaded into every row's reference list, for the reason
    # `style` and `cutoff` are: `_references_for` runs per row, and this reads the
    # plan, the chapter map, and the transition log (#311). Derived, never stored,
    # so the batch a prompt references is the batch `--diagnose` reports.
    #
    # Handed `state_ctx`'s own reads rather than repeating them: `read_transitions`
    # logs a WARNING per malformed row per read, so deriving the batch beside a
    # context that had already read the log reported one broken row twice.
    batch = packet.anchor_batch(project_dir, plan=plan,
                                order=state_ctx['order'],
                                transitions=state_ctx['transitions'])

    # Phase 1 — assemble every request. Sequential and cheap (file reads
    # only), which keeps the reference and anchor warnings in plan order.
    jobs: list[_PromptJob] = []
    state_gaps: dict[str, list[str]] = {}
    unpositioned: dict[ill.SplitCause, list[tuple[str, str]]] = {}
    at_scene_start: list[str] = []
    for row in rows:
        illus_id = row['id'].strip()
        # `include_anchor_gaps=False` because `_warn_unanchored_rows` above named
        # every canon_refs entry with no anchor — and it now runs at every
        # coaching level, which is what makes that true unconditionally.
        state, gaps = packet.state_for_row(row, context=state_ctx,
                                           include_anchor_gaps=False)
        for gap in gaps:
            # Collected, not logged here. One untracked entity across twenty rows
            # is twenty near-identical WARNINGs interleaved with the per-row
            # reference chatter, which is the log-skimming this command's own
            # de-dup rationale objects to. Grouped after the loop, the way
            # `_warn_unanchored_rows` does it — still before the fan-out, so the
            # free-fix moment is preserved.
            state_gaps.setdefault(gap, []).append(illus_id)
        absent_cell = (row.get('absent') or '').strip()
        contrast = packet.contrast_for_row(row, context=state_ctx)
        split = _scene_split(project_dir, row)
        if split['state'] == 'normal' and not split['read'].strip():
            # Positionally legitimate (a `before_anchor` anchored in the first
            # paragraph) but a poor request: nothing is read, so the model has only
            # the plan row's fields, and the prose it could otherwise draw on is the
            # beat the image was placed in front of. Almost always the author meant
            # `scene_open`. Reported rather than silently reclassified.
            at_scene_start.append(illus_id)
        if split['state'] == 'unknown':
            # Keyed on the named `cause`, never on `error`. Every error string
            # interpolates something row-specific — a match count, a placement
            # value, a scene id, an exception — so keying on the message produced
            # one group per row, which is `stale_render_reason`'s documented
            # mistake rebuilt by the choice of key.
            unpositioned.setdefault(split['cause'], []).append(
                (illus_id, split['error']))
        jobs.append({
            'id': illus_id,
            'row': row,
            'state': state,
            'absent': absent_cell,
            'contrast': contrast,
            'split': split,
            'references': _references_for(
                project_dir, illus_id, plan=plan, canon_cutoff=cutoff,
                no_prior_refs=no_prior_refs, style=style, batch=batch),
            'aspect': pi.aspect_for_row(row),
            'request': pi.build_art_direction_request(
                row=row,
                split=split,
                character_anchors=_relevant_anchors(anchors, row),
                canon_context=canon_ctx, direction=direction,
                style_note=style_note, anchor_labels=labels,
                state=state, absent=absent_cell, contrast=contrast,
            ) if needs_api else '',
        })

    for gap, ids in state_gaps.items():
        log(f'WARNING: {gap} ({len(ids)} illustration(s): '
            f'{", ".join(sorted(ids))})')
    if unpositioned:
        # Before the fan-out, with the other free-fix warnings. A row whose
        # position does not resolve gets no spoiler guard and no acceptance check
        # — the prompt says so, but the moment to fix it is now, not after paying
        # for the call (#308).
        total = sum(len(rows_) for rows_ in unpositioned.values())
        log(f'WARNING: {total} of {len(jobs)} illustration(s) have no resolvable '
            f'position in their scene, so the prose after them is unknown and '
            f'their prompts carry no spoiler guard.')
        for cause, entries in unpositioned.items():
            log(f'         {len(entries)}: {_UNPOSITIONED_FIXES[cause]}')
            for illus_id, reason in sorted(entries):
                log(f'           {illus_id} — {reason}')
    if at_scene_start:
        log(f'WARNING: {len(at_scene_start)} illustration(s) are anchored in their '
            f'scene\'s first paragraph, so no prose precedes them and the model '
            f'has only the plan row to work from: {", ".join(at_scene_start)}. '
            f'If the image is meant to open the scene, set placement=scene_open — '
            f'an opener is allowed to depict the prose that follows it.')
    unstated = [job['id'] for job in jobs if not job['state']]
    if unstated:
        log(f'{len(unstated)} of {len(jobs)} illustration(s) have no resolved '
            f'visual state, so their costumes and lighting are the model\'s '
            f'inference rather than a read of reference/visual-state.csv: '
            f'{", ".join(unstated)}. The prompt files say so too.')

    if dry_run:
        for job in jobs:
            log(f'[dry-run] would write '
                f'{ill.default_prompt_rel(job["id"])}')
        return 0

    if style['unresolved_declaration']:
        # Refused, not warned. Staleness is a judgment call and "warn, never
        # exclude" is right for it; a declaration naming a path that does not
        # exist is unambiguous — an author who typed a path meant that path. The
        # alternative is spending the whole run on the convention's artwork and
        # returning 0, which is what the skill commits on: #299's exact outcome
        # with a warning stapled to it.
        log(f'ERROR: refusing to write prompts. {STYLE_REFERENCE_KEY} names '
            f'`{style["unresolved_declaration"]}`, which does not exist, so '
            f'every prompt in this run would inherit its house style from '
            + (f'`{style["path"]}` instead.' if style['path']
               else 'nothing at all.')
            + f' Fix the path, or remove {STYLE_REFERENCE_KEY} to use the '
              f'convention deliberately.')
        return 1

    if needs_api and not os.environ.get('ANTHROPIC_API_KEY'):
        log('ERROR: ANTHROPIC_API_KEY is not set. Art direction in '
            f'{coaching} coaching requires an API key. Set it and re-run, or '
            'use --coaching strict for a scaffold.')
        return 1

    os.makedirs(ill.prompts_dir(project_dir), exist_ok=True)
    written = 0
    failed: list[str] = []

    # Phase 2 — fan the API calls out. Each is ~13s of waiting on one
    # independent request, so a 20-illustration book is minutes of serial
    # latency for no reason. Nothing is written here.
    bodies = _fetch_art_direction(project_dir, jobs) if needs_api else {}

    # Phase 3 — apply, in plan order, single-threaded. Every write lives here:
    # append_anchor_stubs rebuilds its canon_id_index per call, so two rows
    # proposing the same anchor must reach it one at a time or the second
    # would overwrite the first instead of skipping it.
    for job in jobs:
        illus_id = job['id']
        row = job['row']
        if needs_api:
            body = bodies.get(illus_id, '')
            if not body:
                # The actual status, not a hardcoded `planned`: via --ids this
                # row can be ingested, rendered, prompted, or superseded, and
                # telling an author their finished art is at `planned` is the
                # same confusion the status guard below exists to prevent.
                held = (row.get('status') or '').strip()
                log(f'WARNING: no art direction returned for {illus_id} — '
                    f'skipping (status stays '
                    f'`{held or "planned (its status cell is empty)"}`)')
                failed.append(illus_id)
                continue
            unparsed = pi.unparsed_anchor_lines(body)
            body, new_anchors = pi.split_anchor_block(body)
            if unparsed:
                log(f'  WARNING: {len(unparsed)} line(s) in the proposed '
                    f'ANCHORS block did not parse as "Name | type — '
                    f'description" and were discarded: {unparsed!r}')
            if new_anchors:
                added = pi.append_anchor_stubs(project_dir, new_anchors)
                if added:
                    log(f'  wrote {len(added)} new canon stub(s) for review: '
                        f'{", ".join(added)}')
                    others = [j['id'] for j in jobs if j['id'] != illus_id]
                    if others:
                        # Every request in this run was built before these
                        # stubs existed, so no other prompt file uses them.
                        # Naming the re-run is the difference between a note
                        # and an action.
                        log(f'         the other prompt(s) in this run were '
                            f'built before these stubs existed and do not use '
                            f'them. Review the stub text, then re-run: '
                            f'storyforge illustrate --prompts --ids '
                            f'{",".join(others)}')
        else:
            body = _strict_prompt_scaffold(row)

        content = pi.render_prompt_file(
            row=row, body=body, references=job['references'],
            aspect=job['aspect'], state=job['state'],
            absent=job['absent'], contrast=job['contrast'],
            split=job['split'],
        )
        rel = ill.default_prompt_rel(illus_id)
        with open(os.path.join(project_dir, rel), 'w', encoding='utf-8') as f:
            f.write(content)

        # Field-scoped: `prompt_file` always, `status` only when it moves
        # forward. Writing status unconditionally demoted finished art —
        # `--prompts --ids LF-05` on a fully-ingested book took the publishable
        # set from 20/20 to 19/20, silently, because `prompted` is not
        # `ingested` and `ingested` is what every consumer gates on.
        current = (row.get('status') or '').strip()
        updates = {'prompt_file': rel}
        advanced = _status_after_prompt(current)
        if advanced:
            updates['status'] = advanced
            if current == 'superseded':
                log(f'  {illus_id}: reviving a retired row — status '
                    f'superseded → prompted. Its old art still does not ship; '
                    f'render this prompt and --ingest to bring the row back.')
        else:
            log(f'  {illus_id}: prompt rewritten for already-{current} art; '
                f'status stays `{current}` so it keeps publishing. This means '
                f'a re-render is pending — render this prompt and --ingest to '
                f'replace the art.')
        _update_row(project_dir, illus_id, updates)
        log(f'  {illus_id} → {rel}')
        written += 1

    log(f'Wrote {written} prompt file(s) to {ill.PROMPTS_SUBDIR}/')
    if written:
        log('Render each prompt with your image model, then bring the files '
            'back with: storyforge illustrate --ingest <dir>')
    if failed:
        # A partial run is a failure. Reporting success on 2-of-5 leaves the
        # author to notice the gap themselves, and the skill commits after a
        # zero exit.
        log(f'WARNING: {written} of {written + len(failed)} illustration(s) '
            f'completed; {len(failed)} produced no art direction: '
            f'{", ".join(failed)}. Re-run --prompts for those before '
            f'committing.')
        return 1
    return 0


# ============================================================================
# --sequence
# ============================================================================

def run_sequence(project_dir: str, coaching: CoachingLevel,
                 dry_run: bool) -> int:
    """Assign each illustration a distinct treatment, in one cheap call.

    One call for the whole set, because the problem is a property of the set:
    each per-illustration call is individually happy with the shot it wanted,
    and no one of them can see that three others want the same one. It reads
    beats and layouts only — never the scene prose, which is what the
    per-illustration pass reads.

    An author-written treatment is never overwritten, and identical treatments
    across rows are reported: variety is the entire purpose, so a duplicate
    defeats the pass while every individual prompt still looks fine.
    """
    rows = packet.rows_in_reading_order(project_dir)
    if not rows:
        log('No illustration plan rows to stage. Run '
            '`storyforge illustrate --plan` first.')
        return 0

    authored = [r['id'].strip() for r in rows
                if (r.get('treatment') or '').strip()]
    log(f'Staging {len(rows)} illustration(s) as a sequence'
        + (f'; {len(authored)} already carry an author treatment and will not '
           f'be changed: {", ".join(authored)}' if authored else ''))

    if coaching == 'strict':
        return _write_coaching_file(
            project_dir, 'illustration-sequence-checklist.md',
            pp.render_sequence_checklist(rows=rows), dry_run)

    if dry_run:
        log(f'[dry-run] would request treatments for {len(rows)} '
            f'illustration(s) (coaching={coaching})')
        return 0

    if not os.environ.get('ANTHROPIC_API_KEY'):
        log('ERROR: ANTHROPIC_API_KEY is not set. Staging the sequence in '
            f'{coaching} coaching requires an API key. Set it and re-run, or '
            'use --coaching strict for a checklist.')
        return 1

    text = _invoke(project_dir,
                   pp.build_sequence_request(
                       rows=rows, story_context=_story_context(project_dir)),
                   'illustrate-sequence', task_type='synthesis',
                   max_tokens=4096)
    if not text:
        log('ERROR: no response from the API.')
        return 1

    treatments, status = pp.parse_sequence_response(text)
    if status != 'ok':
        log(f'ERROR: could not parse treatments from the response ({status}). '
            f'Nothing was written to the plan.')
        return 1

    known = {row['id'].strip() for row in rows}
    proposed: dict[str, str] = {}
    unknown: list[str] = []
    for item in treatments:
        if item['id'] in known:
            proposed[item['id']] = _sanitize_cell(item['treatment'])
        else:
            unknown.append(item['id'])
    if unknown:
        log(f'WARNING: {len(unknown)} proposed treatment(s) name no plan row '
            f'and were dropped: {", ".join(sorted(unknown))}')

    unstaged = sorted(known - set(proposed) - set(authored))
    if unstaged:
        log(f'WARNING: {len(unstaged)} illustration(s) got no treatment and '
            f'stay unstaged: {", ".join(unstaged)}. Re-run --sequence, or fill '
            f'`treatment` by hand — an unstaged image is one the set cannot '
            f'stop converging on.')

    log(f'Received {len(proposed)} usable treatment(s)')

    if coaching == 'coach':
        # Duplicates are reported here too, over what the *brief* proposes. The
        # author is about to hand-copy these into the plan, and a repeat defeats
        # the pass whichever hand writes it — reporting only on the write path
        # meant coach mode never got the one warning this pass exists to give.
        _report_duplicate_treatments([
            {'id': row['id'].strip(),
             'treatment': (row.get('treatment') or '').strip()
                          or proposed.get(row['id'].strip(), '')}
            for row in rows
        ], where='in this brief')
        return _write_coaching_file(
            project_dir, 'illustration-sequence-brief.md',
            pp.render_sequence_brief(rows=rows, proposed=proposed), dry_run)

    return _apply_treatments(project_dir, proposed)


def _report_duplicate_treatments(rows: list[dict[str, str]], *,
                                 where: str) -> None:
    """Warn about any treatment shared by more than one row."""
    for treatment, ids in sorted(pp.duplicate_treatments(rows).items()):
        log(f'WARNING: {len(ids)} illustrations share one treatment {where} '
            f'({treatment!r}): {", ".join(sorted(ids))}. Variety is the whole '
            f'point of this pass — give them different staging, or say in one '
            f'of them that the echo is deliberate.')


def _apply_treatments(project_dir: str, proposed: dict[str, str]) -> int:
    """Write proposed treatments, never over an author's, and report repeats.

    Reads and writes the *whole* plan, not the reading-order subset, so a
    superseded row keeps its cells. The write is skipped entirely when nothing
    changed: rewriting identical bytes still bumps the plan's mtime, which makes
    an existing packet report `packet_stale` over a run that changed nothing.
    """
    plan = ill.read_plan(project_dir)
    written = 0
    for row in plan:
        illus_id = row['id'].strip()
        if illus_id not in proposed:
            continue
        existing = (row.get('treatment') or '').strip()
        if existing:
            if existing != proposed[illus_id]:
                log(f'  {illus_id}: keeping the author treatment '
                    f'({existing!r}); the model proposed '
                    f'{proposed[illus_id]!r}')
            continue
        row['treatment'] = proposed[illus_id]
        # Stamped so the packet can tell a treatment written *after* a render
        # (the finished art does not follow it) from one written before it
        # (nothing is wrong). Without the stamp the only honest report was "the
        # packet cannot tell which came first", which on a book staged in the
        # documented order fired on every ingested row — 12 of 14 gaps on a
        # 12-row book, burying the two real ones.
        row['treatment_at'] = date.today().isoformat()
        written += 1
    if written:
        ill.write_plan(project_dir, plan)
        log(f'Wrote {written} treatment(s) to reference/{ill.PLAN_FILENAME}')
    else:
        log(f'No new treatment(s) to write — reference/{ill.PLAN_FILENAME} was '
            f'left untouched, so an existing packet does not become stale over '
            f'a run that changed nothing.')

    _report_duplicate_treatments(packet.rows_in_reading_order(project_dir),
                                 where='in the plan')
    if written:
        log('Re-run `storyforge illustrate --package` to carry the staging '
            'into the packet, and --prompts to carry it into the prompts.')
    return 0


# ============================================================================
# --package
# ============================================================================

def run_package(project_dir: str, dry_run: bool, *,
                report_batch: bool) -> int:
    """Assemble `manuscript/illustration-packet/` — six files, no API calls.

    Regenerated wholesale, so the packet is a render and never hand-edited: the
    author's edits belong in the plan, the transition log, or the canon files,
    all of which this reads.

    Nothing here blocks. A warning the author has considered is theirs to
    override, and refusing to build the packet over a never-run audit would
    strand them behind a check they may have a reason to skip — so every gap is
    logged as a WARNING *and* written into README.md, which is the copy they
    will still have in front of them an hour later.

    Args:
        report_batch: Whether to log the anchor batch. `main` passes False when
            `--diagnose` was also requested, because that report owns the batch
            (#290 item 2). **No default**: the guard is against a second caller
            forgetting the coupling, which is likelier than the case it was
            written for — `main` early-returns on `--diagnose` today, so its
            argument is provably True and nothing exercises the False path
            through the CLI. Requiring it keeps the decision at every call site
            rather than only at the one that remembered.
    """
    from storyforge import canon as canon_mod
    # One read for the whole run: `resolve` threads this into `state_context`,
    # the reference list, and the style reference, and `needs_render` takes it
    # too — so the canon tree is walked once and an unparseable `canon_updated`
    # is reported once rather than five times.
    canon_cutoff = canon_mod.newest_canon_updated(project_dir)

    # Before anything is resolved or written. `run_package` deliberately skips
    # `validate_plan` — its findings would duplicate the gaps and make README
    # depend on the previous packet's staleness — but that is a *reporting*
    # argument and never applied to the one check whose absence is destructive.
    # `_write_image_prompts` clears the previous run's uploads before it writes,
    # so an id that cannot name a file used to delete the packet's payload and
    # then raise a traceback out of `main` (#306 review).
    illegal = ill.illegal_plan_ids(ill.read_plan(project_dir))
    if illegal:
        log(f'ERROR: {len(illegal)} plan row(s) have an `id` that cannot name a '
            f'file ({", ".join(repr(i) for i in illegal)}). Fix the `id` cell in '
            f'reference/{ill.PLAN_FILENAME}; nothing has been written.')
        return 1

    # Derived before `resolve`, which ranks the upload list by it (#311), and
    # threaded rather than derived again inside it: `anchor_batch` re-reads the
    # plan, the chapter map, and the transition log for a value this run already
    # has, and `read_transitions` logs per malformed row per read.
    #
    # Not a correctness guarantee, and an earlier version of this comment claimed
    # one: `anchor_batch` is a pure read and nothing between here and the write
    # mutates its three inputs, so deriving it twice would return the same value.
    # Threading is what makes README's batch table and its upload list read the
    # same four ids *cheaply*; they could not have disagreed either way.
    batch = packet.anchor_batch(project_dir)
    contents = packet.resolve(project_dir, canon_cutoff=canon_cutoff,
                              batch=batch)
    grid = packet.state_grid(project_dir)
    needs = packet.needs_render(project_dir, canon_cutoff=canon_cutoff)
    title = read_yaml_field('project.title', project_dir) or '(untitled)'

    illustrated: dict[str, list[str]] = {}
    for entry in contents['entries']:
        if entry['scene_id']:
            illustrated.setdefault(entry['scene_id'], []).append(entry['id'])

    # Every aspect the set actually uses, in the canonical order, so
    # acceptance.md states the orientation rule for those and no others.
    used = {entry['aspect'] for entry in contents['entries']}
    aspects = [a for a in pi.ASPECTS if a in used] or [pi.DEFAULT_ASPECT]

    files = {
        'README.md': pp.render_readme(
            title=title, contents=contents,
            entry_count=len(contents['entries']), batch=batch,
            needs_render=needs),
        'canon.md': pp.render_canon(
            book_level=contents['book_level'], anchors=contents['anchors'],
            labels=_anchor_labels(project_dir)),
        'visual-state.md': pp.render_visual_state(
            grid=grid, illustrated=illustrated),
        'illustrations.md': pp.render_illustrations(
            entries=contents['entries']),
        'acceptance.md': pp.render_acceptance(aspects=aspects),
    }
    prompts = {
        entry['id']: pp.render_image_prompt(prompt=entry, title=title)
        for entry in contents['entries']}

    if dry_run:
        for name in packet.PACKET_FILES:
            log(f'[dry-run] would write '
                f'{os.path.join(packet.PACKET_DIR, name)}')
        log(f'[dry-run] would write {len(prompts)} file(s) to '
            f'{os.path.join(packet.PACKET_DIR, packet.IMAGE_PROMPTS_SUBDIR)}/')
        for gap in contents['gaps']:
            log(f'[dry-run] WARNING: {gap}')
        return 0

    os.makedirs(packet.packet_dir(project_dir), exist_ok=True)
    _remove_retired_files(project_dir)
    # The image prompts go down **before** the root files, and `is_built` keys on
    # the root files alone. Written the other way round, an interrupted run left
    # `--diagnose` reporting a packet "built and current" over a directory with
    # nothing to upload in it (#298's lesson, kept). The stale copies are cleared
    # first so a row dropped from the plan does not leave a file that still looks
    # current beside the ones that are.
    _write_image_prompts(project_dir, prompts)
    for name in packet.PACKET_FILES:
        with open(packet.packet_file(project_dir, name), 'w',
                  encoding='utf-8') as f:
            f.write(files[name])

    log(f'Wrote {len(packet.PACKET_FILES)} file(s) and {len(prompts)} image '
        f'prompt(s) to {packet.PACKET_DIR}/ — '
        f'{len(contents["entries"])} illustration(s), '
        f'{len(contents["anchors"])} continuity anchor(s)')
    _warn_superseded_export(project_dir)
    for gap in contents['gaps']:
        log(f'  WARNING: {gap}')
    if contents['gaps']:
        log(f'  {len(contents["gaps"])} gap(s) above are also written into '
            f'{os.path.join(packet.PACKET_DIR, "README.md")}, so the packet '
            f'says what it cannot tell you.')
    if report_batch:
        _report_anchor_batch(batch, needs)
    log('Render and approve the anchor batch, ingest those, then re-run '
        '--package so the rest can reference real images.')
    return 0


def _remove_retired_files(project_dir: str) -> None:
    """Delete packet files earlier versions wrote and this one does not.

    A leftover `reference-images.md` is not clutter — it is a second, stale
    answer to "what do I upload", sitting beside the current one in a bundle
    whose whole contract is being a render. An author upgrading mid-book would
    otherwise keep reading the pre-#306 file, which lists whichever images that
    version selected and omits every disclosure added since — including the
    anchor-batch ranking, which changes *which* images belong in the list (#311).

    Enumerated rather than "anything not in PACKET_FILES": the packet directory
    is the author's to put a note in, and a wholesale sweep is the destructive
    shape this pipeline has been bitten by before.
    """
    for name in packet.RETIRED_PACKET_FILES:
        path = packet.packet_file(project_dir, name)
        if not os.path.isfile(path):
            continue
        try:
            os.remove(path)
        except OSError as exc:
            # Never fatal. This runs before anything is written, so raising
            # aborted the whole rebuild — leaving both the stale file the
            # removal exists to prevent *and* a packet that was never
            # regenerated, which is strictly worse than the condition guarded
            # against.
            log(f'WARNING: could not remove '
                f'{os.path.join(packet.PACKET_DIR, name)} '
                f'({exc.strerror or exc}). It is a stale upload list from an '
                f'older version — delete it by hand, and do not read it.')
            continue
        log(f'  removed {os.path.join(packet.PACKET_DIR, name)} — its '
            f'contents are in README.md now.')


def _write_image_prompts(project_dir: str, prompts: dict[str, str]) -> None:
    """Write `image-prompts/`, clearing whatever an earlier run left there.

    Cleared rather than merged: an id dropped from the plan would otherwise leave
    a file that reads exactly like the current ones, in the directory whose only
    job is being the thing the author uploads.

    Only `.md` files are removed. The directory is inside a render, so nothing
    should be hand-placed there — but deleting an author's stray note is not this
    function's call to make, and `shutil.rmtree` on a path assembled from a plan
    cell is the destructive shape #298 was reviewed for.
    """
    directory = packet.image_prompts_dir(project_dir)
    os.makedirs(directory, exist_ok=True)
    # Every path is resolved before a single file is removed. `image_prompt_file`
    # raises on an id that cannot name a file, and `run_package` gates on
    # `ill.illegal_plan_ids` before this — but resolving first means even a
    # caller that skipped the gate cannot get past the delete loop on bad data.
    targets = {illus_id: packet.image_prompt_file(project_dir, illus_id)
               for illus_id in prompts}
    keep = {os.path.basename(path) for path in targets.values()}
    for name in sorted(os.listdir(directory)):
        if name.endswith('.md') and name not in keep:
            os.remove(os.path.join(directory, name))
    for illus_id, path in targets.items():
        with open(path, 'w', encoding='utf-8') as f:
            f.write(prompts[illus_id])
    # An exit-0 run reporting a count it did not achieve is worse than a loud
    # failure: on a case-insensitive filesystem two ids differing only in case
    # are one inode, so the survivor carries the second row's prompt under the
    # first row's name and the author generates the wrong illustration.
    # `validate_plan` catches `duplicate_id`, but `run_package` does not call it.
    written = {name for name in os.listdir(directory) if name.endswith('.md')}
    if len(written) != len(targets):
        missing = sorted(os.path.basename(path) for path in targets.values()
                         if os.path.basename(path) not in written)
        cause = (', '.join(missing) if missing else
                 'ids differing only in case collide on this filesystem')
        log(f'WARNING: {len(targets)} image prompt(s) were written but '
            f'{len(written)} file(s) exist — {cause}. The surviving file '
            f'carries one row\'s prompt under another row\'s name, so '
            f'uploading it generates the wrong illustration. Run `storyforge '
            f'validate` and fix the `id` cells first.')


def _warn_superseded_export(project_dir: str) -> None:
    """Say once that a pre-1.57.0 export directory is superseded.

    Reported, never deleted. It is 167 MB on the book this was filed about, so an
    author wants it gone — but a command that removes a directory it did not
    write, on a path the author may have put their own files under, is the
    destructive shape this pipeline has been bitten by before.
    """
    legacy = os.path.join(project_dir, 'manuscript', 'illustration-export')
    if not os.path.isdir(legacy):
        return
    log('NOTE: manuscript/illustration-export/ is superseded — its '
        'per-illustration file is now '
        f'{packet.PACKET_DIR}/{packet.IMAGE_PROMPTS_SUBDIR}/<id>.md and its '
        'reference copies are gone (every unit held the same images). Nothing '
        'reads that directory any more; delete it when you are ready.')


def _report_anchor_batch(batch: packet.AnchorBatch,
                         needs_render: packet.RenderNeeds) -> None:
    """Log the four slots and every disclosure.

    The fallback notes are WARNING lines rather than plain output: a guessed
    darkest slot is a claim the author has to either confirm or correct, and it
    reads as a decision unless something says otherwise. A canon-stale slot is a
    WARNING for the same reason: `[ingested]` on art the canon has outgrown is
    what let a whole set be handed over unrendered (#300).
    """
    log('Anchor batch — render and approve these before the rest:')
    marks: dict[packet.RenderState, str] = {
        'done': '  [ingested]',
        'stale': '  [ingested, but needs a re-render]',
        'pending': '',
    }
    for slot, label in packet.BATCH_SLOTS:
        illus_id = batch[slot]
        if not illus_id:
            log(f'  {label}: (unfilled)')
            continue
        log(f'  {label}: {illus_id}'
            f'{marks[packet.render_state(needs_render, illus_id)]}')
    stale = packet.ids_in_state(
        needs_render, 'stale',
        among=list(packet.slots_by_id(batch)))
    if stale:
        # One aggregated warning, not one per slot: the reason is the same
        # sentence for every row sharing a cause, and the advice is identical for
        # all of them. `--diagnose` has already listed the whole plan's stale
        # rows by the time this runs, so per-slot paragraphs restated it twice.
        log(f'  WARNING: {", ".join(stale)} still say `ingested`, but their art '
            f'predates the current canon (see the reasons above), so phase 1 is '
            f'not done until they are re-rendered and re-ingested. The churn '
            f'would otherwise reference nothing at all: `--prompts` already '
            f'excludes pre-canon renders, so an unrepaired batch leaves the set '
            f'with no likeness reference beyond the cover. Leave `status` alone '
            f'— demoting it drops the illustration from the Bookshelf publish '
            f'manifest while the epub, the PDF, and the web book keep shipping '
            f'it.')
    for note in batch['fallback']:
        log(f'  WARNING: {note}')


def _warn_truncated_anchors(project_dir: str) -> None:
    """Warn, before any call is paid for, about anchors that are silently short.

    The sibling of `_warn_unanchored_rows`, and the harder case: an absent
    anchor is loud, while a truncated one is present, real prose, and shorter
    than the file looks — so every request accepts it and the set drifts on
    whatever the dropped tail described. `validate` and `cleanup` both report it
    (`canon_anchor_truncated`), but an author who goes straight to `--prompts`
    has run neither, and after the calls the money is spent (#293).
    """
    from storyforge import canon

    for canon_id, truncations in sorted(
            canon.truncated_anchor_ids(project_dir).items()):
        headings = ', '.join(f'`{t.heading}`' for t in truncations)
        log(f'WARNING: canon `{canon_id}` has a `##` heading inside its '
            f'Embeddable block ({headings}), which ENDS the block — every '
            f'prompt in this run embeds only the text above it, and the images '
            f'will drift on whatever the rest described. Demote it to `###` '
            f'and re-run. Art already rendered from the short anchor needs '
            f're-rendering.')


def _warn_unanchored_rows(rows: list[dict[str, str]],
                          anchors: dict[str, str]) -> None:
    """Warn, before any call is paid for, about rows with no usable anchor.

    Anchors are *inputs* to the art, not residue from it: `append_anchor_stubs`
    is a fallback for canon that does not exist yet, never the intended path.
    That distinction became load-bearing when the calls started fanning out.
    Previously the anchor set was re-read per row, so a stub written for row 1
    reached rows 2..N verbatim — the identical-string mechanism working by
    accident. Now every request is built before the first call, so N rows with
    no anchor for a character each invent their own description, the first stub
    wins the file, and the other N-1 prompt files disagree with it. That is the
    exact likeness drift the anchor mechanism exists to prevent.

    Nothing downstream can repair that, so the only useful moment is here.
    Two shapes of gap:

    - `canon_refs` naming an id with no anchor — the row asked for an anchor
      that does not exist.
    - `canon_refs` empty while the book *does* have entity canon — the
      full-set fallback is in play (see `_relevant_anchors`), so nothing checks
      whether this row's actual cast is anchored.
    """
    known = {key.strip().lower() for key in anchors}
    missing: dict[str, list[str]] = {}
    unnarrowed: list[str] = []
    for row in rows:
        rid = (row.get('id') or '').strip() or '(no id)'
        named = {n.strip().lower()
                 for n in ill._split_array(row.get('canon_refs', ''))}
        if not named:
            if anchors:
                unnarrowed.append(rid)
            continue
        gaps = sorted(named - known)
        if gaps:
            missing[rid] = gaps

    if missing:
        detail = '; '.join(f'{rid} → {", ".join(ids)}'
                           for rid, ids in sorted(missing.items()))
        log(f'WARNING: {len(missing)} row(s) name canon_refs with no '
            f'continuity anchor: {detail}. Those entities will be '
            f'art-directed with nothing holding their look fixed, and each '
            f'prompt will invent its own description — a model-proposed '
            f'anchor is written after the calls and does NOT reach the other '
            f'rows in this run, so the first one wins the canon file and the '
            f'rest disagree with it. Anchors are inputs, not residue: run '
            f'`storyforge illustrate --direction`, fill the new canon files, '
            f'and then prompt.')
    if unnarrowed:
        log(f'WARNING: {len(unnarrowed)} row(s) have no canon_refs '
            f'({", ".join(sorted(unnarrowed))}), so narrowing is off entirely: '
            f'every anchor in the book is sent to those prompts, which costs '
            f'tokens on a cast that is not in the frame and invites the model '
            f'to put off-frame characters in it. Nothing can check whether '
            f'their actual cast is anchored either, and a model-proposed '
            f'anchor is written after the calls and does NOT reach the other '
            f'rows in this run. Run `storyforge illustrate --direction` to '
            f'author the anchors, then fill canon_refs so each prompt gets '
            f'only the cast it shows.')


#: Statuses a written prompt may set to `prompted`. Everything else is art that
#: already exists on disk, and moving those backwards is what silently
#: un-published a finished illustration. `''` is a row whose status cell was
#: never filled in; `prompted` is the idempotent re-prompt; `superseded` is a
#: retired row an author named explicitly, which means revive it — as far as
#: `prompted`, never straight to `ingested`, because the replacement render
#: does not exist yet.
_ADVANCES_TO_PROMPTED = frozenset({'', 'planned', 'prompted', 'superseded'})


def _status_after_prompt(current: str) -> str:
    """The status to write after a prompt file, or '' to leave it alone.

    Status only ever moves forward. A `rendered` or `ingested` row keeps its
    status: the prompt file is new art direction for art that already ships,
    and the row is the only thing saying that art exists. Demoting it removed
    the illustration from Bookshelf (`manifest_assets` skips a non-`ingested`
    row) while leaving it in the epub, the PDF, and the web book, which drop
    only `superseded` (`ill.resolve_for_local`) — so the editions silently
    disagreed, and `--diagnose` said nothing, because an unrendered row is
    legitimate in-flight state. `FILED_STATUSES` does **not** gate marker
    resolution; its only consumer is `validate_plan`'s file/digest check.
    """
    return 'prompted' if current in _ADVANCES_TO_PROMPTED else ''


#: Art-direction calls issued at once. Each is one independent HTTP request
#: that spends its whole duration waiting, so the ceiling is politeness to the
#: API rather than local resources. `run_parallel` lets STORYFORGE_PARALLEL
#: lower it.
_PROMPT_WORKERS = 5


class _PromptJob(TypedDict):
    """One illustration's prepared art-direction work.

    Built before the fan-out and consumed after it, so the parallel phase
    carries no project state and the writing phase needs no locks. `request`
    is '' in strict coaching, where no API call happens at all.
    """
    id: str
    row: dict[str, str]
    references: list[tuple[str, str]]
    aspect: pi.Aspect
    request: str
    #: The matrix resolved at this row's scene (`state_override` overlaid), and
    #: the row's `absent` and `contrast`. All three are carried on the job rather
    #: than recomputed in the write phase, so the request the model answered and
    #: the prompt file's constraint and acceptance blocks are the same strings —
    #: the whole point of #297 is that two renderings of one row drift apart.
    state: str
    absent: str
    contrast: str
    #: The scene cut at this illustration's reading position. Carried for the
    #: same reason the three above are: the request is built from `unread` and
    #: the prompt file's acceptance block from `next_sentence`, and the two must
    #: describe one split of one scene. Recomputing in the write phase would
    #: re-read the file, so a scene edited mid-run would give the model one
    #: split and the author's spoiler check another (#308).
    split: ill.SceneSplit


def _fetch_art_direction(project_dir: str,
                         jobs: list[_PromptJob]) -> dict[str, str]:
    """Run every job's art-direction call concurrently. Returns id -> body.

    A body of '' means the call failed; the caller reports it and leaves the
    row at `planned`. Uses `runner.run_parallel`, which is a thread pool (the
    calls are I/O-bound) and honours the shutdown flag the signal handlers set.
    An id missing from the results because of that shutdown is reported here
    rather than silently becoming an empty body indistinguishable from an API
    error.
    """
    from storyforge.runner import run_parallel

    requests = {job['id']: job['request'] for job in jobs}

    def _worker(illus_id: str) -> str:
        return _invoke(project_dir, requests[illus_id], 'illustrate-prompt',
                       task_type='creative', max_tokens=2048,
                       target=illus_id)

    results = run_parallel(list(requests), _worker,
                           max_workers=_PROMPT_WORKERS, label='illustration')

    bodies: dict[str, str] = {}
    for illus_id in requests:
        if illus_id not in results:
            log(f'WARNING: {illus_id} was never dispatched — the run was '
                f'interrupted before its art direction was requested.')
            bodies[illus_id] = ''
            continue
        outcome = results[illus_id]
        if isinstance(outcome, BaseException):
            # run_parallel already logged the failure; name the consequence.
            log(f'WARNING: art direction for {illus_id} raised '
                f'{type(outcome).__name__}: {outcome}')
            bodies[illus_id] = ''
        else:
            bodies[illus_id] = outcome
    return bodies


def _anchor_labels(project_dir: str) -> dict[str, str]:
    """Display names for the prompt's anchor list, keyed by canon_id.

    Reports the ids that fell all the way through to a title-cased slug — that
    means neither the canon file nor the registry records the entity's name, so
    the prompt is labeling it with a guess.
    """
    from storyforge import canon as canon_mod
    entries = canon_mod.anchor_display_names(project_dir)
    guessed = sorted(cid for cid, entry in entries.items()
                     if entry['source'] == 'slug')
    if guessed:
        log(f'{len(guessed)} anchor(s) have no recorded display name and are '
            f'labeled from their id: {", ".join(guessed)}. Add '
            f'`display_name:` to the canon file, or a `name` to the registry '
            f'row, if the title-cased slug reads wrong.')
    return {cid: entry['label'] for cid, entry in entries.items()}


def _reference_cutoff(project_dir: str, no_prior_refs: bool,
                      cutoff: str | None = None) -> str:
    """The canon date a prior render must post-date to serve as a reference.

    '' means no cutoff — either the author asked for cover-only references
    anyway, or no canon file carries a parseable `canon_updated`, in which case
    there is no governing direction for art to predate.

    `cutoff` is the run's already-read `newest_canon_updated`. Passed in rather
    than read again so the canon tree is walked once per run and its
    unparseable-date WARNING is logged once. **This return value is not a
    substitute for that argument**: it is '' under `--no-prior-refs`, which is
    exactly the run where the style reference most needs checking, and handing it
    to `resolve_style_reference` is how #299 would come back.
    """
    from storyforge import canon as canon_mod
    if cutoff is None:
        cutoff = canon_mod.newest_canon_updated(project_dir)
    if no_prior_refs:
        log('--no-prior-refs: prompts will reference the cover only, not any '
            'previously ingested illustration.')
        return ''
    if not cutoff:
        log('No parseable `canon_updated` date in reference/canon/ — prior '
            'ingested illustrations will be used as style references without '
            'a staleness check.')
        return ''
    log(f'Canon last updated {cutoff}; illustrations ingested before then are '
        f'not used as style references.')
    return cutoff


def _strict_prompt_scaffold(row: dict[str, str]) -> str:
    """Build the four-section scaffold for strict coaching — no prose.

    Four, not five: the Constraints section is appended deterministically by
    render_prompt_file, so a scaffolded one would be a second, contradictory
    heading.
    """
    def cell(key: str) -> str:
        return (row.get(key) or '').strip() or '_(you fill this in)_'

    return '\n'.join([
        '### Scene', '', cell('mood'), '',
        '### Subject', '', cell('subject'), '',
        '### Important details', '',
        f'- Palette: {cell("palette")}',
        f'- Composition: {cell("composition")}',
        f'- Motifs to carry: {cell("motifs")}',
        f'- Canon to honor: {cell("canon_refs")}', '',
        '### Use case', '',
        'Interior illustration for a novel.', '',
    ])


#: Prior *illustrations* referenced per prompt. Enough to anchor style and
#: likeness; more than this and the model starts averaging them.
#:
#: The cover is **additive**, not one of these four (#311). The cap's own
#: justification is a claim about like-for-like illustration references, and the
#: cover art does a different job — house style, not likeness — so counting it
#: made a full four-slot anchor batch unrepresentable: cover + batch is five, and
#: the fourth approved image was dropped by an arithmetic accident rather than a
#: judgement. Renamed from `_MAX_REFERENCES` so nothing keeps reading it as a
#: total.
_MAX_PRIOR_REFERENCES = 4

#: Where the style reference lives when nothing declares it. The *artwork*, not
#: the typeset cover — `production/cover.*` (or `manuscript/assets/cover.*`) is
#: the composite with the title burned into the raster, and feeding that to a
#: prompt whose own constraint block says "no text, no letters, no words"
#: teaches the render baked-in lettering.
_STYLE_REFERENCE_STEM = os.path.join('manuscript', 'assets', 'cover-illustration')

#: Extensions the convention filename is tried with, in this order. A jpeg export
#: of the same artwork is the same convention; refusing it because the name ends
#: `.jpg` is the brittleness this whole resolution order exists to fix.
#:
#: **This is not behaviour-neutral for a non-PNG project**, and the order is not
#: cosmetic. A book holding only `cover-illustration.jpg` previously resolved *no*
#: cover at all and got four prior illustrations; it now gets the cover *plus*
#: those four, since `_MAX_PRIOR_REFERENCES` counts prior illustrations only and
#: the cover is additive (#311). That is the better chain — the cover is the
#: strongest style anchor a book has — but it is a change, so it is stated rather
#: than described as "unchanged".
_STYLE_REFERENCE_EXTENSIONS = ('png', 'jpg', 'jpeg', 'webp')

#: The YAML key a project uses to say which of several cover variations is the
#: one that sets the house style.
STYLE_REFERENCE_KEY = 'production.cover_artwork'

#: Where the resolved path came from. A `Literal` rather than a `declared: bool`
#: beside an empty-`path` sentinel, because those two fields encoded one
#: three-valued fact and let a caller represent "declared but nothing resolved".
StyleReferenceSource = Literal['declared', 'convention', 'none']


class StyleReference(TypedDict):
    """Which artwork sets the house style for every prompt in the book.

    Returned rather than logged so the same resolution can be reported once per
    run by `--prompts` and rendered into the packet's README,
    without a per-row call logging the same warning twenty times. Same posture
    as `visual_state.prepass`: resolve silently, let the caller report.

    Which combinations occur, so a reader need not re-derive them from the
    constructor (`resolve_style_reference` is the only one):

    - `source='none'` ⟺ `path=''`, and then `symlink_target`, `modified` are ''
      and `stale` is False. Nothing resolved.
    - `source='declared'` ⟹ `unresolved_declaration=''`. The declaration either
      resolved or it did not.
    - `unresolved_declaration != ''` with `source='convention'` — the declaration
      was ignored and the convention answered instead.
    - `stale=True` ⟹ `modified != ''` and `checked_against != ''`.
    - `path != ''` with `modified=''` — the mtime could not be read, so freshness
      is *unknown*, which is not the same as fresh and is warned about.
    """
    #: Whatever the resolution produced, verbatim: the declaration as written
    #: (relativized when it names a file inside the project), or the convention's
    #: project-relative path. '' when nothing resolved.
    path: str
    source: StyleReferenceSource
    #: A declared path that does not exist. Non-empty *and* a resolved `path`
    #: means the declaration was ignored and the convention answered instead —
    #: the one shape an author most needs told about, because the run still
    #: succeeds with the wrong art.
    unresolved_declaration: str
    #: Set when the declaration resolves to a file outside the project. The path
    #: then cannot be made project-relative, and it reaches git-tracked prompt
    #: files, so it is disclosed rather than silently committed.
    outside_project: bool
    #: Set when the resolved file's extension is not one an image model reads.
    #: A `production/cover.svg` compositing source is the realistic case, and it
    #: is exactly what a project with several cover variations also holds.
    unusable_extension: str
    #: What the path points at, when it is a symlink. The documented workaround
    #: for a project with several cover variations is to symlink the convention
    #: filename at the selected art, so the target is the thing the author
    #: actually recognizes.
    symlink_target: str
    #: A symlink whose target does not exist. Distinguished from "no artwork"
    #: because the convention filename *is* present, and telling an author to
    #: create a file they can see in `ls` is the least useful thing to say.
    dangling_symlink: str
    #: ISO date of the file's mtime, or '' if it could not be read.
    modified: str
    #: The newest `canon_updated` this was checked against, '' if there is none.
    #: Named for what it is rather than `canon_cutoff`, which is also the name of
    #: `_references_for`'s parameter — and those two mean deliberately different
    #: things (that parameter is '' under `--no-prior-refs`; this never is), so
    #: one name for both invites the tidy-up that reintroduces #299.
    checked_against: str
    #: `modified` is strictly older than `checked_against`.
    stale: bool


def resolve_style_reference(project_dir: str, *,
                            canon_cutoff: str | None = None) -> StyleReference:
    """Resolve the artwork that sets the house style, and how fresh it is.

    Resolution order — the same *shape* as `assembly._resolve_cover_path`
    (declaration, then convention), but narrower: one directory, four extensions,
    and no explicit-path argument.

    1. `production.cover_artwork` in storyforge.yaml — the declaration. A book
       can hold four rendered cover variations and one selected one, and before
       this key there was no way to say which counted: the convention filename
       won, silently, even when every live consumer pointed elsewhere. That is
       how twenty interior prompts inherited a superseded cover as their sole
       style reference (#299).
    2. `manuscript/assets/cover-illustration.{png,jpg,jpeg,webp}` — the
       convention, so an existing PNG project resolves exactly as before. See
       `_STYLE_REFERENCE_EXTENSIONS` for why a non-PNG project does not.

    Deliberately **not** `production.cover_image`: that key names the file that
    *ships*, which on a real book is the typeset composite. The artwork and the
    typeset cover are different files on purpose, so they get different keys.

    Staleness is the file's mtime against the newest `canon_updated`, on the
    same footing as a prior ingested render — the cover is the most influential
    reference in the list and the *only* one under `--no-prior-refs`, so
    exempting it left the highest-stakes run unchecked. Unlike an ingested row,
    an unreadable mtime is **not** treated as stale: there is no bookkeeping
    column here that a file could predate, so "unknown" is genuinely unknown —
    and because unknown must not read as fresh, it is warned about rather than
    passed over. `os.path.getmtime` follows symlinks, which is what we want —
    the target is the artwork.

    `canon_cutoff` defaults to reading the canon tree rather than taking
    `_reference_cutoff`'s answer, and that distinction is the whole point:
    `_reference_cutoff` returns '' under `--no-prior-refs`, which is precisely
    the run where the cover is 100% of the style signal. Inheriting that
    suppression would leave the highest-stakes run the only unchecked one. A
    caller that has already read the canon tree passes its own value so the tree
    is not walked twice (and its unparseable-date WARNING not logged twice).
    """
    from storyforge import canon as canon_mod
    if canon_cutoff is None:
        canon_cutoff = canon_mod.newest_canon_updated(project_dir)
    declared = read_yaml_field(STYLE_REFERENCE_KEY, project_dir).strip()
    unresolved = ''
    outside = False
    path = ''
    source: StyleReferenceSource = 'none'
    if declared:
        full = (declared if os.path.isabs(declared)
                else os.path.join(project_dir, declared))
        if os.path.isfile(full):
            # Relativized when it can be. `path` reaches git-tracked prompt files
            # and the packet's README, whose contract is
            # project-relative paths — an absolute declaration naming a file
            # inside the project would commit a machine-specific path to a shared
            # artifact. Same dance as `symlink_target` below.
            relative = os.path.relpath(full, project_dir)
            outside = relative.startswith(os.pardir)
            path = full if outside else relative
            source = 'declared'
        else:
            unresolved = declared

    if not path:
        for extension in _STYLE_REFERENCE_EXTENSIONS:
            candidate = f'{_STYLE_REFERENCE_STEM}.{extension}'
            if os.path.isfile(os.path.join(project_dir, candidate)):
                path = candidate
                source = 'convention'
                break

    reference: StyleReference = {
        'path': path,
        'source': source,
        'unresolved_declaration': unresolved,
        'outside_project': outside and bool(path),
        'unusable_extension': '',
        'symlink_target': '',
        'dangling_symlink': '',
        'modified': '',
        'checked_against': canon_cutoff,
        'stale': False,
    }
    if not path:
        # A dangling symlink at the convention path is not "no artwork": the file
        # is right there in `ls`, and symlinking the convention filename at the
        # selected art is the workaround this whole resolution order documents,
        # so a stale target is its likeliest failure mode.
        reference['dangling_symlink'] = _dangling_convention_link(project_dir)
        return reference

    full = path if os.path.isabs(path) else os.path.join(project_dir, path)

    extension = ill.normalize_asset_extension(os.path.splitext(full)[1])
    if extension not in _STYLE_REFERENCE_EXTENSIONS:
        # The convention scan cannot produce this; a declaration can, and
        # `production/cover.svg` is the case the key's own documentation raises.
        # `assembly.cover_manifest_asset` refuses the same condition for the
        # shipped cover; here it is a warning, because "warn, never exclude"
        # holds for the one reference that is sometimes the only one.
        reference['unusable_extension'] = extension

    if os.path.islink(full):
        target = os.path.realpath(full)
        relative = os.path.relpath(target, project_dir)
        reference['symlink_target'] = (
            target if relative.startswith(os.pardir) else relative)
    try:
        reference['modified'] = date.fromtimestamp(
            os.path.getmtime(full)).isoformat()
    except OSError:
        return reference
    reference['stale'] = canon_mod.predates_canon(
        when=reference['modified'], cutoff=canon_cutoff)
    return reference


def _dangling_convention_link(project_dir: str) -> str:
    """The convention path's symlink target, when the link exists and the target does not.

    Returns '' when there is no link at all, which is the ordinary "this book has
    no cover artwork" case.
    """
    for extension in _STYLE_REFERENCE_EXTENSIONS:
        candidate = os.path.join(project_dir,
                                 f'{_STYLE_REFERENCE_STEM}.{extension}')
        if os.path.islink(candidate) and not os.path.exists(candidate):
            return f'{_STYLE_REFERENCE_STEM}.{extension} → {os.readlink(candidate)}'
    return ''


def describe_style_reference(reference: StyleReference) -> str:
    """The one line that names what set the house style, or '' if nothing did.

    A run that spends twenty model calls must say which file directed them.
    Absent that line, the wrong cover surfaced only by reading a generated
    prompt by hand, twenty calls too late (#299). Reported with its symlink
    target because the documented workaround for a book with several cover
    variations is to symlink the convention filename at the selected art, and
    the target is the name the author recognizes.

    The freshness clause names what the mtime was compared against, so a bare
    date is never left for the reader to complete into a verdict of their own —
    and says so explicitly when there was nothing to compare against.
    """
    if not reference['path']:
        return ''
    source = (f'declared in {STYLE_REFERENCE_KEY}'
              if reference['source'] == 'declared'
              else 'the conventional filename')
    if not reference['modified']:
        freshness = ', modification time unreadable'
    elif reference['checked_against']:
        freshness = (f', modified {reference["modified"]} '
                     f'(canon last updated {reference["checked_against"]})')
    else:
        freshness = (f', modified {reference["modified"]} — no canon date to '
                     f'check it against')
    return (f'Style reference: {reference["path"]} ({source})'
            + (f' → {reference["symlink_target"]}'
               if reference['symlink_target'] else '')
            + freshness)


def style_reference_warnings(reference: StyleReference) -> list[str]:
    """Everything wrong with the style reference, as sentences starting lowercase.

    Separate from `describe_style_reference` because the two go to different
    places: the headline is a log line, while these are logged as WARNINGs *and*
    written into the packet's "What is not in that list" section, which must
    carry only problems — a positive resolution line there would read as an
    exclusion.

    **Every way this reference can be wrong or unverified produces a sentence
    here**, including the two that produce no verdict at all: no canon date to
    check against, and an unreadable mtime. #299 was a silent wrong reference, so
    a silent *unchecked* one is the same bug with a smaller blast radius —
    `--audit` renders "Not assessed" rather than "None found" for exactly this
    reason.
    """
    warnings: list[str] = []
    if reference['unresolved_declaration']:
        warnings.append(
            f'{STYLE_REFERENCE_KEY} names '
            f'`{reference["unresolved_declaration"]}`, which does not exist'
            + (f' — the conventional `{reference["path"]}` would be used '
               f'instead, which may not be the artwork you meant.'
               if reference['path'] else
               ' — and no conventional style reference was found either.'))
    if not reference['path']:
        if reference['dangling_symlink']:
            warnings.append(
                f'the style reference `{reference["dangling_symlink"]}` is a '
                f'symlink whose target does not exist, so nothing sets the '
                f'house style. The link is there in `ls` — repoint it at the '
                f'artwork you selected, or set {STYLE_REFERENCE_KEY}.')
        else:
            warnings.append(
                f'there is no cover artwork, so nothing sets the house style '
                f'from outside this set and the first render establishes the '
                f'look. Add {_STYLE_REFERENCE_STEM}.png, or set '
                f'{STYLE_REFERENCE_KEY} in storyforge.yaml.')
        return warnings

    named = (f'`{reference["path"]}`'
             + (f' (→ `{reference["symlink_target"]}`)'
                if reference['symlink_target'] else ''))

    if reference['outside_project']:
        warnings.append(
            f'the style reference {named} is outside the project, so its path '
            f'cannot be made project-relative — the prompt files and the '
            f'packet will carry an absolute path that means nothing on another '
            f'machine. Copy the artwork into the project and point '
            f'{STYLE_REFERENCE_KEY} at it.')
    if reference['unusable_extension']:
        warnings.append(
            f'the style reference {named} is a '
            f'.{reference["unusable_extension"]} file, which no image model '
            f'reads ({", ".join(_STYLE_REFERENCE_EXTENSIONS)} are usable). If '
            f'that is a compositing source, point {STYLE_REFERENCE_KEY} at the '
            f'rendered artwork beside it. It is still listed, because the one '
            f'reference that is sometimes the only one is never dropped '
            f'silently.')
    if not reference['modified']:
        warnings.append(
            f'the style reference {named} exists but its modification time '
            f'could not be read, so it could not be checked against the canon. '
            f'Unknown freshness is not the same as fresh — the art may predate '
            f'the direction now governing the book.')
    elif not reference['checked_against']:
        warnings.append(
            f'nothing in reference/canon/ carries a parseable `canon_updated`, '
            f'so the style reference {named} could not be checked for '
            f'staleness at all. It may predate the direction now governing the '
            f'book, and under --no-prior-refs it is the only thing setting the '
            f'house style.')
    elif reference['stale']:
        warnings.append(
            f'the style reference {named} was last modified '
            f'{reference["modified"]}, before the canon was last updated '
            f'{reference["checked_against"]}. It sets the house style for '
            f'every prompt — under --no-prior-refs it is the only thing that '
            f'does — so drift the new canon exists to remove is taught back. '
            f'Re-render the cover artwork, or point {STYLE_REFERENCE_KEY} at '
            f'art that postdates the canon.')
    return warnings


class _Candidate(NamedTuple):
    """One prior illustration that survived the exclusion checks.

    A `NamedTuple` rather than a bare `(str, str)` because `references` is also a
    list of two strings with the elements the other way round — `(path, label)`,
    the convention `pi.render_references_block` destructures — so one function
    held two same-typed pairs in opposite orders. `.illus_id` at the sort key is
    the one place a swap would otherwise be near-silent: a path looked up in an
    id-keyed dict simply promotes nothing.
    """
    illus_id: str
    path: str


def _slot_name(slot: packet.BatchSlot) -> str:
    """Render one anchor-batch slot key for a reference label.

    Substitutes `-` for `_`, so `later_state` reads `later-state`. That is the
    whole body, and it is load-bearing: the label reaches README's upload list and
    a prompt file, where the author reads it.

    The slot *key*, not `packet.BATCH_SLOTS`' label. Promotion order and slot
    identity both come from that tuple — a second list of the four slots here is
    exactly the divergence one derived batch exists to prevent — but its
    establisher label is a sentence ("the most shared vocabulary, earliest"),
    written for README's batch table where the author is choosing what to render.
    Spliced into a one-line reference label it reads as two clauses fighting:
    `path — prior illustration (anchor batch: establisher — the most shared
    vocabulary, earliest)`. The table explains the slots; the label only has to
    say which one this is.
    """
    return slot.replace('_', '-')


def _references_for(project_dir: str, illus_id: str, *,
                    plan: list[dict[str, str]] | None = None,
                    canon_cutoff: str = '',
                    no_prior_refs: bool = False,
                    style: StyleReference | None = None,
                    batch: packet.AnchorBatch | None = None,
                    notes: list[str] | None = None,
                    rerun: str = '--package') -> list[tuple[str, str]]:
    """Build the labeled reference list for an illustration.

    Prior ingested illustrations plus the cover are what hold a book's art
    together visually — a prompt with no style reference produces an image that
    belongs to no book in particular.

    **Candidates are ranked by anchor-batch slot, then by the caller's row
    order** (#311). Phase 1 of the handoff exists so that the long run which
    follows references four *real* images instead of four descriptions, and
    `--diagnose` will not call a packet ready to hand over until every batch slot
    is ingested from current canon — but selection was a plan-order walk with a
    cap that never asked what the batch was, so once enough post-canon renders
    existed to fill the cap, the images the author deliberately rendered and
    approved were exactly the ones it discarded. The guarantee phase 1 makes was
    not the guarantee phase 2 consumed. CLAUDE.md carries the case this was found
    on.

    The rank is applied as a *stable* sort, so a row in no slot keeps the order
    the caller gave — plan order under `--prompts`, **reading order** under
    `--package`, which passes `rows_in_reading_order`. Either is fine outside the
    batch: the chain needs *some* prior art to anchor style, not a specific one.

    `batch` is the run's already-derived `packet.anchor_batch`, threaded in for
    the reason `style` and `canon_cutoff` are: this is called once per row, so
    deriving it here would re-read the plan, the chapter map, and the transition
    log once per illustration. It is derived rather than stored, so a promoted
    reference cannot disagree with the batch `--diagnose` and README report. The
    `None` fallback exists for a one-off caller and a test, and derives from this
    call's own rows so the two cannot disagree — both production callers thread it.

    The cover reference is the *artwork*, not the typeset cover — using the art
    as a style reference is right, and the two files are deliberately different.
    Which artwork is resolved by `resolve_style_reference`: a declaration in
    `production.cover_artwork` first, then the `cover-illustration.*`
    convention. That reference is staleness-checked on the same footing as a
    prior render, but never *excluded* for being stale — under
    `--no-prior-refs` it is the whole style signal, so dropping it would leave
    the highest-stakes run with nothing.

    Two ways a prior illustration is excluded:

    - `no_prior_refs` — the author said so. This is the rebuild switch: cover
      only, nothing inherited.
    - `canon_cutoff` — a render older than the newest `canon_updated` was
      directed by canon that has since been rewritten, so feeding it back in
      teaches the new render the drift the new canon exists to remove. That is
      how a whole set inherits a pre-canon mistake through the visual key. An
      *empty* `ingested_at` counts as older: the column postdates the plan
      schema, so "unknown" means the render predates even the bookkeeping, and
      guessing in its favour is the failure mode this exists to stop.

    Every exclusion is logged. Silent staleness is what made the original bug
    hard to notice — the prompts looked fine, they just referenced the wrong
    images.

    `notes` is an optional out-list the same disclosures are appended to, in
    prose, for a caller that has to *render* them rather than log them. The
    packet's README is that caller: a log line the author read twenty minutes
    ago is not a substitute for the runbook step that tells them what to upload,
    and a list that silently shrank to the cover reads as "nothing is ingested
    yet". Threaded through this function rather than recomputed beside it so the
    two can never disagree about which references were dropped and why.

    `rerun` names the command a note tells the reader to re-run. It had two
    values while `--export` existed and has one now; kept as a parameter because
    `--prompts` and `--package` both call this and a note is *rendered into*
    whichever asked for it.
    """
    def note(text: str) -> None:
        if notes is not None:
            notes.append(text)

    references: list[tuple[str, str]] = []
    # Threaded in by `--prompts`, which resolves it once for the run so the
    # canon tree is not walked per row and the headline is logged exactly once.
    if style is None:
        style = resolve_style_reference(project_dir)
    cover = style['path']
    if cover:
        label = 'cover art (sets the house style)'
        if style['symlink_target']:
            label += f' → {style["symlink_target"]}'
        references.append((cover, label))
    for warning in style_reference_warnings(style):
        # Noted, not logged: this function is called once per row, and
        # `run_prompts` logs the same warnings once for the whole run.
        #
        # Not sentence-cased. The first warning begins with the literal YAML key,
        # and capitalising it printed `Production.cover_artwork` into the packet
        # — a key nothing reads, told to an author who is reading the packet
        # precisely to find out what to set.
        note(warning)

    rows = plan if plan is not None else ill.read_plan(project_dir)
    if batch is None:
        # `plan=rows`, not a bare disk read: ranking the caller's rows against
        # slots derived from disk is a precondition two callers could disagree
        # about, and this fallback is the only place they could.
        batch = packet.anchor_batch(project_dir, plan=rows)
    # illustration id -> its slot label, in promotion order, from the one function
    # that owns that discrimination. `slot_rank` is a projection of the same
    # dict's order rather than a second walk — 0-based, so the `len(slot_rank)`
    # default below sorts every unranked row strictly after every promoted one.
    promotions = packet.slots_by_id(batch)
    slot_of = {illus_id: _slot_name(slot) + (
                   ', guessed' if slot in batch['guessed'] else '')
               for illus_id, slot in promotions.items()}
    slot_rank = {illus_id: rank for rank, illus_id in enumerate(promotions)}

    skipped_stale = 0
    # Filled slot -> why that approved image is not in the list, for the members
    # whose art exists and still did not reach it. The claim "what is listed is
    # what was approved" has to be *checked*, because the exclusion walk runs
    # before the ranking and a partly re-rendered batch is the normal phase-1
    # state: on one, promotion had nothing to promote and the note said the
    # opposite (#311 review, SF-HIGH-1/HIGH-2).
    #
    # Deliberately not populated for a batch member that is merely not ingested
    # yet: unrendered is valid in-flight state, `--diagnose` already counts those
    # rungs, and a fresh book would get four notes saying nothing actionable. The
    # count below still declines to claim the batch is present.
    slot_unreferenceable: dict[str, str] = {}
    # (id, path) for every row that survived the exclusion checks, in plan order.
    # Collected rather than appended straight to `references` so the cap is
    # applied to *ranked* candidates: the exclusions and their disclosures stay a
    # plan-order walk, and only the ordering of what survives changed (#311).
    eligible: list[_Candidate] = []
    # Excluded files accumulated by *reason*, emitted as one note per reason
    # after the loop. Appended per row, this produced seventeen near-identical
    # paragraphs on a twenty-illustration book — 9.5 KB of a 13.9 KB file — in
    # the one section whose whole job is telling the author what they are not
    # uploading. One root cause, one note (#290, #306).
    excluded_no_prior: list[str] = []
    # Keyed on the *category*, not on the rendered sentence. The distinction
    # between an empty `ingested_at` and a date before the cutoff is worth
    # keeping — collapsing both into "predates the canon" aggregates away the
    # half that says what to fix — but `stale_render_reason` interpolates the
    # row's own date, so keying on it produced one group per ingest date. On the
    # dominant real case, twenty renders ingested across a working session, that
    # is one near-identical note per day: the shape this aggregation removes,
    # reconstituted by the choice of key (#306 review).
    excluded_stale: dict[ill.StaleKind, list[str]] = {}
    for row in rows:
        if row['id'].strip() == illus_id:
            continue
        if (row.get('status') or '').strip() != 'ingested':
            continue
        rel = (row.get('asset_file') or '').strip()
        if not rel or not os.path.isfile(os.path.join(project_dir, rel)):
            # The one exclusion that can lose an approved image with nothing
            # said anywhere: `status=ingested`, a current `ingested_at`, and the
            # file moved or renamed without a plan edit. `packet.needs_render`
            # never consults `asset_file`, so the batch table still reads
            # `Rendered: yes` for that slot while the chain silently lacks it.
            # `validate_plan`'s `missing_file` is the gate; this is the artifact
            # that made the claim (#311 review).
            if row['id'].strip() in slot_of:
                declared = f'`{rel}`' if rel else 'no `asset_file`'
                slot_unreferenceable[row['id'].strip()] = (
                    f'{declared}: declared by the plan, not on disk')
            continue
        if no_prior_refs:
            skipped_stale += 1
            excluded_no_prior.append(rel)
            continue
        # No `if canon_cutoff:` around this: the predicate makes that check
        # itself, and a caller-side copy reads as this caller having a different
        # rule from `packet.needs_render` and `packet.entry_for` — which is the
        # divergence one shared predicate exists to make impossible (#300).
        stale_reason = ill.stale_render_reason(row, canon_cutoff)
        if stale_reason:
            # Logged per file, aggregated in the note. "Every exclusion is
            # logged" is a stated invariant and a log is not the artifact whose
            # signal-to-noise is the feature.
            log(f'WARNING: not referencing {rel} for {illus_id} — '
                f'{stale_reason}. Re-render it from the current canon '
                f'(see `storyforge illustrate --diagnose` for the render '
                f'order), or pass --no-prior-refs to build this prompt '
                f'from the cover alone.')
            skipped_stale += 1
            excluded_stale.setdefault(
                ill.stale_render_kind(row, canon_cutoff), []).append(rel)
            # `excluded_stale` aggregates by `StaleKind` and so cannot say which
            # of those paths were the four the author approved. That disclosure
            # is what `skills/illustrate/SKILL.md` promises the author, and it
            # was the half of #311's asymmetry that went unimplemented.
            if row['id'].strip() in slot_of:
                slot_unreferenceable[row['id'].strip()] = (
                    f'`{rel}`: {stale_reason}')
            continue
        # An excluded row never becomes a candidate — every branch above
        # `continue`s before this line — so **exclusion outranks batch
        # promotion**: a pre-canon batch member stays excluded rather than being
        # promoted past the reason it was dropped, which is the whole point of
        # the check. That is structural, not a consequence of where the cap is
        # applied; an earlier comment said "therefore", which made a guarantee
        # look like an incidental property of pass ordering.
        #
        # The cap is applied after this loop for two reasons, and the primary one
        # is now the second: you cannot rank candidates you have not collected.
        # Breaking out early would also hide every stale render past the fourth
        # prior illustration behind a cap that is not why they were dropped.
        eligible.append(_Candidate(row['id'].strip(), rel))

    # Stable, so a row in no slot keeps its plan-order position and the change is
    # confined to promoting the approved batch ahead of them.
    eligible.sort(key=lambda c: slot_rank.get(c.illus_id, len(slot_rank)))
    for candidate in eligible[:_MAX_PRIOR_REFERENCES]:
        slot = slot_of.get(candidate.illus_id)
        references.append((
            candidate.path, f'prior illustration (anchor batch: {slot})'
            if slot else 'prior illustration (style continuity)'))
    dropped = eligible[_MAX_PRIOR_REFERENCES:]
    # Split, because the cap note has to say when the thing it dropped was an
    # image the author personally approved. Reported as an anonymous "further
    # ingested illustration", silent loss of the approved batch is the part of
    # #311 that made the bug hard to notice at all.
    #
    # **Unreachable while `_MAX_PRIOR_REFERENCES >= len(packet.BATCH_SLOTS)`**,
    # which a test pins: at most four ids are promoted, each to a rank below four,
    # so no promoted row reaches `dropped`. It survives on one production route —
    # two plan rows sharing a batch member's `id`, which `validate_plan` reports
    # as `duplicate_id` and `run_package` does not gate — and as the tripwire for
    # lowering the cap or adding a fifth slot. Kept for `report_batch`'s reason
    # (#290): a guard whose absence is silent is worth the lines even when today's
    # arithmetic makes it moot. The case that fires *constantly* is
    # `slot_unreferenceable` above, not this one.
    dropped_batch = [c for c in dropped if c.illus_id in slot_of]
    # Defined rather than derived by subtracting one length from another:
    # `dropped_batch ⊆ dropped` is what would keep a difference non-negative, and
    # `if capped:` on a negative would print "-1 further ingested illustration(s)".
    capped = sum(1 for c in dropped if c.illus_id not in slot_of)

    # An illustration is never in its own chain, so its own slot is not a slot
    # this list could have carried — counting it would tell every batch member's
    # prompt that the batch is one short.
    expected_slots = [cid for cid in slot_of if cid != illus_id]
    listed_slots = [c.illus_id for c in eligible[:_MAX_PRIOR_REFERENCES]
                    if c.illus_id in slot_of and c.illus_id != illus_id]

    if excluded_no_prior:
        note(f'{len(excluded_no_prior)} ingested illustration(s) are not listed '
             f'because --no-prior-refs was passed ({_and_more_files(excluded_no_prior)}): '
             f'this build inherits nothing from the existing art.')
    for kind, rels in excluded_stale.items():
        note(f'{len(rels)} ingested illustration(s) are **not** listed '
             f'({_and_more_files(rels)}). '
             f'{_STALE_KIND_CLAUSES[kind].format(cutoff=canon_cutoff)} They '
             f'were directed by canon that has since been rewritten, so using '
             f'them would teach the new render the drift the new canon exists '
             f'to remove. Re-render them from the current canon (`storyforge '
             f'illustrate --diagnose` gives the order), then re-run {rerun}.')

    if slot_unreferenceable and not no_prior_refs:
        described = ', '.join(
            f'{slot_of[cid]} — {why}'
            for cid, why in slot_unreferenceable.items())
        log(f'WARNING: {illus_id}: {len(slot_unreferenceable)} anchor-batch '
            f'image(s) exist but cannot be referenced ({described}).')
        note(f'{len(slot_unreferenceable)} image(s) from the **anchor batch** '
             f'have art that this list cannot use: {described}. Those are the '
             f'renders phase 1 exists to approve, so the chain is not what you '
             f'signed off on — fix those before the churn rather than '
             f'generating against the substitutes above.')
    if dropped_batch:
        described = ', '.join(f'`{c.path}` ({slot_of[c.illus_id]})'
                              for c in dropped_batch)
        log(f'  {illus_id}: {len(dropped_batch)} image(s) from the anchor batch '
            f'did not fit the reference list ({described}) — it stops at '
            f'{_MAX_PRIOR_REFERENCES} prior illustration(s).')
        note(f'{len(dropped_batch)} image(s) from the **anchor batch** are '
             f'eligible but not listed, because the list stops at '
             f'{_MAX_PRIOR_REFERENCES} prior illustration(s): {described}. '
             f'Those are the renders phase 1 exists to approve, so a chain '
             f'missing them references a description where it could reference '
             f'the real thing.')
    if capped:
        log(f'  {illus_id}: {capped} further ingested illustration(s) were not '
            f'listed — the reference list stops at {_MAX_PRIOR_REFERENCES} '
            f'prior illustration(s).')
        # The closing clause is a claim about the batch, so it is *checked*
        # rather than asserted. Unconditional, it was an affirmative falsehood on
        # the ordinary partly-re-rendered batch — 0 of 4 approved images in the
        # list, under a sentence saying the list was what was approved, in the
        # one section whose job is telling the author it is thinner than it looks
        # (#311 review). And when `dropped_batch` is non-empty it contradicted
        # the note directly above it.
        assured = (
            'The anchor batch is ranked ahead of plan order, so what is listed '
            'is what was approved.'
            if expected_slots and len(listed_slots) == len(expected_slots)
            and not dropped_batch
            else f'{len(listed_slots)} of {len(expected_slots)} anchor-batch '
                 f'image(s) are in this list; the batch is ranked ahead of plan '
                 f'order, so the rest were excluded or not yet rendered rather '
                 f'than crowded out.' if expected_slots
            else 'No anchor-batch image is filled, so nothing was ranked ahead '
                 'of plan order.')
        note(f'{capped} further ingested illustration(s) are eligible but not '
             f'listed: the list stops at {_MAX_PRIOR_REFERENCES} prior '
             f'illustration(s), because past that a model starts averaging them '
             f'rather than matching them. {assured}')

    prior = [r for r in references if r[0] != cover]
    if not prior:
        if references:
            log(f'  {illus_id}: reference chain is cover-only'
                + (f' ({skipped_stale} prior illustration(s) excluded)'
                   if skipped_stale else
                   ' (no prior illustration is ingested yet)') + '.')
            note('This list is **cover-only**. '
                 + (f'{skipped_stale} ingested illustration(s) exist and were '
                    f'excluded for the reasons above — that is not the same as '
                    f'having nothing to reference.'
                    if skipped_stale else
                    'No illustration has been ingested yet, so the first '
                    'renders establish the look for everything after them.'))
        else:
            log(f'  {illus_id}: no reference images at all'
                + (f' ({skipped_stale} prior illustration(s) excluded)'
                   if skipped_stale else '')
                + ' — nothing anchors this prompt\'s style, so it establishes '
                  'the look for everything that references it.')
            note('There are **no reference images at all**'
                 + (f', and {skipped_stale} ingested illustration(s) were '
                    f'excluded for the reasons above'
                    if skipped_stale else '')
                 + '. Nothing anchors style or likeness, so whatever is '
                   'rendered first sets the look for the whole book.')
    return references


#: One plural sentence per stale category. Written per kind rather than by
#: splicing `stale_render_reason` into a plural frame: that reason is written
#: about one row and opens "its `ingested_at` is ...", which read as a grammar
#: error mid-aggregate — in the section whose only product is the author's trust
#: in it. `''` cannot occur (a row with no kind is not excluded) and is present
#: so the mapping is total over the Literal.
_STALE_KIND_CLAUSES: dict['ill.StaleKind', str] = {
    'no_date': 'None of them carries an `ingested_at`, so they predate ingest '
               'timestamps and therefore the canon last updated {cutoff}.',
    'unparseable_date': 'Each carries an `ingested_at` that is not an ISO date, '
                        'so none of them can be shown to postdate the canon '
                        'last updated {cutoff}.',
    'predates_canon': 'All of them were ingested before the canon was last '
                      'updated {cutoff}.',
    '': 'They predate the canon last updated {cutoff}.',
}


def _and_more_files(paths: list[str]) -> str:
    """Name the first few excluded files and count the rest.

    `packet._and_more` for paths rather than ids. The cap is what makes an
    aggregated note readable: on the book this was filed about seventeen files
    shared one cause, and seventeen backticked paths mid-sentence is not
    meaningfully better than the seventeen paragraphs it replaced.
    """
    named = ', '.join(f'`{p}`' for p in paths[:packet._MAX_NAMED_IDS])
    rest = len(paths) - packet._MAX_NAMED_IDS
    return f'{named} and {rest} more' if rest > 0 else named


def _relevant_anchors(anchors: dict[str, str],
                      row: dict[str, str]) -> dict[str, str]:
    """Narrow the anchor set to what this illustration actually shows.

    Sending every anchor in the book would spend tokens on a cast that isn't in
    the frame, and invites the model to include them. Falls back to all anchors
    when the row names none, since an unfiltered anchor set is a smaller
    failure than a missing one.

    That fallback is silent when `canon_refs` is simply empty (nothing was
    asked for). Every `canon_refs` entry that matched no anchor key is logged
    as a WARNING, whether some others matched or not. Anchor keys are
    canon_ids now (task 4); a plan row still carrying a pre-canon display name
    (e.g. "The village and Great Lamp" instead of "great-lamp") matches
    nothing, and the unfiltered fallback would otherwise send the whole cast
    at full token cost with no sign that the row needs migrating.

    The *partial* mismatch is the one that actually loses art direction, and
    it used to be silent: a row naming `nora;great-lamp` where only `nora`
    resolves narrows to Nora alone, and the lamp is then rendered with no
    anchor in every illustration that shows it. Nothing else catches that —
    an id with no canon anchor is by design not a
    `_direction_anchor_mismatches` finding, and `canon_unfilled_template` is
    info severity, which `build_cleanup_report` leaves out of action items.
    """
    named = {n.strip().lower()
             for n in ill._split_array(row.get('canon_refs', ''))}
    if not named:
        return anchors
    matched = {name: text for name, text in anchors.items()
               if name.strip().lower() in named}
    unmatched = sorted(named - {n.strip().lower() for n in matched})
    if unmatched:
        tail = ('sending the full anchor set instead of narrowing to this '
                'cast' if not matched else
                'those entities are art-directed with no continuity anchor')
        log(f'WARNING: canon_refs {unmatched!r} matched no known anchor '
            f'(illustration {row.get("id", "").strip() or "?"}); {tail} — '
            f'check whether this plan row still uses pre-canon display names, '
            f'or whether those canon files are still TODO scaffolds')
    if matched:
        return matched
    return anchors


# ============================================================================
# --ingest
# ============================================================================

def run_ingest(project_dir: str, source: str, dry_run: bool) -> int:
    """Ingest rendered files, record digests, and embed markers."""
    candidates = _collect_candidates(source)
    if not candidates:
        log(f'ERROR: no image files found at {source}')
        return 1

    plan = ill.read_plan(project_dir)
    if not plan:
        log('ERROR: no illustration plan. Run `--plan` first — ingest matches '
            'files to plan rows, so there is nothing to match against.')
        return 1

    known_ids = {r['id'].strip() for r in plan}
    matched: list[tuple[str, str]] = []
    unmatched: list[str] = []
    for path in candidates:
        stem = os.path.splitext(os.path.basename(path))[0]
        if stem in known_ids:
            matched.append((stem, path))
        else:
            unmatched.append(path)

    for path in unmatched:
        log(f'WARNING: {os.path.basename(path)} does not match any plan id — '
            f'skipping. Rename it to <illustration-id>{os.path.splitext(path)[1]} '
            f'or pass the file directly.')

    if not matched:
        log('ERROR: nothing to ingest — no filename matched a plan id.')
        log(f'Plan ids: {", ".join(sorted(known_ids))}')
        return 1

    os.makedirs(ill.illustrations_dir(project_dir), exist_ok=True)
    status_before = {r['id'].strip(): (r.get('status') or '').strip()
                     for r in plan}
    ingested = 0
    ingested_ids: set[str] = set()
    for illus_id, src in matched:
        if dry_run:
            log(f'[dry-run] would ingest {src} → '
                f'{ill.default_asset_rel(illus_id, os.path.splitext(src)[1])}')
            continue

        # Truncation is checked before anything is written. An aborted render
        # download leaves a header-valid stub whose dimensions parse fine, and
        # overwriting good art with it is unrecoverable.
        incomplete = ill.incomplete_image_reason(src)
        if incomplete:
            log(f'WARNING: {src} {incomplete}. Skipping {illus_id}; any '
                f'existing render is untouched. Re-download it.')
            continue

        probe = ill.probe_image(src)
        dims = probe['dimensions']
        if dims is None:
            log(f'WARNING: {src} {probe["reason"]} — skipping {illus_id}')
            continue

        rel = ill.default_asset_rel(illus_id, os.path.splitext(src)[1])
        dest = os.path.join(project_dir, rel)
        if os.path.abspath(src) != os.path.abspath(dest):
            previous = _existing_render(project_dir, illus_id, dest)
            ill.replace_file(src, dest)
            if previous:
                log(f'  replacing {illus_id}: {previous} → '
                    f'{dims[0]}×{dims[1]}')

        digest = ill.sha256_of(dest)
        # Ingest is the documented revival endpoint for a retired row, so
        # superseded → ingested is correct — but it changes the publishable set,
        # and a stale leftover file in the ingest directory would otherwise
        # un-retire an illustration with nothing said. Same class of silent
        # change the --prompts status guard closes.
        if status_before.get(illus_id) == 'superseded':
            log(f'  {illus_id} was retired (status=superseded); this render '
                f'un-retires it — status superseded → ingested, its marker is '
                f're-embedded, and it ships again. If that was not intended, '
                f'set status back to superseded and re-run --embed.')
        # `ingested_at` is what lets --prompts tell a render directed by the
        # current canon from one that predates it. Stamped on every ingest,
        # including a re-ingest of the same id, because a replacement render is
        # exactly the event that makes the old date wrong.
        #
        # `scene_digest` is the same idea one level down: the prose this render
        # was made from, so "the prose changed under this image" becomes
        # detectable (`prose_changed`). Empty when the scene has no file, which
        # is a legitimate state for a row whose scene is not drafted.
        row_scene = next((r.get('scene_id', '').strip() for r in plan
                          if r['id'].strip() == illus_id), '')
        scene_digest = ill.scene_prose_digest(project_dir, row_scene)
        if row_scene and not scene_digest:
            log(f'  {illus_id}: scene {row_scene} has no file, so no '
                f'scene_digest was recorded — prose drift under this render '
                f'will not be detectable until it does')
        _update_row(project_dir, illus_id, {
            'asset_file': rel, 'sha256': digest, 'status': 'ingested',
            'width': str(dims[0]), 'height': str(dims[1]),
            'ingested_at': date.today().isoformat(),
            'scene_digest': scene_digest,
        })
        log(f'  {illus_id} → {rel} ({dims[0]}×{dims[1]}, '
            f'sha256 {digest[:12]}…)')
        ingested += 1
        ingested_ids.add(illus_id)

    if dry_run:
        return 0

    log(f'Ingested {ingested} illustration(s)')
    if ingested < len(matched):
        log(f'WARNING: {len(matched) - ingested} of {len(matched)} matched '
            f'file(s) were rejected. Nothing was recorded for them.')

    exit_code = 0 if ingested else 1
    if ingested:
        # Embed only what was actually ingested — a rejected file has no art to
        # point a marker at. And propagate embed's status: a drifted anchor
        # during ingest is exactly as bad as one during --embed.
        exit_code = run_embed(project_dir, ingested_ids, dry_run=False) or exit_code
    return exit_code


def _existing_render(project_dir: str, illus_id: str, dest: str) -> str:
    """Describe the render about to be replaced, for the log. '' if none.

    Overwriting art is legitimate — re-rendering is the normal loop — but it
    should never be silent, because the previous file is not recoverable from
    the working tree once replaced.
    """
    if not os.path.isfile(dest):
        return ''
    dims = ill.image_dimensions(dest)
    shape = f'{dims[0]}×{dims[1]}' if dims else 'unreadable'
    return f'{shape}, sha256 {ill.sha256_of(dest)[:12]}…'


def _collect_candidates(source: str) -> list[str]:
    """Return image files at *source*, whether a file or a directory."""
    if os.path.isfile(source):
        return [source] if ill.is_supported_image(source) else []
    if os.path.isdir(source):
        return [os.path.join(source, name)
                for name in sorted(os.listdir(source))
                if ill.is_supported_image(os.path.join(source, name))
                and os.path.isfile(os.path.join(source, name))]
    return []


# ============================================================================
# --embed
# ============================================================================

def run_embed(project_dir: str, ids: set[str] | None, dry_run: bool) -> int:
    """Insert markers into scene files from the plan."""
    all_rows = ill.read_plan(project_dir)
    if ids is not None:
        all_rows = [r for r in all_rows if r['id'].strip() in ids]

    superseded = [r for r in all_rows
                  if (r.get('status') or '').strip() == 'superseded']
    rows = [r for r in all_rows
            if (r.get('status') or '').strip() != 'superseded']

    # Retiring an illustration has to remove its marker, not merely skip the
    # row: a marker left behind keeps pointing at art that must not render.
    unembedded = _unembed_superseded(project_dir, superseded, dry_run)

    if not rows:
        if unembedded:
            return 0
        log('No plan rows to embed.')
        return 0

    embedded = 0
    skipped = 0
    for row in rows:
        illus_id = row['id'].strip()
        scene_id = (row.get('scene_id') or '').strip()
        scene_path = os.path.join(project_dir, 'scenes', f'{scene_id}.md')
        if not os.path.isfile(scene_path):
            log(f'WARNING: {illus_id}: scene {scene_id!r} has no file — '
                f'skipping')
            skipped += 1
            continue

        with open(scene_path, encoding='utf-8') as f:
            original = f.read()

        result = ill.insert_marker(original, row)
        if result['error']:
            log(f'WARNING: {illus_id}: {result["error"]}')
            hint = _nearest_anchor_hint(original, row)
            if hint:
                log(f'         nearest candidate: "{hint}"')
            skipped += 1
            continue
        if not result['changed']:
            continue

        if dry_run:
            log(f'[dry-run] would embed {illus_id} in {scene_id}')
            embedded += 1
            continue

        with open(scene_path, 'w', encoding='utf-8') as f:
            f.write(result['text'])
        log(f'  embedded {illus_id} in scenes/{scene_id}.md')
        embedded += 1

    log(f'Embedded {embedded} marker(s)'
        + (f'; {skipped} skipped' if skipped else ''))
    if skipped:
        log(f'WARNING: {skipped} illustration(s) were not embedded and will '
            f'not appear in the book. Fix the reported anchors, then re-run '
            f'--embed.')
        return 1
    return 0


#: Words too common to signal that a line is the revised anchor.
_HINT_STOPWORDS = frozenset({
    'the', 'and', 'but', 'for', 'her', 'his', 'she', 'him', 'they', 'them',
    'that', 'this', 'with', 'from', 'into', 'was', 'were', 'had', 'has',
    'not', 'you', 'your', 'its', 'their', 'been', 'then', 'than', 'when',
    'what', 'who', 'how', 'all', 'one', 'out', 'off', 'own', 'too',
})


def _unembed_superseded(project_dir: str, rows: list[dict[str, str]],
                        dry_run: bool) -> int:
    """Remove markers for superseded plan rows. Returns how many were removed."""
    removed = 0
    for row in rows:
        illus_id = row['id'].strip()
        scene_id = (row.get('scene_id') or '').strip()
        scene_path = os.path.join(project_dir, 'scenes', f'{scene_id}.md')
        if not os.path.isfile(scene_path):
            continue
        with open(scene_path, encoding='utf-8') as f:
            original = f.read()
        text, changed = ill.remove_marker(original, illus_id)
        if not changed:
            continue
        if dry_run:
            log(f'[dry-run] would remove the superseded marker {illus_id} '
                f'from {scene_id}')
        else:
            with open(scene_path, 'w', encoding='utf-8') as f:
                f.write(text)
            log(f'  removed superseded marker {illus_id} from '
                f'scenes/{scene_id}.md')
        removed += 1
    return removed


def _nearest_anchor_hint(scene_text: str, row: dict[str, str]) -> str:
    """Suggest the closest line to a failed anchor, to speed up re-anchoring.

    Content-word overlap rather than edit distance — after a revision the
    surviving phrase usually keeps the anchor's nouns even when the wording
    around them changed. Substring hits count, because the revision that broke
    the anchor is often a compound ("sill" becoming "windowsill").
    """
    anchor = (row.get('anchor') or '').strip()
    if not anchor:
        return ''
    wanted = {w.lower().strip('.,;:!?"\'—')
              for w in anchor.split() if len(w) > 2}
    wanted -= _HINT_STOPWORDS
    if not wanted:
        return ''

    # A short anchor has few content words to match on, so requiring two hits
    # would suppress the hint exactly when the author most needs it.
    threshold = 1 if len(wanted) <= 2 else 2

    best, best_score = '', 0
    for line in ill.strip_markers(scene_text).splitlines():
        if not line.strip():
            continue
        lowered = line.lower()
        words = {w.strip('.,;:!?"\'—') for w in lowered.split()}
        score = sum(1 for w in wanted
                    if w in words or (len(w) > 3 and w in lowered))
        if score > best_score:
            best, best_score = line.strip(), score
    if best_score < threshold:
        return ''
    return best[:120]


# ============================================================================
# Shared helpers
# ============================================================================

def _update_row(project_dir: str, illus_id: str,
                updates: dict[str, str]) -> bool:
    """Apply updates to one plan row and rewrite the CSV.

    Returns False when no such row exists — which is reachable if the plan is
    edited while a multi-illustration run is in flight. Previously this rewrote
    the file unchanged and returned normally, so a prompt file or a copied
    render would land on disk while its status update evaporated.
    """
    rows = ill.read_plan(project_dir)
    for row in rows:
        if row['id'].strip() == illus_id:
            row.update(updates)
            ill.write_plan(project_dir, rows)
            return True
    log(f'WARNING: {illus_id} is no longer in the illustration plan — its '
        f'file was written but the plan could not record it. The plan may '
        f'have been edited mid-run.')
    return False


def _sanitize_cell(value: str) -> str:
    """Strip pipes and newlines before writing to a pipe-delimited CSV.

    An unsanitized `|` shatters the row at write time and is then silently
    dropped by the column-arity filter on the next read. Matches
    cmd_propose_summaries._sanitize_cell.
    """
    return value.replace('|', '/').replace('\n', ' ').replace('\r', '').strip()


def _slugify(value: str) -> str:
    """Coerce a proposed id into a kebab-case slug."""
    slug = re.sub(r'[^a-z0-9]+', '-', value.lower()).strip('-')
    return slug or 'illustration'


def _write_coaching_file(project_dir: str, filename: str, content: str,
                         dry_run: bool) -> int:
    """Write a coaching artifact to working/coaching/."""
    rel = os.path.join('working', 'coaching', filename)
    if dry_run:
        log(f'[dry-run] would write {rel}')
        return 0
    path = os.path.join(project_dir, rel)
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, 'w', encoding='utf-8') as f:
        f.write(content)
    log(f'Wrote {rel}')
    return 0


def _invoke(project_dir: str, prompt: str, operation: str, *,
            task_type: str, max_tokens: int, target: str = '') -> str:
    """Call the API, log the cost, and return the text (or '' on failure).

    A truncated response counts as a failure. An art-direction prompt cut off
    at max_tokens loses its Constraints section — the orientation directive and
    the no-text rule, the two things render_prompt_file exists to guarantee —
    and would otherwise be written to disk and marked `prompted`.
    """
    model = select_model(task_type)
    started = time.time()
    try:
        response = invoke(prompt, model, max_tokens, label=operation)
    except Exception as exc:  # noqa: BLE001 — surfaced to the author below
        log(f'WARNING: API call failed for {operation}: {exc}')
        return ''
    if not response:
        log(f'WARNING: API returned an empty response for {operation} '
            f'(model={model}). Nothing was written.')
        return ''
    if isinstance(response, dict) and response.get('error'):
        err = response['error']
        detail = err.get('message', err) if isinstance(err, dict) else err
        log(f'WARNING: API returned an error for {operation}: {detail}. '
            f'Not recording a cost entry.')
        return ''

    usage = extract_usage(response)
    log_operation(
        project_dir, operation, model,
        usage['input_tokens'], usage['output_tokens'],
        calculate_cost_from_usage(usage, model),
        duration_s=int(time.time() - started), target=target,
        cache_read=usage.get('cache_read', 0),
        cache_create=usage.get('cache_create', 0),
    )

    if response.get('stop_reason') == 'max_tokens':
        log(f'WARNING: {operation} was cut off at max_tokens '
            f'({usage["output_tokens"]} output tokens){f" for {target}" if target else ""} '
            f'— the response is incomplete and was discarded.')
        return ''
    return extract_text(response).strip()


def _story_context(project_dir: str) -> str:
    """Assemble the story context handed to the selection pass."""
    parts = []
    title = read_yaml_field('project.title', project_dir) or 'Untitled'
    genre = read_yaml_field('project.genre', project_dir) or ''
    parts.append(f'**Title:** {title}' + (f' · **Genre:** {genre}' if genre else ''))

    for rel, label, limit in (
        (os.path.join('reference', 'story-summary.md'), 'Story summary', 4000),
        (os.path.join('reference', 'spine.csv'), 'Spine', 4000),
        (os.path.join('reference', 'architecture.csv'), 'Architecture', 8000),
        (os.path.join('reference', 'themes.csv'), 'Themes', 2000),
        (os.path.join('reference', 'motif-taxonomy.csv'), 'Motifs', 2000),
        (os.path.join('reference', 'scenes.csv'), 'Scene map', 12000),
        (os.path.join('reference', 'chapter-map.csv'), 'Chapter map', 4000),
    ):
        text = _read_capped(os.path.join(project_dir, rel), limit)
        if text:
            parts.append(f'### {label}\n\n```\n{text}\n```')
    return '\n\n'.join(parts)


def _canon_context(project_dir: str) -> str:
    """Assemble the canon context handed to the art-direction pass."""
    parts = []
    for rel, label, limit in (
        (os.path.join('reference', 'character-bible.md'), 'Characters', 6000),
        (os.path.join('reference', 'world-bible.md'), 'World', 6000),
    ):
        text = _read_capped(os.path.join(project_dir, rel), limit)
        if text:
            parts.append(f'### {label}\n\n{text}')
    return '\n\n'.join(parts) or '(no bibles found)'


def _style_note(project_dir: str) -> str:
    """Return the house-style note, if the author recorded one.

    The cover prompt log is the best available statement of a book's visual
    register — it is the one image whose direction was already settled.
    """
    return _read_capped(
        os.path.join(project_dir, 'manuscript', 'assets', 'cover-prompt.md'),
        3000,
    )


def _scene_split(project_dir: str, row: dict[str, str]) -> ill.SceneSplit:
    """Return the scene cut at the point this illustration appears.

    `split_at_position` does the normalizing — markers and frontmatter both — so
    the art-direction model sees the scene as a reader would and every consumer of
    the predicate resolves the same offset for a row.

    The cut, rather than a window centred on the anchor, is #308's fix: the model
    used to receive prose from both sides of the marker with nothing saying which
    side was which, and reliably wrote the image of the beat just after it. A
    scene that is missing, unreadable, or undrafted comes back ``unknown`` with a
    named ``cause``, never as an empty ``unread`` — which would tell the request
    there is nothing after this illustration.
    """
    scene_id = (row.get('scene_id') or '').strip()
    path = os.path.join(project_dir, 'scenes', f'{scene_id}.md')
    if not os.path.isfile(path):
        # No `read` placeholder: the sentinel `'(scene file not found)'` used to
        # be printed to the model under a heading calling it the scene's prose.
        # `state`, `cause`, and `error` already say what happened.
        return {'state': 'unknown', 'offset': None, 'cause': 'scene_missing',
                'read': '', 'unread': '', 'next_sentence': '',
                'error': f'scene file for {scene_id!r} is not in scenes/'}
    try:
        with open(path, encoding='utf-8') as f:
            text = f.read()
    except (OSError, UnicodeDecodeError) as exc:
        # Phase 1 builds every request, so a raise here aborts the whole run
        # before a single prompt is written. An unreadable scene is an unresolved
        # position like any other.
        return {'state': 'unknown', 'offset': None, 'cause': 'scene_unreadable',
                'read': '', 'unread': '', 'next_sentence': '',
                'error': f'could not read scenes/{scene_id}.md: {exc}'}
    return ill.split_at_position(text, row)


def _read_capped(path: str, limit: int) -> str:
    """Read a file, truncated to *limit* characters."""
    if not os.path.isfile(path):
        return ''
    with open(path, encoding='utf-8') as f:
        text = f.read()
    return text[:limit]


if __name__ == '__main__':
    sys.exit(main() or 0)
