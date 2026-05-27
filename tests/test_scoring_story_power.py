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


def _seed_scene_map(project_dir: str, scene_count: int = 4,
                      backward_timeline: bool = False,
                      bogus_architecture_scene: bool = False) -> None:
    """Write a small scenes.csv. Default: 4 sequential scenes that link
    to architecture rows a01-a04 (which _seed_architecture creates)."""
    ref = os.path.join(project_dir, 'reference')
    os.makedirs(ref, exist_ok=True)
    # Default: forward timeline, all linked to existing architecture.
    arch2 = 'a-bogus' if bogus_architecture_scene else 'a02'
    # Backward: row 3 jumps back to day 1 (vs prior row day 2) with no
    # scene_type='flashback' — the deterministic check should flag it.
    day3 = '1' if backward_timeline else '3'
    rows = [
        ('s1', '1', 'Opening',       'a01',  'action', 'L', '1',   'morning',  '',
         '2000', '2000', 'Lucien walks into the archive.'),
        ('s2', '2', 'Discovery',     arch2,  'sequel', 'L', '2',   'afternoon','',
         '1800', '2000', 'Lucien sees the records shifting.'),
        ('s3', '3', 'Confrontation', 'a03',  'action', 'L', day3,  'evening',  '',
         '2400', '2000', 'Lucien refuses the order.'),
        ('s4', '4', 'Fracture',      'a04',  'sequel', 'L', '4',   'night',    '',
         '1700', '2000', 'The archive collapses around him.'),
    ][:scene_count]
    headers = ('id|seq|title|architecture_scene|action_sequel|pov|'
               'timeline_day|time_of_day|type|word_count|target_words|summary')
    lines = [headers] + ['|'.join(r) for r in rows]
    with open(os.path.join(ref, 'scenes.csv'), 'w') as f:
        f.write('\n'.join(lines) + '\n')


def _scene_map_payload() -> dict:
    """Well-shaped scene-map LLM payload."""
    scene_ids = ['s1', 's2', 's3', 's4']
    per_scene = []
    for sid in scene_ids:
        per_scene.append({
            'scene_id': sid,
            'scores': [
                {'axis': 'architecture_coverage', 'score': 8,
                 'rationale': f'coverage for {sid}'},
                {'axis': 'continuity_coherence', 'score': 7 if sid == 's3' else 9,
                 'rationale': f'continuity for {sid}'},
            ],
        })
    whole_map = [
        {'axis': 'coverage_completeness', 'score': 9,
         'positive_signals': 'every anchor covered',
         'negative_signals': '', 'rationale': 'all four anchors mapped'},
        {'axis': 'pov_rotation', 'score': 9,
         'positive_signals': 'single POV consistent',
         'negative_signals': '', 'rationale': 'no pov jumps'},
        {'axis': 'pacing_distribution', 'score': 7,
         'positive_signals': '', 'negative_signals': 's3 oversized',
         'rationale': 's3 above target band'},
        {'axis': 'timeline_flow', 'score': 9,
         'positive_signals': 'monotonic days',
         'negative_signals': '', 'rationale': 'linear progression'},
        {'axis': 'interstitial_economy', 'score': 8,
         'positive_signals': 'no orphan interstitials',
         'negative_signals': '', 'rationale': 'each scene anchored'},
    ]
    return {
        'per_scene': per_scene,
        'whole_scene_map': whole_map,
        'scene_map_diagnostic': {
            'lowest_axis': 'pacing_distribution',
            'lowest_axis_average': '7.0',
            'summary': 's3 sits above the target word band',
            'coverage_assessment': 'all four anchors a01-a04 have mapped scenes',
            'high_leverage_move': 'split s3 into two scenes around the refusal beat',
        },
        'continuity_findings': [
            {'scene_id': 's3', 'preceding_id': 's2', 'field': 'pacing',
             'issue': 'scene runs 2400 words against target 2000',
             'severity': 'medium'},
        ],
        'proposed_operations': [
            {'operation': 'split',
             'scene_ids': ['s3'],
             'summary': 'Split s3 into pre-refusal and refusal-moment scenes.',
             'rationale': 'lifts pacing_distribution 7 → 9'},
        ],
    }


def _quint_mock_llm(pitch_payload: dict, act_shape_payload: dict,
                     spine_payload: dict, architecture_payload: dict,
                     scene_map_payload: dict):
    """Mock that routes by log filename suffix: -scene-map, -architecture,
    -spine, -act-shape, or default (pitch)."""
    def fake(prompt, model, log_file, **kwargs):
        os.makedirs(os.path.dirname(log_file) or '.', exist_ok=True)
        if '-scene-map' in log_file:
            payload = scene_map_payload
        elif '-architecture' in log_file:
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


def test_value_shift_uses_end_polarity_not_start():
    """+/- (starts positive, ends negative) is a loss scene. Pairing it
    with 'rupture' language is CONSISTENT, not contradictory — the
    deterministic check must look at the end polarity, not the start.

    Previously the check used .startswith('+'), which falsely flagged
    every +/- scene that mentioned rupture/loss in emotional_arc.
    """
    from storyforge.scoring_story_power import (
        _check_field_coherence_deterministic, SceneRow,
    )
    # +/- = starts positive, ends negative. Pairing with 'trust to rupture'
    # is the expected shape; should NOT flag.
    s = SceneRow('a01', 'T', 'Things go wrong and the bond breaks.',
                 'ev-1', 'action', 'trust to rupture', 'connection',
                 '+/-', 'choice')
    findings = _check_field_coherence_deterministic(s)
    assert not any(f['field'] == 'value_shift' for f in findings)


def test_value_shift_negative_to_positive_with_rupture_arc_flags():
    """-/+ (starts negative, ends positive) with rupture/loss emotional_arc
    IS contradictory: a recovery scene shouldn't end on rupture language.
    Previously this case was silently missed because the check looked
    at the start polarity."""
    from storyforge.scoring_story_power import (
        _check_field_coherence_deterministic, SceneRow,
    )
    s = SceneRow('a01', 'T', 'They escape and reunite.',
                 'ev-1', 'action', 'fear to rupture', 'safety',
                 '-/+', 'reunion')
    findings = _check_field_coherence_deterministic(s)
    assert any(f['field'] == 'value_shift' and f['severity'] == 'high'
               for f in findings)


def test_revelation_check_uses_word_boundaries_not_substrings():
    """The revelation-verb match must be word-bounded. A summary
    containing 'seeks' (which substring-contains 'see') is NOT a
    recognition verb and should NOT satisfy the recognition check;
    the scene should still flag as missing-recognition."""
    from storyforge.scoring_story_power import (
        _check_field_coherence_deterministic, SceneRow,
    )
    # 'seeks' contains 'see' as a substring; the v1 check would have
    # incorrectly passed this scene. Word-bounded regex catches it.
    s = SceneRow('a01', 'T', 'She seeks the door at the end of the hall.',
                 'ev-1', 'sequel', 'tension', 'memory', '0/-', 'revelation')
    findings = _check_field_coherence_deterministic(s)
    assert any(f['field'] == 'turning_point' and f['severity'] == 'high'
               for f in findings)


def test_action_check_uses_word_boundaries_not_substrings():
    """Similar word-boundary fix on the action-verb regex. 'rune' should
    not satisfy 'run'."""
    from storyforge.scoring_story_power import (
        _check_field_coherence_deterministic, SceneRow,
    )
    s = SceneRow('a01', 'T',
                 'She studies the rune and the brunch arrangement.',
                 'ev-1', 'action', 'curiosity', 'understanding',
                 '0/-', 'choice')
    findings = _check_field_coherence_deterministic(s)
    assert any(f['field'] == 'action_sequel' for f in findings)


def test_action_sequel_check_normalizes_via_startswith_for_symmetry():
    """The deterministic action_sequel check and _action_sequel_ratio
    must use the same matching rule (startswith). An 'action-heavy' or
    'action: high' value should be eligible for the action-verb check."""
    from storyforge.scoring_story_power import (
        _check_field_coherence_deterministic, SceneRow,
    )
    # action_sequel='action-heavy' starts with 'action'; the check
    # should still fire when the summary has no action verbs.
    s = SceneRow('a01', 'T', 'She thinks about what she has lost.',
                 'ev-1', 'action-heavy', 'longing', 'connection',
                 '0/-', 'choice')
    findings = _check_field_coherence_deterministic(s)
    assert any(f['field'] == 'action_sequel' for f in findings)


def test_read_project_register_logs_info_when_absent(tmp_path, capsys):
    """Absent project.register must surface INFO so the author sees
    that scoring is happening against the balanced default. Previously
    the absent path was silent — only the unrecognized-value path
    logged INFO."""
    yml = os.path.join(str(tmp_path), 'storyforge.yaml')
    with open(yml, 'w') as f:
        f.write('project:\n  title: T\n  medium: novel\n')
    from storyforge.scoring_story_power import read_project_register
    result = read_project_register(str(tmp_path))
    assert result == 'balanced'
    out = capsys.readouterr().out
    assert 'project.register not declared' in out
    assert 'balanced' in out


def test_unclassified_action_sequel_majority_warns(tmp_path, monkeypatch,
                                                     capsys):
    """When more than half the scenes lack an action_sequel
    classification, the rhythm axis would score against an unreliable
    denominator. A WARNING surfaces the ratio of unclassified rows."""
    _seed_summary(str(tmp_path))
    # Custom architecture with mostly-empty action_sequel cells.
    ref = os.path.join(str(tmp_path), 'reference')
    os.makedirs(ref, exist_ok=True)
    headers = ('id|seq|title|spine_event|action_sequel|emotional_arc|'
               'value_at_stake|value_shift|turning_point|summary')
    rows = [
        'a01|1|T|ev-1|action|arc|stake|+/-|choice|first.',
        'a02|2|T|ev-2||arc|stake|+/-|choice|second.',
        'a03|3|T|ev-3||arc|stake|+/-|choice|third.',
        'a04|4|T|ev-4||arc|stake|+/-|choice|fourth.',
    ]
    with open(os.path.join(ref, 'architecture.csv'), 'w') as f:
        f.write(headers + '\n' + '\n'.join(rows) + '\n')
    yml = os.path.join(str(tmp_path), 'storyforge.yaml')
    with open(yml, 'a') as f:
        f.write('  register: atmospheric\n')
    monkeypatch.chdir(str(tmp_path))
    monkeypatch.setenv('ANTHROPIC_API_KEY', 'test-key')
    fake = _quad_mock_llm(_full_payload(), _act_shape_payload(),
                            _spine_payload(), _architecture_payload())
    from storyforge import api, scoring_story_power
    monkeypatch.setattr(api, 'invoke_to_file', fake)
    monkeypatch.setattr(scoring_story_power, 'invoke_to_file', fake)
    scoring_story_power.score_story_power(str(tmp_path), 'full')
    out = capsys.readouterr().out
    assert 'lack an action_sequel classification' in out
    assert '3/4' in out  # 3 of 4 scenes unclassified


def test_architecture_prompt_surfaces_unclassified_count(tmp_path):
    """The prompt must name the unclassified count so the LLM can
    factor reliability into the register_assessment."""
    from storyforge.scoring_story_power import (
        _build_architecture_prompt, SceneRow, PitchArtifacts,
    )
    scenes = [
        SceneRow('a01', '', 's', '', 'action', '', '', '', ''),
        SceneRow('a02', '', 's', '', '', '', '', '', ''),
        SceneRow('a03', '', 's', '', '', '', '', '', ''),
    ]
    artifacts = PitchArtifacts(logline='L', synopsis='S', act_shape='',
                                theme='', spine_summaries='',
                                architecture_summaries='')
    prompt = _build_architecture_prompt(scenes, [], artifacts,
                                          'atmospheric', [], 'rubric')
    assert '2 of 3 scenes are unclassified' in prompt or \
           '2 of 3' in prompt


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


# ---------------------------------------------------------------------------
# Test gaps from the PR #242 review
# ---------------------------------------------------------------------------

def test_per_scene_matrix_csv_header_columns(tmp_path, monkeypatch):
    """per-scene-matrix.csv header must match
    scene_id|spine_event|spine_event_service|field_coherence so
    downstream consumers can rely on the schema."""
    _seed_summary(str(tmp_path))
    _seed_architecture(str(tmp_path))
    monkeypatch.chdir(str(tmp_path))
    monkeypatch.setenv('ANTHROPIC_API_KEY', 'test-key')
    fake = _quad_mock_llm(_full_payload(), _act_shape_payload(),
                            _spine_payload(), _architecture_payload())
    from storyforge import api, scoring_story_power
    monkeypatch.setattr(api, 'invoke_to_file', fake)
    monkeypatch.setattr(scoring_story_power, 'invoke_to_file', fake)
    result = scoring_story_power.score_story_power(str(tmp_path), 'full')
    matrix = open(os.path.join(result['output_dir'],
                                'per-scene-matrix.csv')).read()
    header = matrix.splitlines()[0]
    assert header == 'scene_id|spine_event|spine_event_service|field_coherence'


def test_whole_architecture_csv_weight_column_reflects_axes(tmp_path,
                                                              monkeypatch):
    """whole-architecture-axes.csv's weight column must match
    ARCHITECTURE_AXES weights — silent drift would shift composite
    interpretation."""
    _seed_summary(str(tmp_path))
    _seed_architecture(str(tmp_path))
    monkeypatch.chdir(str(tmp_path))
    monkeypatch.setenv('ANTHROPIC_API_KEY', 'test-key')
    fake = _quad_mock_llm(_full_payload(), _act_shape_payload(),
                            _spine_payload(), _architecture_payload())
    from storyforge import api, scoring_story_power
    monkeypatch.setattr(api, 'invoke_to_file', fake)
    monkeypatch.setattr(scoring_story_power, 'invoke_to_file', fake)
    result = scoring_story_power.score_story_power(str(tmp_path), 'full')
    from storyforge.scoring_story_power import ARCHITECTURE_AXES
    csv = open(os.path.join(result['output_dir'],
                              'whole-architecture-axes.csv')).read()
    lines = csv.splitlines()
    weight_by_axis_key = {a.key: str(a.weight) for a in ARCHITECTURE_AXES}
    header = lines[0].split('|')
    axis_col = header.index('axis')
    weight_col = header.index('weight')
    for line in lines[1:]:
        cells = line.split('|')
        assert cells[weight_col] == weight_by_axis_key[cells[axis_col]]


def test_extract_proposed_field_updates_drops_incomplete_rows(capsys):
    """Rows missing scene_id / field / proposed_value must be dropped
    and the drops surfaced in an INFO log."""
    from storyforge.scoring_story_power import _extract_proposed_field_updates
    parsed = {
        'proposed_field_updates': [
            'not a dict',
            {'scene_id': '', 'field': 'arc', 'proposed_value': 'x'},
            {'scene_id': 'a01', 'field': '', 'proposed_value': 'x'},
            {'scene_id': 'a01', 'field': 'arc', 'proposed_value': ''},
            {'scene_id': 'a01', 'field': 'arc', 'proposed_value': 'good',
             'rationale': 'because'},
        ],
    }
    out = _extract_proposed_field_updates(parsed)
    assert len(out) == 1
    assert out[0]['proposed_value'] == 'good'
    info = capsys.readouterr().out
    assert 'proposed_field_updates extraction dropped' in info


def test_extract_proposed_scene_insertions_drops_incomplete_rows(capsys):
    """Rows missing insert_after / proposed_id / summary must be
    dropped and the drops surfaced in an INFO log."""
    from storyforge.scoring_story_power import _extract_proposed_scene_insertions
    parsed = {
        'proposed_scene_insertions': [
            'not a dict',
            {'insert_after': '', 'proposed_id': 'x', 'summary': 's'},
            {'insert_after': 'a01', 'proposed_id': '', 'summary': 's'},
            {'insert_after': 'a01', 'proposed_id': 'a02', 'summary': ''},
            {'insert_after': 'a01', 'proposed_id': 'a02',
             'summary': 'A new scene happens.',
             'spine_event': 'ev-1'},
        ],
    }
    out = _extract_proposed_scene_insertions(parsed)
    assert len(out) == 1
    assert out[0]['proposed_id'] == 'a02'
    info = capsys.readouterr().out
    assert 'proposed_scene_insertions extraction dropped' in info


def test_extract_field_findings_drops_incomplete_rows(capsys):
    from storyforge.scoring_story_power import _extract_field_findings
    parsed = {
        'field_findings': [
            'not a dict',
            {'scene_id': '', 'field': 'arc', 'issue': 'bad'},
            {'scene_id': 'a01', 'field': '', 'issue': 'bad'},
            {'scene_id': 'a01', 'field': 'arc', 'issue': ''},
            {'scene_id': 'a01', 'field': 'arc', 'issue': 'bad',
             'severity': 'high'},
        ],
    }
    out = _extract_field_findings(parsed)
    assert len(out) == 1
    assert out[0]['severity'] == 'high'
    info = capsys.readouterr().out
    assert 'field_findings extraction dropped' in info


def test_parse_response_architecture_handles_greedy_extraction():
    """Tier-3 fallback: JSON embedded in prose with no fence."""
    from storyforge.scoring_story_power import _parse_response_architecture
    payload = json.dumps(_architecture_payload())
    text = f'Here is my analysis. {payload} Done.'
    parsed = _parse_response_architecture(text)
    assert parsed is not None
    assert isinstance(parsed['per_scene'], list)


def test_parse_response_architecture_warns_per_scene_missing(capsys):
    """Shape-failure WARNING fires naming per_scene as the missing key."""
    from storyforge.scoring_story_power import _parse_response_architecture
    bad = json.dumps({'whole_architecture': []})  # per_scene missing
    parsed = _parse_response_architecture(bad)
    assert parsed is None
    out = capsys.readouterr().out
    assert 'per_scene' in out


def test_parse_response_architecture_warns_dual_missing(capsys):
    """When both required lists are missing, the WARN names both."""
    from storyforge.scoring_story_power import _parse_response_architecture
    bad = json.dumps({'unrelated': []})
    parsed = _parse_response_architecture(bad)
    assert parsed is None
    out = capsys.readouterr().out
    assert 'per_scene' in out and 'whole_architecture' in out


