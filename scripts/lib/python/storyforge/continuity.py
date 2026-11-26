"""Deterministic continuity checks over typed state (#648, plan A2).

Models read, code checks. Each scene's typed records (`storyforge.typed_state`)
are compared with every other scene's, the ledger, the briefs, scenes.csv's
calendar and the world table, free and the same every run:

- **life** (PHY): a dead character present, acting or spoken to as present,
  later in the story's present. Deaths come from `alive` records and
  characters.csv's `death_scene`. A death and a presence bind one
  characters.csv character (`Book.person`, #733): a description ("the boy") or
  a name several characters share ("Pisander") binds none, and a presence
  it would have matched is a note. A presence in the paragraph of the
  death, after it, is the death itself (the dying man's heels, his name
  said). A scene off the present (scenes.csv `time_mode` frame, vision,
  memory, dream or ghost: `elaborate.off_present`) is exempt, and so is a
  flashback, whose `timeline_day` comes before the death. An unmarked
  scene is reported, never assumed to be a memory.
- **possession** (PHY): within a scene, an object in two people's hands
  with nothing between; in any scene, an object held or taken whole after
  it was destroyed (a holder's unowned "spear" taken after theirs broke is
  another spear), or held again by the person who gave it away or lost
  it (across scenes, only a name with an owner), unless a fact between
  moves it to someone else (`gets`). An object
  in other hands than an earlier scene left it is a note (an offstage
  handover is ordinary). A name without an owner ("shield", "the round
  shield") is its holder's own object, a name with one ("Teucer's bow")
  the owner's (`object_id`, #732). A current stage sheet's hands (#647)
  count for the kinds of object tracked, placed by their quotes on the
  prose's scale.
- **knowledge** (KNO): the POV character acts on, says or thinks a fact
  before a scene or brief shows them learning it (`knows learns`, the
  briefs' `knowledge_in`/`knowledge_out` for their POV). The ledger's
  `known_by` says who knows a fact, not when, so a fact it alone places
  later, or one never shown learned, is a note.
- **travel** (WLD): a person further from where the story last had them
  than world.csv's fastest `speed` allows in the days between (a time of
  day is a slot: at least `SLOT_DAYS`), places matched through
  locations.csv and distances from world.csv. Two places in one morning
  are ordinary unless they are too far apart.
- **time** (TIM): an elapsed-time phrase ("three days ago", "the tenth
  day", "in twelve days") against the calendar: the days between this
  scene and the scene of the counted event, back for one labelled `before`,
  forward for one labelled `after` (a promise or plan is measured to the
  scene where it happens, never as time passed, #713) (`parse_elapsed`, a
  small parser that says what it can't read rather than guessing: a
  compound, a bound and an estimate are read whole, a range or two counts
  not at all).
- **injury** (PHY): a body part used at full strength while a serious or
  disabling injury to it is current. A serious one is current through its
  own scene, and after it only when that scene shows it lasting (an
  `impaired` use of the part starting after the injury's words, #733), then
  until `SERIOUS_DAYS` pass with no scene showing it again; a disabling
  one until healed.
- **names** (WLD): a name the book rules out appears: an adaptation's name
  map's replaced source names (`source.NameMap.changed`) and the author's
  `continuity.forbidden_names` in storyforge.yaml. A name no registry,
  ledger subject or name map knows is advisory (a NOTE).
- **geography and sky** (WLD): a short phrase list ("the sun went down
  behind Ida") checked against world.csv's directions; free, no model.

Every finding is a `checker.Finding` with the scene's own words, verified;
a record whose quote isn't in its scene makes none. Whatever couldn't be
checked is a note (`ContinuityResult.notes`): silence means checked and
clean. A scene before this one in story order whose typed state wasn't read
(`Book.gaps`) turns a finding it could explain (a `gets`, a `learns`, a
`healed` there) into a note. Cut and merged scenes don't count. The gate
runs this on every scene it checks (`gate.GATE_CONTINUITY`): its findings
join the check's and block like any continuity error.
"""

from __future__ import annotations

import dataclasses
import os
import re
from dataclasses import dataclass, field
from typing import Literal, NamedTuple

from storyforge.checker import CALENDAR, Finding
from storyforge.quotes import normalize, quote_in
from storyforge.typed_state import (END, MAX_OFFERED_FACTS, MAX_OFFERED_INJURIES,
                                    MAX_OFFERED_OBJECTS, START, Record, object_kind, part_key,
                                    prose_offset)

#: The block and key in storyforge.yaml holding names the book rules out,
#: `;`-separated (`continuity:` / `  forbidden_names: Jupiter; Juno`)
FORBIDDEN_BLOCK, FORBIDDEN_KEY = 'continuity', 'forbidden_names'
#: A serious injury its scene shows lasting stays current this many story
#: days past the last scene that shows it (the injury, or an `impaired` use
#: of the part), unless a `healed` record ends it sooner; one its scene
#: doesn't show lasting ends with that scene, and a disabling one lasts
#: until healed (#733: a wound a fight shows for a moment is not carried)
SERIOUS_DAYS = 7
#: Where in its day each time of day falls, for travel
_DAY_FRACTION = {'dawn': 0.2, 'morning': 0.35, 'afternoon': 0.6, 'evening': 0.75,
                 'dusk': 0.8, 'night': 0.9}
#: The least time a move between two scenes is allowed: a time of day is a
#: slot, not an instant, so two scenes in one morning may be hours apart
#: (#648's review, CR-2)
SLOT_DAYS = 0.25
#: Codes by check
CODES = {'life': 'PHY', 'possession': 'PHY', 'knowledge': 'KNO',
         'travel': 'WLD', 'time': 'TIM', 'injury': 'PHY', 'names': 'WLD', 'sky': 'WLD'}


class ContinuityError(RuntimeError):
    """The continuity check could not run; the message says why."""


@dataclass
class ContinuityResult:
    scene_id: str
    findings: list[Finding] = field(default_factory=list)
    #: what couldn't be checked, and why; and advisory names (never blocking)
    notes: list[str] = field(default_factory=list)
    records: list[Record] = field(default_factory=list)
    #: whether this run read the records (a call) or reused the scene's file
    extracted: bool = False


# ============================================================================
# The book the checks read
# ============================================================================

@dataclass(frozen=True)
class CharacterId:
    """One characters.csv character (#733): its id exactly as the registry
    writes it. Built only by `Book.person`, the one rule that binds a name
    to a character."""
    id: str

    def __post_init__(self):
        if not self.id or self.id != self.id.strip():
            raise ValueError(f'a character id must be non-empty and trimmed: {self.id!r}')

    def __str__(self) -> str:
        return self.id


def _norm_name(name: str) -> str:
    return ' '.join((name or '').split()).lower()


@dataclass
class Book:
    scene_id: str
    order: dict[str, int]
    scenes: dict[str, dict]
    #: scene → its records (current prose only), this scene's included
    records: dict[str, list[Record]] = field(default_factory=dict)
    deaths: list[Record] = field(default_factory=list)
    #: lower-case name, alias or id → canonical character id
    chars: dict[str, str] = field(default_factory=dict)
    #: lower-case name or alias characters.csv gives more than one character
    #: → their ids (`namesakes`): it binds none of them (`character`)
    namesakes: dict[str, tuple[str, ...]] = field(default_factory=dict)
    places: dict[str, str] = field(default_factory=dict)
    place_names: dict[str, str] = field(default_factory=dict)
    world: object = None
    rows: list[dict] = field(default_factory=list)
    briefs: dict[str, dict] = field(default_factory=dict)
    #: scenes.csv has a `time_mode` column (without one every scene is the present)
    has_time_mode: bool = False
    #: forbidden name → where it is ruled out (a file name)
    forbidden: dict[str, str] = field(default_factory=dict)
    #: lower-case names a person may be called by; None: no registry
    known_names: set[str] | None = None
    #: lower-case names characters.csv gives (ids, names, aliases); None: no
    #: registry. A forbidden name here isn't checked
    registry_names: set[str] | None = None
    #: other scenes with prose whose typed state couldn't be read (none yet,
    #: or of earlier prose): what they say is unknown (`gap_before`)
    gaps: set[str] = field(default_factory=set)
    key: dict[str, tuple] = field(default_factory=dict)
    #: lower-case characters.csv id → the id (`registry_ids`); without one,
    #: `chars`' canonical values (a name shared with another row's id can
    #: hide that id there, so `load_book` reads them from the rows)
    ids: dict[str, str] = field(default_factory=dict)

    def __post_init__(self):
        if not self.ids:
            self.ids = {v.lower(): v for v in self.chars.values() if v}
        last = -10 ** 9
        for sid in sorted(self.order, key=self.order.get):
            day = self.day(sid)
            if day is not None:
                last = day
            self.key[sid] = (day if day is not None else last, self.order[sid])

    def row(self, sid: str) -> dict:
        return self.scenes.get(sid, {})

    def day(self, sid: str) -> int | None:
        try:
            return int((self.row(sid).get('timeline_day') or '').strip())
        except ValueError:
            return None

    def time(self, sid: str) -> str:
        from storyforge.schema import TIMES_OF_DAY
        t = (self.row(sid).get('time_of_day') or '').strip().lower()
        return t if t in TIMES_OF_DAY else ''

    def off_present(self, sid: str) -> bool:
        from storyforge.elaborate import off_present
        return off_present(self.row(sid))

    def before(self, a: tuple[str, int], b: tuple[str, int]) -> bool:
        """Whether (scene, index) `a` comes before `b` in story time: by
        `timeline_day` (a flashback keeps its earlier day), a scene with no
        day taking the last day before it in reading order, then by reading
        order, then within a scene by index."""
        if a[0] == b[0]:
            return a[1] < b[1]
        return self.key.get(a[0], (0, 0)) < self.key.get(b[0], (0, 0))

    def person(self, name: str, *, by_id: bool = False) -> CharacterId | None:
        """The one characters.csv character `name` binds, the one identity
        rule for people (#733). `by_id` (a registry record, whose `who` is
        its row's id): that id exactly, whatever names share its spelling.
        A name as the prose writes it: a characters.csv id or a name or
        alias only one character has; None for one several characters share
        (`namesakes`, even when one of them has it as an id: "Dolops" in the
        prose may be either Dolops) or one the registry doesn't give (a
        description, "the boy")."""
        n = _norm_name(name)
        if by_id:
            return CharacterId(self.ids[n]) if n in self.ids else None
        if not n or n in self.namesakes:
            return None
        if n in self.ids:
            return CharacterId(self.ids[n])
        return CharacterId(self.chars[n]) if n in self.chars else None

    def bind(self, r: Record) -> CharacterId | None:
        """The character a record names (`person`; a registry record by its
        id)."""
        return self.person(r.who, by_id=r.origin == 'registry')

    def shared(self, name: str) -> bool:
        """Whether `name` is one several characters share (`namesakes`)."""
        return _norm_name(name) in self.namesakes

    def who(self, name: str) -> str:
        """A key for whoever `name` names: the character's id (`person`),
        else the name itself, lower case (a place, someone the registry
        doesn't list, or a name several characters share, which then keys
        none of them)."""
        p = self.person(name)
        return str(p) if p else _norm_name(name)

    def is_person(self, name: str) -> bool:
        """Whether characters.csv gives `name` (as an id, name or alias)."""
        return _norm_name(name) in self.chars

    def place(self, name: str) -> str:
        n = ' '.join((name or '').split()).lower()
        n = re.sub(r'^(?:the|a|an)\s+', '', n)
        return self.places.get(n) or self.places.get(f'the {n}', '')

    def present_records(self, kinds: tuple[str, ...]) -> list[Record]:
        """Every verified record of `kinds` in a present-time scene, in story order."""
        out = [r for sid, recs in self.records.items() if not self.off_present(sid)
               for r in recs if r.type in kinds and r.verified]
        return sorted(out, key=lambda r: (self.key.get(r.scene_id, (0, 0)), r.index))

    def gap_between(self, a: str, b: str) -> list[str]:
        """The scenes in `gaps` that come after scene `a` and before scene
        `b` in story order (`a` '' for the book's start), present-time ones
        only: a fact there (a `gets`, a `learns`, a `healed`) is unknown."""
        lo = self.key.get(a) if a else None
        hi = self.key.get(b, (0, 0))
        return sorted((g for g in self.gaps if not self.off_present(g) and g in self.key
                       and (lo is None or lo < self.key[g]) and self.key[g] < hi),
                      key=self.key.get)

    def pov(self, sid: str) -> str:
        return (self.row(sid).get('pov') or '').strip()


