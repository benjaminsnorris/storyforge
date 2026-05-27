"""storyforge extract (graphic-novel mode) — bootstrap structural data
from existing scripts or adapt prose into the GN data model.

Two input shapes:

  --from-script DIR_OR_FILE
      Parse one or more existing GN scripts (Marvel-style panel scripts
      matching the script_format.py grammar) into scenes.csv +
      scene-briefs.csv rows. Deterministic — no LLM. Each script file
      becomes one scene row; its id is the filename stem.

  --from-prose FILE
      LLM-driven adaptation of a prose passage into GN intent + brief
      shapes. The model collapses prose action into panel beats and
      surfaces dialogue worth keeping. One scene row per prose section
      (split on `## Scene N` or top-level `##` headers).

Coaching-aware (full / coach / strict) for the prose path. The script
path is purely structural and runs the same way regardless.
"""

import argparse
import json
import os
import re
import sys
from datetime import datetime, timezone
from typing import TypedDict

from storyforge.api import (
    invoke_to_file, calculate_cost_from_usage, extract_usage,
)
from storyforge.common import (
    CoachingLevel, detect_project_root, get_coaching_level, get_medium,
    install_signal_handlers, log, select_model,
)
from storyforge.costs import log_operation
from storyforge.elaborate import _SCENES_COLS as SCENE_COLS
from storyforge.elaborate import _BRIEFS_COLS as BRIEF_COLS
from storyforge.script_format import (
    parse_script, detect_page_turn_pages,
)


def parse_args(argv):
    parser = argparse.ArgumentParser(
        prog='storyforge extract (gn)',
        description='Bootstrap GN structural data from existing scripts or prose.',
    )
    src = parser.add_mutually_exclusive_group(required=True)
    src.add_argument('--from-script', type=str, metavar='PATH',
                     help='Path to a panel script file or directory of '
                          '.md script files. Parses deterministically; no '
                          'LLM call.')
    src.add_argument('--from-prose', type=str, metavar='PATH',
                     help='Path to a prose manuscript file. LLM-extracts '
                          'GN intent + brief shapes per scene section. '
                          'Coaching level controls destination.')
    src.add_argument('--from-pages', action='store_true',
                     help='Sync scene-level metadata from pages/<prefix>-pN.md '
                          'files: panel_count (sum), page_count (count). '
                          'Deterministic; no LLM call.')
    parser.add_argument('--coaching', type=str, default=None,
                        choices=['full', 'coach', 'strict'],
                        help='Override coaching level (default: project setting)')
    parser.add_argument('--dry-run', action='store_true',
                        help='Print what would happen without writing files '
                             'or calling the LLM')
    parser.add_argument('--force', action='store_true',
                        help='Overwrite existing rows in scenes.csv / '
                             'scene-briefs.csv (default: skip ids already present)')
    return parser.parse_args(argv)


def main(argv=None):
    args = parse_args(argv if argv is not None else sys.argv[1:])
    install_signal_handlers()
    project_dir = detect_project_root()
    medium = get_medium(project_dir) or 'novel'
    if medium != 'graphic-novel':
        log(f'ERROR: extract (gn) requires project.medium=graphic-novel; '
            f'got {medium!r}. For novel projects use `storyforge extract`.')
        sys.exit(1)
    coaching = args.coaching or get_coaching_level(project_dir)

    if args.from_pages:
        _run_from_pages(project_dir, args.dry_run)
        return

    if args.from_script:
        _run_from_script(project_dir, args.from_script, args.dry_run,
                          args.force)
        return

    if args.from_prose:
        if coaching == 'strict':
            _run_from_prose_strict(project_dir, args.from_prose, args.dry_run)
            return
        if coaching in ('full', 'coach') and not args.dry_run:
            if not os.environ.get('ANTHROPIC_API_KEY'):
                log(f'ERROR: ANTHROPIC_API_KEY is not set. extract --from-prose '
                    f'in {coaching} coaching requires an API key.')
                sys.exit(1)
        _run_from_prose(project_dir, args.from_prose, coaching, args.dry_run,
                         args.force)


