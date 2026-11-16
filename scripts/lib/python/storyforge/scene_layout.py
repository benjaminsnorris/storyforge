"""How a prose scene file is laid out: one sentence per line, paragraphs a
blank line apart.

An author marks a draft in a pull request, and a line comment attaches to a
line: with a sentence per line, a mark is on the sentence it means, as in
the voice rounds (`voice_sample`). Markdown joins the lines of a paragraph,
so the assembled book is the same.

- **What changes:** only the line breaks of a plain prose paragraph, and
  the spaces or tabs around them (`sentence_lines`). Other whitespace (a
  non-breaking or thin space, a double space inside a sentence) is kept.
- **What is left alone:** a paragraph that isn't plain prose (an
  illustration marker, a heading, a scene break, a blockquote, a list, an
  indented block, a hard line break, HTML), and one whose line breaks
  don't all fall at sentence ends (verse, a letter: the author's breaks;
  `notes` says so, since Markdown joins them in the book).
- **Only what changed** (`old`): a paragraph that was already in the scene
  (the same words) keeps its bytes, so a revision lays out only the
  paragraphs it rewrote, and a reply that changed nothing leaves the file
  as it was. `storyforge cleanup --scenes` lays out a whole book once.

Every path that saves drafted or revised prose goes through `write_scene`
or `sentence_lines` (docs/agent-reference.md lists them).

The sentence splitter (`sentence_spans`) and the edit locator (`find_span`,
an edit's `find` matched across a sentence's line break) live here too:
the gate and the voice review use both.
"""

from __future__ import annotations

import re
from typing import Callable, NamedTuple

# ============================================================================
# Sentences
# ============================================================================

#: a sentence's end: its closing quotes and brackets belong to it (`close`),
#: the spaces after don't. A lowercase word after it carries the sentence on
#: (`"Who?" she asks.`). Only spaces, tabs and line breaks part sentences: a
#: non-breaking or thin space binds (`ships. . .`).
_SENTENCE_END = re.compile(
    r'(?<=[.!?…])(?P<close>["”’\')\]]*)[ \t\n]+(?![ \t\na-z])|\n[ \t]*\n|\n')

#: a title or an initial, whose full stop doesn't end the sentence when the
#: sentence goes on on the same line. `I.` is the pronoun, not an initial
#: (`So did I. We left.`); `No.` is an answer.
_ABBREVIATION = re.compile(
    r'(?:^|(?<=[\s(\["“‘\']))(?:Mr|Mrs|Ms|Mx|Dr|St|Mt|Jr|Sr|Prof|Capt|Col|Gen|Lt|Sgt|'
    r'Rev|Fr|Hon|Gov|Sen|Rep|[A-HJ-Z])\.$')


def sentence_spans(prose: str) -> list[tuple[int, int]]:
    """(start, end) of each sentence (or line) in `prose`, in order. A
    sentence keeps its closing quote: `"I'll tell you."` ends after the `"`.
    A line break always ends one."""
    spans, start = [], 0
    for m in _SENTENCE_END.finditer(prose):
        end = m.start() + len(m.group('close') or '')
        if (m.group('close') == '' and '\n' not in m.group(0)
                and _ABBREVIATION.search(prose, max(0, m.start() - 6), m.start())):
            continue   # `Mr. Darcy`, `J. Smith`: the sentence goes on
        if prose[start:end].strip():
            spans.append((start, end))
        start = m.end()
    if prose[start:].strip():
        spans.append((start, len(prose)))
    return spans


# ============================================================================
# Paragraphs
# ============================================================================

_PARA_SPLIT = re.compile(r'(\n(?:[ \t]*\n)+)')
#: a line that makes its paragraph something other than plain prose
_NOT_PROSE = re.compile(
    r'^(?:[ \t]|#|>|<|!\[|\||```|~~~|[-*+][ \t]|\d+[.)][ \t]|'
    r'(?:[-*_][ \t]*){3,}$)')
_BREAK = re.compile(r'[ \t]*\n[ \t]*')


def _is_markup(para: str) -> bool:
    """Whether a paragraph is something other than plain prose."""
    return any(_NOT_PROSE.match(ln) or ln.endswith(('  ', '\\')) for ln in para.split('\n'))


def _flat(text: str) -> str:
    return ' '.join(text.split())


def _reflow(para: str) -> str:
    joined = _BREAK.sub(' ', para.strip(' \t\n'))
    return '\n'.join(joined[a:b].strip(' \t') for a, b in sentence_spans(joined))


def _breaks_at_sentences(para: str, laid: str) -> bool:
    """Whether every line break of `para` is a sentence's end in `laid` (its
    reflow): else the breaks are the author's (verse, a letter)."""
    new = iter(laid.split('\n'))
    for line in para.split('\n'):
        want, got = _flat(line), ''
        while len(got) < len(want):
            nxt = next(new, None)
            if nxt is None:
                return False
            got = f'{got} {_flat(nxt)}'.strip()
        if got != want:
            return False
    return True