def _finding(check: str, quote: str, established_scene: str, established_quote: str,
             why: str, fact_id: str = '') -> Finding:
    return Finding(kind='contradiction', code=CODES[check], scene_quote=quote,
                   established_scene=established_scene, established_quote=established_quote,
                   fact_id=fact_id, explanation=f'(typed state, {check}) {why}')


def _where(book: Book, sid: str) -> str:
    from storyforge.prompts import scene_when
    when = scene_when(book.row(sid))
    return f'{sid} ({when})' if when else sid


# ============================================================================
# Life and death
# ============================================================================

def namesakes(rows: list[dict]) -> dict[str, tuple[str, ...]]:
    """The names and aliases characters.csv gives more than one character
    (lower case), each with their ids: Homer's two Pisanders are two ids
    under one name."""
    ids: dict[str, set[str]] = {}
    for row in rows:
        cid = (row.get('id') or row.get('name') or '').strip()
        if not cid:
            continue
        for n in [row.get('name') or ''] + (row.get('aliases') or '').split(';'):
            n = ' '.join(n.split()).lower()
            if n:
                ids.setdefault(n, set()).add(cid)
    return {n: tuple(sorted(c)) for n, c in ids.items() if len(c) > 1}


def registry_ids(rows: list[dict]) -> dict[str, str]:
    """characters.csv's ids (lower case → the id), for each row with a name
    (`enrich.load_alias_map`'s rows: a row with no name binds no one). An id
    spelled like another row's name (`dolops`, and the other Dolops) is
    still an id, which the name map alone would hide."""
    out = {}
    for row in rows:
        cid = (row.get('id') or row.get('name') or '').strip()
        if cid and (row.get('name') or '').strip():
            out[cid.lower()] = cid
    return out


def paragraph_starts(prose: str) -> list[int]:
    """Where each paragraph (blank-line separated) begins in the normalized
    prose, the scale `place_in_prose` places records on."""
    starts, pos = [], 0
    for para in re.split(r'\n[ \t]*\n', prose or ''):
        text = normalize(para)
        if text:
            starts.append(pos)
            pos += len(text) + 1
    return starts


def _paragraph(starts: list[int], r: Record) -> int:
    from bisect import bisect_right
    return bisect_right(starts, prose_offset(r.index)) - 1


def check_life(book: Book, prose: str = '') -> tuple[list[Finding], list[str]]:
    """PHY: a person this scene puts present (`at`) after their death in
    story order (`alive dead` records, characters.csv's `death_scene`) with
    no `alive alive` between. Both bind one character (`Book.person`,
    #733). Notes, never silence: a presence by a name that binds no one
    while a death names it or a namesake of it, a presence binding a
    namesake of a death recorded by the shared name, no usable registry,
    and (with `prose`) a presence after a death in its paragraph of this
    scene, read as the death itself. Exempt: an off-present scene, and a
    death in one."""
    sid = book.scene_id
    if book.off_present(sid):
        return [], []
    events = [(e, book.bind(e)) for e in book.present_records(('alive',)) + [
        d for d in book.deaths if not book.off_present(d.scene_id)]]
    here = [r for r in book.records.get(sid, []) if r.type == 'at' and r.verified]
    if not book.ids and here and events:
        return [], ['life: no usable characters.csv (missing, or without a name column), so '
                    'no death binds a character: not checked']
    unbound = {_norm_name(e.who) for e, cid in events if cid is None and e.value == 'dead'}
    dead_ids = {cid for e, cid in events if cid and e.value == 'dead'}
    starts = paragraph_starts(prose) if prose else []
    findings, unmatched, namesake, dying = [], [], [], []
    seen: set[CharacterId] = set()
    for r in here:
        who = book.person(r.who)
        if who is None:
            name = _norm_name(r.who)
            if name in unbound or any(CharacterId(i) in dead_ids
                                      for i in book.namesakes.get(name, ())):
                unmatched.append(r.who)
            continue
        if who in seen:
            continue
        if any(str(who) in book.namesakes.get(n, ()) for n in unbound):
            namesake.append(r.who)
        mine = [e for e, cid in events if cid == who
                and book.before((e.scene_id, e.index), (sid, r.index))]
        deaths = [e for e in mine if e.value == 'dead']
        death = next((d for d in deaths if not any(
            e.value == 'alive' and book.before((d.scene_id, d.index), (e.scene_id, e.index))
            for e in mine)), None)
        if death is None:
            continue
        # a registry death stands at END, after everything in its scene, so
        # only a prose death can share a paragraph with a presence
        if (starts and death.scene_id == sid and death.origin == 'prose'
                and _paragraph(starts, death) == _paragraph(starts, r)):
            dying.append(r.who)
            continue   # the dying itself: the heels drumming, the name said (#733)
        seen.add(who)
        where = 'earlier in this scene' if death.scene_id == sid else _where(book, death.scene_id)
        hint = ('; if this scene is a memory, dream, vision or ghost scene, set its '
                'time_mode in scenes.csv' + ('' if book.has_time_mode else
                                             ' (scenes.csv has no time_mode column: every '
                                             'scene is read as the present)'))
        if death.origin == 'registry':
            findings.append(_finding('life', r.quote, 'characters.csv', death.quote,
                                     f'{r.who} is present here, but characters.csv gives '
                                     f'{who} death_scene {death.scene_id}{hint}'))
        else:
            findings.append(_finding('life', r.quote, death.scene_id, death.quote,
                                     f'{r.who} is present here, but died {where}{hint}'))

    def names(xs):
        return ', '.join(sorted(set(xs), key=str.lower)[:5])
    notes = []
    if unmatched:
        notes.append(f'life: {len(unmatched)} presence record(s) by a name that binds no one '
                     f'character in characters.csv (a description, or a name several share) '
                     f'while a death names it or a namesake, not compared: {names(unmatched)}')
    if namesake:
        notes.append(f'life: {len(namesake)} presence record(s) of a character whose name a '
                     f'death was recorded under, a name several characters share, so which '
                     f'one died is unknown, not compared: {names(namesake)}')
    if dying:
        notes.append(f'life: {len(dying)} presence record(s) after a death in the same '
                     f'paragraph of this scene, read as the death itself: {names(dying)}')
    return findings, notes


# ============================================================================
# Possession
# ============================================================================

@dataclass(frozen=True)
class ObjectRef:
    """What an object's name says by itself (`object_ref`): `owner`, the
    canonical id of the person a possessive names ("Teucer's bow"; '' for
    none), and `name`, the rest, lower case, without articles, possessive
    pronouns or "own"."""
    owner: str
    name: str

    @property
    def kind(self) -> str:
        return object_kind(self.name)

    def same(self, other: 'ObjectRef') -> bool:
        """Whether the two names can be one object: no two different owners,
        and `same_name`."""
        return not (self.owner and other.owner and self.owner != other.owner) and \
            same_name(self.name, other.name)


@dataclass(frozen=True)
class ObjectId:
    """One tracked object (#732): an owner and a name. `owner` is the person
    a possessive names, else the holder the object was first read with (a
    person, or a place it lay at); `scope` says which (`owned`, `holder`),
    and isn't part of the identity: Hector's "his shield" is "Hector's
    shield"."""
    owner: str
    name: str
    scope: str = field(default='holder', compare=False)

    @property
    def kind(self) -> str:
        return object_kind(self.name)

    def __str__(self) -> str:
        return f'{self.owner}\'s {self.name}'


def same_name(a: str, b: str) -> bool:
    """Two names for one kind of thing: the same head noun (`object_kind`),
    and one's words all in the other's ("brass key", "the small brass key";
    not "shield" and "shield strap")."""
    if not a or not b or object_kind(a) != object_kind(b):
        return False
    x, y = set(a.split()), set(b.split())
    return x <= y or y <= x


#: An object's state in the possession fold
Status = Literal['held', 'given', 'lost', 'destroyed', 'unknown']


@dataclass(frozen=True)
class Holding:
    """Where an object stands after a record: `held` by `holder` (canonical
    id, or a place); `given`, `lost` or `destroyed` `by` someone; or
    `unknown` (after a misquoted record). `rec` is the record that set it
    (for a handover, its recipient's name in `who`). Built with the named
    constructors, which keep the fields to their status."""
    status: Status
    rec: Record
    holder: str = ''
    by: str = ''

    def __post_init__(self):
        if (self.status == 'held') != bool(self.holder) or (
                self.status == 'unknown' and self.by):
            raise ValueError(f'a {self.status} holding with holder {self.holder!r} '
                             f'and by {self.by!r}')

    @classmethod
    def held(cls, holder: str, rec: Record, by: str = '') -> 'Holding':
        return cls('held', rec, holder=holder, by=by)

    @classmethod
    def gone(cls, status: Status, by: str, rec: Record) -> 'Holding':
        if status not in ('given', 'lost', 'destroyed'):
            raise ValueError(f'{status} is not a way to part with an object')
        return cls(status, rec, by=by)

    @classmethod
    def unknown(cls, rec: Record) -> 'Holding':
        return cls('unknown', rec)


def object_ref(book: Book, item: str) -> ObjectRef:
    """What `item` names by itself: the owner a possessive names (a person
    in characters.csv, a name of one or more words: "Achilles' armour",
    "Oren Tal's knife") and the rest of the name. A possessive naming no
    one ("the king's ring") stays part of the name."""
    from storyforge.stage_sheet import _ARTICLES
    raw = re.findall(r"[\w']+", (item or '').lower())
    for n, w in enumerate(raw):
        if not w.endswith(("'s", "'")):
            continue
        stem = w[:-2] if w.endswith("'s") else w[:-1]
        before = [x for x in raw[:n] if x not in _ARTICLES]
        for cand in (' '.join(before + [stem]), stem):
            if cand and book.is_person(cand):
                rest = [x.strip("'") for x in raw[n + 1:] if x not in _ARTICLES]
                return ObjectRef(book.who(cand), ' '.join(x for x in rest if x))
        break
    words = [w[:-2] if w.endswith("'s") else w.strip("'") for w in raw]
    return ObjectRef('', ' '.join(w for w in words if w and w not in _ARTICLES))