# ---------------------------------------------------------------------------
# --from-pages: deterministic metadata sync
# ---------------------------------------------------------------------------

class _SceneCounts(TypedDict):
    panels: int
    pages: int


def _run_from_pages(project_dir: str, dry_run: bool) -> None:
    """Sum panel_count + page_count per scene from page files and write
    those columns back to scenes.csv. Deterministic — no LLM call.

    Fails loudly if scenes.csv lacks the panel_count or page_count columns
    (GN-mode columns added in #251; pre-fix projects need `storyforge
    cleanup` to add them first) — otherwise csv_cli.update_field silently
    no-ops on a missing column and the run would falsely claim success.
    Also tracks pages missing panel_count and reports partial sums so a
    silent undercount is visible.
    """
    from storyforge.pages import list_page_files, parse_page_file
    from storyforge.csv_cli import update_field, list_ids

    page_paths = list_page_files(project_dir)
    if not page_paths:
        log('ERROR: no pages/*.md files found. Create per-page files first.')
        sys.exit(1)

    scenes_csv = os.path.join(project_dir, 'reference', 'scenes.csv')
    if not os.path.isfile(scenes_csv):
        log(f'ERROR: scenes.csv not found at {scenes_csv}')
        sys.exit(1)

    # Verify the target columns exist BEFORE we sum — update_field silently
    # returns on a missing column, so writing without this check would lie
    # about success on projects that haven't run `storyforge cleanup` since
    # the GN schema was extended.
    with open(scenes_csv, encoding='utf-8') as f:
        header = f.readline().strip().split('|')
    missing_cols = [c for c in ('panel_count', 'page_count') if c not in header]
    if missing_cols and not dry_run:
        log(f'ERROR: scenes.csv is missing required column(s): '
            f'{", ".join(missing_cols)}. Run `storyforge cleanup` to add '
            f'the GN-mode columns before --from-pages.')
        sys.exit(1)

    by_scene: dict[str, _SceneCounts] = {}
    pages_missing_panel_count: dict[str, list[str]] = {}
    for p in page_paths:
        page = parse_page_file(p)
        if page is None:
            log(f'  WARNING: {p} has no frontmatter; skipping')
            continue
        sid = page.get('scene_id')
        if not sid:
            log(f'  WARNING: {p} has no scene_id; skipping')
            continue
        bucket = by_scene.setdefault(sid, {'panels': 0, 'pages': 0})
        panel_count = page.get('panel_count')
        if isinstance(panel_count, int):
            bucket['panels'] += panel_count
        else:
            # Field absent or coerced to string by malformed frontmatter —
            # don't silently treat as zero; surface so authors notice.
            pages_missing_panel_count.setdefault(sid, []).append(
                os.path.basename(p),
            )
        bucket['pages'] += 1

    for sid, files in pages_missing_panel_count.items():
        log(f'  WARNING: scene {sid}: {len(files)} page(s) lack a valid '
            f'integer panel_count ({", ".join(files)}); panel_count sum '
            f'is partial')

    known_ids = set(list_ids(scenes_csv))

    written = 0
    for sid, counts in sorted(by_scene.items()):
        if sid not in known_ids:
            log(f'  WARNING: {sid} referenced by page files but not in '
                f'scenes.csv; skipping')
            continue
        log(f'  {sid}: {counts["pages"]} page(s), {counts["panels"]} panel(s)')
        if dry_run:
            continue
        update_field(scenes_csv, sid, 'panel_count', str(counts['panels']))
        update_field(scenes_csv, sid, 'page_count', str(counts['pages']))
        written += 1

    if dry_run:
        log(f'DRY RUN — would update {len(by_scene)} scene row(s).')
    else:
        log(f'Updated panel_count / page_count for {written} scene(s).')


# ---------------------------------------------------------------------------
# --from-script: deterministic parse
# ---------------------------------------------------------------------------

