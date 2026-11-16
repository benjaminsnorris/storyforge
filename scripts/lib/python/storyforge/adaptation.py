"""An adaptation enters the ladder at the scene map (#658, plan D8).

A book with a `source:` block doesn't build its logline, synopsis, act
shape, spine and architecture: the source supplies the load-bearing facts
of those rungs (its imported scenes, spine, cast and bible under
`reference/source/<slug>/`), and the author's **interpretation decisions**
in `reference/key-decisions.md` settle what the source doesn't: what this
version is about, whose eyes, what's cut, what's invented, where it ends,
and the mode. Those few lines do for an adaptation what the spine and
architecture do for an original.

`entry(project_dir)` says where a book enters the ladder:

- no `source:` block: None, and every caller does what it did before;
- a `source:` book with a spine or architecture of its own: the **full
  ladder** (`Entry.enters_at_map` False). That is how an adaptation that
  strays far from its source builds its upper rungs itself, as an original
  does (plan decision 13), and how every adaptation built before #658 keeps
  its route;
- otherwise it enters at the scene map (`Entry.enters_at_map` True), and
  the upper rungs are given once the source is imported and the decisions
  are recorded (`Entry.ready`); `Entry.problems` says what is missing.

The decisions live under a heading `Interpretation decisions` (any level
from `#` to `####`; a heading in a fenced code block doesn't count), one
per labelled line or sub-heading, as `DECISIONS` lists them:
`- **Whose eyes:** ...`, `1. Whose eyes: ...`, `*Whose eyes* — ...`,
`**Mode (faithful/free):** ...`, `| Whose eyes | ... |`, `### Whose eyes`.
HTML comments (over several lines too) are not the author's text. A
labelled line indented deeper than the section's first decision line is
part of the decision above it, not a new one. A label with nothing after
it, or only a placeholder (`<...>`, `[...]`, TBD, TODO, TK, `?`, N/A,
`...`), is not recorded, and the placeholder is named. A decision given
twice keeps the last one written (key-decisions.md is added to over time),
and a note says so. A label-shaped line naming no decision is named when
a decision is missing, so a decision written in a form the parser can't
read is said, not reported absent without a word. A Mode whose first word
is a mode (`faithful`, `free`) must agree with `source.mode` in
storyforge.yaml, which the checks read; one that doesn't open with a mode
can't be compared, and a note says so.
"""

from __future__ import annotations

import os
import re
from collections.abc import Mapping
from dataclasses import dataclass, field

from storyforge import source

#: The rungs the source gives an adaptation entering at the scene map:
#: logline, synopsis, act-shape, spine, architecture (status's levels 0-4)
GIVEN_LEVELS = (0, 1, 2, 3, 4)
#: An own artifact at one of these levels means the full ladder
OWN_LADDER_LEVELS = (3, 4)

#: Where the decisions are, and the heading over them
KEY_DECISIONS = os.path.join('reference', 'key-decisions.md')
HEADING = 'Interpretation decisions'

#: (key, label) for each interpretation decision, in the order the author
#: is asked for them (plan D8)
DECISIONS = (
    ('about', 'What this version is about'),
    ('eyes', 'Whose eyes'),
    ('cut', "What's cut"),
    ('invented', "What's invented"),
    ('ending', 'Where it ends'),
    ('mode', 'Mode'),
)
_LABELS = dict(DECISIONS)
_KEYS = tuple(k for k, _ in DECISIONS)

# The words that name each decision, after `_norm` (lower case, letters
# and spaces only, a parenthetical dropped): the label, and the forms an
# author writes
_ALIASES = {
    'about': ('what this version is about', 'what this book is about',
              'what the book is about', 'what this version is', 'what this book is',
              'what it is about', 'whats it about', 'what its about', 'about'),
    'eyes': ('whose eyes', 'eyes', 'point of view', 'pov', 'whose point of view'),
    'cut': ('whats cut', 'what is cut', 'what gets cut', 'cut', 'cuts'),
    'invented': ('whats invented', 'what is invented', 'what gets invented', 'invented',
                 'inventions', 'invention'),
    'ending': ('where it ends', 'where the book ends', 'where this version ends',
               'ending', 'the ending', 'end'),
    'mode': ('mode', 'the mode'),
}
_BY_ALIAS = {alias: key for key, aliases in _ALIASES.items() for alias in aliases}