def object_id(book: Book, state: dict, r: Record) -> ObjectId | None:
    """The object a `holds` record names, given the fold's `state` so far
    ({} for none): the one identity rule, used by the fold, the handover
    pairing (`object_ref`), the names offered to extraction and the stage
    sheet's hands (`tracked_objects`, `ObjectId.kind`). None: a record with
    neither an owner nor a holder.

    A name with an owner is that person's ("Teucer's bow" is Teucer's,
    whoever holds it; "Oren's old sword" is the tracked "Oren's sword"). A
    name without one ("shield", "the round shield") is the holder's own,
    unless the holder holds exactly one object it can name now (`same_name`:
    "the sword" in the hand that took Achilles' sword), or once held one
    by exactly that name or, failing that, by exactly one name it can be
    (so the holder who lost their key still has "the key"). It never merges
    into another person's object: two people's shields are two shields.

    Extraction names the owner since #748, so the rule for a name without
    one is the fallback: for state read with the earlier prompt (bare kinds
    throughout), an object no listed person owns, and a model's slip."""
    ref = object_ref(book, r.item)
    if not ref.name:
        return None
    if ref.owner:
        oid = ObjectId(ref.owner, ref.name, 'owned')
        if oid in state:
            return oid
        mine = [k for k in state if k.owner == ref.owner and same_name(k.name, ref.name)]
        return mine[0] if len(mine) == 1 else oid
    holder = book.who(r.who)
    if not holder:
        return None
    held = [k for k, h in state.items() if h.status == 'held' and h.holder == holder
            and same_name(k.name, ref.name)]
    if len(held) == 1:
        return held[0]
    own = ObjectId(holder, ref.name)
    if own in state or held:
        return own
    mine = [k for k in state if k.owner == holder and same_name(k.name, ref.name)]
    return mine[0] if len(mine) == 1 else own


def _recipient(book: Book, r: Record) -> str:
    """The canonical id of the person a `gives` record hands the object to
    ('' for none, or for a recipient characters.csv doesn't name)."""
    to = r.recipient
    return book.who(to) if to and book.is_person(to) else ''


def _is_person(book: Book, r: Record) -> bool:
    return book.is_person(r.who) or r.origin == 'stage-sheet'


def pair_handovers(book: Book, records: list[Record]) -> list[Record]:
    """`records` with each handover recorded twice made one (#732): a
    `gets` by one person and a `gives` or `loses` of the same object
    (`ObjectRef.same`) by another, in the same scene on the same or
    overlapping words (`overlaps`), whatever their order, become one
    `gives` to the taker, placed at the earlier of the two. A `gets` by a
    place (an object dropped there) stays a place's: it is only put after
    the parting, so the fold lays the parted object there
    (`_dropped_at`) and its holder may pick it up again (#732's review,
    SF-1). A `gives` naming another recipient isn't paired.

    A fallback since #748, whose extraction writes a handover as one `gives`
    naming the receiver: state read with the earlier prompt has the pairs,
    and a model may still write one."""
    out: list[Record | None] = list(records)
    used: set[int] = set()
    for gi, g in enumerate(records):
        if g.value != 'gets' or not g.verified or gi in used:
            continue
        taker, ref, person = book.who(g.who), object_ref(book, g.item), _is_person(book, g)
        for xi, x in enumerate(records):
            if (xi in used or x.scene_id != g.scene_id or x.value not in ('gives', 'loses')
                    or not x.verified or book.who(x.who) == taker
                    or not overlaps(x.quote, g.quote)
                    or not object_ref(book, x.item).same(ref)):
                continue
            if x.value == 'gives' and x.recipient and _recipient(book, x) != taker:
                continue
            used.update((gi, xi))
            if person:
                out[xi] = x.replace(value='gives', detail=g.who, index=min(x.index, g.index))
                out[gi] = None
            elif g.index < x.index:
                out[xi], out[gi] = x.replace(index=g.index), g.replace(index=x.index)
            break
    kept = [r for r in out if r is not None]
    return sorted(kept, key=lambda r: (book.key.get(r.scene_id, (0, 0)), r.index))


def _dropped_at(book: Book, parted: list[tuple[Record, ObjectId]], r: Record
                ) -> ObjectId | None:
    """The object a place's `gets` or `has` (`r`, a name without an owner)
    takes from a parting on the same or overlapping words in its scene
    (`parted`: `loses` and `gives` to no person, in fold order): the sword
    dropped on the sand is the sand's, not a second sword."""
    if object_ref(book, r.item).owner:
        return None
    name = object_ref(book, r.item).name
    for x, oid in reversed(parted):
        if x.scene_id == r.scene_id and overlaps(x.quote, r.quote) and same_name(oid.name, name):
            return oid
    return None


def _unknown_after(book: Book, state: dict, r: Record, oid: ObjectId) -> set[ObjectId]:
    """What a misquoted record makes unknown: the object it names; when its
    name has no owner and its holder holds several it can name, all of
    them; when the holder holds none, anyone's it can name (the record
    might be the handover that took one)."""
    out = {oid}
    ref = object_ref(book, r.item)
    if ref.owner:
        return out
    holder = book.who(r.who)
    can = {k: h for k, h in state.items() if h.status == 'held' and same_name(k.name, ref.name)}
    mine = {k for k, h in can.items() if h.holder == holder}
    return out | (mine if mine else set(can))


def check_possession(book: Book, sheet_records: list[Record] | None = None
                     ) -> tuple[list[Finding], list[str]]:
    """PHY: fold every `holds` record (and a current stage sheet's hands), in
    story order, per object (`object_id`: a name without an owner is its
    holder's own, one with an owner the owner's, #732), each handover
    recorded twice made one (`pair_handovers`); check this scene's against
    the state (`Holding`) before each. Blocking: within this scene, an
    object in another person's hands with nothing between; in any scene, an
    object held (`has`) after it was destroyed, or taken (`gets`) when its
    name has an owner (a holder's unowned "spear" taken after theirs broke
    is another spear; discarding the remains or a second `destroyed` is
    not a use); an object held again by the person who gave it away or
    lost it (across scenes only when either name has an owner; an unowned
    "spear" lost in one scene and held in a later one is a note). Notes,
    never findings: a different holder than an earlier
    scene left it with (an offstage handover is ordinary, #648's review
    CR-3); anything a scene between without typed state might explain
    (CR-5); a record on an object whose state a misquoted record made
    unknown; a name without an owner read as the holder's own while
    another of that name is tracked (that pair isn't compared); a record
    with neither an owner nor a holder. Exempt: an off-present scene. A
    holder not in characters.csv is read as a place (an object lying
    there) and said."""
    sid = book.scene_id
    if book.off_present(sid):
        return [], []
    misquoted = [r for s, recs in book.records.items() if not book.off_present(s)
                 for r in recs if r.type == 'holds' and not r.verified]
    records = pair_handovers(book, book.present_records(('holds',))
                             + list(sheet_records or []) + misquoted)
    findings: list[Finding] = []
    state: dict[ObjectId, Holding] = {}
    flagged: set[ObjectId] = set()
    offstage, gapped, places, unknown, apart, unheld = [], [], set(), [], [], []
    parted: list[tuple[Record, ObjectId]] = []
    again: list[str] = []
    for r in records:
        oid = object_id(book, state, r)
        if oid is None:
            if r.scene_id == sid and r.verified:
                unheld.append(f'{r.value} {r.item}')
            continue
        if not r.verified:
            for k in _unknown_after(book, state, r, oid):
                state[k] = Holding.unknown(r)
            continue
        holder = book.who(r.who)
        person = _is_person(book, r)
        if not person and r.value in ('gets', 'has'):
            oid = _dropped_at(book, parted, r) or oid
            if r.scene_id == sid:
                places.add(r.who)
        prev = state.get(oid)
        problem = ''
        if r.scene_id == sid and prev is None:
            ref = object_ref(book, r.item)
            others = [(k, h) for k, h in state.items() if same_name(k.name, ref.name)
                      and (k.owner == ref.owner if ref.owner else k.owner != oid.owner)]
            lost = [h for _k, h in others if h.status == 'unknown']
            if lost:
                unknown.append(f'{r.who} {r.value} {r.item} (after "{lost[0].rec.quote}", '
                               f'{lost[0].rec.scene_id})')
            elif others and not ref.owner:
                apart.append(f'{r.who} {r.value} {r.item} (also tracked: {others[0][0]})')
        elif r.scene_id == sid and prev.status == 'unknown':
            unknown.append(f'{r.who} {r.value} {r.item} (after "{prev.rec.quote}", '
                           f'{prev.rec.scene_id})')
        elif r.scene_id == sid and oid not in flagged:
            p_rec = prev.rec
            here = p_rec.scene_id == sid
            p_where = 'earlier in this scene' if here else _where(book, p_rec.scene_id)
            if prev.status == 'destroyed':
                renewed = r.value == 'gets' and not object_ref(book, r.item).owner
                if r.value == 'has' or (r.value == 'gets' and not renewed):
                    problem = f'{r.item} was destroyed {p_where}'
            elif r.value in ('has', 'gives', 'loses', 'destroyed') and person:
                if (prev.status == 'held' and prev.holder != holder
                        and p_rec.origin != 'place'):
                    if here:
                        problem = f'{p_rec.who} holds {r.item} ({p_where}), with nothing between'
                    else:
                        offstage.append(f'{r.who} has {r.item}, which {p_rec.who} held in '
                                        f'{p_rec.scene_id}')
                elif prev.status in ('given', 'lost') and prev.by == holder:
                    parted_how = 'gave away' if prev.status == 'given' else 'lost'
                    if here or object_ref(book, r.item).owner or \
                            object_ref(book, p_rec.item).owner:
                        problem = (f'{r.who} {parted_how} {r.item} {p_where}, with nothing '
                                   f'between')
                    else:
                        # an unowned "spear" across scenes may be another
                        # spear (the typed-state set's eval, #732)
                        again.append(f'{r.who} {r.value} {r.item} in {sid}, '
                                     f'{parted_how} in {p_rec.scene_id}')
            gap = [] if here else book.gap_between(p_rec.scene_id, sid)
            if problem and gap:
                gapped.append(f'{r.item} ({", ".join(gap[:3])})')
            elif problem:
                flagged.add(oid)
                verb = {'has': 'has', 'gives': 'gives away', 'loses': 'loses',
                        'destroyed': 'destroys', 'gets': 'gets'}[r.value]
                findings.append(_finding('possession', r.quote, p_rec.scene_id, p_rec.quote,
                                         f'{r.who} {verb} {r.item}, but {problem}'))
        # the state after the record
        if prev is not None and prev.status == 'destroyed' and r.value in (
                'gives', 'loses', 'destroyed'):
            continue   # its remains, discarded: still destroyed
        if r.value in ('gets', 'has'):
            state[oid] = Holding.held(holder, r if person else r.replace(origin='place'))
        elif r.value == 'gives':
            to = _recipient(book, r)
            state[oid] = (Holding.held(to, r.replace(who=r.recipient), by=holder) if to
                          else Holding.gone('given', holder, r))
            if not to:
                parted.append((r, oid))
        elif r.value in ('loses', 'destroyed'):
            state[oid] = Holding.gone('lost' if r.value == 'loses' else 'destroyed', holder, r)
            if r.value == 'loses':
                parted.append((r, oid))
    notes = []
    if offstage:
        notes.append(f'possession: {len(offstage)} object(s) in other hands than an earlier '
                     f'scene left them, with no handover shown (an offstage one is ordinary; '
                     f'not a finding): ' + '; '.join(offstage[:5]))
    if gapped:
        notes.append(f'possession: {len(gapped)} object(s) used after being given away, lost '
                     f'or destroyed, with a scene between whose typed state wasn\'t read, not '
                     f'compared: ' + '; '.join(gapped[:5]))
    if again:
        notes.append(f'possession: {len(again)} object(s) named without an owner held again by '
                     f'the person who lost or gave one away in an earlier scene (it may be '
                     f'another; not a finding, name the owner to compare): '
                     + '; '.join(again[:5]))
    if unknown:
        notes.append(f'possession: {len(unknown)} record(s) on an object whose state is unknown '
                     f'after a misquoted record, not compared: ' + '; '.join(unknown[:5]))
    if apart:
        notes.append(f'possession: {len(apart)} object(s) named without an owner, read as the '
                     f'holder\'s own while another of that name is tracked (not compared with '
                     f'it; name the owner to compare): ' + '; '.join(apart[:5]))
    if unheld:
        notes.append(f'possession: {len(unheld)} record(s) with neither an owner nor a holder, '
                     f'not compared: ' + '; '.join(unheld[:5]))
    if places:
        notes.append(f'possession: {len(places)} holder(s) characters.csv doesn\'t name, read as '
                     f'places (an object lying there), not compared as people: '
                     + ', '.join(sorted(places)[:5]))
    return findings, notes


