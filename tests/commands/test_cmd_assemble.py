"""Command-level tests for storyforge.cmd_assemble module.

Tests parse_args, _resolve_formats, VALID_FORMATS, _word_count,
_read_production_field, and _check_pandoc.
"""

import os

import pytest

from storyforge.cmd_assemble import (
    parse_args,
    _resolve_formats,
    VALID_FORMATS,
    _word_count,
    _read_production_field,
    _check_pandoc,
)


# ============================================================================
# parse_args
# ============================================================================

class TestParseArgs:
    def test_default_args(self):
        args = parse_args([])
        assert args.formats == []
        assert args.all_formats is False
        assert args.draft is False
        assert args.annotate is True
        assert args.interactive is False
        assert args.dry_run is False
        assert args.skip_validation is False
        assert args.no_pr is False

    def test_format_epub(self):
        args = parse_args(['--format', 'epub'])
        assert args.formats == ['epub']

    def test_format_multiple(self):
        args = parse_args(['--format', 'epub', '--format', 'pdf'])
        assert args.formats == ['epub', 'pdf']

    def test_all_formats(self):
        args = parse_args(['--all'])
        assert args.all_formats is True

    def test_draft(self):
        args = parse_args(['--draft'])
        assert args.draft is True

    def test_no_annotate(self):
        args = parse_args(['--no-annotate'])
        assert args.annotate is False

    def test_interactive(self):
        args = parse_args(['-i'])
        assert args.interactive is True

    def test_dry_run(self):
        args = parse_args(['--dry-run'])
        assert args.dry_run is True

    def test_skip_validation(self):
        args = parse_args(['--skip-validation'])
        assert args.skip_validation is True

    def test_no_pr(self):
        args = parse_args(['--no-pr'])
        assert args.no_pr is True


# ============================================================================
# _resolve_formats
# ============================================================================

class TestResolveFormats:
    def test_default_is_markdown(self):
        args = parse_args([])
        formats = _resolve_formats(args)
        assert formats == ['markdown']

    def test_draft_is_markdown(self):
        args = parse_args(['--draft'])
        formats = _resolve_formats(args)
        assert formats == ['markdown']

    def test_all_formats_flag(self):
        args = parse_args(['--all'])
        formats = _resolve_formats(args)
        assert formats == ['all']

    def test_explicit_epub(self):
        args = parse_args(['--format', 'epub'])
        formats = _resolve_formats(args)
        assert formats == ['epub']

    def test_comma_separated(self):
        args = parse_args(['--format', 'epub,html'])
        formats = _resolve_formats(args)
        assert 'epub' in formats
        assert 'html' in formats

    def test_unknown_format_exits(self):
        args = parse_args(['--format', 'docx'])
        with pytest.raises(SystemExit):
            _resolve_formats(args)


# ============================================================================
# VALID_FORMATS
# ============================================================================

class TestValidFormats:
    def test_has_expected_formats(self):
        assert 'epub' in VALID_FORMATS
        assert 'pdf' in VALID_FORMATS
        assert 'html' in VALID_FORMATS
        assert 'web' in VALID_FORMATS
        assert 'markdown' in VALID_FORMATS
        assert 'all' in VALID_FORMATS

    def test_is_a_set(self):
        assert isinstance(VALID_FORMATS, set)


# ============================================================================
# _word_count
# ============================================================================

class TestWordCount:
    def test_counts_words(self, tmp_path):
        f = tmp_path / 'scene.md'
        f.write_text('one two three four five')
        assert _word_count(str(f)) == 5

    def test_multiline(self, tmp_path):
        f = tmp_path / 'scene.md'
        f.write_text('one two\nthree four\nfive six seven')
        assert _word_count(str(f)) == 7

    def test_empty_file(self, tmp_path):
        f = tmp_path / 'empty.md'
        f.write_text('')
        assert _word_count(str(f)) == 0


# ============================================================================
# _read_production_field
# ============================================================================

class TestReadProductionField:
    def test_reads_author(self, project_dir):
        result = _read_production_field(project_dir, 'author')
        assert result == 'Test Author'

    def test_reads_scene_break(self, project_dir):
        result = _read_production_field(project_dir, 'scene_break')
        assert result == 'ornamental'

    def test_reads_genre_preset(self, project_dir):
        result = _read_production_field(project_dir, 'genre_preset')
        assert result == 'fantasy'

    def test_missing_field_returns_empty(self, project_dir):
        result = _read_production_field(project_dir, 'nonexistent')
        assert result == ''


# ============================================================================
# _check_pandoc
# ============================================================================

class TestCheckPandoc:
    def test_returns_string(self):
        """Result is a string (version or empty)."""
        result = _check_pandoc()
        assert isinstance(result, str)

    def test_missing_pandoc(self, monkeypatch):
        """When pandoc doesn't exist, returns empty string."""
        import subprocess
        original_run = subprocess.run

        def fake_run(cmd, **kwargs):
            if cmd[0] == 'pandoc':
                raise FileNotFoundError
            return original_run(cmd, **kwargs)

        monkeypatch.setattr('subprocess.run', fake_run)
        result = _check_pandoc()
        assert result == ''
