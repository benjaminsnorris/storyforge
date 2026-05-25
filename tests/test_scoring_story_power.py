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


def _act_shape_payload(per_act_overrides: dict[str, dict[str, int]] | None = None,
                        structural_overrides: dict[str, int] | None = None) -> dict:
    """Build a well-shaped act-shape LLM response payload.

    per_act_overrides: {act_key: {axis_key: score}} — partial override
    on top of the default per-act baseline (Act 2 dips on emotional
    resonance + stakes vs Acts 1 and 3).
    """
    pitch_keys = [a for a in (
        'specificity', 'emotional_resonance', 'character_identification',
        'stakes_dilemma', 'archetypal_resonance', 'thematic_depth',
        'surprise_subversion', 'moral_weight',
    )]
    baseline = {
        'act1': {k: 9 for k in pitch_keys},
        'act2': dict(zip(pitch_keys, [8, 6, 7, 7, 9, 9, 8, 9])),
        'act3': {k: 9 for k in pitch_keys},
    }
    if per_act_overrides:
        for act, scores in per_act_overrides.items():
            baseline.setdefault(act, {}).update(scores)
    per_act = [
        {'act': act, 'scores': [
            {'axis': k, 'score': v,
             'rationale': f'{k} in {act}'}
            for k, v in baseline[act].items()
        ]}
        for act in ('act1', 'act2', 'act3')
    ]
    structural_baseline = {
        'causal_integrity': 8,
        'turning_point_clarity': 7,
        'arc_gradient': 8,
        'promise_payoff': 9,
    }
    if structural_overrides:
        structural_baseline.update(structural_overrides)
    structural = [
        {'axis': k, 'score': v,
         'positive_signals': f'sig+ for {k}',
         'negative_signals': f'sig- for {k}',
         'rationale': f'rationale for {k}'}
        for k, v in structural_baseline.items()
    ]
    return {
        'pitch_axes': {k: k for k in pitch_keys},
        'structural_axes': {k: k for k in structural_baseline},
        'per_act': per_act,
        'structural': structural,
        'structural_diagnostic': {
            'cross_act_pattern': 'Act 2 dips on emotional resonance + stakes; '
                                  'co-locates with turning_point_clarity = 7',
            'high_leverage_move': 'convert the midpoint from a stakes-raise to a reversal',
            'example_beat': 'the failed portrait teaches what record cannot hold',
        },
    }


def _dual_mock_llm(pitch_payload: dict, act_shape_payload: dict):
    """Mock that returns the pitch payload first, then the act-shape
    payload on the second call (when the act-shape extension fires)."""
    state = {'call': 0}

    def fake(prompt, model, log_file, **kwargs):
        os.makedirs(os.path.dirname(log_file) or '.', exist_ok=True)
        # Route by which log file the caller passed: the act-shape call
        # appends '-act-shape' to the basename. This is more robust than
        # counting calls, since back-to-back tests can leak state.
        payload = (act_shape_payload if '-act-shape' in log_file
                   else pitch_payload)
        state['call'] += 1
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


def test_axes_module_load_invariants():
    """AXES enforces unique keys, only-1.0-or-1.5 weights, and exactly
    four 1.5x axes — drift in any of these silently shifts the composite
    math, so they assert at import time."""
    from storyforge.scoring_story_power import AXES
    keys = [a.key for a in AXES]
    assert len(keys) == len(set(keys))
    assert all(a.weight in (1.0, 1.5) for a in AXES)
    assert sum(1 for a in AXES if a.weight == 1.5) == 4


def test_score_story_power_returns_typed_status(tmp_path, monkeypatch):
    """Result has both coaching (the request) and status (the outcome)
    as typed fields; consumers should branch on status rather than
    substring-match the legacy `mode` display string."""
    _seed_summary(str(tmp_path))
    monkeypatch.chdir(str(tmp_path))
    monkeypatch.setenv('ANTHROPIC_API_KEY', 'test-key')
    # Seeded fixture has act-shape populated, so both calls fire. Use
    # the dual mock so this test exercises the fully-ok path.
    fake = _dual_mock_llm(_full_payload(), _act_shape_payload())
    from storyforge import api, scoring_story_power
    monkeypatch.setattr(api, 'invoke_to_file', fake)
    monkeypatch.setattr(scoring_story_power, 'invoke_to_file', fake)
    result = scoring_story_power.score_story_power(str(tmp_path), 'full')
    assert result['coaching'] == 'full'
    assert result['status'] == 'ok'
    assert result['mode'] == 'full'  # display string preserved


def test_status_when_api_key_missing(tmp_path, monkeypatch):
    _seed_summary(str(tmp_path))
    monkeypatch.chdir(str(tmp_path))
    monkeypatch.delenv('ANTHROPIC_API_KEY', raising=False)
    from storyforge.scoring_story_power import score_story_power
    result = score_story_power(str(tmp_path), 'full')
    assert result['status'] == 'no_api_key'
    assert result['coaching'] == 'full'


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
    # All 8 pitch axes get a section, plus the self-scoring scaffolding.
    from storyforge.scoring_story_power import AXES, STRUCTURAL_AXES
    for axis in AXES:
        assert f'## {axis.name}' in text
        assert f'weight {axis.weight}' in text
    # The seeded fixture has all three act-shape paragraphs populated,
    # so the strict checklist also extends with the per-act blanks and
    # the four structural axes.
    for axis in STRUCTURAL_AXES:
        assert f'## {axis.name}' in text
    # Pitch + structural blanks: one per axis. Per-act blanks use a
    # different scaffolding line ("- {axis name}: __").
    assert text.count('Self-score (1-10):') == len(AXES) + len(STRUCTURAL_AXES)
    assert text.count('Positive signals you found:') == len(AXES)
    assert text.count('Negative signals you found:') == len(AXES)
    # Per-act blanks: three acts × eight axes = 24.
    assert text.count(': __') >= 24
    # No LLM commentary should leak in.
    assert 'Proposed' not in text
    assert 'rationale' not in text.lower()


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