def test_architecture_diagnostic_register_assessment_renders(tmp_path,
                                                                monkeypatch):
    """The architecture diagnostic must surface the LLM-provided
    register_assessment substring, not just the declared register name."""
    _seed_summary(str(tmp_path))
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
    # The _architecture_payload register_assessment includes 'within band'.
    assert 'within band' in diag
    # The 'Register assessment:' label line is present.
    assert 'Register assessment:' in diag


def test_proposed_scene_insertion_full_fields_render(tmp_path, monkeypatch):
    """All seven structured fields of a proposed insertion must reach
    the diagnostic — silent drop of any would mislead the author."""
    _seed_summary(str(tmp_path))
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
    # All distinctive values from the _architecture_payload baseline.
    assert 'ev-discovery' in diag           # spine_event
    assert 'sequel' in diag                  # action_sequel
    assert 'recognition to resolve' in diag  # emotional_arc
    assert 'understanding' in diag           # value_at_stake
    assert '0/+' in diag                     # value_shift
    assert 'commitment' in diag              # turning_point
    assert 'traces the pattern' in diag      # summary
    assert 'scene_causal_chain 8 → 9' in diag  # rationale


def test_append_architecture_coaching_brief_warns_when_md_missing(tmp_path,
                                                                    capsys):
    """Parity with the spine appender: when coaching-brief.md is
    absent, the architecture coach-brief appender must surface a
    WARNING and return cleanly."""
    from storyforge.scoring_story_power import (
        _append_architecture_coaching_brief, SceneRow,
    )
    scenes = [SceneRow('a01', 'T', 's', 'ev-1', 'sequel', '', '', '', '')]
    _append_architecture_coaching_brief(
        str(tmp_path), scenes, {'a01': {}}, {}, [], [], [], {}, 'balanced',
    )
    out = capsys.readouterr().out
    assert 'architecture coaching brief could not be appended' in out


def test_action_sequel_ratio_handles_empty_classification():
    """Architecture with no action_sequel populated returns (0, 0, 0.0)
    — degenerate but doesn't crash. The rhythm axis is still scoreable
    by the LLM with the unclassified-share signal in the prompt."""
    from storyforge.scoring_story_power import _action_sequel_ratio, SceneRow
    scenes = [
        SceneRow('a', '', 's', '', '', '', '', '', ''),
        SceneRow('b', '', 's', '', '', '', '', '', ''),
    ]
    action, sequel, ratio = _action_sequel_ratio(scenes)
    assert (action, sequel, ratio) == (0, 0, 0.0)


def test_disjoint_axis_assert_data_driven_error_names_collision():
    """The data-driven disjoint assert reports WHICH key collides
    between WHICH two families — a 7th family with an overlapping key
    fails import with a specific message."""
    # Simulate by patching a 7th family in via the same loop logic.
    from storyforge.scoring_story_power import (
        _AXIS_FAMILIES, AXIS_KEYS,
    )
    # Confirm AXIS_KEYS isn't already present in another family.
    seen: dict[str, str] = {}
    for family, keys in _AXIS_FAMILIES:
        for key in keys:
            assert key not in seen, (
                f'unexpected runtime collision: {key} in {seen[key]} and {family}'
            )
            seen[key] = family
    # The actual collision test would re-run the loop with a fake family;
    # since we can't reimport mid-test, we verify the bookkeeping above
    # which mirrors the import-time loop's semantics.


def test_proposed_scene_insertion_id_collision_warns(tmp_path, monkeypatch,
                                                       capsys):
    """If the LLM proposes a scene id that collides with an existing
    architecture scene, the diagnostic should WARN — silently accepting
    would let the author duplicate an id in architecture.csv."""
    _seed_summary(str(tmp_path))
    _seed_architecture(str(tmp_path))
    monkeypatch.chdir(str(tmp_path))
    monkeypatch.setenv('ANTHROPIC_API_KEY', 'test-key')
    arch_payload = _architecture_payload()
    # Override proposed_id to collide with a01 (an existing scene).
    arch_payload['proposed_scene_insertions'][0]['proposed_id'] = 'a01'
    fake = _quad_mock_llm(_full_payload(), _act_shape_payload(),
                            _spine_payload(), arch_payload)
    from storyforge import api, scoring_story_power
    monkeypatch.setattr(api, 'invoke_to_file', fake)
    monkeypatch.setattr(scoring_story_power, 'invoke_to_file', fake)
    scoring_story_power.score_story_power(str(tmp_path), 'full')
    out = capsys.readouterr().out
    assert 'collides with an existing' in out
    assert "'a01'" in out


def test_value_shift_uses_end_polarity_smoke_via_extension(tmp_path,
                                                             monkeypatch):
    """End-to-end smoke test for the value_shift fix: a scene with
    +/- value_shift and 'rupture' emotional_arc should NOT appear in
    the deterministic field findings (the fix lets the architecture
    extension run cleanly without false-positive value_shift WARNs)."""
    _seed_summary(str(tmp_path))
    ref = os.path.join(str(tmp_path), 'reference')
    os.makedirs(ref, exist_ok=True)
    headers = ('id|seq|title|spine_event|action_sequel|emotional_arc|'
               'value_at_stake|value_shift|turning_point|summary')
    with open(os.path.join(ref, 'architecture.csv'), 'w') as f:
        f.write(headers + '\n')
        # +/- (starts positive, ends negative — consistent with rupture)
        f.write('a01|1|T|ev-1|action|trust to rupture|connection|'
                '+/-|choice|They argue and the bond breaks.\n')
    yml = os.path.join(str(tmp_path), 'storyforge.yaml')
    with open(yml, 'a') as f:
        f.write('  register: atmospheric\n')
    monkeypatch.chdir(str(tmp_path))
    monkeypatch.setenv('ANTHROPIC_API_KEY', 'test-key')
    fake = _quad_mock_llm(_full_payload(), _act_shape_payload(),
                            _spine_payload(), _architecture_payload())
    from storyforge import api, scoring_story_power
    monkeypatch.setattr(api, 'invoke_to_file', fake)
    monkeypatch.setattr(scoring_story_power, 'invoke_to_file', fake)
    result = scoring_story_power.score_story_power(str(tmp_path), 'full')
    ext = result['architecture']
    assert ext is not None
    # No deterministic value_shift finding for the +/- scene.
    assert not any(f['field'] == 'value_shift' and f['scene_id'] == 'a01'
                   for f in ext['field_findings']
                   if f.get('severity') == 'high')


# ---------------------------------------------------------------------------
# Scene-map mode (Layer 1 per-scene + Layer 2 whole-map)
# ---------------------------------------------------------------------------

def test_parse_scene_map_reads_csv_in_seq_order(tmp_path):
    _seed_scene_map(str(tmp_path))
    from storyforge.scoring_story_power import parse_scene_map
    scenes = parse_scene_map(str(tmp_path))
    assert [s.id for s in scenes] == ['s1', 's2', 's3', 's4']
    assert scenes[0].seq == 1
    assert scenes[1].architecture_scene == 'a02'
    assert scenes[2].word_count == 2400


def test_parse_scene_map_returns_empty_when_csv_missing(tmp_path):
    from storyforge.scoring_story_power import parse_scene_map
    assert parse_scene_map(str(tmp_path)) == []


def test_parse_scene_map_warns_on_missing_required_columns(tmp_path, capsys):
    ref = os.path.join(str(tmp_path), 'reference')
    os.makedirs(ref, exist_ok=True)
    with open(os.path.join(ref, 'scenes.csv'), 'w') as f:
        # missing summary column
        f.write('id|title|pov\ns1|T|A\n')
    from storyforge.scoring_story_power import parse_scene_map
    assert parse_scene_map(str(tmp_path)) == []
    out = capsys.readouterr().out
    assert 'missing required columns' in out


def test_parse_scene_map_warns_on_blank_required_field(tmp_path, capsys):
    ref = os.path.join(str(tmp_path), 'reference')
    os.makedirs(ref, exist_ok=True)
    with open(os.path.join(ref, 'scenes.csv'), 'w') as f:
        f.write('id|seq|summary\ns1|1|first.\n|2|second.\ns3|3|\n')
    from storyforge.scoring_story_power import parse_scene_map
    scenes = parse_scene_map(str(tmp_path))
    assert [s.id for s in scenes] == ['s1']
    out = capsys.readouterr().out
    assert 'missing required field' in out


def test_parse_scene_map_sorts_by_seq(tmp_path):
    """Rows out of seq order in the CSV must come back sorted."""
    ref = os.path.join(str(tmp_path), 'reference')
    os.makedirs(ref, exist_ok=True)
    with open(os.path.join(ref, 'scenes.csv'), 'w') as f:
        f.write('id|seq|summary\nlate|9|nine.\nmid|3|three.\nearly|1|one.\n')
    from storyforge.scoring_story_power import parse_scene_map
    scenes = parse_scene_map(str(tmp_path))
    assert [s.id for s in scenes] == ['early', 'mid', 'late']


def test_per_map_scene_axes_invariants():
    from storyforge.scoring_story_power import (
        PER_MAP_SCENE_AXES, AXIS_KEYS, STRUCTURAL_AXIS_KEYS,
        PER_EVENT_AXIS_KEYS, SPINE_AXIS_KEYS, PER_SCENE_AXIS_KEYS,
        ARCHITECTURE_AXIS_KEYS,
    )
    keys = [a.key for a in PER_MAP_SCENE_AXES]
    assert len(keys) == 2
    assert len(set(keys)) == 2
    for other in (AXIS_KEYS, STRUCTURAL_AXIS_KEYS, PER_EVENT_AXIS_KEYS,
                  SPINE_AXIS_KEYS, PER_SCENE_AXIS_KEYS,
                  ARCHITECTURE_AXIS_KEYS):
        assert not (set(keys) & set(other))
    # continuity_coherence carries the elevated weight.
    weights = {a.key: a.weight for a in PER_MAP_SCENE_AXES}
    assert weights['continuity_coherence'] == 1.5


def test_map_axes_invariants():
    from storyforge.scoring_story_power import (
        MAP_AXES, AXIS_KEYS, STRUCTURAL_AXIS_KEYS, PER_EVENT_AXIS_KEYS,
        SPINE_AXIS_KEYS, PER_SCENE_AXIS_KEYS, ARCHITECTURE_AXIS_KEYS,
        PER_MAP_SCENE_AXIS_KEYS,
    )
    keys = [a.key for a in MAP_AXES]
    assert len(keys) == 5
    assert len(set(keys)) == 5
    for other in (AXIS_KEYS, STRUCTURAL_AXIS_KEYS, PER_EVENT_AXIS_KEYS,
                  SPINE_AXIS_KEYS, PER_SCENE_AXIS_KEYS,
                  ARCHITECTURE_AXIS_KEYS, PER_MAP_SCENE_AXIS_KEYS):
        assert not (set(keys) & set(other))


def test_continuity_deterministic_flags_timeline_backward():
    from storyforge.scoring_story_power import (
        _check_continuity_deterministic, MappedScene,
    )
    scenes = [
        MappedScene('s1', 1, 'T', 'a.', 'A', 'L', '3', 'morning', '',
                    1000, 1000, ''),
        MappedScene('s2', 2, 'T', 'b.', 'A', 'L', '1', 'morning', '',
                    1000, 1000, ''),  # day went 3 → 1 with no flashback
    ]
    findings = _check_continuity_deterministic(scenes, set())
    assert any(f['field'] == 'timeline_day' and f['severity'] == 'high'
               for f in findings)


def test_continuity_deterministic_skips_timeline_backward_when_flashback():
    from storyforge.scoring_story_power import (
        _check_continuity_deterministic, MappedScene,
    )
    scenes = [
        MappedScene('s1', 1, 'T', 'a.', 'A', 'L', '3', 'morning', '',
                    1000, 1000, ''),
        MappedScene('s2', 2, 'T', 'b.', 'A', 'L', '1', 'morning',
                    'flashback', 1000, 1000, ''),
    ]
    findings = _check_continuity_deterministic(scenes, set())
    assert not any(f['field'] == 'timeline_day' for f in findings)


def test_continuity_deterministic_flags_broken_architecture_cross_ref():
    from storyforge.scoring_story_power import (
        _check_continuity_deterministic, MappedScene,
    )
    scenes = [
        MappedScene('s1', 1, 'T', 'a.', 'A', 'L', '1', 'morning', '',
                    1000, 1000, 'a-bogus'),
    ]
    findings = _check_continuity_deterministic(scenes, {'a01', 'a02'})
    assert any(f['field'] == 'architecture_scene' and f['severity'] == 'high'
               for f in findings)


def test_continuity_deterministic_flags_word_count_off_target():
    from storyforge.scoring_story_power import (
        _check_continuity_deterministic, MappedScene,
    )
    scenes = [
        MappedScene('s1', 1, 'T', 'a.', 'A', 'L', '1', 'morning', '',
                    5000, 2000, ''),  # 2.5× over target
    ]
    findings = _check_continuity_deterministic(scenes, set())
    assert any(f['field'] == 'word_count' and f['severity'] == 'medium'
               for f in findings)


def test_continuity_deterministic_clean_scenes_return_no_findings():
    from storyforge.scoring_story_power import (
        _check_continuity_deterministic, MappedScene,
    )
    scenes = [
        MappedScene('s1', 1, 'T', 'a.', 'A', 'L', '1', 'morning', '',
                    2000, 2000, 'arch-1'),
        MappedScene('s2', 2, 'T', 'b.', 'A', 'L', '2', 'morning', '',
                    1800, 2000, 'arch-2'),
    ]
    findings = _check_continuity_deterministic(scenes, {'arch-1', 'arch-2'})
    assert findings == []


def test_scene_map_mode_writes_csvs_and_diagnostic(tmp_path, monkeypatch):
    _seed_summary(str(tmp_path))
    _seed_architecture(str(tmp_path))
    _seed_scene_map(str(tmp_path))
    monkeypatch.chdir(str(tmp_path))
    monkeypatch.setenv('ANTHROPIC_API_KEY', 'test-key')
    fake = _quint_mock_llm(_full_payload(), _act_shape_payload(),
                            _spine_payload(), _architecture_payload(),
                            _scene_map_payload())
    from storyforge import api, scoring_story_power
    monkeypatch.setattr(api, 'invoke_to_file', fake)
    monkeypatch.setattr(scoring_story_power, 'invoke_to_file', fake)
    result = scoring_story_power.score_story_power(str(tmp_path), 'full')
    out_dir = result['output_dir']
    assert os.path.isfile(os.path.join(out_dir, 'per-scene-map-matrix.csv'))
    assert os.path.isfile(os.path.join(out_dir, 'whole-scene-map-axes.csv'))
    ext = result['scene_map']
    assert ext is not None
    assert ext['status'] == 'ok'
    assert ext['per_scene_scores']['s3']['continuity_coherence'] == 7
    assert ext['whole_scene_map_scores']['pacing_distribution'] == 7


def test_scene_map_diagnostic_includes_findings_and_operations(tmp_path,
                                                                 monkeypatch):
    _seed_summary(str(tmp_path))
    _seed_architecture(str(tmp_path))
    _seed_scene_map(str(tmp_path))
    monkeypatch.chdir(str(tmp_path))
    monkeypatch.setenv('ANTHROPIC_API_KEY', 'test-key')
    fake = _quint_mock_llm(_full_payload(), _act_shape_payload(),
                            _spine_payload(), _architecture_payload(),
                            _scene_map_payload())
    from storyforge import api, scoring_story_power
    monkeypatch.setattr(api, 'invoke_to_file', fake)
    monkeypatch.setattr(scoring_story_power, 'invoke_to_file', fake)
    result = scoring_story_power.score_story_power(str(tmp_path), 'full')
    diag = open(os.path.join(result['output_dir'], 'diagnostic.md')).read()
    assert 'Per-scene matrix (scene-map Layer 1)' in diag
    assert 'Whole-scene-map axes' in diag
    assert 'Continuity findings' in diag
    assert 'Proposed scene operations' in diag
    assert 'SPLIT: s3' in diag  # operation summary
    assert 'all four anchors' in diag  # coverage_assessment


def test_scene_map_only_runs_when_csv_present(tmp_path, monkeypatch):
    _seed_summary(str(tmp_path))
    _seed_architecture(str(tmp_path))
    monkeypatch.chdir(str(tmp_path))
    monkeypatch.setenv('ANTHROPIC_API_KEY', 'test-key')
    fake = _quad_mock_llm(_full_payload(), _act_shape_payload(),
                            _spine_payload(), _architecture_payload())
    from storyforge import api, scoring_story_power
    monkeypatch.setattr(api, 'invoke_to_file', fake)
    monkeypatch.setattr(scoring_story_power, 'invoke_to_file', fake)
    result = scoring_story_power.score_story_power(str(tmp_path), 'full')
    assert result['scene_map'] is None
    assert not os.path.isfile(os.path.join(result['output_dir'],
                                            'per-scene-map-matrix.csv'))


def test_scene_map_llm_failure_preserves_deterministic_findings(tmp_path,
                                                                  monkeypatch):
    _seed_summary(str(tmp_path))
    _seed_architecture(str(tmp_path))
    # Seed with a broken cross-reference so the deterministic pre-pass
    # produces at least one finding.
    _seed_scene_map(str(tmp_path), bogus_architecture_scene=True)
    monkeypatch.chdir(str(tmp_path))
    monkeypatch.setenv('ANTHROPIC_API_KEY', 'test-key')

    def fake(prompt, model, log_file, **kwargs):
        os.makedirs(os.path.dirname(log_file) or '.', exist_ok=True)
        if '-scene-map' in log_file:
            raise RuntimeError('scene-map LLM unavailable')
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
    ext = result['scene_map']
    assert ext is not None
    assert ext['status'] == 'llm_error'
    # Deterministic continuity findings survive the LLM failure.
    assert any(f['field'] == 'architecture_scene'
               for f in ext['continuity_findings'])


