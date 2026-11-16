"""How a prose scene file is laid out: one sentence per line, paragraphs a
blank line apart.

An author marks a draft in a pull request, and a line comment attaches to a
line: with a sentence per line, a mark is on the sentence it means, as in
the voice rounds (`voice_sample`). Markdown joins the lines of a paragraph,
so the book that's assembled is the same.

`sentence_lines` is applied wherever drafted or revised prose is saved
(drafting, a session, a redraft, a revision pass, the gate's fixes and the
reviser's, through `gate.apply_edits`). It changes only line breaks inside
a paragraph: a paragraph that isn't plain prose (an illustration marker, a
heading, a scene break, a blockquote, a list, an indented block, a hard
line break) is left as it is.
"""

from __future__ import annotations

import re

_PARA_SPLIT = re.compile(r'(\n(?:[ \t]*\n)+)')
#: a line that makes its paragraph something other than plain prose
_NOT_PROSE = re.compile(
    r'^(?:[ \t]|#|>|<|!\[|\||```|~~~|[-*+][ \t]|\d+[.)][ \t]|'
    r'(?:[-*_][ \t]*){3,}$)')


def _is_prose(para: str) -> bool:
    lines = para.split('\n')
    return not any(_NOT_PROSE.match(ln) or ln.endswith(('  ', '\\')) for ln in lines)


def _reflow(para: str) -> str:
    from storyforge.voice_review import sentence_spans
    flat = ' '.join(para.split())
    return '\n'.join(flat[a:b].strip() for a, b in sentence_spans(flat))


def sentence_lines(text: str) -> str:
    """`text` with each sentence of its prose paragraphs on its own line.
    Only line breaks within a paragraph change (and the spaces around
    them): the words, the blank lines between paragraphs, any paragraph
    that isn't plain prose, the leading and trailing whitespace and the
    line endings are kept. Running it twice changes nothing."""
    crlf = '\r\n' in text
    if crlf:
        text = text.replace('\r\n', '\n')
    if not text.strip():
        return text.replace('\n', '\r\n') if crlf else text
    lead = text[:len(text) - len(text.lstrip())]
    trail = text[len(text.rstrip()):]
    body = text.strip()
    parts = _PARA_SPLIT.split(body)
    # parts alternates paragraph, separator, paragraph...
    out = [p if i % 2 or not p.strip() or not _is_prose(p) else _reflow(p)
           for i, p in enumerate(parts)]
    result = lead + ''.join(out) + trail
    return result.replace('\n', '\r\n') if crlf else result
