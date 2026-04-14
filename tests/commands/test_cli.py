"""Tests for storyforge.cli — shared CLI helpers.

Covers base_parser factory, add_scene_filter_args, resolve_filter_args,
apply_coaching_override, flag defaults, aliases, and coaching validation.
"""

import os
import argparse
from types import SimpleNamespace

import pytest

from storyforge.cli import (
    base_parser, add_scene_filter_args, resolve_filter_args,
    apply_coaching_override,
)


# ============================================================================
# base_parser
# ============================================================================


class TestBaseParser:
    """Test the base_parser factory."""

    def test_returns_argument_parser(self):
        parser = base_parser('test', 'A test command')
        assert isinstance(parser, argparse.ArgumentParser)

    def test_prog_includes_storyforge_prefix(self):
        parser = base_parser('score', 'Score scenes')
        assert parser.prog == 'storyforge score'

    def test_description_set(self):
        parser = base_parser('write', 'Draft scenes')
        assert parser.description == 'Draft scenes'

    def test_dry_run_default_false(self):
        parser = base_parser('test', 'desc')
        args = parser.parse_args([])
        assert args.dry_run is False

    def test_dry_run_flag(self):
        parser = base_parser('test', 'desc')
        args = parser.parse_args(['--dry-run'])
        assert args.dry_run is True

    def test_parallel_default_none(self):
        parser = base_parser('test', 'desc')
        args = parser.parse_args([])
        assert args.parallel is None

    def test_parallel_flag(self):
        parser = base_parser('test', 'desc')
        args = parser.parse_args(['--parallel', '8'])
        assert args.parallel == 8

    def test_interactive_default_false(self):
        parser = base_parser('test', 'desc')
        args = parser.parse_args([])
        assert args.interactive is False

    def test_interactive_long_flag(self):
        parser = base_parser('test', 'desc')
        args = parser.parse_args(['--interactive'])
        assert args.interactive is True

    def test_interactive_short_alias(self):
        parser = base_parser('test', 'desc')
        args = parser.parse_args(['-i'])
        assert args.interactive is True

    def test_coaching_default_none(self):
        parser = base_parser('test', 'desc')
        args = parser.parse_args([])
        assert args.coaching is None

    def test_coaching_full(self):
        parser = base_parser('test', 'desc')
        args = parser.parse_args(['--coaching', 'full'])
        assert args.coaching == 'full'

    def test_coaching_coach(self):
        parser = base_parser('test', 'desc')
        args = parser.parse_args(['--coaching', 'coach'])
        assert args.coaching == 'coach'

    def test_coaching_strict(self):
        parser = base_parser('test', 'desc')
        args = parser.parse_args(['--coaching', 'strict'])
        assert args.coaching == 'strict'

    def test_coaching_invalid_exits(self):
        parser = base_parser('test', 'desc')
        with pytest.raises(SystemExit):
            parser.parse_args(['--coaching', 'invalid'])

    def test_all_flags_combined(self):
        parser = base_parser('test', 'desc')
        args = parser.parse_args([
            '--dry-run', '--parallel', '4', '-i', '--coaching', 'coach',
        ])
        assert args.dry_run is True
        assert args.parallel == 4
        assert args.interactive is True
        assert args.coaching == 'coach'


# ============================================================================
# add_scene_filter_args
# ============================================================================


class TestAddSceneFilterArgs:
    """Test add_scene_filter_args adds the expected flags."""

    def _make_parser(self):
        parser = base_parser('test', 'desc')
        add_scene_filter_args(parser)
        return parser

    def test_scenes_default_none(self):
        parser = self._make_parser()
        args = parser.parse_args([])
        assert args.scenes is None

    def test_scenes_flag(self):
        parser = self._make_parser()
        args = parser.parse_args(['--scenes', 'a,b,c'])
        assert args.scenes == 'a,b,c'

    def test_act_default_none(self):
        parser = self._make_parser()
        args = parser.parse_args([])
        assert args.act is None

    def test_act_flag(self):
        parser = self._make_parser()
        args = parser.parse_args(['--act', '2'])
        assert args.act == '2'

    def test_from_seq_default_none(self):
        parser = self._make_parser()
        args = parser.parse_args([])
        assert args.from_seq is None

    def test_from_seq_flag(self):
        parser = self._make_parser()
        args = parser.parse_args(['--from-seq', '5'])
        assert args.from_seq == '5'

    def test_from_seq_range(self):
        parser = self._make_parser()
        args = parser.parse_args(['--from-seq', '3-7'])
        assert args.from_seq == '3-7'