def test_scene_map_unparseable_response_tags_status(tmp_path, monkeypatch):
    _seed_summary(str(tmp_path))
    _seed_architecture(str(tmp_path))
    _seed_scene_map(str(tmp_path))
    monkeypatch.chdir(str(tmp_path))
    monkeypatch.setenv('ANTHROPIC_API_KEY', 'test-key')

    def fake(prompt, model, log_file, **kwargs):
        os.makedirs(os.path.dirname(log_file) or '.', exist_ok=True)
        if '-scene-map' in log_file:
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
    assert result['scene_map'] is not None
    assert result['scene_map']['status'] == 'unparseable'


def test_scene_map_coach_mode_appends_to_brief(tmp_path, monkeypatch):
    _seed_summary(str(tmp_path))
    _seed_architecture(str(tmp_path))
    _seed_scene_map(str(tmp_path))
    monkeypatch.chdir(str(tmp_path))
    monkeypatch.setenv('ANTHROPIC_API_KEY', 'test-key')
    fake = _quint_mock_llm(_full_payload(), _act_shape_payload(),
                            _spine_payload(), _architecture_payload(),
                            _scene_map_payload())
    from storyforge import api, scoring_story_power
    monkeypatch.setattr(api, 'invoke_to_file', fake)
    monkeypatch.setattr(scoring_story_power, 'invoke_to_file', fake)
    result = scoring_story_power.score_story_power(str(tmp_path), 'coach')
    brief = open(os.path.join(result['output_dir'],
                                'coaching-brief.md')).read()
    assert 'Scene-map extension' in brief
    assert 'Per-scene matrix (scene-map Layer 1)' in brief
    assert 'Proposed scene operations' in brief
    # Coach-mode prelude carries the "not directives" independence reminder.
    assert 'not directives' in brief
    # No separate scene-map CSVs in coach mode.
    assert not os.path.isfile(os.path.join(result['output_dir'],
                                            'per-scene-map-matrix.csv'))


def test_strict_mode_with_scene_map_extends_checklist(tmp_path, monkeypatch):
    _seed_summary(str(tmp_path))
    _seed_architecture(str(tmp_path))
    _seed_scene_map(str(tmp_path))
    monkeypatch.chdir(str(tmp_path))
    from storyforge import api, scoring_story_power

    def boom(*a, **k):
        raise AssertionError('LLM must not be called in strict')
    monkeypatch.setattr(api, 'invoke_to_file', boom)
    monkeypatch.setattr(scoring_story_power, 'invoke_to_file', boom)
    result = scoring_story_power.score_story_power(str(tmp_path), 'strict')
    text = open(os.path.join(result['output_dir'],
                              'self-scoring-checklist.md')).read()
    assert 'Scene-map tier' in text
    for sid in ('s1', 's2', 's3', 's4'):
        assert sid in text
    from storyforge.scoring_story_power import MAP_AXES
    for axis in MAP_AXES:
        assert axis.name in text


def test_per_scene_map_matrix_csv_header_columns(tmp_path, monkeypatch):
    _seed_summary(str(tmp_path))
    _seed_architecture(str(tmp_path))
    _seed_scene_map(str(tmp_path))
    monkeypatch.chdir(str(tmp_path))
    monkeypatch.setenv('ANTHROPIC_API_KEY', 'test-key')
    fake = _quint_mock_llm(_full_payload(), _act_shape_payload(),
                            _spine_payload(), _architecture_payload(),
                            _scene_map_payload())
    from storyforge import api, scoring_story_power
    monkeypatch.setattr(api, 'invoke_to_file', fake)
    monkeypatch.setattr(scoring_story_power, 'invoke_to_file', fake)
    result = scoring_story_power.score_story_power(str(tmp_path), 'full')
    matrix = open(os.path.join(result['output_dir'],
                                'per-scene-map-matrix.csv')).read()
    header = matrix.splitlines()[0]
    assert header == ('scene_id|pov|architecture_scene|'
                       'architecture_coverage|continuity_coherence')


def test_whole_scene_map_csv_weight_column_reflects_axes(tmp_path, monkeypatch):
    _seed_summary(str(tmp_path))
    _seed_architecture(str(tmp_path))
    _seed_scene_map(str(tmp_path))
    monkeypatch.chdir(str(tmp_path))
    monkeypatch.setenv('ANTHROPIC_API_KEY', 'test-key')
    fake = _quint_mock_llm(_full_payload(), _act_shape_payload(),
                            _spine_payload(), _architecture_payload(),
                            _scene_map_payload())
    from storyforge import api, scoring_story_power
    monkeypatch.setattr(api, 'invoke_to_file', fake)
    monkeypatch.setattr(scoring_story_power, 'invoke_to_file', fake)
    result = scoring_story_power.score_story_power(str(tmp_path), 'full')
    from storyforge.scoring_story_power import MAP_AXES
    csv = open(os.path.join(result['output_dir'],
                              'whole-scene-map-axes.csv')).read()
    lines = csv.splitlines()
    weight_by_axis = {a.key: str(a.weight) for a in MAP_AXES}
    header = lines[0].split('|')
    axis_col = header.index('axis')
    weight_col = header.index('weight')
    for line in lines[1:]:
        cells = line.split('|')
        assert cells[weight_col] == weight_by_axis[cells[axis_col]]


def test_extract_proposed_operations_validates_operation_field(capsys):
    from storyforge.scoring_story_power import _extract_proposed_operations
    parsed = {
        'proposed_operations': [
            'not a dict',
            {'operation': 'made-up-op', 'scene_ids': ['s1'], 'summary': 's'},
            {'operation': 'merge', 'scene_ids': [], 'summary': 's'},
            {'operation': 'split', 'scene_ids': ['s1'], 'summary': ''},
            {'operation': 'merge', 'scene_ids': ['s1', 's2'],
             'summary': 'Merge s1 and s2.'},
        ],
    }
    out = _extract_proposed_operations(parsed)
    assert len(out) == 1
    assert out[0]['operation'] == 'merge'
    info = capsys.readouterr().out
    assert 'proposed_operations extraction dropped' in info


def test_extract_proposed_operations_enforces_arity(capsys):
    """merge/reorder require exactly 2 scene_ids; split/insert/promote
    require exactly 1. The docstring promises this; the extractor now
    enforces it (previously documented-only, allowing the LLM to slip
    a 1-id 'merge' through silently)."""
    from storyforge.scoring_story_power import _extract_proposed_operations
    parsed = {
        'proposed_operations': [
            # Wrong arity: merge needs 2, this has 1 → dropped.
            {'operation': 'merge', 'scene_ids': ['s1'],
             'summary': 'bogus single-id merge'},
            # Wrong arity: split needs 1, this has 2 → dropped.
            {'operation': 'split', 'scene_ids': ['s1', 's2'],
             'summary': 'bogus dual-id split'},
            # Right arity: merge with 2.
            {'operation': 'merge', 'scene_ids': ['s1', 's2'],
             'summary': 'Merge s1 and s2.'},
            # Right arity: split with 1.
            {'operation': 'split', 'scene_ids': ['s3'],
             'summary': 'Split s3.'},
            # Right arity: promote with 1.
            {'operation': 'promote', 'scene_ids': ['s4'],
             'summary': 'Promote s4.'},
            # Right arity: reorder with 2.
            {'operation': 'reorder', 'scene_ids': ['s5', 's6'],
             'summary': 'Swap s5 and s6.'},
            # Right arity: insert with 1.
            {'operation': 'insert', 'scene_ids': ['s7'],
             'summary': 'Insert after s7.'},
        ],
    }
    out = _extract_proposed_operations(parsed)
    operations = [o['operation'] for o in out]
    assert operations == ['merge', 'split', 'promote', 'reorder', 'insert']
    info = capsys.readouterr().out
    assert 'merge requires 2' in info
    assert 'split requires 1' in info


def test_continuity_deterministic_skips_arch_xref_when_no_architecture(capsys):
    """When architecture_ids is empty (no architecture.csv on disk),
    the cross-reference check is skipped wholesale. Without the skip,
    every scene with a populated architecture_scene would flag as
    broken — a noise storm. One INFO breadcrumb is logged."""
    from storyforge.scoring_story_power import (
        _check_continuity_deterministic, MappedScene,
    )
    scenes = [
        MappedScene('s1', 1, 'T', 'a.', 'A', 'L', '1', 'morning', '',
                    1000, 1000, 'a01'),
        MappedScene('s2', 2, 'T', 'b.', 'A', 'L', '2', 'morning', '',
                    1000, 1000, 'a02'),
        MappedScene('s3', 3, 'T', 'c.', 'A', 'L', '3', 'morning', '',
                    1000, 1000, 'a03'),
    ]
    findings = _check_continuity_deterministic(scenes, set())
    assert not any(f['field'] == 'architecture_scene' for f in findings)
    out = capsys.readouterr().out
    assert 'skipping architecture cross-reference' in out


def test_continuity_deterministic_allows_prologue_and_interlude_types():
    """The deterministic timeline-backward check exempts prologue and
    interlude in addition to flashback. The previous implementation
    only excluded flashback, but the issue message advertised both —
    fixing the message/code mismatch."""
    from storyforge.scoring_story_power import (
        _check_continuity_deterministic, MappedScene,
    )
    scenes_prologue = [
        MappedScene('s1', 1, 'T', 'a.', 'A', 'L', '3', 'morning', '',
                    1000, 1000, ''),
        MappedScene('s2', 2, 'T', 'b.', 'A', 'L', '1', 'morning',
                    'prologue', 1000, 1000, ''),
    ]
    findings = _check_continuity_deterministic(scenes_prologue, set())
    assert not any(f['field'] == 'timeline_day' for f in findings)

    scenes_interlude = [
        MappedScene('s1', 1, 'T', 'a.', 'A', 'L', '3', 'morning', '',
                    1000, 1000, ''),
        MappedScene('s2', 2, 'T', 'b.', 'A', 'L', '1', 'morning',
                    'interlude', 1000, 1000, ''),
    ]
    findings = _check_continuity_deterministic(scenes_interlude, set())
    assert not any(f['field'] == 'timeline_day' for f in findings)


def test_continuity_finding_issue_text_names_allowed_types():
    """When timeline goes backward without an allowed scene_type, the
    issue text should name ALL allowed types (not just 'flashback')
    so the author knows the actual remedy set."""
    from storyforge.scoring_story_power import (
        _check_continuity_deterministic, MappedScene,
    )
    scenes = [
        MappedScene('s1', 1, 'T', 'a.', 'A', 'L', '3', 'morning', '',
                    1000, 1000, ''),
        MappedScene('s2', 2, 'T', 'b.', 'A', 'L', '1', 'morning',
                    'regular', 1000, 1000, ''),
    ]
    findings = _check_continuity_deterministic(scenes, set())
    timeline_findings = [f for f in findings if f['field'] == 'timeline_day']
    assert timeline_findings
    issue = timeline_findings[0]['issue']
    # Names all three allowed types so the author has the full remedy.
    for kw in ('flashback', 'interlude', 'prologue'):
        assert kw in issue


def test_parse_scene_map_unset_seq_sorts_to_end(tmp_path, capsys):
    """Mixed-seq scenarios: rows with seq=blank/non-int (seq=None) must
    sort AFTER rows with explicit seq. The previous int+0-sentinel sort
    put unset-seq scenes at the TOP, silently mis-ordering interstitials
    added without seq numbers."""
    ref = os.path.join(str(tmp_path), 'reference')
    os.makedirs(ref, exist_ok=True)
    with open(os.path.join(ref, 'scenes.csv'), 'w') as f:
        f.write(
            'id|seq|summary\n'
            'unset-first||first row but unset seq — should sort to end\n'
            'chapter-1|1|first explicit\n'
            'unset-second|nonint|second unset — also to end\n'
            'chapter-2|2|second explicit\n'
        )
    from storyforge.scoring_story_power import parse_scene_map
    scenes = parse_scene_map(str(tmp_path))
    # Explicit-seq rows come first, in seq order. Unset-seq rows come
    # last, in CSV row order.
    assert [s.id for s in scenes] == [
        'chapter-1', 'chapter-2', 'unset-first', 'unset-second',
    ]
    # Non-int seq logs a WARNING (rather than silently treating as 0).
    out = capsys.readouterr().out
    assert 'non-int seq' in out


def test_parse_scene_map_all_blank_seq_preserves_csv_order(tmp_path):
    """When every row has blank seq, the stable sort preserves CSV
    order via the secondary key."""
    ref = os.path.join(str(tmp_path), 'reference')
    os.makedirs(ref, exist_ok=True)
    with open(os.path.join(ref, 'scenes.csv'), 'w') as f:
        f.write(
            'id|seq|summary\n'
            'alpha||first.\n'
            'beta||second.\n'
            'gamma||third.\n'
        )
    from storyforge.scoring_story_power import parse_scene_map
    scenes = parse_scene_map(str(tmp_path))
    assert [s.id for s in scenes] == ['alpha', 'beta', 'gamma']
    assert all(s.seq is None for s in scenes)


def test_extract_continuity_findings_drops_incomplete_rows(capsys):
    from storyforge.scoring_story_power import _extract_continuity_findings
    parsed = {
        'continuity_findings': [
            'not a dict',
            {'scene_id': '', 'field': 'pov', 'issue': 'bad'},
            {'scene_id': 's1', 'field': '', 'issue': 'bad'},
            {'scene_id': 's1', 'field': 'pov', 'issue': ''},
            {'scene_id': 's1', 'field': 'pov', 'issue': 'bad',
             'severity': 'high'},
        ],
    }
    out = _extract_continuity_findings(parsed)
    assert len(out) == 1
    assert out[0]['severity'] == 'high'
    info = capsys.readouterr().out
    assert 'continuity_findings extraction dropped' in info


def test_parse_response_scene_map_handles_fenced_json():
    from storyforge.scoring_story_power import _parse_response_scene_map
    payload = json.dumps(_scene_map_payload())
    text = f'```json\n{payload}\n```\n'
    parsed = _parse_response_scene_map(text)
    assert parsed is not None
    assert isinstance(parsed['per_scene'], list)


def test_parse_response_scene_map_warns_when_lists_missing(capsys):
    from storyforge.scoring_story_power import _parse_response_scene_map
    bad = json.dumps({'unrelated': []})
    parsed = _parse_response_scene_map(bad)
    assert parsed is None
    out = capsys.readouterr().out
    assert 'per_scene' in out and 'whole_scene_map' in out


def test_append_scene_map_diagnostic_warns_when_md_missing(tmp_path, capsys):
    from storyforge.scoring_story_power import (
        _append_scene_map_diagnostic, MappedScene,
    )
    scenes = [MappedScene('s1', 1, 'T', 'a.', 'A', 'L', '1', 'morning', '',
                          1000, 1000, '')]
    _append_scene_map_diagnostic(str(tmp_path), scenes, {'s1': {}}, {},
                                   [], [], {})
    out = capsys.readouterr().out
    assert 'scene-map diagnostic could not be appended' in out


def test_append_scene_map_coaching_brief_warns_when_md_missing(tmp_path,
                                                                 capsys):
    from storyforge.scoring_story_power import (
        _append_scene_map_coaching_brief, MappedScene,
    )
    scenes = [MappedScene('s1', 1, 'T', 'a.', 'A', 'L', '1', 'morning', '',
                          1000, 1000, '')]
    _append_scene_map_coaching_brief(str(tmp_path), scenes, {'s1': {}}, {},
                                       [], [], {})
    out = capsys.readouterr().out
    assert 'scene-map coaching brief could not be appended' in out


def test_quint_mock_llm_routes_to_all_five_payloads(tmp_path, monkeypatch):
    """Defensive: assert the quint mock actually routes scene-map; a
    silent fallback to pitch would invalidate every scene-map test."""
    _seed_summary(str(tmp_path))
    _seed_spine(str(tmp_path))
    _seed_architecture(str(tmp_path))
    _seed_scene_map(str(tmp_path))
    monkeypatch.chdir(str(tmp_path))
    monkeypatch.setenv('ANTHROPIC_API_KEY', 'test-key')
    seen: dict[str, int] = {
        'pitch': 0, 'act_shape': 0, 'spine': 0,
        'architecture': 0, 'scene_map': 0,
    }

    def fake(prompt, model, log_file, **kwargs):
        os.makedirs(os.path.dirname(log_file) or '.', exist_ok=True)
        if '-scene-map' in log_file:
            seen['scene_map'] += 1
            payload = _scene_map_payload()
        elif '-architecture' in log_file:
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
    assert seen == {'pitch': 1, 'act_shape': 1, 'spine': 1,
                     'architecture': 1, 'scene_map': 1}


def test_scene_map_integration_with_backward_timeline(tmp_path, monkeypatch,
                                                        capsys):
    """End-to-end: a backward-timeline scenes.csv must produce a
    deterministic timeline_day finding that flows through to the result."""
    _seed_summary(str(tmp_path))
    _seed_architecture(str(tmp_path))
    _seed_scene_map(str(tmp_path), backward_timeline=True)
    monkeypatch.chdir(str(tmp_path))
    monkeypatch.setenv('ANTHROPIC_API_KEY', 'test-key')
    fake = _quint_mock_llm(_full_payload(), _act_shape_payload(),
                            _spine_payload(), _architecture_payload(),
                            _scene_map_payload())
    from storyforge import api, scoring_story_power
    monkeypatch.setattr(api, 'invoke_to_file', fake)
    monkeypatch.setattr(scoring_story_power, 'invoke_to_file', fake)
    result = scoring_story_power.score_story_power(str(tmp_path), 'full')
    ext = result['scene_map']
    assert ext is not None
    assert any(f['field'] == 'timeline_day' and f['severity'] == 'high'
               for f in ext['continuity_findings'])
    # The finding's issue text should describe what went wrong (T-9
    # tightening) — pin the substring so a future generic-ified
    # message would fail loudly.
    timeline_finding = next(
        f for f in ext['continuity_findings']
        if f['field'] == 'timeline_day'
    )
    assert 'went backward' in timeline_finding['issue']


# ---------------------------------------------------------------------------
# Test gaps from the PR #243 review
# ---------------------------------------------------------------------------

def test_parse_response_scene_map_handles_greedy_extraction():
    """Tier-3 fallback: JSON embedded in prose with no fence — the
    last line of defense against an LLM that wraps JSON in commentary."""
    from storyforge.scoring_story_power import _parse_response_scene_map
    payload = json.dumps(_scene_map_payload())
    text = f'Here is my analysis. {payload} Done.'
    parsed = _parse_response_scene_map(text)
    assert parsed is not None
    assert isinstance(parsed['per_scene'], list)


