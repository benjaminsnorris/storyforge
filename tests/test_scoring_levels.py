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
        'id|seq|title|summary|function|part',
        [f'event-{i}|{i}|Title {i}|Summary {i} in one sentence.|Causes the next thing|1'
         for i in range(1, 8)],
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


def test_scene_map_fails_when_no_map_rows(tmp_path):
    """Regression: header-only scenes.csv must NOT vacuous-pass level 5.

    Pre-scene-map phases (spine, architecture) legitimately have empty
    scenes.csv. Level 5 should report this as 'not yet elaborated', not
    as 'metadata populated' (which is true only because there are zero
    rows to check)."""
    ref = tmp_path / 'reference'
    ref.mkdir()
    (ref / 'scenes.csv').write_text(
        'id|seq|title|part|pov|location|timeline_day|time_of_day|duration|'
        'type|status|word_count|target_words|target_pages|panel_count|page_count\n'
    )
    (ref / 'scene-intent.csv').write_text(
        'id|function|action_sequel|emotional_arc|value_at_stake|value_shift|'
        'turning_point|characters|on_stage|mice_threads\n'
    )
    r = score_scene_map(str(tmp_path))
    assert r['level'] == 5
    first = r['checks'][0]
    assert first['check'] == 'scene-map has at least one row'
    assert first['passed'] is False
    assert 'scene-map stage' in first['detail']


def test_scene_map_fails_when_only_pre_map_status_rows(tmp_path):
    """Rows at status=architecture (pre-scene-map) should also trigger the
    'no map rows' failure — those belong to architecture.csv, not the
    scene-map tier."""
    ref = tmp_path / 'reference'
    ref.mkdir()
    (ref / 'scenes.csv').write_text(
        'id|seq|title|part|pov|location|timeline_day|time_of_day|duration|'
        'type|status|word_count|target_words|target_pages|panel_count|page_count\n'
        'sc-1|1|t|1|p|l|||||plot|architecture|||||\n'
    )
    (ref / 'scene-intent.csv').write_text(
        'id|function|action_sequel|emotional_arc|value_at_stake|value_shift|'
        'turning_point|characters|on_stage|mice_threads\n'
    )
    r = score_scene_map(str(tmp_path))
    first = r['checks'][0]
    assert first['check'] == 'scene-map has at least one row'
    assert first['passed'] is False


def test_spine_summary_required(tmp_path):
    """Level 3 must flag spine events that lack a one-sentence summary."""
    ref = tmp_path / 'reference'
    ref.mkdir()
    (ref / 'spine.csv').write_text(
        'id|seq|title|summary|function|part\n'
        'ev-1|1|First|First event in one sentence.|inciting|1\n'
        'ev-2|2|Second||turning point|2\n'
        'ev-3|3|Third|Third event.|midpoint|2\n'
        'ev-4|4|Fourth|Fourth event.|climax|3\n'
    )
    from storyforge.scoring_levels import score_spine
    r = score_spine(str(tmp_path), medium='graphic-novel')
    summary_check = next(
        (c for c in r['checks'] if c['check'].startswith('summary non-empty')),
        None,
    )
    assert summary_check is not None
    assert summary_check['passed'] is False
    assert 'ev-2' in summary_check['detail']


def test_spine_summary_word_limit(tmp_path):
    """Level 3 must flag spine summaries that exceed the word limit."""
    ref = tmp_path / 'reference'
    ref.mkdir()
    long_summary = ' '.join(['word'] * 40)  # 40 words, over the 35 limit
    (ref / 'spine.csv').write_text(
        'id|seq|title|summary|function|part\n'
        f'ev-1|1|t|{long_summary}|inciting|1\n'
        'ev-2|2|t|short summary.|turn|2\n'
        'ev-3|3|t|short summary.|midpoint|2\n'
        'ev-4|4|t|short summary.|climax|3\n'
    )
    from storyforge.scoring_levels import score_spine
    r = score_spine(str(tmp_path), medium='graphic-novel')
    word_check = next(
        (c for c in r['checks'] if 'words' in c['check']),
        None,
    )
    assert word_check is not None
    assert word_check['passed'] is False
    assert '40 words' in word_check['detail']


