"""Deterministic continuity checks over typed state (#648, plan A2).

Models read, code checks. Each scene's typed records (`storyforge.typed_state`)
are compared with every other scene's, the ledger, the briefs, scenes.csv's
calendar and the world table, free and the same every run:

- **life** (PHY): a dead character present, acting or spoken to as present,
  in a later scene of the story's present. Deaths come from `alive` records
  and characters.csv's `death_scene`. A scene marked off the present
  (scenes.csv `frame`: memory, dream, vision, ghost; or a `time_mode` of
  frame or vision) is exempt, and so is a flashback, whose `timeline_day`
  comes before the death. An unmarked scene is reported, never assumed to
  be a memory.
- **possession** (PHY): an object in two people's hands at once, or held,
  given or used after it was given away, lost or destroyed, unless a fact
  between moves it (`gets`). A saved stage sheet's hands (#647) count for
  the objects tracked.
- **knowledge** (KNO): the POV character acts on, says or thinks a fact
  before the scene where they learn it (or one they never learn). When a
  character learns a fact (`learned_at`) is the earliest of the ledger's
  knowledge rows (`known_by`), the briefs' `knowledge_in`/`knowledge_out`
  for their POV, and `knows learns` records.
- **place** (PHY): a character in two places in one time slot (the same
  `timeline_day` and `time_of_day`), places matched through
  locations.csv; (WLD) travel faster than world.csv's fastest `speed`
  allows over a `distance` it gives.
- **time** (TIM): an elapsed-time phrase ("three days ago", "the tenth
  day") against the calendar: the days between this scene and the scene the
  count runs from (`parse_elapsed`, a small parser that says what it can't
  read rather than guessing).
- **injury** (PHY): a body part used at full strength while a serious or
  disabling injury to it is current.
- **names** (WLD): a name the book rules out appears: an adaptation's name
  map's replaced source names (`source.NameMap.changed`) and the author's
  `continuity.forbidden_names` in storyforge.yaml. A name no registry,
  ledger subject or name map knows is advisory (a NOTE).
- **geography and sky** (WLD): a short phrase list ("the sun went down
  behind Ida") checked against world.csv's directions; free, no model.

Every finding is a `checker.Finding` with the scene's own words, verified;
a record whose quote isn't in its scene makes none. Whatever couldn't be
checked is a note (`ContinuityResult.notes`): silence means checked and
clean. The gate runs this on every scene it checks (`gate.GATE_CONTINUITY`):
its findings join the check's and block like any continuity error.
"""

from __future__ import annotations

import os
import re
from dataclasses import dataclass, field

from storyforge.checker import CALENDAR, Finding
from storyforge.quotes import normalize, quote_in
from storyforge.typed_state import (MAX_OFFERED_FACTS, MAX_OFFERED_INJURIES, Record,
                                    object_key, part_key)

#: The block and key in storyforge.yaml holding names the book rules out,
#: `;`-separated (`continuity:` / `  forbidden_names: Jupiter; Juno`)
FORBIDDEN_BLOCK, FORBIDDEN_KEY = 'continuity', 'forbidden_names'
#: A serious injury is current this many story days at most, unless a
#: `healed` record ends it sooner (a disabling one lasts until healed)
SERIOUS_DAYS = 42
#: Where in its day each time of day falls, for travel
_DAY_FRACTION = {'dawn': 0.2, 'morning': 0.35, 'afternoon': 0.6, 'evening': 0.75,
                 'dusk': 0.8, 'night': 0.9}