# ============================================================================
# Knowledge
# ============================================================================

def _split(value: str) -> list[str]:
    return [x.strip() for x in (value or '').split(';') if x.strip()]


def knowledge_facts(rows: list[dict]) -> dict[str, dict]:
    """The ledger's knowledge facts a scene can be held to: binding or
    planned, by id."""
    return {r['id']: r for r in rows if (r.get('type') or '') == 'knowledge'
            and (r.get('status') or '') in ('binding', 'planned') and r.get('id')}


class Learned(NamedTuple):
    """Where a person learns a fact: `at` (scene, index), None for before
    the book; `source` (the scene or file that says so); `words`;
    `shown` True when a scene or brief shows the learning (`knows learns`,
    `knowledge_in`/`knowledge_out`), False for the ledger's `known_by`
    alone, which says who knows a fact, not when they learned it."""
    at: tuple[str, int] | None
    source: str
    words: str
    shown: bool


def learned_at(book: Book, who: str, facts: dict[str, dict], *, shown_only: bool = False
               ) -> dict[str, Learned]:
    """Fact id → the earliest `Learned` for every fact `who` is known to
    learn: from the ledger's `known_by` (a fact's scene, or before the book
    when it has none; skipped with `shown_only`), the briefs
    (`knowledge_out` of a scene `who` is the POV of: learned there;
    `knowledge_in`: known by its start) and `knows learns` records."""
    out: dict[str, Learned] = {}

    def put(fid: str, at, source: str, words: str, shown: bool) -> None:
        if fid not in facts:
            return
        if fid in out:
            old = out[fid].at
            if old is None or (at is not None and not book.before(at, old)):
                return
        out[fid] = Learned(at, source, words, shown)

    if not shown_only:
        for fid, r in facts.items():
            if who in {book.who(k) for k in _split(r.get('known_by', ''))}:
                scene = (r.get('scene_id') or '').strip()
                put(fid, (scene, 0) if scene in book.order else None, scene or 'the ledger',
                    r.get('quote') or r.get('statement') or '', False)
    for sid, brief in book.briefs.items():
        if sid not in book.order or book.who(book.pov(sid)) != who:
            continue
        for fid in _split(brief.get('knowledge_in', '')):
            put(fid, (sid, START), sid, f'knowledge_in of {sid}\'s brief', True)
        for fid in _split(brief.get('knowledge_out', '')):
            put(fid, (sid, 0), sid, f'knowledge_out of {sid}\'s brief', True)
    for sid, recs in book.records.items():
        for r in recs:
            if r.type == 'knows' and r.value == 'learns' and r.verified \
                    and book.who(r.who) == who:
                put(r.item, (sid, r.index), sid, r.quote, True)
    return out


def offered_facts(book: Book) -> tuple[list[tuple[str, str]], int]:
    """(id, statement) of the facts this scene's POV may not know before
    it, for extraction to watch: those learned later (soonest first), then
    those never learned that someone knows. Capped (`MAX_OFFERED_FACTS`);
    returns how many were left out."""
    sid, pov = book.scene_id, book.pov(book.scene_id)
    if not pov or pov.lower() == 'narrator':
        return [], 0
    who = book.who(pov)
    facts = knowledge_facts(book.rows)
    learned = learned_at(book, who, facts)
    later, never = [], []
    for fid, r in facts.items():
        if fid in learned:
            at = learned[fid].at
            if at is not None and at[0] != sid and book.before((sid, END), at):
                later.append((book.key.get(at[0], (0, 0)), fid))
        elif _split(r.get('known_by', '')):
            never.append(fid)
    ids = [fid for _, fid in sorted(later)] + sorted(never)
    shown = ids[:MAX_OFFERED_FACTS]
    return [(fid, ' '.join((facts[fid].get('statement') or '').split())) for fid in shown], \
        len(ids) - len(shown)


def check_knowledge(book: Book) -> tuple[list[Finding], list[str]]:
    """KNO: the POV acts on, says or thinks a fact (`knows uses`) before a
    scene or brief shows them learning it (`learned_at(shown_only=True)`).
    Not a finding, a note: a fact the ledger alone places later (`known_by`
    says who knows, not when: #648's review CR-4), one never shown learned,
    and one a scene before without typed state might teach (CR-5). Exempt:
    an off-present scene (a vision may show what isn't known yet). A scene
    without a POV character isn't checked, and says so."""
    sid = book.scene_id
    if book.off_present(sid):
        return [], []
    facts = knowledge_facts(book.rows)
    pov = book.pov(sid)
    if not pov or pov.lower() == 'narrator':
        return [], ([f'knowledge: the scene has no POV character, so the ledger\'s '
                     f'{len(facts)} knowledge fact(s) were not checked against it']
                    if facts else [])
    findings, notes = [], []
    cache: dict[str, tuple[dict, dict]] = {}
    unknown, unshown, gapped = [], [], []
    for r in book.records.get(sid, []):
        if r.type != 'knows' or r.value != 'uses' or not r.verified:
            continue
        if r.item not in facts:
            unknown.append(r.item)
            continue
        who = book.who(r.who)
        if who not in cache:
            cache[who] = (learned_at(book, who, facts),
                          learned_at(book, who, facts, shown_only=True))
        known, shown = cache[who][0].get(r.item), cache[who][1].get(r.item)
        if known is not None and (known.at is None or known.at[0] == sid
                                  or not book.before((sid, r.index), known.at)):
            continue   # known by now
        if shown is None:
            why = (f'the ledger places it in {known.source}' if known else
                   f'known by {facts[r.item].get("known_by") or "no one named"}')
            unshown.append(f'{r.item} ({why})')
            continue
        gap = book.gap_between('', sid)
        if gap:
            gapped.append(f'{r.item} ({", ".join(gap[:3])})')
            continue
        findings.append(_finding(
            'knowledge', r.quote, shown.at[0], shown.words,
            f'{r.who} acts on {r.item} ("{_short(facts[r.item].get("statement"))}") '
            f'before learning it, in {_where(book, shown.at[0])}', fact_id=r.item))
    if unknown:
        notes.append(f'knowledge: {len(unknown)} record(s) name a fact id the ledger has no '
                     f'binding or planned knowledge fact for, not checked: '
                     + ', '.join(sorted(set(unknown))[:5]))
    if unshown:
        notes.append(f'knowledge: {len(unshown)} fact(s) acted on that no scene or brief shows '
                     f'the POV learning first (the ledger\'s known_by says who knows, not '
                     f'when), not a finding: ' + '; '.join(unshown[:5]))
    if gapped:
        notes.append(f'knowledge: {len(gapped)} fact(s) acted on before the scene that shows '
                     f'them learned, with an earlier scene whose typed state wasn\'t read, not '
                     f'compared: ' + '; '.join(gapped[:5]))
    return findings, notes


def _short(text: str | None, n: int = 80) -> str:
    t = ' '.join((text or '').split())
    return t if len(t) <= n else t[:n - 3] + '...'


# ============================================================================
# Place and travel
# ============================================================================

def _at_place(book: Book, r: Record) -> str:
    """The location id a record puts its person at: its words through
    locations.csv, else the scene's one location when it names only one."""
    if r.item:
        return book.place(r.item)
    locs = _split(book.row(r.scene_id).get('location', ''))
    return book.place(locs[0]) if len(locs) == 1 else ''


def check_place(book: Book) -> tuple[list[Finding], list[str]]:
    """WLD: each person this scene places (`at`, through locations.csv)
    against where the story last had them, in story order: a move longer
    than world.csv's fastest `speed` allows in the time between is a WLD
    finding. A time of day is a slot, so a move is allowed at least
    `SLOT_DAYS` (two scenes in one morning at two places is ordinary unless
    the places are too far apart, #648's review CR-2). Notes count each move
    not compared and why: no place, no `timeline_day`, a summary scene, no
    distance or no speed (SF-3). Exempt: an off-present scene."""
    from storyforge.elaborate import time_mode
    sid = book.scene_id
    if book.off_present(sid):
        return [], []
    findings, notes = [], []
    mine = [r for r in book.records.get(sid, []) if r.type == 'at' and r.verified]
    unplaced = sum(1 for r in mine if not _at_place(book, r))
    if unplaced:
        notes.append(f'place: {unplaced} presence record(s) at a place locations.csv doesn\'t '
                     f'name (or the scene names none), not compared')
    first = {}
    for r in mine:
        first.setdefault(book.who(r.who), r)
    fastest = book.world.fastest() if book.world is not None else None
    skipped: dict[str, int] = {}
    earlier = book.present_records(('at',))
    for who, r in first.items():
        here = _at_place(book, r)
        if not here:
            continue
        prev = None
        for o in earlier:
            if o.scene_id != sid and book.who(o.who) == who and _at_place(book, o) and \
                    book.before((o.scene_id, o.index), (sid, r.index)):
                prev = o
        if prev is None:
            continue
        there = _at_place(book, prev)
        if there == here:
            continue
        why = ''
        if book.day(sid) is None or book.day(prev.scene_id) is None:
            why = 'a scene without a timeline_day'
        elif 'summary' in (time_mode(book.row(sid)), time_mode(book.row(prev.scene_id))):
            why = 'a summary scene, which covers a stretch'
        dist = None
        if not why:
            for a in (book.place_names.get(there, there), there, prev.item):
                for b in (book.place_names.get(here, here), here, r.item):
                    if a and b and dist is None and book.world is not None:
                        dist = book.world.distance(a, b)
            why = ('world.csv gives no distance between them' if dist is None else
                   'world.csv gives no speed' if fastest is None else '')
        if why:
            skipped[why] = skipped.get(why, 0) + 1
            continue
        t0 = _DAY_FRACTION.get(book.time(prev.scene_id), 0.0)
        t1 = _DAY_FRACTION.get(book.time(sid), 1.0)
        days = max(book.day(sid) - book.day(prev.scene_id) + t1 - t0, SLOT_DAYS)
        if dist > fastest * days:
            findings.append(_finding(
                'travel', r.quote, prev.scene_id, prev.quote,
                f'{r.who} is at {book.place_names.get(here, here)} here, '
                f'{dist:g} m from {book.place_names.get(there, there)} in '
                f'{_where(book, prev.scene_id)}; world.csv\'s fastest travel is '
                f'{fastest:g} m a day, so it needs {dist / fastest:.1f} day(s)'))
    for why, n in sorted(skipped.items()):
        notes.append(f'travel: {n} move(s) between places not checked ({why})')
    return findings, notes