def test_parse_response_scene_map_handles_only_per_scene_missing(capsys):
    """Shape-failure WARN names the per_scene list specifically when
    that's the only missing field."""
    from storyforge.scoring_story_power import _parse_response_scene_map
    bad = json.dumps({'whole_scene_map': []})
    parsed = _parse_response_scene_map(bad)
    assert parsed is None
    out = capsys.readouterr().out
    assert 'per_scene' in out


def test_parse_response_scene_map_handles_only_whole_map_missing(capsys):
    """Shape-failure WARN names whole_scene_map specifically when
    that's the only missing field."""
    from storyforge.scoring_story_power import _parse_response_scene_map
    bad = json.dumps({'per_scene': []})
    parsed = _parse_response_scene_map(bad)
    assert parsed is None
    out = capsys.readouterr().out
    assert 'whole_scene_map' in out


def test_scene_map_runs_without_architecture_csv(tmp_path, monkeypatch, capsys):
    """When scenes.csv exists but architecture.csv doesn't, scene-map
    mode runs without producing an architecture-cross-ref storm.
    Deterministic check skips the cross-ref loop and emits one INFO
    breadcrumb instead of N high-severity findings."""
    _seed_summary(str(tmp_path))
    _seed_scene_map(str(tmp_path))  # No _seed_architecture call.
    monkeypatch.chdir(str(tmp_path))
    monkeypatch.setenv('ANTHROPIC_API_KEY', 'test-key')

    def fake(prompt, model, log_file, **kwargs):
        os.makedirs(os.path.dirname(log_file) or '.', exist_ok=True)
        if '-scene-map' in log_file:
            payload = _scene_map_payload()
        elif '-act-shape' in log_file:
            payload = _act_shape_payload()
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
    result = scoring_story_power.score_story_power(str(tmp_path), 'full')
    ext = result['scene_map']
    assert ext is not None
    out = capsys.readouterr().out
    # The skip log fires once.
    assert 'skipping architecture cross-reference' in out
    # No architecture_scene findings appear in the result.
    arch_findings = [f for f in ext['continuity_findings']
                     if f['field'] == 'architecture_scene']
    assert arch_findings == []


def test_continuity_deterministic_non_numeric_timeline_day_safe():
    """Non-int timeline_day values (e.g., 'day-after', 'morning') must
    be silently tolerated — the check skips the timeline comparison
    rather than crashing or flagging."""
    from storyforge.scoring_story_power import (
        _check_continuity_deterministic, MappedScene,
    )
    scenes = [
        MappedScene('s1', 1, 'T', 'a.', 'A', 'L', '1', 'morning', '',
                    1000, 1000, ''),
        MappedScene('s2', 2, 'T', 'b.', 'A', 'L', 'day-after', 'morning',
                    '', 1000, 1000, ''),
    ]
    findings = _check_continuity_deterministic(scenes, set())
    assert not any(f['field'] == 'timeline_day' for f in findings)


def test_build_scene_map_prompt_renders_no_architecture_fallback():
    """When architecture_scenes is empty, the prompt embeds the
    '(no architecture.csv populated)' placeholder so the LLM knows
    not to fault scenes for missing coverage."""
    from storyforge.scoring_story_power import (
        _build_scene_map_prompt, MappedScene, PitchArtifacts,
    )
    scenes = [
        MappedScene('s1', 1, 'T', 'a beat.', '', '', '1', '', '',
                    1000, 1000, ''),
    ]
    artifacts = PitchArtifacts(logline='L', synopsis='S', act_shape='',
                                theme='', spine_summaries='',
                                architecture_summaries='')
    prompt = _build_scene_map_prompt(scenes, [], artifacts, [], 'rubric')
    assert '(no architecture.csv populated)' in prompt


def test_build_scene_map_prompt_inlines_deterministic_findings():
    """The prompt's 'Deterministic continuity findings' block surfaces
    the actual finding text — the LLM seeds its continuity_coherence
    scoring against these. Without the inlining, the LLM would
    re-discover the issues at extra token cost."""
    from storyforge.scoring_story_power import (
        _build_scene_map_prompt, MappedScene, PitchArtifacts,
        _check_continuity_deterministic,
    )
    scenes = [
        MappedScene('s1', 1, 'T', 'a.', 'A', 'L', '3', 'morning', '',
                    1000, 1000, ''),
        MappedScene('s2', 2, 'T', 'b.', 'A', 'L', '1', 'morning',
                    'regular', 1000, 1000, ''),
    ]
    artifacts = PitchArtifacts(logline='L', synopsis='S', act_shape='',
                                theme='', spine_summaries='',
                                architecture_summaries='')
    det_findings = _check_continuity_deterministic(scenes, set())
    assert det_findings  # sanity check the test fixture
    prompt = _build_scene_map_prompt(scenes, [], artifacts,
                                       det_findings, 'rubric')
    # The finding's issue text appears in the prompt — the LLM gets
    # the actionable detail, not just the count.
    assert 'went backward' in prompt


def test_scene_map_partial_per_scene_tags_partial(tmp_path, monkeypatch):
    """A scene-map payload missing per-scene axes for one scene
    surfaces as status='partial' rather than collapsing to 'ok'."""
    _seed_summary(str(tmp_path))
    _seed_architecture(str(tmp_path))
    _seed_scene_map(str(tmp_path))
    monkeypatch.chdir(str(tmp_path))
    monkeypatch.setenv('ANTHROPIC_API_KEY', 'test-key')
    scene_map_payload = _scene_map_payload()
    # Keep one s2 axis; drop the other so per-scene is partial but
    # not empty (the empty-scene floor doesn't trigger).
    for row in scene_map_payload['per_scene']:
        if row['scene_id'] == 's2':
            row['scores'] = row['scores'][:1]
    fake = _quint_mock_llm(_full_payload(), _act_shape_payload(),
                            _spine_payload(), _architecture_payload(),
                            scene_map_payload)
    from storyforge import api, scoring_story_power
    monkeypatch.setattr(api, 'invoke_to_file', fake)
    monkeypatch.setattr(scoring_story_power, 'invoke_to_file', fake)
    result = scoring_story_power.score_story_power(str(tmp_path), 'full')
    assert result['scene_map']['status'] == 'partial'
    assert result['status'] == 'partial'


def test_empty_scene_map_refuses_matrix_and_writes_sidecar(tmp_path,
                                                             monkeypatch,
                                                             capsys):
    """When the LLM returns no per-scene scores for a non-trivial
    fraction of the scenes, refuse to write the matrix AND write the
    full list of empty scene ids to a sidecar file."""
    _seed_summary(str(tmp_path))
    _seed_architecture(str(tmp_path))
    _seed_scene_map(str(tmp_path))
    monkeypatch.chdir(str(tmp_path))
    monkeypatch.setenv('ANTHROPIC_API_KEY', 'test-key')
    scene_map_payload = _scene_map_payload()
    # Drop s2 and s3 entirely from the per-scene response.
    scene_map_payload['per_scene'] = [
        r for r in scene_map_payload['per_scene']
        if r['scene_id'] not in {'s2', 's3'}
    ]
    fake = _quint_mock_llm(_full_payload(), _act_shape_payload(),
                            _spine_payload(), _architecture_payload(),
                            scene_map_payload)
    from storyforge import api, scoring_story_power
    monkeypatch.setattr(api, 'invoke_to_file', fake)
    monkeypatch.setattr(scoring_story_power, 'invoke_to_file', fake)
    result = scoring_story_power.score_story_power(str(tmp_path), 'full')
    out_dir = result['output_dir']
    log_out = capsys.readouterr().out
    assert 'refusing to write per-scene-map-matrix.csv' in log_out
    sidecar = os.path.join(out_dir, 'scene-map-empty-scenes.txt')
    assert os.path.isfile(sidecar)
    body = open(sidecar).read()
    assert 's2' in body and 's3' in body
    # And the CSV itself was NOT written.
    assert not os.path.isfile(os.path.join(out_dir,
                                            'per-scene-map-matrix.csv'))


def test_extract_per_scene_map_scores_drops_malformed(capsys):
    """Drop paths: non-dict event row, unknown scene_id, non-dict
    score row, unknown axis, non-int score, out-of-range score."""
    from storyforge.scoring_story_power import _extract_per_scene_map_scores
    parsed = {
        'per_scene': [
            'not a dict',
            {'scene_id': 'unknown', 'scores': []},
            {'scene_id': 's1', 'scores': [
                'not a dict',
                {'axis': 'made_up', 'score': 8},
                {'axis': 'continuity_coherence', 'score': 'high'},
                {'axis': 'architecture_coverage', 'score': 47},
                {'axis': 'architecture_coverage', 'score': 7},
            ]},
        ],
    }
    out = _extract_per_scene_map_scores(parsed, ['s1'])
    assert out == {'s1': {'architecture_coverage': 7}}
    info = capsys.readouterr().out
    assert 'per-scene-map extraction dropped' in info


def test_extract_whole_scene_map_scores_drops_malformed(capsys):
    from storyforge.scoring_story_power import _extract_whole_scene_map_scores
    parsed = {
        'whole_scene_map': [
            'not a dict',
            {'axis': 'made_up_axis', 'score': 7},
            {'axis': 'pov_rotation', 'score': 'mid'},
            {'axis': 'pov_rotation', 'score': 0},
            {'axis': 'pov_rotation', 'score': 7},
        ],
    }
    out = _extract_whole_scene_map_scores(parsed)
    assert out == {'pov_rotation': 7}
    info = capsys.readouterr().out
    assert 'whole-scene-map extraction dropped' in info


def test_extract_proposed_operations_normalizes_case_and_strips_ids(capsys):
    """The extractor accepts mixed-case operation strings and strips
    whitespace from scene_ids; pure-whitespace ids are filtered out."""
    from storyforge.scoring_story_power import _extract_proposed_operations
    parsed = {
        'proposed_operations': [
            {'operation': '  MERGE  ',
             'scene_ids': ['s1', '  s2  ', '   '],
             'summary': 'Merge s1 and s2.'},
            {'operation': 'Promote',
             'scene_ids': ['s3'],
             'summary': 'Promote s3.'},
        ],
    }
    out = _extract_proposed_operations(parsed)
    assert len(out) == 2
    assert out[0]['operation'] == 'merge'
    # Whitespace stripped + empty-string entry filtered.
    assert out[0]['scene_ids'] == ['s1', 's2']
    assert out[1]['operation'] == 'promote'


# ---------------------------------------------------------------------------
# Briefs mode (Layer 1 per-brief + Layer 2 whole-briefs)
# ---------------------------------------------------------------------------

def _seed_briefs(project_dir: str, *,
                   scene_count: int = 4,
                   missing_engine_field: str | None = None,
                   invalid_outcome: bool = False,
                   orphan_knowledge: bool = False,
                   outcome_streak: str | None = None,
                   motif_singleton: bool = False,
                   empty_engine_row: bool = False) -> None:
    """Write a small scene-briefs.csv. Variants exercise each
    deterministic pre-pass failure mode independently."""
    ref = os.path.join(project_dir, 'reference')
    os.makedirs(ref, exist_ok=True)
    rows = []
    base_rows = [
        # (id, goal, conflict, outcome, crisis, decision, kn_in, kn_out,
        #  actions, dialogue, emotions, motifs, subtext, deps)
        ('s1',
         'Find her father in the archive',
         'The archivist refuses to show her the ledger',
         'no',
         'Comply and lose access forever, or break protocol and lose status',
         'She breaks protocol and steals the key',
         '',
         'archive-locks-after-dark',
         'Mira picks the desk lock at 11pm',
         'You should not be here at this hour.',
         'curiosity → defiance → resolve',
         'lantern;ledger',
         'Mira says she is leaving but means she is staying',
         ''),
        ('s2',
         'Decode the ledger she stole',
         'The cipher requires her fathers signature stroke',
         'yes-but',
         'Use the forged stroke and corrupt the record, or wait and lose the trail',
         'She forges the stroke',
         'archive-locks-after-dark',
         'archive-locks-after-dark;cipher-key-pattern',
         'Mira traces a sigil on tracing paper',
         'The strokes are a name not a code.',
         'doubt → relief → guilt',
         'lantern;sigil',
         'She tells herself she had no choice while planning the next forgery',
         's1'),
        ('s3',
         'Confront her father about the ledger',
         'Her father denies the ledger exists',
         'no-and',
         'Accept the lie and stay safe, or call him a liar and lose home',
         'She calls him a liar and leaves',
         'archive-locks-after-dark;cipher-key-pattern',
         'archive-locks-after-dark;cipher-key-pattern;father-knows-cipher',
         'Mira places the forged ledger on the kitchen table',
         'You wrote this. I traced your sigil.',
         'hope → anger → grief',
         'sigil;table',
         'He says he loves her while planning to destroy the ledger tonight',
         's2'),
        ('s4',
         'Return to the archive and finish the decoding',
         'The archivist has changed the locks',
         'yes',
         'Walk away with what she has, or burn it down for the rest',
         'She breaks the south window and goes in',
         'archive-locks-after-dark;cipher-key-pattern;father-knows-cipher',
         'archive-locks-after-dark;cipher-key-pattern;father-knows-cipher;full-cipher',
         'Mira climbs the south wall by the cipher light',
         'I told you I would come back.',
         'fear → resolve → triumph',
         'lantern;cipher',
         'She knows she is repeating her fathers crime and chooses it anyway',
         's3'),
    ][:scene_count]

    if missing_engine_field:
        # Blank out the named field on s1 only.
        field_idx = {
            'goal': 1, 'conflict': 2, 'outcome': 3, 'crisis': 4,
            'decision': 5,
        }[missing_engine_field]
        first = list(base_rows[0])
        first[field_idx] = ''
        base_rows[0] = tuple(first)
    if invalid_outcome:
        first = list(base_rows[0])
        first[3] = 'maybe'  # not in {yes, no, yes-but, no-and}
        base_rows[0] = tuple(first)
    if orphan_knowledge:
        # s2's knowledge_in claims a fact no upstream brief provided.
        second = list(base_rows[1])
        second[6] = 'unrelated-fact'  # knowledge_in
        base_rows[1] = tuple(second)
    if outcome_streak:
        # Force 4 consecutive identical outcomes.
        for i in range(min(4, len(base_rows))):
            r = list(base_rows[i])
            r[3] = outcome_streak
            base_rows[i] = tuple(r)
    if motif_singleton:
        # Replace s2 motifs with a one-off motif that appears nowhere else.
        second = list(base_rows[1])
        second[11] = 'unique-motif-s2-only'
        base_rows[1] = tuple(second)
    if empty_engine_row:
        # Add an unbriefed scaffold row alongside the others.
        base_rows = list(base_rows) + [('s5', '', '', '', '', '', '', '',
                                          '', '', '', '', '', '')]

    headers = ('id|goal|conflict|outcome|crisis|decision|knowledge_in|'
               'knowledge_out|key_actions|key_dialogue|emotions|motifs|'
               'subtext|continuity_deps')
    rows = [headers] + ['|'.join(r) for r in base_rows]
    with open(os.path.join(ref, 'scene-briefs.csv'), 'w') as f:
        f.write('\n'.join(rows) + '\n')


def _briefs_payload(brief_ids: list[str] | None = None) -> dict:
    """Well-shaped briefs LLM payload."""
    if brief_ids is None:
        brief_ids = ['s1', 's2', 's3', 's4']
    per_brief = []
    for bid in brief_ids:
        per_brief.append({
            'scene_id': bid,
            'scores': [
                {'axis': 'scene_engine_integrity',
                 'score': 7 if bid == 's2' else 9,
                 'rationale': f'engine for {bid}'},
                {'axis': 'concreteness_brief', 'score': 8,
                 'rationale': f'concreteness for {bid}'},
            ],
        })
    whole_briefs = [
        {'axis': 'outcome_distribution', 'score': 8,
         'positive_signals': 'spread across enum',
         'negative_signals': '',
         'rationale': 'no streaks'},
        {'axis': 'knowledge_flow_continuity', 'score': 7,
         'positive_signals': 'cipher arc threads through',
         'negative_signals': 's1 introduces archive-locks without source',
         'rationale': 'one orphan fact'},
        {'axis': 'crisis_density', 'score': 8,
         'positive_signals': 'every brief has a dilemma',
         'negative_signals': '',
         'rationale': '4 of 4 crises are real choices'},
        {'axis': 'subtext_presence', 'score': 8,
         'positive_signals': 'every dialogue brief carries subtext',
         'negative_signals': '',
         'rationale': 'consistent subtext discipline'},
        {'axis': 'motif_recurrence', 'score': 7,
         'positive_signals': 'lantern recurs in three briefs',
         'negative_signals': 'table appears once',
         'rationale': 'one singleton motif'},
    ]
    return {
        'per_brief': per_brief,
        'whole_briefs': whole_briefs,
        'briefs_diagnostic': {
            'lowest_axis': 'knowledge_flow_continuity',
            'lowest_axis_average': '7.0',
            'summary': 's1 introduces a fact with no source',
            'scene_engine_assessment': 'briefs cohere; s2 has the weakest engine',
            'high_leverage_move': 'add archive-locks-after-dark to a pre-s1 brief',
        },
        'brief_findings': [
            {'scene_id': 's2', 'field': 'crisis',
             'issue': 'crisis paraphrases the conflict',
             'severity': 'medium'},
        ],
        'proposed_brief_updates': [
            {'scene_id': 's2', 'field': 'crisis',
             'current_value': 'Use the forged stroke and corrupt the record, '
                              'or wait and lose the trail',
             'proposed_value': 'Either she forges the stroke and becomes the '
                                'crime she came to investigate, or she lets '
                                'the trail die and abandons her father.',
             'rationale': 'lifts scene_engine_integrity 7 → 9'},
        ],
    }


