"""Story-power scorecard — 8 research-grounded craft axes scored on
pitch artifacts (logline + synopsis + theme, optional spine/architecture).

Distinct from craft scoring (prose-level) and structural validation
(CSV-mechanical). Answers: if this story were rendered with adequate
prose, is it built to last?

See references/story-power-rubric.md for the full axis definitions,
research basis, signals, and worked example.
"""

import json
import os
import re
from datetime import datetime, timezone
from typing import NamedTuple

from storyforge.api import (
    invoke_to_file, calculate_cost_from_usage, extract_usage,
)
from storyforge.common import (
    CoachingLevel, get_plugin_dir, log, parse_story_summary, select_model,
)
from storyforge.costs import log_operation


class Axis(NamedTuple):
    key: str
    name: str
    weight: float  # 1.0 or 1.5


AXES: tuple[Axis, ...] = (
    Axis('specificity', 'Specificity & concreteness', 1.0),
    Axis('emotional_resonance', 'Emotional resonance', 1.0),
    Axis('character_identification', 'Character identification', 1.0),
    Axis('stakes_dilemma', 'Stakes & dilemma', 1.5),
    Axis('archetypal_resonance', 'Archetypal resonance', 1.5),
    Axis('thematic_depth', 'Thematic depth', 1.5),
    Axis('surprise_subversion', 'Surprise & genre subversion', 1.0),
    Axis('moral_weight', 'Moral weight', 1.5),
)
AXIS_KEYS = tuple(a.key for a in AXES)
AXIS_BY_KEY = {a.key: a for a in AXES}


def composite_score(scores: dict[str, int | float]) -> float:
    """Return the weighted composite from a {axis_key: score} dict.

    Falls back to a flat average if any axis is missing; never raises.
    Score range stays 1-10.
    """
    total_w = 0.0
    total = 0.0
    for axis in AXES:
        s = scores.get(axis.key)
        if s is None:
            continue
        total_w += axis.weight
        total += float(s) * axis.weight
    if total_w == 0:
        return 0.0
    return round(total / total_w, 2)


# ---------------------------------------------------------------------------
# Inputs
# ---------------------------------------------------------------------------

def _read_optional(path: str, head_lines: int | None = None) -> str:
    if not os.path.isfile(path):
        return ''
    try:
        with open(path, encoding='utf-8') as f:
            text = f.read()
    except (OSError, UnicodeDecodeError):
        return ''
    if head_lines:
        lines = text.splitlines()
        if len(lines) > head_lines:
            text = '\n'.join(lines[:head_lines]) + '\n…'
    return text


def gather_pitch_artifacts(project_dir: str) -> dict[str, str]:
    """Read the artifacts the story-power rubric operates on.

    story-summary.md is required; spine and architecture summaries are
    optional context (improve specificity scoring when present).
    """
    summary = parse_story_summary(project_dir) or {}
    spine_summaries = _summary_column_from_csv(
        os.path.join(project_dir, 'reference', 'spine.csv'),
    )
    architecture_summaries = _summary_column_from_csv(
        os.path.join(project_dir, 'reference', 'architecture.csv'),
    )
    return {
        'logline': summary.get('logline', '').strip(),
        'synopsis': summary.get('synopsis', '').strip(),
        'act_shape': summary.get('act_shape', '').strip(),
        'theme': summary.get('theme', '').strip(),
        'spine_summaries': spine_summaries,
        'architecture_summaries': architecture_summaries,
    }


def _summary_column_from_csv(csv_path: str) -> str:
    """Pull the `summary` column from a pipe-delimited CSV as a numbered
    bullet list. Returns '' if the file is missing or has no summary col."""
    if not os.path.isfile(csv_path):
        return ''
    with open(csv_path, encoding='utf-8') as f:
        raw = f.read().replace('\r\n', '\n').replace('\r', '')
    lines = [l for l in raw.splitlines() if l.strip()]
    if len(lines) < 2:
        return ''
    headers = lines[0].split('|')
    if 'summary' not in headers:
        return ''
    out: list[str] = []
    for i, line in enumerate(lines[1:], start=1):
        cells = line.split('|')
        if len(cells) != len(headers):
            continue
        row = dict(zip(headers, cells))
        s = row.get('summary', '').strip()
        if s:
            out.append(f'{i}. {s}')
    return '\n'.join(out)


