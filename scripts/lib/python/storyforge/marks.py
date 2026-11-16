"""The author's marks on drafted scenes, and revision by reaction (#655).

The voice rounds' lesson: the author reacts to lines (keep, cut, more like
this, a note), and the reviser revises toward what was kept. A marks file:

    ## act1-sc03
    > He had come all the way down from the house to say it.
    cut: reads like AI

    > Andromache did not smile.
    keep

    ## act1-sc04
    > the coolest thing he had felt all day
    reeks of AI

Each `## <scene id>` heading starts a scene. Each `>` line quotes the
scene's words; consecutive `>` lines join into one quote, and a blank line
ends it. The lines after a quote, up to the next blank line, quote or
heading, are its note. A quote with no note, or whose note is just one of
`KEEP_NOTES` (keep, more like this, yes, love this, perfect), is a **keep**: a line that works, shown to the reviser
as an example and never edited (`is_keep`). Every other note asks for a
change.

Problems are refused, never guessed at (`MarksError`, naming the line): a
quote before any heading, a heading that isn't `## <one scene id>`, a scene
given twice, an empty quote, a note with no quote above it.

`storyforge revise --marks <file>` sends each scene's marks to the voice
reviser (`voice_review.revise`): it rewrites only the lines asked for,
toward the voice and the keeps; the scene is then gated and committed.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import NamedTuple


class MarksError(ValueError):
    """A marks file that can't be used; the message says where."""


#: notes that mean "this works": the line is an example, never edited
KEEP_NOTES = frozenset({'keep', 'more like this', 'yes', 'love this', 'perfect'})


class Mark(NamedTuple):
    """One mark: the scene's words and the author's note; `comment_id` the
    PR comment it came from (`revise --marks-from-pr`; 0 from a file)."""
    quote: str
    note: str
    comment_id: int = 0


def is_keep(mark: Mark) -> bool:
    """Whether a mark says the line works (an example for the reviser)."""
    return mark.note.strip().rstrip('.!').lower() in KEEP_NOTES


@dataclass
class SceneMarks:
    """One scene's marks, in the file's order."""
    scene_id: str
    marks: list[Mark] = field(default_factory=list)

    @property
    def keeps(self) -> list[Mark]:
        return [m for m in self.marks if is_keep(m)]

    @property
    def changes(self) -> list[Mark]:
        return [m for m in self.marks if not is_keep(m)]


_HEADING = re.compile(r'^#{1,6}\s')
_SCENE_HEADING = re.compile(r'^##\s+(\S+)\s*$')


def parse_marks(text: str) -> list[SceneMarks]:
    """The scenes and their marks, in the file's order. A `#` heading
    before the first scene heading (a title) is allowed.

    Raises:
        MarksError: as the module says, naming the line.
    """
    scenes: list[SceneMarks] = []
    quote: list[str] = []
    note: list[str] = []
    quote_line = 0

    def flush():
        if quote:
            words = ' '.join(q for q in quote if q).strip()
            if not words:
                raise MarksError(f'line {quote_line}: a `>` line quotes nothing')
            if not scenes:
                raise MarksError(f'line {quote_line}: a marked line comes before any '
                                 f'`## <scene id>` heading')
            scenes[-1].marks.append(Mark(words, ' '.join(note).strip() or 'keep'))
        quote.clear()
        note.clear()

    for n, line in enumerate(text.replace('\r\n', '\n').split('\n'), start=1):
        if _HEADING.match(line):
            flush()
            m = _SCENE_HEADING.match(line)
            if not m:
                if line.startswith('# ') and not scenes:
                    continue   # the file's title
                raise MarksError(f'line {n}: a scene heading is `## <scene id>` alone, '
                                 f'not {line.strip()!r}')
            sid = m.group(1)
            if any(s.scene_id == sid for s in scenes):
                raise MarksError(f'line {n}: scene {sid} is given twice')
            scenes.append(SceneMarks(sid))
        elif line.startswith('>'):
            if note:
                flush()
            if not quote:
                quote_line = n
            quote.append(line[1:].strip())
        elif not line.strip():
            if quote and note:
                flush()
            elif quote:
                flush()   # a blank line ends a quote with no note: a keep
        elif quote:
            note.append(line.strip())
        elif scenes:
            raise MarksError(f'line {n}: a note with no `>` quoted line above it: '
                             f'{line.strip()[:60]!r}')
    flush()
    return scenes