def test_refuses_when_only_synopsis_missing(tmp_path, monkeypatch):
    """logline present but synopsis missing must refuse — scoring requires both."""
    yml = os.path.join(str(tmp_path), 'storyforge.yaml')
    with open(yml, 'w') as f:
        f.write('project:\n  title: T\n  medium: novel\n  coaching_level: full\n')
    ref = os.path.join(str(tmp_path), 'reference')
    os.makedirs(ref, exist_ok=True)
    with open(os.path.join(ref, 'story-summary.md'), 'w') as f:
        f.write('# Story summary\n\n## Logline\n\nA logline.\n\n## Synopsis\n\n')
    monkeypatch.chdir(str(tmp_path))
    from storyforge.scoring_story_power import score_story_power
    result = score_story_power(str(tmp_path), 'full')
    assert result['output_dir'] == ''


def test_refuses_when_only_logline_missing(tmp_path, monkeypatch):
    """synopsis present but logline missing must refuse — scoring requires both."""
    yml = os.path.join(str(tmp_path), 'storyforge.yaml')
    with open(yml, 'w') as f:
        f.write('project:\n  title: T\n  medium: novel\n  coaching_level: full\n')
    ref = os.path.join(str(tmp_path), 'reference')
    os.makedirs(ref, exist_ok=True)
    with open(os.path.join(ref, 'story-summary.md'), 'w') as f:
        f.write('# Story summary\n\n## Logline\n\n## Synopsis\n\nA synopsis.\n\n')
    monkeypatch.chdir(str(tmp_path))
    from storyforge.scoring_story_power import score_story_power
    result = score_story_power(str(tmp_path), 'full')
    assert result['output_dir'] == ''


# ---------------------------------------------------------------------------
# Score extraction robustness
# ---------------------------------------------------------------------------

def test_non_numeric_score_does_not_crash(tmp_path, monkeypatch):
    """If the LLM emits 'score': null or a string, the run must continue —
    we drop that axis and warn the author, not raise TypeError."""
    _seed_summary(str(tmp_path))
    monkeypatch.chdir(str(tmp_path))
    monkeypatch.setenv('ANTHROPIC_API_KEY', 'test-key')
    payload = _full_payload()
    # Corrupt one row's score.
    payload['scores'][2]['score'] = None
    fake = _mock_llm(payload)
    from storyforge import api, scoring_story_power
    monkeypatch.setattr(api, 'invoke_to_file', fake)
    monkeypatch.setattr(scoring_story_power, 'invoke_to_file', fake)
    result = scoring_story_power.score_story_power(str(tmp_path), 'full')
    # 7 of 8 axes scored; result should still come back as partial.
    assert 'character_identification' not in result['scores']
    assert len(result['scores']) == 7
    assert 'partial' in result['mode']


def test_partial_scores_flag_partial_in_mode(tmp_path, monkeypatch):
    """When the LLM omits an axis row, result.mode is tagged '(partial)'."""
    _seed_summary(str(tmp_path))
    monkeypatch.chdir(str(tmp_path))
    monkeypatch.setenv('ANTHROPIC_API_KEY', 'test-key')
    payload = _full_payload()
    payload['scores'] = payload['scores'][:7]  # drop one axis
    fake = _mock_llm(payload)
    from storyforge import api, scoring_story_power
    monkeypatch.setattr(api, 'invoke_to_file', fake)
    monkeypatch.setattr(scoring_story_power, 'invoke_to_file', fake)
    result = scoring_story_power.score_story_power(str(tmp_path), 'full')
    assert 'partial' in result['mode']
    assert len(result['scores']) == 7


def test_out_of_range_score_is_dropped(tmp_path, monkeypatch):
    """A score of 47 is almost always a parse artifact (e.g., 4 → 47 from
    concatenation). Drop it rather than letting it skew the composite."""
    _seed_summary(str(tmp_path))
    monkeypatch.chdir(str(tmp_path))
    monkeypatch.setenv('ANTHROPIC_API_KEY', 'test-key')
    payload = _full_payload()
    payload['scores'][0]['score'] = 47
    fake = _mock_llm(payload)
    from storyforge import api, scoring_story_power
    monkeypatch.setattr(api, 'invoke_to_file', fake)
    monkeypatch.setattr(scoring_story_power, 'invoke_to_file', fake)
    result = scoring_story_power.score_story_power(str(tmp_path), 'full')
    assert 'specificity' not in result['scores']
    assert 'partial' in result['mode']


# ---------------------------------------------------------------------------
# Zero-tokens cost ledger guard
# ---------------------------------------------------------------------------

def test_delta_warns_on_axis_schema_drift(tmp_path, monkeypatch, capsys):
    """A previous scorecard with a different axis set must surface a
    warning — silently comparing partial-overlap scores would let
    schema migrations look like score regressions."""
    _seed_summary(str(tmp_path))
    monkeypatch.chdir(str(tmp_path))
    base = os.path.join(str(tmp_path), 'working', 'scores', 'story-power',
                         '20260101T000000_000000Z')
    os.makedirs(base)
    # Previous run had an axis that no longer exists ("legacy_axis"),
    # plus the current 8.
    with open(os.path.join(base, 'scorecard.csv'), 'w') as f:
        f.write('axis|score\nlegacy_axis|9\nspecificity|7\n'
                'stakes_dilemma|8\n')
    monkeypatch.setenv('ANTHROPIC_API_KEY', 'test-key')
    fake = _mock_llm(_full_payload())
    from storyforge import api, scoring_story_power
    monkeypatch.setattr(api, 'invoke_to_file', fake)
    monkeypatch.setattr(scoring_story_power, 'invoke_to_file', fake)
    scoring_story_power.score_story_power(str(tmp_path), 'full')
    out = capsys.readouterr().out
    assert 'drifted' in out
    assert 'legacy_axis' in out


