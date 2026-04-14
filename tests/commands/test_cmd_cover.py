"""Tests for storyforge.cmd_cover — typographic book cover generation.

Covers: parse_args (all flags), dry-run mode, SVG generation, PNG conversion,
output path resolution, genre pattern selection, subprocess mocking, and
error handling.
"""

import os
import subprocess
import sys

import pytest

from storyforge.cmd_cover import parse_args, main


# ============================================================================
# Helpers
# ============================================================================

def _mock_cover_metadata(monkeypatch, **overrides):
    """Patch _read_project_metadata to return controlled metadata."""
    meta = {
        'title': 'The Cartographer\'s Silence',
        'author': 'Test Author',
        'genre': 'fantasy',
        'subtitle': '',
        'palette': '',
        'series_name': '',
        'series_position': '',
    }
    meta.update(overrides)
    monkeypatch.setattr(
        'storyforge.cmd_cover._read_project_metadata',
        lambda pd: meta,
    )
    return meta


# ============================================================================
# parse_args
# ============================================================================

class TestParseArgs:
    """Tests for parse_args."""

    def test_defaults(self):
        args = parse_args([])
        assert not args.dry_run
        assert not args.svg_only
        assert args.output == ''

    def test_dry_run(self):
        args = parse_args(['--dry-run'])
        assert args.dry_run

    def test_svg_only(self):
        args = parse_args(['--svg-only'])
        assert args.svg_only

    def test_output_path(self):
        args = parse_args(['--output', '/tmp/my-cover.png'])
        assert args.output == '/tmp/my-cover.png'

    def test_combined_flags(self):
        args = parse_args(['--dry-run', '--svg-only'])
        assert args.dry_run
        assert args.svg_only

    def test_output_with_dry_run(self):
        args = parse_args(['--output', 'cover.png', '--dry-run'])
        assert args.output == 'cover.png'
        assert args.dry_run


# ============================================================================
# main — dry run
# ============================================================================

class TestMainDryRun:
    """Tests for main() in dry-run mode."""

    def test_dry_run_no_files_written(self, project_dir, monkeypatch):
        monkeypatch.setattr('storyforge.cmd_cover.detect_project_root', lambda: project_dir)
        _mock_cover_metadata(monkeypatch)
        assets_dir = os.path.join(project_dir, 'manuscript', 'assets')
        svg_file = os.path.join(assets_dir, 'cover.svg')
        with pytest.raises(SystemExit) as exc_info:
            main(['--dry-run'])
        assert exc_info.value.code == 0
        assert not os.path.isfile(svg_file)

    def test_dry_run_prints_config(self, project_dir, monkeypatch, capsys):
        monkeypatch.setattr('storyforge.cmd_cover.detect_project_root', lambda: project_dir)
        _mock_cover_metadata(monkeypatch)
        with pytest.raises(SystemExit) as exc_info:
            main(['--dry-run'])
        assert exc_info.value.code == 0
        output = capsys.readouterr().out
        assert 'dry run' in output.lower()
        assert 'Cartographer' in output

    def test_dry_run_shows_svg_only_without_png(self, project_dir, monkeypatch, capsys):
        monkeypatch.setattr('storyforge.cmd_cover.detect_project_root', lambda: project_dir)
        _mock_cover_metadata(monkeypatch)
        with pytest.raises(SystemExit) as exc_info:
            main(['--dry-run', '--svg-only'])
        assert exc_info.value.code == 0
        output = capsys.readouterr().out
        assert 'SVG' in output
        assert 'PNG' not in output

    def test_dry_run_with_series(self, project_dir, monkeypatch, capsys):
        monkeypatch.setattr('storyforge.cmd_cover.detect_project_root', lambda: project_dir)
        _mock_cover_metadata(monkeypatch, series_name='The Atlas Chronicles', series_position='2')
        with pytest.raises(SystemExit) as exc_info:
            main(['--dry-run'])
        assert exc_info.value.code == 0
        output = capsys.readouterr().out
        assert 'Atlas Chronicles' in output


# ============================================================================
# main — SVG generation
# ============================================================================

