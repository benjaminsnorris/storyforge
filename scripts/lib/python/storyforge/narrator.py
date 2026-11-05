"""The narrator as a point of view (#555).

`narrator` is a reserved `pov` value in scenes.csv: the scene is told by the
book's narrator, not through a character (an epic's omniscient voice, a frame
narrator). It is never a characters.csv entry and need not be on stage.
The variants extraction and the models write ("Omniscient narrator", "the
narrator", "omniscient", "Omniscient epic narrator") normalize to it. A blank
POV is still a gap.

Whether the narrator may hold scenes is the author's, in
reference/key-decisions.md, on a line of its own:

    narrator_pov: allowed        (the default)
    narrator_pov: limited 12     (at most 12 narrator scenes)
    narrator_pov: off            (every scene has a character POV)

Found on the Iliad (95 of 239 scenes "Omniscient epic narrator", F-132),
Quintus (89%), Beowulf (B-005: `herald` or a blank) and Gawain (G-007: the
L5 floor check failed 7 of 8 narrator scenes).
"""

from __future__ import annotations

import os
import re
from dataclasses import dataclass

NARRATOR_POV = 'narrator'

# Words that may precede "narrator" in a variant: "the intrusive omniscient
# narrator", Carol's registered `intrusive-omniscient-narrator`. Anything
# else ("Nick's narrator", "narrator-of-troy") is not the reserved value
_QUALIFIERS = frozenset({
    'the', 'an', 'a', 'omniscient', 'epic', 'intrusive', 'third', 'person',
    'unnamed', 'anonymous', 'external', 'authorial', 'frame', 'framing',
    'heterodiegetic', 'poem', "poem's", 'book', "book's",
})

_SETTING = re.compile(r'narrator_pov\s*`?\s*:\s*`?\s*(allowed|off|limited\s+(\d+))\b', re.I)

ALLOWED, LIMITED, OFF = 'allowed', 'limited', 'off'


def is_narrator(value: str | None) -> bool:
    """True for `narrator` and the variants that mean it."""
    words = re.split(r'[\s_-]+', (value or '').strip().lower())
    words = [w for w in words if w]
    if words == ['omniscient']:
        return True
    return (bool(words) and words[-1] in ('narrator', 'narration')
            and all(w in _QUALIFIERS for w in words[:-1]))


def normalize_pov(value: str | None) -> str:
    """A pov cell with a narrator variant written as `narrator`; anything
    else as given."""
    return NARRATOR_POV if is_narrator(value) else (value or '')


@dataclass(frozen=True)
class Setting:
    mode: str = ALLOWED
    cap: int | None = None   # for `limited`
    stated: bool = False     # the line is in key-decisions.md (not the default)

    def describe(self) -> str:
        return f'limited {self.cap}' if self.mode == LIMITED else self.mode


def read_setting(project_dir: str) -> Setting:
    """The project's narrator_pov setting from reference/key-decisions.md
    (`allowed` when the file or the line is missing)."""
    path = os.path.join(project_dir, 'reference', 'key-decisions.md')
    try:
        with open(path, encoding='utf-8') as f:
            text = f.read()
    except (OSError, UnicodeDecodeError):
        return Setting()
    for line in text.splitlines():
        if line.lstrip().startswith('<!--'):
            continue
        m = _SETTING.search(line)
        if m:
            word = m.group(1).lower()
            if word.startswith(LIMITED):
                return Setting(LIMITED, int(m.group(2)), True)
            return Setting(word, None, True)
    return Setting()


def uses_narrator(project_dir: str) -> bool:
    """Whether any scene in reference/scenes.csv has the narrator as POV."""
    path = os.path.join(project_dir, 'reference', 'scenes.csv')
    if not os.path.isfile(path):
        return False
    from .elaborate import _read_csv
    return bool(narrator_scenes(_read_csv(path)))


def prompt_line(project_dir: str, *, always: bool = False) -> str:
    """One line for the elaborate and drafting prompts saying the setting:
    '' for a book that neither states it nor has a narrator scene, so their
    prompts are unchanged (unless `always`)."""
    s = read_setting(project_dir)
    if not (always or s.stated or uses_narrator(project_dir)):
        return ''
    if s.mode == OFF:
        return ('Narrator POV: off. Every scene has a character as its POV; never '
                'use `narrator` as a scene\'s pov.')
    if s.mode == LIMITED:
        return (f'Narrator POV: limited to {s.cap} scene(s). `narrator` as a scene\'s '
                f'pov means the book\'s narrator tells it, not a character; use it '
                f'for at most {s.cap} scenes.')
    return ('Narrator POV: allowed. `narrator` as a scene\'s pov means the book\'s '
            'narrator tells it, not a character (never a characters.csv entry, '
            'and never on stage).')


def narrator_scenes(scenes: list[dict]) -> list[str]:
    """The ids of the scenes whose pov is the narrator."""
    return [r.get('id', '') for r in scenes if is_narrator(r.get('pov'))]


def setting_problem(project_dir: str, scenes: list[dict]) -> str:
    """What breaks the project's setting ('' when nothing does): narrator
    scenes with `off`, or more than the cap with `limited N`."""
    s = read_setting(project_dir)
    ids = narrator_scenes(scenes)
    shown = ', '.join(ids[:5]) + ('…' if len(ids) > 5 else '')
    if s.mode == OFF and ids:
        return (f'{len(ids)} scene(s) have the narrator as POV, but key-decisions.md '
                f'says narrator_pov: off: {shown}')
    if s.mode == LIMITED and len(ids) > (s.cap or 0):
        return (f'{len(ids)} scene(s) have the narrator as POV, over key-decisions.md\'s '
                f'narrator_pov: limited {s.cap}: {shown}')
    return ''