def test_summary_column_warns_on_malformed_csv_row(tmp_path, capsys):
    """A spine.csv row with the wrong cell count must surface a warning
    so a schema drift doesn't silently drop rows from the prompt."""
    csv_path = os.path.join(str(tmp_path), 'broken.csv')
    with open(csv_path, 'w') as f:
        f.write('id|seq|summary|function\n'
                'e1|1|First event|setup\n'
                'this row is wrong\n'
                'e2|3|Third event|escalation\n')
    from storyforge.scoring_story_power import _summary_column_from_csv
    out = _summary_column_from_csv(csv_path)
    err = capsys.readouterr().out
    # First and third row survive; bad row warned about.
    assert 'First event' in out
    assert 'Third event' in out
    assert 'malformed' in err


def test_zero_tokens_skips_cost_ledger_row(tmp_path, monkeypatch):
    """An LLM response with 0 input + 0 output tokens is almost always a
    mocked or empty round-trip — a $0 ledger row hides the real signal."""
    _seed_summary(str(tmp_path))
    monkeypatch.chdir(str(tmp_path))
    monkeypatch.setenv('ANTHROPIC_API_KEY', 'test-key')

    def fake_zero(prompt, model, log_file, **kwargs):
        os.makedirs(os.path.dirname(log_file) or '.', exist_ok=True)
        response = {
            'content': [{'type': 'text',
                          'text': json.dumps(_full_payload())}],
            'usage': {'input_tokens': 0, 'output_tokens': 0,
                      'cache_read_input_tokens': 0,
                      'cache_creation_input_tokens': 0},
        }
        with open(log_file, 'w') as f:
            json.dump(response, f)
        return response

    from storyforge import api, scoring_story_power
    monkeypatch.setattr(api, 'invoke_to_file', fake_zero)
    monkeypatch.setattr(scoring_story_power, 'invoke_to_file', fake_zero)
    scoring_story_power.score_story_power(str(tmp_path), 'full')
    ledger_path = os.path.join(str(tmp_path), 'working', 'costs', 'ledger.csv')
    if os.path.isfile(ledger_path):
        ledger = open(ledger_path).read()
        # No story-power ledger row for the zero-token call.
        assert 'score-story-power' not in ledger


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


# ---------------------------------------------------------------------------
# _parse_response fallback branches
# ---------------------------------------------------------------------------

def test_parse_response_handles_fenced_json_block():
    """Tier-2 fallback: response wrapped in ```json ... ``` fences must
    still parse. Claude wraps JSON in fences without being asked to."""
    from storyforge.scoring_story_power import _parse_response
    payload = json.dumps(_full_payload())
    text = f'Sure! Here is the scorecard:\n\n```json\n{payload}\n```\n'
    parsed = _parse_response(text)
    assert parsed is not None
    assert isinstance(parsed['scores'], list)
    assert len(parsed['scores']) == 8


def test_parse_response_handles_bare_fenced_block():
    """A ``` block with no language tag must also parse."""
    from storyforge.scoring_story_power import _parse_response
    payload = json.dumps(_full_payload())
    text = f'```\n{payload}\n```'
    parsed = _parse_response(text)
    assert parsed is not None
    assert len(parsed['scores']) == 8


def test_parse_response_handles_greedy_extraction():
    """Tier-3 fallback: when the model embeds JSON in prose with no
    fence (a real failure mode), greedy `{...}` extraction finds it."""
    from storyforge.scoring_story_power import _parse_response
    payload = json.dumps(_full_payload())
    text = f'Here is my analysis. {payload} Hope this helps!'
    parsed = _parse_response(text)
    assert parsed is not None
    assert len(parsed['scores']) == 8


def test_parse_response_rejects_wrong_shape_logs_warning(capsys):
    """Valid JSON with the wrong shape must return None AND log a
    WARNING — silent shape failure was the original bug."""
    from storyforge.scoring_story_power import _parse_response
    # Valid JSON, but `scores` is a dict (object) rather than a list.
    bad = json.dumps({'scores': {'specificity': 8}})
    parsed = _parse_response(bad)
    assert parsed is None
    out = capsys.readouterr().out
    assert 'shape' in out.lower() or 'wrong shape' in out.lower()


def test_parse_response_rejects_non_json():
    """Pure prose returns None with no warning (separate from shape failure)."""
    from storyforge.scoring_story_power import _parse_response
    assert _parse_response('I cannot score this story.') is None


def test_parse_response_rejects_scores_as_string(capsys):
    """A `scores` value that's a string (instead of list/object) must
    also surface as a shape failure rather than silently passing."""
    from storyforge.scoring_story_power import _parse_response
    bad = json.dumps({'scores': 'not a list'})
    parsed = _parse_response(bad)
    assert parsed is None
    out = capsys.readouterr().out
    assert 'shape' in out.lower() or 'wrong shape' in out.lower()


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


# ---------------------------------------------------------------------------
# Act-shape mode (Layer 1 per-act matrix + Layer 2 structural axes)
# ---------------------------------------------------------------------------

def test_parse_act_shape_splits_three_acts():
    """Parser must split `### Act 1` / `### Act 2` / `### Act 3` into
    three labeled paragraphs."""
    from storyforge.scoring_story_power import parse_act_shape
    body = (
        '### Act 1\n\nFirst paragraph.\n\n'
        '### Act 2\n\nSecond paragraph.\n\n'
        '### Act 3\n\nThird paragraph.\n'
    )
    result = parse_act_shape(body)
    assert result is not None
    assert 'First' in result.act1
    assert 'Second' in result.act2
    assert 'Third' in result.act3


def test_parse_act_shape_returns_none_when_act_missing():
    """If Act 3 is missing or empty, the parser returns None so the
    caller falls back to pitch-only mode."""
    from storyforge.scoring_story_power import parse_act_shape
    body = '### Act 1\n\nFirst.\n\n### Act 2\n\nSecond.\n\n'
    assert parse_act_shape(body) is None
    # Empty body short-circuits.
    assert parse_act_shape('') is None
    # Whitespace-only Act 2 also fails the population check.
    assert parse_act_shape('### Act 1\n\nx\n\n### Act 2\n\n   \n\n### Act 3\n\nz\n') is None