# ---------------------------------------------------------------------------
# Prompt
# ---------------------------------------------------------------------------

def _build_prompt(artifacts: dict[str, str], rubric: str) -> str:
    """Assemble the LLM prompt for full-mode scoring."""
    axes_block = '\n'.join(
        f'  - "{a.key}": "{a.name}"' for a in AXES
    )
    return f"""You are evaluating the story DESIGN of a project at the pitch tier,
using the rubric provided. Do NOT score prose quality — score whether
the story is structurally and thematically built to last.

# Rubric

{rubric}

# Pitch artifacts

## Logline
{artifacts['logline'] or '(empty)'}

## Synopsis
{artifacts['synopsis'] or '(empty)'}

## Act-shape
{artifacts['act_shape'] or '(empty)'}

## Theme
{artifacts['theme'] or '(empty)'}

## Spine (one sentence per event)
{artifacts['spine_summaries'] or '(empty)'}

## Architecture (one sentence per anchor)
{artifacts['architecture_summaries'] or '(empty)'}

# Task

Return a JSON object with this exact shape:

{{
  "axes": {{
{axes_block}
  }},
  "scores": [
    {{
      "axis": "specificity",
      "score": 1-10 integer,
      "positive_signals": "semicolon-separated quoted signals from the pitch",
      "negative_signals": "semicolon-separated quoted abstractions / gaps",
      "rationale": "one-sentence justification grounded in the pitch"
    }},
    ... one entry per axis key in the order listed above ...
  ],
  "diagnostic": {{
    "cross_axis_root_cause": "one sentence: when two or more axes share a single underlying gap, name it",
    "high_leverage_move": "one sentence: ONE revision the author could make that lifts multiple axes",
    "example_sentence": "an optional concrete sentence to insert in the synopsis that would deliver the move"
  }}
}}

Reserve scores of 10 for prose-verified excellence; cap synopsis-stage
scores at 9 on most axes. Be specific and grounded — quote the pitch.
Return ONLY the JSON object.
"""


# ---------------------------------------------------------------------------
# Public scoring entry points
# ---------------------------------------------------------------------------

