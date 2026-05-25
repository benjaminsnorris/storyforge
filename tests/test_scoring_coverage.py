"""Tests for cross-tier coverage checks."""

import os

import pytest


def _write(path: str, content: str) -> None:
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, 'w', encoding='utf-8') as f:
        f.write(content)


def _seed_summary(project_dir: str, act_count: int = 3) -> None:
    """Seed a story-summary.md with N act sub-sections."""
    parts = ['---', 'logline_updated:', 'synopsis_updated:', 'act_shape_updated:',
             'theme_updated:', '---', '', '# Story summary', '',
             '## Logline\nLogline.', '',
             '## Synopsis\nOne. Two. Three. Four.', '',
             '## Act-shape', '']
    for n in range(1, act_count + 1):
        parts.append(f'### Act {n}')
        parts.append(f'Act {n} prose.')
        parts.append('')
    parts.extend(['## Theme', 'Theme.'])
    _write(
        os.path.join(project_dir, 'reference', 'story-summary.md'),
        '\n'.join(parts) + '\n',
    )


# ---------------------------------------------------------------------------
# Level 2 → 3: every Act has spine events
# ---------------------------------------------------------------------------

def test_coverage_act_2_to_spine_passes_when_all_acts_have_events(tmp_path):
    _seed_summary(str(tmp_path), act_count=3)
    _write(
        os.path.join(str(tmp_path), 'reference', 'spine.csv'),
        'id|seq|title|summary|function|part\n'
        'ev-1|1|t|s|inciting|1\n'
        'ev-2|2|t|s|turn|1\n'
        'ev-3|3|t|s|mid|2\n'
        'ev-4|4|t|s|climax|3\n',
    )
    from storyforge.scoring_coverage import score_coverage_at_level
    r = score_coverage_at_level(str(tmp_path), 2)
    assert r['failed'] == 0
    assert r['passed'] >= 3


def test_coverage_act_2_to_spine_flags_empty_act(tmp_path):
    """An Act with no spine events fails coverage."""
    _seed_summary(str(tmp_path), act_count=3)
    _write(
        os.path.join(str(tmp_path), 'reference', 'spine.csv'),
        'id|seq|title|summary|function|part\n'
        'ev-1|1|t|s|inciting|1\n'
        'ev-2|2|t|s|turn|1\n'
        # No part=2 event
        'ev-3|3|t|s|climax|3\n',
    )
    from storyforge.scoring_coverage import score_coverage_at_level
    r = score_coverage_at_level(str(tmp_path), 2)
    bad = next((c for c in r['checks'] if 'Act 2' in c['check']), None)
    assert bad is not None
    assert bad['passed'] is False


def test_coverage_act_2_fails_when_act_shape_empty(tmp_path):
    (tmp_path / 'reference').mkdir()
    _write(
        os.path.join(str(tmp_path), 'reference', 'story-summary.md'),
        '## Logline\nx\n## Synopsis\nx\n## Act-shape\n\n## Theme\nx\n',
    )
    from storyforge.scoring_coverage import score_coverage_at_level
    r = score_coverage_at_level(str(tmp_path), 2)
    assert r['failed'] == 1
    assert any('act-shape' in c['detail'].lower() for c in r['checks'])


# ---------------------------------------------------------------------------
# Level 3 → 4: every spine event has an architecture anchor
# ---------------------------------------------------------------------------

def test_coverage_spine_to_architecture_passes(tmp_path):
    _write(
        os.path.join(str(tmp_path), 'reference', 'spine.csv'),
        'id|seq|title|summary|function|part\n'
        'ev-1|1|t|s|f|1\n'
        'ev-2|2|t|s|f|2\n',
    )
    _write(
        os.path.join(str(tmp_path), 'reference', 'architecture.csv'),
        'id|seq|title|summary|part|pov|spine_event|action_sequel|emotional_arc|'
        'value_at_stake|value_shift|turning_point\n'
        'a-1|1|t|s|1|p|ev-1|action|arc|truth|+/-|reveal\n'
        'a-2|2|t|s|2|p|ev-2|action|arc|truth|+/-|reveal\n',
    )
    from storyforge.scoring_coverage import score_coverage_at_level
    r = score_coverage_at_level(str(tmp_path), 3)
    assert r['failed'] == 0


