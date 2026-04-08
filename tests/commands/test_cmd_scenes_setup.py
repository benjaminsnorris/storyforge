"""Tests for cmd_scenes_setup command module."""

import pytest
from storyforge.cmd_scenes_setup import parse_args


class TestParseArgs:
    """Argument parsing for storyforge scenes-setup."""

    def test_defaults(self):
        args = parse_args([])
        assert not args.rename
        assert not args.split_chapters
        assert not args.split_manuscript
        assert args.source == ''
        assert not args.direct
        assert not args.dry_run
        assert not args.yes
        assert args.parallel is None

    def test_rename_mode(self):
        args = parse_args(['--rename'])
        assert args.rename

    def test_split_chapters_mode(self):
        args = parse_args(['--split-chapters'])
        assert args.split_chapters

    def test_split_manuscript_mode(self):
        args = parse_args(['--split-manuscript'])
        assert args.split_manuscript

    def test_source_directory(self):
        args = parse_args(['--split-chapters', '--source', 'chapters/'])
        assert args.source == 'chapters/'

    def test_source_file(self):
        args = parse_args(['--split-manuscript', '--source', 'manuscript.md'])
        assert args.source == 'manuscript.md'

    def test_direct_flag(self):
        args = parse_args(['--direct'])
        assert args.direct

    def test_dry_run(self):
        args = parse_args(['--dry-run'])
        assert args.dry_run

    def test_yes_flag(self):
        args = parse_args(['--yes'])
        assert args.yes

    def test_parallel_workers(self):
        args = parse_args(['--parallel', '4'])
        assert args.parallel == 4

    def test_combined_flags(self):
        args = parse_args(['--split-chapters', '--source', 'ch/', '--yes', '--dry-run'])
        assert args.split_chapters
        assert args.source == 'ch/'
        assert args.yes
        assert args.dry_run


class TestModeValidation:
    """main() validates that exactly one mode is specified."""

    def test_no_mode_exits(self, monkeypatch):
        """When no mode flag given, main should exit."""
        import storyforge.cmd_scenes_setup as mod
        monkeypatch.setattr(mod, 'detect_project_root', lambda: '/tmp/fake')
        monkeypatch.setattr(mod, 'install_signal_handlers', lambda: None)
        with pytest.raises(SystemExit):
            mod.main([])

    def test_multiple_modes_exits(self, monkeypatch):
        """When multiple mode flags given, main should exit."""
        import storyforge.cmd_scenes_setup as mod
        monkeypatch.setattr(mod, 'detect_project_root', lambda: '/tmp/fake')
        monkeypatch.setattr(mod, 'install_signal_handlers', lambda: None)
        with pytest.raises(SystemExit):
            mod.main(['--rename', '--split-chapters'])
