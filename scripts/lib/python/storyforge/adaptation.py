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
  ladder** (`Entry.higher` False). That is how an adaptation that strays far
  from its source builds its upper rungs itself, as an original does (plan
  decision 13), and how every adaptation built before #658 keeps its route;
- otherwise it enters at the scene map (`Entry.higher` True), and the upper
  rungs are given once the source is imported and the decisions are
  recorded (`Entry.ready`); `Entry.problems` says what is missing.

The decisions live under a heading `## Interpretation decisions` (any
level from `##` to `####`), one per labelled line (`- **Whose eyes:** ...`)
or sub-heading (`### Whose eyes`), as `DECISIONS` lists them. A label
with nothing after it, or only a placeholder in angle brackets, is not
recorded. A Mode whose first word is a mode (`faithful`, `free`) must
agree with `source.mode` in storyforge.yaml, which the checks read.
"""

from __future__ import annotations

import os
import re
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

# The words that name each decision, after `_norm` (lower case, letters
# and spaces only): the label, and the short forms an author writes
_ALIASES = {
    'about': ('what this version is about', 'what it is about', 'whats it about',
              'about', 'what its about'),
    'eyes': ('whose eyes', 'eyes', 'point of view', 'pov'),
    'cut': ('whats cut', 'what is cut', 'cut', 'cuts'),
    'invented': ('whats invented', 'what is invented', 'invented', 'inventions',
                 'invention'),
    'ending': ('where it ends', 'ending', 'the ending', 'where the book ends'),
    'mode': ('mode', 'the mode'),
}
_BY_ALIAS = {alias: key for key, aliases in _ALIASES.items() for alias in aliases}

_HEADING_RE = re.compile(r'^(#{1,6})\s+(.+?)\s*#*\s*$')
# `- **Label:** value`, `* Label: value`, `**Label**: value`, `Label: value`
_LINE_RE = re.compile(r'^\s*(?:[-*+]\s+)?(?:\*\*|__)?([^:*_]{1,60}?)(?:\*\*|__)?\s*:'
                      r'\s*(?:\*\*|__)?\s*(.*)$')
_PLACEHOLDER_RE = re.compile(r'^(<[^>]*>|\(?(tbd|todo|tk)\)?\.?|\.\.\.|…)$', re.I)


def _norm(text: str) -> str:
    text = text.lower().replace('’', '').replace("'", '')
    return ' '.join(re.sub(r'[^a-z ]+', ' ', text).split())


def _key_for(label: str) -> str | None:
    return _BY_ALIAS.get(_norm(label))


def _filled(value: str) -> bool:
    v = value.strip().strip('*_').strip()
    return bool(v) and not _PLACEHOLDER_RE.match(v)


@dataclass(frozen=True)
class Decisions:
    """What `read_decisions` found: `found` (key → the author's text, each
    recorded decision), `missing` (keys not recorded, in `DECISIONS`
    order), `problems` (a file that can't be read, a Mode that disagrees
    with storyforge.yaml) and whether the heading was there."""
    found: dict = field(default_factory=dict)
    missing: tuple = ()
    problems: tuple = ()
    has_section: bool = False

    @property
    def ok(self) -> bool:
        return self.has_section and not self.missing and not self.problems

    def missing_labels(self) -> list[str]:
        return [_LABELS[k] for k in self.missing]

    def summary(self) -> str:
        """One line for status and `source status`."""
        if self.problems:
            return '; '.join(self.problems)
        if not self.has_section:
            return (f'reference/key-decisions.md has no `## {HEADING}` section (the '
                    f'decisions: {", ".join(label for _, label in DECISIONS)})')
        if self.missing:
            return (f'{HEADING} in reference/key-decisions.md: '
                    f'{len(DECISIONS) - len(self.missing)} of {len(DECISIONS)} recorded; '
                    f'missing {", ".join(self.missing_labels())}')
        return f'{HEADING}: all {len(DECISIONS)} recorded'


def parse_decisions(text: str) -> tuple[bool, dict[str, str]]:
    """(whether the heading is there, key → text of each recorded decision)
    from key-decisions.md's text. A decision given twice keeps the first."""
    lines = text.splitlines()
    start = level = None
    for i, line in enumerate(lines):
        m = _HEADING_RE.match(line)
        if m and 2 <= len(m.group(1)) <= 4 and _norm(m.group(2)).startswith(
                _norm(HEADING).split()[0]) and 'decision' in _norm(m.group(2)):
            start, level = i + 1, len(m.group(1))
            break
    if start is None:
        return False, {}
    found: dict[str, list[str]] = {}
    current: str | None = None
    for line in lines[start:]:
        m = _HEADING_RE.match(line)
        if m and len(m.group(1)) <= level:
            break                       # the section ends at a heading as high as its own
        if m:                           # a sub-heading names a decision, or ends one
            current = _key_for(m.group(2))
            if current is not None and current in found:
                current = None          # given twice: the first stands
            elif current is not None:
                found[current] = []
            continue
        lm = _LINE_RE.match(line)
        key = _key_for(lm.group(1)) if lm else None
        if key is not None:
            current = None if key in found else key
            if current is not None:
                found[current] = [lm.group(2)]
            continue
        if current is not None and line.strip() and not line.lstrip().startswith('<!--'):
            found[current].append(line.strip())
    out = {k: ' '.join(v).strip() for k, v in found.items()}
    return True, {k: v for k, v in out.items() if _filled(v)}


def read_decisions(project_dir: str, mode: str | None = None) -> Decisions:
    """The interpretation decisions in reference/key-decisions.md. `mode`
    is storyforge.yaml's `source.mode`: a Mode decision opening with
    another mode is a problem (the checks would read one, the author meant
    the other). A missing file is every decision missing; one that can't
    be read is a problem."""
    path = os.path.join(project_dir, KEY_DECISIONS)
    keys = tuple(k for k, _ in DECISIONS)
    if not os.path.isfile(path):
        return Decisions(missing=keys)
    try:
        with open(path, encoding='utf-8') as f:
            text = f.read()
    except (OSError, UnicodeDecodeError) as e:
        return Decisions(missing=keys,
                         problems=(f'reference/key-decisions.md can\'t be read: {e}',))
    has, found = parse_decisions(text)
    problems: list[str] = []
    said = _norm(found.get('mode', '')).split()[:1]
    if mode and said and said[0] in source.MODES and said[0] != mode:
        problems.append(f'the Mode interpretation decision says {said[0]}, but '
                        f'storyforge.yaml\'s source.mode is {mode} (the checks read the '
                        f'yaml): make them agree')
    return Decisions(found=found, missing=tuple(k for k in keys if k not in found),
                     problems=tuple(problems), has_section=has)


@dataclass(frozen=True)
class Entry:
    """Where a `source:` book enters the ladder (see the module docstring).
    `higher`: it enters at the scene map (no spine or architecture of its
    own). `ready`: the upper rungs are given (the source imported and
    usable, the decisions recorded); `problems` say why not, one line each.
    `imported`: every source is imported (False when the block can't be
    read). `decisions` is None when the block can't be read."""
    higher: bool
    ready: bool
    imported: bool
    problems: tuple = ()
    decisions: Decisions | None = None
    mode: str = ''


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
        return Entry(higher=not own_ladder(project_dir), ready=False, imported=False,
                     problems=(f'storyforge.yaml\'s source: block can\'t be used: {e}',))
    if cfg is None:
        return None
    higher = not own_ladder(project_dir)
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
    return Entry(higher=higher, ready=not problems, imported=imported,
                 problems=tuple(problems), decisions=decisions, mode=cfg.mode)
