"""Tests for scenes-export and scenes-import commands."""

import os

from storyforge.csv_cli import get_field


# ============================================================================
# Column definitions (must match cmd_scenes_export.py)
# ============================================================================

STRUCTURAL_FIELDS = [
    'seq', 'title', 'part', 'pov', 'location', 'timeline_day',
    'time_of_day', 'duration', 'type', 'status', 'word_count', 'target_words',
]
INTENT_FIELDS = [
    'function', 'action_sequel', 'emotional_arc', 'value_at_stake',
    'value_shift', 'turning_point', 'characters', 'on_stage', 'mice_threads',
]
BRIEF_FIELDS = [
    'goal', 'conflict', 'outcome', 'crisis', 'decision', 'knowledge_in',
    'knowledge_out', 'key_actions', 'key_dialogue', 'emotions', 'motifs',
    'subtext', 'continuity_deps', 'has_overflow', 'physical_state_in',
    'physical_state_out',
]


class TestExport:
    def test_export_creates_file(self, project_dir):
        from storyforge.cmd_scenes_export import export_scenes

        output = os.path.join(project_dir, 'working', 'scenes-review.md')
        export_scenes(project_dir, output)
        assert os.path.isfile(output)

    def test_export_has_scene_headings(self, project_dir):
        from storyforge.cmd_scenes_export import export_scenes

        output = os.path.join(project_dir, 'working', 'scenes-review.md')
        export_scenes(project_dir, output)
        content = open(output).read()
        assert '## act1-sc01' in content
        assert '## act1-sc02' in content

    def test_export_ordered_by_seq(self, project_dir):
        from storyforge.cmd_scenes_export import export_scenes

        output = os.path.join(project_dir, 'working', 'scenes-review.md')
        export_scenes(project_dir, output)
        content = open(output).read()
        pos1 = content.index('## act1-sc01')
        pos2 = content.index('## act1-sc02')
        assert pos1 < pos2

    def test_export_has_three_sections(self, project_dir):
        from storyforge.cmd_scenes_export import export_scenes

        output = os.path.join(project_dir, 'working', 'scenes-review.md')
        export_scenes(project_dir, output)
        content = open(output).read()
        assert '### Structural' in content
        assert '### Intent' in content
        assert '### Brief' in content

    def test_export_structural_fields(self, project_dir):
        from storyforge.cmd_scenes_export import export_scenes

        output = os.path.join(project_dir, 'working', 'scenes-review.md')
        export_scenes(project_dir, output)
        content = open(output).read()
        assert 'title: The Finest Cartographer' in content
        assert 'pov: Dorren Hayle' in content

    def test_export_intent_fields(self, project_dir):
        from storyforge.cmd_scenes_export import export_scenes

        output = os.path.join(project_dir, 'working', 'scenes-review.md')
        export_scenes(project_dir, output)
        content = open(output).read()
        assert 'action_sequel: action' in content
        assert 'value_at_stake: truth' in content

    def test_export_brief_fields(self, project_dir):
        from storyforge.cmd_scenes_export import export_scenes

        output = os.path.join(project_dir, 'working', 'scenes-review.md')
        export_scenes(project_dir, output)
        content = open(output).read()
        assert 'outcome: no-and' in content

    def test_export_with_act_filter(self, project_dir):
        from storyforge.cmd_scenes_export import export_scenes

        output = os.path.join(project_dir, 'working', 'scenes-review.md')
        export_scenes(project_dir, output, filter_mode='act', filter_value='1')
        content = open(output).read()
        # Both test scenes are in part 1
        assert '## act1-sc01' in content
        assert '## act1-sc02' in content

    def test_export_with_scenes_filter(self, project_dir):
        from storyforge.cmd_scenes_export import export_scenes

        output = os.path.join(project_dir, 'working', 'scenes-review.md')
        export_scenes(project_dir, output, filter_mode='scenes', filter_value='act1-sc01')
        content = open(output).read()
        assert '## act1-sc01' in content
        assert '## act1-sc02' not in content

    def test_export_empty_fields_present(self, project_dir):
        from storyforge.cmd_scenes_export import export_scenes

        output = os.path.join(project_dir, 'working', 'scenes-review.md')
        export_scenes(project_dir, output)
        content = open(output).read()
        # word_count is 0 in fixture, should still appear
        assert 'word_count: 0' in content