def _run_from_script(project_dir: str, source: str, dry_run: bool,
                      force: bool) -> None:
    paths = _resolve_script_paths(source)
    if not paths:
        log(f'ERROR: no .md script files found at {source}')
        sys.exit(1)

    scene_rows: list[dict] = []
    brief_rows: list[dict] = []
    for path in paths:
        with open(path, encoding='utf-8') as f:
            text = f.read()
        scene_id = os.path.splitext(os.path.basename(path))[0]
        parsed = parse_script(text)
        if parsed['page_count'] == 0:
            log(f'WARNING: {path} has no recognized `## Page N — LAYOUT` '
                f'headers; skipping')
            continue
        scene_rows.append(_scene_row_from_script(scene_id, text, parsed))
        brief_rows.append(_brief_row_from_script(scene_id, text, parsed))
        log(f'Extracted {scene_id}: {parsed["page_count"]} pages, '
            f'{parsed["total_panels"]} panels')

    if not scene_rows:
        log('ERROR: no scenes extracted (all source files were unrecognized).')
        sys.exit(1)

    if dry_run:
        log(f'DRY RUN — would write {len(scene_rows)} scene row(s) and '
            f'{len(brief_rows)} brief row(s).')
        return

    _merge_rows_into_csv(
        os.path.join(project_dir, 'reference', 'scenes.csv'),
        SCENE_COLS, scene_rows, force=force,
    )
    _merge_rows_into_csv(
        os.path.join(project_dir, 'reference', 'scene-briefs.csv'),
        BRIEF_COLS, brief_rows, force=force,
    )
    log(f'Wrote {len(scene_rows)} scene(s) and {len(brief_rows)} brief(s) '
        f'to reference/.')


def _resolve_script_paths(source: str) -> list[str]:
    """Return a sorted list of .md script files under `source` (file or dir)."""
    if os.path.isfile(source):
        return [source] if source.endswith('.md') else []
    if not os.path.isdir(source):
        return []
    paths = []
    for entry in sorted(os.listdir(source)):
        if entry.endswith('.md'):
            paths.append(os.path.join(source, entry))
    return paths


def _scene_row_from_script(scene_id: str, text: str, parsed: dict) -> dict:
    """Derive a scenes.csv row from a parsed script.

    Title is left empty: the deterministic extractor can't infer an
    authored title from a slug, and the merge logic would otherwise
    overwrite real author titles with humanized slugs under --force.
    Authors set titles in the CSV or via author tools.
    """
    word_count = len(re.findall(r'\b\w+\b', text))
    return {
        'id': scene_id,
        'status': 'drafted',
        'word_count': str(word_count),
        'panel_count': str(parsed['total_panels']),
        'page_count': str(parsed['page_count']),
    }


def _brief_row_from_script(scene_id: str, text: str, parsed: dict) -> dict:
    """Derive a scene-briefs.csv row from a parsed script.

    Most semantic fields (goal, conflict, outcome, etc.) come from the
    author's intent — we can't reverse-engineer them from prose alone.
    What we CAN populate cleanly from a parsed script:
      - page_layout (sequence of per-page layouts)
      - panel_breakdown (sequence of panel counts per page)
      - page_turn_beats (which pages end on a ⟵ PAGE-TURN REVEAL marker)
      - caption_strategy (heuristic: low / medium / heavy)
    """
    layouts = ';'.join(p['layout'] for p in parsed['pages'])
    breakdown = ';'.join(str(len(p['panels'])) for p in parsed['pages'])
    turn_pages = detect_page_turn_pages(text)
    page_turn_beats = ';'.join(f'p{n}' for n in turn_pages)
    caption_strategy = _caption_strategy_from(parsed)
    return {
        'id': scene_id,
        'page_layout': layouts,
        'panel_breakdown': breakdown,
        'page_turn_beats': page_turn_beats,
        'caption_strategy': caption_strategy,
        'has_overflow': 'false',
    }


