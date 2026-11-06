"""MICE thread entries: the one grammar of scene-intent.csv's ``mice_threads``
and of the ``reference/mice-threads.csv`` registry it names (#272).

An entry is ``[op][type:]name[note]``:

- op ``+`` opens the thread, ``-`` closes it, none mentions it (F-020; what
  ``elaborate --stage mice-fill`` writes);
- ``type`` (milieu, inquiry, character, event) is optional: the registry
  holds it;
- a bracketed ``[note]`` after the name is an older revision pass's habit.
  It is parsed so its colon is not read as a type, and validation reports it.

Every reader (validate, dormancy, structural checks, MICE health, cleanup,
hone, audit, the prior-prose window, the source bible) goes through
:func:`resolve`, so they agree on what an entry means. This module imports
nothing from storyforge but ``common``.
"""

from __future__ import annotations

import enum
import os
import re
from typing import Mapping, NamedTuple

#: Valid MICE thread types
VALID_TYPES = frozenset({'milieu', 'inquiry', 'character', 'event'})

REGISTRY_FILE = 'mice-threads.csv'


class Kind(str, enum.Enum):
    """What an entry does to its thread; the value is its operator."""
    OPEN = '+'
    CLOSE = '-'
    MENTION = ''


class Entry(NamedTuple):
    """One mice_threads entry as written."""
    kind: Kind
    type: str   # lower-cased; '' when the entry carries none
    name: str   # as written; '' for a bare operator or an empty name
    note: str   # a trailing ``[note]``, '' when none
    raw: str    # the entry, stripped
    typed: bool  # a ``type:`` separator was written (even with an empty side)

    def write(self, name: str) -> str:
        """The entry with its thread renamed, operator and note kept."""
        return f'{self.kind.value}{name}{self.note}'


# The model sometimes joins entries with commas despite the prompt
# (`+a,+b`). A comma separates entries only when an operation or a type
# follows it, so a comma inside a free-text name stays put.
_SEPARATOR_RE = re.compile(
    r';|,(?=\s*(?:[+-]|(?:milieu|inquiry|character|event)\s*:))', re.IGNORECASE)
_NOTE_RE = re.compile(r'^(.*?)(\[[^\]]*\])$', re.DOTALL)
_SLUG_RE = re.compile(r"[\w][\w'.-]*")


def split(value: str | None) -> list[str]:
    """A mice_threads value's raw entries (unstripped; empties kept)."""
    return _SEPARATOR_RE.split(value or '')


def parse(text: str) -> Entry:
    """``+inquiry:who-killed`` → ``Entry(Kind.OPEN, 'inquiry', 'who-killed', '', ...)``."""
    raw = (text or '').strip()
    body, note = raw, ''
    m = _NOTE_RE.match(body)
    if m:
        body, note = m.group(1).strip(), m.group(2)
    kind = Kind.MENTION
    if body[:1] in (Kind.OPEN.value, Kind.CLOSE.value):
        kind, body = Kind(body[0]), body[1:]
    type_part, sep, name = body.partition(':')
    if not sep:
        return Entry(kind, '', body.strip(), note, raw, False)
    return Entry(kind, type_part.strip().lower(), name.strip(), note, raw, True)


def entries(value: str | None) -> list[Entry]:
    """The non-empty entries of a mice_threads value, parsed."""
    return [parse(t) for t in split(value) if t.strip()]


# ============================================================================
# The registry
# ============================================================================

class Registry(NamedTuple):
    """reference/mice-threads.csv, indexed for lookup.

    ``lookup`` maps a lower-cased key to the one thread it names: each
    thread's id, name and aliases, the bare name of an id that keeps its
    type (``inquiry:x`` → ``x``), and every one of those prefixed with the
    thread's registered type (``inquiry:<key>``), so a typed entry can name
    a thread whose bare name is shared. A key two threads share is in
    ``ambiguous`` instead, never in ``lookup``: no reader picks one.
    """
    path: str
    present: bool                    # the file exists
    lookup: dict[str, str]           # lower-cased key -> canonical id
    types: dict[str, str]            # canonical id -> registered type
    names: dict[str, str]            # canonical id -> display name
    ambiguous: dict[str, list[str]]  # lower-cased key -> the ids sharing it
    problems: list[str]              # what is wrong with the file itself

    @property
    def checked(self) -> bool:
        """Names are checked against it (it has at least one thread)."""
        return bool(self.names)

    def findings(self) -> list[str]:
        """Every registry problem, collisions included, one line each."""
        out = list(self.problems)
        for key, ids in sorted(self.ambiguous.items()):
            out.append(f'"{key}" names more than one thread in {REGISTRY_FILE} '
                       f'({", ".join(ids)}); an entry using it is not read as '
                       f'either. Give each thread its own name, or write type:name')
        return out

    def mention_for(self, thread: str) -> str:
        """The shortest key that names ``thread`` and no other: what to
        write for a mention of it. '' when there is none."""
        candidates = [thread]
        if ':' in thread:
            candidates.insert(0, thread.split(':', 1)[1])
        if self.types.get(thread):
            candidates.append(f'{self.types[thread]}:{thread.split(":", 1)[-1]}')
        for key in candidates:
            if self.lookup.get(key.lower()) == thread:
                return key
        return ''


