"""Tests for scoring_comparison.py — `storyforge score --compare` (#229)."""

import pytest

from storyforge.scoring_comparison import (
    compare_candidates,
    render_report,
)


# ---------------------------------------------------------------------------
# Input validation
# ---------------------------------------------------------------------------

def test_unknown_level_raises():
    with pytest.raises(ValueError, match='not supported'):
        compare_candidates('spine', ['a', 'b'])


def test_too_few_candidates_raises():
    with pytest.raises(ValueError, match='2.4'):
        compare_candidates('logline', ['only one'])


def test_too_many_candidates_raises():
    with pytest.raises(ValueError, match='2.4'):
        compare_candidates('logline', ['a', 'b', 'c', 'd', 'e'])


# ---------------------------------------------------------------------------
# Logline comparison
# ---------------------------------------------------------------------------

def test_logline_compare_labels_two_candidates():
    result = compare_candidates('logline', [
        'A cartographer loses his daughter.',
        'A cartographer must find his daughter using only maps he made.',
    ])
    assert result['level'] == 'logline'
    assert [c['label'] for c in result['candidates']] == ['A', 'B']


def test_logline_compare_labels_four_candidates():
    result = compare_candidates('logline', ['a', 'b', 'c', 'd'])
    assert [c['label'] for c in result['candidates']] == ['A', 'B', 'C', 'D']


def test_logline_compare_axes_include_length():
    result = compare_candidates('logline', ['short.', 'a ' * 40])
    axis_names = [a['name'] for a in result['axes']]
    assert 'length (words)' in axis_names
    assert 'length ≤ 35 words' in axis_names


def test_logline_compare_no_winner_field():
    """The comparison result must not contain a 'winner' or similar."""
    result = compare_candidates('logline', ['a', 'b'])
    # Must not include any "best" / "winner" / "recommended" key
    for key in result:
        assert key.lower() not in ('winner', 'best', 'recommended')


# ---------------------------------------------------------------------------
# Synopsis comparison
# ---------------------------------------------------------------------------

def test_synopsis_compare_sentence_count_axis():
    result = compare_candidates('synopsis', [
        'One sentence only.',
        'Six sentences. Two. Three. Four. Five. Six.',
    ])
    axis_names = [a['name'] for a in result['axes']]
    assert 'length (sentences)' in axis_names
    # First candidate has 1 sentence, second has 6
    sentence_axis = next(a for a in result['axes'] if a['name'] == 'length (sentences)')
    assert sentence_axis['values'][0] == '1'
    assert sentence_axis['values'][1] == '6'


# ---------------------------------------------------------------------------
# Act-shape comparison
# ---------------------------------------------------------------------------

def test_act_shape_compare_counts_acts():
    result = compare_candidates('act-shape', [
        '### Act 1\nstuff\n\n### Act 2\nstuff\n\n### Act 3\nstuff',
        '### Act 1\nonly one',
    ])
    sub_axis = next(a for a in result['axes'] if 'sub-sections' in a['name'])
    assert sub_axis['values'][0] == '3'
    assert sub_axis['values'][1] == '1'


# ---------------------------------------------------------------------------
# Theme comparison
# ---------------------------------------------------------------------------

def test_theme_compare():
    result = compare_candidates('theme', [
        'Two sentences. Yes.',
        'Five sentences here. One. Two. Three. Four.',
    ])
    sentence_axis = next(a for a in result['axes'] if 'length (sentences)' in a['name'])
    assert sentence_axis['values'][0] == '2'
    assert sentence_axis['values'][1] == '5'


# ---------------------------------------------------------------------------
# Rendering
# ---------------------------------------------------------------------------

def test_render_report_has_no_winner_language():
    """The rendered markdown must say 'does not recommend a winner'
    and not declare a best candidate."""
    result = compare_candidates('logline', ['a', 'b'])
    md = render_report(result)
    assert 'does not recommend a winner' in md
    assert 'Author task' in md
    # No "Best:" or "Winner:" headers
    for forbidden in ('# Winner', '## Winner', '**Best:', '## Best'):
        assert forbidden not in md


def test_render_report_has_ceiling_placeholder():
    """v1 ships with the ceiling-axes table populated by em-dashes; the
    placeholder structure should be present so v2 can fill it in."""
    result = compare_candidates('logline', ['a', 'b'])
    md = render_report(result)
    assert 'Ceiling axes' in md
    assert 'specificity' in md
    assert '—' in md  # placeholder em-dash for unfilled axes


def test_render_report_includes_all_candidate_columns():
    result = compare_candidates('logline', ['a', 'b', 'c'])
    md = render_report(result)
    # The candidate label headers appear in the table
    assert '| A |' in md or '| Axis | A |' in md
    assert 'B' in md
    assert 'C' in md