_HEADING_RE = re.compile(r'^(#{1,6})\s+(.+?)\s*#*\s*$')
_FENCE_RE = re.compile(r'^\s*(```|~~~)')
_COMMENT_RE = re.compile(r'<!--.*?(-->|\Z)', re.S)
_EMPH = r'(?:\*\*|__|\*|_)?'
# An optional bullet or number, an optional emphasised label, then a colon
# or a dash (`:` inside or after the emphasis), then the value
_LINE_RE = re.compile(
    r'^(?P<indent>\s*)(?:[-*+]\s+|\d+[.)]\s+)?' + _EMPH
    + r'(?P<label>[A-Za-z][^:*_|\n—–]{0,60}?)\s*(?::\s*' + _EMPH + r'|' + _EMPH
    + r'\s*(?::|\s[—–-]\s|[—–]))\s*(?P<value>.*)$')
# `| label | value |`
_TABLE_RE = re.compile(r'^\s*\|\s*(?P<label>[^|]+?)\s*\|\s*(?P<value>[^|]*?)\s*\|\s*$')
_PLACEHOLDER_RE = re.compile(
    r'^(<[^>]*>.*|\[[^\]]*\]|\?+|n/?a\.?|(tbd|todo|tk)\b.*|\.\.\.|…)$', re.I)


def _norm(text: str) -> str:
    text = re.sub(r'\([^)]*\)', ' ', text.lower())
    text = text.replace('’', '').replace("'", '')
    return ' '.join(re.sub(r'[^a-z ]+', ' ', text).split())


def _key_for(label: str) -> str | None:
    return _BY_ALIAS.get(_norm(label))


def _clean(value: str) -> str:
    return value.strip().strip('*_').strip()


def _placeholder(value: str) -> bool:
    return bool(_PLACEHOLDER_RE.match(_clean(value)))


@dataclass(frozen=True)
class Parsed:
    """What `parse_decisions` reads from key-decisions.md's text."""
    has_section: bool = False
    #: key → the author's text of each recorded decision
    found: Mapping[str, str] = field(default_factory=dict)
    #: key → the placeholder written in its place
    placeholders: Mapping[str, str] = field(default_factory=dict)
    #: key → how many times it was given (only those given more than once)
    repeated: Mapping[str, int] = field(default_factory=dict)
    #: label-shaped lines in the section that name no decision
    unread: tuple[str, ...] = ()