def test_parse_act_shape_accepts_optional_titles():
    """`### Act 2 — the descent` should parse as Act 2."""
    from storyforge.scoring_story_power import parse_act_shape
    body = (
        '### Act 1 — opening\n\nFirst.\n\n'
        '### Act 2: midpoint\n\nSecond.\n\n'
        '### Act 3 — resolution\n\nThird.\n'
    )
    result = parse_act_shape(body)
    assert result is not None
    assert 'First' in result.act1
    assert 'midpoint' not in result.act2  # heading suffix not included in body
    assert 'Third' in result.act3


def test_structural_axes_invariants():
    """STRUCTURAL_AXES enforces unique keys, all 1.5x weights, four axes,
    and disjoint key set from pitch AXES."""
    from storyforge.scoring_story_power import STRUCTURAL_AXES, AXIS_KEYS
    keys = [a.key for a in STRUCTURAL_AXES]
    assert len(keys) == 4
    assert len(set(keys)) == 4
    assert all(a.weight == 1.5 for a in STRUCTURAL_AXES)
    assert not (set(keys) & set(AXIS_KEYS))


def test_act_shape_mode_writes_matrix_and_structural_csvs(tmp_path, monkeypatch):
    """When act-shape paragraphs are populated and the LLM returns a
    well-shaped payload, the run writes per-act-matrix.csv and
    structural-axes.csv alongside scorecard.csv."""
    _seed_summary(str(tmp_path))
    monkeypatch.chdir(str(tmp_path))
    monkeypatch.setenv('ANTHROPIC_API_KEY', 'test-key')
    fake = _dual_mock_llm(_full_payload(), _act_shape_payload())
    from storyforge import api, scoring_story_power
    monkeypatch.setattr(api, 'invoke_to_file', fake)
    monkeypatch.setattr(scoring_story_power, 'invoke_to_file', fake)
    result = scoring_story_power.score_story_power(str(tmp_path), 'full')
    out_dir = result['output_dir']
    ext = result['act_shape']
    assert ext is not None
    assert os.path.isfile(os.path.join(out_dir, 'scorecard.csv'))
    assert os.path.isfile(os.path.join(out_dir, 'per-act-matrix.csv'))
    assert os.path.isfile(os.path.join(out_dir, 'structural-axes.csv'))
    # Per-act matrix has Act 2 dip on emotional_resonance.
    matrix = open(os.path.join(out_dir, 'per-act-matrix.csv')).read()
    assert 'emotional_resonance' in matrix
    assert 'act1' in matrix and 'act2' in matrix and 'act3' in matrix
    # Structural CSV carries all four axes.
    struct = open(os.path.join(out_dir, 'structural-axes.csv')).read()
    for axis in ('causal_integrity', 'turning_point_clarity',
                 'arc_gradient', 'promise_payoff'):
        assert axis in struct
    # Diagnostic appended with cross-act section.
    diag = open(os.path.join(out_dir, 'diagnostic.md')).read()
    assert 'Per-act matrix' in diag
    assert 'Cross-act' in diag
    # Returned extension carries per-act + structural scores.
    assert ext['per_act_scores']['act2']['emotional_resonance'] == 6
    assert ext['structural_axis_scores']['causal_integrity'] == 8


def test_pitch_only_when_act_shape_missing(tmp_path, monkeypatch):
    """A project with only logline+synopsis (no act-shape) runs pitch-only
    without the act-shape extension files."""
    yml = os.path.join(str(tmp_path), 'storyforge.yaml')
    with open(yml, 'w') as f:
        f.write('project:\n  title: T\n  medium: novel\n  coaching_level: full\n')
    ref = os.path.join(str(tmp_path), 'reference')
    os.makedirs(ref, exist_ok=True)
    with open(os.path.join(ref, 'story-summary.md'), 'w') as f:
        f.write('# Story summary\n\n## Logline\n\nA logline.\n\n'
                '## Synopsis\n\nA synopsis.\n\n## Act-shape\n\n## Theme\n\n')
    monkeypatch.chdir(str(tmp_path))
    monkeypatch.setenv('ANTHROPIC_API_KEY', 'test-key')
    pitch_fake = _mock_llm(_full_payload())
    from storyforge import api, scoring_story_power
    monkeypatch.setattr(api, 'invoke_to_file', pitch_fake)
    monkeypatch.setattr(scoring_story_power, 'invoke_to_file', pitch_fake)
    result = scoring_story_power.score_story_power(str(tmp_path), 'full')
    out_dir = result['output_dir']
    assert result['act_shape'] is None
    assert os.path.isfile(os.path.join(out_dir, 'scorecard.csv'))
    assert not os.path.isfile(os.path.join(out_dir, 'per-act-matrix.csv'))
    assert not os.path.isfile(os.path.join(out_dir, 'structural-axes.csv'))


def test_act_shape_llm_failure_does_not_kill_pitch_result(tmp_path, monkeypatch):
    """If the act-shape LLM call fails (unparseable, error), the pitch
    scorecard must still survive — act-shape is additive, not required.
    The extension is present with a failure status so consumers can
    distinguish 'tried and failed' from 'never tried'."""
    _seed_summary(str(tmp_path))
    monkeypatch.chdir(str(tmp_path))
    monkeypatch.setenv('ANTHROPIC_API_KEY', 'test-key')
    # Mock returns the pitch payload on both calls — the act-shape parser
    # will reject it (wrong shape).
    fake = _mock_llm(_full_payload())
    from storyforge import api, scoring_story_power
    monkeypatch.setattr(api, 'invoke_to_file', fake)
    monkeypatch.setattr(scoring_story_power, 'invoke_to_file', fake)
    result = scoring_story_power.score_story_power(str(tmp_path), 'full')
    out_dir = result['output_dir']
    assert os.path.isfile(os.path.join(out_dir, 'scorecard.csv'))
    assert result['act_shape'] is not None
    assert result['act_shape']['status'] == 'unparseable'
    assert not os.path.isfile(os.path.join(out_dir, 'per-act-matrix.csv'))
    # Pitch result still healthy; overall status degraded to partial.
    assert result['composite'] > 0
    assert result['status'] == 'partial'


