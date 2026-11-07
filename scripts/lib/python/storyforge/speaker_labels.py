"""The speaker-label convention for a brief's scripted lines (#513), as the
prompts say it: one wording, so every prompt says the same thing and a
change is one edit.

The gate reads a label (`gate._label_speaker`, through `gate._brief_lines`)
so its speaker check (#511) can check a speech tag that splits the line;
`references/scene-column-guide.md` is the author's version. The prompts ask
only for the form the gate reads with the least doubt, `Name: "line"`, the
label starting with one character's name, id or alias as characters.csv
writes it, so a prompt never teaches a form it can't read.

Prose books only: a graphic novel's `key_dialogue` is matched verbatim in
the panel script (`script_format`), where a label would fail it, so
`applies` is False there and no prompt carries the rule.
"""

from __future__ import annotations

import os
import re

#: For a prompt that writes a brief's scripted lines from the book's text
#: or plan, with the cast in front of it (`key_dialogue`, and a quoted line
#: in `key_actions`)
LABEL_RULE = ('Label every quoted line a character speaks, in key_dialogue or key_actions, '
              'as `Name: "line"`: start the label with the character\'s name, id or one of '
              'its aliases exactly as characters.csv writes it (nothing added before it, no '
              'possessive), one character per label, repeated for each '
              'line, even when the same character speaks again. Leave the label off only '
              "when it isn't clear who speaks.")

#: For a prompt that rewrites a brief's fields without the scene's text to
#: tell who speaks: it keeps labels and never guesses one (#513's review,
#: P-2: a wrong label sends the brief's own words to the fixer)
LABEL_KEEP = ('Keep every speaker label on a quoted line (`Name: "line"`) exactly as it is. '
              'Add one only where the text you are given already says who speaks the line, '
              'starting it with that character\'s name, id or an alias exactly as the cast '
              'list writes it (no possessive); never guess a speaker.')

#: For a prompt that reads a brief's scripted lines into prose
LABEL_READING = ('A brief line written `Name: "line"` is that character\'s: write the line as '
                 'their speech, and never write the `Name:` label itself into the prose.')

#: A speaker label as the gate reads one: a colon before a quote mark, or a
#: dash after a closing one
_LABEL = re.compile(r'\w[^"“:;|\n]*:\s*["“]|["”]\s*(?:—|–|--?)\s*\w')


def has_label(text: str) -> bool:
    """Whether `text` (a brief cell) holds a speaker label."""
    return bool(_LABEL.search(text or ''))


def applies(project_dir: str) -> bool:
    """Whether the project's briefs take speaker labels: prose books only."""
    from .common import get_medium
    return get_medium(project_dir) != 'graphic-novel'


def cast_list(project_dir: str) -> str:
    """The cast a label may name, compact: `- id: Name (aliases: a; b)` per
    characters.csv row with a name, or a line saying there is none."""
    from .elaborate import _read_csv
    rows = _read_csv(os.path.join(project_dir, 'reference', 'characters.csv'))
    lines = []
    for r in rows:
        name = (r.get('name') or '').strip()
        if not name:
            continue
        cid = (r.get('id') or '').strip()
        aliases = '; '.join(a.strip() for a in (r.get('aliases') or '').split(';') if a.strip())
        lines.append(f'- {cid + ": " if cid else ""}{name}'
                     + (f' (aliases: {aliases})' if aliases else ''))
    return '\n'.join(lines) or '(characters.csv names no one: add no label)'


def keep_section(project_dir: str) -> str:
    """The cast and `LABEL_KEEP`, for a brief rewrite prompt; '' for a
    graphic novel (`applies`)."""
    if not applies(project_dir):
        return ''
    return f'## Cast (characters.csv)\n\n{cast_list(project_dir)}\n\n{LABEL_KEEP}'
