"""The PDF: WeasyPrint's drop-cap crash and the error that hid it (G-030)."""
import os
import shutil
from types import SimpleNamespace
from unittest.mock import patch

import pytest

PLUGIN_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CSS_DIR = os.path.join(PLUGIN_DIR, 'templates', 'production', 'css')

WEASY_CRASH = (b'Traceback (most recent call last):\n'
               b'  File "weasyprint/layout/float.py", line 79, in float_layout\n'
               b'    assert isinstance(box, boxes.BlockReplacedBox)\n'
               b'AssertionError\nError producing PDF.\n')


def _project(tmp_path, genre='literary fiction'):
    (tmp_path / 'storyforge.yaml').write_text(
        f'project:\n  title: Gawain\n  genre: "{genre}"\n')
    return str(tmp_path)


def _runner(*results):
    calls = []

    def run(cmd, **kw):
        calls.append(cmd)
        return results[len(calls) - 1]
    return run, calls


class TestPdfFallbackErrors:
    def test_weasyprint_error_is_logged_before_the_fallback(self, tmp_path, capsys):
        from storyforge.assembly import generate_pdf
        run, calls = _runner(SimpleNamespace(returncode=1, stderr=WEASY_CRASH),
                             SimpleNamespace(returncode=0, stderr=b''))
        with patch('subprocess.run', run):
            generate_pdf(_project(tmp_path), 'm.md', 'out.pdf', PLUGIN_DIR)
        out = capsys.readouterr().out
        assert 'WeasyPrint failed' in out and 'AssertionError' in out
        assert len(calls) == 2

    def test_both_engines_failing_names_both_causes(self, tmp_path):
        from storyforge.assembly import generate_pdf
        run, _ = _runner(
            SimpleNamespace(returncode=1, stderr=WEASY_CRASH),
            SimpleNamespace(returncode=47, stderr=b'pdflatex not found. Please select a '
                                                  b'different --pdf-engine or install pdflatex\n'))
        with patch('subprocess.run', run), pytest.raises(RuntimeError) as exc:
            generate_pdf(_project(tmp_path), 'm.md', 'out.pdf', PLUGIN_DIR)
        msg = str(exc.value)
        assert 'AssertionError' in msg and 'pdflatex not found' in msg

    def test_weasyprint_loads_the_pdf_overrides_after_the_genre_css(self, tmp_path):
        from storyforge.assembly import generate_pdf, get_pdf_css
        run, calls = _runner(SimpleNamespace(returncode=0, stderr=b''))
        with patch('subprocess.run', run):
            generate_pdf(_project(tmp_path), 'm.md', 'out.pdf', PLUGIN_DIR)
        cmd = calls[0]
        css = [cmd[i + 1] for i, a in enumerate(cmd) if a == '--css']
        assert css[-1] == get_pdf_css(PLUGIN_DIR) and os.path.isfile(css[-1])


@pytest.mark.skipif(not (shutil.which('pandoc') and shutil.which('weasyprint')),
                    reason='pandoc and weasyprint not installed')
class TestDropCapPresetsBuildAPdf:
    """WeasyPrint 68 crashed on every input under the floated drop cap."""

    @pytest.mark.parametrize('genre', ['literary fiction', 'fantasy', 'romance',
                                       'default'])
    def test_builds_with_weasyprint(self, tmp_path, capsys, genre):
        from storyforge.assembly import generate_pdf
        md = tmp_path / 'm.md'
        md.write_text('# Troy\n\nAfter the siege and the assault of Troy, the city '
                      'was burnt to brands and ashes.\n')
        out = tmp_path / 'out.pdf'
        generate_pdf(_project(tmp_path, genre), str(md), str(out), PLUGIN_DIR)
        assert out.read_bytes().startswith(b'%PDF')
        assert 'WeasyPrint failed' not in capsys.readouterr().out
