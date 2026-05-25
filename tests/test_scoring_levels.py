"""Tests for scoring_levels.py — per-level floor checks (#229).

Spec: docs/superpowers/specs/2026-05-24-elaboration-scoring-design.md
"""

import os

from storyforge.scoring_levels import (
    score_logline,
    score_synopsis,
    score_act_shape,
    score_spine,
    score_architecture,
    score_scene_map,
    score_briefs,
    score_level,
    score_all_levels,
)


def _write_summary(project_dir, body):
    path = os.path.join(project_dir, 'reference', 'story-summary.md')
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, 'w', encoding='utf-8') as f:
        f.write(body)


def _write_csv(path, header, rows):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, 'w', encoding='utf-8') as f:
        f.write(header + '\n')
        for r in rows:
            f.write(r + '\n')


# ---------------------------------------------------------------------------
# Level 0 — Logline
# ---------------------------------------------------------------------------

def test_logline_empty_flagged(tmp_path):
    _write_summary(str(tmp_path), '''# Story summary

## Logline

''')
    r = score_logline(str(tmp_path))
    assert r['level'] == 0
    assert r['failed'] == 1
    assert any(c['check'] == 'present' and not c['passed'] for c in r['checks'])


def test_logline_within_length_passes(tmp_path):
    _write_summary(str(tmp_path), '''# Story summary

## Logline

A cartographer who maps the unmappable loses his daughter to a country no map contains.
''')
    r = score_logline(str(tmp_path))
    assert r['failed'] == 0
    assert r['passed'] >= 2


def test_logline_too_long_flagged(tmp_path):
    long_text = ' '.join(['word'] * 40)
    _write_summary(str(tmp_path), f'''# Story summary

## Logline

{long_text}
''')
    r = score_logline(str(tmp_path))
    length_check = next(c for c in r['checks'] if 'length' in c['check'])
    assert not length_check['passed']


# ---------------------------------------------------------------------------
# Level 1 — Synopsis
# ---------------------------------------------------------------------------

def test_synopsis_in_range(tmp_path):
    _write_summary(str(tmp_path), '''# Story summary

## Synopsis

First sentence. Second sentence. Third sentence. Fourth sentence. Fifth sentence.
''')
    r = score_synopsis(str(tmp_path))
    assert r['failed'] == 0


def test_synopsis_too_short(tmp_path):
    _write_summary(str(tmp_path), '''# Story summary

## Synopsis

Just one sentence here.
''')
    r = score_synopsis(str(tmp_path))
    length_check = next(c for c in r['checks'] if 'length' in c['check'])
    assert not length_check['passed']


# ---------------------------------------------------------------------------
# Level 2 — Act-shape
# ---------------------------------------------------------------------------

def test_act_shape_three_acts_passes(tmp_path):
    _write_summary(str(tmp_path), '''# Story summary

## Act-shape

### Act 1
First act content.

### Act 2
Second act content.

### Act 3
Third act content.
''')
    r = score_act_shape(str(tmp_path))
    assert r['failed'] == 0


def test_act_shape_two_acts_fails(tmp_path):
    _write_summary(str(tmp_path), '''# Story summary

## Act-shape

### Act 1
Only one act here.

### Act 2
And another.
''')
    r = score_act_shape(str(tmp_path))
    acts_check = next(c for c in r['checks'] if 'exactly 3 acts' in c['check'])
    assert not acts_check['passed']


# ---------------------------------------------------------------------------
# Level 3 — Spine
# ---------------------------------------------------------------------------

def test_spine_missing_file(tmp_path):
    r = score_spine(str(tmp_path))
    assert r['failed'] >= 1
    assert any('spine.csv' in (c.get('detail') or '') for c in r['checks'])


def test_spine_correct_range_novel(tmp_path):
    _write_csv(
        os.path.join(str(tmp_path), 'reference', 'spine.csv'),
        'id|seq|title|function|part',
        [f'event-{i}|{i}|Title {i}|Causes the next thing|1' for i in range(1, 8)],
    )
    r = score_spine(str(tmp_path), medium='novel')
    assert r['failed'] == 0


def test_spine_too_few_for_novel(tmp_path):
    _write_csv(
        os.path.join(str(tmp_path), 'reference', 'spine.csv'),
        'id|seq|title|function|part',
        [f'event-{i}|{i}|T{i}|fn|1' for i in range(1, 4)],
    )
    r = score_spine(str(tmp_path), medium='novel')
    count_check = next(c for c in r['checks'] if 'row count' in c['check'])
    assert not count_check['passed']