def test_act_shape_partial_per_act_tags_partial(tmp_path, monkeypatch):
    """Missing axes (but not a whole act) surface as status='partial'
    and the matrix writes with some empty cells. A whole-act drop is
    handled separately by test_empty_per_act_column_refuses_to_write_matrix."""
    _seed_summary(str(tmp_path))
    monkeypatch.chdir(str(tmp_path))
    monkeypatch.setenv('ANTHROPIC_API_KEY', 'test-key')
    act_payload = _act_shape_payload()
    # Keep one Act 2 score; drop the rest so Act 2 is partial but
    # not empty (the floor only triggers on entirely-empty acts).
    for row in act_payload['per_act']:
        if row['act'] == 'act2':
            row['scores'] = row['scores'][:1]
    fake = _dual_mock_llm(_full_payload(), act_payload)
    from storyforge import api, scoring_story_power
    monkeypatch.setattr(api, 'invoke_to_file', fake)
    monkeypatch.setattr(scoring_story_power, 'invoke_to_file', fake)
    result = scoring_story_power.score_story_power(str(tmp_path), 'full')
    assert result['act_shape'] is not None
    assert result['status'] == 'partial'
    # Matrix written; Act 2 column has one score + seven blanks.
    matrix = open(os.path.join(result['output_dir'],
                                'per-act-matrix.csv')).read()
    lines = matrix.splitlines()
    act2_filled = sum(
        1 for line in lines[1:]
        if line.split('|')[3].strip()
    )
    assert act2_filled == 1


def test_act_shape_coach_mode_appends_to_brief(tmp_path, monkeypatch):
    """coach mode extends coaching-brief.md with the per-act matrix +
    structural sections, not a separate file."""
    _seed_summary(str(tmp_path))
    monkeypatch.chdir(str(tmp_path))
    monkeypatch.setenv('ANTHROPIC_API_KEY', 'test-key')
    fake = _dual_mock_llm(_full_payload(), _act_shape_payload())
    from storyforge import api, scoring_story_power
    monkeypatch.setattr(api, 'invoke_to_file', fake)
    monkeypatch.setattr(scoring_story_power, 'invoke_to_file', fake)
    result = scoring_story_power.score_story_power(str(tmp_path), 'coach')
    out_dir = result['output_dir']
    brief = open(os.path.join(out_dir, 'coaching-brief.md')).read()
    assert 'Per-act matrix' in brief
    assert 'Cross-act structural' in brief
    # No separate per-act CSV in coach mode.
    assert not os.path.isfile(os.path.join(out_dir, 'per-act-matrix.csv'))


def test_act_shape_drop_flag(tmp_path):
    """_flag_act_drops surfaces axes where one act lags ≥ 2 behind the
    other two — the precondition for cross-act diagnostic patterns."""
    from storyforge.scoring_story_power import _flag_act_drops
    per_act = {
        'act1': {'specificity': 9, 'emotional_resonance': 9},
        'act2': {'specificity': 9, 'emotional_resonance': 6},  # 3-point dip
        'act3': {'specificity': 9, 'emotional_resonance': 9},
    }
    drops, skipped = _flag_act_drops(per_act)
    assert ('emotional_resonance', 'act2', 3) in drops
    # Specificity is flat — no drop reported.
    assert not any(d[0] == 'specificity' for d in drops)
    # Other axes have no data — they're skipped, not silently absent.
    assert 'stakes_dilemma' in skipped


def test_flag_act_drops_returns_skipped_axes():
    """An axis with a missing act surfaces in `skipped` so the
    diagnostic can flag incomplete cross-act analysis."""
    from storyforge.scoring_story_power import _flag_act_drops
    per_act = {
        'act1': {'specificity': 9, 'emotional_resonance': 9},
        'act2': {'specificity': 9},  # emotional_resonance missing
        'act3': {'specificity': 9, 'emotional_resonance': 9},
    }
    drops, skipped = _flag_act_drops(per_act)
    assert drops == []
    assert 'emotional_resonance' in skipped


def test_act_shape_extension_extract_drops_non_numeric():
    """_extract_per_act_scores / _extract_structural_scores must drop
    null/string/out-of-range scores rather than raising."""
    from storyforge.scoring_story_power import (
        _extract_per_act_scores, _extract_structural_scores,
    )
    payload = {
        'per_act': [
            {'act': 'act1', 'scores': [
                {'axis': 'specificity', 'score': 8},
                {'axis': 'emotional_resonance', 'score': None},  # dropped
                {'axis': 'stakes_dilemma', 'score': 'high'},     # dropped
                {'axis': 'moral_weight', 'score': 47},           # out-of-range
            ]},
        ],
        'structural': [
            {'axis': 'causal_integrity', 'score': 8},
            {'axis': 'turning_point_clarity', 'score': None},
            {'axis': 'unknown_axis', 'score': 9},                # dropped
        ],
    }
    per_act = _extract_per_act_scores(payload)
    assert per_act['act1'] == {'specificity': 8}
    structural = _extract_structural_scores(payload)
    assert structural == {'causal_integrity': 8}