def score_story_power(project_dir: str, coaching: CoachingLevel,
                      dry_run: bool = False) -> dict:
    """Run the story-power scorecard at the given coaching level.

    Returns a result dict:
      {
        'mode': 'full' | 'coach' | 'strict' | 'full→coach (...)',
        'output_dir': absolute path to the timestamped output directory,
        'composite': float (or 0.0 if no scores produced),
        'scores': {axis_key: int} or {} (coach/strict),
        'deltas': {axis_key: int} or {} (vs previous run),
        'diagnostic': dict or {},
      }
    """
    artifacts = gather_pitch_artifacts(project_dir)
    if not artifacts['logline'] and not artifacts['synopsis']:
        log('ERROR: story-power scoring requires reference/story-summary.md '
            'with at least a logline + synopsis populated.')
        return {'mode': coaching, 'output_dir': '', 'composite': 0.0,
                'scores': {}, 'deltas': {}, 'diagnostic': {}}

    rubric = _load_rubric()
    timestamp = datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')
    output_dir = os.path.join(project_dir, 'working', 'scores',
                              'story-power', timestamp)

    if coaching == 'strict':
        if dry_run:
            log(f'DRY RUN — would write strict checklist to {output_dir}')
            return {'mode': 'strict', 'output_dir': output_dir,
                    'composite': 0.0, 'scores': {}, 'deltas': {},
                    'diagnostic': {}}
        os.makedirs(output_dir, exist_ok=True)
        _write_strict_checklist(output_dir, artifacts, rubric)
        return {'mode': 'strict', 'output_dir': output_dir,
                'composite': 0.0, 'scores': {}, 'deltas': {},
                'diagnostic': {}}

    if dry_run:
        log(f'DRY RUN — would call LLM to score 8 axes; output → {output_dir}')
        return {'mode': f'{coaching}→dry-run', 'output_dir': output_dir,
                'composite': 0.0, 'scores': {}, 'deltas': {},
                'diagnostic': {}}

    # full + coach both call the LLM; differ only in destination.
    if not os.environ.get('ANTHROPIC_API_KEY'):
        log('ERROR: ANTHROPIC_API_KEY is not set. story-power scoring in '
            f'{coaching} coaching requires an API key. Set it and re-run, '
            'or use --coaching strict for the deterministic checklist.')
        return {'mode': coaching, 'output_dir': '', 'composite': 0.0,
                'scores': {}, 'deltas': {}, 'diagnostic': {}}

    os.makedirs(output_dir, exist_ok=True)
    parsed, actual_mode = _invoke_and_parse(project_dir, output_dir,
                                              artifacts, rubric, coaching)
    if not parsed:
        return {'mode': actual_mode, 'output_dir': output_dir,
                'composite': 0.0, 'scores': {}, 'deltas': {},
                'diagnostic': {}}

    scores = {row['axis']: int(row['score'])
              for row in parsed.get('scores', [])
              if row.get('axis') in AXIS_BY_KEY}
    composite = composite_score(scores)
    deltas = _compute_deltas(project_dir, scores)

    if coaching == 'full':
        _write_full_scorecard(output_dir, scores, parsed, composite,
                               deltas, artifacts)
    else:  # coach
        _write_coach_brief(output_dir, scores, parsed, composite,
                           deltas, artifacts)

    return {'mode': actual_mode, 'output_dir': output_dir,
            'composite': composite, 'scores': scores, 'deltas': deltas,
            'diagnostic': parsed.get('diagnostic') or {}}


def _load_rubric() -> str:
    """Return the rubric text from references/story-power-rubric.md."""
    path = os.path.join(get_plugin_dir(), 'references',
                        'story-power-rubric.md')
    if not os.path.isfile(path):
        log('WARNING: references/story-power-rubric.md not found; '
            'the LLM scores will lack rubric grounding.')
        return ''
    with open(path, encoding='utf-8') as f:
        return f.read()


def _invoke_and_parse(project_dir: str, output_dir: str,
                       artifacts: dict[str, str], rubric: str,
                       coaching: CoachingLevel,
                       ) -> tuple[dict | None, str]:
    """Call the LLM and return (parsed_json, actual_mode)."""
    prompt = _build_prompt(artifacts, rubric)
    model = select_model('creative')
    log_dir = os.path.join(project_dir, 'working', 'logs', 'story-power')
    os.makedirs(log_dir, exist_ok=True)
    log_file = os.path.join(log_dir,
                            os.path.basename(output_dir) + '.json')
    try:
        invoke_to_file(prompt, model, log_file, max_tokens=4096)
    except Exception as e:
        log(f'ERROR: story-power LLM call failed: {e}')
        return None, f'{coaching} (LLM error)'
    text = _read_response_text(log_file)
    parsed = _parse_response(text)
    if not parsed:
        _record_cost(project_dir, log_file, model, target='story-power:unparseable')
        log(f'ERROR: story-power LLM response unparseable; raw at {log_file}')
        return None, f'{coaching} (unparseable)'
    _record_cost(project_dir, log_file, model)
    return parsed, coaching


def _read_response_text(log_file: str) -> str:
    try:
        with open(log_file, encoding='utf-8') as f:
            resp = json.load(f)
    except (OSError, json.JSONDecodeError) as e:
        log(f'WARNING: could not read story-power response file: {e}')
        return ''
    for block in resp.get('content', []):
        if block.get('type') == 'text':
            return block.get('text', '')
    return ''


def _parse_response(text: str) -> dict | None:
    """Tolerant JSON parse: direct → fenced → greedy. Validates shape."""
    def _take(obj):
        if not isinstance(obj, dict):
            return None
        scores = obj.get('scores')
        if not isinstance(scores, list):
            return None
        return obj
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
    return None