def _caption_strategy_from(parsed: dict) -> str:
    """Heuristic: 'none' if zero captions, 'minimal' if ≤ 1 per page on
    avg, 'omniscient' if ≥ 3 per page on avg, 'journal-voiceover' for
    everything in between when most captions come from a single speaker."""
    total_captions = 0
    speakers: dict[str, int] = {}
    for page in parsed['pages']:
        for panel in page['panels']:
            for line in panel['dialogue']:
                if line['prefix'].upper() in ('CAPTION', 'THOUGHT'):
                    total_captions += 1
                    sp = line['speaker'] or 'CAPTION'
                    speakers[sp] = speakers.get(sp, 0) + 1
    n_pages = parsed['page_count'] or 1
    avg = total_captions / n_pages
    if total_captions == 0:
        return 'none'
    if avg <= 1.0:
        return 'minimal'
    if avg >= 3.0:
        return 'omniscient'
    # Mid-range: pick journal-voiceover if one speaker dominates ≥ 60%
    if speakers and max(speakers.values()) / total_captions >= 0.6:
        return 'journal-voiceover'
    return 'omniscient'


# ---------------------------------------------------------------------------
# --from-prose: LLM-driven adaptation
# ---------------------------------------------------------------------------

_PROSE_PROMPT = """\
You are adapting prose into a graphic novel. For the section below,
produce a JSON object describing the scene as it would appear in a
panel script. Focus on visual beats and dialogue worth keeping; the
author will refine.

# Prose section

{prose}

# Task

Return a JSON object with these fields:

  - title: a short scene title (3-6 words)
  - summary: one sentence describing what happens (≤ 35 words)
  - key_actions: 3-6 visual beats, semicolon-separated, written as
    things the reader would see panel-by-panel
  - key_dialogue: the 1-3 most worth-keeping lines from the prose
    (semicolon-separated, attributed: "SPEAKER: line")
  - emotions: 2-4 emotional beats the scene plays (semicolon-separated)
  - motifs: 1-3 recurring visual or thematic motifs (semicolon-separated)
  - page_layout: a tentative layout vocabulary for the scene
    (e.g., "wide; 6-grid; splash; 6-grid")
  - caption_strategy: one of "none" / "minimal" / "journal-voiceover" /
    "omniscient", chosen for what fits the prose's narrative voice

Return ONLY the JSON object. No prose before or after.
"""


def _run_from_prose(project_dir: str, source: str, coaching: CoachingLevel,
                     dry_run: bool, force: bool) -> None:
    sections = _split_prose_into_sections(source)
    if not sections:
        log(f'ERROR: no scene sections found at {source} (expected `## Scene N` '
            f'or `## Title` headers)')
        sys.exit(1)

    if dry_run:
        log(f'DRY RUN — would adapt {len(sections)} prose section(s) via LLM, '
            f'coaching={coaching}.')
        return

    model = select_model('creative')
    log_dir = os.path.join(project_dir, 'working', 'logs', 'extract-gn')
    os.makedirs(log_dir, exist_ok=True)

    scene_rows: list[dict] = []
    brief_rows: list[dict] = []
    coaching_notes: list[dict] = []
    failed_llm: list[str] = []
    failed_parse: list[str] = []
    for idx, (sid, header, prose) in enumerate(sections, start=1):
        log(f'Adapting section {idx}/{len(sections)}: {header!r}')
        prompt = _PROSE_PROMPT.format(prose=prose)
        log_file = os.path.join(log_dir, f'{sid}.json')
        try:
            invoke_to_file(prompt, model, log_file, max_tokens=2048)
        except Exception as e:
            log(f'  ERROR: LLM call failed for {sid}: {e}')
            failed_llm.append(sid)
            continue
        text = _read_response_text(log_file)
        parsed = _parse_prose_response(text)
        if not parsed:
            # Bill the call as 'unparseable' so the ledger reflects what
            # Anthropic charged us, but mark it so a summary report can
            # distinguish productive spend from waste.
            _record_cost(project_dir, log_file, model, f'{sid}:unparseable')
            log(f'  WARNING: could not parse LLM response for {sid}; skipping')
            failed_parse.append(sid)
            continue
        _record_cost(project_dir, log_file, model, sid)
        scene_rows.append(_scene_row_from_prose(sid, header, parsed))
        brief_rows.append(_brief_row_from_prose(sid, parsed))
        coaching_notes.append({'scene_id': sid, 'header': header,
                               'parsed': parsed, 'prose_excerpt': prose[:400]})

    if failed_llm or failed_parse:
        log(f'PARTIAL: {len(sections)} section(s) requested, '
            f'{len(scene_rows)} written, '
            f'{len(failed_llm)} LLM failure(s), '
            f'{len(failed_parse)} parse failure(s).')
        if failed_llm:
            log(f'  LLM failed for: {", ".join(failed_llm)}')
        if failed_parse:
            log(f'  Parse failed for: {", ".join(failed_parse)} '
                f'(responses saved in {log_dir})')

    if coaching == 'coach':
        out_path = _write_coaching_brief(project_dir, coaching_notes)
        log(f'Wrote coaching brief: {out_path}')
        return

    # full coaching: write to CSVs
    _merge_rows_into_csv(
        os.path.join(project_dir, 'reference', 'scenes.csv'),
        SCENE_COLS, scene_rows, force=force,
    )
    _merge_rows_into_csv(
        os.path.join(project_dir, 'reference', 'scene-briefs.csv'),
        BRIEF_COLS, brief_rows, force=force,
    )
    log(f'Wrote {len(scene_rows)} adapted scene(s) and brief(s) to reference/.')


