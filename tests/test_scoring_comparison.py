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


# ---------------------------------------------------------------------------
# Semantic (v2) ceiling axes
# ---------------------------------------------------------------------------

import json

_FAKE_CEILING_RESPONSE = {
    'axes': [
        {'name': 'specificity', 'values': ['low', 'high']},
        {'name': 'irony between elements', 'values': ['absent', 'present']},
        {'name': 'memorable hook word', 'values': ['none', '"never recorded"']},
        {'name': 'genre/tone via imagery', 'values': ['generic', 'literary']},
    ],
}


def _mock_ceiling_invoke(prompt, model, log_file, **kwargs):
    import os
    os.makedirs(os.path.dirname(log_file) or '.', exist_ok=True)
    response = {
        'content': [{'type': 'text', 'text': json.dumps(_FAKE_CEILING_RESPONSE)}],
        'usage': {
            'input_tokens': 800, 'output_tokens': 300,
            'cache_read_input_tokens': 0, 'cache_creation_input_tokens': 0,
        },
    }
    with open(log_file, 'w') as f:
        json.dump(response, f)
    return response


def test_semantic_requires_project_dir():
    """semantic=True without project_dir raises (cost ledger needs the path)."""
    with pytest.raises(ValueError, match='project_dir'):
        compare_candidates('logline', ['a', 'b'], semantic=True)


def test_semantic_populates_ceiling_axes(project_dir, monkeypatch):
    """With semantic=True, ceiling axes get LLM-populated values instead of
    em-dash placeholders."""
    from storyforge import api, scoring_comparison
    monkeypatch.setattr(api, 'invoke_to_file', _mock_ceiling_invoke)
    # scoring_comparison imports invoke_to_file LOCALLY inside the function
    # (to keep the module importable without API deps); the api-module
    # patch is enough.

    result = compare_candidates(
        'logline',
        ['A logline.', 'A different, more specific logline with a hook.'],
        semantic=True, project_dir=project_dir,
    )
    ceiling = result['ceiling_axes']
    # All four logline ceiling axes present
    names = [a['name'] for a in ceiling]
    assert 'specificity' in names
    assert 'irony between elements' in names
    assert 'memorable hook word' in names
    # And the values came from the mock, not '—'
    specificity = next(a for a in ceiling if a['name'] == 'specificity')
    assert specificity['values'] == ['low', 'high']


def test_semantic_off_uses_placeholders(project_dir):
    """semantic=False → em-dash placeholders. (Default behavior unchanged.)"""
    result = compare_candidates('logline', ['a', 'b'], semantic=False)
    ceiling = result['ceiling_axes']
    assert all(all(v == '—' for v in a['values']) for a in ceiling)


def test_semantic_recovers_gracefully_from_bad_llm_response(project_dir, monkeypatch):
    """LLM returns garbage → placeholders fill in, no crash."""
    def garbage(prompt, model, log_file, **kwargs):
        import os
        os.makedirs(os.path.dirname(log_file) or '.', exist_ok=True)
        response = {
            'content': [{'type': 'text', 'text': 'this is not json'}],
            'usage': {'input_tokens': 100, 'output_tokens': 20,
                      'cache_read_input_tokens': 0, 'cache_creation_input_tokens': 0},
        }
        with open(log_file, 'w') as f:
            json.dump(response, f)
        return response

    from storyforge import api
    monkeypatch.setattr(api, 'invoke_to_file', garbage)

    result = compare_candidates('logline', ['a', 'b'], semantic=True,
                                project_dir=project_dir)
    ceiling = result['ceiling_axes']
    assert all(all(v == '—' for v in a['values']) for a in ceiling)


def test_semantic_pads_undersized_value_lists(project_dir, monkeypatch):
    """If the LLM returns fewer values than candidates, pad with '—' rather
    than crash."""
    def short_response(prompt, model, log_file, **kwargs):
        import os
        os.makedirs(os.path.dirname(log_file) or '.', exist_ok=True)
        payload = {'axes': [{'name': 'specificity', 'values': ['high']}]}  # only 1!
        response = {
            'content': [{'type': 'text', 'text': json.dumps(payload)}],
            'usage': {'input_tokens': 100, 'output_tokens': 20,
                      'cache_read_input_tokens': 0, 'cache_creation_input_tokens': 0},
        }
        with open(log_file, 'w') as f:
            json.dump(response, f)
        return response

    from storyforge import api
    monkeypatch.setattr(api, 'invoke_to_file', short_response)

    result = compare_candidates('logline', ['a', 'b', 'c'], semantic=True,
                                project_dir=project_dir)
    specificity = next(a for a in result['ceiling_axes'] if a['name'] == 'specificity')
    assert specificity['values'] == ['high', '—', '—']


def test_render_report_shows_populated_ceiling_when_semantic(project_dir, monkeypatch):
    """When ceiling axes are populated, the report header says "Ceiling
    axes (LLM)" not "(LLM — run with --semantic ...)"."""
    from storyforge import api
    monkeypatch.setattr(api, 'invoke_to_file', _mock_ceiling_invoke)
    result = compare_candidates('logline', ['a', 'b'], semantic=True,
                                project_dir=project_dir)
    md = render_report(result)
    assert '## Ceiling axes (LLM)' in md
    assert '--semantic to populate' not in md


def test_render_report_shows_placeholder_ceiling_when_not_semantic():
    """Default (no semantic) → the report invites the author to re-run."""
    result = compare_candidates('logline', ['a', 'b'])
    md = render_report(result)
    assert 'run with --semantic to populate' in md


def test_semantic_ledger_records_compare_call(project_dir, monkeypatch):
    import os
    from storyforge import api
    monkeypatch.setattr(api, 'invoke_to_file', _mock_ceiling_invoke)

    compare_candidates('logline', ['a', 'b'], semantic=True,
                       project_dir=project_dir)
    ledger = os.path.join(project_dir, 'working', 'costs', 'ledger.csv')
    assert os.path.isfile(ledger)
    content = open(ledger).read()
    assert 'score-compare-ceiling' in content


def test_semantic_response_does_not_declare_winner():
    """The prompt explicitly forbids the LLM from declaring a winner. The
    parser still won't emit one even if a bad LLM tried."""
    # The contract is enforced by the prompt + the parser only reading the
    # 'axes' list. If the LLM tried to add a 'winner' field, it'd be
    # silently dropped. Confirm by sending a malicious response.
    text = json.dumps({
        'axes': _FAKE_CEILING_RESPONSE['axes'],
        'winner': 'B',
        'recommendation': 'use B',
    })
    from storyforge.scoring_comparison import _parse_ceiling_response
    parsed = _parse_ceiling_response(text)
    assert parsed is not None
    # No 'winner' key surfaces — we only extract 'axes'.
    # (The parser returns the list itself, not the wrapper dict.)
    assert isinstance(parsed, list)
    assert all('name' in axis for axis in parsed)
