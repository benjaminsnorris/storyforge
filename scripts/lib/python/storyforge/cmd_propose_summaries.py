"""storyforge propose-summaries — draft candidate summaries from the level above.

For each downstream level (3=spine, 4=architecture, 5=scene-map), reads the
upstream level (act-shape, spine, architecture) and proposes one-sentence
summaries that expand it. Output depends on coaching level:

  - full   — LLM proposes summaries; written directly into the target CSV
             (creating rows when needed; filling empty `summary` cells when
             rows already exist).
  - coach  — LLM proposes summaries; written to a working/coaching/ brief
             with questions and alternative framings. No CSV writes.
  - strict — Constraint checklist (no LLM creative output); enumerates what
             each summary needs to cover based on the upstream beats. No
             prose, no CSV writes.
"""

import argparse
import json
import os
import re
import sys
from datetime import datetime, timezone

from storyforge.api import invoke_to_file, calculate_cost_from_usage, extract_usage
from storyforge.common import (
    detect_project_root, get_coaching_level, get_medium, install_signal_handlers,
    log, parse_story_summary, select_model,
)
from storyforge.costs import log_operation


SUPPORTED_LEVELS = (3, 4, 5)

LEVEL_TO_NAME = {3: 'spine', 4: 'architecture', 5: 'scene-map'}
LEVEL_TO_TARGET_CSV = {
    3: 'spine.csv', 4: 'architecture.csv', 5: 'scenes.csv',
}

# Target row count ranges (matching scoring_levels floor checks).
ROW_RANGES_NOVEL = {3: (5, 10), 4: (15, 25)}
ROW_RANGES_GN = {3: (4, 8), 4: (10, 18)}


def parse_args(argv):
    parser = argparse.ArgumentParser(
        prog='storyforge propose-summaries',
        description='Draft candidate summaries for level N from the level above.',
    )
    parser.add_argument('--level', type=int, required=True,
                        choices=SUPPORTED_LEVELS,
                        help='Target level: 3 (spine), 4 (architecture), '
                             '5 (scene-map)')
    parser.add_argument('--coaching', type=str, default=None,
                        choices=['full', 'coach', 'strict'],
                        help='Override coaching level (default: project setting)')
    parser.add_argument('--dry-run', action='store_true',
                        help='Print what would happen without calling the LLM '
                             'or writing files')
    return parser.parse_args(argv)


def main(argv=None):
    args = parse_args(argv if argv is not None else sys.argv[1:])
    install_signal_handlers()
    project_dir = detect_project_root()
    coaching = args.coaching or get_coaching_level(project_dir)
    medium = get_medium(project_dir) or 'novel'

    if coaching == 'strict':
        _run_strict(project_dir, args.level, medium, args.dry_run)
        return

    if coaching == 'full' and not args.dry_run:
        if not os.environ.get('ANTHROPIC_API_KEY'):
            log('ERROR: ANTHROPIC_API_KEY is not set. propose-summaries in '
                'full coaching requires an API key. Set it and re-run, or '
                'use --dry-run / --coaching strict.')
            sys.exit(1)

    # full + coach both call the LLM; differ only in where output lands.
    _run_with_llm(project_dir, args.level, medium, coaching, args.dry_run)


# ---------------------------------------------------------------------------
# strict — rule-based checklist, no LLM
# ---------------------------------------------------------------------------