def test_act_shape_unparseable_response_skips_extension(tmp_path, monkeypatch):
    """If the act-shape response can't be parsed, no CSVs are written
    but the result still carries the extension with status='unparseable'
    so consumers can tell 'tried and failed' from 'never tried'."""
    _seed_summary(str(tmp_path))
    monkeypatch.chdir(str(tmp_path))
    monkeypatch.setenv('ANTHROPIC_API_KEY', 'test-key')

    def fake(prompt, model, log_file, **kwargs):
        os.makedirs(os.path.dirname(log_file) or '.', exist_ok=True)
        if '-act-shape' in log_file:
            text = 'I cannot score these acts.'
        else:
            text = json.dumps(_full_payload())
        response = {
            'content': [{'type': 'text', 'text': text}],
            'usage': {'input_tokens': 100, 'output_tokens': 50,
                      'cache_read_input_tokens': 0,
                      'cache_creation_input_tokens': 0},
        }
        with open(log_file, 'w') as f:
            json.dump(response, f)
        return response
    from storyforge import api, scoring_story_power
    monkeypatch.setattr(api, 'invoke_to_file', fake)
    monkeypatch.setattr(scoring_story_power, 'invoke_to_file', fake)
    result = scoring_story_power.score_story_power(str(tmp_path), 'full')
    assert result['act_shape'] is not None
    assert result['act_shape']['status'] == 'unparseable'
    out_dir = result['output_dir']
    assert os.path.isfile(os.path.join(out_dir, 'scorecard.csv'))
    assert not os.path.isfile(os.path.join(out_dir, 'per-act-matrix.csv'))


def test_partial_act_shape_logs_info_with_missing_acts(tmp_path, monkeypatch, capsys):
    """An act-shape with only Act 1 populated must surface an INFO log
    naming Act 2 + Act 3 — silent fallback to pitch-only hides the
    one-paragraph-away case from the author."""
    yml = os.path.join(str(tmp_path), 'storyforge.yaml')
    with open(yml, 'w') as f:
        f.write('project:\n  title: T\n  medium: novel\n  coaching_level: full\n')
    ref = os.path.join(str(tmp_path), 'reference')
    os.makedirs(ref, exist_ok=True)
    with open(os.path.join(ref, 'story-summary.md'), 'w') as f:
        f.write('# Story summary\n\n## Logline\n\nL.\n\n## Synopsis\n\nS.\n\n'
                '## Act-shape\n\n### Act 1\n\nOnly Act 1 populated.\n\n'
                '## Theme\n\nT.\n')
    monkeypatch.chdir(str(tmp_path))
    monkeypatch.setenv('ANTHROPIC_API_KEY', 'test-key')
    fake = _mock_llm(_full_payload())
    from storyforge import api, scoring_story_power
    monkeypatch.setattr(api, 'invoke_to_file', fake)
    monkeypatch.setattr(scoring_story_power, 'invoke_to_file', fake)
    scoring_story_power.score_story_power(str(tmp_path), 'full')
    out = capsys.readouterr().out
    assert 'partially populated' in out
    assert 'Act 2' in out and 'Act 3' in out


def test_act_shape_llm_failure_surfaces_in_extension_status(tmp_path, monkeypatch):
    """When the act-shape LLM call raises, the result must carry the
    extension with status='llm_error' (not None) so callers can tell
    'tried and failed' from 'never tried'."""
    _seed_summary(str(tmp_path))
    monkeypatch.chdir(str(tmp_path))
    monkeypatch.setenv('ANTHROPIC_API_KEY', 'test-key')

    def fake(prompt, model, log_file, **kwargs):
        os.makedirs(os.path.dirname(log_file) or '.', exist_ok=True)
        if '-act-shape' in log_file:
            raise RuntimeError('simulated API outage')
        # Pitch call succeeds.
        response = {
            'content': [{'type': 'text',
                          'text': json.dumps(_full_payload())}],
            'usage': {'input_tokens': 500, 'output_tokens': 400,
                      'cache_read_input_tokens': 0,
                      'cache_creation_input_tokens': 0},
        }
        with open(log_file, 'w') as f:
            json.dump(response, f)
        return response
    from storyforge import api, scoring_story_power
    monkeypatch.setattr(api, 'invoke_to_file', fake)
    monkeypatch.setattr(scoring_story_power, 'invoke_to_file', fake)
    result = scoring_story_power.score_story_power(str(tmp_path), 'full')
    assert result['act_shape'] is not None
    assert result['act_shape']['status'] == 'llm_error'
    assert result['status'] == 'partial'  # overall degraded
    # Pitch result still healthy.
    assert os.path.isfile(os.path.join(result['output_dir'], 'scorecard.csv'))
    # No matrix/structural CSVs written.
    assert not os.path.isfile(os.path.join(result['output_dir'],
                                            'per-act-matrix.csv'))


def test_act_shape_unparseable_surfaces_status(tmp_path, monkeypatch):
    """Unparseable act-shape response sets act_shape['status']='unparseable'."""
    _seed_summary(str(tmp_path))
    monkeypatch.chdir(str(tmp_path))
    monkeypatch.setenv('ANTHROPIC_API_KEY', 'test-key')

    def fake(prompt, model, log_file, **kwargs):
        os.makedirs(os.path.dirname(log_file) or '.', exist_ok=True)
        text = ('not json' if '-act-shape' in log_file
                else json.dumps(_full_payload()))
        response = {
            'content': [{'type': 'text', 'text': text}],
            'usage': {'input_tokens': 100, 'output_tokens': 50,
                      'cache_read_input_tokens': 0,
                      'cache_creation_input_tokens': 0},
        }
        with open(log_file, 'w') as f:
            json.dump(response, f)
        return response
    from storyforge import api, scoring_story_power
    monkeypatch.setattr(api, 'invoke_to_file', fake)
    monkeypatch.setattr(scoring_story_power, 'invoke_to_file', fake)
    result = scoring_story_power.score_story_power(str(tmp_path), 'full')
    assert result['act_shape'] is not None
    assert result['act_shape']['status'] == 'unparseable'
    assert result['status'] == 'partial'