class TestMainSvgGeneration:
    """Tests for SVG cover generation."""

    def test_generates_svg_file(self, project_dir, monkeypatch):
        monkeypatch.setattr('storyforge.cmd_cover.detect_project_root', lambda: project_dir)
        _mock_cover_metadata(monkeypatch)
        # Mock shutil.which to prevent PNG conversion
        monkeypatch.setattr('storyforge.cmd_cover.shutil.which', lambda cmd: None)
        with pytest.raises(SystemExit) as exc_info:
            main(['--svg-only'])
        assert exc_info.value.code == 0
        svg_file = os.path.join(project_dir, 'manuscript', 'assets', 'cover.svg')
        assert os.path.isfile(svg_file)
        with open(svg_file) as f:
            content = f.read()
        assert '<svg' in content
        assert 'Cartographer' in content

    def test_svg_contains_author(self, project_dir, monkeypatch):
        monkeypatch.setattr('storyforge.cmd_cover.detect_project_root', lambda: project_dir)
        _mock_cover_metadata(monkeypatch)
        monkeypatch.setattr('storyforge.cmd_cover.shutil.which', lambda cmd: None)
        with pytest.raises(SystemExit) as exc_info:
            main(['--svg-only'])
        assert exc_info.value.code == 0
        svg_file = os.path.join(project_dir, 'manuscript', 'assets', 'cover.svg')
        with open(svg_file) as f:
            content = f.read()
        assert 'Test Author' in content

    def test_svg_contains_gradient(self, project_dir, monkeypatch):
        monkeypatch.setattr('storyforge.cmd_cover.detect_project_root', lambda: project_dir)
        _mock_cover_metadata(monkeypatch)
        monkeypatch.setattr('storyforge.cmd_cover.shutil.which', lambda cmd: None)
        with pytest.raises(SystemExit) as exc_info:
            main(['--svg-only'])
        assert exc_info.value.code == 0
        svg_file = os.path.join(project_dir, 'manuscript', 'assets', 'cover.svg')
        with open(svg_file) as f:
            content = f.read()
        assert 'linearGradient' in content

    def test_svg_with_subtitle(self, project_dir, monkeypatch):
        monkeypatch.setattr('storyforge.cmd_cover.detect_project_root', lambda: project_dir)
        _mock_cover_metadata(monkeypatch, subtitle='A Novel of Forgotten Maps')
        monkeypatch.setattr('storyforge.cmd_cover.shutil.which', lambda cmd: None)
        with pytest.raises(SystemExit) as exc_info:
            main(['--svg-only'])
        assert exc_info.value.code == 0
        svg_file = os.path.join(project_dir, 'manuscript', 'assets', 'cover.svg')
        with open(svg_file) as f:
            content = f.read()
        assert 'Forgotten Maps' in content

    def test_svg_with_series_badge(self, project_dir, monkeypatch):
        monkeypatch.setattr('storyforge.cmd_cover.detect_project_root', lambda: project_dir)
        _mock_cover_metadata(monkeypatch, series_name='The Atlas Chronicles', series_position='1')
        monkeypatch.setattr('storyforge.cmd_cover.shutil.which', lambda cmd: None)
        with pytest.raises(SystemExit) as exc_info:
            main(['--svg-only'])
        assert exc_info.value.code == 0
        svg_file = os.path.join(project_dir, 'manuscript', 'assets', 'cover.svg')
        with open(svg_file) as f:
            content = f.read()
        assert 'Atlas Chronicles' in content
        assert 'Book 1' in content


# ============================================================================
# main — genre pattern selection
# ============================================================================

class TestMainGenrePatterns:
    """Tests for genre-specific pattern generation."""

    @pytest.mark.parametrize('genre', [
        'fantasy', 'science-fiction', 'thriller', 'romance', 'literary-fiction',
    ])
    def test_genre_produces_valid_svg(self, genre, project_dir, monkeypatch):
        monkeypatch.setattr('storyforge.cmd_cover.detect_project_root', lambda: project_dir)
        _mock_cover_metadata(monkeypatch, genre=genre)
        monkeypatch.setattr('storyforge.cmd_cover.shutil.which', lambda cmd: None)
        with pytest.raises(SystemExit) as exc_info:
            main(['--svg-only'])
        assert exc_info.value.code == 0
        svg_file = os.path.join(project_dir, 'manuscript', 'assets', 'cover.svg')
        assert os.path.isfile(svg_file)
        with open(svg_file) as f:
            content = f.read()
        assert '<svg' in content
        assert '</svg>' in content

    def test_unknown_genre_uses_default_pattern(self, project_dir, monkeypatch):
        monkeypatch.setattr('storyforge.cmd_cover.detect_project_root', lambda: project_dir)
        _mock_cover_metadata(monkeypatch, genre='experimental-nonfiction')
        monkeypatch.setattr('storyforge.cmd_cover.shutil.which', lambda cmd: None)
        with pytest.raises(SystemExit) as exc_info:
            main(['--svg-only'])
        assert exc_info.value.code == 0
        svg_file = os.path.join(project_dir, 'manuscript', 'assets', 'cover.svg')
        assert os.path.isfile(svg_file)


# ============================================================================
# main — PNG conversion
# ============================================================================