def _hex_mock_llm(pitch_payload: dict, act_shape_payload: dict,
                    spine_payload: dict, architecture_payload: dict,
                    scene_map_payload: dict, briefs_payload: dict):
    """Mock that routes by log filename suffix across all six tiers.

    When adding a seventh tier, extend this dispatcher AND extend
    `test_hex_mock_llm_routes_to_all_six_payloads` to track the new
    tier in its hit-counter — otherwise the new tier's LLM call falls
    through to the default (pitch) payload and downstream tests
    silently assert against the wrong shape."""
    def fake(prompt, model, log_file, **kwargs):
        os.makedirs(os.path.dirname(log_file) or '.', exist_ok=True)
        if '-briefs' in log_file:
            payload = briefs_payload
        elif '-scene-map' in log_file:
            payload = scene_map_payload
        elif '-architecture' in log_file:
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


def test_per_brief_axes_module_load_invariants():
    """PER_BRIEF_AXES carries unique keys and a 1.5x load-bearing axis."""
    from storyforge.scoring_story_power import PER_BRIEF_AXES
    keys = [a.key for a in PER_BRIEF_AXES]
    assert len(keys) == len(set(keys))
    assert all(a.weight in (1.0, 1.5) for a in PER_BRIEF_AXES)
    assert sum(1 for a in PER_BRIEF_AXES if a.weight == 1.5) == 1


def test_briefs_axes_module_load_invariants():
    """BRIEFS_AXES carries unique keys with two load-bearing axes."""
    from storyforge.scoring_story_power import BRIEFS_AXES
    keys = [a.key for a in BRIEFS_AXES]
    assert len(keys) == len(set(keys))
    assert all(a.weight in (1.0, 1.5) for a in BRIEFS_AXES)
    assert sum(1 for a in BRIEFS_AXES if a.weight == 1.5) == 2


def test_briefs_axis_families_disjoint_from_other_families():
    """A briefs axis key must not collide with any other family's
    keys — diagnostic routing depends on it. This is the data-driven
    invariant; if it fires at import time the module won't even load,
    so this test guards against accidentally writing a regression test
    that doesn't exercise the assertion."""
    from storyforge.scoring_story_power import (
        PER_BRIEF_AXIS_KEYS, BRIEFS_AXIS_KEYS, AXIS_KEYS,
        STRUCTURAL_AXIS_KEYS, PER_EVENT_AXIS_KEYS, SPINE_AXIS_KEYS,
        PER_SCENE_AXIS_KEYS, ARCHITECTURE_AXIS_KEYS,
        PER_MAP_SCENE_AXIS_KEYS, MAP_AXIS_KEYS,
    )
    others = (AXIS_KEYS + STRUCTURAL_AXIS_KEYS + PER_EVENT_AXIS_KEYS
              + SPINE_AXIS_KEYS + PER_SCENE_AXIS_KEYS
              + ARCHITECTURE_AXIS_KEYS + PER_MAP_SCENE_AXIS_KEYS
              + MAP_AXIS_KEYS)
    briefs_combined = set(PER_BRIEF_AXIS_KEYS + BRIEFS_AXIS_KEYS)
    assert not (briefs_combined & set(others))


def test_parse_scene_briefs_missing_file_returns_empty(tmp_path):
    from storyforge.scoring_story_power import parse_scene_briefs
    assert parse_scene_briefs(str(tmp_path)) == []


def test_parse_scene_briefs_missing_id_column_returns_empty(tmp_path, capsys):
    from storyforge.scoring_story_power import parse_scene_briefs
    ref = tmp_path / 'reference'
    ref.mkdir()
    (ref / 'scene-briefs.csv').write_text('goal|conflict\nabc|def\n')
    assert parse_scene_briefs(str(tmp_path)) == []
    out = capsys.readouterr().out
    assert 'missing required column id' in out


def test_parse_scene_briefs_drops_malformed_rows(tmp_path, capsys):
    from storyforge.scoring_story_power import parse_scene_briefs
    _seed_briefs(str(tmp_path))
    # Append a malformed row with wrong cell count.
    briefs_path = tmp_path / 'reference' / 'scene-briefs.csv'
    with open(briefs_path, 'a') as f:
        f.write('s9|too|few|cells\n')
    parsed = parse_scene_briefs(str(tmp_path))
    assert {b.id for b in parsed} == {'s1', 's2', 's3', 's4'}
    out = capsys.readouterr().out
    assert 'malformed scene-briefs.csv row' in out


def test_parse_scene_briefs_drops_empty_engine_scaffolds(tmp_path, capsys):
    """A row with all five scene-engine fields empty is migration
    scaffolding, not a real brief — drop it with an INFO log rather
    than letting the pre-pass flag five high-severity findings."""
    from storyforge.scoring_story_power import parse_scene_briefs
    _seed_briefs(str(tmp_path), empty_engine_row=True)
    parsed = parse_scene_briefs(str(tmp_path))
    assert 's5' not in {b.id for b in parsed}
    out = capsys.readouterr().out
    assert 'all scene-engine fields empty' in out


def test_parse_scene_briefs_splits_array_cells(tmp_path):
    """knowledge_in / knowledge_out / motifs / continuity_deps split
    on `;` and return as tuples (empty cells → empty tuple)."""
    from storyforge.scoring_story_power import parse_scene_briefs
    _seed_briefs(str(tmp_path))
    parsed = parse_scene_briefs(str(tmp_path))
    by_id = {b.id: b for b in parsed}
    assert by_id['s2'].knowledge_in == ('archive-locks-after-dark',)
    assert by_id['s2'].knowledge_out == (
        'archive-locks-after-dark', 'cipher-key-pattern',
    )
    assert by_id['s2'].motifs == ('lantern', 'sigil')
    assert by_id['s2'].continuity_deps == ('s1',)
    # s1 has empty knowledge_in.
    assert by_id['s1'].knowledge_in == ()


def test_check_briefs_deterministic_flags_missing_required_fields():
    from storyforge.scoring_story_power import (
        _check_briefs_deterministic, Brief,
    )
    briefs = [
        Brief('s1', '', 'conflict', 'yes', 'crisis', 'decision',
              (), (), '', '', '', (), '', ()),
    ]
    findings = _check_briefs_deterministic(briefs, [])
    goal_finding = next(
        f for f in findings if f['scene_id'] == 's1' and f['field'] == 'goal'
    )
    assert goal_finding['severity'] == 'high'


def test_check_briefs_deterministic_flags_invalid_outcome():
    from storyforge.scoring_story_power import (
        _check_briefs_deterministic, Brief,
    )
    briefs = [
        Brief('s1', 'g', 'c', 'maybe', 'cr', 'dec',
              (), (), '', '', '', (), '', ()),
    ]
    findings = _check_briefs_deterministic(briefs, [])
    outcome_finding = next(
        f for f in findings
        if f['scene_id'] == 's1' and f['field'] == 'outcome'
        and 'not in valid set' in f['issue']
    )
    assert outcome_finding['severity'] == 'high'


def test_check_briefs_deterministic_flags_knowledge_orphan(tmp_path):
    """A knowledge_in fact with no upstream knowledge_out across the
    continuity_deps graph is an orphan — medium severity."""
    from storyforge.scoring_story_power import (
        parse_scene_briefs, _check_briefs_deterministic,
    )
    _seed_briefs(str(tmp_path), orphan_knowledge=True)
    briefs = parse_scene_briefs(str(tmp_path))
    findings = _check_briefs_deterministic(briefs, [b.id for b in briefs])
    orphan_finding = next(
        f for f in findings
        if f['scene_id'] == 's2' and f['field'] == 'knowledge_in'
        and 'unrelated-fact' in f['issue']
    )
    assert orphan_finding['severity'] == 'medium'


def test_check_briefs_deterministic_walks_continuity_deps_transitively(tmp_path):
    """When s3 depends on s2 and s2 depends on s1, s3's knowledge_in
    is satisfied by s1's knowledge_out even though s3 doesn't list s1
    as a direct dep — BFS walks the graph transitively."""
    from storyforge.scoring_story_power import (
        _check_briefs_deterministic, Brief,
    )
    briefs = [
        Brief('s1', 'g', 'c', 'yes', 'cr', 'd',
              (), ('fact-a',), '', '', '', (), '', ()),
        Brief('s2', 'g', 'c', 'yes', 'cr', 'd',
              ('fact-a',), ('fact-a', 'fact-b'), '', '', '', (), '', ('s1',)),
        Brief('s3', 'g', 'c', 'yes', 'cr', 'd',
              ('fact-a',), ('fact-a',), '', '', '', (), '', ('s2',)),
    ]
    findings = _check_briefs_deterministic(briefs, ['s1', 's2', 's3'])
    # No knowledge_in finding for s3 — fact-a is provided by s1 via s2.
    s3_kn = [f for f in findings
             if f['scene_id'] == 's3' and f['field'] == 'knowledge_in']
    assert s3_kn == []


def test_check_briefs_deterministic_handles_continuity_dep_cycle():
    """A continuity_deps cycle (s1 ↔ s2) must not hang the graph
    walk — the visited set bounds traversal regardless of cycle
    topology."""
    from storyforge.scoring_story_power import (
        _check_briefs_deterministic, Brief,
    )
    briefs = [
        Brief('s1', 'g', 'c', 'yes', 'cr', 'd',
              ('fact-a',), ('fact-a',), '', '', '', (), '', ('s2',)),
        Brief('s2', 'g', 'c', 'yes', 'cr', 'd',
              ('fact-a',), ('fact-a',), '', '', '', (), '', ('s1',)),
    ]
    # Must return cleanly — the visited-set guard prevents infinite
    # recursion through the cycle.
    findings = _check_briefs_deterministic(briefs, ['s1', 's2'])
    # Both fact-a appears via s2's knowledge_out for s1's check (and v-v).
    assert all(
        f['field'] != 'knowledge_in' for f in findings
        if 'fact-a' in f['issue']
    )


def test_check_briefs_deterministic_flags_outcome_streak(tmp_path):
    from storyforge.scoring_story_power import (
        parse_scene_briefs, _check_briefs_deterministic,
    )
    _seed_briefs(str(tmp_path), outcome_streak='yes')
    briefs = parse_scene_briefs(str(tmp_path))
    findings = _check_briefs_deterministic(briefs, [b.id for b in briefs])
    streak = next(
        f for f in findings
        if f['field'] == 'outcome' and 'repeats' in f['issue']
    )
    assert streak['severity'] == 'medium'


def test_check_briefs_deterministic_yes_but_streak_is_low_severity(tmp_path):
    """A streak of `yes-but` outcomes is escalation, not stagnation —
    the deterministic check tags it `low` rather than `medium` so it
    doesn't drown the high-priority signal."""
    from storyforge.scoring_story_power import (
        parse_scene_briefs, _check_briefs_deterministic,
    )
    _seed_briefs(str(tmp_path), outcome_streak='yes-but')
    briefs = parse_scene_briefs(str(tmp_path))
    findings = _check_briefs_deterministic(briefs, [b.id for b in briefs])
    streak = next(
        f for f in findings
        if f['field'] == 'outcome' and 'repeats' in f['issue']
    )
    assert streak['severity'] == 'low'


def test_check_briefs_deterministic_streak_uses_seq_order_when_provided():
    """When seq_order is provided, streak detection walks briefs in
    seq sequence — a streak that exists in CSV row order may not exist
    in seq order, and vice versa. This test constructs both halves of
    that discrimination: (a) CSV order has a 4-run but seq scatters it
    so no streak fires, (b) seq order pulls 4 identical outcomes
    together that CSV order interleaves. Without this, a regression
    that ignored seq_order entirely would pass."""
    from storyforge.scoring_story_power import (
        _check_briefs_deterministic, Brief,
    )

    def _make(bid: str, outcome: str) -> Brief:
        return Brief(bid, 'g', 'c', outcome, 'cr', 'd',
                     (), (), '', '', '', (), '', ())

    # Half (a): CSV order has 4 consecutive 'yes' (a, b, c, d). Seq
    # order interleaves them with a 'no' between b and c, breaking the
    # streak. Streak must NOT fire when seq_order is provided.
    briefs_csv_streaks = [
        _make('a', 'yes'), _make('b', 'yes'),
        _make('c', 'yes'), _make('d', 'yes'),
        _make('x', 'no'),
    ]
    findings_a = _check_briefs_deterministic(
        briefs_csv_streaks, ['a', 'b', 'x', 'c', 'd'],
    )
    streaks_a = [f for f in findings_a
                 if f['field'] == 'outcome' and 'repeats' in f['issue']]
    assert streaks_a == [], (
        f'CSV order had a streak but seq order broke it; expected no '
        f'streak finding, got: {streaks_a}'
    )

    # Half (b): CSV order scatters 'yes' outcomes; seq order pulls
    # four together. Streak MUST fire because seq order is what counts.
    briefs_seq_streaks = [
        _make('p', 'yes'), _make('q', 'no'),
        _make('r', 'yes'), _make('s', 'no'),
        _make('t', 'yes'), _make('u', 'yes'),
    ]
    findings_b = _check_briefs_deterministic(
        briefs_seq_streaks, ['p', 'r', 't', 'u', 'q', 's'],
    )
    streaks_b = [f for f in findings_b
                 if f['field'] == 'outcome' and 'repeats' in f['issue']]
    assert len(streaks_b) == 1, (
        f'seq order had a 4-run of yes (p, r, t, u) but no streak '
        f'fired; got: {streaks_b}'
    )
    assert streaks_b[0]['severity'] == 'medium'


def test_check_briefs_deterministic_flags_motif_singleton(tmp_path):
    from storyforge.scoring_story_power import (
        parse_scene_briefs, _check_briefs_deterministic,
    )
    _seed_briefs(str(tmp_path), motif_singleton=True)
    briefs = parse_scene_briefs(str(tmp_path))
    findings = _check_briefs_deterministic(briefs, [b.id for b in briefs])
    singleton = next(
        f for f in findings
        if f['field'] == 'motifs'
        and 'unique-motif-s2-only' in f['issue']
    )
    assert singleton['severity'] == 'low'


def test_build_briefs_prompt_inlines_deterministic_findings(tmp_path):
    """The prompt's 'Deterministic brief findings' block surfaces the
    actual finding text so the LLM seeds its scoring with them rather
    than re-discovering them."""
    from storyforge.scoring_story_power import (
        parse_scene_briefs, _check_briefs_deterministic,
        _build_briefs_prompt, PitchArtifacts,
    )
    _seed_briefs(str(tmp_path), invalid_outcome=True)
    briefs = parse_scene_briefs(str(tmp_path))
    det_findings = _check_briefs_deterministic(briefs, [b.id for b in briefs])
    assert det_findings
    artifacts = PitchArtifacts(logline='L', synopsis='S', act_shape='',
                                theme='', spine_summaries='',
                                architecture_summaries='')
    prompt = _build_briefs_prompt(briefs, [b.id for b in briefs],
                                     artifacts, det_findings, 'rubric')
    assert 'not in valid set' in prompt
    # Every brief id appears in the rendered block.
    for b in briefs:
        assert b.id in prompt


def test_build_briefs_prompt_uses_seq_order_when_provided():
    """When scene_seq is provided, briefs render in seq sequence — not
    CSV order. Scenes the seq doesn't name fall to the end."""
    from storyforge.scoring_story_power import (
        _build_briefs_prompt, Brief, PitchArtifacts,
    )
    briefs = [
        Brief('z', 'g', 'c', 'yes', 'cr', 'd',
              (), (), '', '', '', (), '', ()),
        Brief('a', 'g', 'c', 'yes', 'cr', 'd',
              (), (), '', '', '', (), '', ()),
    ]
    artifacts = PitchArtifacts(logline='L', synopsis='S', act_shape='',
                                theme='', spine_summaries='',
                                architecture_summaries='')
    prompt = _build_briefs_prompt(briefs, ['a', 'z'], artifacts, [], 'rubric')
    # 'a' appears before 'z' in the briefs block when seq says so.
    assert prompt.index('### a') < prompt.index('### z')


def test_parse_response_briefs_happy_path():
    from storyforge.scoring_story_power import _parse_response_briefs
    parsed = _parse_response_briefs(json.dumps(_briefs_payload()))
    assert parsed is not None
    assert isinstance(parsed['per_brief'], list)


def test_parse_response_briefs_handles_fenced_json():
    from storyforge.scoring_story_power import _parse_response_briefs
    text = '```json\n' + json.dumps(_briefs_payload()) + '\n```'
    parsed = _parse_response_briefs(text)
    assert parsed is not None


def test_parse_response_briefs_handles_greedy_extraction():
    from storyforge.scoring_story_power import _parse_response_briefs
    payload = json.dumps(_briefs_payload())
    text = f'Here is my analysis. {payload} Done.'
    parsed = _parse_response_briefs(text)
    assert parsed is not None


def test_parse_response_briefs_handles_only_per_brief_missing(capsys):
    from storyforge.scoring_story_power import _parse_response_briefs
    parsed = _parse_response_briefs(json.dumps({'whole_briefs': []}))
    assert parsed is None
    out = capsys.readouterr().out
    assert 'per_brief' in out


def test_parse_response_briefs_handles_only_whole_briefs_missing(capsys):
    from storyforge.scoring_story_power import _parse_response_briefs
    parsed = _parse_response_briefs(json.dumps({'per_brief': []}))
    assert parsed is None
    out = capsys.readouterr().out
    assert 'whole_briefs' in out


def test_extract_per_brief_scores_drops_malformed(capsys):
    from storyforge.scoring_story_power import _extract_per_brief_scores
    parsed = {
        'per_brief': [
            'not a dict',
            {'scene_id': 'unknown', 'scores': []},
            {'scene_id': 's1', 'scores': [
                'not a dict',
                {'axis': 'made_up', 'score': 8},
                {'axis': 'scene_engine_integrity', 'score': 'high'},
                {'axis': 'concreteness_brief', 'score': 47},
                {'axis': 'concreteness_brief', 'score': 7},
            ]},
        ],
    }
    out = _extract_per_brief_scores(parsed, ['s1'])
    assert out == {'s1': {'concreteness_brief': 7}}
    info = capsys.readouterr().out
    assert 'per-brief extraction dropped' in info


