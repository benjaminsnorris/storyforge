"""storyforge illustrate — plan, art-direct, ingest, and embed interior illustrations.

Nine phases, each its own flag:

  --direction  Write the book-level art direction: format, visual promise,
               recurring visual language, content limits, continuity anchors.
               Authored once; constrains every illustration.
  --plan       Decide where illustrations belong. Deterministic pre-pass, then
               an LLM pass that argues against those findings.
  --state      Write the visual-state transition log: what changes on schedule,
               as opposed to the canon tier for what must never change.
  --audit      Read the prose against that matrix and report contradictions.
               Read-only with respect to the prose and the log.
  --prompts    Turn planned rows into image-generation prompts.
  --package    Assemble manuscript/illustration-packet/ — one bundle a
               long-running generation session works through, instead of
               fifteen separate prompt pastes. Assembly only, no API calls.
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
from typing import TypedDict

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

# Excerpt handed to the art-direction prompt. Enough to establish the beat and
# its immediate surroundings without paying to re-send the whole scene.
_EXCERPT_CHARS = 2400


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
    phase.add_argument('--package', action='store_true',
                       help='Assemble the handoff packet in '
                            'manuscript/illustration-packet/ (no API calls)')
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

    phases = [args.direction, args.plan, args.prompts, bool(args.ingest),
              args.embed, args.diagnose, args.review, args.state, args.audit,
              args.package]
    if not any(phases):
        log('Nothing to do. Pick a phase: --direction, --plan, --prompts, '
            '--package, --ingest PATH, --embed, --state, --audit, --diagnose, '
            'or --review.')
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
    if args.prompts:
        exit_code = run_prompts(project_dir, coaching, _id_filter(args.ids),
                                args.dry_run,
                                no_prior_refs=args.no_prior_refs) or exit_code
    if args.package:
        exit_code = run_package(project_dir, args.dry_run) or exit_code
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
    rows = ill.read_plan(project_dir)
    if not rows:
        log('No illustration plan yet. Run `storyforge illustrate --plan` to '
            'propose one.')
        # The state rung *and its findings* are reported even with no plan: the
        # transition log is about the book, not about the illustrations, and the
        # skill now tells authors to build it before the plan. Returning 0 here
        # hid a `state_unknown_scene` error entirely.
        findings = ill.validate_plan(project_dir)
        _report_state_rung(project_dir, findings)
        return _report_findings(findings)

    report = ill.plan_report(project_dir)
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
            mark = '*' if step['status'] == 'ingested' else ' '
            key = '  <- visual key' if step['is_visual_key'] else ''
            locks = (f'  locks: {", ".join(step["locks"])}'
                     if step['locks'] else '')
            log(f'  {mark} {i:2}. {step["id"]}{key}{locks}')

    _report_anchor_batch(packet.anchor_batch(project_dir),
                         _unrendered_ids(project_dir))

    findings = ill.validate_plan(project_dir)
    _report_state_rung(project_dir, findings)
    return _report_findings(findings)


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

    if dry_run:
        for row in rows:
            log(f'[dry-run] would write '
                f'{ill.default_prompt_rel(row["id"].strip())}')
        return 0

    needs_api = coaching in ('full', 'coach')
    if needs_api and not os.environ.get('ANTHROPIC_API_KEY'):
        log('ERROR: ANTHROPIC_API_KEY is not set. Art direction in '
            f'{coaching} coaching requires an API key. Set it and re-run, or '
            'use --coaching strict for a scaffold.')
        return 1

    os.makedirs(ill.prompts_dir(project_dir), exist_ok=True)
    canon_ctx = _canon_context(project_dir)
    style_note = _style_note(project_dir)
    # Read once for the whole run. Every request is built before any call is
    # made, so a stub a later row's response proposes cannot reach the others
    # — which is exactly why _warn_unanchored_rows runs first, while the author
    # can still fix it for free.
    anchors = pi.anchors_for_prompt(project_dir)
    labels = _anchor_labels(project_dir)
    if needs_api:
        _warn_unanchored_rows(rows, anchors)
    cutoff = _reference_cutoff(project_dir, no_prior_refs)
    written = 0
    failed: list[str] = []

    # Phase 1 — assemble every request. Sequential and cheap (file reads
    # only), which keeps the reference and anchor warnings in plan order.
    jobs: list[_PromptJob] = []
    for row in rows:
        illus_id = row['id'].strip()
        jobs.append({
            'id': illus_id,
            'row': row,
            'references': _references_for(
                project_dir, illus_id, plan=plan, canon_cutoff=cutoff,
                no_prior_refs=no_prior_refs),
            'aspect': pi.aspect_for_row(row),
            'request': pi.build_art_direction_request(
                row=row,
                scene_excerpt=_scene_excerpt(project_dir, row),
                character_anchors=_relevant_anchors(anchors, row),
                canon_context=canon_ctx, direction=direction,
                style_note=style_note, anchor_labels=labels,
            ) if needs_api else '',
        })

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
            aspect=job['aspect'],
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
# --package
# ============================================================================

def run_package(project_dir: str, dry_run: bool) -> int:
    """Assemble `manuscript/illustration-packet/` — six files, no API calls.

    Regenerated wholesale, so the packet is a render and never hand-edited: the
    author's edits belong in the plan, the transition log, or the canon files,
    all of which this reads.

    Nothing here blocks. A warning the author has considered is theirs to
    override, and refusing to build the packet over a never-run audit would
    strand them behind a check they may have a reason to skip — so every gap is
    logged as a WARNING *and* written into README.md, which is the copy they
    will still have in front of them an hour later.
    """
    contents = packet.resolve(project_dir)
    grid = packet.state_grid(project_dir)
    batch = packet.anchor_batch(project_dir)
    unrendered = _unrendered_ids(project_dir)
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
            unrendered=unrendered),
        'canon.md': pp.render_canon(
            book_level=contents['book_level'], anchors=contents['anchors'],
            labels=_anchor_labels(project_dir)),
        'visual-state.md': pp.render_visual_state(
            grid=grid, illustrated=illustrated),
        'illustrations.md': pp.render_illustrations(
            entries=contents['entries']),
        'reference-images.md': pp.render_reference_images(
            references=contents['references']),
        'acceptance.md': pp.render_acceptance(aspects=aspects),
    }

    if dry_run:
        for name in packet.PACKET_FILES:
            log(f'[dry-run] would write '
                f'{os.path.join(packet.PACKET_DIR, name)}')
        for gap in contents['gaps']:
            log(f'[dry-run] WARNING: {gap}')
        return 0

    os.makedirs(packet.packet_dir(project_dir), exist_ok=True)
    for name in packet.PACKET_FILES:
        with open(packet.packet_file(project_dir, name), 'w',
                  encoding='utf-8') as f:
            f.write(files[name])

    log(f'Wrote {len(packet.PACKET_FILES)} file(s) to '
        f'{packet.PACKET_DIR}/ — {len(contents["entries"])} illustration(s), '
        f'{len(contents["anchors"])} continuity anchor(s)')
    for gap in contents['gaps']:
        log(f'  WARNING: {gap}')
    if contents['gaps']:
        log(f'  {len(contents["gaps"])} gap(s) above are also written into '
            f'{os.path.join(packet.PACKET_DIR, "README.md")}, so the packet '
            f'says what it cannot tell you.')
    _report_anchor_batch(batch, unrendered)
    log('Render and approve the anchor batch, ingest those, then re-run '
        '--package so the rest can reference real images.')
    return 0


def _unrendered_ids(project_dir: str) -> list[str]:
    """Plan ids that have not reached `ingested`, in reading order."""
    return [row['id'].strip()
            for row in packet.rows_in_reading_order(project_dir)
            if (row.get('status') or '').strip() != 'ingested']


def _report_anchor_batch(batch: packet.AnchorBatch,
                         unrendered: list[str]) -> None:
    """Log the four slots and every disclosure.

    The fallback notes are WARNING lines rather than plain output: a guessed
    darkest slot is a claim the author has to either confirm or correct, and it
    reads as a decision unless something says otherwise.
    """
    log('Anchor batch — render and approve these before the rest:')
    for slot, label in packet.BATCH_SLOTS:
        illus_id = batch[slot]  # type: ignore[literal-required]
        if not illus_id:
            log(f'  {label}: (unfilled)')
            continue
        mark = '' if illus_id in unrendered else '  [ingested]'
        log(f'  {label}: {illus_id}{mark}')
    for note in batch['fallback']:
        log(f'  WARNING: {note}')


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
    row) and from the epub, PDF, and web book (`FILED_STATUSES` gates marker
    resolution) while leaving the file on disk — invisible to `--diagnose`,
    because an unrendered row is legitimate in-flight state.
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


def _reference_cutoff(project_dir: str, no_prior_refs: bool) -> str:
    """The canon date a prior render must post-date to serve as a reference.

    '' means no cutoff — either the author asked for cover-only references
    anyway, or no canon file carries a parseable `canon_updated`, in which case
    there is no governing direction for art to predate.
    """
    from storyforge import canon as canon_mod
    if no_prior_refs:
        log('--no-prior-refs: prompts will reference the cover only, not any '
            'previously ingested illustration.')
        return ''
    cutoff = canon_mod.newest_canon_updated(project_dir)
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


#: Reference images sent per prompt. Enough to anchor style and likeness; more
#: than this and the model starts averaging them.
_MAX_REFERENCES = 4


def _references_for(project_dir: str, illus_id: str, *,
                    plan: list[dict[str, str]] | None = None,
                    canon_cutoff: str = '',
                    no_prior_refs: bool = False) -> list[tuple[str, str]]:
    """Build the labeled reference list for an illustration.

    Prior ingested illustrations plus the cover are what hold a book's art
    together visually — a prompt with no style reference produces an image that
    belongs to no book in particular. Walked in plan order, which is usually but
    not necessarily render order — the chain only needs *some* prior art to
    anchor style, not a specific one.

    The cover reference is the *artwork* (`cover-illustration.png`), not the
    typeset cover — using the art as a style reference is right, and the two
    files are deliberately different.

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
    """
    references: list[tuple[str, str]] = []
    cover = os.path.join('manuscript', 'assets', 'cover-illustration.png')
    if os.path.isfile(os.path.join(project_dir, cover)):
        references.append((cover, 'cover art (sets the house style)'))

    rows = plan if plan is not None else ill.read_plan(project_dir)
    skipped_stale = 0
    for row in rows:
        if len(references) >= _MAX_REFERENCES:
            break
        if row['id'].strip() == illus_id:
            continue
        if (row.get('status') or '').strip() != 'ingested':
            continue
        rel = (row.get('asset_file') or '').strip()
        if not rel or not os.path.isfile(os.path.join(project_dir, rel)):
            continue
        if no_prior_refs:
            skipped_stale += 1
            continue
        if canon_cutoff:
            stale_reason = _stale_reference_reason(row, canon_cutoff)
            if stale_reason:
                log(f'WARNING: not referencing {rel} for {illus_id} — '
                    f'{stale_reason}. Re-render it from the current canon '
                    f'(see `storyforge illustrate --diagnose` for the render '
                    f'order), or pass --no-prior-refs to build this prompt '
                    f'from the cover alone.')
                skipped_stale += 1
                continue
        references.append((rel, 'prior illustration (style continuity)'))

    prior = [r for r in references if r[0] != cover]
    if not prior:
        if references:
            log(f'  {illus_id}: reference chain is cover-only'
                + (f' ({skipped_stale} prior illustration(s) excluded)'
                   if skipped_stale else
                   ' (no prior illustration is ingested yet)') + '.')
        else:
            log(f'  {illus_id}: no reference images at all'
                + (f' ({skipped_stale} prior illustration(s) excluded)'
                   if skipped_stale else '')
                + ' — nothing anchors this prompt\'s style, so it establishes '
                  'the look for everything that references it.')
    return references


def _stale_reference_reason(row: dict[str, str], canon_cutoff: str) -> str:
    """Why this ingested row predates the canon, or '' if it does not.

    Compared as ISO dates (`canon.iso_date_or_empty`), which sort
    lexicographically. Strictly older: a render ingested the *same day* the
    canon was last touched is kept, because same-day is the normal incremental
    loop (write canon, render, ingest, prompt the next one) and date granularity
    cannot separate the two — treating same-day as stale would empty the chain
    on every ordinary run.
    """
    from storyforge import canon as canon_mod
    raw = (row.get('ingested_at') or '').strip()
    if not raw:
        return (f'its `ingested_at` is empty, so it predates ingest '
                f'timestamps and therefore the canon last updated '
                f'{canon_cutoff}')
    ingested = canon_mod.iso_date_or_empty(raw)
    if not ingested:
        return (f'its `ingested_at` ({raw!r}) is not an ISO date, so it '
                f'cannot be shown to postdate the canon last updated '
                f'{canon_cutoff}')
    if ingested < canon_cutoff:
        return (f'it was ingested {ingested}, before the canon was last '
                f'updated {canon_cutoff}')
    return ''


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


def _scene_excerpt(project_dir: str, row: dict[str, str]) -> str:
    """Return the prose around an illustration's anchor.

    Markers are stripped first — the art-direction model should see the scene
    as a reader would, not the build artifacts in it.
    """
    scene_id = (row.get('scene_id') or '').strip()
    path = os.path.join(project_dir, 'scenes', f'{scene_id}.md')
    if not os.path.isfile(path):
        return '(scene file not found)'
    with open(path, encoding='utf-8') as f:
        text = ill.strip_markers(f.read())

    anchor = (row.get('anchor') or '').strip()
    match = ill.find_anchor(text, anchor) if anchor else None
    if match is None:
        return text[:_EXCERPT_CHARS]

    half = _EXCERPT_CHARS // 2
    start = max(0, match['start'] - half)
    return text[start:match['end'] + half]


def _read_capped(path: str, limit: int) -> str:
    """Read a file, truncated to *limit* characters."""
    if not os.path.isfile(path):
        return ''
    with open(path, encoding='utf-8') as f:
        text = f.read()
    return text[:limit]


if __name__ == '__main__':
    sys.exit(main() or 0)