def test_empty_per_act_column_refuses_to_write_matrix(tmp_path, monkeypatch, capsys):
    """If one whole act has zero valid scores, refuse to write
    per-act-matrix.csv (don't publish an empty column as data)."""
    _seed_summary(str(tmp_path))
    monkeypatch.chdir(str(tmp_path))
    monkeypatch.setenv('ANTHROPIC_API_KEY', 'test-key')
    act_payload = _act_shape_payload()
    # Wipe Act 2's score rows entirely.
    for row in act_payload['per_act']:
        if row['act'] == 'act2':
            row['scores'] = []
    fake = _dual_mock_llm(_full_payload(), act_payload)
    from storyforge import api, scoring_story_power
    monkeypatch.setattr(api, 'invoke_to_file', fake)
    monkeypatch.setattr(scoring_story_power, 'invoke_to_file', fake)
    result = scoring_story_power.score_story_power(str(tmp_path), 'full')
    out = capsys.readouterr().out
    assert 'refusing to write per-act-matrix.csv' in out
    assert not os.path.isfile(os.path.join(result['output_dir'],
                                            'per-act-matrix.csv'))
    # Structural CSV still writes (it had scores).
    assert os.path.isfile(os.path.join(result['output_dir'],
                                        'structural-axes.csv'))
    assert result['status'] == 'partial'


def test_empty_structural_refuses_to_write_csv(tmp_path, monkeypatch, capsys):
    """If structural extraction is entirely empty, refuse to write
    structural-axes.csv."""
    _seed_summary(str(tmp_path))
    monkeypatch.chdir(str(tmp_path))
    monkeypatch.setenv('ANTHROPIC_API_KEY', 'test-key')
    act_payload = _act_shape_payload()
    act_payload['structural'] = []
    fake = _dual_mock_llm(_full_payload(), act_payload)
    from storyforge import api, scoring_story_power
    monkeypatch.setattr(api, 'invoke_to_file', fake)
    monkeypatch.setattr(scoring_story_power, 'invoke_to_file', fake)
    result = scoring_story_power.score_story_power(str(tmp_path), 'full')
    out = capsys.readouterr().out
    assert 'refusing to write structural-axes.csv' in out
    assert not os.path.isfile(os.path.join(result['output_dir'],
                                            'structural-axes.csv'))
    # Per-act matrix still writes.
    assert os.path.isfile(os.path.join(result['output_dir'],
                                        'per-act-matrix.csv'))


def test_parse_act_shape_silently_drops_act_0_and_act_4():
    """Acts outside 1-3 are silently ignored. Pins the behavior so a
    future regex tightening doesn't shift it without a deliberate
    decision."""
    from storyforge.scoring_story_power import parse_act_shape
    body = (
        '### Act 0\n\nPrologue.\n\n'
        '### Act 1\n\nFirst.\n\n'
        '### Act 2\n\nSecond.\n\n'
        '### Act 3\n\nThird.\n\n'
        '### Act 4\n\nEpilogue.\n'
    )
    result = parse_act_shape(body)
    assert result is not None
    assert 'First' in result.act1
    assert 'Prologue' not in result.act1


def test_parse_act_shape_duplicate_act_keeps_last():
    """A duplicate `### Act 2` header silently uses the second body
    (dict overwrite). Pinning the behavior — if it changes to first-wins
    or error, that should be a deliberate design choice."""
    from storyforge.scoring_story_power import parse_act_shape
    body = (
        '### Act 1\n\nFirst.\n\n'
        '### Act 2\n\nFirst Act 2.\n\n'
        '### Act 3\n\nThird.\n\n'
        '### Act 2\n\nSecond Act 2.\n'
    )
    result = parse_act_shape(body)
    assert result is not None
    assert result.act2 == 'Second Act 2.'


def test_parse_act_shape_word_headings_not_recognized():
    """`### Act One` (word, not digit) is not recognized. Author who
    writes act headers as words gets pitch-only with no parse — the
    partial-population INFO doesn't fire because no numbered acts were
    detected at all."""
    from storyforge.scoring_story_power import parse_act_shape
    body = (
        '### Act One\n\nFirst.\n\n'
        '### Act Two\n\nSecond.\n\n'
        '### Act Three\n\nThird.\n'
    )
    assert parse_act_shape(body) is None


def test_append_structural_diagnostic_warns_when_md_missing(tmp_path, capsys):
    """If diagnostic.md is absent (upstream _safe_write failed), the
    appender must surface a WARNING — silent no-op cascades one error
    into two casualties."""
    from storyforge.scoring_story_power import _append_structural_diagnostic
    _append_structural_diagnostic(str(tmp_path), {'act1': {}, 'act2': {},
                                                    'act3': {}},
                                    {}, {})
    out = capsys.readouterr().out
    assert 'cross-act diagnostic could not be appended' in out
    assert 'upstream' in out


def test_append_act_shape_coaching_brief_warns_when_md_missing(tmp_path, capsys):
    """Same cascade-surfacing for the coach-mode appender."""
    from storyforge.scoring_story_power import _append_act_shape_coaching_brief
    _append_act_shape_coaching_brief(
        str(tmp_path), {'act1': {}, 'act2': {}, 'act3': {}},
        {}, {'structural': []}, {},
    )
    out = capsys.readouterr().out
    assert 'act-shape coaching brief could not be appended' in out


def test_diagnostic_md_carries_cross_act_payload(tmp_path, monkeypatch):
    """Strengthen the diagnostic-content assertions — pin that
    cross-act pattern, high-leverage move, example beat, and per-axis
    drops all reach diagnostic.md."""
    _seed_summary(str(tmp_path))
    monkeypatch.chdir(str(tmp_path))
    monkeypatch.setenv('ANTHROPIC_API_KEY', 'test-key')
    fake = _dual_mock_llm(_full_payload(), _act_shape_payload())
    from storyforge import api, scoring_story_power
    monkeypatch.setattr(api, 'invoke_to_file', fake)
    monkeypatch.setattr(scoring_story_power, 'invoke_to_file', fake)
    result = scoring_story_power.score_story_power(str(tmp_path), 'full')
    diag = open(os.path.join(result['output_dir'], 'diagnostic.md')).read()
    # Cross-act diagnostic from _act_shape_payload baseline.
    assert 'midpoint' in diag.lower() or 'turning_point' in diag.lower()
    assert 'High-leverage move' in diag
    # Example beat lands in the markdown.
    assert 'failed portrait' in diag
    # Act 2 has the multi-axis dip — drops section should mention act2.
    assert 'ACT2' in diag


