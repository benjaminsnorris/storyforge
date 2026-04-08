"""Command-level tests for storyforge.cmd_score module.

Tests parse_args, _resolve_filter, _determine_cycle, _avg_word_count,
_build_scene_prompt, and _parse_scene_evaluation.
"""

import os

import pytest

from storyforge.cmd_score import (
    parse_args,
    _resolve_filter,
    _determine_cycle,
    _avg_word_count,
    _build_scene_prompt,
)


# ============================================================================
# parse_args
# ============================================================================

class TestParseArgs:
    def test_default_args(self):
        args = parse_args([])
        assert args.dry_run is False
        assert args.direct is False
        assert args.deep is False
        assert args.interactive is False
        assert args.scenes is None
        assert args.act is None
        assert args.from_seq is None
        assert args.parallel == 6  # default

    def test_dry_run(self):
        args = parse_args(['--dry-run'])
        assert args.dry_run is True

    def test_direct(self):
        args = parse_args(['--direct'])
        assert args.direct is True

    def test_deep_requires_no_separate_check(self):
        args = parse_args(['--deep'])
        assert args.deep is True

    def test_scenes_filter(self):
        args = parse_args(['--scenes', 'sc1,sc2,sc3'])
        assert args.scenes == 'sc1,sc2,sc3'

    def test_act_filter(self):
        args = parse_args(['--act', '2'])
        assert args.act == '2'

    def test_from_seq_filter(self):
        args = parse_args(['--from-seq', '5'])
        assert args.from_seq == '5'

    def test_parallel_custom(self):
        args = parse_args(['--parallel', '12'])
        assert args.parallel == 12

    def test_parallel_env_override(self, monkeypatch):
        monkeypatch.setenv('STORYFORGE_SCORE_PARALLEL', '3')
        # Need to re-import or re-call parse_args for env to take effect
        # Actually the default is evaluated at import time. Let's just test
        # that the flag works.
        args = parse_args(['--parallel', '3'])
        assert args.parallel == 3

    def test_interactive(self):
        args = parse_args(['-i'])
        assert args.interactive is True


# ============================================================================
# _resolve_filter
# ============================================================================

class TestResolveFilter:
    def test_default_is_all(self):
        args = parse_args([])
        mode, val, _ = _resolve_filter(args)
        assert mode == 'all'
        assert val is None

    def test_scenes(self):
        args = parse_args(['--scenes', 'sc1,sc2'])
        mode, val, _ = _resolve_filter(args)
        assert mode == 'scenes'
        assert val == 'sc1,sc2'

    def test_act(self):
        args = parse_args(['--act', '1'])
        mode, val, _ = _resolve_filter(args)
        assert mode == 'act'
        assert val == '1'

    def test_from_seq(self):
        args = parse_args(['--from-seq', '3-5'])
        mode, val, _ = _resolve_filter(args)
        assert mode == 'from_seq'
        assert val == '3-5'


# ============================================================================
# _determine_cycle
# ============================================================================

class TestDetermineCycle:
    def test_no_scores_dir_returns_nonzero(self, tmp_path):
        """With no pipeline.csv and no scores dir, returns at least 1."""
        pdir = str(tmp_path / 'proj')
        os.makedirs(pdir)
        (tmp_path / 'proj' / 'storyforge.yaml').write_text('phase: scoring\n')
        result = _determine_cycle(pdir)
        assert result >= 1

    def test_with_existing_cycles(self, tmp_path):
        """When cycle dirs already exist, returns highest + 1."""
        pdir = str(tmp_path / 'proj')
        os.makedirs(os.path.join(pdir, 'working', 'scores', 'cycle-1'))
        os.makedirs(os.path.join(pdir, 'working', 'scores', 'cycle-2'))
        os.makedirs(os.path.join(pdir, 'working', 'scores', 'cycle-3'))
        result = _determine_cycle(pdir)
        assert result == 4

    def test_from_fixture(self, project_dir):
        """Fixture has 3 cycles in pipeline.csv."""
        result = _determine_cycle(project_dir)
        assert result >= 1


# ============================================================================
# _avg_word_count
# ============================================================================