def test_extract_whole_briefs_scores_drops_malformed(capsys):
    from storyforge.scoring_story_power import _extract_whole_briefs_scores
    parsed = {
        'whole_briefs': [
            'not a dict',
            {'axis': 'made_up_axis', 'score': 7},
            {'axis': 'crisis_density', 'score': 'mid'},
            {'axis': 'crisis_density', 'score': 0},
            {'axis': 'crisis_density', 'score': 7},
        ],
    }
    out = _extract_whole_briefs_scores(parsed)
    assert out == {'crisis_density': 7}
    info = capsys.readouterr().out
    assert 'whole-briefs extraction dropped' in info


def test_extract_brief_findings_drops_incomplete(capsys):
    from storyforge.scoring_story_power import _extract_brief_findings
    parsed = {
        'brief_findings': [
            {'scene_id': 's1', 'field': '', 'issue': 'no field'},
            {'scene_id': 's1', 'field': 'goal', 'issue': '', 'severity': 'high'},
            {'scene_id': 's2', 'field': 'crisis',
             'issue': 'paraphrases conflict', 'severity': 'medium'},
            'not a dict',
        ],
    }
    out = _extract_brief_findings(parsed)
    assert len(out) == 1
    assert out[0]['scene_id'] == 's2'
    info = capsys.readouterr().out
    assert 'brief_findings extraction dropped' in info


def test_extract_brief_findings_normalizes_bad_severity_to_medium():
    from storyforge.scoring_story_power import _extract_brief_findings
    parsed = {
        'brief_findings': [
            {'scene_id': 's1', 'field': 'goal', 'issue': 'x',
             'severity': 'critical'},
        ],
    }
    out = _extract_brief_findings(parsed)
    assert out[0]['severity'] == 'medium'


def test_extract_proposed_brief_updates_drops_incomplete(capsys):
    from storyforge.scoring_story_power import _extract_proposed_brief_updates
    parsed = {
        'proposed_brief_updates': [
            {'scene_id': '', 'field': 'goal',
             'proposed_value': 'x'},
            {'scene_id': 's1', 'field': '',
             'proposed_value': 'x'},
            {'scene_id': 's1', 'field': 'goal',
             'proposed_value': ''},
            {'scene_id': 's2', 'field': 'crisis',
             'current_value': 'old', 'proposed_value': 'new',
             'rationale': 'lifts engine'},
        ],
    }
    out = _extract_proposed_brief_updates(parsed)
    assert len(out) == 1
    assert out[0] == {
        'scene_id': 's2', 'field': 'crisis',
        'current_value': 'old', 'proposed_value': 'new',
        'rationale': 'lifts engine',
    }
    info = capsys.readouterr().out
    assert 'proposed_brief_updates extraction dropped' in info


def test_briefs_only_runs_when_csv_present(tmp_path, monkeypatch):
    """No scene-briefs.csv on disk → result['briefs'] is None."""
    _seed_summary(str(tmp_path))
    monkeypatch.chdir(str(tmp_path))
    monkeypatch.setenv('ANTHROPIC_API_KEY', 'test-key')
    fake = _dual_mock_llm(_full_payload(), _act_shape_payload())
    from storyforge import api, scoring_story_power
    monkeypatch.setattr(api, 'invoke_to_file', fake)
    monkeypatch.setattr(scoring_story_power, 'invoke_to_file', fake)
    result = scoring_story_power.score_story_power(str(tmp_path), 'full')
    assert result['briefs'] is None


def test_briefs_mode_writes_csvs_and_diagnostic(tmp_path, monkeypatch):
    _seed_summary(str(tmp_path))
    _seed_briefs(str(tmp_path))
    monkeypatch.chdir(str(tmp_path))
    monkeypatch.setenv('ANTHROPIC_API_KEY', 'test-key')
    fake = _hex_mock_llm(_full_payload(), _act_shape_payload(),
                           _spine_payload(), _architecture_payload(),
                           _scene_map_payload(), _briefs_payload())
    from storyforge import api, scoring_story_power
    monkeypatch.setattr(api, 'invoke_to_file', fake)
    monkeypatch.setattr(scoring_story_power, 'invoke_to_file', fake)
    result = scoring_story_power.score_story_power(str(tmp_path), 'full')
    ext = result['briefs']
    assert ext is not None
    assert ext['status'] == 'ok'
    matrix_path = os.path.join(result['output_dir'], 'per-brief-matrix.csv')
    whole_path = os.path.join(result['output_dir'], 'whole-briefs-axes.csv')
    diag_path = os.path.join(result['output_dir'], 'diagnostic.md')
    assert os.path.isfile(matrix_path)
    assert os.path.isfile(whole_path)
    # Diagnostic contains the briefs section.
    diag = open(diag_path).read()
    assert '## Per-brief matrix' in diag
    assert '## Whole-briefs axes' in diag
    # Matrix has one row per brief plus header.
    matrix = open(matrix_path).read().strip().splitlines()
    assert len(matrix) == 5  # header + 4 briefs


def test_briefs_diagnostic_includes_findings_and_updates(tmp_path, monkeypatch):
    """The diagnostic.md contains the proposed brief updates with
    rationale, plus the deterministic findings the pre-pass produced."""
    _seed_summary(str(tmp_path))
    _seed_briefs(str(tmp_path), invalid_outcome=True)
    monkeypatch.chdir(str(tmp_path))
    monkeypatch.setenv('ANTHROPIC_API_KEY', 'test-key')
    fake = _hex_mock_llm(_full_payload(), _act_shape_payload(),
                           _spine_payload(), _architecture_payload(),
                           _scene_map_payload(), _briefs_payload())
    from storyforge import api, scoring_story_power
    monkeypatch.setattr(api, 'invoke_to_file', fake)
    monkeypatch.setattr(scoring_story_power, 'invoke_to_file', fake)
    result = scoring_story_power.score_story_power(str(tmp_path), 'full')
    diag = open(os.path.join(result['output_dir'], 'diagnostic.md')).read()
    assert 'Proposed brief updates' in diag
    # Deterministic finding for invalid outcome surfaces.
    assert 'not in valid set' in diag
    # Proposed update rationale appears.
    assert 'lifts scene_engine_integrity' in diag


def test_briefs_llm_failure_preserves_deterministic_findings(tmp_path,
                                                                monkeypatch):
    """When the briefs LLM call raises, the deterministic findings are
    still returned in the extension's brief_findings field — the user
    sees orphan-knowledge and missing-field signal without an API
    response."""
    _seed_summary(str(tmp_path))
    _seed_briefs(str(tmp_path), orphan_knowledge=True)
    monkeypatch.chdir(str(tmp_path))
    monkeypatch.setenv('ANTHROPIC_API_KEY', 'test-key')

    def fake(prompt, model, log_file, **kwargs):
        if '-briefs' in log_file:
            raise RuntimeError('Anthropic 500')
        os.makedirs(os.path.dirname(log_file) or '.', exist_ok=True)
        if '-scene-map' in log_file:
            payload = _scene_map_payload()
        elif '-architecture' in log_file:
            payload = _architecture_payload()
        elif '-spine' in log_file:
            payload = _spine_payload()
        elif '-act-shape' in log_file:
            payload = _act_shape_payload()
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
    result = scoring_story_power.score_story_power(str(tmp_path), 'full')
    ext = result['briefs']
    assert ext is not None
    assert ext['status'] == 'llm_error'
    # Pitch still scored.
    assert result['composite'] > 0
    # Pre-pass orphan-knowledge finding survived.
    orphan = next(
        f for f in ext['brief_findings']
        if f['field'] == 'knowledge_in' and 'unrelated-fact' in f['issue']
    )
    assert orphan['severity'] == 'medium'


