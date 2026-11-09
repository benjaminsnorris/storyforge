"""The stage sheet: blocking tracked as state, checked by code (#647, plan A4).

A film's continuity supervisor keeps a sheet: who is on the set, standing or
sitting, what each hand holds, what is worn, where the light is. The
whole-scene blocking read (`storyforge.blocking`, #626) asks a large model
to find slips by reading the scene twice; this asks a small one only to
*record* the stage, and code finds the slips.

1. **Extraction** (`extract`, one structured call on a small model,
   `select_model('extraction')`, or `STORYFORGE_STAGE_SHEET_MODEL`): each
   physical action in the scene becomes an event on the sheet in a fixed
   schema (`SCHEMA`): `posture: sitting -> standing`, `hand_right: the spear
   -> empty`, `worn: helm on -> off`, each with the scene's own words. An
   event's `from` is what *its own sentence* says the state was ("stood up"
   says he wasn't standing), never what the sheet says; a blank `from` is an
   observation ("he sat by the fire"). Every quote is verified
   (`quotes.quote_in`).
2. **Code checks the events** (`replay`, free): an event from a state the
   sheet doesn't hold is a finding (standing up when standing, a "free hand"
   with both hands full, taking off a cloak that's off, reading by a candle
   that went out, acting after leaving), as is a sun or a shadow against the
   time of day, or a face seen past sight range (`storyforge.world_table`).
3. **A narrow yes/no for the rest** (`ask`): actions that depend on where
   people and things are ("she reached the lamp behind her") come back from
   extraction as yes/no questions; a small model answers each against the
   sheet where the question's words stand in the prose, twice (`ASKINGS`),
   and a finding is kept only when both answers say it can't happen.
   Position and facing are recorded for these; code never compares them.

Findings are `checker.Finding`s with code `blocking.BLOCKING_CODE` (BLK)
against the scene itself, exactly as the blocking read's, so the gate
classifies, fixes and accepts them the same way (`gate._classify`,
`problems_to_fix`, `_accepted_blocking_covers`) and they stop only their own
scene (#641).

**What isn't checked is said.** A misquoted event (its states aren't
applied: what it touches becomes unknown), a slip against a carried state,
an event the sheet can't read or check (`Replay.skipped`), a misquoted or
empty question, a question past `MAX_QUESTIONS`, a split yes/no answer and
an empty extraction are not findings; each is counted in
`StageResult.notes`, which `check --blocking` reports and the gate logs.

**The sheet's file** (`working/stage-sheets/<scene>.json`, `FORMAT`): the
state at the opening, then each beat's changes, then the end state, in a
format a writer can produce too (#655: the writer keeps the sheet while
drafting and returns its end state after each scene; the code then compares
the two). See `write_sheet` / `load_sheet` / `states`. The opening is
carried over from the previous scene's sheet when that sheet was made from
the previous scene's current prose (`carried_opening`). A carried state is
shown to the yes/no asker but never makes a finding (a slip against one is
counted): a scene break allows any change, and only the writer's note
(#655) will say what carries.

The gate uses this in place of the blocking read when
`gate.GATE_BLOCKING_METHOD` is `stage-sheet` (`storyforge check
--stage-sheet`); the blocking read stays the default until the sheet matches
it on the blocking set (#646; `evals/suites/blocking_set_sheet.py`).
"""

from __future__ import annotations

import hashlib
import json
import os
import re
from dataclasses import dataclass, field, replace

from storyforge.blocking import BLOCKING_CODE
from storyforge.checker import Finding
from storyforge.quotes import quote_in

#: The sheet file's format version (`write_sheet`, `load_sheet`)
FORMAT = 1
SHEETS_DIR = os.path.join('working', 'stage-sheets')
#: Overrides the model for extraction and the yes/no questions
MODEL_ENV = 'STORYFORGE_STAGE_SHEET_MODEL'
#: How many times each yes/no question is asked; a finding needs every
#: answer to say the action can't happen
ASKINGS = 2
#: The most questions asked per scene (the rest are counted in the notes)
MAX_QUESTIONS = 20

#: The sheet's fields. Per person: posture, hands, what's worn, presence,
#: position, facing, what they make out. The scene's: lights, doors, time,
#: sun, shadows; and `break`, a gap in time (states end there)
PERSON_FIELDS = ('posture', 'hand_left', 'hand_right', 'hand_either', 'worn', 'present',
                 'position', 'facing', 'sees')
SCENE_FIELDS = ('light', 'door', 'time', 'sun', 'shadow', 'break')
FIELDS = PERSON_FIELDS + SCENE_FIELDS
POSTURES = ('standing', 'sitting', 'kneeling', 'lying', 'crouching', 'mounted', 'down', 'other')
HANDS = ('hand_left', 'hand_right')
EMPTY = 'empty'
#: The values each closed field takes (posture: `POSTURES`)
VALUES = {'worn': ('on', 'off'), 'present': ('here', 'gone'), 'light': ('lit', 'out'),
          'door': ('open', 'shut')}
_POSTURE_WORDS = {
    'stand': 'standing', 'stood': 'standing', 'upright': 'standing', 'on foot': 'standing',
    'seated': 'sitting', 'sit': 'sitting', 'sat': 'sitting',
    'kneel': 'kneeling', 'knelt': 'kneeling',
    'lie': 'lying', 'lay': 'lying', 'prone': 'lying', 'supine': 'lying', 'lying down': 'lying',
    'crouch': 'crouching', 'squatting': 'crouching', 'squat': 'crouching',
    'riding': 'mounted', 'on horseback': 'mounted', 'in the saddle': 'mounted',
}
_ARTICLES = {'the', 'a', 'an', 'his', 'her', 'their', 'its', 'my', 'your', 'our', 'some',
             'one', 'of', 'own'}

_EVENT = {
    'type': 'object',
    'properties': {
        'quote': {'type': 'string'},
        'who': {'type': 'string'},
        'field': {'type': 'string', 'enum': list(FIELDS)},
        'item': {'type': 'string'},
        'from': {'type': 'string'},
        'to': {'type': 'string'},
    },
    'required': ['quote', 'who', 'field', 'item', 'from', 'to'],
    'additionalProperties': False,
}
SCHEMA = {
    'type': 'object',
    'properties': {
        'cast': {'type': 'array', 'items': {'type': 'string'}},
        'events': {'type': 'array', 'items': _EVENT},
        'questions': {'type': 'array', 'items': {
            'type': 'object',
            'properties': {'quote': {'type': 'string'}, 'question': {'type': 'string'}},
            'required': ['quote', 'question'],
            'additionalProperties': False,
        }},
    },
    'required': ['cast', 'events', 'questions'],
    'additionalProperties': False,
}
ASK_SCHEMA = {
    'type': 'object',
    'properties': {'answers': {'type': 'array', 'items': {
        'type': 'object',
        'properties': {'n': {'type': 'integer'},
                       'answer': {'type': 'string', 'enum': ['yes', 'no']},
                       'why': {'type': 'string'}},
        'required': ['n', 'answer', 'why'],
        'additionalProperties': False,
    }}},
    'required': ['answers'],
    'additionalProperties': False,
}