def _record_cost(project_dir: str, log_file: str, model: str, *,
                  target: str = 'story-power') -> None:
    try:
        with open(log_file, encoding='utf-8') as f:
            resp = json.load(f)
    except (OSError, json.JSONDecodeError) as e:
        log(f'WARNING: cost ledger update failed reading {log_file}: {e}')
        return
    usage = extract_usage(resp)
    cost = calculate_cost_from_usage(usage, model)
    log_operation(
        project_dir, 'score-story-power', model,
        usage['input_tokens'], usage['output_tokens'], cost,
        target=target,
        cache_read=usage.get('cache_read', 0),
        cache_create=usage.get('cache_create', 0),
    )


# ---------------------------------------------------------------------------
# Delta tracking
# ---------------------------------------------------------------------------

def _compute_deltas(project_dir: str,
                     current_scores: dict[str, int]) -> dict[str, int]:
    """Compare current scores against the most recent prior run.

    Returns {axis_key: delta} where delta = current - previous. Empty
    when no prior run exists.
    """
    base = os.path.join(project_dir, 'working', 'scores', 'story-power')
    if not os.path.isdir(base):
        return {}
    prior_runs = sorted(d for d in os.listdir(base)
                        if os.path.isdir(os.path.join(base, d)))
    # Drop the current run if it's already in the list (just-created dir).
    prior_runs = [d for d in prior_runs
                  if os.path.isfile(
                      os.path.join(base, d, 'scorecard.csv'),
                  )]
    if not prior_runs:
        return {}
    prev_path = os.path.join(base, prior_runs[-1], 'scorecard.csv')
    prev_scores = _read_scorecard_scores(prev_path)
    return {k: current_scores[k] - prev_scores[k]
            for k in current_scores if k in prev_scores}


def _read_scorecard_scores(path: str) -> dict[str, int]:
    """Read {axis: score} from a scorecard.csv."""
    if not os.path.isfile(path):
        return {}
    out: dict[str, int] = {}
    with open(path, encoding='utf-8') as f:
        lines = [l for l in f.read().splitlines() if l.strip()]
    if len(lines) < 2:
        return {}
    headers = lines[0].split('|')
    for line in lines[1:]:
        cells = line.split('|')
        if len(cells) != len(headers):
            continue
        row = dict(zip(headers, cells))
        axis = row.get('axis', '').strip()
        try:
            out[axis] = int(row.get('score', '0'))
        except ValueError:
            continue
    return out


# ---------------------------------------------------------------------------
# Output writers
# ---------------------------------------------------------------------------

def _sanitize_cell(value: str) -> str:
    if not isinstance(value, str):
        value = str(value)
    return value.replace('|', '/').replace('\n', ' ').replace('\r', '').strip()


def _write_full_scorecard(output_dir: str, scores: dict[str, int],
                            parsed: dict, composite: float,
                            deltas: dict[str, int],
                            artifacts: dict[str, str]) -> None:
    """full coaching: write scorecard.csv + diagnostic.md."""
    csv_path = os.path.join(output_dir, 'scorecard.csv')
    headers = ['axis', 'name', 'score', 'weight', 'positive_signals',
               'negative_signals', 'rationale']
    rows_by_axis = {r.get('axis'): r for r in parsed.get('scores', [])}
    lines = ['|'.join(headers)]
    for axis in AXES:
        row = rows_by_axis.get(axis.key, {})
        lines.append('|'.join(_sanitize_cell(c) for c in (
            axis.key,
            axis.name,
            str(row.get('score', '')),
            str(axis.weight),
            row.get('positive_signals', ''),
            row.get('negative_signals', ''),
            row.get('rationale', ''),
        )))
    with open(csv_path, 'w', encoding='utf-8') as f:
        f.write('\n'.join(lines) + '\n')

    md_path = os.path.join(output_dir, 'diagnostic.md')
    diag = parsed.get('diagnostic') or {}
    md_lines = [
        f'# Story-power scorecard — diagnostic',
        '',
        f'Composite (weighted): **{composite}** / 10.',
        '',
        '## Per-axis scores',
        '',
        '| Axis | Score | Weight | Δ vs last run |',
        '|---|---|---|---|',
    ]
    for axis in AXES:
        s = scores.get(axis.key, '–')
        d = deltas.get(axis.key)
        d_text = f'{d:+d}' if d is not None and d != 0 else ('–' if d is None else '0')
        md_lines.append(f'| {axis.name} | {s} | {axis.weight} | {d_text} |')
    md_lines.extend([
        '',
        '## Diagnostic',
        '',
        f'**Cross-axis root cause:** {diag.get("cross_axis_root_cause") or "(none identified)"}',
        '',
        f'**High-leverage move:** {diag.get("high_leverage_move") or "(none proposed)"}',
        '',
    ])
    example = diag.get('example_sentence')
    if example:
        md_lines.extend([
            '**Example sentence to consider:**',
            '',
            f'> {example}',
            '',
        ])
    with open(md_path, 'w', encoding='utf-8') as f:
        f.write('\n'.join(md_lines) + '\n')