def _run_strict(project_dir: str, level: int, medium: str, dry_run: bool) -> None:
    upstream = _read_upstream(project_dir, level)
    target_csv = LEVEL_TO_TARGET_CSV[level]
    range_str = _row_range_for(level, medium)

    out_lines: list[str] = []
    out_lines.append(f'# Constraint checklist — propose summaries for '
                     f'reference/{target_csv}')
    out_lines.append('')
    out_lines.append(
        f'Generated for coaching=strict on {datetime.now(timezone.utc).isoformat()}. '
        'The author drafts the summaries themselves; this file lists what '
        'each summary must cover based on the upstream content.'
    )
    out_lines.append('')

    if range_str:
        out_lines.append(f'## Row count target')
        out_lines.append('')
        out_lines.append(f'Aim for {range_str} rows total for {target_csv}.')
        out_lines.append('')

    out_lines.append(f'## Upstream content to expand from')
    out_lines.append('')
    out_lines.append(f'```')
    out_lines.append(upstream.strip())
    out_lines.append(f'```')
    out_lines.append('')

    out_lines.append('## What each summary must cover')
    out_lines.append('')
    out_lines.append('- One sentence, ≤ 35 words')
    out_lines.append('- Describes what happens (not what it means)')
    out_lines.append('- Identifies the change in state (before → after)')
    if level == 3:
        out_lines.append('- Ties to a specific Act number via the `part` column')
    if level == 4:
        out_lines.append('- References its parent spine event via `spine_event`')
        out_lines.append('- Specifies POV, action/sequel, value at stake')
    if level == 5:
        out_lines.append('- Sets the operational frame (location, time of day, '
                         'duration) — those columns are required at scene-map')

    output = '\n'.join(out_lines) + '\n'
    out_path = os.path.join(
        project_dir, 'working', 'coaching',
        f'propose-summaries-level-{level}.md',
    )
    if dry_run:
        log(f'Would write strict-mode checklist to {out_path}')
        return
    os.makedirs(os.path.dirname(out_path), exist_ok=True)
    with open(out_path, 'w', encoding='utf-8') as f:
        f.write(output)
    log(f'Wrote strict-mode checklist: {out_path}')


# ---------------------------------------------------------------------------
# full / coach — LLM-driven
# ---------------------------------------------------------------------------

def _run_with_llm(project_dir: str, level: int, medium: str,
                  coaching: str, dry_run: bool) -> None:
    upstream = _read_upstream(project_dir, level)
    if not upstream.strip():
        log(f'ERROR: upstream content for level {level} is empty. '
            'Populate the level above first.')
        sys.exit(1)

    target_csv = LEVEL_TO_TARGET_CSV[level]
    range_str = _row_range_for(level, medium)
    prompt = _build_prompt(level, upstream, range_str, coaching, medium)

    if dry_run:
        log(f'DRY RUN — propose summaries for level {level} ({LEVEL_TO_NAME[level]})')
        log(f'Upstream content ({len(upstream)} chars):')
        log(upstream[:300] + ('…' if len(upstream) > 300 else ''))
        log('')
        log(f'Prompt would be {len(prompt)} chars; coaching={coaching}; '
            f'target={target_csv}')
        return

    model = select_model('creative')
    log_dir = os.path.join(project_dir, 'working', 'logs',
                           'propose-summaries')
    os.makedirs(log_dir, exist_ok=True)
    log_file = os.path.join(log_dir, f'level-{level}.json')
    try:
        invoke_to_file(prompt, model, log_file, max_tokens=4096)
    except Exception as e:
        log(f'ERROR: propose-summaries LLM call failed: {e}')
        sys.exit(1)

    response_text = _read_response_text(log_file)
    proposals = _parse_proposals(response_text)
    _record_cost(project_dir, log_file, model, level)

    if not proposals:
        log('ERROR: LLM returned no parseable proposals. See log file: '
            + log_file)
        sys.exit(1)

    if coaching == 'full':
        written = _write_to_csv(project_dir, level, proposals)
        log(f'Wrote {written} summary(ies) to reference/{target_csv}')
    else:
        out_path = _write_coaching_brief(
            project_dir, level, upstream, proposals, response_text,
        )
        log(f'Wrote coaching brief: {out_path}')


