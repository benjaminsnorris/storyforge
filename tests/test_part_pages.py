"""Part pages in the epub, HTML and PDF, matching the web book and manifest (G-031)."""
import os
import shutil
from unittest.mock import patch

import pytest

from test_publish_parts_and_record import _project

PLUGIN_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def _manuscript(proj):
    from storyforge.assembly import assemble_manuscript
    out = os.path.join(proj, 'manuscript', 'manuscript.md')
    assemble_manuscript(proj, out)
    with open(out) as f:
        return f.read()


def _h1s(text):
    return [line for line in text.split('\n') if line.startswith('# ')]


class TestManuscriptPartPages:
    def test_each_titled_part_opens_with_its_own_heading(self, tmp_path):
        proj = _project(tmp_path, ['', '1', '1', '2'],
                        ['Book I: Miss Brooke', 'Book II: Old and Young'])
        chapters = [h for h in _h1s(_manuscript(proj))
                    if h.startswith('# Chapter') or 'part-title' in h]
        assert chapters == [
            '# Chapter 1',
            '# Book I: Miss Brooke {#part-1 .part-title epub:type=part}',
            '# Chapter 2',
            '# Chapter 3',
            '# Book II: Old and Young {#part-2 .part-title epub:type=part}',
            '# Chapter 4',
        ]

    def test_a_part_number_without_a_title_prints_no_part_page(self, tmp_path):
        """Homer: each book its own chapter, a part number but no parts: titles."""
        text = _manuscript(_project(tmp_path, ['1', '2']))
        assert 'part-title' not in text

    def test_no_parts_no_part_pages(self, tmp_path):
        assert 'part-title' not in _manuscript(_project(tmp_path, ['', '']))


class TestFormatsLoadThePartStylesheet:
    @pytest.mark.parametrize('fn', ['generate_epub', 'generate_html', 'generate_pdf'])
    def test_parts_css_follows_the_genre_css(self, tmp_path, fn):
        from storyforge import assembly
        proj = _project(tmp_path, ['1'], ['Part One'])
        with patch('subprocess.run') as run:
            run.return_value.returncode = 0
            getattr(assembly, fn)(proj, 'm.md', 'out', PLUGIN_DIR)
        cmd = run.call_args_list[0].args[0]
        css = [cmd[i + 1] for i, a in enumerate(cmd) if a == '--css']
        # Right after the genre CSS (the PDF loads its overrides last)
        assert css[1] == assembly.get_parts_css(PLUGIN_DIR)
        assert os.path.isfile(css[1])


@pytest.mark.skipif(not shutil.which('pandoc'), reason='pandoc not installed')
class TestWebBookPartPages:
    def test_part_page_carries_the_parts_own_number_and_title(self, tmp_path):
        """A book whose first chapter is in part 2 once printed part 1's title."""
        from storyforge.assembly import generate_web_book
        proj = _project(tmp_path, ['2', '2', '3'], ['Front', 'Middle', 'End'])
        web = generate_web_book(proj, PLUGIN_DIR)
        pages = sorted(os.listdir(os.path.join(web, 'chapters')))
        assert [p for p in pages if p.startswith('part-')] == ['part-2.html', 'part-3.html']
        with open(os.path.join(web, 'chapters', 'part-2.html')) as f:
            assert '<h1 class="part-title">Middle</h1>' in f.read()

    def test_a_part_number_without_a_title_makes_no_part_page(self, tmp_path):
        from storyforge.assembly import generate_web_book
        web = generate_web_book(_project(tmp_path, ['1', '2']), PLUGIN_DIR)
        assert not any(p.startswith('part-')
                       for p in os.listdir(os.path.join(web, 'chapters')))