def parse_decisions(text: str) -> Parsed:
    """The interpretation decisions in key-decisions.md's text (the module
    docstring has the forms read)."""
    text = _COMMENT_RE.sub('', text)
    lines, fenced = [], False
    for line in text.splitlines():
        if _FENCE_RE.match(line):
            fenced = not fenced
            lines.append('')
            continue
        lines.append('' if fenced else line)
    start = level = None
    for i, line in enumerate(lines):
        m = _HEADING_RE.match(line)
        if m and len(m.group(1)) <= 4 and _norm(m.group(2)).startswith('interpretation') \
                and 'decision' in _norm(m.group(2)):
            start, level = i + 1, len(m.group(1))
            break
    if start is None:
        return Parsed()
    given: dict[str, list[list[str]]] = {}
    unread: list[str] = []
    current: list[str] | None = None
    base: int | None = None              # the indent of the first decision line

    def begin(key: str) -> list[str]:
        given.setdefault(key, []).append([])
        return given[key][-1]

    for line in lines[start:]:
        m = _HEADING_RE.match(line)
        if m and len(m.group(1)) <= level:
            break                       # the section ends at a heading as high as its own
        if m and level == 1 and len(m.group(1)) == 2 and _key_for(m.group(2)) is None:
            break                       # under an H1, the next `##` that names no decision
        if m:                           # a sub-heading names a decision, or ends one
            key = _key_for(m.group(2))
            current = begin(key) if key else None
            if key is None:
                unread.append(m.group(2).strip())
            continue
        if not line.strip():
            continue
        tm = _TABLE_RE.match(line)
        if tm and not set(tm.group('label')) <= set('-: '):
            key = _key_for(tm.group('label'))
            if key:
                begin(key).append(tm.group('value'))
                current = None
            continue
        lm = _LINE_RE.match(line)
        indent = len(lm.group('indent').expandtabs(4)) if lm else 0
        # a new decision: no deeper than the first decision line; before
        # one, an indented line under a sub-heading's decision is its text
        starts = lm and (indent <= base if base is not None
                         else indent == 0 or current is None)
        if starts:
            key = _key_for(lm.group('label'))
            if key is not None:
                base = indent if base is None else base
                current = begin(key)
                current.append(lm.group('value'))
                continue
            if current is None and re.match(r'\s*([-*+]|\d+[.)])\s', line):
                unread.append(lm.group('label').strip())
                continue
        if current is not None:
            current.append(line.strip())
    found: dict[str, str] = {}
    placeholders: dict[str, str] = {}
    for key, entries in given.items():
        for parts in entries:           # the last one written wins
            value = ' '.join(p for p in parts if p.strip()).strip()
            if not _clean(value):
                continue
            if _placeholder(value):
                placeholders[key] = _clean(value)
                found.pop(key, None)
            else:
                found[key] = value
                placeholders.pop(key, None)
    repeated = {k: len(v) for k, v in given.items() if len(v) > 1}
    return Parsed(True, found, placeholders, repeated, tuple(unread))


@dataclass(frozen=True)
class Decisions:
    """What `read_decisions` found: `found` (key → the author's text, each
    recorded decision), `problems` (a file that can't be read, a Mode that
    disagrees with storyforge.yaml), `notes` (said, never blocking: a
    decision given twice, a Mode that can't be compared), `placeholders`
    (key → the placeholder written in its place), `unread` (label-shaped
    lines naming no decision) and whether the heading was there. `missing`
    is the keys not in `found`, in `DECISIONS` order."""
    found: Mapping[str, str] = field(default_factory=dict)
    problems: tuple[str, ...] = ()
    has_section: bool = False
    notes: tuple[str, ...] = ()
    placeholders: Mapping[str, str] = field(default_factory=dict)
    unread: tuple[str, ...] = ()

    @property
    def missing(self) -> tuple[str, ...]:
        return tuple(k for k in _KEYS if k not in self.found)

    @property
    def ok(self) -> bool:
        return self.has_section and not self.missing and not self.problems

    def missing_labels(self) -> list[str]:
        return [_LABELS[k] for k in self.missing]

    def summary(self) -> str:
        """One line for status and `source status`."""
        if self.problems and (not self.missing or not self.has_section):
            return '; '.join(self.problems)
        if not self.has_section:
            return (f'reference/key-decisions.md has no `## {HEADING}` section (the '
                    f'decisions: {", ".join(label for _, label in DECISIONS)})')
        if self.missing:
            line = (f'{HEADING} in reference/key-decisions.md: '
                    f'{len(DECISIONS) - len(self.missing)} of {len(DECISIONS)} recorded; '
                    f'missing {", ".join(self.missing_labels())}')
            held = [f'{_LABELS[k]} is a placeholder ({v!r})'
                    for k, v in self.placeholders.items() if k in self.missing]
            if held:
                line += f' ({"; ".join(held)})'
            if self.unread:
                line += (f'; lines under the heading that name no decision: '
                         f'{", ".join(repr(u) for u in self.unread)} (the labels: '
                         f'{", ".join(label for _, label in DECISIONS)})')
            return '; '.join([line, *self.problems])
        return f'{HEADING}: all {len(DECISIONS)} recorded'


