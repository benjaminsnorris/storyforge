"""Tests for cli infrastructure module."""

import argparse
import os
import pytest
from storyforge.cli import (
    base_parser, add_scene_filter_args, resolve_filter_args,
    apply_coaching_override,
)


class TestBaseParser:
    """base_parser creates parser with common flags."""

    def test_prog_name(self):
        parser = base_parser('test', 'A test command')
        assert 'storyforge test' in parser.prog

    def test_description(self):
        parser = base_parser('test', 'A test command')
        assert parser.description == 'A test command'

    def test_dry_run_flag(self):
        parser = base_parser('test', 'A test')
        args = parser.parse_args(['--dry-run'])
        assert args.dry_run

    def test_dry_run_default(self):
        parser = base_parser('test', 'A test')
        args = parser.parse_args([])
        assert not args.dry_run

    def test_parallel_flag(self):
        parser = base_parser('test', 'A test')
        args = parser.parse_args(['--parallel', '8'])
        assert args.parallel == 8

    def test_parallel_default_none(self):
        parser = base_parser('test', 'A test')
        args = parser.parse_args([])
        assert args.parallel is None

    def test_interactive_flag(self):
        parser = base_parser('test', 'A test')
        args = parser.parse_args(['--interactive'])
        assert args.interactive

    def test_interactive_short(self):
        parser = base_parser('test', 'A test')
        args = parser.parse_args(['-i'])
        assert args.interactive

    def test_interactive_default(self):
        parser = base_parser('test', 'A test')
        args = parser.parse_args([])
        assert not args.interactive

    def test_coaching_choices(self):
        parser = base_parser('test', 'A test')
        for level in ('full', 'coach', 'strict'):
            args = parser.parse_args(['--coaching', level])
            assert args.coaching == level

    def test_coaching_default_none(self):
        parser = base_parser('test', 'A test')
        args = parser.parse_args([])
        assert args.coaching is None

    def test_coaching_invalid(self):
        parser = base_parser('test', 'A test')
        with pytest.raises(SystemExit):
            parser.parse_args(['--coaching', 'invalid'])

    def test_all_flags_combined(self):
        parser = base_parser('test', 'A test')
        args = parser.parse_args([
            '--dry-run', '--parallel', '4', '-i', '--coaching', 'strict',
        ])
        assert args.dry_run
        assert args.parallel == 4
        assert args.interactive
        assert args.coaching == 'strict'


class TestAddSceneFilterArgs:
    """add_scene_filter_args adds --scenes, --act, --from-seq."""

    def test_scenes_flag(self):
        parser = argparse.ArgumentParser()
        add_scene_filter_args(parser)
        args = parser.parse_args(['--scenes', 'a,b,c'])
        assert args.scenes == 'a,b,c'

    def test_act_flag(self):
        parser = argparse.ArgumentParser()
        add_scene_filter_args(parser)
        args = parser.parse_args(['--act', '2'])
        assert args.act == '2'

    def test_from_seq_flag(self):
        parser = argparse.ArgumentParser()
        add_scene_filter_args(parser)
        args = parser.parse_args(['--from-seq', '5-10'])
        assert args.from_seq == '5-10'

    def test_defaults_all_none(self):
        parser = argparse.ArgumentParser()
        add_scene_filter_args(parser)
        args = parser.parse_args([])
        assert args.scenes is None
        assert args.act is None
        assert args.from_seq is None


class TestResolveFilterArgs:
    """resolve_filter_args extracts (mode, value, value2) from parsed args."""

    def _make_args(self, **kwargs):
        ns = argparse.Namespace(scenes=None, act=None, from_seq=None)
        for k, v in kwargs.items():
            setattr(ns, k, v)
        return ns

    def test_no_filter_returns_all(self):
        args = self._make_args()
        mode, val, val2 = resolve_filter_args(args)
        assert mode == 'all'
        assert val is None
        assert val2 is None

    def test_scenes_filter(self):
        args = self._make_args(scenes='a,b')
        mode, val, val2 = resolve_filter_args(args)
        assert mode == 'scenes'
        assert val == 'a,b'

    def test_act_filter(self):
        args = self._make_args(act='2')
        mode, val, val2 = resolve_filter_args(args)
        assert mode == 'act'
        assert val == '2'

    def test_from_seq_filter(self):
        args = self._make_args(from_seq='5')
        mode, val, val2 = resolve_filter_args(args)
        assert mode == 'from_seq'
        assert val == '5'

    def test_scenes_takes_priority(self):
        """When multiple filters set, scenes wins (first check)."""
        args = self._make_args(scenes='x', act='2')
        mode, val, _ = resolve_filter_args(args)
        assert mode == 'scenes'

    def test_act_before_from_seq(self):
        args = self._make_args(act='1', from_seq='3')
        mode, val, _ = resolve_filter_args(args)
        assert mode == 'act'


class TestApplyCoachingOverride:
    """apply_coaching_override sets env var when --coaching given."""

    def test_sets_env_var(self, monkeypatch):
        monkeypatch.delenv('STORYFORGE_COACHING', raising=False)
        args = argparse.Namespace(coaching='strict')
        apply_coaching_override(args)
        assert os.environ.get('STORYFORGE_COACHING') == 'strict'
        monkeypatch.delenv('STORYFORGE_COACHING', raising=False)

    def test_no_coaching_no_change(self, monkeypatch):
        monkeypatch.delenv('STORYFORGE_COACHING', raising=False)
        args = argparse.Namespace(coaching=None)
        apply_coaching_override(args)
        assert os.environ.get('STORYFORGE_COACHING') is None

    def test_missing_attr_no_crash(self):
        args = argparse.Namespace()
        apply_coaching_override(args)  # should not raise