PROMPT = """You are a film's continuity supervisor. Read one scene of a novel and record its stage sheet: who is present, their posture, what each hand holds, what each person wears, lights and doors, the time and the sun. You only record what the text says, sentence by sentence; code checks the sheet afterwards, so never fix or smooth over what you read.

## Scene: {scene_id}{pov_line}

{prose}

## What to record

`cast`: everyone physically present at any point, each under one name (the one the scene uses most). Use exactly these names in `who`.

`events`: every sentence that states or changes a physical state, in the scene's order. One event per state; a sentence with two gives two events with the same quote.
- `quote`: the scene's own words, copied exactly: the shortest clause that shows the state.
- `who`: a cast name; empty for lights, doors, the time, the sun, shadows and breaks.
- `field`, `item` and `to`, the state the sentence gives:
  - `posture`: `to` one of standing, sitting, kneeling, lying, crouching, mounted, other.
  - `hand_left`, `hand_right`: `to` what that hand now holds or grips, a short name used the same way every time ("spear", "her wrist"), or `empty`. Both hands on one thing: two events.
  - `hand_either`: a hand the text doesn't say is left or right ("his hand", "a free hand"); `to` as above.
  - `worn`: `item` what is worn or carried on the body (helm, cloak, gauntlets, sword at the hip); `to` `on` or `off`.
  - `present`: `to` `here` (comes in, arrives) or `gone` (leaves, goes out of the scene).
  - `position`: `to` where the person now is, in a few words, relative to people and things ("behind the cart", "at Ann's left").
  - `facing`: `to` what or whom the person now faces or looks toward.
  - `sees`: the person makes out a detail of someone or something; `item` `face` (a face, eyes, an expression) or `figure` (who someone is, by build or bearing); `from` where the viewer is, `to` where what is seen is, each as a place name.
  - `light`: `item` the light (candle, lamp, fire, torch); `to` `lit` or `out`.
  - `door`: `item` the door, gate, curtain or shutter; `to` `open` or `shut`.
  - `time`: `to` the time of day the scene states (dawn, morning, noon, afternoon, evening, dusk, night).
  - `sun`: `to` where the sun is: a compass direction, or the landmark the text puts it at ("behind the Tor": `the Tor`).
  - `shadow`: `to` the compass direction a shadow falls or points.
  - `break`: a gap in time or a section break in the text; `item` and `to` empty.
- `from` (except `sees`): the state THIS sentence itself says or implies there was just before, never what earlier sentences said. "He stood up": posture `from` `down`, `to` standing. "She set the cup down": hand `from` `cup`, `to` empty. "He waved with his free hand": `hand_either` `from` `empty`. "She took off her cloak": worn `from` on, `to` off. Posture `from` may be `down` (any posture but standing). When the sentence only describes a state ("He sat by the fire", "the spear in his right hand"), `from` is empty.

Record what the narration says happens now, not memories, dreams, plans, similes or what someone imagines.

`questions`: the fields can't record whether an action fits where people and things are, so write one yes/no question for EVERY action that depends on it: reaching, taking or handing something; striking, grabbing or passing someone; touching or breathing through armour or clothing; seeing or hearing past someone or something; anything done on a side or in an order that has to fit where people stand, sit or face. Ask even when it looks fine; another check answers them. Each question asks whether the action can happen as written, so that "yes" means it can: "Can Ann, seated at the rail, reach the lamp on the shelf behind her?". `quote` is the action's words.

Return every event in the scene's order."""

ASK_PROMPT = """You check whether physical actions in one scene of a novel can happen as written. Each question gives the action's words and the stage at that moment (who is present, posture, what each hand holds, what is worn, the light), as recorded so far; a state not listed is unknown. Answer `yes` when the action can happen as written, given the scene and the stage, and `no` only when it can't. When in doubt, `yes`. Give a one-sentence reason.

## Scene: {scene_id}

{prose}

## Questions

{questions}"""


class StageSheetError(RuntimeError):
    """The stage sheet could not be made or checked; the message says why."""


@dataclass(frozen=True)
class Event:
    quote: str
    who: str
    field: str
    item: str
    from_: str
    to: str
    verified: bool = True


#: Where a state on the sheet came from: this scene set it, or the previous
#: scene left it (never a finding: a scene break allows any change)
ORIGINS = ('scene', 'carried')
#: Who made a sheet file (`sheet_path` keeps them apart, #655 compares them)
SOURCES = ('extracted', 'writer')
#: The fields a state on the sheet can have: an event on the others
#: (`hand_either`, `sees`, `shadow`, `break`) changes or checks these, never
#: becomes a state itself
STATE_FIELDS = tuple(f for f in FIELDS if f not in ('hand_either', 'sees', 'shadow', 'break'))
#: The state fields whose `item` names a thing (one state per thing); the
#: rest are one state per person (or per scene) and their `item` is blank
ITEM_FIELDS = ('worn', 'light', 'door')


@dataclass(frozen=True)
class Entry:
    """One state on the sheet: (who, field, item) → value, set by `quote`.

    Every state on a sheet `replay` builds comes from a verified quote (a
    misquoted event's states are never applied: the keys it touches become
    unknown) or is carried from the previous scene. Build one from a file
    with `from_json`, which checks and normalizes it."""
    who: str
    field: str
    item: str
    value: str
    quote: str
    #: one of `ORIGINS`
    origin: str = 'scene'
    #: the index of the event that set it (-1: the opening)
    seq: int = -1
    #: a hand placed by an event that didn't say which hand ("she took the
    #: cup"), when either hand could have been it: the side is a guess, and a
    #: later event naming a side moves it to the other hand when that fits
    side_guessed: bool = False

    def key(self) -> tuple[str, str, str]:
        return (_who(self.who), self.field, _obj(self.item))

    def to_json(self) -> dict:
        out = {'who': self.who, 'field': self.field, 'item': self.item, 'value': self.value,
               'quote': self.quote}
        if self.origin != 'scene':
            out['origin'] = self.origin
        if self.side_guessed:
            out['side_guessed'] = True
        return out

    @classmethod
    def from_json(cls, it, where: str = 'the sheet') -> 'Entry':
        """An entry from a sheet file (an extractor's or a writer's), its
        value normalized (`posture`, the hand values, the closed values).
        Raises ValueError, naming `where`, for anything a replay couldn't
        have written: a field that isn't a state, an item on a field that
        has none, a value outside its field's list, an unknown origin."""
        def bad(why):
            return ValueError(f'an entry in {where} {why}: {it!r}'[:240])
        if not isinstance(it, dict):
            raise bad('is not an object')
        f = it.get('field')
        if f not in STATE_FIELDS:
            raise bad(f'has field {f!r}, not one of {", ".join(STATE_FIELDS)}')
        if not all(isinstance(it.get(k, ''), str) for k in ('who', 'item', 'value', 'quote')):
            raise bad('has a who, item, value or quote that is not text')
        who, item, raw = it.get('who', '').strip(), it.get('item', '').strip(), it.get('value', '')
        origin = it.get('origin', 'scene')
        if origin not in ORIGINS:
            raise bad(f'has origin {origin!r}, not one of {", ".join(ORIGINS)}')
        guessed = it.get('side_guessed', False)
        if not isinstance(guessed, bool) or (guessed and f not in HANDS):
            raise bad('has side_guessed on something that is not a hand')
        if item and f not in ITEM_FIELDS:
            raise bad(f'names an item on {f}, which has one state per '
                      f'{"person" if f in PERSON_FIELDS else "scene"}')
        if f in ITEM_FIELDS and not item:
            raise bad(f'names no item ({f} is one state per thing)')
        if (f in PERSON_FIELDS) != bool(who):
            raise bad('names no one' if f in PERSON_FIELDS else f'names someone on {f}')
        if f == 'posture':
            value = posture(raw)
        elif f in HANDS:
            value = _hand_value(raw)
        elif f in VALUES:
            value = _closed(f, raw)
        else:
            value = raw.strip()
        if not value:
            allowed = (', '.join(VALUES[f]) if f in VALUES
                       else 'a thing held or empty' if f in HANDS else 'a value')
            raise bad(f'has value {raw!r}, not {allowed}')
        return cls(who, f, item, value, it.get('quote', ''), origin=origin,
                   side_guessed=guessed)