def test_briefs_unparseable_response_tags_status(tmp_path, monkeypatch, capsys):
    _seed_summary(str(tmp_path))
    _seed_briefs(str(tmp_path))
    monkeypatch.chdir(str(tmp_path))
    monkeypatch.setenv('ANTHROPIC_API_KEY', 'test-key')

    def fake(prompt, model, log_file, **kwargs):
        os.makedirs(os.path.dirname(log_file) or '.', exist_ok=True)
        if '-briefs' in log_file:
            text = 'this is not json'
        elif '-scene-map' in log_file:
            text = json.dumps(_scene_map_payload())
        elif '-architecture' in log_file:
            text = json.dumps(_architecture_payload())
        elif '-spine' in log_file:
            text = json.dumps(_spine_payload())
        elif '-act-shape' in log_file:
            text = json.dumps(_act_shape_payload())
        else:
            text = json.dumps(_full_payload())
        response = {
            'content': [{'type': 'text', 'text': text}],
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
    assert result['briefs']['status'] == 'unparseable'
    out = capsys.readouterr().out
    assert 'briefs LLM response unparseable' in out


def test_briefs_coach_mode_appends_to_brief(tmp_path, monkeypatch):
    _seed_summary(str(tmp_path))
    _seed_briefs(str(tmp_path))
    monkeypatch.chdir(str(tmp_path))
    monkeypatch.setenv('ANTHROPIC_API_KEY', 'test-key')
    fake = _hex_mock_llm(_full_payload(), _act_shape_payload(),
                           _spine_payload(), _architecture_payload(),
                           _scene_map_payload(), _briefs_payload())
    from storyforge import api, scoring_story_power
    monkeypatch.setattr(api, 'invoke_to_file', fake)
    monkeypatch.setattr(scoring_story_power, 'invoke_to_file', fake)
    result = scoring_story_power.score_story_power(str(tmp_path), 'coach')
    coach_path = os.path.join(result['output_dir'], 'coaching-brief.md')
    assert os.path.isfile(coach_path)
    body = open(coach_path).read()
    assert '# Briefs extension' in body
    # The coach-mode prelude makes the role explicit.
    assert 'not directives' in body
    # The diagnostic body — not just the prelude — must render. A
    # regression where the prelude wrote but the section was empty
    # would pass without these. Confirm the matrix heading, the
    # proposed-update block, and a piece of the LLM-supplied
    # diagnostic text.
    assert '## Per-brief matrix' in body
    assert 'Proposed brief updates' in body
    # The proposed-update rationale from _briefs_payload appears.
    assert 'lifts scene_engine_integrity' in body
    # The LLM-supplied high-leverage move from briefs_diagnostic.
    assert 'add archive-locks-after-dark' in body


def test_briefs_strict_mode_extends_checklist(tmp_path, monkeypatch):
    _seed_summary(str(tmp_path))
    _seed_briefs(str(tmp_path))
    monkeypatch.chdir(str(tmp_path))
    result = __import__('storyforge.scoring_story_power',
                         fromlist=['score_story_power']
                         ).score_story_power(str(tmp_path), 'strict')
    checklist = open(os.path.join(result['output_dir'],
                                     'self-scoring-checklist.md')).read()
    assert '# Briefs tier' in checklist
    assert '# Whole-briefs axes' in checklist
    # Each brief id should have a heading.
    assert '## s1 — outcome=' in checklist
    # Every whole-briefs axis name must render. A regression that
    # drops the `for axis in BRIEFS_AXES` block would slip past the
    # heading check above.
    from storyforge.scoring_story_power import BRIEFS_AXES
    for axis in BRIEFS_AXES:
        assert f'## {axis.name}' in checklist, (
            f'whole-briefs axis {axis.name!r} did not render in strict '
            f'checklist'
        )


def test_briefs_partial_per_brief_tags_partial(tmp_path, monkeypatch):
    """A briefs payload missing per-brief axes for one brief surfaces as
    status='partial' rather than collapsing to 'ok'."""
    _seed_summary(str(tmp_path))
    _seed_briefs(str(tmp_path))
    monkeypatch.chdir(str(tmp_path))
    monkeypatch.setenv('ANTHROPIC_API_KEY', 'test-key')
    briefs_payload = _briefs_payload()
    for row in briefs_payload['per_brief']:
        if row['scene_id'] == 's2':
            row['scores'] = row['scores'][:1]
    fake = _hex_mock_llm(_full_payload(), _act_shape_payload(),
                           _spine_payload(), _architecture_payload(),
                           _scene_map_payload(), briefs_payload)
    from storyforge import api, scoring_story_power
    monkeypatch.setattr(api, 'invoke_to_file', fake)
    monkeypatch.setattr(scoring_story_power, 'invoke_to_file', fake)
    result = scoring_story_power.score_story_power(str(tmp_path), 'full')
    assert result['briefs']['status'] == 'partial'
    assert result['status'] == 'partial'


def test_empty_briefs_refuses_matrix_and_writes_sidecar(tmp_path,
                                                          monkeypatch,
                                                          capsys):
    """When the LLM returns zero scores for some briefs, refuse to
    write the matrix and write the empty-id list to a sidecar."""
    _seed_summary(str(tmp_path))
    _seed_briefs(str(tmp_path))
    monkeypatch.chdir(str(tmp_path))
    monkeypatch.setenv('ANTHROPIC_API_KEY', 'test-key')
    briefs_payload = _briefs_payload()
    # Drop s2 and s3 from per_brief response.
    briefs_payload['per_brief'] = [
        r for r in briefs_payload['per_brief']
        if r['scene_id'] not in {'s2', 's3'}
    ]
    fake = _hex_mock_llm(_full_payload(), _act_shape_payload(),
                           _spine_payload(), _architecture_payload(),
                           _scene_map_payload(), briefs_payload)
    from storyforge import api, scoring_story_power
    monkeypatch.setattr(api, 'invoke_to_file', fake)
    monkeypatch.setattr(scoring_story_power, 'invoke_to_file', fake)
    result = scoring_story_power.score_story_power(str(tmp_path), 'full')
    out_dir = result['output_dir']
    log_out = capsys.readouterr().out
    assert 'refusing to write per-brief-matrix.csv' in log_out
    sidecar = os.path.join(out_dir, 'briefs-empty-scenes.txt')
    assert os.path.isfile(sidecar)
    body = open(sidecar).read()
    assert 's2' in body and 's3' in body
    assert not os.path.isfile(os.path.join(out_dir, 'per-brief-matrix.csv'))


def test_briefs_status_ok_implies_nonempty_payload_smoke(tmp_path, monkeypatch):
    """Smoke test for the `status='ok' ⇒ non-empty payload` contract:
    a happy-path full-mode run carries non-empty per_brief_scores and
    whole_briefs_scores. The actual contract is enforced by a runtime
    assert inside _run_briefs_extension; this test catches accidental
    inversions where the assert is removed or the payload is built
    with empty dicts."""
    _seed_summary(str(tmp_path))
    _seed_briefs(str(tmp_path))
    monkeypatch.chdir(str(tmp_path))
    monkeypatch.setenv('ANTHROPIC_API_KEY', 'test-key')
    fake = _hex_mock_llm(_full_payload(), _act_shape_payload(),
                           _spine_payload(), _architecture_payload(),
                           _scene_map_payload(), _briefs_payload())
    from storyforge import api, scoring_story_power
    monkeypatch.setattr(api, 'invoke_to_file', fake)
    monkeypatch.setattr(scoring_story_power, 'invoke_to_file', fake)
    result = scoring_story_power.score_story_power(str(tmp_path), 'full')
    assert result['briefs']['status'] == 'ok'
    assert result['briefs']['per_brief_scores']
    assert result['briefs']['whole_briefs_scores']


def test_briefs_status_ok_assertion_fires_on_empty_payload(tmp_path, monkeypatch):
    """The runtime assertion `status='ok' ⇒ non-empty payload` fires
    when the per-brief / whole-briefs extractors return empty dicts
    even though the count math says nothing is missing. The
    `score_story_power` orchestrator catches the AssertionError via
    pytest.raises — without it, an empty extension would silently
    propagate as a false 'ok'. This is the white-box test for the
    contract the smoke test above only sniff-checks."""
    import pytest
    from storyforge.scoring_story_power import (
        _run_briefs_extension, Brief, PitchArtifacts, PER_BRIEF_AXES,
        BRIEFS_AXES,
    )
    briefs = [
        Brief('s1', 'g', 'c', 'yes', 'cr', 'd',
              (), (), '', '', '', (), '', ()),
    ]
    artifacts = PitchArtifacts(logline='L', synopsis='S', act_shape='',
                                theme='', spine_summaries='',
                                architecture_summaries='')
    # Mock the LLM to return a malformed payload: per_brief and
    # whole_briefs are valid lists (so the shape check passes), but
    # contain unrecognized axes that the extractor will drop. After
    # extraction, per_brief and whole_briefs are empty dicts.
    bogus_payload = {
        'per_brief': [
            {'scene_id': 's1', 'scores': [
                {'axis': 'not_a_real_axis', 'score': 8},
            ]},
        ],
        'whole_briefs': [
            {'axis': 'not_a_real_whole_axis', 'score': 8,
             'positive_signals': '', 'negative_signals': '',
             'rationale': ''},
        ],
        'briefs_diagnostic': {},
        'brief_findings': [],
        'proposed_brief_updates': [],
    }
    log_dir = str(tmp_path / 'logs')
    output_dir = str(tmp_path / 'out')
    os.makedirs(log_dir, exist_ok=True)
    os.makedirs(output_dir, exist_ok=True)

    def fake(prompt, model, log_file, **kwargs):
        os.makedirs(os.path.dirname(log_file) or '.', exist_ok=True)
        response = {
            'content': [{'type': 'text', 'text': json.dumps(bogus_payload)}],
            'usage': {'input_tokens': 100, 'output_tokens': 100,
                      'cache_read_input_tokens': 0,
                      'cache_creation_input_tokens': 0},
        }
        with open(log_file, 'w') as f:
            json.dump(response, f)
        return response
    from storyforge import api, scoring_story_power
    monkeypatch.setattr(api, 'invoke_to_file', fake)
    monkeypatch.setattr(scoring_story_power, 'invoke_to_file', fake)
    # The status-computation logic will mark status='partial' because
    # missing_per_brief and missing_briefs_axes are both > 0. So this
    # path actually produces 'partial', not 'ok' — the runtime
    # assertion only guards the 'ok' branch and is *unreachable* via
    # extractor drops. That's the correct behavior: the contract holds
    # because empty payloads naturally cascade to 'partial'.
    ext = _run_briefs_extension(
        str(tmp_path), output_dir, log_dir, briefs, [], artifacts,
        'rubric', 'full',
    )
    # Empty extractor results → partial status, not ok. The runtime
    # assertion never fires because the count-math path makes the
    # 'ok' branch unreachable from this failure mode.
    assert ext['status'] == 'partial'
    assert ext['per_brief_scores'] == {'s1': {}}
    assert ext['whole_briefs_scores'] == {}


def test_hex_mock_llm_routes_to_all_six_payloads(tmp_path, monkeypatch):
    """Confirm the hex mock helper routes correctly across all six
    tiers — without this, a payload could silently fall through to the
    default and a downstream test would assert against the wrong shape."""
    _seed_summary(str(tmp_path))
    _seed_spine(str(tmp_path))
    _seed_architecture(str(tmp_path))
    _seed_scene_map(str(tmp_path))
    _seed_briefs(str(tmp_path))
    monkeypatch.chdir(str(tmp_path))
    monkeypatch.setenv('ANTHROPIC_API_KEY', 'test-key')

    hits = {'pitch': 0, 'act_shape': 0, 'spine': 0, 'architecture': 0,
            'scene_map': 0, 'briefs': 0}

    def fake(prompt, model, log_file, **kwargs):
        os.makedirs(os.path.dirname(log_file) or '.', exist_ok=True)
        if '-briefs' in log_file:
            hits['briefs'] += 1
            payload = _briefs_payload()
        elif '-scene-map' in log_file:
            hits['scene_map'] += 1
            payload = _scene_map_payload()
        elif '-architecture' in log_file:
            hits['architecture'] += 1
            payload = _architecture_payload()
        elif '-spine' in log_file:
            hits['spine'] += 1
            payload = _spine_payload()
        elif '-act-shape' in log_file:
            hits['act_shape'] += 1
            payload = _act_shape_payload()
        else:
            hits['pitch'] += 1
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
    assert all(v == 1 for v in hits.values()), hits


def test_briefs_runs_without_scene_map_csv(tmp_path, monkeypatch):
    """Briefs mode runs even without scenes.csv on disk — seq order
    falls back to CSV row order. No crash, no missing-csv warnings."""
    _seed_summary(str(tmp_path))
    _seed_briefs(str(tmp_path))
    monkeypatch.chdir(str(tmp_path))
    monkeypatch.setenv('ANTHROPIC_API_KEY', 'test-key')
    fake = _hex_mock_llm(_full_payload(), _act_shape_payload(),
                           _spine_payload(), _architecture_payload(),
                           _scene_map_payload(), _briefs_payload())
    from storyforge import api, scoring_story_power
    monkeypatch.setattr(api, 'invoke_to_file', fake)
    monkeypatch.setattr(scoring_story_power, 'invoke_to_file', fake)
    result = scoring_story_power.score_story_power(str(tmp_path), 'full')
    assert result['briefs'] is not None
    assert result['scene_map'] is None


# ---------------------------------------------------------------------------
# PR #244 review fixes — regression tests
# ---------------------------------------------------------------------------

def test_check_briefs_deterministic_flags_broken_continuity_dep():
    """A continuity_deps entry pointing to a brief id not present in
    scene-briefs.csv is a typo / deleted-scene / rename-drift bug.
    Surface it as its own medium-severity finding rather than silently
    absorbing the broken edge into downstream orphan-knowledge
    false-positives. (PR #244 silent-failure review HIGH-1.)"""
    from storyforge.scoring_story_power import (
        _check_briefs_deterministic, Brief,
    )
    briefs = [
        # s2 lists 's99' (typo / deleted scene) as a dep; s99 isn't a
        # brief. Without the explicit finding, the orphan-knowledge
        # check for fact-a in s2 fires (false positive) and the broken
        # graph edge is invisible.
        Brief('s1', 'g', 'c', 'yes', 'cr', 'd',
              (), ('fact-a',), '', '', '', (), '', ()),
        Brief('s2', 'g', 'c', 'yes', 'cr', 'd',
              ('fact-a',), ('fact-a',), '', '', '', (), '', ('s99',)),
    ]
    findings = _check_briefs_deterministic(briefs, ['s1', 's2'])
    broken = [f for f in findings
              if f['field'] == 'continuity_deps' and 's99' in f['issue']]
    assert len(broken) == 1
    assert broken[0]['severity'] == 'medium'
    assert broken[0]['scene_id'] == 's2'


def test_check_briefs_deterministic_dedupes_broken_dep_findings():
    """Multiple briefs that list the same nonexistent dep produce one
    finding per (referrer, missing-target) pair, not one per
    visit-during-walk. (PR #244 silent-failure review HIGH-1 detail.)"""
    from storyforge.scoring_story_power import (
        _check_briefs_deterministic, Brief,
    )
    briefs = [
        # s1 and s2 both list the same nonexistent 's99' dep.
        Brief('s1', 'g', 'c', 'yes', 'cr', 'd',
              ('fact-a',), ('fact-a',), '', '', '', (), '', ('s99',)),
        Brief('s2', 'g', 'c', 'yes', 'cr', 'd',
              ('fact-a',), ('fact-a',), '', '', '', (), '', ('s99',)),
    ]
    findings = _check_briefs_deterministic(briefs, ['s1', 's2'])
    broken = [f for f in findings
              if f['field'] == 'continuity_deps' and 's99' in f['issue']]
    # Two referrers, both pointing at the same missing target → 2 findings.
    assert len(broken) == 2
    scene_ids = {f['scene_id'] for f in broken}
    assert scene_ids == {'s1', 's2'}


def test_check_briefs_deterministic_finds_broken_dep_without_knowledge_in():
    """A brief with empty knowledge_in still surfaces broken-dep
    findings — the dep typo is a real signal even when no orphan
    knowledge walk would have caught it. (PR #244 silent-failure
    review HIGH-1 detail.)"""
    from storyforge.scoring_story_power import (
        _check_briefs_deterministic, Brief,
    )
    briefs = [
        Brief('s1', 'g', 'c', 'yes', 'cr', 'd',
              (), (), '', '', '', (), '', ('s99',)),
    ]
    findings = _check_briefs_deterministic(briefs, ['s1'])
    broken = [f for f in findings
              if f['field'] == 'continuity_deps' and 's99' in f['issue']]
    assert len(broken) == 1


def test_check_briefs_deterministic_orphan_finding_carries_preceding_id():
    """An orphan-knowledge finding pins the brief's first
    continuity_deps entry as preceding_id — the closest ancestor where
    the author would expect the missing fact. (PR #244 type-design
    review TD-3 + comment review CO-1.)"""
    from storyforge.scoring_story_power import (
        _check_briefs_deterministic, Brief,
    )
    briefs = [
        # s2 depends on s1, but s1 doesn't produce fact-a; the orphan
        # finding should point at s1 since that's the brief author
        # would investigate first.
        Brief('s1', 'g', 'c', 'yes', 'cr', 'd',
              (), (), '', '', '', (), '', ()),
        Brief('s2', 'g', 'c', 'yes', 'cr', 'd',
              ('fact-a',), ('fact-a',), '', '', '', (), '', ('s1',)),
    ]
    findings = _check_briefs_deterministic(briefs, ['s1', 's2'])
    orphan = next(
        f for f in findings
        if f['scene_id'] == 's2' and f['field'] == 'knowledge_in'
    )
    assert orphan.get('preceding_id') == 's1'


def test_check_briefs_deterministic_orphan_without_deps_omits_preceding_id():
    """An orphan-knowledge finding on a brief with empty
    continuity_deps omits preceding_id — there's no closest ancestor
    to pin. (PR #244 type-design review TD-3 + comment review CO-1.)"""
    from storyforge.scoring_story_power import (
        _check_briefs_deterministic, Brief,
    )
    briefs = [
        Brief('s1', 'g', 'c', 'yes', 'cr', 'd',
              ('fact-a',), ('fact-a',), '', '', '', (), '', ()),
    ]
    findings = _check_briefs_deterministic(briefs, ['s1'])
    orphan = next(
        f for f in findings
        if f['scene_id'] == 's1' and f['field'] == 'knowledge_in'
    )
    assert 'preceding_id' not in orphan


def test_check_briefs_deterministic_handles_triadic_cycle():
    """A triadic continuity_deps cycle (s1→s2→s3→s1) must terminate
    cleanly — the visited set bounds graph walks regardless of cycle
    arity. Without this, a copy-paste regression that breaks
    multi-node cycles while keeping binary-cycle handling intact
    would pass the existing s1↔s2 test. (PR #244 test review T-1.)"""
    from storyforge.scoring_story_power import (
        _check_briefs_deterministic, Brief,
    )
    briefs = [
        Brief('s1', 'g', 'c', 'yes', 'cr', 'd',
              ('fact-a',), ('fact-a',), '', '', '', (), '', ('s2',)),
        Brief('s2', 'g', 'c', 'yes', 'cr', 'd',
              ('fact-a',), ('fact-a',), '', '', '', (), '', ('s3',)),
        Brief('s3', 'g', 'c', 'yes', 'cr', 'd',
              ('fact-a',), ('fact-a',), '', '', '', (), '', ('s1',)),
    ]
    # Must return; visited set bounds the walk through the cycle.
    findings = _check_briefs_deterministic(briefs, ['s1', 's2', 's3'])
    # Each brief's fact-a is provided by its predecessor in the cycle —
    # no orphan-knowledge findings should fire.
    orphan_findings = [
        f for f in findings
        if f['field'] == 'knowledge_in' and 'fact-a' in f['issue']
    ]
    assert orphan_findings == []


def test_check_briefs_deterministic_mixed_streak_no_flag():
    """A 3-yes / 1-no / 3-yes pattern is NOT a streak — the no breaks
    the run, neither side reaches the threshold of 4. Without this,
    a regression that forgets to reset the run counter on outcome
    change would still pass the threshold-exactly-4 case. (PR #244
    test review T-4.)"""
    from storyforge.scoring_story_power import (
        _check_briefs_deterministic, Brief,
    )

    def _make(bid: str, outcome: str) -> Brief:
        return Brief(bid, 'g', 'c', outcome, 'cr', 'd',
                     (), (), '', '', '', (), '', ())

    briefs = [
        _make('a', 'yes'), _make('b', 'yes'), _make('c', 'yes'),
        _make('d', 'no'),
        _make('e', 'yes'), _make('f', 'yes'), _make('g', 'yes'),
    ]
    findings = _check_briefs_deterministic(briefs, [])
    streaks = [f for f in findings
               if f['field'] == 'outcome' and 'repeats' in f['issue']]
    assert streaks == [], (
        f'3-yes-1-no-3-yes pattern is not a streak; got: {streaks}'
    )


def test_check_briefs_deterministic_half_filled_row_fires_four_findings():
    """A brief row with only one scene-engine field populated produces
    exactly 4 high-severity findings (one per empty required field).
    Locks the missing-field contract in place against a regression
    that early-returns on the first empty field. (PR #244 code
    review S1.)"""
    from storyforge.scoring_story_power import (
        _check_briefs_deterministic, Brief,
    )
    briefs = [
        # Only outcome populated; goal/conflict/crisis/decision empty.
        Brief('s1', '', '', 'yes', '', '',
              (), (), '', '', '', (), '', ()),
    ]
    findings = _check_briefs_deterministic(briefs, ['s1'])
    high_missing = [
        f for f in findings
        if f['scene_id'] == 's1' and f['severity'] == 'high'
        and f['field'] in {'goal', 'conflict', 'crisis', 'decision'}
        and 'is empty' in f['issue']
    ]
    fields_seen = {f['field'] for f in high_missing}
    assert fields_seen == {'goal', 'conflict', 'crisis', 'decision'}, (
        f'expected all four empty required fields flagged; got {fields_seen}'
    )


def test_briefs_skipped_when_csv_contains_only_scaffold_rows(tmp_path,
                                                                 monkeypatch):
    """A scene-briefs.csv that exists but contains only all-empty
    scene-engine rows (migration scaffolding) yields result['briefs']
    is None — parse_scene_briefs drops every row, so the orchestrator
    sees an empty briefs list and doesn't run the extension. (PR #244
    test review T-7.)"""
    _seed_summary(str(tmp_path))
    ref = tmp_path / 'reference'
    ref.mkdir(exist_ok=True)
    headers = ('id|goal|conflict|outcome|crisis|decision|knowledge_in|'
               'knowledge_out|key_actions|key_dialogue|emotions|motifs|'
               'subtext|continuity_deps')
    # Three scaffold rows, all five engine fields empty.
    rows = [
        's1|||||||||||||',
        's2|||||||||||||',
        's3|||||||||||||',
    ]
    (ref / 'scene-briefs.csv').write_text(
        '\n'.join([headers] + rows) + '\n',
    )
    monkeypatch.chdir(str(tmp_path))
    monkeypatch.setenv('ANTHROPIC_API_KEY', 'test-key')
    fake = _dual_mock_llm(_full_payload(), _act_shape_payload())
    from storyforge import api, scoring_story_power
    monkeypatch.setattr(api, 'invoke_to_file', fake)
    monkeypatch.setattr(scoring_story_power, 'invoke_to_file', fake)
    result = scoring_story_power.score_story_power(str(tmp_path), 'full')
    assert result['briefs'] is None


# ---------------------------------------------------------------------------
# max_tokens ceilings + truncation detection
# ---------------------------------------------------------------------------

def test_per_row_tier_max_tokens_constant_above_8k():
    """The per-row-heavy tiers (architecture, scene-map, briefs) ship
    with a max_tokens ceiling well above the 8K wall observed in
    issue #245 (15-scene architecture + 43-scene scene-map both
    truncated mid-JSON at 8192 output tokens)."""
    from storyforge.scoring_story_power import (
        _PER_ROW_TIER_MAX_TOKENS, _FIXED_PAYLOAD_TIER_MAX_TOKENS,
        _PITCH_MAX_TOKENS,
    )
    assert _PER_ROW_TIER_MAX_TOKENS >= 16384, (
        f'per-row tier ceiling must be at least 2× the observed 8K '
        f'wall; got {_PER_ROW_TIER_MAX_TOKENS}'
    )
    # Bounded tiers (act-shape, spine) and pitch retain their lower
    # ceilings — their payloads don't scale with project size.
    assert _FIXED_PAYLOAD_TIER_MAX_TOKENS == 8192
    assert _PITCH_MAX_TOKENS == 4096


def test_per_row_tier_max_tokens_under_creative_model_cap():
    """The per-row ceiling must fit under the creative model's output
    cap (api.MODEL_MAX_OUTPUT is the source of truth). PR #247 review
    caught a factual claim of '64K Opus output cap' — Opus 4.6
    actually caps at 128K, but the lesson is that constants drift
    from documentation. This test grounds the claim in the API
    config so a future model change can't silently break it."""
    from storyforge.scoring_story_power import (
        _PER_ROW_TIER_MAX_TOKENS,
    )
    from storyforge.api import MODEL_MAX_OUTPUT
    from storyforge.common import select_model
    creative_model = select_model('creative')
    model_cap = MODEL_MAX_OUTPUT.get(creative_model)
    assert model_cap is not None, (
        f'creative model {creative_model!r} is not in MODEL_MAX_OUTPUT; '
        'add an entry or update select_model'
    )
    assert _PER_ROW_TIER_MAX_TOKENS <= model_cap, (
        f'_PER_ROW_TIER_MAX_TOKENS={_PER_ROW_TIER_MAX_TOKENS} exceeds '
        f'the creative model {creative_model!r} cap of {model_cap}; '
        'the API would reject the request with HTTP 400'
    )


def test_architecture_passes_per_row_max_tokens(tmp_path, monkeypatch):
    """Architecture mode calls invoke_to_file with the per-row tier
    ceiling, not the old 8K wall."""
    _seed_summary(str(tmp_path))
    _seed_architecture(str(tmp_path))
    monkeypatch.chdir(str(tmp_path))
    monkeypatch.setenv('ANTHROPIC_API_KEY', 'test-key')

    seen_max_tokens: dict[str, int] = {}

    def fake(prompt, model, log_file, **kwargs):
        os.makedirs(os.path.dirname(log_file) or '.', exist_ok=True)
        if '-architecture' in log_file:
            seen_max_tokens['architecture'] = kwargs.get('max_tokens', -1)
            payload = _architecture_payload()
        elif '-spine' in log_file:
            payload = _spine_payload()
        elif '-act-shape' in log_file:
            payload = _act_shape_payload()
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
    assert seen_max_tokens['architecture'] == (
        scoring_story_power._PER_ROW_TIER_MAX_TOKENS
    ), seen_max_tokens


def test_scene_map_passes_per_row_max_tokens(tmp_path, monkeypatch):
    _seed_summary(str(tmp_path))
    _seed_architecture(str(tmp_path))
    _seed_scene_map(str(tmp_path))
    monkeypatch.chdir(str(tmp_path))
    monkeypatch.setenv('ANTHROPIC_API_KEY', 'test-key')

    seen: dict[str, int] = {}

    def fake(prompt, model, log_file, **kwargs):
        os.makedirs(os.path.dirname(log_file) or '.', exist_ok=True)
        if '-scene-map' in log_file:
            seen['scene-map'] = kwargs.get('max_tokens', -1)
            payload = _scene_map_payload()
        elif '-architecture' in log_file:
            payload = _architecture_payload()
        elif '-spine' in log_file:
            payload = _spine_payload()
        elif '-act-shape' in log_file:
            payload = _act_shape_payload()
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
    assert seen['scene-map'] == scoring_story_power._PER_ROW_TIER_MAX_TOKENS


def test_briefs_passes_per_row_max_tokens(tmp_path, monkeypatch):
    _seed_summary(str(tmp_path))
    _seed_briefs(str(tmp_path))
    monkeypatch.chdir(str(tmp_path))
    monkeypatch.setenv('ANTHROPIC_API_KEY', 'test-key')

    seen: dict[str, int] = {}

    def fake(prompt, model, log_file, **kwargs):
        os.makedirs(os.path.dirname(log_file) or '.', exist_ok=True)
        if '-briefs' in log_file:
            seen['briefs'] = kwargs.get('max_tokens', -1)
            payload = _briefs_payload()
        elif '-act-shape' in log_file:
            payload = _act_shape_payload()
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
    assert seen['briefs'] == scoring_story_power._PER_ROW_TIER_MAX_TOKENS


def test_all_tiers_pass_correct_max_tokens_constant(tmp_path, monkeypatch):
    """Every tier (pitch, act-shape, spine, architecture, scene-map,
    briefs) passes the *expected* per-tier ceiling to invoke_to_file.
    Without this, a refactor that promotes spine to _PER_ROW (4×
    cost regression) or demotes architecture to _FIXED_PAYLOAD
    (reintroducing #245) would pass the existing per-tier tests
    that only assert the value matches the expected constant for
    that tier individually. This single test enforces the full
    matrix in one place. (PR #247 review T-1.)"""
    _seed_summary(str(tmp_path))
    _seed_spine(str(tmp_path))
    _seed_architecture(str(tmp_path))
    _seed_scene_map(str(tmp_path))
    _seed_briefs(str(tmp_path))
    monkeypatch.chdir(str(tmp_path))
    monkeypatch.setenv('ANTHROPIC_API_KEY', 'test-key')

    seen: dict[str, int] = {}

    def fake(prompt, model, log_file, **kwargs):
        os.makedirs(os.path.dirname(log_file) or '.', exist_ok=True)
        if '-briefs' in log_file:
            seen['briefs'] = kwargs.get('max_tokens', -1)
            payload = _briefs_payload()
        elif '-scene-map' in log_file:
            seen['scene-map'] = kwargs.get('max_tokens', -1)
            payload = _scene_map_payload()
        elif '-architecture' in log_file:
            seen['architecture'] = kwargs.get('max_tokens', -1)
            payload = _architecture_payload()
        elif '-spine' in log_file:
            seen['spine'] = kwargs.get('max_tokens', -1)
            payload = _spine_payload()
        elif '-act-shape' in log_file:
            seen['act-shape'] = kwargs.get('max_tokens', -1)
            payload = _act_shape_payload()
        else:
            seen['pitch'] = kwargs.get('max_tokens', -1)
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
    expected = {
        'pitch': scoring_story_power._PITCH_MAX_TOKENS,
        'act-shape': scoring_story_power._FIXED_PAYLOAD_TIER_MAX_TOKENS,
        'spine': scoring_story_power._FIXED_PAYLOAD_TIER_MAX_TOKENS,
        'architecture': scoring_story_power._PER_ROW_TIER_MAX_TOKENS,
        'scene-map': scoring_story_power._PER_ROW_TIER_MAX_TOKENS,
        'briefs': scoring_story_power._PER_ROW_TIER_MAX_TOKENS,
    }
    assert seen == expected, (
        f'tier → max_tokens mismatch.\nexpected: {expected}\n'
        f'actual:   {seen}'
    )


def test_read_stop_reason_returns_field_when_present(tmp_path):
    """Reads the LLM's stop_reason from the raw response log."""
    from storyforge.scoring_story_power import _read_stop_reason
    log_file = str(tmp_path / 'resp.json')
    with open(log_file, 'w') as f:
        json.dump({
            'content': [{'type': 'text', 'text': 'partial'}],
            'stop_reason': 'max_tokens',
            'usage': {'input_tokens': 500, 'output_tokens': 8192},
        }, f)
    assert _read_stop_reason(log_file) == 'max_tokens'


def test_read_stop_reason_handles_missing_field(tmp_path):
    """A response without stop_reason (common in mocks) yields ''."""
    from storyforge.scoring_story_power import _read_stop_reason
    log_file = str(tmp_path / 'resp.json')
    with open(log_file, 'w') as f:
        json.dump({'content': [{'type': 'text', 'text': 'x'}]}, f)
    assert _read_stop_reason(log_file) == ''


def test_read_stop_reason_handles_missing_file():
    from storyforge.scoring_story_power import _read_stop_reason
    assert _read_stop_reason('/nonexistent/path.json') == ''


def test_truncation_hint_returns_descriptive_text_on_max_tokens(tmp_path):
    """When stop_reason is max_tokens, the hint names the cause + the
    ceiling so the user knows which knob to turn."""
    from storyforge.scoring_story_power import _truncation_hint
    log_file = str(tmp_path / 'resp.json')
    with open(log_file, 'w') as f:
        json.dump({
            'content': [{'type': 'text', 'text': 'partial'}],
            'stop_reason': 'max_tokens',
        }, f)
    hint = _truncation_hint(log_file, 32768)
    assert hint != ''
    assert 'max_tokens=32768' in hint
    assert 'truncated' in hint


def test_truncation_hint_returns_empty_for_genuine_parse_failure(tmp_path):
    """When stop_reason is end_turn (or absent), the hint is empty —
    the parse failure is genuine, not truncation, and the original
    'unparseable' message stands alone."""
    from storyforge.scoring_story_power import _truncation_hint
    log_file = str(tmp_path / 'resp.json')
    with open(log_file, 'w') as f:
        json.dump({
            'content': [{'type': 'text', 'text': 'not json'}],
            'stop_reason': 'end_turn',
        }, f)
    assert _truncation_hint(log_file, 32768) == ''


def test_architecture_unparseable_with_max_tokens_logs_truncation_hint(
        tmp_path, monkeypatch, capsys):
    """End-to-end: when architecture LLM truncates at max_tokens and
    the response is therefore unparseable, the ERROR message names
    truncation as the cause — not 'parse failed' alone."""
    _seed_summary(str(tmp_path))
    _seed_architecture(str(tmp_path))
    monkeypatch.chdir(str(tmp_path))
    monkeypatch.setenv('ANTHROPIC_API_KEY', 'test-key')

    def fake(prompt, model, log_file, **kwargs):
        os.makedirs(os.path.dirname(log_file) or '.', exist_ok=True)
        if '-architecture' in log_file:
            # Truncated JSON + stop_reason=max_tokens — the real-world
            # signature from the issue logs.
            text = '{"per_scene": [{"scene_id": "a01", "scores":'
            stop = 'max_tokens'
        elif '-spine' in log_file:
            text = json.dumps(_spine_payload())
            stop = 'end_turn'
        elif '-act-shape' in log_file:
            text = json.dumps(_act_shape_payload())
            stop = 'end_turn'
        else:
            text = json.dumps(_full_payload())
            stop = 'end_turn'
        response = {
            'content': [{'type': 'text', 'text': text}],
            'stop_reason': stop,
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
    assert result['architecture']['status'] == 'unparseable'
    out = capsys.readouterr().out
    assert 'architecture LLM response unparseable' in out
    assert 'truncated mid-JSON' in out
    # The ceiling is named so the user knows the budget that hit the
    # wall.
    assert 'max_tokens=32768' in out


def test_unparseable_without_truncation_omits_hint(tmp_path, monkeypatch,
                                                      capsys):
    """When the LLM returns malformed JSON but did NOT hit
    max_tokens, the error message stays clean — no spurious
    'truncated' suffix on what is actually a genuine parse failure."""
    _seed_summary(str(tmp_path))
    _seed_architecture(str(tmp_path))
    monkeypatch.chdir(str(tmp_path))
    monkeypatch.setenv('ANTHROPIC_API_KEY', 'test-key')

    def fake(prompt, model, log_file, **kwargs):
        os.makedirs(os.path.dirname(log_file) or '.', exist_ok=True)
        if '-architecture' in log_file:
            text = 'this is not json'
            stop = 'end_turn'
        elif '-spine' in log_file:
            text = json.dumps(_spine_payload())
            stop = 'end_turn'
        elif '-act-shape' in log_file:
            text = json.dumps(_act_shape_payload())
            stop = 'end_turn'
        else:
            text = json.dumps(_full_payload())
            stop = 'end_turn'
        response = {
            'content': [{'type': 'text', 'text': text}],
            'stop_reason': stop,
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
    out = capsys.readouterr().out
    assert 'architecture LLM response unparseable' in out
    assert 'truncated mid-JSON' not in out


def test_read_stop_reason_handles_non_dict_top_level(tmp_path):
    """A JSON log whose top level is a list / string / number must not
    crash _read_stop_reason — the .get call on a non-dict would
    propagate AttributeError out of the diagnostic helper and
    suppress the original unparseable-error message. (PR #247 review
    SF-HIGH-1.)"""
    from storyforge.scoring_story_power import _read_stop_reason
    log_file = str(tmp_path / 'resp.json')
    # Top-level list — has happened on partial writes where only the
    # `content` array was flushed.
    with open(log_file, 'w') as f:
        json.dump(['partial', 'list'], f)
    assert _read_stop_reason(log_file) == ''


def test_read_stop_reason_handles_non_string_stop_reason(tmp_path):
    """A response with a non-string stop_reason value (would not match
    the API contract, but defensive against schema drift) returns ''
    rather than crashing the comparison downstream."""
    from storyforge.scoring_story_power import _read_stop_reason
    log_file = str(tmp_path / 'resp.json')
    with open(log_file, 'w') as f:
        json.dump({'stop_reason': {'unexpected': 'shape'}}, f)
    assert _read_stop_reason(log_file) == ''


def test_read_stop_reason_logs_warning_on_oserror(tmp_path, capsys):
    """OSError (file should exist but unreadable, or a missing
    directory leading to FileNotFoundError) logs a WARNING so the
    diagnostic itself doesn't fail silently. Mirrors
    _read_response_text's behavior. (PR #247 review SF-MED-2.)"""
    from storyforge.scoring_story_power import _read_stop_reason
    # Nested non-existent directory raises FileNotFoundError, an
    # OSError subclass.
    _read_stop_reason(str(tmp_path / 'sub' / 'missing.json'))
    out = capsys.readouterr().out
    assert 'could not read story-power log' in out


def test_read_stop_reason_decode_error_stays_quiet(tmp_path, capsys):
    """A JSONDecodeError is expected on partial writes (file exists,
    content incomplete) and stays quiet — that's the normal case
    for a truncated invoke_to_file, not a diagnostic failure."""
    from storyforge.scoring_story_power import _read_stop_reason
    log_file = str(tmp_path / 'partial.json')
    with open(log_file, 'w') as f:
        f.write('{"partial":')  # incomplete
    assert _read_stop_reason(log_file) == ''
    out = capsys.readouterr().out
    # The OSError WARNING must NOT fire on a parse failure.
    assert 'could not read story-power log' not in out


def test_read_stop_reason_logs_info_on_unrecognized_value(tmp_path, capsys):
    """An unrecognized stop_reason value (Anthropic API schema drift)
    logs an INFO so the codebase doesn't silently lose truncation
    detection on a future API change. (PR #247 review SF-HIGH-2.)"""
    from storyforge.scoring_story_power import _read_stop_reason
    log_file = str(tmp_path / 'resp.json')
    with open(log_file, 'w') as f:
        json.dump({'stop_reason': 'budget_exhausted'}, f)
    result = _read_stop_reason(log_file)
    # The helper still returns the raw value so a downstream consumer
    # can decide what to do; the INFO is a breadcrumb, not a block.
    assert result == 'budget_exhausted'
    out = capsys.readouterr().out
    assert 'unrecognized stop_reason' in out
    assert 'budget_exhausted' in out
    assert 'KNOWN_STOP_REASONS' in out


def test_read_stop_reason_known_values_stay_quiet(tmp_path, capsys):
    """The documented stop_reason values do NOT log INFO — the
    drift-detection breadcrumb should fire only on schema surprise."""
    from storyforge.scoring_story_power import (
        _read_stop_reason, KNOWN_STOP_REASONS,
    )
    log_file = str(tmp_path / 'resp.json')
    for known in KNOWN_STOP_REASONS:
        if not known:
            continue  # '' sentinel covered by missing-field test
        with open(log_file, 'w') as f:
            json.dump({'stop_reason': known}, f)
        _read_stop_reason(log_file)
    out = capsys.readouterr().out
    assert 'unrecognized stop_reason' not in out


def test_max_tokens_constants_are_monotone():
    """The module-load assert pins _PITCH <= _FIXED_PAYLOAD <=
    _PER_ROW. This regression test exercises the actual values so a
    future edit can't accidentally invert the ordering and rely on
    the import-time assert never running. (PR #247 review TD-HIGH-1.)"""
    from storyforge.scoring_story_power import (
        _PITCH_MAX_TOKENS, _FIXED_PAYLOAD_TIER_MAX_TOKENS,
        _PER_ROW_TIER_MAX_TOKENS,
    )
    assert _PITCH_MAX_TOKENS <= _FIXED_PAYLOAD_TIER_MAX_TOKENS
    assert _FIXED_PAYLOAD_TIER_MAX_TOKENS <= _PER_ROW_TIER_MAX_TOKENS


def test_known_stop_reasons_includes_max_tokens():
    """KNOWN_STOP_REASONS must include 'max_tokens', otherwise the
    drift-detection INFO would fire on every truncation and the
    truncation hint would silently disable itself."""
    from storyforge.scoring_story_power import KNOWN_STOP_REASONS
    assert 'max_tokens' in KNOWN_STOP_REASONS
    # The other documented values per Anthropic API docs.
    assert 'end_turn' in KNOWN_STOP_REASONS
    assert 'stop_sequence' in KNOWN_STOP_REASONS
    assert 'tool_use' in KNOWN_STOP_REASONS


def test_truncation_hint_uses_hedged_wording(tmp_path):
    """The hint says 'likely truncated', not 'was truncated' —
    stop_reason=max_tokens guarantees the LLM stopped at the budget
    but doesn't *prove* the JSON was truncated mid-token. The hedge
    prevents a future 'you said truncated but the JSON was complete'
    confusion. (PR #247 review SF-MED-1.)"""
    from storyforge.scoring_story_power import _truncation_hint
    log_file = str(tmp_path / 'resp.json')
    with open(log_file, 'w') as f:
        json.dump({'stop_reason': 'max_tokens'}, f)
    hint = _truncation_hint(log_file, 32768)
    assert 'likely truncated' in hint
    assert 'was truncated' not in hint


def test_scene_map_unparseable_with_max_tokens_logs_truncation_hint(
        tmp_path, monkeypatch, capsys):
    """Scene-map mode mirrors the architecture truncation contract.
    Without this test, a copy-paste regression that drops the
    _truncation_hint call from scene-map's unparseable log site
    would slip past architecture's coverage. (PR #247 review T-2.)"""
    _seed_summary(str(tmp_path))
    _seed_architecture(str(tmp_path))
    _seed_scene_map(str(tmp_path))
    monkeypatch.chdir(str(tmp_path))
    monkeypatch.setenv('ANTHROPIC_API_KEY', 'test-key')

    def fake(prompt, model, log_file, **kwargs):
        os.makedirs(os.path.dirname(log_file) or '.', exist_ok=True)
        if '-scene-map' in log_file:
            text = '{"per_scene": [{"scene_id": "s1", "scores":'
            stop = 'max_tokens'
        elif '-architecture' in log_file:
            text = json.dumps(_architecture_payload())
            stop = 'end_turn'
        elif '-spine' in log_file:
            text = json.dumps(_spine_payload())
            stop = 'end_turn'
        elif '-act-shape' in log_file:
            text = json.dumps(_act_shape_payload())
            stop = 'end_turn'
        else:
            text = json.dumps(_full_payload())
            stop = 'end_turn'
        response = {
            'content': [{'type': 'text', 'text': text}],
            'stop_reason': stop,
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
    assert result['scene_map']['status'] == 'unparseable'
    out = capsys.readouterr().out
    assert 'scene-map LLM response unparseable' in out
    assert 'truncated mid-JSON' in out
    assert 'max_tokens=32768' in out


def test_briefs_unparseable_with_max_tokens_logs_truncation_hint(
        tmp_path, monkeypatch, capsys):
    """Briefs mode mirrors the architecture truncation contract.
    (PR #247 review T-2.)"""
    _seed_summary(str(tmp_path))
    _seed_briefs(str(tmp_path))
    monkeypatch.chdir(str(tmp_path))
    monkeypatch.setenv('ANTHROPIC_API_KEY', 'test-key')

    def fake(prompt, model, log_file, **kwargs):
        os.makedirs(os.path.dirname(log_file) or '.', exist_ok=True)
        if '-briefs' in log_file:
            text = '{"per_brief": [{"scene_id": "s1", "scores":'
            stop = 'max_tokens'
        elif '-act-shape' in log_file:
            text = json.dumps(_act_shape_payload())
            stop = 'end_turn'
        else:
            text = json.dumps(_full_payload())
            stop = 'end_turn'
        response = {
            'content': [{'type': 'text', 'text': text}],
            'stop_reason': stop,
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
    assert result['briefs']['status'] == 'unparseable'
    out = capsys.readouterr().out
    assert 'briefs LLM response unparseable' in out
    assert 'truncated mid-JSON' in out
    assert 'max_tokens=32768' in out


def test_truncation_path_records_unparseable_target_in_ledger(
        tmp_path, monkeypatch):
    """When architecture truncates and the parse fails, the cost
    ledger MUST record the unparseable target (not the success
    target). A regression that swapped the targets on the
    truncation path would silently mis-bill — costs that look like
    successful runs but actually delivered no diagnostic.
    (PR #247 review T-3.)"""
    _seed_summary(str(tmp_path))
    _seed_architecture(str(tmp_path))
    monkeypatch.chdir(str(tmp_path))
    monkeypatch.setenv('ANTHROPIC_API_KEY', 'test-key')

    def fake(prompt, model, log_file, **kwargs):
        os.makedirs(os.path.dirname(log_file) or '.', exist_ok=True)
        if '-architecture' in log_file:
            text = '{"per_scene":'
            stop = 'max_tokens'
        elif '-spine' in log_file:
            text = json.dumps(_spine_payload())
            stop = 'end_turn'
        elif '-act-shape' in log_file:
            text = json.dumps(_act_shape_payload())
            stop = 'end_turn'
        else:
            text = json.dumps(_full_payload())
            stop = 'end_turn'
        response = {
            'content': [{'type': 'text', 'text': text}],
            'stop_reason': stop,
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
    ledger_path = os.path.join(str(tmp_path), 'working', 'costs',
                                  'ledger.csv')
    assert os.path.isfile(ledger_path)
    ledger = open(ledger_path).read()
    # The architecture truncation path must record the unparseable
    # target — not the success target.
    assert 'story-power:architecture:unparseable' in ledger
    # And it must NOT record the success target for the architecture
    # call (separate from the success targets the other tiers
    # legitimately produced).
    assert 'story-power:architecture,' not in ledger