def _run_from_prose_strict(project_dir: str, source: str, dry_run: bool) -> None:
    """strict coaching: produce a constraint checklist for each section
    (no LLM, no creative output) describing what the author needs to
    decide when adapting the prose by hand."""
    sections = _split_prose_into_sections(source)
    if not sections:
        log(f'ERROR: no scene sections found at {source}')
        sys.exit(1)

    out_lines: list[str] = []
    out_lines.append('# Adaptation checklist — prose → graphic-novel')
    out_lines.append('')
    out_lines.append(
        f'Generated for coaching=strict on '
        f'{datetime.now(timezone.utc).isoformat()}. For each prose section '
        'below, the author decides every adaptation move themselves — '
        'this file lists what each section must specify when written by '
        'hand.'
    )
    out_lines.append('')
    out_lines.append('## What each adapted scene must specify')
    out_lines.append('')
    out_lines.append('- title: 3-6 word scene title')
    out_lines.append('- summary: one sentence describing what happens '
                     '(≤ 35 words)')
    out_lines.append('- key_actions: 3-6 visual beats panel-by-panel')
    out_lines.append('- key_dialogue: 1-3 lines worth keeping')
    out_lines.append('- emotions, motifs: 1-4 each')
    out_lines.append('- page_layout: layout tokens per page')
    out_lines.append('- caption_strategy: none | minimal | '
                     'journal-voiceover | omniscient')
    out_lines.append('')

    for idx, (sid, header, prose) in enumerate(sections, start=1):
        out_lines.append(f'## Section {idx}: {header}')
        out_lines.append('')
        out_lines.append(f'Proposed scene id: `{sid}`')
        out_lines.append('')
        out_lines.append('```')
        out_lines.append(prose.strip()[:1200] +
                         ('\n…' if len(prose.strip()) > 1200 else ''))
        out_lines.append('```')
        out_lines.append('')

    out_path = os.path.join(project_dir, 'working', 'coaching',
                            'extract-gn-from-prose.md')
    if dry_run:
        log(f'Would write strict-mode checklist to {out_path}')
        return
    os.makedirs(os.path.dirname(out_path), exist_ok=True)
    with open(out_path, 'w', encoding='utf-8') as f:
        f.write('\n'.join(out_lines) + '\n')
    log(f'Wrote strict-mode checklist: {out_path}')