def _build_prompt(level: int, upstream: str, range_str: str,
                   coaching: str, medium: str) -> str:
    target_name = LEVEL_TO_NAME[level]
    parent_name = {3: 'act-shape', 4: 'spine', 5: 'architecture'}[level]
    extra_fields = ''
    if level == 3:
        extra_fields = ('Each event should belong to a specific Act '
                        '(part 1, 2, or 3 typically).')
    elif level == 4:
        extra_fields = ('Each anchor should clearly tie to a spine event '
                        '(reference the spine event id in your reasoning).')
    elif level == 5:
        extra_fields = ('Each scene should clearly tie to a specific '
                        'architecture anchor (reference the anchor id).')
    count_hint = (f'Aim for {range_str} rows total.' if range_str
                  else 'Match the granularity of the upstream content.')
    coach_note = ''
    if coaching == 'coach':
        coach_note = (
            'In addition to the proposals, append a "considerations" block '
            'with 2-3 questions the author should weigh, and one alternative '
            'framing for any proposal you found difficult.'
        )

    return f"""You are drafting candidate one-sentence summaries for the {target_name} \
tier of a story-elaboration pipeline.

# Upstream content ({parent_name})

{upstream}

# Task

Propose {target_name} summaries that expand the upstream. Each summary is:
- one sentence describing what happens
- at most 35 words
- specific enough to feed downstream elaboration

{extra_fields}
{count_hint}

{coach_note}

Return ONLY a JSON object of this shape:

{{
  "proposals": [
    {{"summary": "...", "rationale": "..."}},
    ...
  ]{', "considerations": ["...", "..."]' if coaching == 'coach' else ''}
}}

No prose outside the JSON.
"""


def _parse_proposals(text: str) -> list[dict]:
    """Extract the `proposals` list from the LLM response. Tolerant of
    fenced or prose-wrapped JSON."""
    def _take(obj):
        if isinstance(obj, dict):
            inner = obj.get('proposals')
            if isinstance(inner, list):
                return [p for p in inner
                        if isinstance(p, dict) and p.get('summary', '').strip()]
        return None
    try:
        out = _take(json.loads(text))
        if out is not None:
            return out
    except json.JSONDecodeError:
        pass
    m = re.search(r'```(?:json)?\s*\n(.*?)\n```', text, re.DOTALL)
    if m:
        try:
            out = _take(json.loads(m.group(1).strip()))
            if out is not None:
                return out
        except json.JSONDecodeError:
            pass
    m = re.search(r'\{.*\}', text, re.DOTALL)
    if m:
        try:
            out = _take(json.loads(m.group(0)))
            if out is not None:
                return out
        except json.JSONDecodeError:
            pass
    return []


# ---------------------------------------------------------------------------
# Output: CSV writes (full) or coaching briefs (coach)
# ---------------------------------------------------------------------------

def _sanitize_cell(value: str) -> str:
    """Strip pipes/newlines from a value before writing to a pipe-CSV.

    LLM responses may contain `|` or `\\n` in summaries; without
    sanitization those would shatter the row at write time AND be
    silently dropped by the column-arity filter on the next read.
    Matches the convention used by cmd_score and cmd_revise.
    """
    if not isinstance(value, str):
        value = str(value)
    return value.replace('|', '/').replace('\n', ' ').replace('\r', '').strip()


