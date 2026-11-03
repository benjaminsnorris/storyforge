"""storyforge-evals: publish (and every pandoc output) printed a manuscript's
"--" as an en dash, pandoc's markdown rule, where prose means an em dash
(Self-Control 966 times, P&P 601, Age of Innocence 857), and a long blank
("the ----shire", "Lord ----") as an em dash plus a stray hyphen. The scene
files keep the author's text; the conversion happens on the way to pandoc, and
keeps the visible text's length (Bookshelf anchors highlights by offset)."""

import os
import shutil

import pytest

from storyforge.assembly import prose_dashes, _md_to_html, assemble_chapter

needs_pandoc = pytest.mark.skipif(not shutil.which('pandoc'), reason='pandoc not installed')


def test_double_hyphen_is_an_em_dash():
    assert prose_dashes('I mean--well, no.') == 'I mean—well, no.'


def test_double_hyphen_between_digits_stays_a_range():
    assert prose_dashes('pages 10--12') == 'pages 10–12'


def test_long_run_is_a_two_em_blank():
    assert prose_dashes('the ----shire and Lord ----.') == 'the ——shire and Lord ——.'


def test_triple_hyphen_and_real_dashes_unchanged_in_meaning():
    assert prose_dashes('a---b and c—d') == 'a—b and c—d'


def test_break_lines_comments_and_markers_left_alone():
    md = 'One.\n\n---\n\n<!-- scene:a-b -->\n\n![[illus:x-y]]\n\n----\n\nTwo--three.'
    assert prose_dashes(md) == 'One.\n\n---\n\n<!-- scene:a-b -->\n\n![[illus:x-y]]\n\n----\n\nTwo—three.'


def test_table_rule_left_alone():
    md = '| a | b |\n|---|:--:|\n| x--y | 1 |'
    assert prose_dashes(md) == '| a | b |\n|---|:--:|\n| x\u2014y | 1 |'


@needs_pandoc
@pytest.mark.parametrize('n', range(4, 13))
def test_any_long_run_prints_as_many_characters_as_pandoc(n):
    import re, subprocess
    md = 'Lord ' + '-' * n + ' came.'
    pandoc = re.sub(r'<[^>]+>', '', subprocess.run(['pandoc', '-f', 'markdown', '-t', 'html'],
                    input=md, capture_output=True, text=True).stdout)
    ours = re.sub(r'<[^>]+>', '', _md_to_html(md))
    assert len(ours) == len(pandoc) and '-' not in ours and '\u2013' not in ours


def test_idempotent():
    s = 'a--b ----c 1--2'
    assert prose_dashes(prose_dashes(s)) == prose_dashes(s)


@needs_pandoc
def test_published_html_has_em_dashes_and_keeps_text_length():
    import re
    md = 'He said--no. The ----shire militia. Pages 3--4.'
    before = re.sub(r'<[^>]+>', '', __import__('subprocess').run(
        ['pandoc', '-f', 'markdown', '-t', 'html'], input=md, capture_output=True, text=True).stdout)
    after = re.sub(r'<[^>]+>', '', _md_to_html(md))
    assert '—no' in after and '——shire' in after and '3–4' in after
    assert '–no' not in after and '—-' not in after
    assert len(after) == len(before)


@needs_pandoc
def test_assembled_chapter_converts_dashes(tmp_path):
    proj = tmp_path
    (proj / 'reference').mkdir()
    (proj / 'scenes').mkdir()
    (proj / 'reference' / 'chapter-map.csv').write_text(
        'seq|title|heading|part|scenes\n1|One|titled||a;b\n')
    (proj / 'scenes' / 'a.md').write_text('First--then.\n')
    (proj / 'scenes' / 'b.md').write_text('Lord ----.\n')
    out = assemble_chapter(1, str(proj), 'blank')
    assert 'First—then.' in out and 'Lord ——.' in out
    assert '<!-- scene:a -->' in out and '\n---\n' in out
    assert (proj / 'scenes' / 'a.md').read_text() == 'First--then.\n'