def _add(index: dict[str, set[str]], key: str, canonical: str) -> None:
    key = key.strip().lower()
    if key:
        index.setdefault(key, set()).add(canonical)


def registry_from_rows(rows: list[Mapping[str, str]], path: str = '',
                       present: bool = True,
                       problems: list[str] | None = None) -> Registry:
    """A :class:`Registry` from registry rows (dicts with id, name, type,
    aliases; a row with neither id nor name is skipped)."""
    index: dict[str, set[str]] = {}
    types: dict[str, str] = {}
    names: dict[str, str] = {}
    for row in rows:
        name = (row.get('name') or '').strip()
        canonical = (row.get('id') or '').strip() or name
        if not canonical:
            continue
        names[canonical] = name or canonical
        rtype = (row.get('type') or '').strip().lower()
        if rtype:
            types[canonical] = rtype
        keys = [canonical, name]
        # An older registry id carries its type (`inquiry:who-killed`); scene
        # entries, and mice-fill's mentions, use the bare name
        type_part, sep, bare = canonical.partition(':')
        if sep and type_part.strip().lower() in VALID_TYPES:
            keys.append(bare)
        keys += [a for a in (row.get('aliases') or '').split(';')]
        for key in keys:
            if key.strip():
                _add(index, key, canonical)
                if rtype and not key.lower().startswith(f'{rtype}:'):
                    _add(index, f'{rtype}:{key}', canonical)
    lookup = {k: next(iter(ids)) for k, ids in index.items() if len(ids) == 1}
    ambiguous = {k: sorted(ids) for k, ids in index.items() if len(ids) > 1
                 # `inquiry:x` when two inquiry threads share x is the same
                 # collision as `x`: report it once
                 and not (':' in k and k.split(':', 1)[1] in index
                          and len(index[k.split(':', 1)[1]]) > 1)}
    return Registry(path, present, lookup, types, names, ambiguous, list(problems or []))


def load_registry(path: str) -> Registry:
    """The registry at ``path`` (a missing file gives an empty, absent one).

    A file with no ``name`` column is read by its ids, and says so in
    ``problems``; with neither ``id`` nor ``name`` no thread is read.
    """
    if not path or not os.path.isfile(path):
        return Registry(path or '', False, {}, {}, {}, {}, [])
    with open(path, newline='', encoding='utf-8-sig') as f:
        lines = [l for l in f.read().replace('\r\n', '\n').replace('\r', '').split('\n')
                 if l.strip()]
    if not lines:
        return Registry(path, True, {}, {}, {}, {}, [f'{REGISTRY_FILE} is empty'])
    header = [h.strip() for h in lines[0].split('|')]
    problems = []
    if 'name' not in header and 'id' not in header:
        return Registry(path, True, {}, {}, {}, {}, [
            f'{REGISTRY_FILE} has neither an id nor a name column; no thread '
            f'names can be checked'])
    if 'name' not in header:
        problems.append(f'{REGISTRY_FILE} has no name column; threads are '
                        f'matched by id and aliases only')
    rows = [dict(zip(header, line.split('|'))) for line in lines[1:]]
    return registry_from_rows(rows, path, True, problems)


def registry_for(ref_dir: str) -> Registry:
    """The registry in a reference directory."""
    return load_registry(os.path.join(ref_dir, REGISTRY_FILE)) if ref_dir else \
        Registry('', False, {}, {}, {}, {}, [])


def lookup_thread(lookup: Mapping[str, str], entry: Entry) -> str:
    """The canonical thread ``entry`` names in ``lookup``: its full
    ``type:name`` first, then its name. '' when neither is there."""
    if entry.type and entry.name:
        found = lookup.get(f'{entry.type}:{entry.name}'.lower())
        if found:
            return found
    return lookup.get(entry.name.lower(), '') if entry.name else ''


# ============================================================================
# Reading an entry
# ============================================================================