def _paragraph_note(n: int, para: str) -> str:
    words = _flat(para)
    head = words[:40] + ('…' if len(words) > 40 else '')
    return (f'paragraph {n} ("{head}") keeps its line breaks: they don\'t fall at '
            f'sentence ends (verse, or a letter?). Markdown joins them in the book; end a '
            f'line with two spaces or a backslash to keep a break there.')


def sentence_lines(text: str, old: str | None = None,
                   notes: list[str] | None = None) -> str:
    """`text` with each sentence of its plain prose paragraphs on its own
    line (see the module's docstring for what's left alone).

    `old`: the scene before; a paragraph with the same words as one of its
    paragraphs is given that paragraph's bytes, so only what changed is
    laid out. `notes`: a paragraph left alone for its own line breaks is
    said there.

    Leading and trailing whitespace and the blank lines between paragraphs
    are kept; so are CRLF endings, when every line has one (mixed endings:
    `text` comes back as it is). Running it twice changes nothing."""
    crlf = '\r\n' in text
    if crlf:
        if text.count('\r\n') != text.count('\n'):
            return text
        text = text.replace('\r\n', '\n')
        old = old.replace('\r\n', '\n') if old else old
    if not text.strip():
        return text.replace('\n', '\r\n') if crlf else text
    before = {}
    if old:
        for p in _PARA_SPLIT.split(old.strip())[::2]:
            if p.strip():
                before.setdefault(_flat(p), p)
    lead = text[:len(text) - len(text.lstrip())]
    trail = text[len(text.rstrip()):]
    parts = _PARA_SPLIT.split(text.strip())
    out, n = [], 0
    for i, p in enumerate(parts):
        if i % 2 or not p.strip():
            out.append(p)
            continue
        n += 1
        if _flat(p) in before:
            out.append(before[_flat(p)])
            continue
        if _is_markup(p):
            out.append(p)
            continue
        laid = _reflow(p)
        if '\n' in p.strip() and not _breaks_at_sentences(p.strip(), laid):
            if notes is not None:
                notes.append(_paragraph_note(n, p))
            out.append(p)
            continue
        out.append(laid)
    result = lead + ''.join(out) + trail
    return result.replace('\n', '\r\n') if crlf else result


def write_scene(path: str, text: str, old: str | None = None,
                log: Callable[[str], None] | None = None, who: str = '') -> str:
    """Save prose to a scene file laid out a sentence per line
    (`sentence_lines`, with `old`), saying through `log` (with `who`, the
    scene's name) any paragraph left alone. Returns what was written."""
    notes: list[str] = []
    laid = sentence_lines(text, old=old, notes=notes)
    with open(path, 'w', encoding='utf-8') as f:
        f.write(laid)
    if log:
        for note in notes:
            log(f'  NOTE: {who + ": " if who else ""}{note}')
    return laid


# ============================================================================
# Finding an edit's words
# ============================================================================

class Found(NamedTuple):
    """Where an edit's `find` is: `span` when it's in one place, else None;
    how often it occurs exactly, and loosely (whitespace aside, within a
    paragraph's prose)."""
    span: tuple[int, int] | None
    exact: int
    loose: int = 0

    def problem(self, find: str) -> str:
        """Why an edit can't be placed, after "occur(s)": `0 times exactly,
        2 ignoring line breaks, in the scene: 'find'`."""
        loose = (f', {self.loose} ignoring line breaks,' if self.loose else '')
        return f'{self.exact} times exactly{loose} in the scene: {find[:80]!r}'


_BLANK = re.compile(r'\r?\n[ \t]*\r?\n')


def _soft_breaks(prose: str, at: int) -> bool:
    """Whether the line breaks of the paragraph at `at` are a prose
    paragraph's sentence ends (not markup, not verse)."""
    start = 0
    for m in _BLANK.finditer(prose, 0, at):
        start = m.end()
    m = _BLANK.search(prose, at)
    para = prose[start:m.start() if m else len(prose)].replace('\r\n', '\n').strip()
    return not _is_markup(para) and _breaks_at_sentences(para, _reflow(para))


def find_span(prose: str, find: str) -> Found:
    """Where `find` is in `prose`. Exactly once wins. Otherwise, since a
    scene has a sentence per line, the words may be there with a line break
    where `find` has a space (or the other way): `find`'s words, in order,
    with any spaces or one soft line break between them, found once within
    a plain prose paragraph (never across a blank line, a hard break, a
    heading or verse). Spaces around `find` are left out of that match."""
    exact = prose.count(find) if find else 0
    if exact == 1:
        start = prose.index(find)
        return Found((start, start + len(find)), 1)
    if exact or not find.strip():
        return Found(None, exact)
    gap = r'(?:[ \t]*\r?\n[ \t]*|[ \t]+)'
    hits = [m for m in re.finditer(gap.join(re.escape(w) for w in find.split()), prose)
            if '\n' not in m.group(0) or _soft_breaks(prose, m.start())]
    if len(hits) == 1:
        return Found((hits[0].start(), hits[0].end()), 0, 1)
    return Found(None, 0, len(hits))