def test_architecture_summary_required(tmp_path):
    """Level 4 must flag architecture anchors that lack a summary."""
    ref = tmp_path / 'reference'
    ref.mkdir()
    (ref / 'spine.csv').write_text(
        'id|seq|title|summary|function|part\n'
        'ev-1|1|t|s|f|1\n'
    )
    rows = [
        f'a{i:02d}|{i}|t||1|POV|ev-1|action|focus to ease|safety|+/-|reveal'
        for i in range(1, 11)
    ]
    # First anchor has a summary; rest don't
    rows[0] = 'a01|1|t|One-sentence summary.|1|POV|ev-1|action|focus to ease|safety|+/-|reveal'
    (ref / 'architecture.csv').write_text(
        'id|seq|title|summary|part|pov|spine_event|action_sequel|'
        'emotional_arc|value_at_stake|value_shift|turning_point\n'
        + '\n'.join(rows) + '\n'
    )
    from storyforge.scoring_levels import score_architecture
    r = score_architecture(str(tmp_path), medium='graphic-novel')
    summary_check = next(
        (c for c in r['checks'] if c['check'].startswith('summary non-empty')),
        None,
    )
    assert summary_check is not None
    assert summary_check['passed'] is False


def test_scene_map_summary_check_skipped_when_no_map_rows(tmp_path):
    """Summary check should not run when there are no map-tier rows
    (the prior 'at least one row' check already covers that case)."""
    ref = tmp_path / 'reference'
    ref.mkdir()
    (ref / 'scenes.csv').write_text(
        'id|seq|title|summary|part|pov|location|timeline_day|time_of_day|'
        'duration|type|status|word_count|target_words\n'
    )
    (ref / 'scene-intent.csv').write_text(
        'id|function|action_sequel|emotional_arc|value_at_stake|value_shift|'
        'turning_point|characters|on_stage|mice_threads\n'
    )
    from storyforge.scoring_levels import score_scene_map
    r = score_scene_map(str(tmp_path))
    # 'has at least one row' should fail, but no summary check should appear.
    summary_checks = [c for c in r['checks']
                      if 'summary' in c['check'].lower()]
    assert summary_checks == []


def test_briefs_fails_when_csv_is_header_only(tmp_path):
    """Regression: header-only scene-briefs.csv must NOT vacuous-pass level 6."""
    ref = tmp_path / 'reference'
    ref.mkdir()
    (ref / 'scene-briefs.csv').write_text(
        'id|goal|conflict|outcome|crisis|decision|knowledge_in|knowledge_out|'
        'key_actions|key_dialogue|emotions|motifs|continuity_deps|has_overflow\n'
    )
    r = score_briefs(str(tmp_path))
    assert r['level'] == 6
    first = r['checks'][0]
    assert first['check'] == 'scene-briefs.csv has at least one row'
    assert first['passed'] is False
    assert 'brief stage' in first['detail']


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


# ---------------------------------------------------------------------------
# v2 Phase 4: scoring-overrides wired as quality gate
# ---------------------------------------------------------------------------

def test_failed_check_with_override_tagged_accepted(tmp_path):
    """An author-accepted override on a failed floor check tags the check
    with accepted=True and decrements the effective failure count."""
    # Empty story-summary triggers logline floor failures.
    _write_summary(str(tmp_path), '''# Story summary

## Logline

''')
    # Pre-record an override for the failing 'present' check.
    from storyforge.scoring_state import append_override
    append_override(
        scope='level-0', axis='level-quality', finding_id='present',
        verdict='accepted',
        rationale='intentional placeholder while iterating',
        recorded_at='2026-05-24', project_dir=str(tmp_path),
    )

    from storyforge.scoring_levels import score_level
    r = score_level(str(tmp_path), 0)
    # The 'present' check itself still surfaces (passed=False) but is
    # tagged accepted.
    present_check = next(c for c in r['checks'] if c['check'] == 'present')
    assert not present_check['passed']
    assert present_check.get('accepted') is True
    # The result-level `accepted` count reflects this.
    assert r['accepted'] == 1


def test_unrelated_overrides_do_not_apply(tmp_path):
    """An override for a different finding_id does NOT flip the unrelated
    check."""
    _write_summary(str(tmp_path), '''# Story summary

## Logline

''')
    from storyforge.scoring_state import append_override
    append_override(
        scope='level-0', axis='level-quality',
        finding_id='length ≤ 35 words',  # different finding
        verdict='accepted', rationale='ok', recorded_at='2026-05-24',
        project_dir=str(tmp_path),
    )

    from storyforge.scoring_levels import score_level
    r = score_level(str(tmp_path), 0)
    present_check = next(c for c in r['checks'] if c['check'] == 'present')
    assert not present_check.get('accepted')


