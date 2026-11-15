"""The author's marks on drafted scenes, and revision by reaction (#655).

The voice rounds' lesson: the author reacts to lines (keep, cut, more like
this, a note), and the writer revises toward what was kept. A marks file:

    ## act1-sc03
    > He had come all the way down from the house to say it.
    cut: reads like AI

    > Andromache did not smile.
    more like this

    ## act1-sc04
    > the coolest thing he had felt all day
    reeks of AI

Each `## <scene id>` starts a scene; each `>` line quotes the scene's words
(several `>` lines join into one quote); the lines after it, up to the next
quote or heading, are the note. A quote with no note is kept as a mark with
the note "keep" (it tells the reviser what works).

`storyforge revise --marks <file>` sends each scene's marks to the voice
reviser (`voice_review.revise`), which rewrites only the marked sentences
toward the voice; the scene then goes through the gate and is committed.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field


class MarksError(ValueError):
    """A marks file that can't be used; the message says where."""


@dataclass
class SceneMarks:
    """One scene's marks: (the scene's words, the note), in order."""
    scene_id: str
    marks: list[tuple[str, str]] = field(default_factory=list)


def parse_marks(text: str) -> list[SceneMarks]:
    """The scenes and their marks, in the file's order.

    Raises:
        MarksError: a quote before any `## <scene id>`, or a scene given twice.
    """
    scenes: list[SceneMarks] = []
    quote: list[str] = []
    note: list[str] = []

    def flush():
        if quote:
            if not scenes:
                raise MarksError('a marked line comes before any `## <scene id>` heading')
            scenes[-1].marks.append((' '.join(quote).strip(),
                                     ' '.join(note).strip() or 'keep'))
        quote.clear()
        note.clear()

    for n, line in enumerate(text.replace('\r\n', '\n').split('\n'), start=1):
        heading = re.match(r'^##\s+(\S+)\s*$', line)
        if heading:
            flush()
            sid = heading.group(1)
            if any(s.scene_id == sid for s in scenes):
                raise MarksError(f'line {n}: scene {sid} is given twice')
            scenes.append(SceneMarks(sid))
        elif line.startswith('>'):
            if note:
                flush()
            quote.append(line[1:].strip())
        elif line.strip() and quote:
            note.append(line.strip())
    flush()
    return scenes
