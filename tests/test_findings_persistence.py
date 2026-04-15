"""Tests for deterministic scorer findings persistence."""

import os
import csv
import pytest


class TestRepetitionFindings:
    def _setup_project(self, tmp_path):
        """Create a minimal project with scenes that have repeated phrases."""
        project_dir = str(tmp_path / 'project')
        scenes_dir = os.path.join(project_dir, 'scenes')
        ref_dir = os.path.join(project_dir, 'reference')
        os.makedirs(scenes_dir)
        os.makedirs(ref_dir)

        with open(os.path.join(ref_dir, 'scenes.csv'), 'w') as f:
            f.write('id|seq|title|part|pov|status|word_count|target_words\n')
            f.write('s01|1|Scene 1|1|Alice|drafted|100|1000\n')
            f.write('s02|2|Scene 2|1|Bob|drafted|100|1000\n')
            f.write('s03|3|Scene 3|1|Alice|drafted|100|1000\n')

        with open(os.path.join(scenes_dir, 's01.md'), 'w') as f:
            f.write('Alice stood at the edge of the garden. She looked at the flowers. '
                    'The dog put her chin on her paws and watched. '
                    'Alice could feel the warmth of the sun on her face.\n')
        with open(os.path.join(scenes_dir, 's02.md'), 'w') as f:
            f.write('Bob walked to the edge of the yard. He looked at the house. '
                    'The dog put her chin on her paws again. '
                    'He could feel the cold of the night air.\n')
        with open(os.path.join(scenes_dir, 's03.md'), 'w') as f:
            f.write('They met at the edge of the road. She looked at him. '
                    'The dog lifted her chin on her paws. '
                    'She could feel the tension in the room.\n')

        with open(os.path.join(project_dir, 'storyforge.yaml'), 'w') as f:
            f.write('project:\n  title: Test\n')

        return project_dir

    def test_writes_repetition_findings_csv(self, tmp_path):
        from storyforge.cmd_score import _score_repetition

        project_dir = self._setup_project(tmp_path)
        cycle_dir = str(tmp_path / 'cycle-1')
        os.makedirs(cycle_dir)

        _score_repetition(['s01', 's02', 's03'], project_dir, cycle_dir)

        findings_path = os.path.join(cycle_dir, 'repetition-findings.csv')
        assert os.path.isfile(findings_path)

        with open(findings_path) as f:
            content = f.read()
        assert 'phrase|category|severity|count|scene_ids' in content
        lines = content.strip().split('\n')
        assert len(lines) >= 2  # header + at least one finding

    def test_findings_contain_phrase_and_scenes(self, tmp_path):
        from storyforge.cmd_score import _score_repetition

        project_dir = self._setup_project(tmp_path)
        cycle_dir = str(tmp_path / 'cycle-1')
        os.makedirs(cycle_dir)

        _score_repetition(['s01', 's02', 's03'], project_dir, cycle_dir)

        findings_path = os.path.join(cycle_dir, 'repetition-findings.csv')
        with open(findings_path, newline='', encoding='utf-8') as f:
            reader = csv.DictReader(f, delimiter='|')
            rows = list(reader)

        multi_scene = [r for r in rows if ';' in r.get('scene_ids', '')]
        assert len(multi_scene) >= 1

        for row in rows:
            assert row.get('phrase')
            assert row.get('category')
            assert row.get('severity') in ('high', 'medium')
            assert int(row.get('count', '0')) >= 2

    def test_scores_csv_still_written(self, tmp_path):
        from storyforge.cmd_score import _score_repetition

        project_dir = self._setup_project(tmp_path)
        cycle_dir = str(tmp_path / 'cycle-1')
        os.makedirs(cycle_dir)

        scores_path = _score_repetition(['s01', 's02', 's03'], project_dir, cycle_dir)
        assert os.path.isfile(scores_path)
        with open(scores_path) as f:
            content = f.read()
        assert 'id|prose_repetition' in content
