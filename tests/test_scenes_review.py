"""Tests for scenes-export and scenes-import commands."""

import os

from storyforge.csv_cli import get_field


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


class TestParse:
    """Test the markdown parser independently."""

    def test_parse_single_scene(self):
        from storyforge.cmd_scenes_import import parse_markdown

        md = (
            '## test-scene\n'
            '\n'
            '### Structural\n'
            'seq: 5\n'
            'title: Test Scene\n'
            '\n'
            '### Intent\n'
            'function: Introduce conflict\n'
            '\n'
            '### Brief\n'
            'goal: Establish stakes\n'
        )
        scenes = parse_markdown(md)
        assert 'test-scene' in scenes
        assert scenes['test-scene']['Structural']['seq'] == '5'
        assert scenes['test-scene']['Structural']['title'] == 'Test Scene'
        assert scenes['test-scene']['Intent']['function'] == 'Introduce conflict'
        assert scenes['test-scene']['Brief']['goal'] == 'Establish stakes'

    def test_parse_multiple_scenes(self):
        from storyforge.cmd_scenes_import import parse_markdown

        md = (
            '## scene-a\n'
            '\n'
            '### Structural\n'
            'seq: 1\n'
            '\n'
            '## scene-b\n'
            '\n'
            '### Structural\n'
            'seq: 2\n'
        )
        scenes = parse_markdown(md)
        assert len(scenes) == 2
        assert scenes['scene-a']['Structural']['seq'] == '1'
        assert scenes['scene-b']['Structural']['seq'] == '2'

    def test_parse_empty_field(self):
        from storyforge.cmd_scenes_import import parse_markdown

        md = (
            '## test-scene\n'
            '\n'
            '### Structural\n'
            'seq: 1\n'
            'title: \n'
        )
        scenes = parse_markdown(md)
        assert scenes['test-scene']['Structural']['title'] == ''

    def test_parse_colon_in_value(self):
        from storyforge.cmd_scenes_import import parse_markdown

        md = (
            '## test-scene\n'
            '\n'
            '### Brief\n'
            'key_dialogue: She said: "Run!"\n'
        )
        scenes = parse_markdown(md)
        assert scenes['test-scene']['Brief']['key_dialogue'] == 'She said: "Run!"'

    def test_parse_continuation_line(self):
        from storyforge.cmd_scenes_import import parse_markdown

        md = (
            '## test-scene\n'
            '\n'
            '### Brief\n'
            'goal: Establish the world and introduce\n'
            '  the main character\n'
        )
        scenes = parse_markdown(md)
        assert scenes['test-scene']['Brief']['goal'] == 'Establish the world and introduce the main character'


class TestImport:
    def test_import_no_changes(self, project_dir):
        """Export then immediately import — nothing should change."""
        from storyforge.cmd_scenes_export import export_scenes
        from storyforge.cmd_scenes_import import import_scenes

        output = os.path.join(project_dir, 'working', 'scenes-review.md')
        export_scenes(project_dir, output)
        changes = import_scenes(project_dir, output, dry_run=True)
        assert changes == []

    def test_import_detects_change(self, project_dir):
        from storyforge.cmd_scenes_export import export_scenes
        from storyforge.cmd_scenes_import import import_scenes

        output = os.path.join(project_dir, 'working', 'scenes-review.md')
        export_scenes(project_dir, output)

        # Edit the markdown
        content = open(output).read()
        content = content.replace(
            'title: The Finest Cartographer',
            'title: The Last Cartographer',
        )
        with open(output, 'w') as f:
            f.write(content)

        changes = import_scenes(project_dir, output, dry_run=True)
        assert len(changes) == 1
        assert changes[0] == ('act1-sc01', 'reference/scenes.csv', 'title',
                              'The Finest Cartographer', 'The Last Cartographer')

    def test_import_writes_change(self, project_dir):
        from storyforge.cmd_scenes_export import export_scenes
        from storyforge.cmd_scenes_import import import_scenes

        output = os.path.join(project_dir, 'working', 'scenes-review.md')
        export_scenes(project_dir, output)

        content = open(output).read()
        content = content.replace(
            'title: The Finest Cartographer',
            'title: The Last Cartographer',
        )
        with open(output, 'w') as f:
            f.write(content)

        changes = import_scenes(project_dir, output, dry_run=False)
        assert len(changes) == 1

        # Verify the CSV was actually updated
        csv_path = os.path.join(project_dir, 'reference', 'scenes.csv')
        assert get_field(csv_path, 'act1-sc01', 'title') == 'The Last Cartographer'

    def test_import_multiple_changes(self, project_dir):
        from storyforge.cmd_scenes_export import export_scenes
        from storyforge.cmd_scenes_import import import_scenes

        output = os.path.join(project_dir, 'working', 'scenes-review.md')
        export_scenes(project_dir, output)

        content = open(output).read()
        content = content.replace('pov: Dorren Hayle', 'pov: Elara Voss')
        with open(output, 'w') as f:
            f.write(content)

        changes = import_scenes(project_dir, output, dry_run=False)
        # Three scenes have pov: Dorren Hayle, so all three should change
        assert len(changes) == 3

        csv_path = os.path.join(project_dir, 'reference', 'scenes.csv')
        assert get_field(csv_path, 'act1-sc01', 'pov') == 'Elara Voss'
        assert get_field(csv_path, 'act1-sc02', 'pov') == 'Elara Voss'
        assert get_field(csv_path, 'act2-sc03', 'pov') == 'Elara Voss'

    def test_import_unknown_scene_skipped(self, project_dir):
        from storyforge.cmd_scenes_import import import_scenes

        md_path = os.path.join(project_dir, 'working', 'scenes-review.md')
        os.makedirs(os.path.dirname(md_path), exist_ok=True)
        with open(md_path, 'w') as f:
            f.write('## nonexistent-scene\n\n### Structural\nseq: 99\n')

        changes = import_scenes(project_dir, md_path, dry_run=False)
        assert changes == []