@dataclass
class Slip:
    """What `replay` found: the event, and the state it breaks (None when
    the event is wrong on its own, e.g. a shadow toward the sun)."""
    event: Event
    against: Entry | None
    why: str
    kind: str = 'contradiction'


@dataclass
class Question:
    quote: str
    question: str
    #: the stage at that beat, as `render` gives it
    stage: str = ''


@dataclass
class Replay:
    opening: list[Entry]
    beats: list[dict]
    end: list[Entry]
    slips: list[Slip]
    #: slips made by a misquoted event: not findings
    unchecked: int = 0
    #: the stage before each event (index → `render`), for the questions
    stage_at: dict[int, str] = field(default_factory=dict)
    #: slips set against a state carried from the previous scene: not findings
    carried: int = 0
    #: misquoted events whose states were not applied (the keys they touched
    #: are unknown from there)
    unapplied: int = 0
    #: what else couldn't be checked: the reason → how many events
    skipped: dict[str, int] = field(default_factory=dict)

    def notes(self, events: int) -> list[str]:
        """What couldn't be checked, one line each (`StageResult.notes`)."""
        out = []
        if self.unapplied:
            out.append(f'{self.unapplied} of {events} event(s) quote words not in the scene: '
                       f'their states were not applied, so what they touched is unknown from '
                       f'there')
        if self.unchecked:
            out.append(f'{self.unchecked} possible slip(s) made by a misquoted event: not '
                       f'checked')
        if self.carried:
            out.append(f'{self.carried} possible slip(s) set against a state carried from the '
                       f'previous scene: not findings (a scene break allows any change)')
        out += [f'{n} {why}' for why, n in self.skipped.items()]
        return out


@dataclass
class StageResult:
    scene_id: str
    findings: list[Finding] = field(default_factory=list)
    unverified: list[Finding] = field(default_factory=list)
    #: what couldn't be checked, and why (never silent)
    notes: list[str] = field(default_factory=list)
    sheet: dict = field(default_factory=dict)
    events: int = 0
    asked: int = 0


# ============================================================================
# Normalizing
# ============================================================================

def _who(name: str) -> str:
    return ' '.join((name or '').lower().split())


def _obj(name: str) -> str:
    """An object's key: lower case, without articles and possessives."""
    words = re.findall(r"[\w']+", (name or '').lower())
    words = [w[:-2] if w.endswith("'s") else w for w in words]
    return ' '.join(w for w in words if w not in _ARTICLES)


def same_object(a: str, b: str) -> bool:
    """Two names for one object: the same key, or one's words all in the
    other's ("holly" and "the holly branch")."""
    x, y = _obj(a), _obj(b)
    if not x or not y:
        return False
    if x == y:
        return True
    xs, ys = set(x.split()), set(y.split())
    return xs <= ys or ys <= xs


def posture(value: str) -> str:
    """A `POSTURES` word for `value` ('' for none)."""
    v = ' '.join((value or '').lower().split())
    if not v:
        return ''
    if v in POSTURES:
        return v
    for words, p in sorted(_POSTURE_WORDS.items(), key=lambda kv: -len(kv[0])):
        if re.search(rf'(?<!\w){re.escape(words)}(?!\w)', v):
            return p
    for p in POSTURES:
        if p in v:
            return p
    return 'other'


def _posture_fits(said: str, held: str) -> bool:
    if 'other' in (said, held) or said == held:
        return True
    if 'down' in (said, held):
        return 'standing' not in (said, held)
    return False


def _hand_value(value: str) -> str:
    v = _obj(value)
    if v in ('', 'empty', 'nothing', 'free', 'none', 'bare'):
        return EMPTY if v else ''
    return value.strip()


#: Other words a model gives for a closed value
_CLOSED_WORDS = {
    'worn': {'worn': 'on', 'wearing': 'on', 'donned': 'on', 'put on': 'on',
             'removed': 'off', 'taken off': 'off', 'doffed': 'off', 'not worn': 'off'},
    'present': {'present': 'here', 'arrived': 'here', 'arrives': 'here', 'entered': 'here',
                'in': 'here', 'left': 'gone', 'away': 'gone', 'out': 'gone',
                'departed': 'gone', 'absent': 'gone', 'exited': 'gone'},
    'light': {'burning': 'lit', 'alight': 'lit', 'on': 'lit', 'kindled': 'lit',
              'extinguished': 'out', 'unlit': 'out', 'dark': 'out', 'off': 'out',
              'doused': 'out', 'snuffed': 'out'},
    'door': {'opened': 'open', 'ajar': 'open', 'closed': 'shut', 'locked': 'shut',
             'barred': 'shut', 'bolted': 'shut'},
}


def _closed(field_name: str, value: str) -> str:
    """The `VALUES` word `value` gives for a closed field ('' when none)."""
    v = ' '.join((value or '').lower().split())
    if v in VALUES.get(field_name, ()):
        return v
    return _CLOSED_WORDS.get(field_name, {}).get(v, '')


# ============================================================================
# Code checks the events
# ============================================================================

class _Sheet:
    def __init__(self, opening: list[Entry]):
        self.states: dict[tuple[str, str, str], Entry] = {e.key(): e for e in opening}

    def get(self, who: str, field_name: str, item: str = '') -> Entry | None:
        return self.states.get((_who(who), field_name, _obj(item)))

    def find_item(self, who: str, field_name: str, item: str) -> Entry | None:
        """The entry for `item` or another name for it (`same_object`)."""
        exact = self.get(who, field_name, item)
        if exact:
            return exact
        for (w, f, i), e in self.states.items():
            if w == _who(who) and f == field_name and same_object(i, item):
                return e
        return None

    def put(self, e: Entry) -> None:
        self.states[e.key()] = e

    def drop(self, who: str, field_name: str, item: str = '') -> None:
        self.states.pop((_who(who), field_name, _obj(item)), None)

    def entries(self) -> list[Entry]:
        return list(self.states.values())


def _binding(e: Entry | None) -> bool:
    """A state that can make a finding: one this scene set (every state on
    the sheet is from a verified quote, or carried)."""
    return e is not None and e.origin == 'scene'


def render(entries: list[Entry]) -> str:
    """The stage as lines a model reads: per person, then the scene's."""
    people: dict[str, list[str]] = {}
    scene: list[str] = []
    for e in entries:
        if e.field in ('break', 'sees'):
            continue
        what = {'hand_left': 'left hand', 'hand_right': 'right hand'}.get(e.field, e.field)
        if e.side_guessed:
            what = f'{what} (or the other)'
        text = f'{what}{" " + e.item if e.item else ""}: {e.value}'
        if e.who:
            people.setdefault(e.who, []).append(text)
        else:
            scene.append(text)
    lines = [f'- {who}: ' + '; '.join(parts) for who, parts in people.items()]
    lines += [f'- {part}' for part in scene]
    return '\n'.join(lines) or '- (nothing recorded yet)'


