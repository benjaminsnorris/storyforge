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