def test_passed_check_is_never_marked_accepted(tmp_path):
    """A passing check shouldn't pick up an `accepted=True` even if the
    overrides file happens to mention its name."""
    _write_summary(str(tmp_path), '''# Story summary

## Logline

A perfectly fine short logline.
''')
    from storyforge.scoring_state import append_override
    append_override(
        scope='level-0', axis='level-quality', finding_id='present',
        verdict='accepted', rationale='whatever', recorded_at='2026-05-24',
        project_dir=str(tmp_path),
    )
    from storyforge.scoring_levels import score_level
    r = score_level(str(tmp_path), 0)
    present_check = next(c for c in r['checks'] if c['check'] == 'present')
    assert present_check['passed']
    # Passing checks aren't tagged accepted (the field may be present
    # but it's False for passing checks).
    assert not present_check.get('accepted', False)


def test_accepted_count_in_result_dict(tmp_path):
    """LevelResult.accepted is an explicit count of accepted-failures."""
    _write_summary(str(tmp_path), '''# Story summary

## Logline

''')
    from storyforge.scoring_state import append_override
    append_override(
        scope='level-0', axis='level-quality', finding_id='present',
        verdict='accepted', rationale='r', recorded_at='2026-05-24',
        project_dir=str(tmp_path),
    )
    from storyforge.scoring_levels import score_level
    r = score_level(str(tmp_path), 0)
    # Invariant: accepted <= failed, accepted is part of failed not passed
    assert r['accepted'] <= r['failed']
    assert r['accepted'] >= 1


def test_registry_consistency_respects_overrides(project_dir):
    """The same override propagation applies to consistency checks."""
    from storyforge.csv_cli import update_field
    intent = os.path.join(project_dir, 'reference', 'scene-intent.csv')
    update_field(intent, 'act1-sc01', 'value_at_stake', 'definitely-not-a-real-value')

    from storyforge.scoring_state import append_override
    from storyforge.scoring_consistency import score_consistency_at_level

    # First confirm the orphan flag is there (no override yet).
    r = score_consistency_at_level(project_dir, 5)
    bad = next((c for c in r['checks']
                if 'value_at_stake' in c['check'] and not c['passed']), None)
    assert bad is not None
    assert not bad.get('accepted')

    # Now add the override and re-run.
    append_override(
        scope='level-5', axis='registry-consistency',
        finding_id=bad['check'], verdict='accepted',
        rationale='intentional placeholder', recorded_at='2026-05-24',
        project_dir=project_dir,
    )
    r2 = score_consistency_at_level(project_dir, 5)
    bad2 = next(c for c in r2['checks'] if c['check'] == bad['check'])
    assert bad2['accepted'] is True


def test_score_all_levels_returns_seven(project_dir):
    results = score_all_levels(project_dir)
    assert len(results) == 7
    assert [r['level'] for r in results] == [0, 1, 2, 3, 4, 5, 6]


# ---------------------------------------------------------------------------
# _print_level_result headline arithmetic (regression: PR #232 test review)
# ---------------------------------------------------------------------------

def test_print_level_result_subtracts_accepted_from_failed(capsys):
    """The CLI headline must show `failed - accepted` so the author sees
    the real blocking count, not the raw failure count that included
    accepted overrides. Pre-fix, a regression here could leave the dict
    invariant intact while showing the wrong number to the user."""
    from storyforge.cmd_score import _print_level_result
    result = {
        'level': 0, 'name': 'logline', 'checks': [
            {'check': 'a', 'passed': True, 'detail': '', 'severity': 'high'},
            {'check': 'b', 'passed': False, 'detail': 'd1', 'severity': 'high'},
            {'check': 'c', 'passed': False, 'detail': 'd2', 'severity': 'high',
             'accepted': True},
            {'check': 'd', 'passed': False, 'detail': 'd3', 'severity': 'high'},
        ],
        'passed': 1, 'failed': 3, 'accepted': 1,
    }
    _print_level_result(result)
    out = capsys.readouterr().out
    assert '1 passed' in out
    # 3 failed - 1 accepted = 2 real blocking failures shown to the author.
    assert '2 failed' in out
    assert '(+ 1 accepted)' in out


def test_print_level_result_no_accepted_renders_no_suffix(capsys):
    from storyforge.cmd_score import _print_level_result
    result = {
        'level': 0, 'name': 'logline', 'checks': [
            {'check': 'a', 'passed': True, 'detail': '', 'severity': 'high'},
            {'check': 'b', 'passed': False, 'detail': 'd', 'severity': 'high'},
        ],
        'passed': 1, 'failed': 1, 'accepted': 0,
    }
    _print_level_result(result)
    out = capsys.readouterr().out
    assert '1 passed, 1 failed' in out
    assert 'accepted' not in out
