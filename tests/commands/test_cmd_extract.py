"""Tests for cmd_extract command module."""

import pytest
from storyforge.cmd_extract import parse_args


class TestParseArgs:
    """Argument parsing for storyforge extract."""

    def test_defaults(self):
        args = parse_args([])
        assert args.phase is None
        assert not args.cleanup
        assert not args.cleanup_only
        assert not args.force
        assert not args.expand
        assert not args.dry_run

    def test_phase_0(self):
        args = parse_args(['--phase', '0'])
        assert args.phase == 0

    def test_phase_1(self):
        args = parse_args(['--phase', '1'])
        assert args.phase == 1

    def test_phase_2(self):
        args = parse_args(['--phase', '2'])
        assert args.phase == 2

    def test_phase_3(self):
        args = parse_args(['--phase', '3'])
        assert args.phase == 3

    def test_cleanup_flag(self):
        args = parse_args(['--cleanup'])
        assert args.cleanup

    def test_cleanup_only_flag(self):
        args = parse_args(['--cleanup-only'])
        assert args.cleanup_only

    def test_force_flag(self):
        args = parse_args(['--force'])
        assert args.force

    def test_expand_flag(self):
        args = parse_args(['--expand'])
        assert args.expand

    def test_dry_run_flag(self):
        args = parse_args(['--dry-run'])
        assert args.dry_run

    def test_combined_flags(self):
        args = parse_args(['--phase', '1', '--force', '--dry-run'])
        assert args.phase == 1
        assert args.force
        assert args.dry_run

    def test_cleanup_and_expand(self):
        args = parse_args(['--cleanup', '--expand'])
        assert args.cleanup
        assert args.expand

    def test_phase_is_int(self):
        args = parse_args(['--phase', '2'])
        assert isinstance(args.phase, int)

    def test_phase_invalid_string(self):
        with pytest.raises(SystemExit):
            parse_args(['--phase', 'skeleton'])
