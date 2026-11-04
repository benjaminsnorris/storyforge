"""Tests for storyforge.gutenberg: a Project Gutenberg text as a manuscript."""

import json
import os

import pytest

from storyforge import gutenberg as g

HEADER = ('The Project Gutenberg eBook of A Test\n\nTitle: A Test\n\n'
          '*** START OF THE PROJECT GUTENBERG EBOOK A TEST ***\n\n')
FOOTER = '\n*** END OF THE PROJECT GUTENBERG EBOOK A TEST ***\n\nLicence text.\n'


def raw(body: str, crlf: bool = False) -> str:
    text = HEADER + body + FOOTER
    return text.replace('\n', '\r\n') if crlf else text


PROSE = """CONTENTS

I
II


I


It was a dark
and stormy night.

The rain fell
in torrents.{1a}


II


Morning came.

Footnotes:

{1a} A note.
"""

VERSE = """PRELUDE OF THE KING


LO, praise of the prowess of people-kings
of spear-armed Danes, in days long sped,{0a}
we have heard!

Oft Scyld the Scefing
from squadroned foes


I


[To the door of the hall
Wulfgar went] and the word declared:  --
owned by thee!_

Footnotes:

{0a} A note.
"""

PROSE_META = {'chapter_heading': r'^([IVX]+)$', 'note_marker': r'\{\d+[a-z]\}',
              'skip_from': ['^Footnotes:$']}
VERSE_META = {'chapter_heading': r'^([IVX]+)$', 'heading': 'Fitt {}',
              'other_headings': {'^PRELUDE OF THE KING$': 'Prelude'},
              'note_marker': r' ?\{\d+[a-z]\}', 'skip_from': ['^Footnotes:$'],
              'verse': True}


class TestProse:
    def test_paragraphs_join_and_boilerplate_goes(self):
        out = g.normalize(raw(PROSE, crlf=True), PROSE_META)
        assert out == ('# Chapter I\n\nIt was a dark and stormy night.\n\n'
                       'The rain fell in torrents.\n\n# Chapter II\n\nMorning came.\n')

    def test_a_missing_marker_or_heading_is_an_error(self):
        with pytest.raises(g.GutenbergError, match='START'):
            g.normalize('no markers here\n', PROSE_META)
        with pytest.raises(g.GutenbergError, match='chapter_heading'):
            g.normalize(raw('Just prose.\n'), PROSE_META)


class TestVerse:
    def test_line_breaks_and_stanzas_survive(self):
        out = g.normalize(raw(VERSE), VERSE_META)
        assert out.startswith(
            '# Prelude\n\n'
            'LO, praise of the prowess of people-kings\\\n'
            'of spear-armed Danes, in days long sped,\\\n'
            'we have heard!\n\n'
            'Oft Scyld the Scefing\\\nfrom squadroned foes\n\n# Fitt I\n')

    def test_word_count_is_the_prose_count(self):
        prose = g.normalize(raw(VERSE), dict(VERSE_META, verse=False))
        verse = g.normalize(raw(VERSE), VERSE_META)
        assert len(prose.split()) == len(verse.split())
        assert verse.replace('\\\n', ' ') == prose

    def test_prose_is_unchanged_by_the_verse_options(self):
        # verse off: one paragraph per line, as prepare_corpus made it
        out = g.normalize(raw(VERSE), dict(VERSE_META, verse=False))
        assert 'LO, praise of the prowess of people-kings of spear-armed Danes' in out
        assert '\\' not in out

    def test_verse_cleanups(self):
        out = g.normalize(raw(VERSE), dict(VERSE_META, drop_cap_case='title',
                                           strip_brackets=True,
                                           strip_unmatched_underscore=True))
        assert 'Lo, praise' in out
        assert 'To the door of the hall\\\nWulfgar went and the word' in out
        assert 'owned by thee!\n' in out
        assert '{0a}' not in out and 'A note' not in out

    def test_summary_counts_verse_lines(self):
        stats = g.summarize(g.normalize(raw(VERSE), VERSE_META), VERSE_META)
        assert stats['chapters'] == 2
        assert stats['verse_lines'] == 8


class TestSections:
    BODY = """I


Untitled opening.

How the knight rode out

He rode.

How he came home

He came home.


II


How it began

It began.
"""
    META = {'chapter_heading': r'^([IVX]+)$',
            'section_heading': r'^How [a-z ]+$'}

    def test_default_never_breaks_a_chapters_first_section(self):
        out = g.normalize(raw(self.BODY), self.META)
        assert out.count('* * *') == 1   # only before "How he came home"

    def test_after_text_breaks_a_first_section_after_untitled_text(self):
        """G-004: Weston's Fitts II and IV open with untitled paragraphs, so
        their first titled section is a real scene boundary."""
        out = g.normalize(raw(self.BODY), dict(self.META, section_break='after_text'))
        assert out == ('# Chapter I\n\nUntitled opening.\n\n* * *\n\nHe rode.\n\n'
                       '* * *\n\nHe came home.\n\n# Chapter II\n\nIt began.\n')

    def test_section_break_false_only_drops_the_titles(self):
        """G-002: titles that fall more often than scenes are dropped with no break."""
        out = g.normalize(raw(self.BODY), dict(self.META, section_break=False))
        assert '* * *' not in out and 'How' not in out


def test_verse_blocks_keep_an_indented_poem_in_prose():
    """G-003: Weston's closing bob-and-wheel, indented in prose."""
    body = 'I\n\n\nThe book bears witness, I wis\n\n  Many a venture\n    Hath fallen such as this:\n\nAmen.\n'
    meta = {'chapter_heading': r'^([IVX]+)$'}
    assert 'Many a venture Hath fallen' in g.normalize(raw(body), meta)
    out = g.normalize(raw(body), dict(meta, verse_blocks=True))
    assert 'Many a venture\\\nHath fallen such as this:\n' in out
    assert 'The book bears witness, I wis\n' in out


class TestConfig:
    def test_unknown_key_is_an_error(self):
        with pytest.raises(g.GutenbergError, match='chapter_headng'):
            g.check_config({'chapter_heading': 'x', 'chapter_headng': 'y'})

    def test_bad_regex_and_values(self):
        with pytest.raises(g.GutenbergError, match='does not compile'):
            g.check_config({'chapter_heading': '('})
        with pytest.raises(g.GutenbergError, match='section_break'):
            g.check_config({'chapter_heading': 'x', 'section_break': 'yes'})

    def test_descriptive_keys_are_accepted(self):
        g.check_config({'chapter_heading': 'x', 'title': 'T', 'author': 'A',
                        'edition': 'e', 'set': 'canon', 'form': 'verse'})


EVALS = os.path.expanduser('~/Developer/evals/corpus')


@pytest.mark.skipif(not os.path.isdir(EVALS), reason='needs the storyforge-evals corpus')
@pytest.mark.parametrize('slug', sorted(os.listdir(EVALS)) if os.path.isdir(EVALS) else [])
def test_every_evals_corpus_gives_the_same_manuscript(slug):
    """The port of the evals harness's prepare_corpus.py: each book's raw text
    and config give exactly the manuscript the harness made."""
    d = os.path.join(EVALS, slug)
    meta = g.check_config(json.load(open(os.path.join(d, 'meta.json'))))
    with open(os.path.join(d, 'source.txt'), 'rb') as f:
        text = f.read().decode('utf-8-sig')
    with open(os.path.join(d, 'manuscript.md')) as f:
        assert g.normalize(text, meta) == f.read()