def _split_prose_into_sections(path: str) -> list[tuple[str, str, str]]:
    """Split a prose manuscript into (scene_id, header_text, body) triples.

    Splits on top-level `##` headers. The scene_id is a slug derived
    from the header; duplicate slugs get a numeric suffix so duplicate
    headers like two `## Interlude` blocks don't silently collide and
    lose a section. Content before the first `##` is ignored.
    """
    if not os.path.isfile(path):
        return []
    with open(path, encoding='utf-8') as f:
        text = f.read()
    header_pattern = re.compile(r'^##\s+(.+?)\s*$', re.MULTILINE)
    matches = list(header_pattern.finditer(text))
    sections: list[tuple[str, str, str]] = []
    seen: set[str] = set()
    for i, m in enumerate(matches):
        header = m.group(1).strip()
        body_start = m.end()
        body_end = matches[i + 1].start() if i + 1 < len(matches) else len(text)
        body = text[body_start:body_end].strip()
        if not body:
            continue
        base = _slugify(header) or f'adapted-{i + 1}'
        sid = base
        n = 2
        while sid in seen:
            sid = f'{base}-{n}'
            n += 1
        seen.add(sid)
        sections.append((sid, header, body))
    return sections


def _slugify(text: str) -> str:
    """Lowercase + hyphenate words; strip non-alphanumerics."""
    s = text.lower()
    s = re.sub(r'[^a-z0-9]+', '-', s).strip('-')
    return s[:60]


def _parse_prose_response(text: str) -> dict | None:
    """Extract the JSON object from the LLM response. Tolerant of fenced
    and prose-wrapped JSON."""
    if not text:
        return None
    def _take(obj):
        return obj if isinstance(obj, dict) else None
    try:
        result = _take(json.loads(text))
        if result is not None:
            return result
    except json.JSONDecodeError:
        pass
    m = re.search(r'```(?:json)?\s*\n(.*?)\n```', text, re.DOTALL)
    if m:
        try:
            result = _take(json.loads(m.group(1).strip()))
            if result is not None:
                return result
        except json.JSONDecodeError:
            pass
    m = re.search(r'\{.*\}', text, re.DOTALL)
    if m:
        try:
            result = _take(json.loads(m.group(0)))
            if result is not None:
                return result
        except json.JSONDecodeError:
            pass
    return None


def _scene_row_from_prose(sid: str, header: str, parsed: dict) -> dict:
    title = str(parsed.get('title', '')).strip() or _humanize(sid)
    summary = str(parsed.get('summary', '')).strip()
    return {
        'id': sid,
        'title': title,
        'summary': _sanitize_cell(summary),
        'status': 'mapped',
    }


def _brief_row_from_prose(sid: str, parsed: dict) -> dict:
    return {
        'id': sid,
        'key_actions': _sanitize_cell(parsed.get('key_actions', '')),
        'key_dialogue': _sanitize_cell(parsed.get('key_dialogue', '')),
        'emotions': _sanitize_cell(parsed.get('emotions', '')),
        'motifs': _sanitize_cell(parsed.get('motifs', '')),
        'page_layout': _sanitize_cell(parsed.get('page_layout', '')),
        'caption_strategy': _sanitize_cell(parsed.get('caption_strategy', '')),
        'has_overflow': 'false',
    }


# ---------------------------------------------------------------------------
# Shared helpers
# ---------------------------------------------------------------------------

def _humanize(slug: str) -> str:
    """Turn 'act1-sc01' into 'Act1 Sc01'-style title fallback."""
    return ' '.join(part.capitalize() for part in re.split(r'[-_]', slug))


def _sanitize_cell(value: str) -> str:
    """Strip pipes/newlines from CSV cell values."""
    if not isinstance(value, str):
        value = str(value)
    return value.replace('|', '/').replace('\n', ' ').replace('\r', '').strip()


