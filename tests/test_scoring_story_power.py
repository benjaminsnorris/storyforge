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


def _seed_spine(project_dir: str, event_count: int = 4) -> None:
    """Write a small spine.csv. Default: four events covering a 3-act
    structure. Pitch + act-shape seeding handled by _seed_summary."""
    ref = os.path.join(project_dir, 'reference')
    os.makedirs(ref, exist_ok=True)
    rows = [
        ('ev-incite', '1', 'Inciting incident', 'inciting incident',
         'Lucien is commissioned to portrait a woman the Archive cannot hold.'),
        ('ev-discovery', '2', 'Discovery', 'midpoint reversal',
         'Lucien finds the Archive itself is unmaking memory.'),
        ('ev-climax', '3', 'Climax', 'climax',
         'Lucien refuses to finalize the portrait.'),
        ('ev-fracture', '4', 'Fracture', 'resolution',
         'The Archive collapses; what remains is hers and unstable.'),
    ][:event_count]
    headers = 'id|seq|title|function|summary'
    lines = [headers] + ['|'.join(r) for r in rows]
    with open(os.path.join(ref, 'spine.csv'), 'w') as f:
        f.write('\n'.join(lines) + '\n')


def _spine_payload(per_event_overrides=None, whole_spine_overrides=None,
                    weak_handoff_score: int = 6) -> dict:
    """Build a well-shaped spine LLM response payload.

    Defaults: 4 events, final event has no causal_handoff row, one weak
    handoff (ev-discovery → ev-climax at weak_handoff_score) so the
    diagnostic and proposed-fix paths are exercised by the baseline.
    """
    event_ids = ['ev-incite', 'ev-discovery', 'ev-climax', 'ev-fracture']
    base_scores = {
        eid: {'function_alignment': 9, 'concreteness': 8, 'causal_handoff': 8}
        for eid in event_ids
    }
    # Final event has no handoff.
    base_scores['ev-fracture'].pop('causal_handoff', None)
    # Plant the weak handoff on ev-discovery.
    base_scores['ev-discovery']['causal_handoff'] = weak_handoff_score
    if per_event_overrides:
        for eid, overrides in per_event_overrides.items():
            base_scores.setdefault(eid, {}).update(overrides)
    per_event_rows = [
        {'event_id': eid,
         'scores': [
             {'axis': k, 'score': v, 'rationale': f'{k} for {eid}'}
             for k, v in scores.items()
         ]}
        for eid, scores in base_scores.items()
    ]
    whole = {
        'function_coverage': 9, 'escalation_curve': 9, 'arc_visibility': 8,
        'thematic_distribution': 9, 'spine_act_shape_alignment': 9,
    }
    if whole_spine_overrides:
        whole.update(whole_spine_overrides)
    whole_rows = [
        {'axis': k, 'score': v,
         'positive_signals': f'sig+ for {k}',
         'negative_signals': f'sig- for {k}',
         'rationale': f'rationale for {k}'}
        for k, v in whole.items()
    ]
    return {
        'per_event': per_event_rows,
        'whole_spine': whole_rows,
        'spine_diagnostic': {
            'lowest_axis': 'causal_handoff',
            'lowest_axis_average': '7.0',
            'summary': 'One handoff dips below threshold at the midpoint.',
            'high_leverage_move': 'add a one-clause causal bridge from the midpoint to the climax',
        },
        'proposed_fix': {
            'target_event_id': 'ev-discovery',
            'target_handoff': 'ev-discovery -> ev-climax',
            'current_summary_tail': 'is unmaking memory.',
            'proposed_clause': 'and he resolves to refuse the portrait commission outright.',
            'expected_lift': 'causal_handoff: 6 → 8',
        },
    }


def _triple_mock_llm(pitch_payload: dict, act_shape_payload: dict,
                      spine_payload: dict):
    """Mock that routes by log filename suffix: -act-shape, -spine,
    or default (pitch)."""
    def fake(prompt, model, log_file, **kwargs):
        os.makedirs(os.path.dirname(log_file) or '.', exist_ok=True)
        if '-spine' in log_file:
            payload = spine_payload
        elif '-act-shape' in log_file:
            payload = act_shape_payload
        else:
            payload = pitch_payload
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


def _seed_architecture(project_dir: str, register: str = 'atmospheric',
                         scene_count: int = 4) -> None:
    """Write a small architecture.csv. Adds project.register to
    storyforge.yaml when the seeded summary doesn't already set it."""
    ref = os.path.join(project_dir, 'reference')
    os.makedirs(ref, exist_ok=True)
    rows = [
        ('a01', '1', 'Opening', 'ev-incite', 'action',
         'longing to obligation', 'autonomy', '+/-', 'commitment',
         'Lucien accepts the commission and walks into the archive.'),
        ('a02', '2', 'Discovery', 'ev-discovery', 'sequel',
         'search to recognition', 'understanding', '-/+', 'revelation',
         'Lucien realizes the archive itself is unmaking memory.'),
        ('a03', '3', 'Confrontation', 'ev-climax', 'action',
         'descent to refusal', 'integrity', '-/-', 'choice',
         'Lucien refuses the order and the archive turns against him.'),
        ('a04', '4', 'Fracture', 'ev-fracture', 'sequel',
         'rupture to acceptance', 'memory', '-/+', 'closure',
         'The archive collapses; what remains is unstable and hers.'),
    ][:scene_count]
    headers = ('id|seq|title|spine_event|action_sequel|emotional_arc|'
               'value_at_stake|value_shift|turning_point|summary')
    lines = [headers] + ['|'.join(r) for r in rows]
    with open(os.path.join(ref, 'architecture.csv'), 'w') as f:
        f.write('\n'.join(lines) + '\n')

    # Patch register into the yaml if it isn't already there.
    yml = os.path.join(project_dir, 'storyforge.yaml')
    if os.path.isfile(yml):
        text = open(yml).read()
        if 'register:' not in text:
            with open(yml, 'a') as f:
                f.write(f'  register: {register}\n')


def _architecture_payload(register_assessment: str | None = None) -> dict:
    """Build a well-shaped architecture LLM response with field findings
    and proposals."""
    scene_ids = ['a01', 'a02', 'a03', 'a04']
    per_scene = []
    for sid in scene_ids:
        per_scene.append({
            'scene_id': sid,
            'scores': [
                {'axis': 'spine_event_service', 'score': 9,
                 'rationale': f'service for {sid}'},
                {'axis': 'field_coherence', 'score': 7 if sid == 'a02' else 9,
                 'rationale': f'coherence for {sid}'},
            ],
        })
    whole = [
        {'axis': 'action_sequel_rhythm', 'score': 8,
         'positive_signals': 'alternation', 'negative_signals': 'slight skew',
         'rationale': 'ok for atmospheric register'},
        {'axis': 'spine_coverage_balance', 'score': 9,
         'positive_signals': 'event coverage even', 'negative_signals': '',
         'rationale': 'each spine event has at least one scene'},
        {'axis': 'cumulative_arc_gradient', 'score': 8,
         'positive_signals': 'arc shifts each scene', 'negative_signals': '',
         'rationale': 'no repeat arcs'},
        {'axis': 'scene_causal_chain', 'score': 8,
         'positive_signals': 'a02 → a03 strong', 'negative_signals': 'a03 → a04 abrupt',
         'rationale': 'one weak handoff'},
        {'axis': 'scene_promise_payoff', 'score': 9,
         'positive_signals': 'opening commission paid off in closing fracture',
         'negative_signals': '',
         'rationale': 'closing image refers to opening'},
    ]
    return {
        'per_scene': per_scene,
        'whole_architecture': whole,
        'architecture_diagnostic': {
            'lowest_axis': 'field_coherence',
            'lowest_axis_average': '8.5',
            'summary': 'a02 has a coherence gap between summary and emotional_arc',
            'register_assessment': register_assessment or
                '50% action vs declared atmospheric register — within band',
            'high_leverage_move': 'update a02 emotional_arc to match expanded summary',
        },
        'field_findings': [
            {'scene_id': 'a02', 'field': 'emotional_arc',
             'issue': 'arc has not been updated since summary expanded',
             'severity': 'high'},
        ],
        'proposed_field_updates': [
            {'scene_id': 'a02', 'field': 'emotional_arc',
             'current_value': 'search to recognition',
             'proposed_value': 'search to recognition and recurrence',
             'rationale': 'matches expanded summary about pattern reading'},
        ],
        'proposed_scene_insertions': [
            {'insert_after': 'a02', 'proposed_id': 'a02b-pattern-trace',
             'spine_event': 'ev-discovery', 'action_sequel': 'sequel',
             'emotional_arc': 'recognition to resolve',
             'value_at_stake': 'understanding', 'value_shift': '0/+',
             'turning_point': 'commitment',
             'summary': 'Lucien traces the pattern and resolves to refuse.',
             'rationale': 'lifts scene_causal_chain 8 → 9 by bridging a02 to a03'},
        ],
    }


