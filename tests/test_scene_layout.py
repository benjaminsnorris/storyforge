"""A prose scene is saved one sentence per line (scene_layout)."""

import pytest

from storyforge.scene_layout import sentence_lines


def _words(text):
    return text.split()


def test_each_sentence_of_a_paragraph_gets_its_own_line():
    text = ('Calchas takes the staff. "Achilles. I\'ll tell you." His eyes go past him.\n'
            '\n'
            '"Who is it?" she asks. Nobody answers.\n')
    assert sentence_lines(text) == (
        'Calchas takes the staff.\n"Achilles.\nI\'ll tell you."\nHis eyes go past him.\n'
        '\n'
        '"Who is it?" she asks.\nNobody answers.\n')


def test_only_line_breaks_change_and_twice_is_once():
    text = ('  The light goes first. Briseis is in the courtyard.\n\n\n'
            'She folds it.   Corner to corner.\nThen she stops.\n\n')
    once = sentence_lines(text)
    assert _words(once) == _words(text)
    assert once.startswith('  The light goes first.\nBriseis')
    assert '\n\n\nShe folds it.\nCorner to corner.\nThen she stops.\n\n' in once
    assert sentence_lines(once) == once


def test_a_paragraph_that_is_not_plain_prose_is_left_alone():
    blocks = ['![[illus:the-ships]]',
              '# A heading. With two sentences.',
              '---',
              '* * *',
              '> A quoted line. And another.',
              '- a list. item two.',
              '    indented. block.',
              'A hard break.  \nNext line. Here.',
              '<!-- a note. two -->']
    for block in blocks:
        text = f'One. Two.\n\n{block}\n\nThree. Four.\n'
        assert sentence_lines(text) == f'One.\nTwo.\n\n{block}\n\nThree.\nFour.\n', block


def test_crlf_is_kept():
    assert sentence_lines('One. Two.\r\n\r\nThree.\r\n') == 'One.\r\nTwo.\r\n\r\nThree.\r\n'


def test_empty_and_blank_text():
    assert sentence_lines('') == ''
    assert sentence_lines('\n\n') == '\n\n'


# ============================================================================
# Review of #704
# ============================================================================

from storyforge.scene_layout import find_span, sentence_spans, write_scene  # noqa: E402

CORPUS = [
    '*He is gone.* She waits. Then.',
    'It cost 3.50 in the U.S. market. Fine!',
    '"No!"—then he ran. Who? Nobody… And then.',
    'She left. <!-- a note. two --> He stayed.',
    '‘I don’t know,’ she said. ‘Nor I.’ They went.',
    'Neither did I. We left. So did I.',
    'Mr. Darcy met J. R. Smith. "No." Dr. Who left.',
    'Line one of a paragraph per line, with three sentences. Two. Three.',
    'He saw the ships. . . Then nothing. It cost 5 drachmas.',
    'Tabs\tinside. And  double  spaces. Kept.',
]


@pytest.mark.parametrize('text', CORPUS)
def test_words_survive_and_twice_is_once(text):
    """T-1: the words, every non-breaking or thin space among them, survive."""
    out = sentence_lines(text + '\n\n' + text + '\n')
    assert _words(out) == _words(text + ' ' + text)
    for ch in '  \t':
        assert out.count(ch) == (text + text).count(ch)
    assert sentence_lines(out) == out


def test_unicode_spaces_bind_and_pronoun_i_ends_a_sentence():
    """CR-2 / I2, CR-4 / I3."""
    assert sentence_lines('He saw the ships. . . Then nothing.') == \
        'He saw the ships. . .\nThen nothing.'
    assert sentence_lines('It cost 5 drachmas. Fine.') == 'It cost 5 drachmas.\nFine.'
    assert sentence_lines('Neither did I. We left.') == 'Neither did I.\nWe left.'


def test_a_line_break_always_ends_a_sentence_even_after_an_initial():
    """CR-1 / H3: `I.` or `B.` at a paragraph's end never joins the next."""
    prose = 'Nobody knew but Plan B.\n\nHector came down. He was tired.'
    texts = [prose[a:b] for a, b in sentence_spans(prose)]
    assert texts == ['Nobody knew but Plan B.', 'Hector came down.', 'He was tired.']


def test_verse_and_letters_keep_their_breaks_and_are_named():
    """SF-2 / H4: breaks that aren't at sentence ends are the author's."""
    verse = 'Sing, goddess, the wrath\nof Peleus\' son, the ruinous wrath\nthat brought pain.'
    letter = 'Dear Hector,\nCome home.\nYour mother'
    notes = []
    text = f'One. Two.\n\n{verse}\n\n{letter}\n'
    assert sentence_lines(text, notes=notes) == f'One.\nTwo.\n\n{verse}\n\n{letter}\n'
    assert len(notes) == 2 and 'paragraph 2' in notes[0] and 'two spaces' in notes[0]
    # breaks already at sentence ends are a laid-out paragraph
    assert sentence_lines('He fell.\nAnd fell. Again.') == 'He fell.\nAnd fell.\nAgain.'


def test_only_changed_paragraphs_are_laid_out():
    """H2, H5, I1: a paragraph with the same words as one before keeps its
    bytes; a reply that changed nothing leaves the scene as it was."""
    old = 'One. Two.\n\nThree. Four.\n'
    assert sentence_lines(old, old=old) == old
    assert sentence_lines('One.\nTwo.\n\nThree. Four.\n', old=old) == old
    assert sentence_lines('One. Two.\n\nThree. Five.\n', old=old) == \
        'One. Two.\n\nThree.\nFive.\n'


def test_mixed_line_endings_come_back_as_they_are():
    assert sentence_lines('One. Two.\r\nThree.\n') == 'One. Two.\r\nThree.\n'


def test_markup_paragraphs_left_alone_including_a_leading_marker():
    text = '![[illus:a]] He goes. She stays.\n'
    assert sentence_lines(text) == text


def test_write_scene_writes_and_names_what_it_left(tmp_path):
    path = tmp_path / 's.md'
    said = []
    out = write_scene(str(path), 'One. Two.\n\nroses are red\nviolets blue\n',
                      log=said.append, who='s1')
    assert path.read_text() == out == 'One.\nTwo.\n\nroses are red\nviolets blue\n'
    assert said and said[0].startswith('  NOTE: s1: paragraph 2')


@pytest.mark.parametrize('prose, find, span, why', [
    ('A b.\nC d.\n\nA b.\nC d.\n', 'A b. C d.', None, '0 times exactly, 2 ignoring'),
    ('He waits.\nShe comes.\n', 'waits. She', (3, 13), ''),
    ('He waits.\r\nShe comes.\r\n', 'waits. She', (3, 14), ''),
    ('comes.\n\nThey go.\n', 'comes. They', None, '0 times exactly in'),
    ('the wrath  \nof Peleus son\n', 'wrath of Peleus', None, '0 times exactly in'),
    ('Sing the wrath\nof Peleus son\nthat brought pain.\n', 'wrath of', None, '0 times'),
])
def test_find_span(prose, find, span, why):
    """T-2, SF-5 / I4, SF-6 / I6: loosened only across a soft break of a
    prose paragraph; an ambiguous loose match is said as such."""
    found = find_span(prose, find)
    assert found.span == span
    if why:
        assert why in found.problem(find)
