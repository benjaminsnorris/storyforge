"""Tests for storyforge.quotes: is a model's quote really in the prose."""

import pytest

from storyforge.quotes import normalize, quote_in, word_count

TEXT = ('"Seven years dead," mused Scrooge -- and she knew it… '
        'The *old* man’s chain was long.\nVery long.')


@pytest.mark.parametrize('quote', [
    'seven years dead,” mused Scrooge',
    'mused Scrooge — and she knew it',
    'she knew it...',
    'The old man\'s chain',
    'chain was long. Very long.',
    '"Seven years dead," ... the old man\'s chain',
])
def test_found(quote):
    assert quote_in(TEXT, quote)


@pytest.mark.parametrize('quote', [
    'he knew it',            # inside "she knew"
    'even years',            # inside "Seven"
    'Twelve years dead',
    'the old man ... seven years',   # parts out of order
    '...',
    '',
])
def test_not_found(quote):
    assert not quote_in(TEXT, quote)


def test_normalize_and_count():
    assert normalize('A—B -- *c*') == 'a-b - c'
    assert word_count('the old man’s') == 4


def test_a_quote_across_verse_lines_matches():
    """`source fetch --verse` ends each verse line but a stanza's last with a
    hard break (`\\`); a quote spanning two lines didn't match."""
    verse = 'and add this word, -- they are welcome guests\\\nto folk of the Danes."\n'
    assert quote_in(verse, 'they are welcome guests to folk of the Danes')
    assert normalize('guests\\\nto folk') == 'guests to folk'
    # a backslash that isn't a line's end is left alone
    assert normalize('a\\b') == 'a\\b'


@pytest.mark.parametrize('quote', [
    'they are welcome guests\\ to folk',
    'they are welcome guests / to folk',
])
def test_a_verse_quote_written_on_one_line_matches(quote):
    verse = 'and add this word, -- they are welcome guests\\\nto folk of the Danes."\n'
    assert quote_in(verse, quote)