def test_coverage_spine_to_architecture_flags_orphan_spine(tmp_path):
    """A spine event with no architecture anchor referencing it fails."""
    _write(
        os.path.join(str(tmp_path), 'reference', 'spine.csv'),
        'id|seq|title|summary|function|part\n'
        'ev-1|1|t|s|f|1\n'
        'ev-orphan|2|t|s|f|2\n',
    )
    _write(
        os.path.join(str(tmp_path), 'reference', 'architecture.csv'),
        'id|seq|title|summary|part|pov|spine_event|action_sequel|emotional_arc|'
        'value_at_stake|value_shift|turning_point\n'
        'a-1|1|t|s|1|p|ev-1|action|arc|truth|+/-|reveal\n',
    )
    from storyforge.scoring_coverage import score_coverage_at_level
    r = score_coverage_at_level(str(tmp_path), 3)
    assert r['failed'] == 1
    assert 'ev-orphan' in r['checks'][0]['detail']


def test_coverage_spine_to_architecture_fails_when_arch_empty(tmp_path):
    _write(
        os.path.join(str(tmp_path), 'reference', 'spine.csv'),
        'id|seq|title|summary|function|part\n'
        'ev-1|1|t|s|f|1\n',
    )
    from storyforge.scoring_coverage import score_coverage_at_level
    r = score_coverage_at_level(str(tmp_path), 3)
    assert r['failed'] == 1


# ---------------------------------------------------------------------------
# Level 4 → 5: every architecture anchor has a mapped scene
# ---------------------------------------------------------------------------

def test_coverage_architecture_to_scenes_passes(tmp_path):
    _write(
        os.path.join(str(tmp_path), 'reference', 'architecture.csv'),
        'id|seq|title|summary|part|pov|spine_event|action_sequel|emotional_arc|'
        'value_at_stake|value_shift|turning_point\n'
        'a-1|1|t|s|1|p|ev-1|action|arc|truth|+/-|reveal\n',
    )
    _write(
        os.path.join(str(tmp_path), 'reference', 'scenes.csv'),
        'id|seq|title|summary|part|pov|location|timeline_day|time_of_day|'
        'duration|type|status|word_count|target_words|architecture_scene\n'
        'sc-1|1|t|s|1|p|l|1|m|2h|character|mapped|0|2500|a-1\n',
    )
    from storyforge.scoring_coverage import score_coverage_at_level
    r = score_coverage_at_level(str(tmp_path), 4)
    assert r['failed'] == 0


def test_coverage_architecture_to_scenes_flags_orphan_anchor(tmp_path):
    _write(
        os.path.join(str(tmp_path), 'reference', 'architecture.csv'),
        'id|seq|title|summary|part|pov|spine_event|action_sequel|emotional_arc|'
        'value_at_stake|value_shift|turning_point\n'
        'a-1|1|t|s|1|p|ev-1|action|arc|truth|+/-|reveal\n'
        'a-orphan|2|t|s|1|p|ev-1|action|arc|truth|+/-|reveal\n',
    )
    _write(
        os.path.join(str(tmp_path), 'reference', 'scenes.csv'),
        'id|seq|title|summary|part|pov|location|timeline_day|time_of_day|'
        'duration|type|status|word_count|target_words|architecture_scene\n'
        'sc-1|1|t|s|1|p|l|1|m|2h|character|mapped|0|2500|a-1\n',
    )
    from storyforge.scoring_coverage import score_coverage_at_level
    r = score_coverage_at_level(str(tmp_path), 4)
    assert r['failed'] == 1
    assert 'a-orphan' in r['checks'][0]['detail']