def _write_to_csv(project_dir: str, level: int,
                  proposals: list[dict]) -> int:
    """Write proposals into the target CSV's `summary` column.

    Existing non-empty summaries are NEVER overwritten. Empty cells fill
    first, then leftover proposals append as new rows. Header upgrades
    preserve every column from the old header (orphan columns are not
    silently dropped).
    """
    from storyforge.elaborate import _SPINE_COLS, _ARCHITECTURE_COLS, _SCENES_COLS
    cols_by_level = {3: _SPINE_COLS, 4: _ARCHITECTURE_COLS, 5: _SCENES_COLS}
    target_cols = cols_by_level[level]
    csv_path = os.path.join(project_dir, 'reference',
                            LEVEL_TO_TARGET_CSV[level])

    if not os.path.isfile(csv_path):
        return _create_csv_with_proposals(csv_path, target_cols,
                                           proposals, level)

    with open(csv_path, encoding='utf-8') as f:
        raw = f.read().replace('\r\n', '\n').replace('\r', '')
    lines = [l for l in raw.splitlines() if l.strip()]
    headers = lines[0].split('|')
    rows = []
    for line in lines[1:]:
        cells = line.split('|')
        if len(cells) == len(headers):
            rows.append(dict(zip(headers, cells)))

    if 'summary' not in headers:
        # Header upgrade: preserve every existing column AND add the new
        # target columns. The old header may include legacy columns not
        # in target_cols — we keep them rather than silently dropping
        # author data.
        log(f'INFO: {csv_path} predates `summary` column; upgrading header '
            f'(preserving any existing columns).')
        extra_cols = [c for c in headers if c not in target_cols]
        headers = list(target_cols) + extra_cols
        for r in rows:
            r.setdefault('summary', '')

    existing_ids = {r.get('id', '').strip() for r in rows
                    if r.get('id', '').strip()}

    written = 0
    proposal_iter = iter(proposals)
    for r in rows:
        if not r.get('summary', '').strip():
            p = next(proposal_iter, None)
            if p is None:
                break
            r['summary'] = _sanitize_cell(p['summary'])
            written += 1

    max_seq = 0
    for r in rows:
        try:
            s = int(r.get('seq', '0'))
            if s > max_seq:
                max_seq = s
        except ValueError:
            pass

    # Append remaining proposals as new rows. Bump the id counter past
    # any collision with existing rows (re-runs of propose-summaries
    # can land on the same `proposed-{level}-N` namespace).
    next_seq = max_seq + 1
    for p in proposal_iter:
        new_id = f'proposed-{level}-{next_seq}'
        while new_id in existing_ids:
            next_seq += 1
            new_id = f'proposed-{level}-{next_seq}'
        existing_ids.add(new_id)
        new_row: dict = {c: '' for c in headers}
        new_row['id'] = new_id
        new_row['seq'] = str(next_seq)
        new_row['summary'] = _sanitize_cell(p['summary'])
        rows.append(new_row)
        written += 1
        next_seq += 1

    out_lines = ['|'.join(headers)]
    for r in rows:
        out_lines.append('|'.join(_sanitize_cell(r.get(c, '')) for c in headers))
    try:
        with open(csv_path, 'w', encoding='utf-8') as f:
            f.write('\n'.join(out_lines) + '\n')
    except OSError as e:
        log(f'ERROR: could not write {csv_path}: {e}')
        log(f'  LLM proposals were not lost — recover them from the '
            f'response file under working/logs/propose-summaries/')
        raise
    return written


def _create_csv_with_proposals(csv_path: str, target_cols: list[str],
                                 proposals: list[dict], level: int) -> int:
    """Create a fresh target CSV with one row per proposal."""
    os.makedirs(os.path.dirname(csv_path), exist_ok=True)
    out_lines = ['|'.join(target_cols)]
    for i, p in enumerate(proposals, start=1):
        new_id = f'proposed-{level}-{i}'
        new_row = {c: '' for c in target_cols}
        new_row['id'] = new_id
        new_row['seq'] = str(i)
        new_row['summary'] = _sanitize_cell(p['summary'])
        out_lines.append('|'.join(_sanitize_cell(new_row.get(c, ''))
                                   for c in target_cols))
    try:
        with open(csv_path, 'w', encoding='utf-8') as f:
            f.write('\n'.join(out_lines) + '\n')
    except OSError as e:
        log(f'ERROR: could not write {csv_path}: {e}')
        log(f'  LLM proposals were not lost — recover them from the '
            f'response file under working/logs/propose-summaries/')
        raise
    return len(proposals)