def test_coach_brief_carries_full_act_shape_content(tmp_path, monkeypatch):
    """Strengthen the coach-mode brief assertion — pin that the
    structural rationale, drops, cross-act pattern, and independence
    reminder all reach the brief."""
    _seed_summary(str(tmp_path))
    monkeypatch.chdir(str(tmp_path))
    monkeypatch.setenv('ANTHROPIC_API_KEY', 'test-key')
    fake = _dual_mock_llm(_full_payload(), _act_shape_payload())
    from storyforge import api, scoring_story_power
    monkeypatch.setattr(api, 'invoke_to_file', fake)
    monkeypatch.setattr(scoring_story_power, 'invoke_to_file', fake)
    result = scoring_story_power.score_story_power(str(tmp_path), 'coach')
    brief = open(os.path.join(result['output_dir'],
                                'coaching-brief.md')).read()
    # Independence-reminder paragraph from the writer.
    assert 'independent' in brief.lower()
    assert 'localize root cause' in brief
    # Per-axis structural rows include Question/rationale scaffolding.
    assert '- Rationale:' in brief
    assert 'Question:' in brief
    # Drops section + cross-act pattern from the payload.
    assert 'ACT2' in brief
    assert 'midpoint' in brief.lower()
    assert 'failed portrait' in brief


def test_strict_without_act_shape_omits_structural_section(tmp_path, monkeypatch):
    """A project with only logline+synopsis runs strict mode without
    the per-act blanks or structural-axis sections."""
    yml = os.path.join(str(tmp_path), 'storyforge.yaml')
    with open(yml, 'w') as f:
        f.write('project:\n  title: T\n  medium: novel\n  coaching_level: strict\n')
    ref = os.path.join(str(tmp_path), 'reference')
    os.makedirs(ref, exist_ok=True)
    with open(os.path.join(ref, 'story-summary.md'), 'w') as f:
        f.write('# Story summary\n\n## Logline\n\nL.\n\n'
                '## Synopsis\n\nS.\n\n## Act-shape\n\n## Theme\n\n')
    monkeypatch.chdir(str(tmp_path))
    from storyforge.scoring_story_power import (
        score_story_power, AXES, STRUCTURAL_AXES,
    )
    result = score_story_power(str(tmp_path), 'strict')
    text = open(os.path.join(result['output_dir'],
                              'self-scoring-checklist.md')).read()
    # All 8 pitch axes appear.
    for axis in AXES:
        assert f'## {axis.name}' in text
    # No structural axis sections, no per-act blanks.
    for axis in STRUCTURAL_AXES:
        assert axis.name not in text
    assert 'Act 1' not in text
    assert 'Act 2' not in text


def test_flag_act_drops_rounding_boundary():
    """Half-point gaps round to flag at 1.5 (rounds to 2) but not at
    0.5 (rounds to 0). Pins Python's banker's-rounding behavior so an
    accidental switch to integer truncation would be caught."""
    from storyforge.scoring_story_power import _flag_act_drops
    # other_avg = (9 + 8) / 2 = 8.5; gap = 8.5 - 7 = 1.5 → rounds to 2 → flags
    per_act = {
        'act1': {'specificity': 9},
        'act2': {'specificity': 7},
        'act3': {'specificity': 8},
    }
    drops, _skipped = _flag_act_drops(per_act)
    assert ('specificity', 'act2', 2) in drops
    # other_avg = (9 + 9) / 2 = 9; gap = 9 - 8 = 1 → does not flag (< 2)
    per_act = {
        'act1': {'specificity': 9},
        'act2': {'specificity': 8},
        'act3': {'specificity': 9},
    }
    drops, _skipped = _flag_act_drops(per_act)
    assert not drops


def test_dry_run_full_does_not_call_llm(tmp_path, monkeypatch):
    """dry-run for full coaching: no LLM call, status='dry_run', no
    CSVs written. CLI contract for `storyforge score --story-power
    --dry-run`."""
    _seed_summary(str(tmp_path))
    monkeypatch.chdir(str(tmp_path))
    monkeypatch.setenv('ANTHROPIC_API_KEY', 'test-key')
    from storyforge import api, scoring_story_power

    def boom(*a, **k):
        raise AssertionError('LLM must not be called in dry-run')
    monkeypatch.setattr(api, 'invoke_to_file', boom)
    monkeypatch.setattr(scoring_story_power, 'invoke_to_file', boom)
    result = scoring_story_power.score_story_power(str(tmp_path), 'full',
                                                    dry_run=True)
    assert result['status'] == 'dry_run'
    # No CSVs land on disk.
    out_dir = result['output_dir']
    if out_dir and os.path.isdir(out_dir):
        assert not os.path.isfile(os.path.join(out_dir, 'scorecard.csv'))


def test_dry_run_strict_does_not_call_llm(tmp_path, monkeypatch):
    """dry-run for strict coaching: status='dry_run', no checklist."""
    _seed_summary(str(tmp_path))
    monkeypatch.chdir(str(tmp_path))
    from storyforge import api, scoring_story_power

    def boom(*a, **k):
        raise AssertionError('LLM must not be called in strict')
    monkeypatch.setattr(api, 'invoke_to_file', boom)
    monkeypatch.setattr(scoring_story_power, 'invoke_to_file', boom)
    result = scoring_story_power.score_story_power(str(tmp_path), 'strict',
                                                    dry_run=True)
    assert result['status'] == 'dry_run'


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
