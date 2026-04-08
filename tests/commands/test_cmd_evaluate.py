"""Command-level tests for storyforge.cmd_evaluate module.

Tests parse_args, _resolve_filter, CORE_EVALUATORS, _load_custom_evaluators,
_resolve_voice_guide, and _build_file_list.
"""

import os

import pytest

from storyforge.cmd_evaluate import (
    parse_args,
    _resolve_filter,
    CORE_EVALUATORS,
    _load_custom_evaluators,
    _resolve_voice_guide,
)


# ============================================================================
# parse_args
# ============================================================================

class TestParseArgs:
    def test_default_args(self):
        args = parse_args([])
        assert args.manuscript is False
        assert args.chapter is None
        assert args.act is None
        assert args.scenes is None
        assert args.scene is None
        assert args.from_seq is None
        assert args.evaluator is None
        assert args.final is False
        assert args.interactive is False
        assert args.direct is False
        assert args.dry_run is False

    def test_manuscript(self):
        args = parse_args(['--manuscript'])
        assert args.manuscript is True

    def test_chapter(self):
        args = parse_args(['--chapter', '5'])
        assert args.chapter == 5

    def test_act(self):
        args = parse_args(['--act', '2'])
        assert args.act == '2'

    def test_scenes(self):
        args = parse_args(['--scenes', 'sc1,sc2'])
        assert args.scenes == 'sc1,sc2'

    def test_scene_single(self):
        args = parse_args(['--scene', 'act1-sc01'])
        assert args.scene == 'act1-sc01'

    def test_from_seq(self):
        args = parse_args(['--from-seq', '5'])
        assert args.from_seq == '5'

    def test_evaluator(self):
        args = parse_args(['--evaluator', 'line-editor'])
        assert args.evaluator == 'line-editor'

    def test_final(self):
        args = parse_args(['--final'])
        assert args.final is True

    def test_interactive(self):
        args = parse_args(['-i'])
        assert args.interactive is True

    def test_direct(self):
        args = parse_args(['--direct'])
        assert args.direct is True

    def test_dry_run(self):
        args = parse_args(['--dry-run'])
        assert args.dry_run is True


# ============================================================================
# _resolve_filter
# ============================================================================

class TestResolveFilter:
    def test_default_is_all(self):
        args = parse_args([])
        result = _resolve_filter(args)
        assert result[0] == 'all'

    def test_manuscript(self):
        args = parse_args(['--manuscript'])
        result = _resolve_filter(args)
        assert result[0] == 'manuscript'

    def test_chapter(self):
        args = parse_args(['--chapter', '3'])
        result = _resolve_filter(args)
        assert result[0] == 'chapter'
        assert result[1] == '3'

    def test_act(self):
        args = parse_args(['--act', '2'])
        result = _resolve_filter(args)
        assert result[0] == 'act'
        assert result[1] == '2'

    def test_single_scene(self):
        args = parse_args(['--scene', 'act1-sc01'])
        result = _resolve_filter(args)
        assert result[0] == 'single'
        assert result[2] == 'act1-sc01'

    def test_scenes_comma(self):
        args = parse_args(['--scenes', 'sc1,sc2'])
        result = _resolve_filter(args)
        assert result[0] == 'scenes'
        assert result[4] == 'sc1,sc2'

    def test_scenes_range(self):
        args = parse_args(['--scenes', 'sc1..sc5'])
        result = _resolve_filter(args)
        assert result[0] == 'range'
        assert result[2] == 'sc1'
        assert result[3] == 'sc5'

    def test_from_seq(self):
        args = parse_args(['--from-seq', '10'])
        result = _resolve_filter(args)
        assert result[0] == 'from_seq'
        assert result[5] == '10'


# ============================================================================
# CORE_EVALUATORS
# ============================================================================

class TestCoreEvaluators:
    def test_is_list(self):
        assert isinstance(CORE_EVALUATORS, list)

    def test_has_six_evaluators(self):
        assert len(CORE_EVALUATORS) == 6

    def test_expected_evaluators(self):
        assert 'literary-agent' in CORE_EVALUATORS
        assert 'developmental-editor' in CORE_EVALUATORS
        assert 'line-editor' in CORE_EVALUATORS
        assert 'genre-expert' in CORE_EVALUATORS
        assert 'first-reader' in CORE_EVALUATORS
        assert 'writing-coach' in CORE_EVALUATORS


# ============================================================================
# _load_custom_evaluators
# ============================================================================

class TestLoadCustomEvaluators:
    def test_empty_when_no_custom(self, project_dir):
        """Fixture has no custom evaluators."""
        result = _load_custom_evaluators(project_dir)
        assert result == []

    def test_missing_yaml(self, tmp_path):
        result = _load_custom_evaluators(str(tmp_path))
        assert result == []

    def test_with_custom_evaluator(self, tmp_path):
        yaml_file = tmp_path / 'storyforge.yaml'
        persona_file = tmp_path / 'personas' / 'my-evaluator.md'
        os.makedirs(tmp_path / 'personas')
        persona_file.write_text('You are a test evaluator.')
        yaml_file.write_text(
            'project:\n'
            '  title: Test\n'
            'custom_evaluators:\n'
            '  - name: my-evaluator\n'
            '    persona_file: personas/my-evaluator.md\n'
        )
        result = _load_custom_evaluators(str(tmp_path))
        assert len(result) == 1
        assert result[0][0] == 'my-evaluator'


# ============================================================================
# _resolve_voice_guide
# ============================================================================

class TestResolveVoiceGuide:
    def test_finds_voice_guide_in_fixture(self, project_dir):
        path, content = _resolve_voice_guide(project_dir)
        assert path is not None
        assert 'voice' in path.lower() or 'guide' in path.lower()
        assert len(content) > 0

    def test_returns_none_when_missing(self, tmp_path):
        os.makedirs(tmp_path / 'reference')
        (tmp_path / 'storyforge.yaml').write_text('project:\n  title: Test\n')
        path, content = _resolve_voice_guide(str(tmp_path))
        assert path is None
        assert content == ''

    def test_fallback_to_reference_dir(self, tmp_path):
        """Falls back to reference/voice-guide.md when no custom path."""
        os.makedirs(tmp_path / 'reference')
        (tmp_path / 'reference' / 'voice-guide.md').write_text('My voice guide')
        (tmp_path / 'storyforge.yaml').write_text('project:\n  title: Test\n')
        path, content = _resolve_voice_guide(str(tmp_path))
        assert path is not None
        assert 'My voice guide' in content


# ============================================================================
# Filter tuple structure
# ============================================================================

class TestFilterTupleStructure:
    def test_all_mode_has_6_elements(self):
        args = parse_args([])
        result = _resolve_filter(args)
        assert len(result) == 6

    def test_chapter_mode_value_is_string(self):
        args = parse_args(['--chapter', '5'])
        result = _resolve_filter(args)
        assert result[1] == '5'