#: Codes by check
CODES = {'life': 'PHY', 'possession': 'PHY', 'knowledge': 'KNO', 'place': 'PHY',
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
    places: dict[str, str] = field(default_factory=dict)
    place_names: dict[str, str] = field(default_factory=dict)
    world: object = None
    rows: list[dict] = field(default_factory=list)
    briefs: dict[str, dict] = field(default_factory=dict)
    has_frame_column: bool = False
    #: forbidden name → where it is ruled out (a file name)
    forbidden: dict[str, str] = field(default_factory=dict)
    #: lower-case names a person may be called by; None: no registry
    known_names: set[str] | None = None
    key: dict[str, tuple] = field(default_factory=dict)

    def __post_init__(self):
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

    def who(self, name: str) -> str:
        n = ' '.join((name or '').split()).lower()
        return self.chars.get(n, n)

    def is_person(self, name: str) -> bool:
        return ' '.join((name or '').split()).lower() in self.chars

    def place(self, name: str) -> str:
        n = ' '.join((name or '').split()).lower()
        n = re.sub(r'^(?:the|a|an)\s+', '', n)
        return self.places.get(n) or self.places.get(f'the {n}', '')

    def present_records(self, kinds: tuple[str, ...]) -> list[Record]:
        """Every verified record of `kinds` in a present-time scene, in story order."""
        out = [r for sid, recs in self.records.items() if not self.off_present(sid)
               for r in recs if r.type in kinds and r.verified]
        return sorted(out, key=lambda r: (self.key.get(r.scene_id, (0, 0)), r.index))

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

def check_life(book: Book) -> tuple[list[Finding], list[str]]:
    sid = book.scene_id
    if book.off_present(sid):
        return [], []
    events = book.present_records(('alive',)) + [
        d for d in book.deaths if not book.off_present(d.scene_id)]
    findings, notes = [], []
    seen: set[str] = set()
    for r in book.records.get(sid, []):
        if r.type != 'at' or not r.verified:
            continue
        who = book.who(r.who)
        if who in seen:
            continue
        mine = [e for e in events if book.who(e.who) == who
                and book.before((e.scene_id, e.index), (sid, r.index))]
        deaths = [e for e in mine if e.value == 'dead']
        death = next((d for d in deaths if not any(
            e.value == 'alive' and book.before((d.scene_id, d.index), (e.scene_id, e.index))
            for e in mine)), None)
        if death is None:
            continue
        seen.add(who)
        where = 'earlier in this scene' if death.scene_id == sid else _where(book, death.scene_id)
        hint = ('; if this scene is a memory, dream, vision or ghost scene, mark it in '
                'scenes.csv\'s frame column' + ('' if book.has_frame_column else
                                                  ' (scenes.csv has none: every scene is '
                                                  'read as the present)'))
        if death.origin == 'registry':
            findings.append(_finding('life', r.quote, 'characters.csv', death.quote,
                                     f'{r.who} is present here, but characters.csv gives '
                                     f'{who} death_scene {death.scene_id}{hint}'))
        else:
            findings.append(_finding('life', r.quote, death.scene_id, death.quote,
                                     f'{r.who} is present here, but died {where}{hint}'))
    return findings, notes


# ============================================================================
# Possession
# ============================================================================

def check_possession(book: Book, sheet_records: list[Record] | None = None
                     ) -> tuple[list[Finding], list[str]]:
    """Fold every `holds` record, in story order, per object; check this
    scene's against the state before each."""
    sid = book.scene_id
    if book.off_present(sid):
        return [], []
    records = book.present_records(('holds',)) + list(sheet_records or [])
    records.sort(key=lambda r: (book.key.get(r.scene_id, (0, 0)), r.index))
    findings: list[Finding] = []
    # object key → (holder canonical or place, status, record, by)
    state: dict[str, tuple[str, str, Record, str]] = {}
    flagged: set[str] = set()
    for r in records:
        obj = object_key(r.item)
        if not obj:
            continue
        holder = book.who(r.who)
        person = book.is_person(r.who) or r.origin == 'stage-sheet'
        prev = state.get(obj)
        problem = ''
        if r.scene_id == sid and prev is not None and obj not in flagged:
            p_holder, status, p_rec, by = prev
            p_where = ('earlier in this scene' if p_rec.scene_id == sid
                       else _where(book, p_rec.scene_id))
            if r.value != 'gets' and status == 'destroyed':
                problem = f'{r.item} was destroyed {p_where}'
            elif r.value in ('has', 'gives', 'loses', 'destroyed') and person:
                if status == 'held' and p_holder != holder and p_rec.origin != 'place':
                    problem = f'{p_rec.who} holds {r.item} ({p_where}), with nothing between'
                elif status in ('given', 'lost') and by == holder:
                    problem = (f'{r.who} {"gave away" if status == "given" else "lost"} '
                               f'{r.item} {p_where}, with nothing between')
            if problem:
                flagged.add(obj)
                verb = {'has': 'has', 'gives': 'gives away', 'loses': 'loses',
                        'destroyed': 'destroys', 'gets': 'gets'}[r.value]
                findings.append(_finding('possession', r.quote, p_rec.scene_id, p_rec.quote,
                                         f'{r.who} {verb} {r.item}, but {problem}'))
        # the state after the record
        if r.value in ('gets', 'has'):
            rec = r if person else Record(**{**r.__dict__, 'origin': 'place'})
            state[obj] = (holder, 'held', rec, '')
        elif r.value == 'gives':
            to = r.detail.strip()
            if to and book.is_person(to):
                state[obj] = (book.who(to), 'held',
                              Record(**{**r.__dict__, 'who': to}), holder)
            else:
                state[obj] = ('', 'given', r, holder)
        elif r.value == 'loses':
            state[obj] = ('', 'lost', r, holder)
        elif r.value == 'destroyed':
            state[obj] = ('', 'destroyed', r, holder)
    return findings, []


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


def learned_at(book: Book, who: str, facts: dict[str, dict]
               ) -> dict[str, tuple[tuple[str, int] | None, str, str]]:
    """Fact id → (where `who` learns it: (scene, index), None for before
    the book; the scene or file that says so; its words) for every fact
    `who` is known to learn. From the ledger's `known_by` (a fact's scene,
    or before the book when it has none), the briefs (`knowledge_out` of a
    scene `who` is the POV of: learned there; `knowledge_in`: known by its
    start) and `knows learns` records. The earliest wins."""
    out: dict[str, tuple[tuple[str, int] | None, str, str]] = {}

    def put(fid: str, at, source: str, words: str) -> None:
        if fid not in facts:
            return
        if fid in out:
            old = out[fid][0]
            if old is None or (at is not None and not book.before(at, old)):
                return
        out[fid] = (at, source, words)

    for fid, r in facts.items():
        if who in {book.who(k) for k in _split(r.get('known_by', ''))}:
            scene = (r.get('scene_id') or '').strip()
            put(fid, (scene, 0) if scene in book.order else None, scene or 'the ledger',
                r.get('quote') or r.get('statement') or '')
    for sid, brief in book.briefs.items():
        if sid not in book.order or book.who(book.pov(sid)) != who:
            continue
        for fid in _split(brief.get('knowledge_in', '')):
            put(fid, (sid, -1), sid, f'knowledge_in of {sid}\'s brief')
        for fid in _split(brief.get('knowledge_out', '')):
            put(fid, (sid, 0), sid, f'knowledge_out of {sid}\'s brief')
    for sid, recs in book.records.items():
        for r in recs:
            if r.type == 'knows' and r.value == 'learns' and r.verified \
                    and book.who(r.who) == who:
                put(r.item, (sid, r.index), sid, r.quote)
    return out


def offered_facts(book: Book) -> tuple[list[tuple[str, str]], int]:
    """(id, statement) of the facts this scene's POV hasn't learned before
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
            at = learned[fid][0]
            if at is not None and at[0] != sid and book.before((sid, 10 ** 6), at):
                later.append((book.key.get(at[0], (0, 0)), fid))
        elif _split(r.get('known_by', '')):
            never.append(fid)
    ids = [fid for _, fid in sorted(later)] + sorted(never)
    shown = ids[:MAX_OFFERED_FACTS]
    return [(fid, ' '.join((facts[fid].get('statement') or '').split())) for fid in shown], \
        len(ids) - len(shown)


def check_knowledge(book: Book) -> tuple[list[Finding], list[str]]:
    sid = book.scene_id
    facts = knowledge_facts(book.rows)
    findings, notes = [], []
    cache: dict[str, dict] = {}
    unknown = []
    for r in book.records.get(sid, []):
        if r.type != 'knows' or r.value != 'uses' or not r.verified:
            continue
        if r.item not in facts:
            unknown.append(r.item)
            continue
        who = book.who(r.who)
        if who not in cache:
            cache[who] = learned_at(book, who, facts)
        learned = cache[who].get(r.item)
        if learned is not None:
            at, source, words = learned
            if at is None or not book.before((sid, r.index), at) or at[0] == sid:
                continue
            findings.append(_finding(
                'knowledge', r.quote, at[0], words,
                f'{r.who} acts on {r.item} ("{_short(facts[r.item].get("statement"))}") '
                f'before learning it, in {_where(book, at[0])}', fact_id=r.item))
        else:
            row = facts[r.item]
            findings.append(_finding(
                'knowledge', r.quote, (row.get('scene_id') or '').strip(),
                row.get('quote') or row.get('statement') or '',
                f'{r.who} acts on {r.item} ("{_short(row.get("statement"))}"), which no scene, '
                f'brief or ledger row has {r.who} learn (known by '
                f'{row.get("known_by") or "no one named"})', fact_id=r.item))
    if unknown:
        notes.append(f'knowledge: {len(unknown)} record(s) name a fact id the ledger has no '
                     f'binding or planned knowledge fact for, not checked: '
                     + ', '.join(sorted(set(unknown))[:5]))
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


def _slot_scene(book: Book, sid: str) -> bool:
    from storyforge.elaborate import time_mode, told_by
    row = book.row(sid)
    return (not book.off_present(sid) and time_mode(row) != 'summary' and not told_by(row)
            and book.day(sid) is not None and bool(book.time(sid)))


def check_place(book: Book) -> tuple[list[Finding], list[str]]:
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
    # two places in one time slot
    if _slot_scene(book, sid):
        slot = (book.day(sid), book.time(sid))
        for other, recs in book.records.items():
            if other == sid or not _slot_scene(book, other) or \
                    (book.day(other), book.time(other)) != slot:
                continue
            for o in recs:
                if o.type != 'at' or not o.verified:
                    continue
                r = first.get(book.who(o.who))
                here, there = (_at_place(book, r), _at_place(book, o)) if r else ('', '')
                if r and here and there and here != there:
                    findings.append(_finding(
                        'place', r.quote, other, o.quote,
                        f'{r.who} is at {book.place_names.get(here, here)} here and at '
                        f'{book.place_names.get(there, there)} in {other}, both day {slot[0]}, '
                        f'{slot[1]}'))
                    first.pop(book.who(o.who), None)
    # travel
    fastest = book.world.fastest() if book.world is not None else None
    untimed = 0
    for who, r in first.items():
        here = _at_place(book, r)
        if not here or book.day(sid) is None:
            continue
        prev = None
        for o in book.present_records(('at',)):
            if o.scene_id != sid and book.who(o.who) == who and _at_place(book, o) and \
                    book.before((o.scene_id, o.index), (sid, r.index)):
                prev = o
        if prev is None:
            continue
        there = _at_place(book, prev)
        if there == here or book.day(prev.scene_id) is None:
            continue
        dist = None
        for a in (book.place_names.get(there, there), there, prev.item):
            for b in (book.place_names.get(here, here), here, r.item):
                if a and b and dist is None:
                    dist = book.world.distance(a, b) if book.world is not None else None
        if dist is None or fastest is None:
            untimed += 1
            continue
        t0 = _DAY_FRACTION.get(book.time(prev.scene_id), 0.0)
        t1 = _DAY_FRACTION.get(book.time(sid), 1.0)
        days = book.day(sid) - book.day(prev.scene_id) + t1 - t0
        if days <= 0 or dist > fastest * days:
            findings.append(_finding(
                'travel', r.quote, prev.scene_id, prev.quote,
                f'{r.who} is at {book.place_names.get(here, here)} here, '
                f'{dist:g} m from {book.place_names.get(there, there)} in '
                f'{_where(book, prev.scene_id)}; world.csv\'s fastest travel is '
                f'{fastest:g} m a day, so it needs {dist / fastest:.1f} day(s)'))
    if untimed:
        notes.append(f'travel: {untimed} move(s) between places not checked (world.csv gives '
                     + ('no speed' if fastest is None else 'no distance between them') + ')')
    return findings, notes


# ============================================================================
# Time
# ============================================================================

_NUMBERS = {
    'a': 1, 'an': 1, 'one': 1, 'two': 2, 'three': 3, 'four': 4, 'five': 5, 'six': 6,
    'seven': 7, 'eight': 8, 'nine': 9, 'ten': 10, 'eleven': 11, 'twelve': 12,
    'thirteen': 13, 'fourteen': 14, 'fifteen': 15, 'sixteen': 16, 'seventeen': 17,
    'eighteen': 18, 'nineteen': 19, 'twenty': 20, 'thirty': 30, 'forty': 40, 'fifty': 50,
    'sixty': 60, 'hundred': 100, 'dozen': 12, 'a dozen': 12, 'a hundred': 100,
}
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
_NUM = r'(?P<n>\d+|(?:a |an )?(?:hundred|dozen)|' + '|'.join(
    sorted((k for k in _NUMBERS if ' ' not in k), key=len, reverse=True)) + r')'
_ORD = r'(?P<o>\d+(?:st|nd|rd|th)|' + '|'.join(sorted(_ORDINALS, key=len, reverse=True)) + r')'
_UNIT = r'(?P<u>' + '|'.join(sorted(_UNITS, key=len, reverse=True)) + r')s?'
_COUNT_RE = re.compile(rf'\b{_NUM}\s+(?:(?:full|whole|long|more)\s+)?{_UNIT}\b')
_ORDINAL_RE = re.compile(rf'\b{_ORD}\s+{_UNIT}\b')
_PAST = re.compile(r'\b(ago|since|later|after|past|gone|before this|earlier)\b')
_FUTURE = re.compile(r'^\s*(in|within)\b|\b(from now|hence|to come|more to)\b')
_VAGUE = re.compile(r'\b(few|several|some|many|countless|a couple|couple of|ages|years and)\b')


@dataclass
class Span:
    """What an elapsed-time phrase says: the days between the scene and the
    one the count runs from, `low` to `high` (a tolerance included), and
    whether the counted event is `past` or `future`."""
    low: float
    high: float
    direction: str


def parse_elapsed(phrase: str) -> tuple[Span | None, str]:
    """A phrase's `Span`, or None and why it can't be read (vague, no
    direction, no number)."""
    p = ' '.join((phrase or '').lower().replace('-', ' ').split())
    if _VAGUE.search(p):
        return None, 'a vague count'
    m = _ORDINAL_RE.search(p)
    if m and not _COUNT_RE.search(p[:m.start()]):
        o = m.group('o')
        n = int(re.match(r'\d+', o).group()) if o[0].isdigit() else _ORDINALS[o]
        unit = _UNITS[m.group('u')]
        if unit < 1:
            return None, 'an hour counted by ordinal'
        low = (n - 1) * unit
        high = n * unit - 1 if unit > 1 else low
        return Span(low, high, 'past'), ''
    m = _COUNT_RE.search(p)
    if not m:
        return None, 'no number of days, weeks, months or years'
    raw = m.group('n').strip()
    n = int(raw) if raw.isdigit() else _NUMBERS.get(raw, _NUMBERS.get(raw.split()[-1]))
    if n is None:
        return None, 'a number it can\'t read'
    unit = m.group('u')
    days = n * _UNITS[unit]
    if _FUTURE.search(p):
        direction = 'future'
    elif _PAST.search(p):
        direction = 'past'
    else:
        return None, 'no ago, since, later or in to say which way it counts'
    if unit == 'hour':
        low, high = float(int(days)), float(int(days)) + 1
    elif unit in ('month', 'moon'):
        tol = max(3, 3 * n)
        low, high = days - tol, days + tol
    elif unit in ('year', 'winter', 'summer'):
        tol = max(15, 15 * n)
        low, high = days - tol, days + tol
    elif unit in ('week', 'fortnight'):
        tol = max(1, n)
        low, high = days - tol, days + tol
    else:
        tol = 0 if days <= 3 else max(1, round(days / 10))
        low, high = days - tol, days + tol
    return Span(low, high, direction), ''


def check_time(book: Book) -> tuple[list[Finding], list[str]]:
    sid = book.scene_id
    from storyforge.elaborate import time_mode
    if book.off_present(sid):
        return [], []
    findings: list[Finding] = []
    unread, no_anchor, undated = [], 0, 0
    for r in book.records.get(sid, []):
        if r.type != 'elapsed' or not r.verified:
            continue
        span, why = parse_elapsed(r.value)
        if span is None:
            unread.append(f'"{r.value}" ({why})')
            continue
        anchor = r.item.strip()
        if not anchor or anchor not in book.order:
            no_anchor += 1
            continue
        if book.day(sid) is None or book.day(anchor) is None or \
                time_mode(book.row(anchor)) == 'summary' or book.off_present(anchor):
            undated += 1
            continue
        gap = (book.day(sid) - book.day(anchor) if span.direction == 'past'
               else book.day(anchor) - book.day(sid))
        if not span.low <= gap <= span.high:
            from storyforge.prompts import scene_when
            findings.append(_finding(
                'time', r.quote, CALENDAR, f'{anchor}: {scene_when(book.row(anchor))}',
                f'"{r.value}" counts from {anchor}, day {book.day(anchor)}; this scene is '
                f'day {book.day(sid)}, {abs(gap)} day(s) '
                f'{"after" if gap >= 0 else "before"} it'))
    notes = []
    if unread:
        notes.append(f'time: {len(unread)} elapsed-time phrase(s) the parser can\'t read, not '
                     f'checked: ' + '; '.join(unread[:5]))
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


def current_injuries(book: Book, at: tuple[str, int]) -> list[Record]:
    """The serious or disabling injuries in force at (scene, index): from
    present-time scenes before it, less those healed since, and a serious
    one past `SERIOUS_DAYS` story days (when both scenes have a day)."""
    live: dict[tuple[str, str, str], Record] = {}
    for r in book.present_records(('injury',)):
        if not book.before((r.scene_id, r.index), at):
            continue
        k = (book.who(r.who), part_key(r.item), _side(r))
        if r.value == 'healed':
            for key in list(live):
                if key[:2] == k[:2] and (not k[2] or key[2] == k[2]):
                    live.pop(key)
        elif r.value in ('serious', 'disabling'):
            live[k] = r
        else:
            live.pop(k, None)
    out = []
    for r in live.values():
        d0, d1 = book.day(r.scene_id), book.day(at[0])
        if r.value == 'serious' and d0 is not None and d1 is not None \
                and d1 - d0 > SERIOUS_DAYS:
            continue
        out.append(r)
    return out


def offered_injuries(book: Book) -> tuple[list[str], int]:
    live = current_injuries(book, (book.scene_id, -1))
    lines = [f'{r.who}: {_side(r) + " " if _side(r) else ""}{part_key(r.item)}, {r.value} '
             f'(since {r.scene_id})' for r in live]
    return lines[:MAX_OFFERED_INJURIES], max(0, len(lines) - MAX_OFFERED_INJURIES)


def check_injury(book: Book) -> tuple[list[Finding], list[str]]:
    sid = book.scene_id
    if book.off_present(sid):
        return [], []
    findings, unsided = [], 0
    done: set[tuple] = set()
    for r in book.records.get(sid, []):
        if r.type != 'uses' or r.value != 'full' or not r.verified:
            continue
        who, part, side = book.who(r.who), part_key(r.item), _side(r)
        for inj in current_injuries(book, (sid, r.index)):
            if book.who(inj.who) != who or part_key(inj.item) != part:
                continue
            iside = _side(inj)
            if iside and not side:
                unsided += 1
                continue
            if side and iside and side != iside:
                continue
            if (who, part, iside) in done:
                continue
            done.add((who, part, iside))
            where = 'earlier in this scene' if inj.scene_id == sid else _where(book, inj.scene_id)
            findings.append(_finding(
                'injury', r.quote, inj.scene_id, inj.quote,
                f'{r.who} uses the {(iside + " ") if iside else ""}{part} at full strength, '
                f'but it was {inj.value}ly injured {where} and nothing since heals it'))
    notes = []
    if unsided:
        notes.append(f'injury: {unsided} use(s) of a part injured on one side, with no side '
                     f'given, not checked')
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
    findings, notes = [], []
    lower_words = set(re.findall(r'\b[a-z][\w\']*\b', prose))
    for name, where in sorted(book.forbidden.items()):
        if book.known_names is not None and name.lower() in book.known_names:
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

_PLACE = r'(?:the\s+)?(?P<place>[^.,;:!?\n"“”]{1,40})'
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
                          r'sank)\s+in\s+the\s+(?P<place>north|south|east|west|north-?east|'
                          r'north-?west|south-?east|south-?west)\b', re.I)


def check_sky(book: Book, prose: str) -> tuple[list[Finding], list[str]]:
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
            if place[:1].isupper():
                unknown.append(f'"{quote}" ({place.split()[0]} is not in world.csv)')
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
    try:
        from storyforge import source
        cfg = source.read_config(project_dir)
    except Exception as e:   # noqa: BLE001 - a bad source block: say so, check the rest
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
    try:
        from storyforge import source
        cfg = source.read_config(project_dir)
        for proj in (cfg.projects if cfg else ()):
            rel = cfg.map_path(proj)
            if rel:
                nm = source.load_name_map(source.resolve(project_dir, rel))
                names |= {t.lower() for t in nm.replacements.values()}
                names |= {t.lower() for t in nm.id_names.values()}
    except Exception:   # noqa: BLE001 - forbidden_names reports an unreadable map
        pass
    tokens = {t for n in names for t in re.findall(r"[\w']+", n)}
    return names | tokens


def load_book(project_dir: str, scene_id: str, *, rows: list[dict] | None = None
              ) -> tuple[Book, list[str]]:
    """Everything the checks read but this scene's records, and notes on
    what couldn't be read (earlier scenes without typed state for their
    current prose, a name map). Raises ContinuityError on a malformed
    world table or scenes.csv."""
    from storyforge import ledger, typed_state, world_table
    from storyforge.elaborate import _read_csv, _read_csv_as_map
    from storyforge.enrich import load_alias_map
    ref = os.path.join(project_dir, 'reference')
    try:
        order = ledger.scene_order(project_dir)
        rows = ledger.load(project_dir) if rows is None else rows
        world = world_table.load(project_dir)
    except (ValueError, ledger.LedgerError, OSError) as e:
        raise ContinuityError(f'{scene_id}: {e}') from e
    scenes = _read_csv_as_map(os.path.join(ref, 'scenes.csv'))
    header = _read_csv(os.path.join(ref, 'scenes.csv'))
    places = load_alias_map(os.path.join(ref, 'locations.csv'))
    place_names = {}
    for r in _read_csv(os.path.join(ref, 'locations.csv')):
        pid = (r.get('id') or r.get('name') or '').strip()
        if pid:
            place_names[pid] = (r.get('name') or pid).strip()
    forbidden, notes = forbidden_names(project_dir)
    book = Book(scene_id, order, scenes, deaths=typed_state.registry_deaths(project_dir),
                chars=load_alias_map(os.path.join(ref, 'characters.csv')), places=places,
                place_names=place_names, world=world, rows=rows,
                briefs=_read_csv_as_map(os.path.join(ref, 'scene-briefs.csv')),
                has_frame_column=bool(header) and 'frame' in header[0],
                forbidden=forbidden, known_names=known_names(project_dir, rows))
    missing, stale = [], []
    for sid in sorted(order, key=order.get):
        if sid == scene_id or not os.path.isfile(os.path.join(project_dir, 'scenes', f'{sid}.md')):
            continue
        recs, why = typed_state.current(project_dir, sid)
        if recs is not None:
            for r in recs:
                r.scene_id = sid
            book.records[sid] = recs
        elif order[sid] < order.get(scene_id, 0):
            (stale if why else missing).append(sid if not why else f'{sid} ({why})')
    if missing:
        notes.append(f'{len(missing)} earlier scene(s) with prose have no typed state yet, so '
                     f'their facts weren\'t read (check them to add it): '
                     + ', '.join(missing[:8]) + (' ...' if len(missing) > 8 else ''))
    if stale:
        notes.append(f'{len(stale)} earlier scene(s)\' typed state not read: '
                     + '; '.join(stale[:5]) + (' ...' if len(stale) > 5 else ''))
    return book, notes


def run_checks(book: Book, prose: str, sheet_records: list[Record] | None = None
               ) -> tuple[list[Finding], list[str]]:
    """Every check on `book.scene_id`, its records in `book.records`. Pure:
    no model, no files. Findings whose quote isn't in `prose` are dropped
    (a record's verified quote always is) and counted."""
    findings, notes = [], []
    if book.off_present(book.scene_id):
        from storyforge.elaborate import frame, time_mode
        row = book.row(book.scene_id)
        notes.append(f'the scene is marked {frame(row) or time_mode(row)} (not the story\'s '
                     f'present): only names were checked')
    for check in (check_life, check_knowledge, lambda b: check_possession(b, sheet_records),
                  check_place, check_time, check_injury, lambda b: check_names(b, prose),
                  lambda b: check_sky(b, prose)):
        f, n = check(book)
        findings += f
        notes += n
    kept = [f for f in findings if quote_in(prose, f.scene_quote)]
    if len(kept) < len(findings):
        notes.append(f'{len(findings) - len(kept)} finding(s) quote words not in the scene: '
                     f'dropped')
    return kept, notes


def check_continuity(project_dir: str, scene_id: str, *, prose: str | None = None,
                     model: str | None = None, log_file: str = '', reuse: bool = True,
                     save: bool = True, rows: list[dict] | None = None) -> ContinuityResult:
    """Read `scene_id`'s typed state (one call; none when `reuse` and its
    file is of this prose), save it, and run every check.

    Raises:
        ContinuityError: no prose, a refusal or API failure, a reply off
            the schema twice, or a malformed world table or scenes.csv.
    """
    from storyforge import typed_state, world_table
    from storyforge.prompts import calendar_lines, live_order
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
    records, _ = typed_state.current(project_dir, scene_id, prose) if reuse else (None, '')
    if records is None:
        facts, cut_f = offered_facts(book)
        injuries, cut_i = offered_injuries(book)
        cast = sorted({(r.get('name') or r.get('id') or '').strip() for r in _registry(
            project_dir)} - {''})
        calendar = calendar_lines(live_order(book.order, book.scenes, scene_id), book.scenes,
                                  scene_id)
        model = typed_state.resolve_model(model)
        try:
            got = typed_state.extract(scene_id, prose, model=model, log_file=log_file,
                                      pov=book.pov(scene_id), cast=cast, calendar=calendar,
                                      facts=facts, injuries=injuries)
        except typed_state.TypedStateError as e:
            raise ContinuityError(str(e)) from e
        records = got.records
        result.notes += got.notes
        if cut_f:
            result.notes.append(f'knowledge: {cut_f} fact(s) past the {MAX_OFFERED_FACTS} '
                                f'offered not watched')
        if cut_i:
            result.notes.append(f'injury: {cut_i} injur(ies) past the {MAX_OFFERED_INJURIES} '
                                f'offered not watched')
        result.extracted = True
        if save:
            typed_state.write_state(project_dir, scene_id, prose, records, model=model)
    for r in records:
        r.scene_id = scene_id
    misquoted = sum(1 for r in records if not r.verified)
    if misquoted:
        result.notes.append(f'{misquoted} of {len(records)} record(s) quote words not in the '
                            f'scene: they make no finding')
    book.records[scene_id] = records
    result.records = records
    tracked = {object_key(r.item) for recs in book.records.values() for r in recs
               if r.type == 'holds'} - {''}
    sheet_records = []
    for sid in book.records:
        got, why = typed_state.sheet_holdings(project_dir, sid, tracked)
        sheet_records += [r for r in got if quote_in(prose, r.quote)] if sid == scene_id \
            else got
        if why:
            result.notes.append(f'possession: {why}')
    findings, more = run_checks(book, prose, sheet_records)
    result.findings = findings
    result.notes += more
    return result


def _registry(project_dir: str) -> list[dict]:
    from storyforge.elaborate import _read_csv
    return _read_csv(os.path.join(project_dir, 'reference', 'characters.csv'))


def overlaps(a: str, b: str) -> bool:
    """Whether two quotes are on the same words (one inside the other)."""
    x, y = normalize(a), normalize(b)
    return bool(x and y and (x in y or y in x))
