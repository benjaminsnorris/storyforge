"""Integration tests for the assembly pipeline (cmd_assemble + assembly).

Tests argument parsing, format resolution, dry-run mode, manuscript
assembly from real fixture data, and cover generation.
"""

import os
import sys

import pytest

from storyforge.cmd_assemble import parse_args, _resolve_formats, main


# ---------------------------------------------------------------------------
# Argument parsing and format resolution
# ---------------------------------------------------------------------------

class TestAssembleParseArgs:
    """Verify parse_args handles flags correctly."""

    def test_default_no_args(self):
        args = parse_args([])
        assert args.draft is False
        assert args.all_formats is False
        assert args.formats == []

    def test_draft_flag(self):
        args = parse_args(['--draft'])
        assert args.draft is True

    def test_all_flag(self):
        args = parse_args(['--all'])
        assert args.all_formats is True

    def test_format_epub(self):
        args = parse_args(['--format', 'epub'])
        assert 'epub' in args.formats

    def test_format_multiple(self):
        args = parse_args(['--format', 'epub', '--format', 'html'])
        assert 'epub' in args.formats
        assert 'html' in args.formats

    def test_dry_run(self):
        args = parse_args(['--dry-run'])
        assert args.dry_run is True

    def test_no_annotate(self):
        args = parse_args(['--no-annotate'])
        assert args.annotate is False

    def test_no_pr(self):
        args = parse_args(['--no-pr'])
        assert args.no_pr is True

    def test_skip_validation(self):
        args = parse_args(['--skip-validation'])
        assert args.skip_validation is True


class TestResolveFormats:
    """Verify _resolve_formats logic."""

    def test_draft_returns_markdown(self):
        args = parse_args(['--draft'])
        formats = _resolve_formats(args)
        assert formats == ['markdown']

    def test_all_returns_all(self):
        args = parse_args(['--all'])
        formats = _resolve_formats(args)
        assert formats == ['all']

    def test_no_format_defaults_to_markdown(self):
        args = parse_args([])
        formats = _resolve_formats(args)
        assert formats == ['markdown']

    def test_explicit_epub(self):
        args = parse_args(['--format', 'epub'])
        formats = _resolve_formats(args)
        assert formats == ['epub']

    def test_comma_separated(self):
        args = parse_args(['--format', 'epub,html'])
        formats = _resolve_formats(args)
        assert 'epub' in formats
        assert 'html' in formats

    def test_invalid_format_exits(self):
        args = parse_args(['--format', 'docx'])
        with pytest.raises(SystemExit):
            _resolve_formats(args)


# ---------------------------------------------------------------------------
# Assembly module direct tests
# ---------------------------------------------------------------------------

class TestAssemblyModule:
    """Test assembly.py functions with real fixture data."""

    def test_count_chapters(self, project_dir):
        from storyforge.assembly import count_chapters
        count = count_chapters(project_dir)
        assert count == 2

    def test_read_chapter_field(self, project_dir):
        from storyforge.assembly import read_chapter_field
        title = read_chapter_field(1, project_dir, 'title')
        assert title == 'The Finest Cartographer'

    def test_chapter_scenes(self, project_dir):
        from storyforge.assembly import get_chapter_scenes
        scenes = get_chapter_scenes(1, project_dir)
        assert 'act1-sc01' in scenes
        assert 'act1-sc02' in scenes

    def test_assemble_chapter(self, project_dir):
        from storyforge.assembly import assemble_chapter
        md = assemble_chapter(1, project_dir)
        # Should contain the chapter heading and scene content
        assert 'Chapter' in md or 'Finest Cartographer' in md
        # Should contain prose from act1-sc01.md
        assert 'Dorren' in md or 'cartograph' in md.lower()

    def test_assemble_manuscript(self, project_dir):
        from storyforge.assembly import assemble_manuscript
        output_file = os.path.join(project_dir, 'manuscript', 'manuscript.md')
        os.makedirs(os.path.dirname(output_file), exist_ok=True)
        word_count = assemble_manuscript(project_dir, output_file)
        assert word_count > 0
        assert os.path.isfile(output_file)
        with open(output_file) as f:
            content = f.read()
        assert len(content) > 100


class TestCoverGeneration:
    """Test cover generation from the assembly module."""

    def test_generate_cover_if_missing_creates_svg(self, project_dir):
        from storyforge.assembly import generate_cover_if_missing
        from storyforge.common import get_plugin_dir
        plugin_dir = get_plugin_dir()

        generate_cover_if_missing(project_dir, plugin_dir)

        production_dir = os.path.join(project_dir, 'production')
        svg_path = os.path.join(production_dir, 'cover.svg')
        assert os.path.isfile(svg_path)
        with open(svg_path) as f:
            content = f.read()
        assert '<svg' in content

    def test_generate_cover_if_missing_skips_existing(self, project_dir):
        from storyforge.assembly import generate_cover_if_missing
        from storyforge.common import get_plugin_dir
        plugin_dir = get_plugin_dir()

        # Create an existing cover
        production_dir = os.path.join(project_dir, 'production')
        os.makedirs(production_dir, exist_ok=True)
        cover_path = os.path.join(production_dir, 'cover.png')
        with open(cover_path, 'w') as f:
            f.write('fake png data')

        generate_cover_if_missing(project_dir, plugin_dir)

        # Should NOT have created an SVG
        svg_path = os.path.join(production_dir, 'cover.svg')
        assert not os.path.isfile(svg_path)

    def test_cover_contains_title(self, project_dir):
        from storyforge.assembly import generate_cover_if_missing
        from storyforge.common import get_plugin_dir
        plugin_dir = get_plugin_dir()

        generate_cover_if_missing(project_dir, plugin_dir)

        svg_path = os.path.join(project_dir, 'production', 'cover.svg')
        with open(svg_path) as f:
            content = f.read()
        assert 'Cartographer' in content


# ---------------------------------------------------------------------------
# cmd_assemble dry-run
# ---------------------------------------------------------------------------

class TestAssembleDryRun:
    """Dry-run should describe what would happen without modifying files."""

    def test_dry_run_draft(self, project_dir, mock_api, mock_git, monkeypatch, capsys):
        monkeypatch.chdir(project_dir)

        main(['--draft', '--dry-run'])

        out = capsys.readouterr().out
        assert 'DRY RUN' in out
        assert 'Chapter' in out

    def test_dry_run_shows_chapters(self, project_dir, mock_api, mock_git, monkeypatch, capsys):
        monkeypatch.chdir(project_dir)

        main(['--draft', '--dry-run'])

        out = capsys.readouterr().out
        assert 'Finest Cartographer' in out

    def test_dry_run_no_files_created(self, project_dir, mock_api, mock_git, monkeypatch, capsys):
        monkeypatch.chdir(project_dir)

        main(['--draft', '--dry-run'])

        manuscript_dir = os.path.join(project_dir, 'manuscript')
        # manuscript directory should not be created in dry-run
        assert not os.path.isdir(os.path.join(manuscript_dir, 'chapters'))
