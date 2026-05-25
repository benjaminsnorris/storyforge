"""Multi-axis comparison of 2-4 candidates at the same level.

Never declares an overall winner — the report surfaces what each candidate
does best on each axis so the author decides. Deterministic floor axes
(length, registry conformance) always populate; LLM ceiling axes
(specificity, irony, hook word) populate when semantic=True.
"""

import json
import os
import re

from storyforge.scoring_levels import (
    _count_sentences,
    _count_words,
)


# ============================================================================
# Per-level deterministic axes
# ============================================================================

def _axes_for_logline(text: str) -> dict:
    """Deterministic axes for a logline candidate."""
    text = text.strip()
    return {
        'length (words)': str(_count_words(text)),
        'length ≤ 35 words': 'yes' if _count_words(text) <= 35 else 'no',
        'present': 'yes' if text else 'no',
    }


def _axes_for_synopsis(text: str) -> dict:
    text = text.strip()
    sentences = _count_sentences(text)
    return {
        'length (sentences)': str(sentences),
        'length 4–8 sentences': 'yes' if 4 <= sentences <= 8 else 'no',
        'word count': str(_count_words(text)),
        'present': 'yes' if text else 'no',
    }


def _axes_for_act_shape(text: str) -> dict:
    text = text.strip()
    act_headers = re.findall(r'^###\s+Act\s+\d+', text, flags=re.MULTILINE)
    return {
        'act sub-sections': str(len(act_headers)),
        'exactly 3 acts': 'yes' if len(act_headers) == 3 else 'no',
        'word count': str(_count_words(text)),
        'present': 'yes' if text else 'no',
    }


def _axes_for_theme(text: str) -> dict:
    text = text.strip()
    sentences = _count_sentences(text)
    return {
        'length (sentences)': str(sentences),
        'length 2–4 sentences': 'yes' if 2 <= sentences <= 4 else 'no',
        'present': 'yes' if text else 'no',
    }


# Map level name → axis extractor.
AXIS_EXTRACTORS = {
    'logline': _axes_for_logline,
    'synopsis': _axes_for_synopsis,
    'act-shape': _axes_for_act_shape,
    'act_shape': _axes_for_act_shape,
    'theme': _axes_for_theme,
}


# ============================================================================
# Ceiling axes — per-level LLM-judged qualities
# ============================================================================

# Per-level ceiling axis names. The LLM is asked to evaluate each
# candidate on these axes and return a short cell value per candidate.
# These names match the ceiling sketches in the scoring design doc.
CEILING_AXES = {
    'logline': (
        'specificity',
        'irony between elements',
        'memorable hook word',
        'genre/tone via imagery',
    ),
    'synopsis': (
        'causation visible (X because of Y, not X and then Y)',
        'internal arc traced alongside plot',
        'escalation in visible steps',
        'ending lands as inevitable-in-retrospect',
    ),
    'act-shape': (
        'Act 2 has its own internal arc',
        'climax falls out of Act 2 setup',
        'opposition pressure scales with protagonist',
        'each act has a different kind of pressure',
    ),
    'act_shape': (
        'Act 2 has its own internal arc',
        'climax falls out of Act 2 setup',
        'opposition pressure scales with protagonist',
        'each act has a different kind of pressure',
    ),
    'theme': (
        'distinct from generic claim',
        'alive in specifics',
        'asks a question rather than states a slogan',
        'audible across the story',
    ),
}


# ============================================================================
# Report assembly
# ============================================================================

