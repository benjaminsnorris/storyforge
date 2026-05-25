"""Tests for scoring_story_power — 8-axis pitch-tier craft scorecard."""

import json
import os

import pytest


def _seed_summary(project_dir: str) -> None:
    yml = os.path.join(project_dir, 'storyforge.yaml')
    if not os.path.isfile(yml):
        with open(yml, 'w') as f:
            f.write('project:\n  title: Test\n  medium: novel\n  '
                    'coaching_level: full\n')
    ref = os.path.join(project_dir, 'reference')
    os.makedirs(ref, exist_ok=True)
    with open(os.path.join(ref, 'story-summary.md'), 'w') as f:
        f.write(
            '# Story summary\n\n'
            '## Logline\n\nA real logline.\n\n'
            '## Synopsis\n\nA real synopsis. With sentences. Many of them. '
            'And more. And more.\n\n'
            '## Act-shape\n\n'
            '### Act 1\nFirst.\n\n### Act 2\nSecond.\n\n### Act 3\nThird.\n\n'
            '## Theme\n\nThe theme is real.\n'
        )


def _full_payload(scores: list[int] | None = None) -> dict:
    """Build a well-shaped LLM response payload."""
    keys = [
        'specificity', 'emotional_resonance', 'character_identification',
        'stakes_dilemma', 'archetypal_resonance', 'thematic_depth',
        'surprise_subversion', 'moral_weight',
    ]
    scores = scores or [7, 7, 7, 9, 9, 9, 8, 9]
    rows = [
        {'axis': k, 'score': s,
         'positive_signals': f'sig+ for {k}',
         'negative_signals': f'sig- for {k}',
         'rationale': f'rationale for {k}'}
        for k, s in zip(keys, scores)
    ]
    return {
        'axes': {k: k.replace('_', ' ').title() for k in keys},
        'scores': rows,
        'diagnostic': {
            'cross_axis_root_cause': 'protagonist rendered as practitioner, not interior person',
            'high_leverage_move': 'plant a single interior sensory line',
            'example_sentence': 'he can still draw her face from memory.',
        },
    }


def _mock_llm(payload: dict):
    def fake(prompt, model, log_file, **kwargs):
        os.makedirs(os.path.dirname(log_file) or '.', exist_ok=True)
        response = {
            'content': [{'type': 'text', 'text': json.dumps(payload)}],
            'usage': {'input_tokens': 500, 'output_tokens': 400,
                      'cache_read_input_tokens': 0,
                      'cache_creation_input_tokens': 0},
        }
        with open(log_file, 'w') as f:
            json.dump(response, f)
        return response
    return fake


# ---------------------------------------------------------------------------
# Composite weighting
# ---------------------------------------------------------------------------

def test_composite_uses_correct_weights():
    """Stakes, archetypal, thematic, moral weighted 1.5x; others 1.0x."""
    from storyforge.scoring_story_power import composite_score, AXES
    # All-10 → composite 10. All-1 → composite 1.
    assert composite_score({a.key: 10 for a in AXES}) == 10.0
    assert composite_score({a.key: 1 for a in AXES}) == 1.0
    # Ashes worked example from the rubric: [8, 7, 7, 9, 9, 9, 8, 9]
    scores = {
        'specificity': 8, 'emotional_resonance': 7,
        'character_identification': 7, 'stakes_dilemma': 9,
        'archetypal_resonance': 9, 'thematic_depth': 9,
        'surprise_subversion': 8, 'moral_weight': 9,
    }
    # (8 + 7 + 7 + 9*1.5 + 9*1.5 + 9*1.5 + 8 + 9*1.5) / (1+1+1+1.5*4+1) = 84.5/10
    assert composite_score(scores) == 8.4


def test_composite_handles_missing_axes():
    """Missing axes fall out of the average gracefully."""
    from storyforge.scoring_story_power import composite_score
    assert composite_score({}) == 0.0
    assert composite_score({'stakes_dilemma': 10}) == 10.0


