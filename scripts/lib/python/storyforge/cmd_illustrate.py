"""storyforge illustrate — plan, art-direct, ingest, and embed interior illustrations.

Seven phases, each its own flag:

  --direction  Write the book-level art direction: format, visual promise,
               recurring visual language, content limits, continuity anchors.
               Authored once; constrains every illustration.
  --plan       Decide where illustrations belong. Deterministic pre-pass, then
               an LLM pass that argues against those findings.
  --prompts    Turn planned rows into image-generation prompts.
  --ingest     Bring rendered files in, record digests, embed markers.
  --embed      (Re)insert markers from the plan, without ingesting.
  --diagnose   Read-only plan health report, with the recommended render order.
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
import shutil
import sys
import time

from storyforge.api import (
    calculate_cost_from_usage, extract_text, extract_usage, invoke,
)
from storyforge.common import (
    CoachingLevel, detect_project_root, get_coaching_level, get_medium,
    install_signal_handlers, log, read_yaml_field, select_model,
)
from storyforge.costs import log_operation
from storyforge import illustrations as ill
from storyforge import prompts_illustrate as pi

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
    phase.add_argument('--ingest', metavar='PATH', default=None,
                       help='Ingest rendered illustration file(s) from a file '
                            'or directory')
    phase.add_argument('--embed', action='store_true',
                       help='(Re)insert markers into scene files from the plan')
    phase.add_argument('--diagnose', action='store_true',
                       help='Read-only plan health report + render order')
    phase.add_argument('--review', action='store_true',
                       help='Write the whole-sequence continuity checklist')

    parser.add_argument('--count', type=int, default=None,
                        help='Target illustration count for --plan '
                             '(default: recommended from book length)')
    parser.add_argument('--ids', type=str, default=None,
                        help='Comma-separated illustration ids to limit '
                             '--prompts or --embed to')
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
              args.embed, args.diagnose, args.review]
    if not any(phases):
        log('Nothing to do. Pick a phase: --direction, --plan, --prompts, '
            '--ingest PATH, --embed, --diagnose, or --review.')
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
                                args.dry_run) or exit_code
    if args.ingest:
        exit_code = run_ingest(project_dir, args.ingest,
                               args.dry_run) or exit_code
    if args.embed:
        exit_code = run_embed(project_dir, _id_filter(args.ids),
                              args.dry_run) or exit_code
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


# ============================================================================
# --diagnose
# ============================================================================

def run_diagnose(project_dir: str) -> int:
    """Report plan state and every incoherence, without writing anything."""
    rows = ill.read_plan(project_dir)
    if not rows:
        log('No illustration plan yet. Run `storyforge illustrate --plan` to '
            'propose one.')
        return 0

    report = ill.plan_report(project_dir)
    log(f'Illustration plan: {report["total"]} rows')
    for status in sorted(report['by_status']):
        log(f'  {status}: {report["by_status"][status]}')
    log(f'  embedded in scenes: {len(report["embedded"])}')
    if report['unembedded']:
        log(f'  not yet embedded: {", ".join(report["unembedded"])}')
    if report['next_unrendered']:
        log(f'  next to render: {report["next_unrendered"]}')

    steps = ill.render_order(project_dir)
    if steps:
        log('Recommended render order:')
        for i, step in enumerate(steps, 1):
            mark = '*' if step['status'] == 'ingested' else ' '
            key = '  <- visual key' if step['is_visual_key'] else ''
            locks = (f'  locks: {", ".join(step["locks"])}'
                     if step['locks'] else '')
            log(f'  {mark} {i:2}. {step["id"]}{key}{locks}')

    findings = ill.validate_plan(project_dir)
    if not findings:
        log('No problems found.')
        return 0

    errors = [f for f in findings if ill.severity_of(f['kind']) == 'error']
    log(f'{len(findings)} finding(s), {len(errors)} blocking:')
    for finding in findings:
        target = finding.get('id') or finding.get('file') or ''
        prefix = 'WARNING: ' if ill.severity_of(finding['kind']) == 'warning' else ''
        log(f'  {prefix}[{finding["kind"]}] {target}: {finding["detail"]}')

    # Warning-only findings are normal in-flight state (a drifted anchor after a
    # revision, a file mid-rename), so they must not fail the command — matching
    # how cmd_validate gates on `errors` alone.
    return 1 if errors else 0


# ============================================================================
# --direction
# ============================================================================

def run_direction(project_dir: str, coaching: CoachingLevel,
                  dry_run: bool) -> int:
    """Write the book-level art-direction document.

    Authored once, and it constrains every illustration — which makes it the
    highest-leverage artifact in the flow. A per-illustration prompt can be
    re-rolled cheaply; a book whose images disagree with each other has to be
    re-rendered wholesale.
    """
    path = ill.direction_path(project_dir)
    rel = os.path.relpath(path, project_dir)
    entities = _anchor_candidates(project_dir)

    if ill.has_direction(project_dir):
        missing = ill.missing_direction_sections(project_dir)
        if not missing:
            log(f'{rel} is already written. Edit it directly, or delete it to '
                f'start over.')
            return 0
        log(f'{rel} exists but these sections are empty or still placeholder: '
            f'{", ".join(missing)}')
        log('Fill them in, or delete the file to regenerate it.')
        return 0

    title = read_yaml_field('project.title', project_dir) or 'Untitled'

    if coaching in ('coach', 'strict'):
        content = pi.render_direction_template(
            title=title, coaching=coaching, entities=entities)
        return _write_direction(project_dir, content, rel, dry_run,
                               entities, coaching)

    if dry_run:
        log(f'[dry-run] would draft {rel} '
            f'({len(entities)} continuity anchor(s))')
        return 0

    if not os.environ.get('ANTHROPIC_API_KEY'):
        log('ERROR: ANTHROPIC_API_KEY is not set. Drafting art direction in '
            'full coaching requires an API key. Set it and re-run, or use '
            '--coaching coach for a template to fill in yourself.')
        return 1

    prompt = pi.build_direction_request(
        title=title,
        genre=read_yaml_field('project.genre', project_dir) or '',
        audience=read_yaml_field('project.audience', project_dir) or '',
        canon_context=_canon_context(project_dir),
        story_context=_story_context(project_dir),
        entities=entities,
    )
    body = _invoke(project_dir, prompt, 'illustrate-direction',
                   task_type='synthesis', max_tokens=8192)
    if not body:
        log('ERROR: no response from the API.')
        return 1

    content = f'# Illustration art direction — {title}\n\n{body.strip()}\n'
    return _write_direction(project_dir, content, rel, dry_run, entities,
                            coaching)


def _write_direction(project_dir: str, content: str, rel: str, dry_run: bool,
                     entities: list[str], coaching: CoachingLevel) -> int:
    """Write the direction document and report what still needs the author."""
    if dry_run:
        log(f'[dry-run] would write {rel}')
        return 0

    path = ill.direction_path(project_dir)
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, 'w', encoding='utf-8') as f:
        f.write(content)
    log(f'Wrote {rel}')

    anchors = ill.read_continuity_anchors(project_dir)
    log(f'  continuity anchors: {len(anchors)}')
    missing = ill.missing_direction_sections(project_dir)
    if missing:
        log(f'  needs your input: {", ".join(missing)}')
    if coaching == 'full':
        log('Read it before running --prompts — every illustration inherits '
            'whatever is in there, including anything it got wrong.')
    return 0


def _anchor_candidates(project_dir: str) -> list[str]:
    """Suggest what needs a continuity anchor, from the project's registries.

    Characters and locations come from their registries; both matter because
    art has to keep a place consistent as much as a face. The author adds
    creatures and signature props the registries don't model.
    """
    names: list[str] = []
    for filename, limit in (('characters.csv', 12), ('locations.csv', 6)):
        rows = ill._read_ref_csv(project_dir, filename)
        for row in rows[:limit]:
            name = (row.get('name') or row.get('id') or '').strip()
            if name and name not in names:
                names.append(name)
    return names


# ============================================================================
# --review
# ============================================================================

def run_review(project_dir: str, dry_run: bool) -> int:
    """Write the whole-sequence continuity review checklist.

    Per-illustration validation cannot see drift: each image is individually
    fine and the set is still inconsistent. This is the pass that looks at all
    of them together.
    """
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
        anchors=ill.read_continuity_anchors(project_dir),
        direction=ill.read_direction(project_dir),
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
                ids: set[str] | None, dry_run: bool) -> int:
    """Write an art-direction prompt file per planned illustration."""
    rows = [r for r in ill.read_plan(project_dir)
            if (r.get('status') or '').strip() in ('', 'planned')]
    if ids is not None:
        rows = [r for r in rows if r['id'].strip() in ids]

    if not rows:
        log('No rows at status=planned need prompts. '
            '(Use --ids to re-prompt a specific illustration.)')
        return 0

    log(f'Writing art direction for {len(rows)} illustration(s)')

    direction = ill.read_direction(project_dir)
    if not direction:
        log(f'WARNING: no {ill.DIRECTION_FILENAME} — these prompts will carry '
            f'no house style, and the illustrations will not look like they '
            f'belong to one book. Run `storyforge illustrate --direction` '
            f'first.')
    else:
        missing = ill.missing_direction_sections(project_dir)
        if missing:
            log(f'WARNING: {ill.DIRECTION_FILENAME} is missing: '
                f'{", ".join(missing)}')

    if coaching == 'strict':
        log('Coaching is strict — art direction is creative work. Writing the '
            'prompt scaffold with your constraints; fill in the five sections '
            'yourself.')

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
    canon = _canon_context(project_dir)
    style_note = _style_note(project_dir)
    written = 0
    failed: list[str] = []

    for row in rows:
        illus_id = row['id'].strip()
        anchors = pi.anchors_for_prompt(project_dir)
        references = _references_for(project_dir, illus_id)
        aspect = pi.aspect_for_row(row)

        if needs_api:
            request = pi.build_art_direction_request(
                row=row,
                scene_excerpt=_scene_excerpt(project_dir, row),
                character_anchors=_relevant_anchors(anchors, row),
                canon_context=canon, direction=direction,
                style_note=style_note,
            )
            body = _invoke(project_dir, request, 'illustrate-prompt',
                           task_type='creative', max_tokens=2048,
                           target=illus_id)
            if not body:
                log(f'WARNING: no art direction returned for {illus_id} — '
                    f'skipping (status stays `planned`)')
                failed.append(illus_id)
                continue
            body, new_anchors = pi.split_anchor_block(body)
            if new_anchors:
                added = pi.append_anchor_stubs(project_dir, new_anchors)
                if added:
                    log(f'  appended {len(added)} anchor(s) to '
                        f'{ill.DIRECTION_FILENAME} for review: '
                        f'{", ".join(added)}')
        else:
            body = _strict_prompt_scaffold(row)

        content = pi.render_prompt_file(
            row=row, body=body, references=references, aspect=aspect,
        )
        rel = ill.default_prompt_rel(illus_id)
        with open(os.path.join(project_dir, rel), 'w', encoding='utf-8') as f:
            f.write(content)

        _update_row(project_dir, illus_id,
                    {'prompt_file': rel, 'status': 'prompted'})
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


def _strict_prompt_scaffold(row: dict[str, str]) -> str:
    """Build the five-section scaffold for strict coaching — no prose."""
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


def _references_for(project_dir: str,
                    illus_id: str) -> list[tuple[str, str]]:
    """Build the labeled reference list for an illustration.

    Prior ingested illustrations plus the cover are what hold a book's art
    together visually — a prompt with no style reference produces an image that
    belongs to no book in particular. Earlier illustrations come first, so the
    references follow the render order that produced them.
    """
    references: list[tuple[str, str]] = []
    cover = os.path.join('manuscript', 'assets', 'cover-illustration.png')
    if os.path.isfile(os.path.join(project_dir, cover)):
        references.append((cover, 'cover art (sets the house style)'))

    for row in ill.read_plan(project_dir):
        if len(references) >= _MAX_REFERENCES:
            break
        if row['id'].strip() == illus_id:
            continue
        if (row.get('status') or '').strip() != 'ingested':
            continue
        rel = (row.get('asset_file') or '').strip()
        if rel and os.path.isfile(os.path.join(project_dir, rel)):
            references.append((rel, 'prior illustration (style continuity)'))

    return references


def _relevant_anchors(anchors: dict[str, str],
                      row: dict[str, str]) -> dict[str, str]:
    """Narrow the anchor set to what this illustration actually shows.

    Sending every anchor in the book would spend tokens on a cast that isn't in
    the frame, and invites the model to include them. Falls back to all anchors
    when the row names none, since an unfiltered anchor set is a smaller
    failure than a missing one.
    """
    named = {n.strip().lower()
             for n in ill._split_array(row.get('canon_refs', ''))}
    if not named:
        return anchors
    matched = {name: text for name, text in anchors.items()
               if name.strip().lower() in named}
    return matched or anchors


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
    ingested = 0
    ingested_ids: set[str] = set()
    for illus_id, src in matched:
        if dry_run:
            log(f'[dry-run] would ingest {src} → '
                f'{ill.default_asset_rel(illus_id, os.path.splitext(src)[1])}')
            continue

        if os.path.getsize(src) == 0:
            log(f'WARNING: {src} is empty — skipping {illus_id}')
            continue

        dims = ill.image_dimensions(src)
        if dims is None:
            log(f'WARNING: {src} is not a readable PNG, JPEG, or WebP — '
                f'skipping {illus_id}')
            continue

        rel = ill.default_asset_rel(illus_id, os.path.splitext(src)[1])
        dest = os.path.join(project_dir, rel)
        if os.path.abspath(src) != os.path.abspath(dest):
            shutil.copy2(src, dest)

        digest = ill.sha256_of(dest)
        _update_row(project_dir, illus_id, {
            'asset_file': rel, 'sha256': digest, 'status': 'ingested',
            'width': str(dims[0]), 'height': str(dims[1]),
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
    rows = ill.read_plan(project_dir)
    if ids is not None:
        rows = [r for r in rows if r['id'].strip() in ids]
    rows = [r for r in rows
            if (r.get('status') or '').strip() != 'superseded']

    if not rows:
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
                updates: dict[str, str]) -> None:
    """Apply updates to one plan row and rewrite the CSV."""
    rows = ill.read_plan(project_dir)
    for row in rows:
        if row['id'].strip() == illus_id:
            row.update(updates)
            break
    ill.write_plan(project_dir, rows)


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
    """Call the API, log the cost, and return the text (or '' on failure)."""
    model = select_model(task_type)
    started = time.time()
    try:
        response = invoke(prompt, model, max_tokens, label=operation)
    except Exception as exc:  # noqa: BLE001 — surfaced to the author below
        log(f'WARNING: API call failed for {operation}: {exc}')
        return ''
    if not response:
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
