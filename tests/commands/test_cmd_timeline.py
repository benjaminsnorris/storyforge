"""Tests for cmd_timeline command module."""

import pytest
from storyforge.cmd_timeline import parse_args


class TestParseArgs:
    """Argument parsing for storyforge timeline."""

    def test_defaults(self):
        args = parse_args([])
        assert args.scenes is None
        assert args.act is None
        assert args.from_seq is None
        assert not args.interactive
        assert not args.direct
        assert args.parallel is None
        assert not args.force
        assert not args.dry_run
        assert not args.skip_phase1
        assert not args.phase1_only
        assert not args.embedded

    def test_scene_filter(self):
        args = parse_args(['--scenes', 'scene-1,scene-2'])
        assert args.scenes == 'scene-1,scene-2'

    def test_act_filter(self):
        args = parse_args(['--act', '2'])
        assert args.act == '2'

    def test_from_seq_filter(self):
        args = parse_args(['--from-seq', '5-10'])
        assert args.from_seq == '5-10'

    def test_interactive_flag(self):
        args = parse_args(['--interactive'])
        assert args.interactive

    def test_interactive_short(self):
        args = parse_args(['-i'])
        assert args.interactive

    def test_direct_flag(self):
        args = parse_args(['--direct'])
        assert args.direct

    def test_parallel_workers(self):
        args = parse_args(['--parallel', '8'])
        assert args.parallel == 8

    def test_force_flag(self):
        args = parse_args(['--force'])
        assert args.force

    def test_dry_run(self):
        args = parse_args(['--dry-run'])
        assert args.dry_run

    def test_skip_phase1(self):
        args = parse_args(['--skip-phase1'])
        assert args.skip_phase1

    def test_phase1_only(self):
        args = parse_args(['--phase1-only'])
        assert args.phase1_only

    def test_embedded(self):
        args = parse_args(['--embedded'])
        assert args.embedded

    def test_combined_flags(self):
        args = parse_args(['--force', '--direct', '--parallel', '4', '--act', '1'])
        assert args.force
        assert args.direct
        assert args.parallel == 4
        assert args.act == '1'

    def test_embedded_with_skip_phase1(self):
        args = parse_args(['--embedded', '--skip-phase1'])
        assert args.embedded
        assert args.skip_phase1