# ============================================================================
# resolve_filter_args
# ============================================================================


class TestResolveFilterArgs:
    """Test resolve_filter_args returns correct (mode, value, value2) tuples."""

    def _make_args(self, **kwargs):
        """Build an args namespace with optional filter attrs."""
        defaults = {'scenes': None, 'act': None, 'from_seq': None}
        defaults.update(kwargs)
        return SimpleNamespace(**defaults)

    def test_no_filter_returns_all(self):
        args = self._make_args()
        mode, value, value2 = resolve_filter_args(args)
        assert mode == 'all'
        assert value is None
        assert value2 is None

    def test_scenes_filter(self):
        args = self._make_args(scenes='scene-a,scene-b')
        mode, value, value2 = resolve_filter_args(args)
        assert mode == 'scenes'
        assert value == 'scene-a,scene-b'
        assert value2 is None

    def test_act_filter(self):
        args = self._make_args(act='2')
        mode, value, value2 = resolve_filter_args(args)
        assert mode == 'act'
        assert value == '2'
        assert value2 is None

    def test_from_seq_filter(self):
        args = self._make_args(from_seq='5')
        mode, value, value2 = resolve_filter_args(args)
        assert mode == 'from_seq'
        assert value == '5'
        assert value2 is None

    def test_scenes_takes_priority_over_act(self):
        """When multiple filters are set, --scenes wins."""
        args = self._make_args(scenes='x', act='1')
        mode, value, _ = resolve_filter_args(args)
        assert mode == 'scenes'
        assert value == 'x'

    def test_act_takes_priority_over_from_seq(self):
        """When --act and --from-seq both set, --act wins."""
        args = self._make_args(act='3', from_seq='10')
        mode, value, _ = resolve_filter_args(args)
        assert mode == 'act'
        assert value == '3'

    def test_missing_attrs_returns_all(self):
        """An args object without filter attrs defaults to 'all'."""
        args = SimpleNamespace()
        mode, value, value2 = resolve_filter_args(args)
        assert mode == 'all'
        assert value is None

    def test_empty_string_scenes_returns_all(self):
        """An empty --scenes value is treated as unset."""
        args = self._make_args(scenes='')
        mode, _, _ = resolve_filter_args(args)
        assert mode == 'all'


# ============================================================================
# apply_coaching_override
# ============================================================================


class TestApplyCoachingOverride:
    """Test apply_coaching_override sets env var correctly."""

    def test_sets_env_var(self, monkeypatch):
        # Pre-set via monkeypatch so it gets cleaned up after the test
        monkeypatch.setenv('STORYFORGE_COACHING', '')
        args = SimpleNamespace(coaching='strict')
        apply_coaching_override(args)
        assert os.environ.get('STORYFORGE_COACHING') == 'strict'

    def test_no_coaching_does_not_set_env(self, monkeypatch):
        monkeypatch.delenv('STORYFORGE_COACHING', raising=False)
        args = SimpleNamespace(coaching=None)
        apply_coaching_override(args)
        assert os.environ.get('STORYFORGE_COACHING') is None

    def test_missing_attr_does_not_set_env(self, monkeypatch):
        monkeypatch.delenv('STORYFORGE_COACHING', raising=False)
        args = SimpleNamespace()
        apply_coaching_override(args)
        assert os.environ.get('STORYFORGE_COACHING') is None