#: Why an event wasn't checked (`Replay.skipped`): each becomes a note line
NO_ONE = 'event(s) for a person with no one named: not recorded'
NO_ITEM = 'worn, light or door event(s) with no item named: not recorded'
UNREADABLE = 'event(s) with a value the sheet can\'t read: not recorded'
SKY_PLACE = ('sun or shadow event(s) at a place the world table doesn\'t place '
             '(reference/world.csv `direction`): not checked')
SKY_NO_TIME = 'sun or shadow event(s) with no time of day known: not checked'
SKY_ODD_TIME = 'sun or shadow event(s) at a time of day the world table doesn\'t know: not checked'
SKY_NIGHT = 'sun or shadow event(s) at night: not checked (a time question, not blocking)'
SIGHT_DETAIL = 'sighting(s) of a detail with no sight range: not checked'
SIGHT_FAR = ('sighting(s) between places with no distance in reference/world.csv: '
             'not checked')


def replay(events: list[Event], *, opening: list[Entry] | None = None, world=None,
           time_of_day: str = '') -> Replay:
    """Apply `events` in order to the sheet that starts at `opening`, and
    check each against it. Pure: no model, no files.

    A misquoted event (`verified` False) is checked against nothing and its
    states aren't applied: the keys it would change become unknown (a
    paraphrase may stand for a real change, which an unchanged sheet would
    then flag). A slip set against a carried state isn't a finding. Both are
    counted (`Replay.notes`), as is every event that couldn't be read or
    checked (`Replay.skipped`).

    `time_of_day` is the scene's (scenes.csv), used when the scene states
    none; `world` a `world_table.World` (the defaults when None).
    """
    from storyforge.world_table import World, angle, opposite, SUN_DOWN
    world = world or World()
    opening = list(opening or [])
    sheet = _Sheet(opening)
    slips: list[Slip] = []
    beats: list[dict] = []
    counts = {'unchecked': 0, 'carried': 0, 'unapplied': 0}
    skipped: dict[str, int] = {}
    stage_at: dict[int, str] = {}
    scene_time = time_of_day.strip()

    def skip(why: str) -> None:
        skipped[why] = skipped.get(why, 0) + 1

    def slip(ev: Event, against: Entry | None, why: str, kind: str = 'contradiction') -> None:
        if not ev.verified:
            counts['unchecked'] += 1
        elif against is not None and against.origin != 'scene':
            counts['carried'] += 1
        else:
            slips.append(Slip(ev, against, why, kind))

    def entry(ev: Event, field_name: str, value: str, item: str = '', who: str | None = None,
              guessed: bool = False) -> Entry:
        return Entry(ev.who if who is None else who, field_name, item, value, ev.quote, seq=i,
                     side_guessed=guessed)

    for i, ev in enumerate(events):
        stage_at[i] = render(sheet.entries())
        before = dict(sheet.states)
        cleared = False
        who = ev.who.strip()
        f = ev.field
        name = who or 'someone'

        if f in PERSON_FIELDS and not who:
            skip(NO_ONE)
        if who and f not in ('present', 'position'):
            gone = sheet.get(who, 'present')
            if gone is not None and gone.value == 'gone':
                slip(ev, gone, f'{name} acts here after leaving')
                if not _binding(gone):
                    # counted once: the person is evidently back
                    sheet.drop(who, 'present')

        if f == 'break':
            kept = [e for e in sheet.entries() if e.field == 'worn']
            sheet = _Sheet(kept)
            cleared = True
        elif f == 'posture' and who:
            said, to = posture(ev.from_), posture(ev.to)
            held = sheet.get(who, 'posture')
            if held is not None:
                if said and not _posture_fits(said, held.value):
                    slip(ev, held, f'{name} {_moves(said, to)}, but is {held.value}')
                elif not said and to and not _posture_fits(to, held.value):
                    slip(ev, held, f'{name} is {to} with nothing between, but was {held.value}')
            if to:
                sheet.put(entry(ev, 'posture', to))
        elif f in HANDS and who:
            _named_hand(ev, sheet, slip, entry, name, settle=ev.verified)
        elif f == 'hand_either' and who:
            _either_hand(ev, sheet, slip, entry, name)
        elif f in ('worn', 'present', 'light', 'door') and (who or f in ('light', 'door')):
            said, to = _closed(f, ev.from_), _closed(f, ev.to)
            if (ev.from_.strip() and not said) or (ev.to.strip() and not to):
                skip(UNREADABLE)
            if f != 'present' and not ev.item.strip():
                skip(NO_ITEM)
            elif f == 'present':
                held = sheet.get(who, 'present')
                if held is not None and said and said != held.value:
                    slip(ev, held, f'{name} {"leaves" if said == "here" else "arrives"}, but '
                                   f'is already {held.value}')
                if to:
                    sheet.put(entry(ev, 'present', to))
            else:
                owner = who if f == 'worn' else ''
                held = sheet.find_item(owner, f, ev.item)
                what = ev.item.strip()
                if held is not None:
                    if said and said != held.value:
                        slip(ev, held, f'{name} {"takes off" if said == "on" else "puts on"} '
                                       f'{what}, which is already {held.value}' if f == 'worn'
                             else f'{what} goes from {said}, but is {held.value}')
                    elif not said and to and to != held.value:
                        slip(ev, held, f'{name} has {what} {to} with nothing between, but it '
                                       f'was {held.value}' if f == 'worn'
                             else f'{what} is {to} with nothing between, but was '
                                  f'{held.value}')
                if to:
                    sheet.put(entry(ev, f, to, held.item if held else what, who=owner))
        elif f in ('position', 'facing') and who and ev.to.strip():
            sheet.put(entry(ev, f, ev.to.strip()))
        elif f == 'time' and ev.to.strip():
            sheet.put(entry(ev, 'time', ev.to.strip(), who=''))
        elif f in ('sun', 'shadow') and ev.to.strip():
            where = world.direction(ev.to)
            time_e, sun_e = sheet.get('', 'time'), sheet.get('', 'sun')
            # the time a finding can rest on: this scene's own, else scenes.csv;
            # a carried time only to count what it would have flagged
            if _binding(time_e):
                when, basis = time_e.value, time_e
            elif scene_time:
                when, basis = scene_time, None
            elif time_e is not None:
                when, basis = time_e.value, time_e
            else:
                when, basis = '', None
            expected = world.sun(when) if when else None
            no_sun = (SKY_NO_TIME if not when else SKY_ODD_TIME if expected is None
                      else SKY_NIGHT if expected == SUN_DOWN else '')
            if not where:
                skip(SKY_PLACE)
            elif f == 'sun':
                if no_sun:
                    skip(no_sun)
                elif angle(where, expected) > 90:
                    slip(ev, basis, f'the sun is {where} at {when}, when it is {expected}',
                         kind='impossible')
                sheet.put(entry(ev, 'sun', where, who=''))
            else:
                if _binding(sun_e):
                    sun, against = sun_e.value, sun_e
                elif not no_sun and (basis is None or _binding(basis)):
                    sun, against = expected, basis
                elif sun_e is not None:
                    sun, against = sun_e.value, sun_e
                elif not no_sun:
                    sun, against = expected, basis
                else:
                    sun, against = None, None
                    skip(no_sun)
                if sun and angle(where, opposite(sun)) > 90:
                    slip(ev, against, f'a shadow falls {where} with the sun in the {sun}',
                         kind='impossible')
        elif (f in ('sun', 'shadow', 'time', 'position', 'facing') and not ev.to.strip()
              and (who or f not in PERSON_FIELDS)):
            skip(UNREADABLE)
        elif f == 'sees' and who:
            detail = ev.item.strip().lower() or 'face'
            rng = world.sight(detail)
            far = world.distance(ev.from_, ev.to) if rng else None
            if not rng:
                skip(SIGHT_DETAIL)
            elif not far:
                skip(SIGHT_FAR)
            elif far > rng:
                slip(ev, None, f'{name} makes out a {detail} {far:g} m away; a {detail} can '
                               f'be made out at {rng:g} m', kind='impossible')

        if not ev.verified:
            # not applied: what it touched is unknown from here
            touched = [k for k in set(before) | set(sheet.states)
                       if before.get(k) is not sheet.states.get(k)]
            if cleared:
                sheet = _Sheet(list(before.values()))
                touched = [k for k, e in before.items() if e.field != 'worn']
                cleared = False
            for k in touched:
                sheet.states.pop(k, None)
            if touched:
                counts['unapplied'] += 1
        beat = {'quote': ev.quote, 'event': _event_json(ev),
                'set': [e.to_json() for k, e in sheet.states.items() if before.get(k) is not e]}
        gone_keys = [k for k in before if k not in sheet.states
                     and not (cleared and before[k].field != 'worn')]
        if gone_keys:
            beat['unknown'] = [{'who': before[k].who, 'field': before[k].field,
                                'item': before[k].item} for k in gone_keys]
        if cleared:
            beat['cleared'] = True
        beats.append(beat)
    return Replay(opening, beats, sheet.entries(), slips, counts['unchecked'], stage_at,
                  carried=counts['carried'], unapplied=counts['unapplied'], skipped=skipped)


