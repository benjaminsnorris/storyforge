"""Comparison scoring — `storyforge score --compare` (#229).

Produces a multi-axis comparison of 2–4 candidates at the same level.
**Never declares an overall winner**. The report surfaces what each
candidate does best on each axis so the author decides.

Spec: docs/superpowers/specs/2026-05-24-elaboration-scoring-design.md
section "Comparison scoring".

v1 ships the deterministic axes only (length, presence of required
elements, registry conformance). LLM ceiling axes (specificity, irony,
hook word, etc.) ship in v2 with the rest of the LLM scoring
infrastructure.
"""

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
# Report assembly
# ============================================================================

def compare_candidates(level: str, candidates: list[str]) -> dict:
    """Compare 2–4 candidate texts at the given level.

    Args:
        level: 'logline' / 'synopsis' / 'act-shape' / 'theme'. (Other levels
            aren't supported in v1 — candidate comparison is most useful
            for the prose tier.)
        candidates: list of 2–4 candidate text strings.

    Returns:
        {
            'level': str,
            'candidates': list[{'label': 'A', 'text': str}],
            'axes': list[{'name': str, 'values': list[str]}],
            'narrative': str,  # what each candidate does best (when known)
        }

    Raises ValueError on bad inputs (wrong count, unknown level).
    """
    if level not in AXIS_EXTRACTORS:
        raise ValueError(
            f'comparison not supported for level {level!r}; '
            f'v1 supports: {sorted(AXIS_EXTRACTORS)}'
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

    # Collect axes from each candidate; preserve order from the first one.
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

    return {
        'level': level,
        'candidates': candidate_records,
        'axes': axes_table,
        # v1 has no LLM ceiling-axis narrative — placeholder for v2.
        'narrative': '',
    }


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
    lines.append('## Ceiling axes (LLM, v2)')
    lines.append('')
    lines.append('| Axis | ' + ' | '.join(c['label'] for c in result['candidates']) + ' |')
    lines.append(sep)
    for axis_name in ('specificity', 'irony between elements', 'memorable hook word',
                      'genre/tone via imagery'):
        lines.append(f'| {axis_name} | ' + ' | '.join('—' for _ in result['candidates']) + ' |')
    lines.append('')
    lines.append('## Author task')
    lines.append('')
    lines.append('Pick the axes that matter most for THIS story and decide. The '
                 'system does not recommend a winner — it surfaces what each '
                 'candidate does best so you can either pick one or synthesize.')
    lines.append('')
    return '\n'.join(lines)
