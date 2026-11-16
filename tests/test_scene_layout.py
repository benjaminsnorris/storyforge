"""A prose scene is saved one sentence per line (scene_layout)."""

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