def _moves(said: str, to: str) -> str:
    if to and to != said:
        return f'goes from {said} to {to}'
    return f'moves as if {said}'


def _hand_fits(said: str, held: str) -> bool:
    if said == EMPTY or held == EMPTY:
        return said == held
    return same_object(said, held)


def _hand_needs(said: str) -> str:
    return 'needs to be free' if said == EMPTY else f'lets go of {said}'


def _other(hand: str) -> str:
    return 'hand_right' if hand == 'hand_left' else 'hand_left'


def _slot_fits(e: Entry | None, said: str, to: str) -> bool:
    """Whether a hand in state `e` (None: unknown) fits an event that says
    it held `said` before, or (with no `said`) holds `to`."""
    if e is None:
        return True
    if said:
        return _hand_fits(said, e.value)
    if to == EMPTY:
        return e.value == EMPTY
    if to:
        return e.value == EMPTY or same_object(to, e.value)
    return True


def _holding(e: Entry | None, thing: str) -> bool:
    return e is not None and e.value != EMPTY and same_object(thing, e.value)


def _against(*hands: Entry | None) -> Entry | None:
    """The hand state a slip is set against: the latest this scene set,
    else the latest (carried)."""
    known = [h for h in hands if h is not None]
    scene = [h for h in known if _binding(h)]
    return max(scene or known, key=lambda e: e.seq) if known else None


def _named_hand(ev: Event, sheet: _Sheet, slip, entry, name: str, settle: bool) -> None:
    """A hand the text names as left or right. A guessed side
    (`Entry.side_guessed`) that the event shows was the other hand is
    swapped first (`settle`: only for a verified event); naming one hand
    settles the other's side too."""
    f, o = ev.field, _other(ev.field)
    said, to = _hand_value(ev.from_), _hand_value(ev.to)
    mine, theirs = sheet.get(ev.who, f), sheet.get(ev.who, o)
    thing = said if said and said != EMPTY else to if to and to != EMPTY and not said else ''
    if settle and ((mine is not None and mine.side_guessed)
                   or (theirs is not None and theirs.side_guessed)) and (
            # this hand can't be the one, the other can
            (not _slot_fits(mine, said, to) and _slot_fits(theirs, said, to))
            # or the other, a guess, holds what this event names, and this
            # hand isn't known to
            or (thing and theirs is not None and theirs.side_guessed
                and _holding(theirs, thing) and not _holding(mine, thing)
                and (mine is None or mine.side_guessed or mine.value == EMPTY))):
        # the guessed hand was the other one
        sheet.drop(ev.who, f)
        sheet.drop(ev.who, o)
        if theirs is not None:
            sheet.put(replace(theirs, field=f, side_guessed=False))
        if mine is not None:
            sheet.put(replace(mine, field=o, side_guessed=False))
    held = sheet.get(ev.who, f)
    side = 'left' if f == 'hand_left' else 'right'
    if held is not None:
        if said and not _hand_fits(said, held.value):
            slip(ev, held, f'{name}\'s {side} hand {_hand_needs(said)}, but it holds '
                           f'{held.value}')
        elif (not said and to and to != EMPTY and held.value != EMPTY
              and not same_object(to, held.value)):
            slip(ev, held, f'{name}\'s {side} hand holds {to}, but it already holds '
                           f'{held.value}')
    if to:
        sheet.put(entry(ev, f, to))
    if settle:
        other = sheet.get(ev.who, o)
        if other is not None and other.side_guessed:
            sheet.put(replace(other, side_guessed=False))


def _either_hand(ev: Event, sheet: _Sheet, slip, entry, name: str) -> None:
    """A hand the text doesn't name as left or right ("she took the cup",
    "a free hand"). It takes the hand that fits: the one holding what it
    lets go of, else a free hand, else a hand not known. When either could
    be it, the left takes it with `side_guessed`, and a later event naming a
    side settles it (`_named_hand`). Only when no hand fits (both hold
    other things) is it a slip; a known state is never forgotten."""
    said, to = _hand_value(ev.from_), _hand_value(ev.to)
    slots = {h: sheet.get(ev.who, h) for h in HANDS}
    left, right = slots['hand_left'], slots['hand_right']
    hand, many = None, False
    if said and said != EMPTY:
        # lets go of `said`: the hand holding it, else a hand not known
        holding = [h for h, e in slots.items() if _holding(e, said)]
        unknown = [h for h, e in slots.items() if e is None]
        pick = holding or unknown
        if pick:
            hand, many = pick[0], len(pick) > 1
        else:
            slip(ev, _against(left, right), f'{name} lets go of {said}, but the left holds '
                                            f'{left.value} and the right {right.value}')
    elif said == EMPTY or to:
        # needs a free hand, or is seen holding `to`
        holding = [h for h, e in slots.items() if to and to != EMPTY and _holding(e, to)]
        free = [h for h, e in slots.items() if e is not None and e.value == EMPTY]
        unknown = [h for h, e in slots.items() if e is None]
        pick = holding or (free + unknown)
        if pick:
            hand, many = pick[0], len(pick) > 1 and not holding
        else:
            what = ('uses a free hand' if said == EMPTY or to == EMPTY
                    else f'takes {to} in a hand')
            slip(ev, _against(left, right), f'{name} {what}, but the left holds {left.value} '
                                            f'and the right {right.value}')
    if not to:
        return
    if hand is None:
        # a slip was found (or carried): the hand that takes it is the one
        # not set by this scene, else the one set longer ago; a guess
        carried = [h for h, e in slots.items() if not _binding(e)]
        hand = carried[0] if carried else min(slots, key=lambda h: slots[h].seq)
        many = True
    other = slots[_other(hand)]
    guessed = many or (slots[hand] is not None and slots[hand].side_guessed) \
        or (other is not None and other.side_guessed)
    sheet.put(entry(ev, hand, to, guessed=guessed))