# ============================================================================
# Time
# ============================================================================

_SMALL = {
    'zero': 0, 'one': 1, 'two': 2, 'three': 3, 'four': 4, 'five': 5, 'six': 6, 'seven': 7,
    'eight': 8, 'nine': 9, 'ten': 10, 'eleven': 11, 'twelve': 12, 'thirteen': 13,
    'fourteen': 14, 'fifteen': 15, 'sixteen': 16, 'seventeen': 17, 'eighteen': 18,
    'nineteen': 19,
}
_TENS = {'twenty': 20, 'thirty': 30, 'forty': 40, 'fifty': 50, 'sixty': 60, 'seventy': 70,
         'eighty': 80, 'ninety': 90}
_SCALES = {'hundred': 100, 'thousand': 1000, 'dozen': 12}
_ORDINALS = {
    'first': 1, 'second': 2, 'third': 3, 'fourth': 4, 'fifth': 5, 'sixth': 6,
    'seventh': 7, 'eighth': 8, 'ninth': 9, 'tenth': 10, 'eleventh': 11, 'twelfth': 12,
    'thirteenth': 13, 'fourteenth': 14, 'fifteenth': 15, 'sixteenth': 16,
    'seventeenth': 17, 'eighteenth': 18, 'nineteenth': 19, 'twentieth': 20,
    'thirtieth': 30, 'fortieth': 40,
}
#: Units in days
_UNITS = {
    'hour': 1 / 24, 'day': 1, 'night': 1, 'morning': 1, 'dawn': 1, 'evening': 1,
    'sunrise': 1, 'sunset': 1, 'sun': 1, 'week': 7, 'fortnight': 14, 'month': 30,
    'moon': 30, 'year': 365, 'winter': 365, 'summer': 365,
}
_WORD = '|'.join(sorted({**_SMALL, **_TENS, **_SCALES}, key=len, reverse=True))
#: A count: digits, or number words ("twenty three", "a hundred and twenty")
_NUM = rf'(?P<n>\d+|(?:an?|{_WORD})(?:\s+(?:and\s+)?(?:{_WORD}))*)'
_ORD = r'(?P<o>\d+(?:st|nd|rd|th)|' + '|'.join(sorted(_ORDINALS, key=len, reverse=True)) + r')'
_UNIT = r'(?P<u>' + '|'.join(sorted(_UNITS, key=len, reverse=True)) + r')s?'
_COUNT_RE = re.compile(rf'\b{_NUM}\s+(?:(?:full|whole|long|more)\s+)?{_UNIT}\b')
_ORDINAL_RE = re.compile(rf'\b{_ORD}\s+{_UNIT}\b')
_PAST = re.compile(r'\b(ago|since|later|after|past|gone|before (?:this|now)|earlier)\b')
#: Words that count back from the scene's present and nothing else: with no
#: way labelled, a phrase with one is still measured back (#713). "later" and
#: "after" are two-way ("twelve days later we sail"), and so is an ordinal
#: with neither ("on the twelfth day")
_ONLY_BACK = re.compile(r'\b(ago|since|past|gone|before (?:this|now)|earlier)\b')
_FUTURE = re.compile(r'^\s*(in|within)\b|\b(from now|hence|to come|more to)\b')
_VAGUE = re.compile(r'\b(few|several|many|countless|a couple|couple of|ages|years and)\b')
#: Words before a count that make it a bound or an estimate, not exact
#: (#648's review, T2)
_AT_LEAST = re.compile(r'\b(more than|over|upwards of|at least|longer than|better than)\s*$')
_AT_MOST = re.compile(r'\b(less than|under|fewer than|not yet|barely|scarcely)\s*$')
_NEARLY = re.compile(r'\b(nearly|almost|close to|just short of)\s*$')
_ABOUT = re.compile(r'\b(about|around|roughly|some|maybe|perhaps)\s*$')
_RANGE = re.compile(r'\b(or|to)\s*$')


@dataclass
class Span:
    """What an elapsed-time phrase says: the days between the scene and the
    one the count runs from, `low` to `high` (a tolerance included; `high`
    may be infinite for "more than"), and whether the counted event is
    `past` or `future`."""
    low: float
    high: float
    direction: str


def _count(raw: str) -> int | None:
    """The number a count's words or digits give ("twenty three" 23, "a
    hundred and twenty" 120), or None when the words don't make one number
    ("three two")."""
    raw = raw.strip()
    if raw.isdigit():
        return int(raw)
    total, cur, first = 0, 0, True
    for t in raw.split():
        if t == 'and':
            continue
        if t in ('a', 'an'):
            if not first:
                return None
            cur = 1
        elif t in _SMALL:
            if cur % 10 or 10 <= cur % 100 <= 19:
                return None
            cur += _SMALL[t]
        elif t in _TENS:
            if cur % 100:
                return None
            cur += _TENS[t]
        elif t == 'hundred':
            cur = (cur or 1) * 100
        elif t == 'dozen':
            cur = (cur or 1) * 12
        elif t == 'thousand':
            total, cur = total + (cur or 1) * 1000, 0
        else:
            return None
        first = False
    n = total + cur
    return n or None


def parse_elapsed(phrase: str) -> tuple[Span | None, str]:
    """A phrase's `Span`, or None and why it can't be read: vague ("a few
    days"), a half, a range ("one or two days"), two counts ("two weeks and
    three days"), no direction, no number. A bound ("more than three days",
    "nearly a week") or an estimate ("about ten days") widens the span; it
    never reads part of a phrase as the whole (#648's review, SF-2, T1, T2)."""
    p = ' '.join((phrase or '').lower().replace('-', ' ').split())
    if _VAGUE.search(p):
        return None, 'a vague count'
    if re.search(r'\bhalf\b', p):
        return None, 'a half'
    future = bool(_FUTURE.search(p))
    m = _ORDINAL_RE.search(p)
    if m and not _COUNT_RE.search(p[:m.start()]):
        o = m.group('o')
        n = int(re.match(r'\d+', o).group()) if o[0].isdigit() else _ORDINALS[o]
        unit = _UNITS[m.group('u')]
        if unit < 1:
            return None, 'an hour counted by ordinal'
        low = (n - 1) * unit
        high = n * unit - 1 if unit > 1 else low
        return Span(low, high, 'future' if future else 'past'), ''
    counts = list(_COUNT_RE.finditer(p))
    if not counts:
        return None, 'no number of days, weeks, months or years'
    if len(counts) > 1:
        return None, 'two counts in one phrase'
    m = counts[0]
    lead = p[:m.start()]
    if _RANGE.search(lead):
        return None, 'a range ("or", "to")'
    n = _count(m.group('n'))
    if n is None:
        return None, 'a number it can\'t read'
    unit = m.group('u')
    days = n * _UNITS[unit]
    if future:
        direction = 'future'
    elif _PAST.search(p):
        direction = 'past'
    else:
        return None, 'no ago, since, later or in to say which way it counts'
    if unit == 'hour':
        low, high = float(int(days)), float(int(days)) + 1
    else:
        if unit in ('month', 'moon'):
            tol = max(3, 3 * n)
        elif unit in ('year', 'winter', 'summer'):
            tol = max(15, 15 * n)
        elif unit in ('week', 'fortnight'):
            tol = max(1, n)
        else:
            tol = 0 if days <= 3 else max(1, round(days / 10))
        if _ABOUT.search(lead) or re.search(r'\bor so\b', p[m.end():]):
            tol = max(1, 2 * tol)
        low, high = days - tol, days + tol
    if _AT_LEAST.search(lead):
        low, high = days, float('inf')
    elif _AT_MOST.search(lead):
        low, high = 0.0, days
    elif _NEARLY.search(lead):
        low, high = days * 0.5, days
    return Span(low, high, direction), ''


def _way_from_words(phrase: str, span: Span) -> str:
    """The way a phrase's own words count when the model labelled none:
    `after` for a future form ("in twelve days", "a week from now"),
    `before` for words that only count back ("ago", "since", "before now"),
    '' when they could go either way ("later", "after", a bare ordinal)."""
    if span.direction == 'future':
        return 'after'
    p = ' '.join((phrase or '').lower().replace('-', ' ').split())
    return 'before' if _ONLY_BACK.search(p) else ''


def check_time(book: Book) -> tuple[list[Finding], list[str]]:
    """TIM: each `elapsed` phrase (`parse_elapsed`) against the days between
    this scene and the scene of the counted event (#713). The extractor
    labels which way that event lies (`detail`, `typed_state.ELAPSED_WAYS`):
    `before` is measured back from this scene ("three days ago"), `after`
    forward to the scene where the promised or planned event happens ("in
    twelve days"); code computes the days. A forward reference is never
    measured as time already passed. A phrase with no way labelled is
    measured as its own words count (`_way_from_words`: "ago" back, "in"
    forward), as before the labels. Notes, not checked: a phrase the parser
    can't read; one with no label whose words could count either way
    ("twelve days later", "the tenth day"), or labelled against its own words ("ago" labelled `after`); one counting
    from this scene itself (a span from a scene to itself can't be read);
    one counting from no scene; one between scenes without a `timeline_day`
    or from a summary or off-present scene. Exempt: an off-present scene."""
    sid = book.scene_id
    from storyforge.elaborate import time_mode
    from storyforge.typed_state import ELAPSED_WAYS
    if book.off_present(sid):
        return [], []
    findings: list[Finding] = []
    unread, unlabelled, crossed, itself = [], [], [], []
    no_anchor, undated = 0, 0
    for r in book.records.get(sid, []):
        if r.type != 'elapsed' or not r.verified:
            continue
        span, why = parse_elapsed(r.value)
        if span is None:
            unread.append(f'"{r.value}" ({why})')
            continue
        way = r.detail.strip().lower()
        if way not in ELAPSED_WAYS:
            way = _way_from_words(r.value, span)
            if not way:
                unlabelled.append(f'"{r.value}"')
                continue
        if (way == 'after') != (span.direction == 'future'):
            crossed.append(f'"{r.value}" (labelled {way}, its words count '
                           f'{"forward" if span.direction == "future" else "back"})')
            continue
        anchor = r.item.strip()
        if anchor == sid:
            itself.append(f'"{r.value}"')
            continue
        if not anchor or anchor not in book.order:
            no_anchor += 1
            continue
        if book.day(sid) is None or book.day(anchor) is None or \
                time_mode(book.row(anchor)) == 'summary' or book.off_present(anchor):
            undated += 1
            continue
        here, there = book.day(sid), book.day(anchor)
        gap = here - there if way == 'before' else there - here
        if not span.low <= gap <= span.high:
            from storyforge.prompts import scene_when
            if way == 'before':
                said = f'counts from {anchor}, day {there}'
            else:
                said = f'points ahead to {anchor}, day {there}'
            findings.append(_finding(
                'time', r.quote, CALENDAR, f'{anchor}: {scene_when(book.row(anchor))}',
                f'"{r.value}" {said}; this scene is day {here}, {abs(here - there)} day(s) '
                f'{"after" if here >= there else "before"} it'))
    notes = []
    if unread:
        notes.append(f'time: {len(unread)} elapsed-time phrase(s) the parser can\'t read, not '
                     f'checked: ' + '; '.join(unread[:5]))
    if unlabelled:
        notes.append(f'time: {len(unlabelled)} elapsed-time phrase(s) not labelled before or '
                     f'after this scene, whose words could count either way, not checked: '
                     + '; '.join(unlabelled[:5]))
    if crossed:
        notes.append(f'time: {len(crossed)} elapsed-time phrase(s) labelled against their own '
                     f'words, not checked: ' + '; '.join(crossed[:5]))
    if itself:
        notes.append(f'time: {len(itself)} elapsed-time phrase(s) count from this scene '
                     f'itself, which no span can be measured from, not checked: '
                     + '; '.join(itself[:5]))
    if no_anchor:
        notes.append(f'time: {no_anchor} elapsed-time phrase(s) count from an event no scene '
                     f'shows, not checked')
    if undated:
        notes.append(f'time: {undated} elapsed-time phrase(s) between scenes without a '
                     f'timeline_day (or from a summary or off-present scene), not checked')
    return findings, notes