def _quad_mock_llm(pitch_payload: dict, act_shape_payload: dict,
                    spine_payload: dict, architecture_payload: dict):
    """Mock that routes by log filename suffix: -act-shape, -spine,
    -architecture, or default (pitch)."""
    def fake(prompt, model, log_file, **kwargs):
        os.makedirs(os.path.dirname(log_file) or '.', exist_ok=True)
        if '-architecture' in log_file:
            payload = architecture_payload
        elif '-spine' in log_file:
            payload = spine_payload
        elif '-act-shape' in log_file:
            payload = act_shape_payload
        else:
            payload = pitch_payload
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

# ---------------------------------------------------------------------------
# Spine mode (Layer 1 per-event matrix + Layer 2 whole-spine axes)
# ---------------------------------------------------------------------------

def test_parse_spine_reads_csv_in_order(tmp_path):
    """parse_spine returns events in CSV order, with id/title/summary/
    function populated from the named columns."""
    _seed_spine(str(tmp_path))
    from storyforge.scoring_story_power import parse_spine
    events = parse_spine(str(tmp_path))
    assert [e.id for e in events] == [
        'ev-incite', 'ev-discovery', 'ev-climax', 'ev-fracture',
    ]
    assert events[1].function == 'midpoint reversal'
    assert 'unmaking memory' in events[1].summary


def test_parse_spine_returns_empty_when_csv_missing(tmp_path):
    from storyforge.scoring_story_power import parse_spine
    assert parse_spine(str(tmp_path)) == []


def test_parse_spine_warns_on_missing_required_columns(tmp_path, capsys):
    ref = os.path.join(str(tmp_path), 'reference')
    os.makedirs(ref, exist_ok=True)
    with open(os.path.join(ref, 'spine.csv'), 'w') as f:
        # no summary col
        f.write('id|title|function\nev-1|Title|function\n')
    from storyforge.scoring_story_power import parse_spine
    assert parse_spine(str(tmp_path)) == []
    out = capsys.readouterr().out
    assert 'missing required columns' in out


def test_parse_spine_skips_rows_without_id_or_summary(tmp_path):
    ref = os.path.join(str(tmp_path), 'reference')
    os.makedirs(ref, exist_ok=True)
    with open(os.path.join(ref, 'spine.csv'), 'w') as f:
        f.write(
            'id|seq|title|function|summary\n'
            '|1|Untitled|f|with summary\n'
            'ev-2|2|T|f|\n'
            'ev-3|3|T|f|Has both\n'
        )
    from storyforge.scoring_story_power import parse_spine
    events = parse_spine(str(tmp_path))
    assert [e.id for e in events] == ['ev-3']


def test_per_event_axes_invariants():
    from storyforge.scoring_story_power import (
        PER_EVENT_AXES, AXIS_KEYS, STRUCTURAL_AXIS_KEYS,
    )
    keys = [a.key for a in PER_EVENT_AXES]
    assert len(keys) == 3
    assert len(set(keys)) == 3
    # Disjoint from pitch + structural — diagnostic routing depends on it.
    assert not (set(keys) & set(AXIS_KEYS))
    assert not (set(keys) & set(STRUCTURAL_AXIS_KEYS))
    # Causal handoff carries the elevated weight per the rubric.
    weights = {a.key: a.weight for a in PER_EVENT_AXES}
    assert weights['causal_handoff'] == 1.5


def test_spine_axes_invariants():
    from storyforge.scoring_story_power import (
        SPINE_AXES, AXIS_KEYS, STRUCTURAL_AXIS_KEYS, PER_EVENT_AXIS_KEYS,
    )
    keys = [a.key for a in SPINE_AXES]
    assert len(keys) == 5
    assert len(set(keys)) == 5
    assert not (set(keys) & set(AXIS_KEYS))
    assert not (set(keys) & set(STRUCTURAL_AXIS_KEYS))
    assert not (set(keys) & set(PER_EVENT_AXIS_KEYS))


def test_function_concreteness_floor_conceptual_vs_concrete():
    from storyforge.scoring_story_power import function_concreteness_floor
    # Conceptual-shift functions → floor 7
    assert function_concreteness_floor('midpoint reversal') == 7
    assert function_concreteness_floor('revelation') == 7
    assert function_concreteness_floor('Discovery moment') == 7
    # Concrete-event functions → floor 8
    assert function_concreteness_floor('inciting incident') == 8
    assert function_concreteness_floor('climax') == 8
    assert function_concreteness_floor('Act 2 turning point') == 8
    # Empty / unknown defaults to concrete floor.
    assert function_concreteness_floor('') == 8
    assert function_concreteness_floor('something custom') == 8


def test_spine_mode_writes_matrix_and_whole_spine_csvs(tmp_path, monkeypatch):
    """With spine.csv populated and a well-shaped spine response, the
    run writes per-event-matrix.csv and whole-spine-axes.csv plus the
    appended diagnostic."""
    _seed_summary(str(tmp_path))
    _seed_spine(str(tmp_path))
    monkeypatch.chdir(str(tmp_path))
    monkeypatch.setenv('ANTHROPIC_API_KEY', 'test-key')
    fake = _triple_mock_llm(_full_payload(), _act_shape_payload(),
                              _spine_payload())
    from storyforge import api, scoring_story_power
    monkeypatch.setattr(api, 'invoke_to_file', fake)
    monkeypatch.setattr(scoring_story_power, 'invoke_to_file', fake)
    result = scoring_story_power.score_story_power(str(tmp_path), 'full')
    out_dir = result['output_dir']
    assert os.path.isfile(os.path.join(out_dir, 'scorecard.csv'))
    assert os.path.isfile(os.path.join(out_dir, 'per-event-matrix.csv'))
    assert os.path.isfile(os.path.join(out_dir, 'whole-spine-axes.csv'))
    matrix = open(os.path.join(out_dir, 'per-event-matrix.csv')).read()
    for ev_id in ('ev-incite', 'ev-discovery', 'ev-climax', 'ev-fracture'):
        assert ev_id in matrix
    whole = open(os.path.join(out_dir, 'whole-spine-axes.csv')).read()
    for axis in ('function_coverage', 'escalation_curve', 'arc_visibility',
                  'thematic_distribution', 'spine_act_shape_alignment'):
        assert axis in whole
    # SpineExtension reaches the result.
    ext = result['spine']
    assert ext is not None
    assert ext['status'] == 'ok'
    assert ext['per_event_scores']['ev-discovery']['causal_handoff'] == 6
    assert ext['whole_spine_scores']['function_coverage'] == 9


def test_spine_diagnostic_appended_with_weak_handoff_and_fix(tmp_path,
                                                              monkeypatch):
    _seed_summary(str(tmp_path))
    _seed_spine(str(tmp_path))
    monkeypatch.chdir(str(tmp_path))
    monkeypatch.setenv('ANTHROPIC_API_KEY', 'test-key')
    fake = _triple_mock_llm(_full_payload(), _act_shape_payload(),
                              _spine_payload())
    from storyforge import api, scoring_story_power
    monkeypatch.setattr(api, 'invoke_to_file', fake)
    monkeypatch.setattr(scoring_story_power, 'invoke_to_file', fake)
    result = scoring_story_power.score_story_power(str(tmp_path), 'full')
    diag = open(os.path.join(result['output_dir'], 'diagnostic.md')).read()
    assert 'Per-event matrix' in diag
    assert 'Whole-spine axes' in diag
    assert 'Weak causal handoffs' in diag
    # The weak handoff on ev-discovery should appear with score 6.
    assert 'ev-discovery' in diag
    # Proposed fix lands in the diagnostic.
    assert 'Proposed clause to add' in diag
    assert 'refuse the portrait commission' in diag
    assert 'Expected lift' in diag


def test_spine_only_runs_when_csv_present(tmp_path, monkeypatch):
    """A project with only logline+synopsis+act-shape (no spine.csv)
    runs without the spine extension. result.spine stays None."""
    _seed_summary(str(tmp_path))
    monkeypatch.chdir(str(tmp_path))
    monkeypatch.setenv('ANTHROPIC_API_KEY', 'test-key')
    fake = _dual_mock_llm(_full_payload(), _act_shape_payload())
    from storyforge import api, scoring_story_power
    monkeypatch.setattr(api, 'invoke_to_file', fake)
    monkeypatch.setattr(scoring_story_power, 'invoke_to_file', fake)
    result = scoring_story_power.score_story_power(str(tmp_path), 'full')
    assert result['spine'] is None
    out_dir = result['output_dir']
    assert not os.path.isfile(os.path.join(out_dir, 'per-event-matrix.csv'))