def _event_json(ev: Event) -> dict:
    out = {'who': ev.who, 'field': ev.field, 'item': ev.item, 'from': ev.from_, 'to': ev.to}
    if not ev.verified:
        out['verified'] = False
    return out


def to_finding(scene_id: str, s: Slip) -> Finding:
    """A slip as a blocking finding (BLK, against the scene itself). With
    nothing to set it against, it is set against its own sentence, as the
    blocking read's one-sided findings are (`gate._classify` reads it)."""
    other = s.against.quote if s.against is not None and s.against.quote else s.event.quote
    return Finding(kind='contradiction', code=BLOCKING_CODE, scene_quote=s.event.quote,
                   established_scene=scene_id, established_quote=other, fact_id='',
                   explanation=f'({s.kind}, stage sheet) {s.why}.')


# ============================================================================
# Extraction
# ============================================================================

def build_prompt(scene_id: str, prose: str, pov: str = '') -> str:
    pov_line = f'\n\nPoint of view: {pov}' if pov.strip() else ''
    return PROMPT.format(scene_id=scene_id, pov_line=pov_line, prose=prose.strip())


def parse(text: str) -> tuple[list[str], list[dict], list[dict]]:
    """(cast, events, questions) from the reply. Raises ValueError when it
    isn't the schema."""
    try:
        data = json.loads(text)
        cast, events, questions = data['cast'], data['events'], data['questions']
    except (TypeError, ValueError, KeyError) as e:
        raise ValueError(f'reply is not the schema ({e})') from e
    if not all(isinstance(x, list) for x in (cast, events, questions)):
        raise ValueError('cast, events and questions must be lists')
    for ev in events:
        if (not isinstance(ev, dict) or ev.get('field') not in FIELDS
                or not all(isinstance(ev.get(k), str)
                           for k in ('quote', 'who', 'item', 'from', 'to'))):
            raise ValueError(f'an event is not the schema: {ev!r}'[:200])
    for q in questions:
        if not (isinstance(q, dict) and isinstance(q.get('quote'), str)
                and isinstance(q.get('question'), str)):
            raise ValueError(f'a question is not the schema: {q!r}'[:200])
    return [c for c in cast if isinstance(c, str)], events, questions


def max_tokens(prose: str) -> int:
    """Room for a dense scene's events (about one per ten words, 60 tokens
    each; `api` adds its thinking allowance on top)."""
    return min(32000, 6000 + len(prose.split()) * 6)


def resolve_model(model: str | None = None) -> str:
    from storyforge.common import select_model
    return model or os.environ.get(MODEL_ENV) or select_model('extraction')


def _call(prompt: str, model: str, log_file: str, tokens: int, schema: dict, label: str,
          check, what: str):
    """One structured call, retried once on an unusable reply. Raises
    StageSheetError on a refusal, an API failure, or a second bad reply."""
    from storyforge import api
    for attempt in (1, 2):
        try:
            if log_file:
                response = api.invoke_to_file(prompt, model, log_file, tokens,
                                              output_schema=schema, label=label)
            else:
                response = api.invoke(prompt, model, tokens, output_schema=schema, label=label)
            if api.is_truncated(response):
                raise ValueError('the reply hit its token limit')
            return check(api.extract_text(response))
        except ValueError as e:
            if attempt == 2:
                raise StageSheetError(f'{what} failed twice: {e}') from e
            prompt = prompt + f'\n\nYour last answer was not usable: {e}. Answer in the schema.'
        except RuntimeError as e:   # RefusalError, an API failure
            raise StageSheetError(f'{what} failed: {e}') from e
    raise AssertionError('unreachable')


#: A scene at least this long with no event at all is asked again once: a
#: small model that gives up on a dense scene returns empty lists, which
#: would read as a clean scene
EMPTY_RETRY_WORDS = 80
_EMPTY_NUDGE = ('\n\nYour last answer recorded no events, but this scene is {words} words '
                'long. Record every sentence that states or changes a physical state.')


@dataclass
class Extraction:
    """What `extract` read from a scene: its cast, events (each quote
    verified) and the questions to ask, with what was left out."""
    cast: list[str]
    events: list[Event]
    questions: list[Question]
    #: questions whose quote isn't in the scene (not asked)
    misquoted_questions: int = 0
    #: questions with a quote but no question (not asked)
    empty_questions: int = 0
    #: the scene has `EMPTY_RETRY_WORDS` or more, and both replies had no event
    no_events: bool = False


def extract(scene_id: str, prose: str, *, pov: str = '', model: str,
            log_file: str = '') -> Extraction:
    """The scene's cast, events and questions, each quote verified. A scene
    of `EMPTY_RETRY_WORDS` or more with no event is asked once more
    (`Extraction.no_events` when that reply has none either)."""
    prompt = build_prompt(scene_id, prose, pov)
    what = f'{scene_id}: the stage sheet extraction'
    cast, items, qs = _call(prompt, model, log_file, max_tokens(prose), SCHEMA,
                            f'stage sheet {scene_id}', parse, what)
    words = len(prose.split())
    no_events = False
    if not items and words >= EMPTY_RETRY_WORDS:
        again = ''
        if log_file:
            stem, ext = os.path.splitext(log_file)
            again = f'{stem}.again{ext}'
        cast, items, qs = _call(prompt + _EMPTY_NUDGE.format(words=words), model, again,
                                max_tokens(prose), SCHEMA, f'stage sheet {scene_id}', parse,
                                what)
        no_events = not items
    events = [Event(quote=it['quote'].strip(), who=it['who'].strip(), field=it['field'],
                    item=it['item'].strip(), from_=it['from'].strip(), to=it['to'].strip(),
                    verified=bool(it['quote'].strip()) and quote_in(prose, it['quote']))
              for it in items]
    out = Extraction(cast, events, [], no_events=no_events)
    for q in qs:
        if not (q['quote'].strip() and quote_in(prose, q['quote'])):
            out.misquoted_questions += 1
        elif not q['question'].strip():
            out.empty_questions += 1
        else:
            out.questions.append(Question(q['quote'].strip(), q['question'].strip()))
    return out


# ============================================================================
# The yes/no fallback
# ============================================================================

def build_ask_prompt(scene_id: str, prose: str, questions: list[Question],
                     asking: int = 1) -> str:
    """The questions, numbered from 1 in `questions`' order. A later asking
    lists them in reverse, and says which it is, so it is its own request
    and the order doesn't lean every answer the same way."""
    order = list(enumerate(questions, start=1))
    if asking > 1:
        order.reverse()
    blocks = [f'{n}. At: "{q.quote}"\n   The stage then:\n'
              + '\n'.join(f'   {line}' for line in (q.stage or '- (nothing recorded yet)')
                          .splitlines())
              + f'\n   Question: {q.question}' for n, q in order]
    text = ASK_PROMPT.format(scene_id=scene_id, prose=prose.strip(),
                             questions='\n\n'.join(blocks))
    if asking > 1:
        text += f'\n\nThis is independent asking {asking}: answer each question afresh.'
    return text