def read_decisions(project_dir: str, mode: str | None = None) -> Decisions:
    """The interpretation decisions in reference/key-decisions.md. `mode`
    is storyforge.yaml's `source.mode`: a Mode decision opening with
    another mode is a problem (the checks would read one, the author meant
    the other), and one opening with neither is a note (it can't be
    compared). A missing file is every decision missing; one that can't be
    read is a problem."""
    path = os.path.join(project_dir, KEY_DECISIONS)
    if not os.path.isfile(path):
        return Decisions()
    try:
        with open(path, encoding='utf-8') as f:
            text = f.read()
    except (OSError, UnicodeDecodeError) as e:
        return Decisions(problems=(f'reference/key-decisions.md can\'t be read: {e}',))
    parsed = parse_decisions(text)
    problems: list[str] = []
    notes = [f'{_LABELS[k]} is given {n} times in reference/key-decisions.md; the last '
             f'one written is used' for k, n in parsed.repeated.items()]
    said = _norm(parsed.found.get('mode', '')).split()[:1]
    if mode and said and said[0] in source.MODES and said[0] != mode:
        problems.append(f'the Mode interpretation decision says {said[0]}, but '
                        f'storyforge.yaml\'s source.mode is {mode} (the checks read the '
                        f'yaml): make them agree')
    elif mode and said and said[0] not in source.MODES:
        notes.append(f'the Mode interpretation decision doesn\'t open with faithful or free, '
                     f'so it isn\'t checked against storyforge.yaml\'s source.mode ({mode}), '
                     f'which the checks read')
    return Decisions(found=dict(parsed.found), problems=tuple(problems),
                     has_section=parsed.has_section, notes=tuple(notes),
                     placeholders=dict(parsed.placeholders), unread=parsed.unread)


@dataclass(frozen=True)
class Entry:
    """Where a `source:` book enters the ladder (see the module docstring).
    `problems` say why the upper rungs aren't given yet, one line each."""
    #: no spine or architecture of its own: it enters at the scene map
    enters_at_map: bool
    #: every source is imported (False when the block can't be read)
    imported: bool
    problems: tuple[str, ...] = ()
    #: None when the `source:` block can't be read
    decisions: Decisions | None = None
    #: storyforge.yaml's `source.mode` ('' when the block can't be read)
    mode: str = ''
    #: why the `source:` block can't be used ('' when it can)
    config_error: str = ''

    @property
    def ready(self) -> bool:
        """The upper rungs are given: the source imported and usable, the
        decisions recorded."""
        return not self.problems


def own_ladder(project_dir: str) -> bool:
    """Whether the book has a spine or architecture of its own: the full
    ladder, as an original climbs it."""
    from storyforge.status import artifact_present
    return any(artifact_present(project_dir, level) for level in OWN_LADDER_LEVELS)


def entry(project_dir: str) -> Entry | None:
    """None for a book without a `source:` block; otherwise its `Entry`.
    Never raises for what it can't read: a block, import or range that
    can't be used is a problem, and the rungs aren't given."""
    try:
        cfg = source.read_config(project_dir)
    except source.SourceError as e:
        why = f'storyforge.yaml\'s source: block can\'t be used: {e}'
        return Entry(enters_at_map=not own_ladder(project_dir), imported=False,
                     problems=(why,), config_error=why)
    if cfg is None:
        return None
    problems: list[str] = []
    imported = all(source.is_imported(project_dir, s) for s in cfg.slugs())
    if not imported:
        missing = [s for s in cfg.slugs() if not source.is_imported(project_dir, s)]
        problems.append(f'source {", ".join(missing)} not imported: run '
                        f'`storyforge source import`')
    else:
        try:
            source.require_imported(project_dir, cfg)   # a stale bible, a bad range
        except source.SourceError as e:
            problems.append(str(e))
    decisions = read_decisions(project_dir, cfg.mode)
    if not decisions.ok:
        problems.append(decisions.summary())
    return Entry(enters_at_map=not own_ladder(project_dir), imported=imported,
                 problems=tuple(problems), decisions=decisions, mode=cfg.mode)