def compare_candidates(level: str, candidates: list[str],
                       semantic: bool = False,
                       project_dir: str | None = None,
                       dry_run: bool = False) -> dict:
    """Compare 2–4 candidate texts at the given level.

    Args:
        level: 'logline' / 'synopsis' / 'act-shape' / 'theme'. (Other levels
            aren't supported — comparison is most useful for the prose tier.)
        candidates: list of 2–4 candidate text strings.
        semantic: when True, run the LLM to populate ceiling axes
            (specificity, irony, hook word, etc.). When False (default),
            ceiling axes are returned with '—' placeholders.
        project_dir: required when semantic=True (for cost ledger).
        dry_run: when True, semantic ceiling axes return em-dash
            placeholders even with semantic=True — no LLM call is made.
            Deterministic floor axes still populate normally.

    Returns:
        {
            'level': str,
            'candidates': list[{'label': 'A', 'text': str}],
            'axes': list[{'name': str, 'values': list[str]}],
            'ceiling_axes': list[{'name': str, 'values': list[str]}],
            'narrative': str,
        }

    Raises ValueError on bad inputs (wrong count, unknown level).
    """
    if level not in AXIS_EXTRACTORS:
        raise ValueError(
            f'comparison not supported for level {level!r}; '
            f'supports: {sorted(AXIS_EXTRACTORS)}'
        )
    if not 2 <= len(candidates) <= 4:
        raise ValueError(
            f'comparison takes 2–4 candidates; got {len(candidates)}'
        )

    extractor = AXIS_EXTRACTORS[level]
    labels = ['A', 'B', 'C', 'D'][:len(candidates)]
    candidate_records = [
        {'label': label, 'text': text} for label, text in zip(labels, candidates)
    ]

    # Floor axes: collect per-candidate dicts, preserve order from first.
    axis_names: list[str] = []
    per_candidate_axes: list[dict] = []
    for text in candidates:
        axes = extractor(text)
        per_candidate_axes.append(axes)
        for name in axes:
            if name not in axis_names:
                axis_names.append(name)

    axes_table = [
        {
            'name': name,
            'values': [str(c.get(name, '—')) for c in per_candidate_axes],
        }
        for name in axis_names
    ]

    # Ceiling axes: populated via LLM when semantic=True (unless dry_run).
    ceiling_axes_table = _ceiling_axes_for(
        level, candidates, semantic and not dry_run,
        project_dir=project_dir,
    )

    return {
        'level': level,
        'candidates': candidate_records,
        'axes': axes_table,
        'ceiling_axes': ceiling_axes_table,
        'narrative': '',
    }


def _ceiling_axes_for(level: str, candidates: list[str], semantic: bool,
                       project_dir: str | None) -> list[dict]:
    """Build the ceiling-axes table.

    semantic=False → '—' placeholder values (deterministic-only).
    semantic=True  → one LLM call evaluates all candidates on the level's
                     ceiling-axis set, returns per-candidate values.
    """
    axis_names = CEILING_AXES.get(level, ())
    if not semantic:
        return [
            {'name': name, 'values': ['—' for _ in candidates]}
            for name in axis_names
        ]
    if project_dir is None:
        raise ValueError(
            'semantic=True requires project_dir (for cost ledger tracking)'
        )
    return _llm_ceiling_axes(level, candidates, axis_names, project_dir)


def _llm_ceiling_axes(level: str, candidates: list[str],
                      axis_names: tuple[str, ...],
                      project_dir: str) -> list[dict]:
    """Call the LLM once to score every candidate on every ceiling axis.

    Returns a table matching CEILING_AXES[level]. On LLM failure or parse
    error, returns the placeholder em-dashes so callers always get a
    well-shaped result.
    """
    # Local imports keep the module importable without API deps for
    # callers that only want the deterministic floor axes.
    from storyforge.api import (
        invoke_to_file, extract_text_from_file,
        extract_usage, calculate_cost_from_usage,
    )
    from storyforge.common import log, select_model
    from storyforge.costs import log_operation

    model = select_model('evaluation')

    labels = ['A', 'B', 'C', 'D'][:len(candidates)]
    cands_block = '\n'.join(
        f'## Candidate {label}\n{text.strip()}'
        for label, text in zip(labels, candidates)
    )
    axes_block = '\n'.join(f'- {name}' for name in axis_names)

    prompt = f"""\
You are comparing {len(candidates)} candidate {level}s for a story project.
The goal is NOT to pick a winner — the goal is to surface what each
candidate does best on each axis so the author can decide or synthesize.

# Candidates

{cands_block}

# Axes to evaluate

{axes_block}

# Task

Return ONE JSON object with this shape:

{{
  "axes": [
    {{"name": "{axis_names[0] if axis_names else 'example'}",
      "values": ["short cell for A", "short cell for B", ...]}},
    ...
  ]
}}

Rules:
  - Exactly {len(candidates)} values per axis, in order: {", ".join(labels)}.
  - Each cell is a short phrase (2-6 words), not a sentence. Compare
    candidates *against each other*, not against an absolute standard.
    For example, for "specificity" prefer values like "high", "medium",
    "low", "highest", "vague" — not "the cartographer is specific".
  - Cover every axis listed above, in the order given.
  - **Do not declare an overall winner.** No "best", "preferred",
    "recommended". The author decides.

Return only the JSON object.
"""

    log_dir = os.path.join(project_dir, 'working', 'logs',
                           'comparison-ceiling')
    os.makedirs(log_dir, exist_ok=True)
    log_file = os.path.join(log_dir, f'{level}-ceiling.json')

    try:
        invoke_to_file(prompt, model, log_file, max_tokens=1024)
    except Exception as e:
        log(f'WARNING: LLM ceiling-axes call failed for {level}: {e}')
        return [
            {'name': name, 'values': ['—' for _ in candidates]}
            for name in axis_names
        ]

    text = extract_text_from_file(log_file)
    if not text:
        log(f'WARNING: empty LLM response for {level} ceiling axes')
        return [
            {'name': name, 'values': ['—' for _ in candidates]}
            for name in axis_names
        ]

    parsed = _parse_ceiling_response(text)
    if parsed is None:
        log(f'WARNING: could not parse LLM ceiling-axes response for {level}')
        return [
            {'name': name, 'values': ['—' for _ in candidates]}
            for name in axis_names
        ]

    # Cost ledger
    try:
        with open(log_file, encoding='utf-8') as f:
            resp = json.load(f)
        usage = extract_usage(resp)
        cost = calculate_cost_from_usage(usage, model)
        log_operation(
            project_dir, 'score-compare-ceiling', model,
            usage['input_tokens'], usage['output_tokens'], cost,
            target=level,
            cache_read=usage.get('cache_read', 0),
            cache_create=usage.get('cache_create', 0),
        )
    except Exception as e:
        log(f'WARNING: cost ledger update failed: {e}')

    # Defensively coerce the parsed shape to what we need. Missing axes
    # get filled with em-dashes; mis-sized value lists get padded/trimmed.
    received = {a.get('name', ''): a.get('values', []) for a in parsed}
    out: list[dict] = []
    for name in axis_names:
        vals = received.get(name, [])
        if len(vals) < len(candidates):
            vals = list(vals) + ['—'] * (len(candidates) - len(vals))
        elif len(vals) > len(candidates):
            vals = list(vals)[:len(candidates)]
        out.append({'name': name, 'values': [str(v) for v in vals]})
    return out