def test_coverage_ignores_pre_map_status_rows(tmp_path):
    """Scenes at status=architecture (pre-scene-map) don't count toward
    coverage — they belong to architecture.csv conceptually."""
    _write(
        os.path.join(str(tmp_path), 'reference', 'architecture.csv'),
        'id|seq|title|summary|part|pov|spine_event|action_sequel|emotional_arc|'
        'value_at_stake|value_shift|turning_point\n'
        'a-1|1|t|s|1|p|ev-1|action|arc|truth|+/-|reveal\n',
    )
    _write(
        os.path.join(str(tmp_path), 'reference', 'scenes.csv'),
        'id|seq|title|summary|part|pov|location|timeline_day|time_of_day|'
        'duration|type|status|word_count|target_words|architecture_scene\n'
        'sc-1|1|t|s|1|p|||||character|architecture|||a-1\n',
    )
    from storyforge.scoring_coverage import score_coverage_at_level
    r = score_coverage_at_level(str(tmp_path), 4)
    # architecture-status scene doesn't satisfy coverage — needs a mapped scene
    assert r['failed'] == 1


# ---------------------------------------------------------------------------
# all_levels + overrides
# ---------------------------------------------------------------------------

def test_score_coverage_all_levels_returns_three(tmp_path):
    """all_levels emits one result per coverage-eligible level (2, 3, 4)."""
    from storyforge.scoring_coverage import score_coverage_all_levels
    results = score_coverage_all_levels(str(tmp_path))
    assert len(results) == 3
    assert [r['level'] for r in results] == [2, 3, 4]


def test_coverage_accepted_count_only_includes_failed_checks(tmp_path):
    """Regression: _result must count accepted ONLY among failed checks.
    A passed check carrying accepted=True (shouldn't happen, but if a
    future override mechanism does set it) must not inflate the
    headline accepted total."""
    from storyforge.scoring_coverage import _result, _check
    checks = [
        _check('passing check', True, ''),
        _check('failed-and-accepted', False, 'detail'),
        _check('failed-no-override', False, 'detail'),
    ]
    # Forcibly set accepted on the passing check too (defensive case).
    checks[0]['accepted'] = True
    checks[1]['accepted'] = True
    r = _result(3, checks)
    assert r['passed'] == 1
    assert r['failed'] == 2
    assert r['accepted'] == 1  # NOT 2 — passed check excluded


def test_coverage_respects_overrides(tmp_path):
    """When the author has recorded an override for a coverage finding,
    it surfaces tagged accepted=True."""
    _write(
        os.path.join(str(tmp_path), 'reference', 'spine.csv'),
        'id|seq|title|summary|function|part\n'
        'ev-1|1|t|s|f|1\n'
        'ev-orphan|2|t|s|f|2\n',
    )
    _write(
        os.path.join(str(tmp_path), 'reference', 'architecture.csv'),
        'id|seq|title|summary|part|pov|spine_event|action_sequel|emotional_arc|'
        'value_at_stake|value_shift|turning_point\n'
        'a-1|1|t|s|1|p|ev-1|action|arc|truth|+/-|reveal\n',
    )
    from storyforge.scoring_state import append_override
    from storyforge.scoring_coverage import score_coverage_at_level
    # Establish the check name once by running, then add override.
    r = score_coverage_at_level(str(tmp_path), 3)
    finding_id = r['checks'][0]['check']
    append_override(
        scope='level-3', axis='coverage', finding_id=finding_id,
        verdict='accepted', rationale='intentional gap', recorded_at='2026-05-25',
        project_dir=str(tmp_path),
    )
    r2 = score_coverage_at_level(str(tmp_path), 3)
    assert r2['checks'][0].get('accepted') is True
    assert r2['accepted'] == 1