# ============================================================================
# Injury
# ============================================================================

def _side(r: Record) -> str:
    if r.detail in ('left', 'right'):
        return r.detail
    words = re.findall(r'[a-z]+', r.item.lower())
    return 'left' if 'left' in words else 'right' if 'right' in words else ''


#: The injuries the fold carries (`Wound`); `minor` is never carried
Grade = Literal['serious', 'disabling']
GRADES: tuple[Grade, ...] = ('serious', 'disabling')
#: `Book.key`'s day before any scene with a `timeline_day`
_NO_DAY = -10 ** 9


@dataclass(frozen=True)
class WoundKey:
    """Whose body part an injury or use names: `who` the person's key
    (`Book.who`: a character id when the name binds one), `part`
    (`part_key`), `side` ('' for none)."""
    who: str
    part: str
    side: str = ''

    @classmethod
    def of(cls, book: Book, r: Record) -> 'WoundKey | None':
        """The key of an `injury` or `uses` record; None for a name several
        characters share (two Pisanders' wounds are never one, #733)."""
        if book.shared(r.who):
            return None
        return cls(book.who(r.who), part_key(r.item), _side(r))

    def meets(self, other: 'WoundKey') -> bool:
        """The same person's same part, on sides that can be one (either
        unsaid, or the same)."""
        return (self.who == other.who and self.part == other.part
                and (not self.side or not other.side or self.side == other.side))


def _starts_after(first: Record, then: Record) -> bool:
    """Whether `then`'s quote starts after `first`'s ends, in one scene's
    prose (`place_in_prose`'s offsets): partly shared words are one moment
    (#733's review, CR-2)."""
    return (then.scene_id == first.scene_id and prose_offset(then.index)
            >= prose_offset(first.index) + len(normalize(first.quote)))


@dataclass(frozen=True)
class Wound:
    """A serious or disabling injury in the fold (`fold_injuries`): `rec`
    the injury record (the worst, the first of its grade), `last` the latest
    record showing it (the injury, a re-record, an `impaired` use), and
    `lasting`, whether its own scene shows it lasting: an `impaired` use of
    the part that starts after the injury's words end (#733: "his shield arm
    will not come up" said once is a moment of the fight). A disabling one
    lasts until healed, so `lasting` is never set on one. Built with
    `inflicted`, renewed with `shown`."""
    key: WoundKey
    rec: Record
    last: Record
    lasting: bool = False

    def __post_init__(self):
        if self.rec.type != 'injury' or self.rec.value not in GRADES:
            raise ValueError(f'a wound is a serious or disabling injury, not '
                             f'{self.rec.type} {self.rec.value}')
        if self.last.type not in ('injury', 'uses'):
            raise ValueError(f'a wound is shown by an injury or a use, not {self.last.type}')
        if self.lasting and self.grade == 'disabling':
            raise ValueError('a disabling wound lasts until healed; it is never "shown lasting"')

    @property
    def grade(self) -> Grade:
        return self.rec.value  # type: ignore[return-value]

    @classmethod
    def inflicted(cls, key: WoundKey, r: Record) -> 'Wound':
        return cls(key, r, r)

    def shown(self, r: Record) -> 'Wound':
        """This wound as `r`, a later record of it, shows it."""
        own = self.grade == 'serious' and r.type == 'uses' and _starts_after(self.rec, r)
        return dataclasses.replace(self, last=r, lasting=self.lasting or own)


def _story_day(book: Book, sid: str) -> int | None:
    """The scene's story day, an undated scene taking the last day before
    it in reading order (`Book.key`); None when no scene up to it has one."""
    day = book.key.get(sid, (_NO_DAY,))[0]
    return None if day == _NO_DAY else day


def _in_force(book: Book, w: Wound, at: tuple[str, int]) -> bool:
    """Whether `w` is current at (scene, index): a disabling one always; a
    serious one in its own scene, and after it only when shown lasting and
    within `SERIOUS_DAYS` of the last scene showing it (story days,
    `_story_day`; with no day at all it stays in force, and `check_injury`
    says so)."""
    if w.grade == 'disabling' or at[0] == w.rec.scene_id:
        return True
    if not w.lasting:
        return False
    d0, d1 = _story_day(book, w.last.scene_id), _story_day(book, at[0])
    return d0 is None or d1 is None or d1 - d0 <= SERIOUS_DAYS


def fold_injuries(book: Book, at: tuple[str, int]) -> tuple[list[Wound], list[Wound]]:
    """The serious or disabling injuries in force at (scene, index), from
    present-time scenes before it, and those that lapsed (the latest per
    part, for `check_injury`'s notes): less those healed since; a serious
    one its scene didn't show lasting lapses once that scene is over, one
    shown lasting once `SERIOUS_DAYS` pass with no scene showing it again.
    An `impaired` use renews only an injury still in force: one that has
    lapsed isn't brought back. A later `minor` injury to the same part
    doesn't end one, and a `serious` one doesn't replace a `disabling`
    one. A record by a name several characters share is left out."""
    live: dict[WoundKey, Wound] = {}
    lapsed: dict[WoundKey, Wound] = {}
    for r in book.present_records(('injury', 'uses')):
        if not book.before((r.scene_id, r.index), at):
            continue
        for key in [k for k, w in live.items() if not _in_force(book, w, (r.scene_id, r.index))]:
            lapsed[key] = live.pop(key)
        k = WoundKey.of(book, r)
        if k is None:
            continue
        if r.type == 'uses':
            if r.value == 'impaired':
                for key, w in live.items():
                    if key.meets(k):
                        live[key] = w.shown(r)
        elif r.value == 'healed':
            for key in [key for key in live if key.meets(k)]:
                live.pop(key)
        elif r.value in GRADES:
            w = live.get(k)
            if w is None or (r.value == 'disabling' and w.grade == 'serious'):
                live[k] = Wound.inflicted(k, r)
                lapsed.pop(k, None)
            else:
                live[k] = w.shown(r)
        # a minor injury never ends a worse one (#648's review, C4)
    for key in [k for k, w in live.items() if not _in_force(book, w, at)]:
        lapsed[key] = live.pop(key)
    return list(live.values()), list(lapsed.values())


def current_injuries(book: Book, at: tuple[str, int]) -> list[Wound]:
    """The serious or disabling injuries in force at (scene, index)
    (`fold_injuries`)."""
    return fold_injuries(book, at)[0]


def offered_injuries(book: Book) -> tuple[list[str], int]:
    live = current_injuries(book, (book.scene_id, -1))
    lines = [f'{w.rec.who}: {w.key.side + " " if w.key.side else ""}{w.key.part}, {w.grade} '
             f'(since {w.rec.scene_id})' for w in live]
    return lines[:MAX_OFFERED_INJURIES], max(0, len(lines) - MAX_OFFERED_INJURIES)


def check_injury(book: Book) -> tuple[list[Finding], list[str]]:
    """PHY: a body part this scene uses at full strength (`uses full`)
    while a serious or disabling injury to it is current
    (`current_injuries`). Notes, never silence: a use with no side against
    a one-sided injury; an injury a scene between without typed state might
    have healed (CR-5); a use of a part whose injury lapsed, either never
    shown lasting in its scene or past `SERIOUS_DAYS` with an unread scene
    between that might have shown it again (#733's review, SF-1, SF-6); a
    use by a name several characters share; and a finding on an injury no
    story day can lapse (SF-5). Exempt: an off-present scene."""
    sid = book.scene_id
    if book.off_present(sid):
        return [], []
    findings, unsided, gapped, shared, undated = [], 0, [], [], []
    brief, unread = [], []
    done: set[WoundKey] = set()
    for r in book.records.get(sid, []):
        if r.type != 'uses' or r.value != 'full' or not r.verified:
            continue
        k = WoundKey.of(book, r)
        if k is None:
            shared.append(r.who)
            continue
        live, lapsed = fold_injuries(book, (sid, r.index))
        hit = False
        for w in live:
            if not w.key.meets(k):
                continue
            hit = True
            if w.key.side and not k.side:
                unsided += 1
                continue
            if w.key in done:
                continue
            done.add(w.key)
            inj = w.rec
            gap = book.gap_between(inj.scene_id, sid) if inj.scene_id != sid else []
            if gap:
                gapped.append(f'{r.who}\'s {k.part} ({", ".join(gap[:3])})')
                continue
            if inj.scene_id != sid and None in (_story_day(book, w.last.scene_id),
                                               _story_day(book, sid)):
                undated.append(f'{r.who}\'s {k.part}')
            where = 'earlier in this scene' if inj.scene_id == sid else _where(book, inj.scene_id)
            side = w.key.side
            findings.append(_finding(
                'injury', r.quote, inj.scene_id, inj.quote,
                f'{r.who} uses the {(side + " ") if side else ""}{k.part} at full strength, '
                f'but it was {w.grade}ly injured {where} and nothing since heals it'))
        if hit:
            continue
        for w in lapsed:
            if not w.key.meets(k) or w.key in done:
                continue
            done.add(w.key)
            gap = book.gap_between(w.last.scene_id, sid)
            if not w.lasting:
                brief.append(f'{r.who}\'s {k.part} ({w.rec.scene_id})')
            elif gap:
                unread.append(f'{r.who}\'s {k.part} (last shown {w.last.scene_id}; unread: '
                              f'{", ".join(gap[:3])})')
    notes = []
    if unsided:
        notes.append(f'injury: {unsided} use(s) of a part injured on one side, with no side '
                     f'given, not checked')
    if gapped:
        notes.append(f'injury: {len(gapped)} injured part(s) used at full strength, with a scene '
                     f'between whose typed state wasn\'t read (it may heal them), not compared: '
                     + '; '.join(gapped[:5]))
    if brief:
        notes.append(f'injury: {len(brief)} part(s) used at full strength whose serious injury '
                     f'its scene didn\'t show lasting (no impaired use after it), so not carried: '
                     + '; '.join(brief[:5]))
    if unread:
        notes.append(f'injury: {len(unread)} part(s) used at full strength whose serious injury '
                     f'lapsed {SERIOUS_DAYS} days after it was last shown, with a scene between '
                     f'whose typed state wasn\'t read (it may show it again), not compared: '
                     + '; '.join(unread[:5]))
    if shared:
        notes.append(f'injury: {len(shared)} full-strength use(s) by a name several characters '
                     f'share, not compared: ' + ', '.join(sorted(set(shared))[:5]))
    if undated:
        notes.append(f'injury: {len(undated)} finding(s) on an injury no story day can lapse '
                     f'(no timeline_day up to its scene or this one): ' + '; '.join(undated[:5]))
    return findings, notes