def _write_coaching_brief(project_dir: str, level: int, upstream: str,
                           proposals: list[dict], raw_text: str) -> str:
    """Write a coaching brief — proposals + considerations, no CSV writes."""
    out_path = os.path.join(project_dir, 'working', 'coaching',
                            f'propose-summaries-level-{level}.md')
    os.makedirs(os.path.dirname(out_path), exist_ok=True)

    considerations: list[str] = []
    try:
        parsed = json.loads(raw_text) if raw_text.lstrip().startswith('{') else None
        if isinstance(parsed, dict) and isinstance(parsed.get('considerations'), list):
            considerations = [str(c) for c in parsed['considerations']
                              if isinstance(c, str) and c.strip()]
    except json.JSONDecodeError:
        pass

    out: list[str] = [
        f'# Coaching brief: propose-summaries level {level} '
        f'({LEVEL_TO_NAME[level]})',
        '',
        f'Generated {datetime.now(timezone.utc).isoformat()}.',
        '',
        '## Candidate summaries',
        '',
    ]
    for i, p in enumerate(proposals, start=1):
        out.append(f'{i}. {p["summary"].strip()}')
        rationale = (p.get('rationale') or '').strip()
        if rationale:
            out.append(f'   - Rationale: {rationale}')
    out.append('')
    if considerations:
        out.append('## Considerations')
        out.append('')
        for c in considerations:
            out.append(f'- {c}')
        out.append('')
    out.append('## Upstream content used')
    out.append('')
    out.append('```')
    out.append(upstream.strip())
    out.append('```')
    out.append('')
    with open(out_path, 'w', encoding='utf-8') as f:
        f.write('\n'.join(out) + '\n')
    return out_path


# ---------------------------------------------------------------------------
# Upstream loaders
# ---------------------------------------------------------------------------

def _read_upstream(project_dir: str, level: int) -> str:
    """Return the upstream text used to seed the LLM proposal for level N."""
    if level == 3:
        summary = parse_story_summary(project_dir) or {}
        return summary.get('act_shape', '') or ''
    if level == 4:
        return _render_summaries_from(
            os.path.join(project_dir, 'reference', 'spine.csv'),
        )
    if level == 5:
        return _render_summaries_from(
            os.path.join(project_dir, 'reference', 'architecture.csv'),
        )
    return ''


def _render_summaries_from(csv_path: str) -> str:
    """Render a CSV's summary column as a numbered list (one per row)."""
    if not os.path.isfile(csv_path):
        return ''
    with open(csv_path, encoding='utf-8') as f:
        raw = f.read().replace('\r\n', '\n').replace('\r', '')
    lines = [l for l in raw.splitlines() if l.strip()]
    if not lines:
        return ''
    headers = lines[0].split('|')
    if 'summary' not in headers:
        return ''
    bullets: list[str] = []
    for i, line in enumerate(lines[1:], start=1):
        cells = line.split('|')
        if len(cells) != len(headers):
            continue
        row = dict(zip(headers, cells))
        summary = row.get('summary', '').strip()
        sid = row.get('id', '').strip()
        if summary:
            bullets.append(f'{i}. ({sid}) {summary}')
    return '\n'.join(bullets)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _row_range_for(level: int, medium: str) -> str:
    """Return human-readable row-count target like '5-10' for level/medium."""
    ranges = ROW_RANGES_GN if medium == 'graphic-novel' else ROW_RANGES_NOVEL
    if level in ranges:
        lo, hi = ranges[level]
        return f'{lo}-{hi}'
    return ''


def _read_response_text(log_file: str) -> str:
    """Read the LLM response text from the api log file."""
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
                  level: int) -> None:
    try:
        with open(log_file, encoding='utf-8') as f:
            resp = json.load(f)
        usage = extract_usage(resp)
        cost = calculate_cost_from_usage(usage, model)
        log_operation(
            project_dir, 'propose-summaries', model,
            usage['input_tokens'], usage['output_tokens'], cost,
            target=f'level-{level}',
            cache_read=usage.get('cache_read', 0),
            cache_create=usage.get('cache_create', 0),
        )
    except Exception as e:
        log(f'WARNING: cost ledger update failed: {e}')
