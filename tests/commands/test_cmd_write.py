"""Command-level tests for storyforge.cmd_write module.

Tests parse_args, _resolve_filter, _avg_word_count, _detect_briefs,
_extract_scene_from_response, and _check_voice_guide.
"""

import json
import os

import pytest

from storyforge.cmd_write import (
    parse_args,
    _resolve_filter,
    _avg_word_count,
    _detect_briefs,
    _extract_scene_from_response,
    _check_voice_guide,
    _safe_remove,
    _safe_rmdir,
)


# ============================================================================
# parse_args
# ============================================================================

class TestParseArgs:
    def test_default_args(self):
        args = parse_args([])
        assert args.dry_run is False
        assert args.force is False
        assert args.direct is False
        assert args.interactive is False
        assert args.positional == []
        assert args.scenes is None
        assert args.act is None
        assert args.from_seq is None

    def test_dry_run(self):
        args = parse_args(['--dry-run'])
        assert args.dry_run is True

    def test_force(self):
        args = parse_args(['--force'])
        assert args.force is True

    def test_direct(self):
        args = parse_args(['--direct'])
        assert args.direct is True

    def test_interactive(self):
        args = parse_args(['-i'])
        assert args.interactive is True

    def test_coaching(self):
        args = parse_args(['--coaching', 'coach'])
        assert args.coaching == 'coach'

    def test_scenes_filter(self):
        args = parse_args(['--scenes', 'sc1,sc2'])
        assert args.scenes == 'sc1,sc2'

    def test_act_filter(self):
        args = parse_args(['--act', '2'])
        assert args.act == '2'

    def test_from_seq_filter(self):
        args = parse_args(['--from-seq', '5'])
        assert args.from_seq == '5'

    def test_single_positional(self):
        args = parse_args(['act1-sc01'])
        assert args.positional == ['act1-sc01']

    def test_two_positionals_range(self):
        args = parse_args(['act1-sc01', 'act1-sc05'])
        assert args.positional == ['act1-sc01', 'act1-sc05']


# ============================================================================
# _resolve_filter
# ============================================================================

class TestResolveFilter:
    def test_no_args_returns_all(self):
        args = parse_args([])
        mode, val, val2 = _resolve_filter(args)
        assert mode == 'all'
        assert val is None
        assert val2 is None

    def test_scenes_flag(self):
        args = parse_args(['--scenes', 'sc1,sc2'])
        mode, val, val2 = _resolve_filter(args)
        assert mode == 'scenes'
        assert val == 'sc1,sc2'

    def test_act_flag(self):
        args = parse_args(['--act', '3'])
        mode, val, val2 = _resolve_filter(args)
        assert mode == 'act'
        assert val == '3'

    def test_from_seq_flag(self):
        args = parse_args(['--from-seq', '10'])
        mode, val, val2 = _resolve_filter(args)
        assert mode == 'from_seq'
        assert val == '10'

    def test_single_positional(self):
        args = parse_args(['my-scene'])
        mode, val, val2 = _resolve_filter(args)
        assert mode == 'single'
        assert val == 'my-scene'

    def test_range_positional(self):
        args = parse_args(['act1-sc01', 'act1-sc10'])
        mode, val, val2 = _resolve_filter(args)
        assert mode == 'range'
        assert val == 'act1-sc01'
        assert val2 == 'act1-sc10'


# ============================================================================
# _avg_word_count
# ============================================================================

class TestAvgWordCount:
    def test_with_fixture_csv(self, meta_csv):
        result = _avg_word_count(meta_csv)
        # Fixture has target_words: 2500, 3000, 1500, 2800, 2000, 2200
        expected = int((2500 + 3000 + 1500 + 2800 + 2000 + 2200) / 6)
        assert result == expected

    def test_empty_csv_returns_default(self, tmp_path):
        f = tmp_path / 'empty.csv'
        f.write_text('id|seq|target_words\n')
        result = _avg_word_count(str(f))
        assert result == 2000  # default

    def test_zero_values_excluded(self, tmp_path):
        f = tmp_path / 'zeros.csv'
        f.write_text('id|seq|target_words\n1|1|0\n2|2|3000\n')
        result = _avg_word_count(str(f))
        assert result == 3000


# ============================================================================
# _detect_briefs
# ============================================================================

class TestDetectBriefs:
    def test_detects_existing_briefs(self, project_dir):
        result = _detect_briefs(project_dir)
        assert result is True

    def test_no_briefs_file(self, tmp_path):
        result = _detect_briefs(str(tmp_path))
        assert result is False

    def test_empty_briefs_csv(self, tmp_path):
        os.makedirs(tmp_path / 'reference')
        (tmp_path / 'reference' / 'scene-briefs.csv').write_text(
            'id|goal|conflict|outcome\n'
        )
        result = _detect_briefs(str(tmp_path))
        assert result is False

    def test_briefs_with_only_header(self, tmp_path):
        os.makedirs(tmp_path / 'reference')
        (tmp_path / 'reference' / 'scene-briefs.csv').write_text(
            'id|goal|conflict|outcome\nsc1|||\n'
        )
        result = _detect_briefs(str(tmp_path))
        assert result is False


# ============================================================================
# _extract_scene_from_response
# ============================================================================

class TestExtractSceneFromResponse:
    def test_extracts_text(self, tmp_path):
        log_file = str(tmp_path / 'response.json')
        scene_file = str(tmp_path / 'scene.md')
        with open(log_file, 'w') as f:
            json.dump({
                'content': [{'type': 'text', 'text': 'The morning light filtered in.'}],
                'usage': {'input_tokens': 100, 'output_tokens': 50},
            }, f)
        _extract_scene_from_response(log_file, scene_file)
        assert os.path.isfile(scene_file)
        with open(scene_file) as f:
            content = f.read()
        assert 'morning light' in content

    def test_empty_response(self, tmp_path):
        log_file = str(tmp_path / 'empty.json')
        scene_file = str(tmp_path / 'scene.md')
        with open(log_file, 'w') as f:
            json.dump({'content': [], 'usage': {}}, f)
        _extract_scene_from_response(log_file, scene_file)
        # Should not create file on empty response
        # (the function logs a warning)


# ============================================================================
# _check_voice_guide
# ============================================================================

class TestCheckVoiceGuide:
    def test_with_voice_guide(self, project_dir, capsys):
        _check_voice_guide(project_dir)
        captured = capsys.readouterr()
        # Should NOT warn because fixture has voice-guide.md
        assert 'WARNING: No voice guide' not in captured.out

    def test_without_voice_guide(self, tmp_path, capsys):
        os.makedirs(tmp_path / 'reference')
        (tmp_path / 'storyforge.yaml').write_text('project:\n  title: Test\n')
        _check_voice_guide(str(tmp_path))
        captured = capsys.readouterr()
        assert 'WARNING: No voice guide' in captured.out


# ============================================================================
# Utility helpers
# ============================================================================

class TestUtilities:
    def test_safe_remove_existing(self, tmp_path):
        f = tmp_path / 'test.txt'
        f.write_text('hello')
        _safe_remove(str(f))
        assert not f.exists()

    def test_safe_remove_nonexistent(self, tmp_path):
        # Should not raise
        _safe_remove(str(tmp_path / 'nope.txt'))

    def test_safe_rmdir_existing(self, tmp_path):
        d = tmp_path / 'subdir'
        d.mkdir()
        (d / 'file.txt').write_text('data')
        _safe_rmdir(str(d))
        assert not d.exists()

    def test_safe_rmdir_nonexistent(self, tmp_path):
        # Should not raise
        _safe_rmdir(str(tmp_path / 'nope'))