# ---------------------------------------------------------------------------
# Strict coaching — no LLM
# ---------------------------------------------------------------------------

def test_strict_writes_checklist_no_llm(tmp_path, monkeypatch):
    _seed_summary(str(tmp_path))
    monkeypatch.chdir(str(tmp_path))
    from storyforge import api, scoring_story_power
    def fail(*a, **k):
        raise AssertionError('LLM must not be called in strict')
    monkeypatch.setattr(api, 'invoke_to_file', fail)
    monkeypatch.setattr(scoring_story_power, 'invoke_to_file', fail)
    result = scoring_story_power.score_story_power(str(tmp_path), 'strict')
    assert result['mode'] == 'strict'
    assert os.path.isdir(result['output_dir'])
    checklist = os.path.join(result['output_dir'],
                              'self-scoring-checklist.md')
    assert os.path.isfile(checklist)
    text = open(checklist).read()
    # All 8 axes appear
    for axis_name in ('Specificity', 'Stakes & dilemma', 'Moral weight'):
        assert axis_name in text


# ---------------------------------------------------------------------------
# Full coaching — LLM → scorecard.csv + diagnostic.md
# ---------------------------------------------------------------------------

def test_full_writes_scorecard_and_diagnostic(tmp_path, monkeypatch):
    _seed_summary(str(tmp_path))
    monkeypatch.chdir(str(tmp_path))
    monkeypatch.setenv('ANTHROPIC_API_KEY', 'test-key')
    fake = _mock_llm(_full_payload([8, 7, 7, 9, 9, 9, 8, 9]))
    from storyforge import api, scoring_story_power
    monkeypatch.setattr(api, 'invoke_to_file', fake)
    monkeypatch.setattr(scoring_story_power, 'invoke_to_file', fake)
    result = scoring_story_power.score_story_power(str(tmp_path), 'full')
    assert result['composite'] == 8.4
    out_dir = result['output_dir']
    assert os.path.isfile(os.path.join(out_dir, 'scorecard.csv'))
    assert os.path.isfile(os.path.join(out_dir, 'diagnostic.md'))
    csv_text = open(os.path.join(out_dir, 'scorecard.csv')).read()
    # CSV has all 8 axis rows + header
    assert csv_text.count('\n') >= 9
    assert 'specificity' in csv_text
    assert 'moral_weight' in csv_text
    diag = open(os.path.join(out_dir, 'diagnostic.md')).read()
    assert 'practitioner' in diag
    assert 'sensory line' in diag


def test_full_without_api_key_errors(tmp_path, monkeypatch):
    _seed_summary(str(tmp_path))
    monkeypatch.chdir(str(tmp_path))
    monkeypatch.delenv('ANTHROPIC_API_KEY', raising=False)
    from storyforge.scoring_story_power import score_story_power
    result = score_story_power(str(tmp_path), 'full')
    assert result['composite'] == 0.0
    assert result['output_dir'] == ''


def test_full_logs_partial_when_response_unparseable(tmp_path, monkeypatch):
    _seed_summary(str(tmp_path))
    monkeypatch.chdir(str(tmp_path))
    monkeypatch.setenv('ANTHROPIC_API_KEY', 'test-key')
    def fake(prompt, model, log_file, **kwargs):
        os.makedirs(os.path.dirname(log_file) or '.', exist_ok=True)
        with open(log_file, 'w') as f:
            json.dump({
                'content': [{'type': 'text', 'text': 'not json at all'}],
                'usage': {'input_tokens': 100, 'output_tokens': 50,
                          'cache_read_input_tokens': 0,
                          'cache_creation_input_tokens': 0},
            }, f)
        return {}
    from storyforge import api, scoring_story_power
    monkeypatch.setattr(api, 'invoke_to_file', fake)
    monkeypatch.setattr(scoring_story_power, 'invoke_to_file', fake)
    result = scoring_story_power.score_story_power(str(tmp_path), 'full')
    assert 'unparseable' in result['mode']
    # Cost ledger has the unparseable tag
    ledger = open(os.path.join(str(tmp_path), 'working', 'costs',
                                'ledger.csv')).read()
    assert 'unparseable' in ledger


