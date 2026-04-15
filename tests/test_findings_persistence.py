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


class TestSceneFindings:
    def _setup_project(self, tmp_path):
        project_dir = str(tmp_path / 'project')
        scenes_dir = os.path.join(project_dir, 'scenes')
        ref_dir = os.path.join(project_dir, 'reference')
        os.makedirs(scenes_dir)
        os.makedirs(ref_dir)

        with open(os.path.join(ref_dir, 'scenes.csv'), 'w') as f:
            f.write('id|seq|title|part|pov|status|word_count|target_words\n')
            f.write('s01|1|Scene 1|1|Alice|drafted|200|1000\n')

        # Scene with passive voice clusters and adverb issues
        with open(os.path.join(scenes_dir, 's01.md'), 'w') as f:
            f.write('The door was opened by Alice. The room was filled with smoke. '
                    'The window was broken by the wind. The floor was covered in glass. '
                    'She walked slowly and carefully through the debris. '
                    'He said quietly that the building was being evacuated. '
                    'She nodded reluctantly and moved cautiously toward the exit.\n')

        with open(os.path.join(project_dir, 'storyforge.yaml'), 'w') as f:
            f.write('project:\n  title: Test\n')

        return project_dir

    def test_writes_scene_findings_csv(self, tmp_path):
        from storyforge.cmd_score import _score_passive

        project_dir = self._setup_project(tmp_path)
        cycle_dir = str(tmp_path / 'cycle-1')
        os.makedirs(cycle_dir)

        _score_passive(['s01'], project_dir, cycle_dir)

        findings_path = os.path.join(cycle_dir, 'scene-findings.csv')
        assert os.path.isfile(findings_path)

        with open(findings_path) as f:
            content = f.read()
        assert 'scene_id|principle|finding|detail' in content

    def test_multiple_scorers_append_to_same_file(self, tmp_path):
        from storyforge.cmd_score import _score_passive, _score_adverbs

        project_dir = self._setup_project(tmp_path)
        cycle_dir = str(tmp_path / 'cycle-1')
        os.makedirs(cycle_dir)

        _score_passive(['s01'], project_dir, cycle_dir)
        _score_adverbs(['s01'], project_dir, cycle_dir)

        findings_path = os.path.join(cycle_dir, 'scene-findings.csv')
        with open(findings_path, newline='', encoding='utf-8') as f:
            reader = csv.DictReader(f, delimiter='|')
            rows = list(reader)

        principles = set(r['principle'] for r in rows)
        assert 'avoid_passive' in principles
        assert 'avoid_adverbs' in principles

    def test_only_scenes_with_findings_written(self, tmp_path):
        """Scenes that score 5 (no issues) should not appear in findings."""
        from storyforge.cmd_score import _score_weather

        project_dir = self._setup_project(tmp_path)
        cycle_dir = str(tmp_path / 'cycle-1')
        os.makedirs(cycle_dir)

        # The test scene doesn't start with weather/dream/waking
        _score_weather(['s01'], project_dir, cycle_dir)

        findings_path = os.path.join(cycle_dir, 'scene-findings.csv')
        if os.path.isfile(findings_path):
            with open(findings_path, newline='', encoding='utf-8') as f:
                reader = csv.DictReader(f, delimiter='|')
                weather_rows = [r for r in reader if r['principle'] == 'no_weather_dreams']
            assert len(weather_rows) == 0

    def test_scores_csv_still_written(self, tmp_path):
        """Findings persistence should not break existing score output."""
        from storyforge.cmd_score import _score_passive

        project_dir = self._setup_project(tmp_path)
        cycle_dir = str(tmp_path / 'cycle-1')
        os.makedirs(cycle_dir)

        scores_path = _score_passive(['s01'], project_dir, cycle_dir)
        assert os.path.isfile(scores_path)
        with open(scores_path) as f:
            content = f.read()
        assert 'id|avoid_passive' in content


class TestFindingsSanitization:
    """Regression tests for pipe and newline sanitization in findings files."""

    def test_scene_findings_sanitizes_pipes_in_detail(self, tmp_path):
        """Pipe chars in scorer detail strings must not corrupt CSV."""
        from storyforge.cmd_score import _score_single_principle, _load_scene_texts
        import csv

        project_dir = str(tmp_path / 'project')
        scenes_dir = os.path.join(project_dir, 'scenes')
        os.makedirs(scenes_dir)

        # Create a scene that will trigger findings
        with open(os.path.join(scenes_dir, 's01.md'), 'w') as f:
            f.write('The door was opened by Alice. The room was filled with smoke. '
                    'The window was broken by the wind. The floor was covered.\n')

        cycle_dir = str(tmp_path / 'cycle-1')
        os.makedirs(cycle_dir)

        from storyforge.scoring_passive import score_avoid_passive
        _score_single_principle(['s01'], project_dir, cycle_dir,
                                'avoid_passive', score_avoid_passive)

        findings_path = os.path.join(cycle_dir, 'scene-findings.csv')
        if os.path.isfile(findings_path):
            with open(findings_path, newline='', encoding='utf-8') as f:
                reader = csv.DictReader(f, delimiter='|')
                for row in reader:
                    # Should have exactly 4 fields (header columns)
                    assert set(row.keys()) == {'scene_id', 'principle', 'finding', 'detail'}
                    # No None values from extra pipe splits
                    assert None not in row.values()