def test_spine_missing_function_flagged(tmp_path):
    _write_csv(
        os.path.join(str(tmp_path), 'reference', 'spine.csv'),
        'id|seq|title|function|part',
        ['event-1|1|First||1'] + [f'event-{i}|{i}|T{i}|fn|1' for i in range(2, 7)],
    )
    r = score_spine(str(tmp_path), medium='novel')
    fn_check = next(c for c in r['checks'] if 'function' in c['check'])
    assert not fn_check['passed']


def test_spine_gn_range(tmp_path):
    _write_csv(
        os.path.join(str(tmp_path), 'reference', 'spine.csv'),
        'id|seq|title|function|part',
        [f'event-{i}|{i}|T{i}|fn|1' for i in range(1, 6)],
    )
    r = score_spine(str(tmp_path), medium='graphic-novel')
    # 5 rows is in the 4-8 GN range
    count_check = next(c for c in r['checks'] if 'row count' in c['check'])
    assert count_check['passed']


# ---------------------------------------------------------------------------
# Level 4 — Architecture
# ---------------------------------------------------------------------------

def test_architecture_orphan_spine_event_flagged(tmp_path):
    ref = os.path.join(str(tmp_path), 'reference')
    _write_csv(
        os.path.join(ref, 'spine.csv'),
        'id|seq|title|function|part',
        ['event-1|1|First|fn|1', 'event-2|2|Second|fn|1'],
    )
    _write_csv(
        os.path.join(ref, 'architecture.csv'),
        'id|seq|title|part|pov|spine_event|action_sequel|emotional_arc|value_at_stake|value_shift|turning_point',
        [f'arch-{i}|{i}|T{i}|1|hero|event-99|action|a|truth|+/-|action'
         for i in range(1, 18)],
    )
    r = score_architecture(str(tmp_path), medium='novel')
    bad_check = next(c for c in r['checks'] if 'resolve to spine.csv' in c['check'])
    assert not bad_check['passed']


def test_architecture_action_sequel_balance(tmp_path):
    ref = os.path.join(str(tmp_path), 'reference')
    # 16 rows, all 'action' — should fail the both-present check
    _write_csv(
        os.path.join(ref, 'architecture.csv'),
        'id|seq|title|part|pov|spine_event|action_sequel|emotional_arc|value_at_stake|value_shift|turning_point',
        [f'arch-{i}|{i}|T{i}|1|hero||action|a|truth|+/-|action'
         for i in range(1, 17)],
    )
    r = score_architecture(str(tmp_path), medium='novel')
    balance_check = next(c for c in r['checks'] if 'action and sequel' in c['check'])
    assert not balance_check['passed']


def test_architecture_count_correct_novel(tmp_path):
    ref = os.path.join(str(tmp_path), 'reference')
    _write_csv(
        os.path.join(ref, 'architecture.csv'),
        'id|seq|title|part|pov|spine_event|action_sequel|emotional_arc|value_at_stake|value_shift|turning_point',
        [f'arch-{i}|{i}|T{i}|1|hero||action|a|truth|+/-|action'
         for i in range(1, 9)] +
        [f'arch-s{i}|{i+10}|T{i+10}|1|hero||sequel|a|truth|+/-|revelation'
         for i in range(1, 9)],
    )
    r = score_architecture(str(tmp_path), medium='novel')
    # 16 rows, mixed action/sequel — count check passes
    count_check = next(c for c in r['checks'] if 'row count' in c['check'])
    assert count_check['passed']


# ---------------------------------------------------------------------------
# Level 5 + 6 (against fixtures)
# ---------------------------------------------------------------------------

def test_scene_map_against_fixture(project_dir):
    """Run scene-map floor checks against the test-project fixture."""
    r = score_scene_map(project_dir)
    assert r['level'] == 5
    # Fixture has rows at mapped+ status — checks run; some may pass or fail
    assert isinstance(r['checks'], list)


def test_briefs_against_fixture(project_dir):
    r = score_briefs(project_dir)
    assert r['level'] == 6
    assert isinstance(r['checks'], list)


# ---------------------------------------------------------------------------
# Dispatch
# ---------------------------------------------------------------------------