def test_spine_independent_of_act_shape(tmp_path, monkeypatch):
    """Spine mode fires even when act-shape is empty. The
    spine_act_shape_alignment axis still scores (LLM marks it N/A)."""
    yml = os.path.join(str(tmp_path), 'storyforge.yaml')
    with open(yml, 'w') as f:
        f.write('project:\n  title: T\n  medium: novel\n  coaching_level: full\n')
    ref = os.path.join(str(tmp_path), 'reference')
    os.makedirs(ref, exist_ok=True)
    # No act-shape paragraphs.
    with open(os.path.join(ref, 'story-summary.md'), 'w') as f:
        f.write('# Story summary\n\n## Logline\n\nL.\n\n'
                '## Synopsis\n\nS.\n\n## Act-shape\n\n## Theme\n\nT.\n')
    _seed_spine(str(tmp_path))
    monkeypatch.chdir(str(tmp_path))
    monkeypatch.setenv('ANTHROPIC_API_KEY', 'test-key')

    def fake(prompt, model, log_file, **kwargs):
        os.makedirs(os.path.dirname(log_file) or '.', exist_ok=True)
        payload = (_spine_payload() if '-spine' in log_file
                   else _full_payload())
        response = {
            'content': [{'type': 'text', 'text': json.dumps(payload)}],
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
    assert result['act_shape'] is None
    assert result['spine'] is not None
    assert result['spine']['status'] == 'ok'


def test_spine_llm_failure_does_not_kill_other_results(tmp_path, monkeypatch):
    """Spine LLM raises → spine extension carries status='llm_error',
    pitch result intact, overall status degrades to partial."""
    _seed_summary(str(tmp_path))
    _seed_spine(str(tmp_path))
    monkeypatch.chdir(str(tmp_path))
    monkeypatch.setenv('ANTHROPIC_API_KEY', 'test-key')

    def fake(prompt, model, log_file, **kwargs):
        os.makedirs(os.path.dirname(log_file) or '.', exist_ok=True)
        if '-spine' in log_file:
            raise RuntimeError('simulated spine API outage')
        payload = (_act_shape_payload() if '-act-shape' in log_file
                   else _full_payload())
        response = {
            'content': [{'type': 'text', 'text': json.dumps(payload)}],
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
    assert result['spine'] is not None
    assert result['spine']['status'] == 'llm_error'
    assert result['status'] == 'partial'
    out_dir = result['output_dir']
    assert os.path.isfile(os.path.join(out_dir, 'scorecard.csv'))
    assert not os.path.isfile(os.path.join(out_dir, 'per-event-matrix.csv'))


def test_spine_unparseable_response_tags_status(tmp_path, monkeypatch):
    _seed_summary(str(tmp_path))
    _seed_spine(str(tmp_path))
    monkeypatch.chdir(str(tmp_path))
    monkeypatch.setenv('ANTHROPIC_API_KEY', 'test-key')

    def fake(prompt, model, log_file, **kwargs):
        os.makedirs(os.path.dirname(log_file) or '.', exist_ok=True)
        if '-spine' in log_file:
            text = 'no json here'
        else:
            payload = (_act_shape_payload() if '-act-shape' in log_file
                       else _full_payload())
            text = json.dumps(payload)
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
    assert result['spine'] is not None
    assert result['spine']['status'] == 'unparseable'


def test_weak_handoff_threshold_flags_below_8():
    """_identify_weak_handoffs returns every transition with
    causal_handoff below 8. Final event has no handoff and is skipped."""
    from storyforge.scoring_story_power import (
        _identify_weak_handoffs, SpineEvent, WEAK_HANDOFF_THRESHOLD,
    )
    assert WEAK_HANDOFF_THRESHOLD == 8
    events = [
        SpineEvent('a', 'A', 'sa', 'inciting incident'),
        SpineEvent('b', 'B', 'sb', 'midpoint reversal'),
        SpineEvent('c', 'C', 'sc', 'climax'),
        SpineEvent('d', 'D', 'sd', 'resolution'),
    ]
    per_event = {
        'a': {'causal_handoff': 7},  # weak
        'b': {'causal_handoff': 8},  # at threshold, not weak
        'c': {'causal_handoff': 6},  # weak
        'd': {},                      # final, no handoff
    }
    weak, skipped = _identify_weak_handoffs(events, per_event)
    weak_pairs = [(h['from_event'], h['to_event'], h['score']) for h in weak]
    assert ('a', 'b', 7) in weak_pairs
    assert ('c', 'd', 6) in weak_pairs
    assert ('b', 'c', 8) not in weak_pairs
    # All transitions had upstream scores → no skipped entries.
    assert skipped == []


def test_weak_handoff_act_bridge_detection():
    """Transitions whose upstream function suggests an act closer
    (turning point, midpoint, climax) carry is_act_bridge=True."""
    from storyforge.scoring_story_power import (
        _identify_weak_handoffs, SpineEvent,
    )
    events = [
        SpineEvent('a', 'A', 'sa', 'rising action'),
        SpineEvent('b', 'B', 'sb', 'Act 1 turning point'),
        SpineEvent('c', 'C', 'sc', 'climax setup'),
    ]
    per_event = {
        'a': {'causal_handoff': 5},
        'b': {'causal_handoff': 5},
        'c': {},
    }
    weak, _skipped = _identify_weak_handoffs(events, per_event)
    by_from = {h['from_event']: h for h in weak}
    assert by_from['a']['is_act_bridge'] is False
    assert by_from['b']['is_act_bridge'] is True


def test_spine_extension_status_ok_implies_non_empty_scores(tmp_path, monkeypatch):
    """Invariant: if SpineExtension status == 'ok', per_event_scores AND
    whole_spine_scores must be non-empty. The arithmetic that enforces
    this lives in the missing-count calculation in _run_spine_extension
    — easy to break in a "performance tweak" refactor that short-circuits
    on LLM failure. Pin it."""
    _seed_summary(str(tmp_path))
    _seed_spine(str(tmp_path))
    monkeypatch.chdir(str(tmp_path))
    monkeypatch.setenv('ANTHROPIC_API_KEY', 'test-key')
    fake = _triple_mock_llm(_full_payload(), _act_shape_payload(),
                              _spine_payload())
    from storyforge import api, scoring_story_power
    monkeypatch.setattr(api, 'invoke_to_file', fake)
    monkeypatch.setattr(scoring_story_power, 'invoke_to_file', fake)
    result = scoring_story_power.score_story_power(str(tmp_path), 'full')
    ext = result['spine']
    assert ext is not None
    if ext['status'] == 'ok':
        assert ext['per_event_scores']
        assert ext['whole_spine_scores']


def test_identify_weak_handoffs_surfaces_skipped_transitions():
    """When the upstream's causal_handoff score is missing (LLM omitted
    the row), the transition is skipped rather than silently treated
    as not-weak. The caller surfaces these so the author knows the
    analysis is incomplete at that position."""
    from storyforge.scoring_story_power import (
        _identify_weak_handoffs, SpineEvent,
    )
    events = [
        SpineEvent('a', 'A', 'sa', 'inciting incident'),
        SpineEvent('b', 'B', 'sb', 'midpoint reversal'),
        SpineEvent('c', 'C', 'sc', 'climax'),
    ]
    per_event = {
        'a': {'causal_handoff': 9},  # strong, not weak
        'b': {},                       # no score — should appear in skipped
        'c': {},
    }
    weak, skipped = _identify_weak_handoffs(events, per_event)
    assert weak == []
    assert ('b', 'c') in skipped
    assert ('a', 'b') not in skipped


def test_partial_per_event_column_refuses_to_write_spine_matrix(tmp_path,
                                                                  monkeypatch,
                                                                  capsys):
    """Mirror of the act-shape matrix-floor behavior: if any spine event
    has zero valid scores, refuse to write per-event-matrix.csv. The
    floor prevents publishing a half-empty CSV that downstream consumers
    would read as 'score 0 / N/A'."""
    _seed_summary(str(tmp_path))
    _seed_spine(str(tmp_path))
    monkeypatch.chdir(str(tmp_path))
    monkeypatch.setenv('ANTHROPIC_API_KEY', 'test-key')
    spine_payload = _spine_payload()
    # Wipe ev-climax's score rows entirely (whole row empty, not just
    # missing one axis).
    for row in spine_payload['per_event']:
        if row['event_id'] == 'ev-climax':
            row['scores'] = []
    fake = _triple_mock_llm(_full_payload(), _act_shape_payload(),
                              spine_payload)
    from storyforge import api, scoring_story_power
    monkeypatch.setattr(api, 'invoke_to_file', fake)
    monkeypatch.setattr(scoring_story_power, 'invoke_to_file', fake)
    result = scoring_story_power.score_story_power(str(tmp_path), 'full')
    out = capsys.readouterr().out
    assert 'refusing to write per-event-matrix.csv' in out
    assert 'ev-climax' in out
    assert not os.path.isfile(os.path.join(result['output_dir'],
                                            'per-event-matrix.csv'))
    # Whole-spine CSV still writes (it has data).
    assert os.path.isfile(os.path.join(result['output_dir'],
                                        'whole-spine-axes.csv'))
    assert result['status'] == 'partial'


def test_skipped_handoff_surfaces_in_diagnostic(tmp_path, monkeypatch):
    """When the LLM omits the causal_handoff score for a non-final event,
    the spine diagnostic surfaces the skipped transition so the author
    knows the cross-event analysis is incomplete at that position."""
    _seed_summary(str(tmp_path))
    _seed_spine(str(tmp_path))
    monkeypatch.chdir(str(tmp_path))
    monkeypatch.setenv('ANTHROPIC_API_KEY', 'test-key')
    spine_payload = _spine_payload()
    # Strip causal_handoff from ev-discovery (a non-final event).
    for row in spine_payload['per_event']:
        if row['event_id'] == 'ev-discovery':
            row['scores'] = [s for s in row['scores']
                             if s['axis'] != 'causal_handoff']
    fake = _triple_mock_llm(_full_payload(), _act_shape_payload(),
                              spine_payload)
    from storyforge import api, scoring_story_power
    monkeypatch.setattr(api, 'invoke_to_file', fake)
    monkeypatch.setattr(scoring_story_power, 'invoke_to_file', fake)
    result = scoring_story_power.score_story_power(str(tmp_path), 'full')
    diag = open(os.path.join(result['output_dir'], 'diagnostic.md')).read()
    assert 'Skipped causal handoffs' in diag
    assert 'ev-discovery → ev-climax' in diag


def test_spine_partial_per_event_tags_partial(tmp_path, monkeypatch):
    """Missing per-event scores surface as status='partial'."""
    _seed_summary(str(tmp_path))
    _seed_spine(str(tmp_path))
    monkeypatch.chdir(str(tmp_path))
    monkeypatch.setenv('ANTHROPIC_API_KEY', 'test-key')
    spine_payload = _spine_payload()
    # Drop ev-climax entirely.
    spine_payload['per_event'] = [r for r in spine_payload['per_event']
                                    if r['event_id'] != 'ev-climax']
    fake = _triple_mock_llm(_full_payload(), _act_shape_payload(),
                              spine_payload)
    from storyforge import api, scoring_story_power
    monkeypatch.setattr(api, 'invoke_to_file', fake)
    monkeypatch.setattr(scoring_story_power, 'invoke_to_file', fake)
    result = scoring_story_power.score_story_power(str(tmp_path), 'full')
    assert result['spine']['status'] == 'partial'
    assert result['status'] == 'partial'


def test_empty_spine_extraction_refuses_to_write_csv(tmp_path, monkeypatch,
                                                       capsys):
    """Zero valid per-event scores → refuse to write the matrix."""
    _seed_summary(str(tmp_path))
    _seed_spine(str(tmp_path))
    monkeypatch.chdir(str(tmp_path))
    monkeypatch.setenv('ANTHROPIC_API_KEY', 'test-key')
    spine_payload = _spine_payload()
    spine_payload['per_event'] = []
    fake = _triple_mock_llm(_full_payload(), _act_shape_payload(),
                              spine_payload)
    from storyforge import api, scoring_story_power
    monkeypatch.setattr(api, 'invoke_to_file', fake)
    monkeypatch.setattr(scoring_story_power, 'invoke_to_file', fake)
    result = scoring_story_power.score_story_power(str(tmp_path), 'full')
    out = capsys.readouterr().out
    assert 'refusing to write per-event-matrix.csv' in out
    assert not os.path.isfile(os.path.join(result['output_dir'],
                                            'per-event-matrix.csv'))


def test_spine_coach_mode_appends_to_brief(tmp_path, monkeypatch):
    _seed_summary(str(tmp_path))
    _seed_spine(str(tmp_path))
    monkeypatch.chdir(str(tmp_path))
    monkeypatch.setenv('ANTHROPIC_API_KEY', 'test-key')
    fake = _triple_mock_llm(_full_payload(), _act_shape_payload(),
                              _spine_payload())
    from storyforge import api, scoring_story_power
    monkeypatch.setattr(api, 'invoke_to_file', fake)
    monkeypatch.setattr(scoring_story_power, 'invoke_to_file', fake)
    result = scoring_story_power.score_story_power(str(tmp_path), 'coach')
    brief = open(os.path.join(result['output_dir'],
                                'coaching-brief.md')).read()
    assert 'Spine extension' in brief
    assert 'Per-event matrix' in brief
    assert 'Weak causal handoffs' in brief
    # Independence reminder — proposed fix is a proposal, not a directive.
    assert 'not a directive' in brief
    # No separate spine CSVs in coach mode.
    assert not os.path.isfile(os.path.join(result['output_dir'],
                                            'per-event-matrix.csv'))


def test_strict_mode_with_spine_extends_checklist(tmp_path, monkeypatch):
    """Strict mode reads spine.csv and adds per-event + whole-spine
    blanks to the checklist. No LLM call."""
    _seed_summary(str(tmp_path))
    _seed_spine(str(tmp_path))
    monkeypatch.chdir(str(tmp_path))
    from storyforge import api, scoring_story_power

    def boom(*a, **k):
        raise AssertionError('LLM must not be called in strict')
    monkeypatch.setattr(api, 'invoke_to_file', boom)
    monkeypatch.setattr(scoring_story_power, 'invoke_to_file', boom)
    result = scoring_story_power.score_story_power(str(tmp_path), 'strict')
    text = open(os.path.join(result['output_dir'],
                              'self-scoring-checklist.md')).read()
    # Spine section appears with per-event blanks.
    assert 'Spine tier' in text
    for ev_id in ('ev-incite', 'ev-discovery', 'ev-climax', 'ev-fracture'):
        assert ev_id in text
    # Five whole-spine axes get their own sections.
    from storyforge.scoring_story_power import SPINE_AXES
    for axis in SPINE_AXES:
        assert axis.name in text


# ---------------------------------------------------------------------------
# Test gaps from the PR #240 review
# ---------------------------------------------------------------------------

def test_append_spine_diagnostic_warns_when_md_missing(tmp_path, capsys):
    """Mirror of the act-shape gap PR #238 caught — if diagnostic.md
    is absent, the spine appender must surface a WARNING."""
    from storyforge.scoring_story_power import (
        _append_spine_diagnostic, SpineEvent,
    )
    events = [SpineEvent('a', 'A', 'sa', 'inciting incident')]
    _append_spine_diagnostic(str(tmp_path), events, {'a': {}}, {}, [], [], {}, {})
    out = capsys.readouterr().out
    assert 'spine diagnostic could not be appended' in out
    assert 'upstream' in out


def test_append_spine_coaching_brief_warns_when_md_missing(tmp_path, capsys):
    from storyforge.scoring_story_power import (
        _append_spine_coaching_brief, SpineEvent,
    )
    events = [SpineEvent('a', 'A', 'sa', 'inciting incident')]
    _append_spine_coaching_brief(str(tmp_path), events, {'a': {}}, {}, [],
                                   [], {}, {})
    out = capsys.readouterr().out
    assert 'spine coaching brief could not be appended' in out


def test_parse_response_spine_handles_fenced_json():
    """Tier-2 fallback: ```json {...} ``` wrapper must still parse."""
    from storyforge.scoring_story_power import _parse_response_spine
    payload = json.dumps(_spine_payload())
    text = f'Here is the spine score:\n\n```json\n{payload}\n```\n'
    parsed = _parse_response_spine(text)
    assert parsed is not None
    assert isinstance(parsed['per_event'], list)
    assert isinstance(parsed['whole_spine'], list)


def test_parse_response_spine_handles_greedy_extraction():
    """Tier-3 fallback: JSON embedded in prose with no fences."""
    from storyforge.scoring_story_power import _parse_response_spine
    payload = json.dumps(_spine_payload())
    text = f'Here is my analysis. {payload} Done.'
    parsed = _parse_response_spine(text)
    assert parsed is not None


def test_parse_response_spine_warns_when_list_is_missing(capsys):
    """If JSON parses but per_event or whole_spine isn't a list, the
    shape-failure WARNING fires naming the missing key."""
    from storyforge.scoring_story_power import _parse_response_spine
    bad = json.dumps({'per_event': []})  # whole_spine missing
    parsed = _parse_response_spine(bad)
    assert parsed is None
    out = capsys.readouterr().out
    assert 'whole_spine' in out


def test_extract_per_event_scores_drops_malformed(capsys):
    """Drop paths: non-dict event row, unknown event_id, non-dict score
    row, unknown axis, non-int score, out-of-range score. Logs INFO
    naming the drops."""
    from storyforge.scoring_story_power import _extract_per_event_scores
    parsed = {
        'per_event': [
            'not a dict',                                # non-dict row
            {'event_id': 'unknown-id', 'scores': []},    # unknown event
            {'event_id': 'ev-a', 'scores': [
                'not a dict',                            # non-dict score row
                {'axis': 'made_up', 'score': 8},         # unknown axis
                {'axis': 'concreteness', 'score': 'h'},  # non-int
                {'axis': 'function_alignment', 'score': 15},  # out-of-range
                {'axis': 'function_alignment', 'score': 7},   # valid, kept
            ]},
        ],
    }
    out = _extract_per_event_scores(parsed, ['ev-a'])
    assert out == {'ev-a': {'function_alignment': 7}}
    info = capsys.readouterr().out
    assert 'per-event extraction dropped' in info


def test_extract_whole_spine_scores_drops_malformed(capsys):
    """Same drop pattern for whole-spine extraction."""
    from storyforge.scoring_story_power import _extract_whole_spine_scores
    parsed = {
        'whole_spine': [
            'not a dict',
            {'axis': 'made_up_axis', 'score': 7},
            {'axis': 'arc_visibility', 'score': 'low'},
            {'axis': 'arc_visibility', 'score': 0},
            {'axis': 'arc_visibility', 'score': 8},
        ],
    }
    out = _extract_whole_spine_scores(parsed)
    assert out == {'arc_visibility': 8}
    info = capsys.readouterr().out
    assert 'whole-spine extraction dropped' in info


def test_parse_spine_warns_on_blank_required_field(tmp_path, capsys):
    """A row with blank id or blank summary must surface a WARNING —
    not silently drop the event."""
    ref = os.path.join(str(tmp_path), 'reference')
    os.makedirs(ref, exist_ok=True)
    with open(os.path.join(ref, 'spine.csv'), 'w') as f:
        f.write(
            'id|seq|title|function|summary\n'
            'ev-a|1|A|inciting incident|first.\n'
            '|2|Untitled|midpoint reversal|paragraph with blank id.\n'
            'ev-c|3|C|climax|\n'
        )
    from storyforge.scoring_story_power import parse_spine
    events = parse_spine(str(tmp_path))
    assert [e.id for e in events] == ['ev-a']
    out = capsys.readouterr().out
    assert 'missing required field' in out
    assert 'id' in out
    assert 'summary' in out


def test_spine_csv_header_columns(tmp_path, monkeypatch):
    """per-event-matrix.csv header must match
    event_id|function|function_alignment|concreteness|causal_handoff."""
    _seed_summary(str(tmp_path))
    _seed_spine(str(tmp_path))
    monkeypatch.chdir(str(tmp_path))
    monkeypatch.setenv('ANTHROPIC_API_KEY', 'test-key')
    fake = _triple_mock_llm(_full_payload(), _act_shape_payload(),
                              _spine_payload())
    from storyforge import api, scoring_story_power
    monkeypatch.setattr(api, 'invoke_to_file', fake)
    monkeypatch.setattr(scoring_story_power, 'invoke_to_file', fake)
    result = scoring_story_power.score_story_power(str(tmp_path), 'full')
    matrix = open(os.path.join(result['output_dir'],
                                'per-event-matrix.csv')).read()
    header = matrix.splitlines()[0]
    assert header == 'event_id|function|function_alignment|concreteness|causal_handoff'


def test_whole_spine_csv_weight_column_reflects_axes(tmp_path, monkeypatch):
    """whole-spine-axes.csv's weight column must match SPINE_AXES."""
    _seed_summary(str(tmp_path))
    _seed_spine(str(tmp_path))
    monkeypatch.chdir(str(tmp_path))
    monkeypatch.setenv('ANTHROPIC_API_KEY', 'test-key')
    fake = _triple_mock_llm(_full_payload(), _act_shape_payload(),
                              _spine_payload())
    from storyforge import api, scoring_story_power
    monkeypatch.setattr(api, 'invoke_to_file', fake)
    monkeypatch.setattr(scoring_story_power, 'invoke_to_file', fake)
    result = scoring_story_power.score_story_power(str(tmp_path), 'full')
    from storyforge.scoring_story_power import SPINE_AXES
    csv = open(os.path.join(result['output_dir'],
                              'whole-spine-axes.csv')).read()
    lines = csv.splitlines()
    weight_by_axis_key = {a.key: str(a.weight) for a in SPINE_AXES}
    header = lines[0].split('|')
    axis_col = header.index('axis')
    weight_col = header.index('weight')
    for line in lines[1:]:
        cells = line.split('|')
        assert cells[weight_col] == weight_by_axis_key[cells[axis_col]]


def test_proposed_fix_renders_all_five_fields_in_diagnostic(tmp_path,
                                                              monkeypatch):
    """diagnostic.md must surface target_handoff, target_event_id,
    current_summary_tail, proposed_clause, AND expected_lift."""
    _seed_summary(str(tmp_path))
    _seed_spine(str(tmp_path))
    monkeypatch.chdir(str(tmp_path))
    monkeypatch.setenv('ANTHROPIC_API_KEY', 'test-key')
    fake = _triple_mock_llm(_full_payload(), _act_shape_payload(),
                              _spine_payload())
    from storyforge import api, scoring_story_power
    monkeypatch.setattr(api, 'invoke_to_file', fake)
    monkeypatch.setattr(scoring_story_power, 'invoke_to_file', fake)
    result = scoring_story_power.score_story_power(str(tmp_path), 'full')
    diag = open(os.path.join(result['output_dir'], 'diagnostic.md')).read()
    # All five proposed_fix fields from the _spine_payload baseline.
    assert 'ev-discovery -> ev-climax' in diag           # target_handoff
    assert 'ev-discovery' in diag                          # target_event_id
    assert 'is unmaking memory' in diag                    # current_summary_tail
    assert 'refuse the portrait commission' in diag        # proposed_clause
    assert 'causal_handoff: 6 → 8' in diag                 # expected_lift


def test_spine_independent_prompt_contains_no_act_shape_fallback(tmp_path,
                                                                   monkeypatch):
    """When act-shape is empty, the spine prompt must include the
    fallback instruction telling the LLM to score
    spine_act_shape_alignment as N/A. Capture the prompt to verify."""
    yml = os.path.join(str(tmp_path), 'storyforge.yaml')
    with open(yml, 'w') as f:
        f.write('project:\n  title: T\n  medium: novel\n  coaching_level: full\n')
    ref = os.path.join(str(tmp_path), 'reference')
    os.makedirs(ref, exist_ok=True)
    with open(os.path.join(ref, 'story-summary.md'), 'w') as f:
        f.write('# Story summary\n\n## Logline\n\nL.\n\n## Synopsis\n\nS.\n\n'
                '## Act-shape\n\n## Theme\n\nT.\n')
    _seed_spine(str(tmp_path))
    monkeypatch.chdir(str(tmp_path))
    monkeypatch.setenv('ANTHROPIC_API_KEY', 'test-key')

    captured = {'spine_prompt': None}

    def fake(prompt, model, log_file, **kwargs):
        os.makedirs(os.path.dirname(log_file) or '.', exist_ok=True)
        if '-spine' in log_file:
            captured['spine_prompt'] = prompt
            payload = _spine_payload()
        else:
            payload = _full_payload()
        response = {
            'content': [{'type': 'text', 'text': json.dumps(payload)}],
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
    scoring_story_power.score_story_power(str(tmp_path), 'full')
    assert captured['spine_prompt'] is not None
    assert 'no act-shape populated' in captured['spine_prompt']
    assert 'spine_act_shape_alignment' in captured['spine_prompt']


def test_strict_mode_spine_without_act_shape(tmp_path, monkeypatch):
    """Strict mode with spine.csv but no act-shape: checklist includes
    spine tier but omits the per-act / structural tiers."""
    yml = os.path.join(str(tmp_path), 'storyforge.yaml')
    with open(yml, 'w') as f:
        f.write('project:\n  title: T\n  medium: novel\n  coaching_level: strict\n')
    ref = os.path.join(str(tmp_path), 'reference')
    os.makedirs(ref, exist_ok=True)
    with open(os.path.join(ref, 'story-summary.md'), 'w') as f:
        f.write('# Story summary\n\n## Logline\n\nL.\n\n## Synopsis\n\nS.\n\n'
                '## Act-shape\n\n## Theme\n\nT.\n')
    _seed_spine(str(tmp_path))
    monkeypatch.chdir(str(tmp_path))
    from storyforge.scoring_story_power import score_story_power
    result = score_story_power(str(tmp_path), 'strict')
    text = open(os.path.join(result['output_dir'],
                              'self-scoring-checklist.md')).read()
    assert 'Spine tier' in text
    assert 'Act-shape tier' not in text
    assert 'Cross-act structural axes' not in text


def test_function_concreteness_floor_returns_literal_seven_or_eight():
    """The return annotation is Literal[7, 8]; verify both literals
    are reachable from real-world function strings."""
    from storyforge.scoring_story_power import function_concreteness_floor
    sevens = ['midpoint reversal', 'climactic revelation',
              'pinpoint discovery', 'inciting recognition']
    eights = ['inciting incident', 'climax setup', 'Act 2 closer',
              'resolution', 'denouement', 'custom function']
    for f in sevens:
        assert function_concreteness_floor(f) == 7, f
    for f in eights:
        assert function_concreteness_floor(f) == 8, f


def test_function_concreteness_floor_conceptual_wins_on_mixed_keywords():
    """A function containing both a conceptual and a concrete keyword
    takes the conceptual floor (7). Pins the precedence so a future
    ordering change is loud."""
    from storyforge.scoring_story_power import function_concreteness_floor
    assert function_concreteness_floor('discovery during midpoint reversal') == 7
    assert function_concreteness_floor('revelation at the climax') == 7


def test_identify_weak_handoffs_single_event_spine():
    """A spine with one event has no handoffs — returns ([], []) cleanly."""
    from storyforge.scoring_story_power import (
        _identify_weak_handoffs, SpineEvent,
    )
    events = [SpineEvent('only', 'O', 'so', 'climax')]
    per_event = {'only': {'causal_handoff': 5}}  # would be weak if there were a next
    weak, skipped = _identify_weak_handoffs(events, per_event)
    assert weak == []
    assert skipped == []


def test_llm_includes_final_event_causal_handoff_does_not_crash(tmp_path,
                                                                  monkeypatch):
    """If the LLM violates the prompt instruction and includes a
    causal_handoff for the final event, the extractor accepts it and
    _identify_weak_handoffs doesn't crash (final event isn't iterated)."""
    _seed_summary(str(tmp_path))
    _seed_spine(str(tmp_path))
    monkeypatch.chdir(str(tmp_path))
    monkeypatch.setenv('ANTHROPIC_API_KEY', 'test-key')
    spine_payload = _spine_payload()
    # Add a causal_handoff to ev-fracture (the final event).
    for row in spine_payload['per_event']:
        if row['event_id'] == 'ev-fracture':
            row['scores'].append({
                'axis': 'causal_handoff', 'score': 5,
                'rationale': 'LLM violated prompt instruction',
            })
    fake = _triple_mock_llm(_full_payload(), _act_shape_payload(),
                              spine_payload)
    from storyforge import api, scoring_story_power
    monkeypatch.setattr(api, 'invoke_to_file', fake)
    monkeypatch.setattr(scoring_story_power, 'invoke_to_file', fake)
    result = scoring_story_power.score_story_power(str(tmp_path), 'full')
    ext = result['spine']
    assert ext is not None
    # Score is accepted (not rejected).
    assert ext['per_event_scores']['ev-fracture'].get('causal_handoff') == 5
    # No weak-handoff entry naming ev-fracture as upstream (no next event).
    assert all(h['from_event'] != 'ev-fracture' for h in ext['weak_handoffs'])


def test_parse_spine_strips_whitespace(tmp_path):
    """Trailing whitespace in cells must be stripped, not preserved."""
    ref = os.path.join(str(tmp_path), 'reference')
    os.makedirs(ref, exist_ok=True)
    with open(os.path.join(ref, 'spine.csv'), 'w') as f:
        f.write(
            'id|seq|title|function|summary\n'
            'ev-1 |1| Inciting | inciting incident |  A paragraph.  \n'
        )
    from storyforge.scoring_story_power import parse_spine
    events = parse_spine(str(tmp_path))
    assert events[0].id == 'ev-1'
    assert events[0].title == 'Inciting'
    assert events[0].function == 'inciting incident'
    assert events[0].summary == 'A paragraph.'


def test_missing_whole_spine_axes_path_partial_warning(tmp_path, monkeypatch,
                                                        capsys):
    """If the LLM drops one whole-spine axis, the partial WARN fires
    naming the missing axis and overall status degrades to partial."""
    _seed_summary(str(tmp_path))
    _seed_spine(str(tmp_path))
    monkeypatch.chdir(str(tmp_path))
    monkeypatch.setenv('ANTHROPIC_API_KEY', 'test-key')
    spine_payload = _spine_payload()
    # Drop arc_visibility from the whole_spine list.
    spine_payload['whole_spine'] = [r for r in spine_payload['whole_spine']
                                       if r['axis'] != 'arc_visibility']
    fake = _triple_mock_llm(_full_payload(), _act_shape_payload(),
                              spine_payload)
    from storyforge import api, scoring_story_power
    monkeypatch.setattr(api, 'invoke_to_file', fake)
    monkeypatch.setattr(scoring_story_power, 'invoke_to_file', fake)
    result = scoring_story_power.score_story_power(str(tmp_path), 'full')
    out = capsys.readouterr().out
    assert 'spine extraction partial' in out
    assert 'arc_visibility' in out
    assert result['spine']['status'] == 'partial'
    assert result['status'] == 'partial'


def test_triple_mock_llm_routes_to_all_three_payloads(tmp_path, monkeypatch):
    """Defensive: assert the triple mock is actually routing to spine,
    not silently returning pitch when the suffix key drifts. Counts
    each route via a sentinel marker in each payload."""
    _seed_summary(str(tmp_path))
    _seed_spine(str(tmp_path))
    monkeypatch.chdir(str(tmp_path))
    monkeypatch.setenv('ANTHROPIC_API_KEY', 'test-key')

    seen: dict[str, int] = {'pitch': 0, 'act_shape': 0, 'spine': 0}

    def fake(prompt, model, log_file, **kwargs):
        os.makedirs(os.path.dirname(log_file) or '.', exist_ok=True)
        if '-spine' in log_file:
            seen['spine'] += 1
            payload = _spine_payload()
        elif '-act-shape' in log_file:
            seen['act_shape'] += 1
            payload = _act_shape_payload()
        else:
            seen['pitch'] += 1
            payload = _full_payload()
        response = {
            'content': [{'type': 'text', 'text': json.dumps(payload)}],
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
    scoring_story_power.score_story_power(str(tmp_path), 'full')
    # All three routes must have been hit. If the log-file naming on the
    # implementation side drifts, this fails loudly instead of silently.
    assert seen == {'pitch': 1, 'act_shape': 1, 'spine': 1}


# ---------------------------------------------------------------------------
# Architecture mode (Layer 1 per-scene matrix + Layer 2 whole-architecture)
# ---------------------------------------------------------------------------

def test_parse_architecture_reads_csv_in_order(tmp_path):
    _seed_architecture(str(tmp_path))
    from storyforge.scoring_story_power import parse_architecture
    scenes = parse_architecture(str(tmp_path))
    assert [s.id for s in scenes] == ['a01', 'a02', 'a03', 'a04']
    assert scenes[1].spine_event == 'ev-discovery'
    assert scenes[1].emotional_arc == 'search to recognition'


def test_parse_architecture_returns_empty_when_csv_missing(tmp_path):
    from storyforge.scoring_story_power import parse_architecture
    assert parse_architecture(str(tmp_path)) == []


def test_parse_architecture_warns_on_missing_required_columns(tmp_path, capsys):
    ref = os.path.join(str(tmp_path), 'reference')
    os.makedirs(ref, exist_ok=True)
    with open(os.path.join(ref, 'architecture.csv'), 'w') as f:
        # missing summary column
        f.write('id|title|spine_event\na01|T|ev-1\n')
    from storyforge.scoring_story_power import parse_architecture
    assert parse_architecture(str(tmp_path)) == []
    out = capsys.readouterr().out
    assert 'missing required columns' in out


def test_parse_architecture_warns_on_blank_required_field(tmp_path, capsys):
    ref = os.path.join(str(tmp_path), 'reference')
    os.makedirs(ref, exist_ok=True)
    with open(os.path.join(ref, 'architecture.csv'), 'w') as f:
        f.write(
            'id|seq|title|spine_event|summary\n'
            'a01|1|T|ev-1|First scene.\n'
            '|2|Untitled|ev-2|second.\n'
            'a03|3|T|ev-3|\n'
        )
    from storyforge.scoring_story_power import parse_architecture
    scenes = parse_architecture(str(tmp_path))
    assert [s.id for s in scenes] == ['a01']
    out = capsys.readouterr().out
    assert 'missing required field' in out


def test_per_scene_axes_invariants():
    from storyforge.scoring_story_power import (
        PER_SCENE_AXES, AXIS_KEYS, STRUCTURAL_AXIS_KEYS,
        PER_EVENT_AXIS_KEYS, SPINE_AXIS_KEYS,
    )
    keys = [a.key for a in PER_SCENE_AXES]
    assert len(keys) == 2
    assert len(set(keys)) == 2
    assert not (set(keys) & set(AXIS_KEYS))
    assert not (set(keys) & set(STRUCTURAL_AXIS_KEYS))
    assert not (set(keys) & set(PER_EVENT_AXIS_KEYS))
    assert not (set(keys) & set(SPINE_AXIS_KEYS))
    # field_coherence carries the elevated weight per the rubric.
    weights = {a.key: a.weight for a in PER_SCENE_AXES}
    assert weights['field_coherence'] == 1.5


def test_architecture_axes_invariants():
    from storyforge.scoring_story_power import (
        ARCHITECTURE_AXES, AXIS_KEYS, STRUCTURAL_AXIS_KEYS,
        PER_EVENT_AXIS_KEYS, SPINE_AXIS_KEYS, PER_SCENE_AXIS_KEYS,
    )
    keys = [a.key for a in ARCHITECTURE_AXES]
    assert len(keys) == 5
    assert len(set(keys)) == 5
    for other in (AXIS_KEYS, STRUCTURAL_AXIS_KEYS, PER_EVENT_AXIS_KEYS,
                  SPINE_AXIS_KEYS, PER_SCENE_AXIS_KEYS):
        assert not (set(keys) & set(other))


def test_read_project_register_returns_balanced_when_absent(tmp_path):
    yml = os.path.join(str(tmp_path), 'storyforge.yaml')
    with open(yml, 'w') as f:
        f.write('project:\n  title: T\n  medium: novel\n')
    from storyforge.scoring_story_power import read_project_register
    assert read_project_register(str(tmp_path)) == 'balanced'


def test_read_project_register_reads_declared_value(tmp_path):
    yml = os.path.join(str(tmp_path), 'storyforge.yaml')
    with open(yml, 'w') as f:
        f.write('project:\n  title: T\n  medium: novel\n  register: atmospheric\n')
    from storyforge.scoring_story_power import read_project_register
    assert read_project_register(str(tmp_path)) == 'atmospheric'


def test_read_project_register_falls_back_on_unrecognized(tmp_path, capsys):
    yml = os.path.join(str(tmp_path), 'storyforge.yaml')
    with open(yml, 'w') as f:
        f.write('project:\n  title: T\n  medium: novel\n  register: unknowable\n')
    from storyforge.scoring_story_power import read_project_register
    assert read_project_register(str(tmp_path)) == 'balanced'
    out = capsys.readouterr().out
    assert 'not a recognized register' in out


def test_field_coherence_deterministic_flags_revelation_without_verb():
    from storyforge.scoring_story_power import (
        _check_field_coherence_deterministic, SceneRow,
    )
    # turning_point names revelation but summary has no recognition verb.
    s = SceneRow('a01', 'T', 'They walk through the corridor and stop.',
                 'ev-1', 'sequel', 'tension', 'memory', '0/-', 'revelation')
    findings = _check_field_coherence_deterministic(s)
    assert any(f['field'] == 'turning_point' and f['severity'] == 'high'
               for f in findings)


def test_field_coherence_deterministic_flags_action_without_verbs():
    from storyforge.scoring_story_power import (
        _check_field_coherence_deterministic, SceneRow,
    )
    # action_sequel='action' but summary reads as pure reflection.
    s = SceneRow('a01', 'T', 'She thinks about what she has lost.',
                 'ev-1', 'action', 'longing', 'connection', '0/-', 'choice')
    findings = _check_field_coherence_deterministic(s)
    assert any(f['field'] == 'action_sequel' for f in findings)


def test_field_coherence_deterministic_flags_positive_shift_with_rupture():
    from storyforge.scoring_story_power import (
        _check_field_coherence_deterministic, SceneRow,
    )
    # value_shift +/+ but emotional_arc uses rupture language.
    s = SceneRow('a01', 'T', 'They reach a resolution and embrace.',
                 'ev-1', 'sequel', 'love to rupture', 'connection',
                 '+/+', 'commitment')
    findings = _check_field_coherence_deterministic(s)
    assert any(f['field'] == 'value_shift' and f['severity'] == 'high'
               for f in findings)


def test_field_coherence_deterministic_clean_scene_returns_no_findings():
    from storyforge.scoring_story_power import (
        _check_field_coherence_deterministic, SceneRow,
    )
    # All fields cohere with the summary.
    s = SceneRow('a01', 'T', 'She realizes the pattern and recognizes the trap.',
                 'ev-1', 'sequel', 'search to recognition',
                 'understanding', '-/+', 'revelation')
    findings = _check_field_coherence_deterministic(s)
    assert findings == []


def test_action_sequel_ratio_computes_correctly():
    from storyforge.scoring_story_power import _action_sequel_ratio, SceneRow
    scenes = [
        SceneRow('a', '', 's', '', 'action', '', '', '', ''),
        SceneRow('b', '', 's', '', 'action', '', '', '', ''),
        SceneRow('c', '', 's', '', 'sequel', '', '', '', ''),
        SceneRow('d', '', 's', '', 'something else', '', '', '', ''),
    ]
    action, sequel, ratio = _action_sequel_ratio(scenes)
    assert action == 2
    assert sequel == 1
    assert round(ratio, 2) == round(2 / 3, 2)


def test_architecture_mode_writes_csvs_and_diagnostic(tmp_path, monkeypatch):
    _seed_summary(str(tmp_path))
    _seed_spine(str(tmp_path))
    _seed_architecture(str(tmp_path))
    monkeypatch.chdir(str(tmp_path))
    monkeypatch.setenv('ANTHROPIC_API_KEY', 'test-key')
    fake = _quad_mock_llm(_full_payload(), _act_shape_payload(),
                            _spine_payload(), _architecture_payload())
    from storyforge import api, scoring_story_power
    monkeypatch.setattr(api, 'invoke_to_file', fake)
    monkeypatch.setattr(scoring_story_power, 'invoke_to_file', fake)
    result = scoring_story_power.score_story_power(str(tmp_path), 'full')
    out_dir = result['output_dir']
    assert os.path.isfile(os.path.join(out_dir, 'scorecard.csv'))
    assert os.path.isfile(os.path.join(out_dir, 'per-scene-matrix.csv'))
    assert os.path.isfile(os.path.join(out_dir, 'whole-architecture-axes.csv'))
    ext = result['architecture']
    assert ext is not None
    assert ext['status'] == 'ok'
    assert ext['per_scene_scores']['a02']['field_coherence'] == 7
    assert ext['whole_architecture_scores']['action_sequel_rhythm'] == 8


def test_architecture_diagnostic_includes_findings_and_proposals(tmp_path,
                                                                   monkeypatch):
    _seed_summary(str(tmp_path))
    _seed_spine(str(tmp_path))
    _seed_architecture(str(tmp_path))
    monkeypatch.chdir(str(tmp_path))
    monkeypatch.setenv('ANTHROPIC_API_KEY', 'test-key')
    fake = _quad_mock_llm(_full_payload(), _act_shape_payload(),
                            _spine_payload(), _architecture_payload())
    from storyforge import api, scoring_story_power
    monkeypatch.setattr(api, 'invoke_to_file', fake)
    monkeypatch.setattr(scoring_story_power, 'invoke_to_file', fake)
    result = scoring_story_power.score_story_power(str(tmp_path), 'full')
    diag = open(os.path.join(result['output_dir'], 'diagnostic.md')).read()
    assert 'Per-scene matrix' in diag
    assert 'Whole-architecture axes' in diag
    # Field findings (from LLM).
    assert 'a02' in diag
    assert 'emotional_arc' in diag
    # Proposed field updates.
    assert 'Proposed field updates' in diag
    assert 'search to recognition and recurrence' in diag
    # Proposed scene insertions.
    assert 'Proposed scene insertions' in diag
    assert 'a02b-pattern-trace' in diag
    # Architecture diagnostic block names the register.
    assert 'atmospheric' in diag


def test_architecture_only_runs_when_csv_present(tmp_path, monkeypatch):
    """No architecture.csv → result['architecture'] is None and no
    architecture CSVs land on disk."""
    _seed_summary(str(tmp_path))
    monkeypatch.chdir(str(tmp_path))
    monkeypatch.setenv('ANTHROPIC_API_KEY', 'test-key')
    fake = _dual_mock_llm(_full_payload(), _act_shape_payload())
    from storyforge import api, scoring_story_power
    monkeypatch.setattr(api, 'invoke_to_file', fake)
    monkeypatch.setattr(scoring_story_power, 'invoke_to_file', fake)
    result = scoring_story_power.score_story_power(str(tmp_path), 'full')
    assert result['architecture'] is None
    assert not os.path.isfile(os.path.join(result['output_dir'],
                                            'per-scene-matrix.csv'))


def test_architecture_llm_failure_does_not_kill_other_results(tmp_path,
                                                                monkeypatch):
    """Architecture LLM raises → architecture extension carries
    status='llm_error', pitch result intact, overall status partial.
    Deterministic field findings are preserved on the extension."""
    _seed_summary(str(tmp_path))
    _seed_architecture(str(tmp_path))
    monkeypatch.chdir(str(tmp_path))
    monkeypatch.setenv('ANTHROPIC_API_KEY', 'test-key')

    def fake(prompt, model, log_file, **kwargs):
        os.makedirs(os.path.dirname(log_file) or '.', exist_ok=True)
        if '-architecture' in log_file:
            raise RuntimeError('simulated architecture API outage')
        payload = (_act_shape_payload() if '-act-shape' in log_file
                   else _full_payload())
        response = {
            'content': [{'type': 'text', 'text': json.dumps(payload)}],
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
    assert result['architecture'] is not None
    assert result['architecture']['status'] == 'llm_error'
    assert result['status'] == 'partial'
    assert os.path.isfile(os.path.join(result['output_dir'], 'scorecard.csv'))
    assert not os.path.isfile(os.path.join(result['output_dir'],
                                            'per-scene-matrix.csv'))


def test_architecture_unparseable_response_tags_status(tmp_path, monkeypatch):
    _seed_summary(str(tmp_path))
    _seed_architecture(str(tmp_path))
    monkeypatch.chdir(str(tmp_path))
    monkeypatch.setenv('ANTHROPIC_API_KEY', 'test-key')

    def fake(prompt, model, log_file, **kwargs):
        os.makedirs(os.path.dirname(log_file) or '.', exist_ok=True)
        if '-architecture' in log_file:
            text = 'no json here'
        else:
            payload = (_act_shape_payload() if '-act-shape' in log_file
                       else _full_payload())
            text = json.dumps(payload)
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
    assert result['architecture'] is not None
    assert result['architecture']['status'] == 'unparseable'


def test_architecture_partial_per_scene_tags_partial(tmp_path, monkeypatch):
    _seed_summary(str(tmp_path))
    _seed_architecture(str(tmp_path))
    monkeypatch.chdir(str(tmp_path))
    monkeypatch.setenv('ANTHROPIC_API_KEY', 'test-key')
    arch_payload = _architecture_payload()
    # Keep one a02 score; drop the other to leave a non-empty but partial row.
    for row in arch_payload['per_scene']:
        if row['scene_id'] == 'a02':
            row['scores'] = row['scores'][:1]
    fake = _quad_mock_llm(_full_payload(), _act_shape_payload(),
                            _spine_payload(), arch_payload)
    from storyforge import api, scoring_story_power
    monkeypatch.setattr(api, 'invoke_to_file', fake)
    monkeypatch.setattr(scoring_story_power, 'invoke_to_file', fake)
    result = scoring_story_power.score_story_power(str(tmp_path), 'full')
    assert result['architecture']['status'] == 'partial'
    assert result['status'] == 'partial'


def test_empty_per_scene_column_refuses_to_write_matrix(tmp_path, monkeypatch,
                                                          capsys):
    """If any scene has zero valid scores, refuse to write the matrix —
    mirrors spine/act-shape floor philosophy."""
    _seed_summary(str(tmp_path))
    _seed_architecture(str(tmp_path))
    monkeypatch.chdir(str(tmp_path))
    monkeypatch.setenv('ANTHROPIC_API_KEY', 'test-key')
    arch_payload = _architecture_payload()
    # Wipe a03's scores entirely.
    for row in arch_payload['per_scene']:
        if row['scene_id'] == 'a03':
            row['scores'] = []
    fake = _quad_mock_llm(_full_payload(), _act_shape_payload(),
                            _spine_payload(), arch_payload)
    from storyforge import api, scoring_story_power
    monkeypatch.setattr(api, 'invoke_to_file', fake)
    monkeypatch.setattr(scoring_story_power, 'invoke_to_file', fake)
    result = scoring_story_power.score_story_power(str(tmp_path), 'full')
    out = capsys.readouterr().out
    assert 'refusing to write per-scene-matrix.csv' in out
    assert 'a03' in out
    assert not os.path.isfile(os.path.join(result['output_dir'],
                                            'per-scene-matrix.csv'))


def test_architecture_coach_mode_appends_to_brief(tmp_path, monkeypatch):
    _seed_summary(str(tmp_path))
    _seed_architecture(str(tmp_path))
    monkeypatch.chdir(str(tmp_path))
    monkeypatch.setenv('ANTHROPIC_API_KEY', 'test-key')
    fake = _quad_mock_llm(_full_payload(), _act_shape_payload(),
                            _spine_payload(), _architecture_payload())
    from storyforge import api, scoring_story_power
    monkeypatch.setattr(api, 'invoke_to_file', fake)
    monkeypatch.setattr(scoring_story_power, 'invoke_to_file', fake)
    result = scoring_story_power.score_story_power(str(tmp_path), 'coach')
    brief = open(os.path.join(result['output_dir'],
                                'coaching-brief.md')).read()
    assert 'Architecture extension' in brief
    assert 'Per-scene matrix' in brief
    assert 'Proposed field updates' in brief
    # No separate architecture CSVs in coach mode.
    assert not os.path.isfile(os.path.join(result['output_dir'],
                                            'per-scene-matrix.csv'))


def test_strict_mode_with_architecture_extends_checklist(tmp_path, monkeypatch):
    _seed_summary(str(tmp_path))
    _seed_architecture(str(tmp_path))
    monkeypatch.chdir(str(tmp_path))
    from storyforge import api, scoring_story_power

    def boom(*a, **k):
        raise AssertionError('LLM must not be called in strict')
    monkeypatch.setattr(api, 'invoke_to_file', boom)
    monkeypatch.setattr(scoring_story_power, 'invoke_to_file', boom)
    result = scoring_story_power.score_story_power(str(tmp_path), 'strict')
    text = open(os.path.join(result['output_dir'],
                              'self-scoring-checklist.md')).read()
    assert 'Architecture tier' in text
    for sid in ('a01', 'a02', 'a03', 'a04'):
        assert sid in text
    from storyforge.scoring_story_power import ARCHITECTURE_AXES
    for axis in ARCHITECTURE_AXES:
        assert axis.name in text


def test_deterministic_findings_preserved_on_llm_failure(tmp_path, monkeypatch):
    """Even when the LLM call fails, the deterministic field findings
    from the pre-pass survive on the extension."""
    _seed_summary(str(tmp_path))
    ref = os.path.join(str(tmp_path), 'reference')
    os.makedirs(ref, exist_ok=True)
    # Architecture with a deterministically-flaggable scene (revelation
    # turning_point but no recognition verbs in the summary).
    headers = ('id|seq|title|spine_event|action_sequel|emotional_arc|'
               'value_at_stake|value_shift|turning_point|summary')
    with open(os.path.join(ref, 'architecture.csv'), 'w') as f:
        f.write(headers + '\n')
        f.write('a01|1|T|ev-1|sequel|tension|memory|0/-|revelation|'
                'They walk through the corridor and stop.\n')
    yml = os.path.join(str(tmp_path), 'storyforge.yaml')
    if os.path.isfile(yml):
        with open(yml, 'a') as f:
            f.write('  register: atmospheric\n')
    monkeypatch.chdir(str(tmp_path))
    monkeypatch.setenv('ANTHROPIC_API_KEY', 'test-key')

    def fake(prompt, model, log_file, **kwargs):
        os.makedirs(os.path.dirname(log_file) or '.', exist_ok=True)
        if '-architecture' in log_file:
            raise RuntimeError('llm down')
        payload = (_act_shape_payload() if '-act-shape' in log_file
                   else _full_payload())
        response = {
            'content': [{'type': 'text', 'text': json.dumps(payload)}],
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
    ext = result['architecture']
    assert ext is not None
    assert ext['status'] == 'llm_error'
    # Deterministic finding survives the LLM failure.
    assert any(f['field'] == 'turning_point' for f in ext['field_findings'])


def test_parse_response_architecture_handles_fenced_json():
    from storyforge.scoring_story_power import _parse_response_architecture
    payload = json.dumps(_architecture_payload())
    text = f'```json\n{payload}\n```\n'
    parsed = _parse_response_architecture(text)
    assert parsed is not None
    assert isinstance(parsed['per_scene'], list)


def test_parse_response_architecture_warns_when_list_missing(capsys):
    from storyforge.scoring_story_power import _parse_response_architecture
    bad = json.dumps({'per_scene': []})  # whole_architecture missing
    parsed = _parse_response_architecture(bad)
    assert parsed is None
    out = capsys.readouterr().out
    assert 'whole_architecture' in out


def test_extract_per_scene_scores_drops_malformed(capsys):
    from storyforge.scoring_story_power import _extract_per_scene_scores
    parsed = {
        'per_scene': [
            'not a dict',
            {'scene_id': 'unknown', 'scores': []},
            {'scene_id': 'a01', 'scores': [
                'not a dict',
                {'axis': 'made_up', 'score': 8},
                {'axis': 'field_coherence', 'score': 'high'},
                {'axis': 'spine_event_service', 'score': 99},
                {'axis': 'spine_event_service', 'score': 8},
            ]},
        ],
    }
    out = _extract_per_scene_scores(parsed, ['a01'])
    assert out == {'a01': {'spine_event_service': 8}}
    info = capsys.readouterr().out
    assert 'per-scene extraction dropped' in info


def test_extract_whole_architecture_scores_drops_malformed(capsys):
    from storyforge.scoring_story_power import _extract_whole_architecture_scores
    parsed = {
        'whole_architecture': [
            'not a dict',
            {'axis': 'made_up_axis', 'score': 7},
            {'axis': 'cumulative_arc_gradient', 'score': 'mid'},
            {'axis': 'cumulative_arc_gradient', 'score': 0},
            {'axis': 'cumulative_arc_gradient', 'score': 7},
        ],
    }
    out = _extract_whole_architecture_scores(parsed)
    assert out == {'cumulative_arc_gradient': 7}
    info = capsys.readouterr().out
    assert 'whole-architecture extraction dropped' in info


def test_append_architecture_diagnostic_warns_when_md_missing(tmp_path, capsys):
    from storyforge.scoring_story_power import (
        _append_architecture_diagnostic, SceneRow,
    )
    scenes = [SceneRow('a01', 'T', 's', 'ev-1', 'sequel', '', '', '', '')]
    _append_architecture_diagnostic(str(tmp_path), scenes, {'a01': {}}, {},
                                      [], [], [], {}, 'balanced')
    out = capsys.readouterr().out
    assert 'architecture diagnostic could not be appended' in out


def test_quad_mock_llm_routes_to_all_four_payloads(tmp_path, monkeypatch):
    """Defensive: assert the quad mock is actually routing to
    architecture, not silently returning pitch when the suffix key
    drifts."""
    _seed_summary(str(tmp_path))
    _seed_spine(str(tmp_path))
    _seed_architecture(str(tmp_path))
    monkeypatch.chdir(str(tmp_path))
    monkeypatch.setenv('ANTHROPIC_API_KEY', 'test-key')

    seen: dict[str, int] = {'pitch': 0, 'act_shape': 0, 'spine': 0,
                              'architecture': 0}

    def fake(prompt, model, log_file, **kwargs):
        os.makedirs(os.path.dirname(log_file) or '.', exist_ok=True)
        if '-architecture' in log_file:
            seen['architecture'] += 1
            payload = _architecture_payload()
        elif '-spine' in log_file:
            seen['spine'] += 1
            payload = _spine_payload()
        elif '-act-shape' in log_file:
            seen['act_shape'] += 1
            payload = _act_shape_payload()
        else:
            seen['pitch'] += 1
            payload = _full_payload()
        response = {
            'content': [{'type': 'text', 'text': json.dumps(payload)}],
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
    scoring_story_power.score_story_power(str(tmp_path), 'full')
    assert seen == {'pitch': 1, 'act_shape': 1, 'spine': 1, 'architecture': 1}