def _parse_ceiling_response(text: str) -> list[dict] | None:
    """Pull the `axes` list out of the LLM's response. Tolerant of fenced
    blocks and leading/trailing prose. Returns None on failure."""
    def _take(obj):
        if isinstance(obj, dict):
            inner = obj.get('axes')
            if isinstance(inner, list):
                return inner
        return None

    try:
        return _take(json.loads(text))
    except json.JSONDecodeError:
        pass
    m = re.search(r'```(?:json)?\s*\n(.*?)\n```', text, re.DOTALL)
    if m:
        try:
            return _take(json.loads(m.group(1).strip()))
        except json.JSONDecodeError:
            pass
    m = re.search(r'\{.*\}', text, re.DOTALL)
    if m:
        try:
            return _take(json.loads(m.group(0)))
        except json.JSONDecodeError:
            pass
    return None


def render_report(result: dict) -> str:
    """Render a comparison result dict as a human-readable markdown report.

    Used by cmd_score --compare to produce
    `working/comparison-<level>-<timestamp>.md`.
    """
    lines: list[str] = []
    lines.append(f'# Comparison: {result["level"]} candidates ({len(result["candidates"])})')
    lines.append('')
    lines.append('## Candidates')
    lines.append('')
    for c in result['candidates']:
        text = c['text'].strip().replace('\n', ' ')
        lines.append(f'- **{c["label"]}**: {text}')
    lines.append('')
    lines.append('## Floor checks (deterministic)')
    lines.append('')
    # Build the table
    header = '| Axis | ' + ' | '.join(c['label'] for c in result['candidates']) + ' |'
    sep = '|---' * (1 + len(result['candidates'])) + '|'
    lines.append(header)
    lines.append(sep)
    for axis in result['axes']:
        row = f'| {axis["name"]} | ' + ' | '.join(axis['values']) + ' |'
        lines.append(row)
    lines.append('')
    ceiling_axes = result.get('ceiling_axes', [])
    ceiling_populated = any(
        any(v != '—' for v in axis.get('values', []))
        for axis in ceiling_axes
    )
    if ceiling_populated:
        lines.append('## Ceiling axes (LLM)')
    else:
        lines.append('## Ceiling axes (LLM — run with --semantic to populate)')
    lines.append('')
    lines.append('| Axis | ' + ' | '.join(c['label'] for c in result['candidates']) + ' |')
    lines.append(sep)
    for axis in ceiling_axes:
        lines.append(f'| {axis["name"]} | ' + ' | '.join(axis['values']) + ' |')
    lines.append('')
    lines.append('## Author task')
    lines.append('')
    lines.append('Pick the axes that matter most for THIS story and decide. The '
                 'system does not recommend a winner — it surfaces what each '
                 'candidate does best so you can either pick one or synthesize.')
    lines.append('')
    return '\n'.join(lines)