# ---------------------------------------------------------------------------
# Coach coaching — LLM → coaching-brief.md, no scorecard CSV
# ---------------------------------------------------------------------------

def test_coach_writes_brief_not_csv(tmp_path, monkeypatch):
    _seed_summary(str(tmp_path))
    monkeypatch.chdir(str(tmp_path))
    monkeypatch.setenv('ANTHROPIC_API_KEY', 'test-key')
    fake = _mock_llm(_full_payload())
    from storyforge import api, scoring_story_power
    monkeypatch.setattr(api, 'invoke_to_file', fake)
    monkeypatch.setattr(scoring_story_power, 'invoke_to_file', fake)
    result = scoring_story_power.score_story_power(str(tmp_path), 'coach')
    out_dir = result['output_dir']
    assert os.path.isfile(os.path.join(out_dir, 'coaching-brief.md'))
    # No scorecard CSV in coach mode
    assert not os.path.isfile(os.path.join(out_dir, 'scorecard.csv'))
    text = open(os.path.join(out_dir, 'coaching-brief.md')).read()
    assert '- Question:' in text


# ---------------------------------------------------------------------------
# Delta tracking
# ---------------------------------------------------------------------------

def test_delta_tracking_compares_against_previous_run(tmp_path, monkeypatch):
    _seed_summary(str(tmp_path))
    monkeypatch.chdir(str(tmp_path))
    monkeypatch.setenv('ANTHROPIC_API_KEY', 'test-key')
    # Two consecutive runs with different scores.
    fake1 = _mock_llm(_full_payload([7, 7, 7, 9, 9, 9, 8, 9]))
    from storyforge import api, scoring_story_power
    monkeypatch.setattr(api, 'invoke_to_file', fake1)
    monkeypatch.setattr(scoring_story_power, 'invoke_to_file', fake1)
    scoring_story_power.score_story_power(str(tmp_path), 'full')

    # Second run — improved specificity. Timestamps are microsecond
    # resolution + non-existence loop, so back-to-back runs naturally land
    # in distinct directories.
    fake2 = _mock_llm(_full_payload([8, 8, 7, 9, 9, 9, 8, 9]))
    monkeypatch.setattr(api, 'invoke_to_file', fake2)
    monkeypatch.setattr(scoring_story_power, 'invoke_to_file', fake2)
    result2 = scoring_story_power.score_story_power(str(tmp_path), 'full')
    assert result2['deltas']['specificity'] == 1
    assert result2['deltas']['emotional_resonance'] == 1
    assert result2['deltas']['character_identification'] == 0


# ---------------------------------------------------------------------------
# Empty-input guard
# ---------------------------------------------------------------------------

def test_refuses_without_logline_or_synopsis(tmp_path, monkeypatch, capsys):
    yml = os.path.join(str(tmp_path), 'storyforge.yaml')
    with open(yml, 'w') as f:
        f.write('project:\n  title: T\n  medium: novel\n  coaching_level: full\n')
    ref = os.path.join(str(tmp_path), 'reference')
    os.makedirs(ref, exist_ok=True)
    # story-summary.md with empty logline + synopsis
    with open(os.path.join(ref, 'story-summary.md'), 'w') as f:
        f.write('# Story summary\n\n## Logline\n\n## Synopsis\n\n')
    monkeypatch.chdir(str(tmp_path))
    from storyforge.scoring_story_power import score_story_power
    result = score_story_power(str(tmp_path), 'full')
    out = capsys.readouterr().out
    assert 'story-summary.md' in out
    assert result['output_dir'] == ''


# ---------------------------------------------------------------------------
# CLI dispatch
# ---------------------------------------------------------------------------