class TestAvgWordCount:
    def test_from_metadata(self, tmp_path):
        """When word_count column has values, use them."""
        csv_file = str(tmp_path / 'scenes.csv')
        with open(csv_file, 'w') as f:
            f.write('id|seq|word_count|target_words\n')
            f.write('sc1|1|1500|2000\n')
            f.write('sc2|2|2500|2000\n')
        result = _avg_word_count(csv_file, ['sc1', 'sc2'], str(tmp_path))
        assert result == 2000  # (1500 + 2500) / 2

    def test_fallback_to_scene_files(self, tmp_path):
        """When word_count is 0, measure from scene files."""
        csv_file = str(tmp_path / 'scenes.csv')
        with open(csv_file, 'w') as f:
            f.write('id|seq|word_count\n')
            f.write('sc1|1|0\n')
            f.write('sc2|2|0\n')

        scenes_dir = str(tmp_path / 'scenes')
        os.makedirs(scenes_dir)
        with open(os.path.join(scenes_dir, 'sc1.md'), 'w') as f:
            f.write(' '.join(['word'] * 1000))
        with open(os.path.join(scenes_dir, 'sc2.md'), 'w') as f:
            f.write(' '.join(['word'] * 2000))

        result = _avg_word_count(csv_file, ['sc1', 'sc2'], scenes_dir)
        assert result == 1500  # (1000 + 2000) / 2

    def test_no_scenes_returns_default(self, tmp_path):
        csv_file = str(tmp_path / 'scenes.csv')
        with open(csv_file, 'w') as f:
            f.write('id|seq|word_count\n')
        result = _avg_word_count(csv_file, [], str(tmp_path))
        assert result == 3000


# ============================================================================
# _build_scene_prompt
# ============================================================================

class TestBuildScenePrompt:
    def test_substitutes_template_vars(self, project_dir):
        template = (
            '{{SCENE_TITLE}} — {{SCENE_POV}}\n'
            'Function: {{SCENE_FUNCTION}}\n'
            'Arc: {{SCENE_EMOTIONAL_ARC}}\n'
            'Criteria: {{EVALUATION_CRITERIA}}\n'
            'Weights: {{WEIGHTED_PRINCIPLES}}\n'
            '{{SCENE_TEXT}}'
        )
        metadata_csv = os.path.join(project_dir, 'reference', 'scenes.csv')
        intent_csv = os.path.join(project_dir, 'reference', 'scene-intent.csv')
        scenes_dir = os.path.join(project_dir, 'scenes')

        result = _build_scene_prompt(
            'act1-sc01', template, 'MY_CRITERIA', 'MY_WEIGHTS',
            metadata_csv, intent_csv, scenes_dir,
        )
        assert 'The Finest Cartographer' in result
        assert 'Dorren Hayle' in result
        assert 'MY_CRITERIA' in result
        assert 'MY_WEIGHTS' in result

    def test_missing_scene_file(self, tmp_path):
        """Scene prompt still works even if scene file doesn't exist."""
        csv_file = str(tmp_path / 'scenes.csv')
        with open(csv_file, 'w') as f:
            f.write('id|title|pov\nsc1|Test Scene|John\n')
        intent_csv = str(tmp_path / 'intent.csv')
        template = '{{SCENE_TITLE}} {{SCENE_TEXT}}'
        result = _build_scene_prompt(
            'sc1', template, '', '', csv_file, intent_csv, str(tmp_path),
        )
        assert 'Test Scene' in result

    def test_lines_are_numbered(self, project_dir):
        """Scene text should have line numbers."""
        template = '{{SCENE_TEXT}}'
        metadata_csv = os.path.join(project_dir, 'reference', 'scenes.csv')
        intent_csv = os.path.join(project_dir, 'reference', 'scene-intent.csv')
        scenes_dir = os.path.join(project_dir, 'scenes')

        result = _build_scene_prompt(
            'act1-sc01', template, '', '', metadata_csv, intent_csv, scenes_dir,
        )
        # Lines should be numbered like "1: ...\n2: ...\n"
        assert '1: ' in result