class Resolved(NamedTuple):
    """An entry read against the registry."""
    entry: Entry
    thread: str    # canonical id; a lower-cased slug for a name the registry
                   # lacks; '' when the entry names no thread at all
    type: str      # the registry's type, else the entry's, else ''
    problem: str   # '' for a valid entry, else why validation rejects it

    @property
    def kind(self) -> Kind:
        return self.entry.kind

    @property
    def valid(self) -> bool:
        return not self.problem


def check(text: str, registry: Registry) -> Resolved:
    """Read one entry: which thread it names, and what (if anything) is
    wrong with it. The rules validate reports (``schema._check_mice``) and
    every reader counts by.
    """
    e = parse(text)

    def bad(problem: str, thread: str = '') -> Resolved:
        return Resolved(e, thread, registry.types.get(thread) or e.type, problem)

    body = e.raw[1:] if e.kind is not Kind.MENTION else e.raw
    if not body.strip():
        return bad('invalid format (expected +name, -name or name)')
    if e.typed:
        if not e.type or not e.name:
            return bad('missing type or name')
        if e.type not in VALID_TYPES:
            return bad(f'invalid type "{e.type}" (expected: milieu, inquiry, character, event)')
    if not e.name:
        return bad('empty thread name')
    if e.note:
        thread = lookup_thread(registry.lookup, e) if registry.checked else ''
        return bad(f'note "{e.note}" after the thread name: an entry is only '
                   f'+name, -name or name', thread)
    if registry.checked:
        thread = lookup_thread(registry.lookup, e)
        if not thread:
            keys = [k for k in (f'{e.type}:{e.name}'.lower() if e.type else '',
                                e.name.lower()) if k in registry.ambiguous]
            if keys:
                ids = registry.ambiguous[keys[0]]
                return bad(f'thread name "{e.name}" is ambiguous in {REGISTRY_FILE} '
                           f'({", ".join(ids)}); write type:name or rename one')
            if not _SLUG_RE.fullmatch(e.name):
                return bad('thread name is not a slug')
            return bad(f'thread name "{e.name}" not in {REGISTRY_FILE}', e.name.lower())
        expected = registry.types.get(thread)
        if e.type and expected and e.type != expected:
            return bad(f'type "{e.type}" doesn\'t match registered type "{expected}"', thread)
        return Resolved(e, thread, expected or e.type, '')
    # No registry to check against: a slug names a thread; prose
    # ("gatsby dream opens", "+ +x") does not
    if not _SLUG_RE.fullmatch(e.name):
        return bad('thread name is not a slug')
    return Resolved(e, e.name.lower(), e.type, '')


def resolve(value: str | None, registry: Registry) -> list[Resolved]:
    """Every non-empty entry of a mice_threads value, read by :func:`check`.

    Readers filter: ``r.valid`` for the entries validate accepts (dormancy,
    mice-fill), ``r.thread`` for any well-formed slug, registered or not
    (structural checks, which follow an unregistered thread while validate
    reports its name). Entries a reader leaves out must be reported by it.
    """
    return [check(t, registry) for t in split(value) if t.strip()]


def span_gaps(touches: Mapping[int, set[Kind]]) -> list[tuple[int, int]]:
    """Consecutive positions of a thread's scenes that lie inside its
    open..close span.

    ``touches`` maps the reading-order position of each scene that carries
    the thread to the kinds of entry there. A thread is not dormant before
    it opens or after it closes: a mention outside the span (foreshadowing
    before the open, an echo after the close) is valid and not reported,
    but the stretch between it and the span is no gap to fill. With no open
    the span starts at the first scene; with no close it runs to the last.
    A close before the open leaves no span (``misordered`` reports it).
    """
    positions = sorted(touches)
    if not positions:
        return []
    opens = [i for i in positions if Kind.OPEN in touches[i]]
    closes = [i for i in positions if Kind.CLOSE in touches[i]]
    start = opens[0] if opens else positions[0]
    end = closes[-1] if closes else positions[-1]
    return [(a, b) for a, b in zip(positions, positions[1:]) if a >= start and b <= end]


def misordered(touches: Mapping[int, set[Kind]]) -> tuple[int, int] | None:
    """``(close, open)`` positions when a thread closes before it first
    opens and never closes after that open; None otherwise."""
    opens = sorted(i for i, k in touches.items() if Kind.OPEN in k)
    closes = sorted(i for i, k in touches.items() if Kind.CLOSE in k)
    if opens and closes and closes[0] < opens[0] and closes[-1] < opens[0]:
        return closes[0], opens[0]
    return None