# ============================================================================
# Names
# ============================================================================

def _sentence(prose: str, start: int, end: int) -> str:
    """The clause around prose[start:end], as written (for a quote)."""
    left = max(prose.rfind(c, 0, start) for c in '.!?\n;')
    rights = [i for i in (prose.find(c, end) for c in '.!?\n;') if i != -1]
    right = min(rights) if rights else len(prose)
    text = prose[left + 1:right].strip(' "\'“”‘’*_')
    return ' '.join(text.split())[:240]


def check_names(book: Book, prose: str) -> tuple[list[Finding], list[str]]:
    """WLD: a name the book rules out (`forbidden_names`) in the prose, as a
    whole word; skipped at a sentence start when the scene also uses it as a
    lower-case word ("Will you..."), and skipped (with a note) when
    characters.csv gives it. Advisory note: a `named` record no registry,
    ledger subject or name map knows. Runs in every scene, off the present
    too."""
    findings, notes = [], []
    lower_words = set(re.findall(r'\b[a-z][\w\']*\b', prose))
    for name, where in sorted(book.forbidden.items()):
        if book.registry_names is not None and name.lower() in book.registry_names:
            notes.append(f'names: "{name}" is ruled out in {where} but is also a name the '
                         f'character registry gives, not checked')
            continue
        hits = []
        for m in re.finditer(rf'(?<![\w]){re.escape(name)}(?![\w])', prose):
            initial = not prose[:m.start()].rstrip(' "\'“‘*_') or \
                prose[:m.start()].rstrip(' "\'“‘*_')[-1] in '.!?\n'
            if initial and name.lower() in lower_words:
                continue   # "Will you…" where "will" is also a word of the scene
            hits.append(m)
        if hits:
            quote = _sentence(prose, hits[0].start(), hits[0].end())
            findings.append(_finding(
                'names', quote, where, name,
                f'"{name}" is a name {where} rules out'
                + (f' ({len(hits)} times in the scene)' if len(hits) > 1 else '')))
    if book.known_names is None:
        if any(r.type == 'named' for r in book.records.get(book.scene_id, [])):
            notes.append('names: reference/characters.csv is missing, so the names the scene '
                         'uses were not checked against a registry')
        return findings, notes
    unknown = {}
    for r in book.records.get(book.scene_id, []):
        if r.type != 'named' or not r.verified:
            continue
        v = ' '.join(r.value.split())
        tokens = [t for t in re.findall(r"[\w']+", v) if t[:1].isupper()]
        if v.lower() in book.known_names or (tokens and all(
                t.lower() in book.known_names for t in tokens)):
            continue
        unknown.setdefault(v, r.quote)
    if unknown:
        notes.append('advisory: names no registry, ledger subject or name map knows: '
                     + '; '.join(f'{n} ("{_short(q, 60)}")' for n, q in sorted(unknown.items())))
    return findings, notes


# ============================================================================
# Geography and sky
# ============================================================================

#: The place a sun phrase names: from an optional "the" (kept, as world.csv
#: may name "the sea") up to punctuation or a word that starts another
#: clause or phrase ("behind the hills on the road from Kesh" is the hills;
#: #648's review, T4, T5)
_PLACE = (r'(?P<place>(?:the\s+)?[^.,;:!?\n"“”]{1,40}?)'
          r'(?=\s+(?:as|and|but|while|when|where|until|on|from|to|toward|towards|into|at|'
          r'with|for|over|across|along|through)\b|[.,;:!?\n"“”]|$)')
_SKY = [
    ('east', re.compile(r'\b(?:the\s+)?sun\s+(?:rose|rises|risen|was\s+rising|came\s+up|comes\s+up|'
                        r'climbed|lifted|broke|cleared|was\s+up)\s+(?:up\s+)?(?:over|above|behind|'
                        r'from\s+behind|beyond|out\s+of)\s+' + _PLACE, re.I)),
    ('west', re.compile(r'\b(?:the\s+)?sun\s+(?:set|sets|was\s+setting|went\s+down|goes\s+down|sank|'
                        r'sinks|dropped|drops|fell|slid|dipped)\s+(?:down\s+)?(?:behind|beyond|into|'
                        r'below|over|under)\s+' + _PLACE, re.I)),
    ('east', re.compile(r'\b(?:dawn|daybreak|first\s+light|sunrise)\s+(?:broke|came|rose|spread|'
                        r'grew|showed|paled|reddened)?\s*(?:over|above|behind|beyond)\s+' + _PLACE,
                        re.I)),
    ('west', re.compile(r'\bsunset\s+(?:burned\s+|flared\s+|reddened\s+)?(?:over|behind|beyond)\s+'
                        + _PLACE, re.I)),
]
_SKY_COMPASS = re.compile(r'\b(?:the\s+)?sun\s+(?P<verb>rose|rises|came\s+up|set|sets|went\s+down|'
                          r'sank)\s+in\s+the\s+(?P<place>north[\s-]?east|north[\s-]?west|'
                          r'south[\s-]?east|south[\s-]?west|north|south|east|west)(?![\w-])',
                          re.I)


def check_sky(book: Book, prose: str) -> tuple[list[Finding], list[str]]:
    """WLD: the sun rising or setting over, behind or in a place (`_SKY`,
    `_SKY_COMPASS`) more than 45° from east or west by world.csv's
    directions. A capitalised place world.csv doesn't give is a note; a
    common noun ("the hills") is nothing. Exempt: an off-present scene."""
    from storyforge.world_table import angle
    if book.off_present(book.scene_id) or book.world is None:
        return [], []
    findings, unknown = [], []
    hits = [(want, m) for want, rx in _SKY for m in rx.finditer(prose)]
    for m in _SKY_COMPASS.finditer(prose):
        verb = m.group('verb').lower()
        hits.append(('east' if verb.startswith(('ros', 'ris', 'came')) else 'west', m))
    for want, m in sorted(hits, key=lambda h: h[1].start()):
        place = m.group('place').strip()
        where = book.world.direction(place)
        quote = ' '.join(m.group(0).split())
        if where is None:
            bare = re.sub(r'^the\s+', '', place, flags=re.I)
            if bare[:1].isupper():
                unknown.append(f'"{quote}" ({bare.split()[0]} is not in world.csv)')
            continue
        if angle(where, want) > 45:
            findings.append(_finding(
                'sky', quote, 'world.csv', f'{place}: {where}',
                f'the sun {"rises" if want == "east" else "sets"} in the {want}, but this puts '
                f'it in the {where}' + ('' if place.lower() == where else
                                       f' (world.csv: {place} lies {where})')))
    notes = []
    if unknown:
        notes.append(f'sky: {len(unknown)} phrase(s) about the sun at a place world.csv doesn\'t '
                     f'give a direction for, not checked: ' + '; '.join(unknown[:5]))
    return findings, notes


# ============================================================================
# Building the book, and the whole check
# ============================================================================

def forbidden_names(project_dir: str) -> tuple[dict[str, str], list[str]]:
    """Forbidden name → the file ruling it out: an adaptation's name maps'
    replaced source names (`source.NameMap.changed`), then storyforge.yaml's
    `continuity.forbidden_names`. Notes for a name map that can't be read."""
    from storyforge.common import read_top_level_field
    out: dict[str, str] = {}
    notes: list[str] = []
    from storyforge import source
    try:
        cfg = source.read_config(project_dir)
    except (source.SourceError, OSError, ValueError) as e:   # a bad source block: say so
        cfg, notes = None, [f'names: the source block can\'t be read ({e}); its name map not '
                            f'checked']
    if cfg is not None:
        for proj in cfg.projects:
            rel = cfg.map_path(proj)
            if not rel:
                continue
            try:
                nm = source.load_name_map(source.resolve(project_dir, rel))
            except source.SourceError as e:
                notes.append(f'names: {e}; its names not checked')
                continue
            for old, new in nm.changed():
                if old != new:
                    out.setdefault(old, os.path.basename(rel))
    for name in _split(read_top_level_field(project_dir, FORBIDDEN_BLOCK, FORBIDDEN_KEY)):
        out.setdefault(name, 'storyforge.yaml')
    return out, notes


def known_names(project_dir: str, rows: list[dict]) -> set[str] | None:
    """Lower-case names a person may be called by: the character registry
    (ids, names, aliases), ledger subjects, an adaptation's name map targets
    and its imported sources' registries. None without characters.csv."""
    from storyforge.enrich import load_alias_map
    path = os.path.join(project_dir, 'reference', 'characters.csv')
    if not os.path.isfile(path):
        return None
    names = set(load_alias_map(path))
    names |= {(r.get('subject') or '').strip().lower() for r in rows} - {''}
    src = os.path.join(project_dir, 'reference', 'source')
    if os.path.isdir(src):
        for slug in sorted(os.listdir(src)):
            names |= set(load_alias_map(os.path.join(src, slug, 'reference', 'characters.csv')))
            names |= set(load_alias_map(os.path.join(src, slug, 'characters.csv')))
    from storyforge import source
    try:
        cfg = source.read_config(project_dir)
    except (source.SourceError, OSError, ValueError):
        cfg = None   # forbidden_names reports an unreadable source block
    for proj in (cfg.projects if cfg else ()):
        rel = cfg.map_path(proj)
        if not rel:
            continue
        try:
            nm = source.load_name_map(source.resolve(project_dir, rel))
        except (source.SourceError, OSError, ValueError):
            continue   # forbidden_names reports an unreadable name map
        names |= {t.lower() for t in nm.replacements.values()}
        names |= {t.lower() for t in nm.id_names.values()}
    tokens = {t for n in names for t in re.findall(r"[\w']+", n)}
    return names | tokens