def test_score_level_unknown_raises(tmp_path):
    import pytest
    with pytest.raises(ValueError):
        score_level(str(tmp_path), 99)


# ---------------------------------------------------------------------------
# Regression tests for review fixes
# ---------------------------------------------------------------------------

def test_architecture_warns_when_spine_csv_missing(tmp_path):
    """When architecture rows have spine_event references but spine.csv
    isn't present, the floor check should explicitly flag the gap rather
    than silently skipping the cross-reference check."""
    ref = os.path.join(str(tmp_path), 'reference')
    _write_csv(
        os.path.join(ref, 'architecture.csv'),
        'id|seq|title|part|pov|spine_event|action_sequel|emotional_arc|'
        'value_at_stake|value_shift|turning_point',
        [f'arch-{i}|{i}|T|1|hero|event-x|action|a|truth|+/-|action'
         for i in range(1, 17)],
    )
    # NO spine.csv
    from storyforge.scoring_levels import score_architecture
    r = score_architecture(str(tmp_path), medium='novel')
    # A check should fail with detail mentioning spine.csv
    bad = [c for c in r['checks'] if not c['passed']]
    assert any('spine.csv' in (c.get('detail') or '') for c in bad), (
        'architecture check should surface missing spine.csv when '
        'spine_event references exist'
    )


def test_architecture_no_warning_when_spine_event_all_empty(tmp_path):
    """If no architecture row has a spine_event yet (project at architecture
    stage but spine.csv hasn't been populated), the warning should NOT
    fire — the cross-reference simply isn't required yet."""
    ref = os.path.join(str(tmp_path), 'reference')
    _write_csv(
        os.path.join(ref, 'architecture.csv'),
        'id|seq|title|part|pov|spine_event|action_sequel|emotional_arc|'
        'value_at_stake|value_shift|turning_point',
        [f'arch-{i}|{i}|T|1|hero||action|a|truth|+/-|action'
         for i in range(1, 17)],
    )
    from storyforge.scoring_levels import score_architecture
    r = score_architecture(str(tmp_path), medium='novel')
    spine_msg_findings = [
        c for c in r['checks']
        if 'spine.csv is missing' in (c.get('detail') or '')
    ]
    assert not spine_msg_findings, (
        'should not warn about missing spine.csv when no architecture row '
        'has a spine_event value yet'
    )


def test_scene_map_pov_check_skips_empty_on_stage(project_dir):
    """When on_stage is empty for a POV scene, the check should not
    false-positive — it should surface a separate informational finding
    about on_stage being unpopulated."""
    from storyforge.csv_cli import update_field
    intent_path = os.path.join(project_dir, 'reference', 'scene-intent.csv')
    # Find a POV scene at status=mapped+ and blank its on_stage
    update_field(intent_path, 'act1-sc01', 'on_stage', '')

    from storyforge.scoring_levels import score_scene_map
    r = score_scene_map(project_dir)
    # The POV-vs-on_stage check should NOT fail on the unpopulated scene
    pov_check = next(c for c in r['checks'] if 'POV is on-stage' in c['check'])
    detail = pov_check.get('detail') or ''
    assert 'act1-sc01' not in detail, (
        'unpopulated on_stage should not trigger the POV mismatch check'
    )
    # And we should see the informational on_stage-populated finding
    populated_check = next(
        (c for c in r['checks'] if 'on_stage data populated' in c['check']),
        None,
    )
    assert populated_check is not None, (
        'expected an informational finding about unpopulated on_stage'
    )
    assert populated_check.get('severity') == 'low'


# ---------------------------------------------------------------------------
# Severity validation (#13)
# ---------------------------------------------------------------------------

def test_check_validates_severity():
    """_check() should reject any severity not in VALID_SEVERITIES."""
    import pytest
    from storyforge.scoring_levels import _check
    # Valid ones work
    for sev in ('high', 'medium', 'low'):
        _check('test', True, '', severity=sev)
    # Invalid raises
    with pytest.raises(ValueError, match='severity'):
        _check('test', True, '', severity='critical')
    with pytest.raises(ValueError, match='severity'):
        _check('test', True, '', severity='')
    with pytest.raises(ValueError, match='severity'):
        _check('test', True, '', severity='HIGH')


def test_score_all_levels_returns_seven(project_dir):
    results = score_all_levels(project_dir)
    assert len(results) == 7
    assert [r['level'] for r in results] == [0, 1, 2, 3, 4, 5, 6]