def parse_answers(text: str, count: int) -> dict[int, tuple[str, str]]:
    """n → (answer, why) for questions 1..count, each answered exactly once.
    Raises ValueError otherwise."""
    try:
        items = json.loads(text)['answers']
    except (TypeError, ValueError, KeyError) as e:
        raise ValueError(f'reply is not the schema ({e})') from e
    out: dict[int, tuple[str, str]] = {}
    for it in items if isinstance(items, list) else []:
        if not (isinstance(it, dict) and isinstance(it.get('n'), int)
                and it.get('answer') in ('yes', 'no') and isinstance(it.get('why'), str)):
            raise ValueError(f'an answer is not the schema: {it!r}'[:200])
        if it['n'] in out:
            raise ValueError(f'question {it["n"]} is answered twice')
        out[it['n']] = (it['answer'], it['why'].strip())
    missing = [n for n in range(1, count + 1) if n not in out]
    extra = [n for n in out if not 1 <= n <= count]
    if missing or extra:
        raise ValueError(f'answers must cover questions 1 to {count} exactly '
                         f'(missing {missing}, extra {extra})')
    return out


def ask(scene_id: str, prose: str, questions: list[Question], *, model: str,
        log_file: str = '', askings: int = ASKINGS) -> tuple[list[tuple[Question, str]], int]:
    """Ask every question `askings` times. Returns the questions every
    asking answered `no` (with the first asking's reason), and how many got
    split answers (not findings; counted in the notes)."""
    if not questions:
        return [], 0
    answers = []
    for n in range(1, askings + 1):
        log = log_file
        if n > 1 and log_file:
            stem, ext = os.path.splitext(log_file)
            log = f'{stem}.a{n}{ext}'
        answers.append(_call(build_ask_prompt(scene_id, prose, questions, n), model, log,
                             600 + 120 * len(questions), ASK_SCHEMA,
                             f'stage questions {scene_id}',
                             lambda t: parse_answers(t, len(questions)),
                             f'{scene_id}: the stage sheet questions'))
    no, split = [], 0
    for i, q in enumerate(questions, start=1):
        said = [a[i][0] for a in answers]
        if all(s == 'no' for s in said):
            no.append((q, answers[0][i][1]))
        elif 'no' in said:
            split += 1
    return no, split


# ============================================================================
# The sheet's file
# ============================================================================

def sheet_path(project_dir: str, scene_id: str, source: str = 'extracted') -> str:
    """Where a scene's sheet from `source` lives: `<scene>.json` for the
    extractor's, `<scene>.<source>.json` for another (#655's writer), so
    the two never overwrite each other."""
    if source not in SOURCES:
        raise ValueError(f'source must be one of {", ".join(SOURCES)}, not {source!r}')
    name = f'{scene_id}.json' if source == 'extracted' else f'{scene_id}.{source}.json'
    return os.path.join(project_dir, SHEETS_DIR, name)


def prose_hash(prose: str) -> str:
    return hashlib.sha256(prose.strip().encode('utf-8')).hexdigest()


def build_sheet(scene_id: str, prose: str, r: Replay, *, source: str = 'extracted',
                model: str = '', cast: list[str] | None = None) -> dict:
    return {'format': FORMAT, 'scene_id': scene_id, 'source': source, 'model': model,
            'prose_sha256': prose_hash(prose), 'cast': list(cast or []),
            'opening': [e.to_json() for e in r.opening], 'beats': r.beats,
            'end': [e.to_json() for e in r.end]}


def write_sheet(project_dir: str, sheet: dict) -> str:
    """Write a sheet (LF, sorted keys) at its source's path. Returns it."""
    path = sheet_path(project_dir, sheet['scene_id'], sheet.get('source', 'extracted'))
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, 'w', encoding='utf-8', newline='\n') as f:
        json.dump(sheet, f, indent=1, ensure_ascii=False, sort_keys=True)
        f.write('\n')
    return path


def _entries(items, where: str) -> list[Entry]:
    if not isinstance(items, list):
        raise ValueError(f'{where} is not a list')
    return [Entry.from_json(it, where) for it in items]


def _unknown_keys(items, where: str) -> list[tuple[str, str, str]]:
    """A beat's `unknown` list: the states it made unknown, as keys."""
    if not isinstance(items, list):
        raise ValueError(f'{where} is not a list')
    out = []
    for it in items:
        if not (isinstance(it, dict) and it.get('field') in STATE_FIELDS
                and all(isinstance(it.get(k, ''), str) for k in ('who', 'item'))):
            raise ValueError(f'an entry in {where} is not a state\'s key: {it!r}'[:200])
        out.append((_who(it.get('who', '')), it['field'], _obj(it.get('item', ''))))
    return out


def load_sheet(path: str) -> dict:
    """A sheet file, checked against `FORMAT` (every entry through
    `Entry.from_json`). Raises ValueError (naming the file) when it isn't
    one; OSError when it can't be read."""
    with open(path, encoding='utf-8') as f:
        try:
            data = json.load(f)
        except ValueError as e:
            raise ValueError(f'{path}: not JSON ({e})') from e
    try:
        if not isinstance(data, dict) or data.get('format') != FORMAT:
            raise ValueError(f'format is not {FORMAT}')
        if not isinstance(data.get('scene_id'), str) or not data['scene_id']:
            raise ValueError('no scene_id')
        if data.get('source', 'extracted') not in SOURCES:
            raise ValueError(f'source is {data.get("source")!r}, not one of '
                             f'{", ".join(SOURCES)}')
        _entries(data.get('opening', []), 'opening')
        _entries(data.get('end', []), 'end')
        if not isinstance(data.get('beats', []), list):
            raise ValueError('beats is not a list')
        for b in data.get('beats', []):
            if not isinstance(b, dict):
                raise ValueError('a beat is not an object')
            _entries(b.get('set', []), 'a beat')
            _unknown_keys(b.get('unknown', []), 'a beat\'s unknown')
    except ValueError as e:
        raise ValueError(f'{path}: {e}') from e
    return data


def states(sheet: dict) -> list[list[Entry]]:
    """The state at the opening, then after each beat (`cleared` ends every
    state but what's worn; a beat's `unknown` keys are no longer known; its
    `set` entries replace their keys)."""
    current = {e.key(): e for e in _entries(sheet.get('opening', []), 'opening')}
    out = [list(current.values())]
    for b in sheet.get('beats', []):
        if b.get('cleared'):
            current = {k: e for k, e in current.items() if e.field == 'worn'}
        for k in _unknown_keys(b.get('unknown', []), 'a beat\'s unknown'):
            current.pop(k, None)
        for e in _entries(b.get('set', []), 'a beat'):
            current[e.key()] = e
        out.append(list(current.values()))
    return out