def load_book(project_dir: str, scene_id: str, *, rows: list[dict] | None = None
              ) -> tuple[Book, list[str]]:
    """Everything the checks read but this scene's records, and notes on
    what couldn't be read. The scenes are the live ones (`prompts.live_order`:
    a cut or merged scene's records never count, #648's review CR-9). Notes:
    scenes before this one in story order without typed state for their
    current prose (`Book.gaps`, which turns findings they could explain into
    notes; C5, SF-10), other scenes' misquoted records that would have
    counted (SF-6), a characters.csv `death_scene` that isn't a scene (left
    out, never placed at the book's start; SF-7, TD-3), a name map. Raises
    ContinuityError on a malformed world table or scenes.csv."""
    from storyforge import ledger, typed_state, world_table
    from storyforge.elaborate import _read_csv, _read_csv_as_map
    from storyforge.enrich import load_alias_map
    from storyforge.prompts import live_order
    ref = os.path.join(project_dir, 'reference')
    try:
        all_order = ledger.scene_order(project_dir)
        rows = ledger.load(project_dir) if rows is None else rows
        world = world_table.load(project_dir)
    except (ValueError, ledger.LedgerError, OSError) as e:
        raise ContinuityError(f'{scene_id}: {e}') from e
    scenes = _read_csv_as_map(os.path.join(ref, 'scenes.csv'))
    order = live_order(all_order, scenes, scene_id)
    header = _read_csv(os.path.join(ref, 'scenes.csv'))
    places = load_alias_map(os.path.join(ref, 'locations.csv'))
    place_names = {}
    for r in _read_csv(os.path.join(ref, 'locations.csv')):
        pid = (r.get('id') or r.get('name') or '').strip()
        if pid:
            place_names[pid] = (r.get('name') or pid).strip()
    forbidden, notes = forbidden_names(project_dir)
    deaths, unplaced = [], []
    for d in typed_state.registry_deaths(project_dir):
        (deaths if d.scene_id in order else unplaced).append(d)
    if unplaced:
        notes.append(f'life: {len(unplaced)} characters.csv death_scene(s) name no live scene, '
                     f'not checked: ' + ', '.join(f'{d.who} ({d.scene_id})' for d in unplaced[:5]))
    chars_path = os.path.join(ref, 'characters.csv')
    book = Book(scene_id, order, scenes, deaths=deaths, chars=load_alias_map(chars_path),
                namesakes=namesakes(_read_csv(chars_path)),
                ids=registry_ids(_read_csv(chars_path)),
                places=places, place_names=place_names, world=world, rows=rows,
                briefs=_read_csv_as_map(os.path.join(ref, 'scene-briefs.csv')),
                has_time_mode=bool(header) and 'time_mode' in header[0],
                forbidden=forbidden, known_names=known_names(project_dir, rows),
                registry_names=(set(load_alias_map(chars_path))
                                if os.path.isfile(chars_path) else None))
    # a death_scene binds its row's id (#733); a row the name map leaves out
    # (no name) binds no one, so it is said rather than kept as a death
    loose = [d for d in book.deaths if book.bind(d) is None]
    if loose:
        book.deaths = [d for d in book.deaths if d not in loose]
        notes.append(f'life: {len(loose)} characters.csv death_scene(s) on a row with no name, '
                     f'so they bind no character, not checked: '
                     + ', '.join(f'{d.who} ({d.scene_id})' for d in loose[:5]))
    missing, stale, misquoted = [], [], []
    here = book.key.get(scene_id, (0, 0))
    for sid in sorted(order, key=order.get):
        if sid == scene_id or not os.path.isfile(os.path.join(project_dir, 'scenes', f'{sid}.md')):
            continue
        recs, why = typed_state.current(project_dir, sid)
        if recs is not None:
            book.records[sid] = [r if r.scene_id == sid else r.replace(scene_id=sid)
                                 for r in recs]
            bad = sum(1 for r in recs if not r.verified and (
                r.type in ('alive', 'holds', 'injury') or (r.type == 'knows'
                                                         and r.value == 'learns')))
            if bad and not book.off_present(sid):
                misquoted.append(f'{sid} ({bad})')
            continue
        if book.key[sid] < here:
            book.gaps.add(sid)
            (stale if why else missing).append(sid if not why else f'{sid} ({why})')
    if missing:
        notes.append(f'{len(missing)} earlier scene(s) in story order with prose have no typed '
                     f'state yet, so their facts weren\'t read (check them to add it): '
                     + ', '.join(missing[:8]) + (' ...' if len(missing) > 8 else ''))
    if stale:
        notes.append(f'{len(stale)} earlier scene(s)\' typed state not read: '
                     + '; '.join(stale[:5]) + (' ...' if len(stale) > 5 else ''))
    if misquoted:
        notes.append(f'{len(misquoted)} other scene(s) have death, possession, injury or '
                     f'learning records whose quotes aren\'t in their prose, so those records '
                     f'weren\'t compared: ' + ', '.join(misquoted[:8]))
    return book, notes


def run_checks(book: Book, prose: str, sheet_records: list[Record] | None = None
               ) -> tuple[list[Finding], list[str]]:
    """Every check on `book.scene_id`, its records in `book.records`. Pure:
    no model, no files. Findings whose quote isn't in `prose` are dropped
    (a record's verified quote always is) and counted."""
    findings, notes = [], []
    if book.off_present(book.scene_id):
        from storyforge.elaborate import time_mode
        notes.append(f'the scene is marked {time_mode(book.row(book.scene_id))} (not the story\'s '
                     f'present): only names were checked')
    for check in (lambda b: check_life(b, prose), check_knowledge,
                  lambda b: check_possession(b, sheet_records), check_place, check_time,
                  check_injury, lambda b: check_names(b, prose), lambda b: check_sky(b, prose)):
        f, n = check(book)
        findings += f
        notes += n
    kept = [f for f in findings if quote_in(prose, f.scene_quote)]
    if len(kept) < len(findings):
        notes.append(f'{len(findings) - len(kept)} finding(s) quote words not in the scene: '
                     f'dropped')
    return kept, notes


def tracked_objects(book: Book) -> list[str]:
    """The object names other present-time scenes' `holds` records give, for
    extraction to name an object the same way (#648's review, TD-6): those
    before this scene in story order first, nearest first; one name per
    name the identity rule reads (`object_ref`: "his shield" and "shield"
    are one name, "Achilles' armour" another); capped at
    `MAX_OFFERED_OBJECTS`."""
    sid = book.scene_id
    seen: dict[ObjectRef, tuple] = {}
    names: dict[ObjectRef, str] = {}
    for r in book.present_records(('holds',)):
        k = object_ref(book, r.item)
        if not k.name or r.scene_id == sid:
            continue
        before = book.before((r.scene_id, r.index), (sid, START))
        rank = (0, tuple(-x for x in book.key.get(r.scene_id, (0, 0)))) if before else \
            (1, book.key.get(r.scene_id, (0, 0)))
        if k not in seen or rank < seen[k]:
            seen[k], names[k] = rank, r.item
    return [names[k] for k in sorted(seen, key=seen.get)][:MAX_OFFERED_OBJECTS]


def check_continuity(project_dir: str, scene_id: str, *, prose: str | None = None,
                     model: str | None = None, log_file: str = '', reuse: bool = True,
                     save: bool = True, rows: list[dict] | None = None) -> ContinuityResult:
    """Read `scene_id`'s typed state (one call; none when `reuse` and its
    file is of this prose and of this prompt: the same facts, injuries,
    objects and calendar offered, and the same model), save it with what
    extraction couldn't use, and run every check. A reused file's notes are
    said again.

    Raises:
        ContinuityError: no prose, a scene not in scenes.csv, a refusal or
            API failure, a reply off the schema twice, or a malformed world
            table or scenes.csv.
    """
    from storyforge import typed_state, world_table
    from storyforge.prompts import calendar_lines
    if prose is None:
        from storyforge.illustrations import read_scene_raw
        prose = read_scene_raw(project_dir, scene_id)
    if not (prose or '').strip():
        raise ContinuityError(f'{scene_id} has no prose to check')
    try:
        book, notes = load_book(project_dir, scene_id, rows=rows)
    except world_table.WorldTableError as e:
        raise ContinuityError(str(e)) from e
    if scene_id not in book.order:
        raise ContinuityError(f'{scene_id} is not a scene in reference/scenes.csv')
    result = ContinuityResult(scene_id, notes=notes)
    facts, cut_f = offered_facts(book)
    injuries, cut_i = offered_injuries(book)
    objects = tracked_objects(book)
    cast = sorted({(r.get('name') or r.get('id') or '').strip() for r in _registry(
        project_dir)} - {''})
    calendar = calendar_lines(book.order, book.scenes, scene_id)
    model = typed_state.resolve_model(model)
    pov = book.pov(scene_id)
    prompt_id = typed_state.prompt_hash(
        typed_state.build_prompt(scene_id, prose, pov=pov, cast=cast, calendar=calendar,
                                 facts=facts, injuries=injuries, objects=objects), model)
    saved, why = (typed_state.current_state(project_dir, scene_id, prose, prompt_sha256=prompt_id)
                  if reuse else (None, ''))
    if saved is not None:
        records = saved['records']
        result.notes += saved['notes']
    else:
        if why and why != 'its typed state is of earlier prose':
            result.notes.append(f'typed state read again: {why}')
        try:
            got = typed_state.extract(scene_id, prose, model=model, log_file=log_file,
                                      pov=pov, cast=cast, calendar=calendar,
                                      facts=facts, injuries=injuries, objects=objects)
        except typed_state.TypedStateError as e:
            raise ContinuityError(str(e)) from e
        records = got.records
        extracted = list(got.notes)
        if cut_f:
            extracted.append(f'knowledge: {cut_f} fact(s) past the {MAX_OFFERED_FACTS} '
                             f'offered not watched')
        if cut_i:
            extracted.append(f'injury: {cut_i} injur(ies) past the {MAX_OFFERED_INJURIES} '
                             f'offered not watched')
        result.notes += extracted
        result.extracted = True
        if save:
            typed_state.write_state(project_dir, scene_id, prose, records, model=model,
                                    prompt_sha256=got.prompt_sha256, notes=extracted)
    records = [r if r.scene_id == scene_id else r.replace(scene_id=scene_id) for r in records]
    misquoted = sum(1 for r in records if not r.verified)
    if misquoted:
        result.notes.append(f'{misquoted} of {len(records)} record(s) quote words not in the '
                            f'scene: they make no finding')
    book.records[scene_id] = records
    result.records = records
    # the kinds of thing tracked (`ObjectId.kind`): a sheet's "the armour"
    # counts for the records' "Achilles' armour" (#732's review, TD-3)
    tracked = {object_ref(book, r.item).kind for recs in book.records.values() for r in recs
               if r.type == 'holds'} - {''}
    sheet_records = []
    for sid in book.records:
        if book.off_present(sid):
            continue   # a memory's hands say nothing about the present (TD-4)
        got_sheet, why = typed_state.sheet_holdings(project_dir, sid, tracked)
        sheet_records += got_sheet
        if why:
            result.notes.append(f'possession: {why}')
    findings, more = run_checks(book, prose, sheet_records)
    result.findings = findings
    result.notes += more
    return result


def _registry(project_dir: str) -> list[dict]:
    from storyforge.elaborate import _read_csv
    return _read_csv(os.path.join(project_dir, 'reference', 'characters.csv'))


def covered_fact_ids(rows: list[dict]) -> set[str]:
    """The ledger ids whose content a typed check compares by code, for the
    question layer (#649) to leave out: the knowledge facts the knowledge
    check holds a scene to (`knowledge_facts`: type `knowledge`, binding or
    planned) that name someone in `known_by` (a fact no one knows is never
    offered to extraction, so nothing compares it). Every other row (every
    `physical` row among them: the possession and injury checks compare the
    prose's own records, not ledger rows) stays a statement only a model
    reads (#648's review, TD-7)."""
    return {fid for fid, r in knowledge_facts(rows).items() if _split(r.get('known_by', ''))}


def overlaps(a: str, b: str) -> bool:
    """Whether two quotes are on the same words (one inside the other)."""
    x, y = normalize(a), normalize(b)
    return bool(x and y and (x in y or y in x))
