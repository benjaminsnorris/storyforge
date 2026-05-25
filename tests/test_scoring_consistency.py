"""Tests for scoring_consistency.py — registry conformance per level (#229)."""

import os

from storyforge.csv_cli import update_field
from storyforge.scoring_consistency import (
    score_consistency_at_level,
    score_consistency_all_levels,
    LEVEL_FILES,
)


def test_returns_per_level_results(project_dir):
    """Smoke test: every level returns the expected result shape."""
    for level in LEVEL_FILES:
        r = score_consistency_at_level(project_dir, level)
        assert r['level'] == level
        assert r['name'] == 'registry-consistency'
        assert isinstance(r['checks'], list)
        # passed + failed accounts for every check
        assert r['passed'] + r['failed'] == len(r['checks'])


def test_orphan_value_at_stake_flagged_at_level_5(project_dir):
    """Introduce an orphan value reference in scene-intent.csv → level 5
    (scene-intent's level) should report it."""
    intent = os.path.join(project_dir, 'reference', 'scene-intent.csv')
    # act1-sc01 is in the fixture; set its value_at_stake to a non-registry value
    update_field(intent, 'act1-sc01', 'value_at_stake', 'definitely-not-a-real-value')

    r = score_consistency_at_level(project_dir, 5)
    assert r['failed'] >= 1
    bad = [c for c in r['checks'] if not c['passed']]
    assert any('scene-intent.csv' in c['check'] and 'value_at_stake' in c['check']
               for c in bad)


def test_clean_no_orphan_state_emits_one_passed_check(tmp_path):
    """With a fresh empty-but-valid project, no orphans → one synthetic
    'all references resolve' passed check per level."""
    # Build a minimal clean project structure
    ref = tmp_path / 'reference'
    ref.mkdir()
    (ref / 'scenes.csv').write_text(
        'id|seq|title|part|pov|location|timeline_day|time_of_day|duration|type|'
        'status|word_count|target_words|target_pages|panel_count|page_count|'
        'architecture_scene\n'
    )
    (ref / 'scene-intent.csv').write_text(
        'id|function|action_sequel|emotional_arc|value_at_stake|value_shift|'
        'turning_point|characters|on_stage|mice_threads|theme_threads\n'
    )
    (ref / 'scene-briefs.csv').write_text(
        'id|goal|conflict|outcome|crisis|decision|knowledge_in|knowledge_out|'
        'key_actions|key_dialogue|emotions|motifs|subtext|continuity_deps|'
        'has_overflow|physical_state_in|physical_state_out|page_layout|'
        'panel_breakdown|visual_keywords|page_turn_beats|caption_strategy\n'
    )
    (ref / 'spine.csv').write_text('id|seq|title|function|part\n')
    (ref / 'architecture.csv').write_text(
        'id|seq|title|part|pov|spine_event|action_sequel|emotional_arc|'
        'value_at_stake|value_shift|turning_point\n'
    )
    # Minimal storyforge.yaml so detect_project_root works
    (tmp_path / 'storyforge.yaml').write_text('project:\n  title: test\n')

    for level in LEVEL_FILES:
        r = score_consistency_at_level(str(tmp_path), level)
        assert r['failed'] == 0
        assert r['passed'] == 1
        assert 'references resolve' in r['checks'][0]['check']


def test_all_levels_returns_per_level_results(project_dir):
    results = score_consistency_all_levels(project_dir)
    assert len(results) == 4  # levels 3, 4, 5, 6
    assert [r['level'] for r in results] == [3, 4, 5, 6]