def carried_opening(project_dir: str, scene_id: str) -> tuple[list[Entry], str]:
    """The previous scene's end state, carried (`origin` `carried`), from
    its extracted sheet, and a note when there is a previous scene but its
    sheet can't be used ('' when carried, or when this is the first scene).
    A writer's sheet (#655) isn't read here yet."""
    from storyforge import ledger
    try:
        order = ledger.scene_order(project_dir)
    except (OSError, ValueError, UnicodeDecodeError) as e:
        return [], f'no state carried over (the reading order could not be read: {e})'
    if scene_id not in order:
        return [], ''
    before = [s for s, n in order.items() if n < order[scene_id]]
    if not before:
        return [], ''
    prev = max(before, key=lambda s: order[s])
    path = sheet_path(project_dir, prev)
    if not os.path.isfile(path):
        return [], f'no state carried over: {prev} has no stage sheet yet'
    try:
        sheet = load_sheet(path)
        from storyforge.illustrations import read_scene_raw
        # the bytes the gate read (the gate exception, docs/history.md)
        prev_prose = read_scene_raw(project_dir, prev)
        if prev_prose is None:
            return [], f'no state carried over: {prev} has no prose'
    except (OSError, ValueError) as e:
        return [], f'no state carried over: {prev}\'s stage sheet could not be used ({e})'
    if sheet.get('prose_sha256') != prose_hash(prev_prose):
        return [], f'no state carried over: {prev}\'s stage sheet is of earlier prose'
    return [replace(e, origin='carried', seq=-1) for e in _entries(sheet.get('end', []), 'end')], ''


# ============================================================================
# The check
# ============================================================================

def _scene_meta(project_dir: str, scene_id: str) -> tuple[str, str]:
    from storyforge.elaborate import _read_csv_as_map
    try:
        rows = _read_csv_as_map(os.path.join(project_dir, 'reference', 'scenes.csv'))
    except OSError:
        return '', ''
    row = rows.get(scene_id, {})
    time_of_day = (row.get('time_of_day') or '').strip()
    # scenes.csv's `unstated`: the text gives no time (the sky check says so)
    return (row.get('pov') or '').strip(), '' if time_of_day == 'unstated' else time_of_day


def _overlap(a: str, b: str) -> bool:
    """Whether two quotes are on the same words (one inside the other)."""
    from storyforge.quotes import normalize
    x, y = normalize(a), normalize(b)
    return bool(x and y and (x in y or y in x))


def _find(hay: str, quote: str, start: int = 0) -> int:
    """Where `quote`'s first words begin in `hay` (already `normalize`d),
    at or after `start`, as whole words; -1 when they aren't there."""
    from storyforge.quotes import normalize
    parts = [p.strip(' .,;:!?"\'-') for p in normalize(quote).split('...')]
    part = next((p for p in parts if re.search(r'\w', p)), '')
    if not part:
        return -1
    pattern = (r'(?<!\w)' if re.match(r'\w', part) else '') + re.escape(part) \
        + (r'(?!\w)' if re.search(r'\w$', part) else '')
    m = re.compile(pattern).search(hay, start)
    return m.start() if m else -1


def in_prose_order(prose: str, events: list[Event]) -> tuple[list[Event], list[int]]:
    """`events` sorted by where each quote stands in the prose (a stable
    sort: the model's order where the prose doesn't decide), and each one's
    position. A quote said twice is placed at its next occurrence after the
    event before it; a quote not in the prose stays after the event before
    it."""
    from storyforge.quotes import normalize
    hay = normalize(prose)
    placed, last = [], 0
    for ev in events:
        p = _find(hay, ev.quote, last) if ev.verified else -1
        if p < 0 and ev.verified:
            p = _find(hay, ev.quote, 0)
        if p < 0:
            p = last
        placed.append(p)
        last = p
    order = sorted(range(len(events)), key=lambda k: placed[k])
    return [events[k] for k in order], [placed[k] for k in order]


def stage_for(prose: str, quote: str, positions: list[int], r: Replay) -> str:
    """The stage a question on `quote` is asked against: the stage before
    the first event that stands at or after the quote in the prose (the end
    state when none does)."""
    from storyforge.quotes import normalize
    at = _find(normalize(prose), quote)
    if at >= 0:
        k = next((k for k, p in enumerate(positions) if p >= at), None)
        if k is not None:
            return r.stage_at[k]
    return render(r.end)


def check_stage_sheet(project_dir: str, scene_id: str, *, prose: str | None = None,
                      model: str | None = None, log_file: str = '',
                      carry: bool = True, save: bool = False) -> StageResult:
    """Make `scene_id`'s stage sheet from its prose (its file, or `prose`),
    check it, and return the findings (`StageResult`). The events are
    replayed in the prose's order (`in_prose_order`). `carry`: open with the
    previous scene's end state (`carried_opening`). `save`: write the sheet
    to `working/stage-sheets/<scene>.json`.

    Raises:
        StageSheetError: no prose, a refusal or API failure, or a reply cut
            off or off-schema twice running.
        world_table.WorldTableError: `reference/world.csv` is malformed.
    """
    from storyforge import world_table
    if prose is None:
        from storyforge.illustrations import read_scene_raw
        prose = read_scene_raw(project_dir, scene_id)   # the gate exception (docs/history.md)
    if not (prose or '').strip():
        raise StageSheetError(f'{scene_id} has no prose to check')
    world = world_table.load(project_dir)
    model = resolve_model(model)
    pov, time_of_day = _scene_meta(project_dir, scene_id)
    result = StageResult(scene_id)
    opening: list[Entry] = []
    if carry:
        opening, note = carried_opening(project_dir, scene_id)
        if note:
            result.notes.append(note)
    x = extract(scene_id, prose, pov=pov, model=model, log_file=log_file)
    if x.no_events:
        result.notes.append(f'the extraction recorded no physical event in '
                            f'{len(prose.split())} words (asked twice): nothing was checked')
    events, positions = in_prose_order(prose, x.events)
    result.events = len(events)
    r = replay(events, opening=opening, world=world, time_of_day=time_of_day)
    for s in r.slips:
        result.findings.append(to_finding(scene_id, s))
    result.notes += r.notes(len(events))
    cast = {_who(c) for c in x.cast}
    strangers = sorted({e.who for e in events if e.who and cast and _who(e.who) not in cast})
    if strangers:
        result.notes.append(f'{len(strangers)} name(s) in the events not in the cast '
                            f'({", ".join(strangers)[:120]}): kept apart from the cast\'s '
                            f'states, so a slip across the two names is not checked')
    if x.misquoted_questions:
        result.notes.append(f'{x.misquoted_questions} question(s) quote words not in the '
                            f'scene: not asked')
    if x.empty_questions:
        result.notes.append(f'{x.empty_questions} question(s) with no question: not asked')
    questions = x.questions
    for q in questions:
        q.stage = stage_for(prose, q.quote, positions, r)
    if len(questions) > MAX_QUESTIONS:
        result.notes.append(f'{len(questions) - MAX_QUESTIONS} question(s) past the '
                            f'{MAX_QUESTIONS} a scene gets: not asked')
        questions = questions[:MAX_QUESTIONS]
    q_log = ''
    if log_file:
        stem, ext = os.path.splitext(log_file)
        q_log = f'{stem}.ask{ext}'
    no, split = ask(scene_id, prose, questions, model=model, log_file=q_log)
    result.asked = len(questions)
    if split:
        result.notes.append(f'{split} question(s) got split answers: not findings')
    for q, why in no:
        if any(_overlap(q.quote, f.scene_quote) for f in result.findings):
            continue   # the code already found this slip, in these words
        result.findings.append(Finding(
            kind='contradiction', code=BLOCKING_CODE, scene_quote=q.quote,
            established_scene=scene_id, established_quote=q.quote, fact_id='',
            explanation=f'(impossible, stage sheet: asked {ASKINGS} times) {q.question} '
                        f'No: {why}'))
    result.sheet = build_sheet(scene_id, prose, r, model=model, cast=x.cast)
    if save:
        write_sheet(project_dir, result.sheet)
    return result