class TestMainPngConversion:
    """Tests for PNG conversion via external tools."""

    def test_rsvg_convert_called_when_available(self, project_dir, monkeypatch):
        monkeypatch.setattr('storyforge.cmd_cover.detect_project_root', lambda: project_dir)
        _mock_cover_metadata(monkeypatch)
        monkeypatch.setattr('storyforge.cmd_cover.shutil.which',
                            lambda cmd: '/usr/bin/rsvg-convert' if cmd == 'rsvg-convert' else None)
        cmds_run = []
        def mock_subprocess_run(cmd, check=False, capture_output=False):
            cmds_run.append(cmd)
            # Create a fake PNG file
            for arg in cmd:
                if arg.endswith('.png'):
                    with open(arg, 'wb') as f:
                        f.write(b'fake png')
            return subprocess.CompletedProcess(cmd, 0)
        monkeypatch.setattr('storyforge.cmd_cover.subprocess.run', mock_subprocess_run)
        main([])
        assert len(cmds_run) == 1
        assert 'rsvg-convert' in cmds_run[0]

    def test_sips_fallback_when_rsvg_missing(self, project_dir, monkeypatch):
        monkeypatch.setattr('storyforge.cmd_cover.detect_project_root', lambda: project_dir)
        _mock_cover_metadata(monkeypatch)
        monkeypatch.setattr('storyforge.cmd_cover.shutil.which',
                            lambda cmd: '/usr/bin/sips' if cmd == 'sips' else None)
        cmds_run = []
        def mock_subprocess_run(cmd, check=False, capture_output=False):
            cmds_run.append(cmd)
            for arg in cmd:
                if arg.endswith('.png'):
                    with open(arg, 'wb') as f:
                        f.write(b'fake png')
            return subprocess.CompletedProcess(cmd, 0)
        monkeypatch.setattr('storyforge.cmd_cover.subprocess.run', mock_subprocess_run)
        main([])
        assert len(cmds_run) == 1
        assert 'sips' in cmds_run[0]

    def test_no_converter_logs_warning(self, project_dir, monkeypatch, capsys):
        monkeypatch.setattr('storyforge.cmd_cover.detect_project_root', lambda: project_dir)
        _mock_cover_metadata(monkeypatch)
        monkeypatch.setattr('storyforge.cmd_cover.shutil.which', lambda cmd: None)
        main([])
        output = capsys.readouterr().out
        assert 'WARNING' in output or 'not available' in output.lower()
        # SVG should still be written even without PNG conversion
        svg_file = os.path.join(project_dir, 'manuscript', 'assets', 'cover.svg')
        assert os.path.isfile(svg_file)


# ============================================================================
# main — custom output path
# ============================================================================

class TestMainOutputPath:
    """Tests for custom --output path handling."""

    def test_custom_absolute_output(self, project_dir, monkeypatch, tmp_path):
        monkeypatch.setattr('storyforge.cmd_cover.detect_project_root', lambda: project_dir)
        _mock_cover_metadata(monkeypatch)
        monkeypatch.setattr('storyforge.cmd_cover.shutil.which', lambda cmd: None)
        output_path = str(tmp_path / 'custom' / 'my-cover.png')
        # --svg-only causes sys.exit(0) after writing the SVG
        with pytest.raises(SystemExit) as exc_info:
            main(['--svg-only', '--output', output_path])
        assert exc_info.value.code == 0
        # svg_only + output: should write SVG at the output path base
        svg_path = os.path.splitext(output_path)[0] + '.svg'
        assert os.path.isfile(svg_path)

    def test_custom_relative_output(self, project_dir, monkeypatch):
        monkeypatch.setattr('storyforge.cmd_cover.detect_project_root', lambda: project_dir)
        _mock_cover_metadata(monkeypatch)
        monkeypatch.setattr('storyforge.cmd_cover.shutil.which', lambda cmd: None)
        with pytest.raises(SystemExit) as exc_info:
            main(['--svg-only', '--output', 'my-cover.png'])
        assert exc_info.value.code == 0
        svg_path = os.path.join(project_dir, 'my-cover.svg')
        assert os.path.isfile(svg_path)


# ============================================================================
# main — XML escaping
# ============================================================================

class TestMainXmlSafety:
    """Tests that special characters in metadata are handled safely."""

    def test_ampersand_in_title_escaped(self, project_dir, monkeypatch):
        monkeypatch.setattr('storyforge.cmd_cover.detect_project_root', lambda: project_dir)
        _mock_cover_metadata(monkeypatch, title='War & Peace')
        monkeypatch.setattr('storyforge.cmd_cover.shutil.which', lambda cmd: None)
        with pytest.raises(SystemExit) as exc_info:
            main(['--svg-only'])
        assert exc_info.value.code == 0
        svg_file = os.path.join(project_dir, 'manuscript', 'assets', 'cover.svg')
        with open(svg_file) as f:
            content = f.read()
        # The raw & should be escaped to &amp;
        assert '&amp;' in content
        # Should not have unescaped & in text content (outside of &amp;)
        # This is a basic check — the SVG should be well-formed
        assert 'War &amp; Peace' in content

    def test_angle_brackets_in_author_escaped(self, project_dir, monkeypatch):
        monkeypatch.setattr('storyforge.cmd_cover.detect_project_root', lambda: project_dir)
        _mock_cover_metadata(monkeypatch, author='Author <Pseudonym>')
        monkeypatch.setattr('storyforge.cmd_cover.shutil.which', lambda cmd: None)
        with pytest.raises(SystemExit) as exc_info:
            main(['--svg-only'])
        assert exc_info.value.code == 0
        svg_file = os.path.join(project_dir, 'manuscript', 'assets', 'cover.svg')
        with open(svg_file) as f:
            content = f.read()
        assert '&lt;Pseudonym&gt;' in content