def _write_coach_brief(output_dir: str, scores: dict[str, int],
                        parsed: dict, composite: float,
                        deltas: dict[str, int],
                        artifacts: dict[str, str]) -> None:
    """coach coaching: write a review brief with the LLM proposals +
    author-facing questions per axis."""
    md_path = os.path.join(output_dir, 'coaching-brief.md')
    diag = parsed.get('diagnostic') or {}
    rows_by_axis = {r.get('axis'): r for r in parsed.get('scores', [])}
    out: list[str] = [
        f'# Story-power scorecard — coaching brief',
        '',
        f'Proposed composite (weighted): {composite} / 10. The scores '
        'below are LLM proposals for author review — not authoritative. '
        'Use them to focus revision; the author decides what to act on.',
        '',
    ]
    for axis in AXES:
        row = rows_by_axis.get(axis.key, {})
        out.extend([
            f'## {axis.name} (proposed {row.get("score", "–")}, weight {axis.weight})',
            '',
            f'- Positive: {row.get("positive_signals", "—")}',
            f'- Negative: {row.get("negative_signals", "—")}',
            f'- Rationale: {row.get("rationale", "—")}',
            f'- Question: does the score match your read? If not, what '
            'signal is the LLM missing?',
            '',
        ])
    out.extend([
        '## Diagnostic',
        '',
        f'**Cross-axis root cause:** {diag.get("cross_axis_root_cause") or "(none identified)"}',
        '',
        f'**High-leverage move:** {diag.get("high_leverage_move") or "(none proposed)"}',
        '',
    ])
    example = diag.get('example_sentence')
    if example:
        out.extend([
            '**Example sentence to consider:**',
            '',
            f'> {example}',
            '',
        ])
    with open(md_path, 'w', encoding='utf-8') as f:
        f.write('\n'.join(out) + '\n')


def _write_strict_checklist(output_dir: str, artifacts: dict[str, str],
                              rubric: str) -> None:
    """strict coaching: rule-based checklist of signals per axis, no LLM
    call. Lists what to look for and a 'self-score 1-10' line the author
    fills in by hand."""
    md_path = os.path.join(output_dir, 'self-scoring-checklist.md')
    out: list[str] = [
        '# Story-power scorecard — self-scoring checklist',
        '',
        f'Generated for coaching=strict on '
        f'{datetime.now(timezone.utc).isoformat()}. For each axis below, '
        'review the signals in the rubric and assign a 1-10 score yourself. '
        'No LLM call has been made. See references/story-power-rubric.md '
        'for full signal definitions and scoring bands.',
        '',
    ]
    for axis in AXES:
        out.extend([
            f'## {axis.name} (weight {axis.weight})',
            '',
            f'Self-score (1-10): __',
            '',
            'Positive signals you found:',
            '- ',
            '',
            'Negative signals you found:',
            '- ',
            '',
        ])
    with open(md_path, 'w', encoding='utf-8') as f:
        f.write('\n'.join(out) + '\n')