def test_cmd_score_story_power_flag(tmp_path, monkeypatch):
    """`storyforge score --story-power` routes to scoring_story_power."""
    _seed_summary(str(tmp_path))
    monkeypatch.chdir(str(tmp_path))
    monkeypatch.setenv('ANTHROPIC_API_KEY', 'test-key')
    # Other tests can leak STORYFORGE_COACHING into the env; force full
    # so this test exercises the LLM path it intends to.
    monkeypatch.delenv('STORYFORGE_COACHING', raising=False)
    fake = _mock_llm(_full_payload())
    from storyforge import api, scoring_story_power
    monkeypatch.setattr(api, 'invoke_to_file', fake)
    monkeypatch.setattr(scoring_story_power, 'invoke_to_file', fake)
    from storyforge.cmd_score import main as score_main
    score_main(['--story-power'])
    # Output dir was created
    base = os.path.join(str(tmp_path), 'working', 'scores', 'story-power')
    assert os.path.isdir(base)
    dirs = os.listdir(base)
    assert len(dirs) == 1
    assert os.path.isfile(os.path.join(base, dirs[0], 'scorecard.csv'))


def test_story_power_in_elaboration_score_flags():
    """The flag must be in _ELABORATION_SCORE_FLAGS so GN dispatcher
    routes it to cmd_score instead of cmd_score_gn."""
    from storyforge.__main__ import _ELABORATION_SCORE_FLAGS
    assert '--story-power' in _ELABORATION_SCORE_FLAGS


# ---------------------------------------------------------------------------
# Critical-fix regression tests
# ---------------------------------------------------------------------------

def test_missing_rubric_fails_full_mode_without_llm_call(tmp_path, monkeypatch):
    """If the rubric file is gone, full/coach must refuse to score —
    otherwise the LLM gets called with no rubric grounding."""
    _seed_summary(str(tmp_path))
    monkeypatch.chdir(str(tmp_path))
    monkeypatch.setenv('ANTHROPIC_API_KEY', 'test-key')
    from storyforge import api, scoring_story_power

    def boom(*a, **kw):
        raise AssertionError('LLM must not be called when rubric is missing')
    monkeypatch.setattr(api, 'invoke_to_file', boom)
    monkeypatch.setattr(scoring_story_power, 'invoke_to_file', boom)
    monkeypatch.setattr(scoring_story_power, '_load_rubric', lambda: '')

    result = scoring_story_power.score_story_power(str(tmp_path), 'full')
    assert result['output_dir'] == ''
    assert result['composite'] == 0.0


def test_missing_rubric_does_not_block_strict(tmp_path, monkeypatch):
    """strict coaching runs entirely off the per-axis names baked into AXES,
    so an absent rubric must not stop it (the author can self-score)."""
    _seed_summary(str(tmp_path))
    monkeypatch.chdir(str(tmp_path))
    from storyforge import scoring_story_power
    monkeypatch.setattr(scoring_story_power, '_load_rubric', lambda: '')
    result = scoring_story_power.score_story_power(str(tmp_path), 'strict')
    assert result['output_dir']
    assert os.path.isfile(os.path.join(result['output_dir'],
                                        'self-scoring-checklist.md'))


def test_back_to_back_runs_get_distinct_output_dirs(tmp_path, monkeypatch):
    """Two runs in the same second must land in distinct directories —
    otherwise the second clobbers the first."""
    _seed_summary(str(tmp_path))
    monkeypatch.chdir(str(tmp_path))
    monkeypatch.setenv('ANTHROPIC_API_KEY', 'test-key')
    fake = _mock_llm(_full_payload())
    from storyforge import api, scoring_story_power
    monkeypatch.setattr(api, 'invoke_to_file', fake)
    monkeypatch.setattr(scoring_story_power, 'invoke_to_file', fake)

    r1 = scoring_story_power.score_story_power(str(tmp_path), 'full')
    r2 = scoring_story_power.score_story_power(str(tmp_path), 'full')
    assert r1['output_dir'] != r2['output_dir']
    assert os.path.isfile(os.path.join(r1['output_dir'], 'scorecard.csv'))
    assert os.path.isfile(os.path.join(r2['output_dir'], 'scorecard.csv'))