def _merge_rows_into_csv(csv_path: str, columns: list[str],
                         new_rows: list[dict], *, force: bool) -> None:
    """Merge `new_rows` into the CSV at `csv_path`.

    - If the CSV doesn't exist, create it with `columns` as the header.
    - If a row id already exists and force=False, skip it (preserved).
    - If force=True, fields with non-empty extracted values overwrite
      existing fields; fields the extractor left empty keep their
      prior value (field-level merge, not wholesale row replace).
    - New ids append at the end.
    - Existing columns not in `columns` are preserved in the header
      (legacy data is never silently dropped).
    """
    os.makedirs(os.path.dirname(csv_path), exist_ok=True)
    if not os.path.isfile(csv_path):
        existing_headers = list(columns)
        existing_rows: list[dict] = []
    else:
        with open(csv_path, encoding='utf-8') as f:
            raw = f.read().replace('\r\n', '\n').replace('\r', '')
        lines = [l for l in raw.splitlines() if l.strip()]
        existing_headers = lines[0].split('|') if lines else list(columns)
        existing_rows = []
        for line in lines[1:]:
            cells = line.split('|')
            if len(cells) == len(existing_headers):
                existing_rows.append(dict(zip(existing_headers, cells)))

    # Ensure every target column exists in the header (idempotent upgrade).
    extra_existing = [c for c in existing_headers if c not in columns]
    headers = list(columns) + extra_existing
    by_id = {r.get('id', '').strip(): r for r in existing_rows
             if r.get('id', '').strip()}

    written = 0
    skipped = 0
    appended = 0
    for r in new_rows:
        sid = r.get('id', '').strip()
        if not sid:
            continue
        if sid in by_id:
            if not force:
                skipped += 1
                continue
            # Merge: overwrite only the fields present in the new row.
            for k, v in r.items():
                if v:
                    by_id[sid][k] = v
            written += 1
        else:
            new_row = {c: '' for c in headers}
            new_row.update(r)
            by_id[sid] = new_row
            existing_rows.append(new_row)
            appended += 1

    out_lines = ['|'.join(headers)]
    for r in existing_rows:
        out_lines.append('|'.join(_sanitize_cell(r.get(c, '')) for c in headers))
    with open(csv_path, 'w', encoding='utf-8') as f:
        f.write('\n'.join(out_lines) + '\n')
    log(f'  {csv_path}: +{appended} new, {written} updated, {skipped} '
        f'skipped (existing).')


def _write_coaching_brief(project_dir: str, notes: list[dict]) -> str:
    """coach coaching: write proposals to a working/coaching brief for
    author review. No CSV writes."""
    out_path = os.path.join(project_dir, 'working', 'coaching',
                            'extract-gn-from-prose.md')
    os.makedirs(os.path.dirname(out_path), exist_ok=True)
    lines: list[str] = [
        '# Coaching brief: extract --from-prose (graphic-novel)',
        '',
        f'Generated {datetime.now(timezone.utc).isoformat()}.',
        '',
    ]
    for n in notes:
        lines.append(f'## {n["scene_id"]} — {n["header"]}')
        lines.append('')
        lines.append('### LLM-proposed adaptation')
        lines.append('')
        lines.append('```json')
        lines.append(json.dumps(n['parsed'], indent=2))
        lines.append('```')
        lines.append('')
        lines.append('### Source excerpt')
        lines.append('')
        lines.append('```')
        lines.append(n['prose_excerpt'])
        lines.append('```')
        lines.append('')
    with open(out_path, 'w', encoding='utf-8') as f:
        f.write('\n'.join(lines) + '\n')
    return out_path


def _read_response_text(log_file: str) -> str:
    try:
        with open(log_file, encoding='utf-8') as f:
            resp = json.load(f)
        for block in resp.get('content', []):
            if block.get('type') == 'text':
                return block.get('text', '')
    except (OSError, json.JSONDecodeError) as e:
        log(f'WARNING: could not read LLM response file {log_file}: {e}')
    return ''


def _record_cost(project_dir: str, log_file: str, model: str,
                  scene_id: str) -> None:
    try:
        with open(log_file, encoding='utf-8') as f:
            resp = json.load(f)
    except (OSError, json.JSONDecodeError) as e:
        log(f'WARNING: cost ledger update failed reading {log_file}: {e}')
        return
    usage = extract_usage(resp)
    cost = calculate_cost_from_usage(usage, model)
    log_operation(
        project_dir, 'extract-gn', model,
        usage['input_tokens'], usage['output_tokens'], cost,
        target=scene_id,
        cache_read=usage.get('cache_read', 0),
        cache_create=usage.get('cache_create', 0),
    )
