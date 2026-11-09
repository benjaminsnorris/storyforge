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
3. **A narrow yes/no for the rest** (`ask`): actions the fields can't type
   ("he reached the box behind him") come back from extraction as yes/no
   questions; a small model answers each against the sheet at that beat,
   twice (`ASKINGS`), and a finding is kept only when both answers say it
   can't happen.

Findings are `checker.Finding`s with code `blocking.BLOCKING_CODE` (BLK)
against the scene itself, exactly as the blocking read's, so the gate
classifies, fixes and accepts them the same way (`gate._classify`,
`problems_to_fix`, `_accepted_blocking_covers`) and they stop only their own
scene (#641).

**What isn't checked is said.** An event or question whose quote isn't in
the scene, a state set by one, a question past `MAX_QUESTIONS`, and a
split yes/no answer are not findings; each is counted in
`StageResult.notes`, which `check --blocking` reports and the gate logs.

**The sheet's file** (`working/stage-sheets/<scene>.json`, `FORMAT`): the
state at the opening, then each beat's changes, then the end state, in a
format a writer can produce too (#655: the writer keeps the sheet while
drafting and returns its end state after each scene; the code then compares
the two). See `write_sheet` / `load_sheet` / `states`. The opening is
carried over from the previous scene's sheet when that sheet was made from
the previous scene's current prose (`carried_opening`). A carried state is
shown to the yes/no asker but never makes a finding: a scene break allows
any change, and only the writer's note (#655) will say what carries.

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
from dataclasses import dataclass, field

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
  - `position`: `to` where the person now is, in a few words, relative to people and things ("behind the wagon", "at Priam's left").
  - `facing`: `to` what or whom the person now faces or looks toward.
  - `sees`: the person makes out a detail of someone or something; `item` `face` (a face, eyes, an expression) or `figure` (who someone is, by build or bearing); `from` where the viewer is, `to` where what is seen is, each as a place name.
  - `light`: `item` the light (candle, lamp, fire, torch); `to` `lit` or `out`.
  - `door`: `item` the door, gate, curtain or shutter; `to` `open` or `shut`.
  - `time`: `to` the time of day the scene states (dawn, morning, noon, afternoon, evening, dusk, night).
  - `sun`: `to` where the sun is: a compass direction, or the landmark the text puts it at ("behind Ida": `Ida`).
  - `shadow`: `to` the compass direction a shadow falls or points.
  - `break`: a gap in time or a section break in the text; `item` and `to` empty.
- `from` (except `sees`): the state THIS sentence itself says or implies there was just before, never what earlier sentences said. "He stood up": posture `from` `down`, `to` standing. "She set the cup down": hand `from` `cup`, `to` empty. "He waved with his free hand": `hand_either` `from` `empty`. "She took off her cloak": worn `from` on, `to` off. Posture `from` may be `down` (any posture but standing). When the sentence only describes a state ("He sat by the fire", "the spear in his right hand"), `from` is empty.

Record what the narration says happens now, not memories, dreams, plans, similes or what someone imagines.

`questions`: for a physical action none of the fields can record where a careful reader might doubt it can happen as written (reaching something behind them or out of reach, seeing past something or someone, touching or breathing through armour, a side or an order that may not fit where people are), one yes/no question asking whether it can happen as written, so that "yes" means it can: "Can Priam, seated in the car, reach the box in the wagon ahead of him?". `quote` is the action's words. Ask only where there is real doubt; most scenes need none.

Return every event in the scene's order."""

ASK_PROMPT = """You check whether physical actions in one scene of a novel can happen as written. Each question gives the action's words and the stage at that moment (who is present, posture, what each hand holds, what is worn, the light), as recorded so far; a state not listed is unknown. Answer `yes` when the action can happen as written, given the scene and the stage, and `no` only when it can't. When in doubt, `yes`. Give a one-sentence reason.

## Scene: {scene_id}

{prose}

## Questions

{questions}"""


class StageSheetError(RuntimeError):
    """The stage sheet could not be made or checked; the message says why."""


@dataclass
class Event:
    quote: str
    who: str
    field: str
    item: str
    from_: str
    to: str
    verified: bool = True


@dataclass
class Entry:
    """One state on the sheet: (who, field, item) → value, set by `quote`."""
    who: str
    field: str
    item: str
    value: str
    quote: str
    #: `scene` (this scene set it) or `carried` (the previous scene left it)
    origin: str = 'scene'
    verified: bool = True
    #: the index of the event that set it (-1: the opening)
    seq: int = -1

    def key(self) -> tuple[str, str, str]:
        return (_who(self.who), self.field, _obj(self.item))

    def to_json(self) -> dict:
        out = {'who': self.who, 'field': self.field, 'item': self.item, 'value': self.value,
               'quote': self.quote}
        if self.origin != 'scene':
            out['origin'] = self.origin
        return out


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
    #: slips set against (or made by) an unverified event: not findings
    unchecked: int = 0
    #: the stage before each event (index → `render`), for the questions
    stage_at: dict[int, str] = field(default_factory=dict)


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


def _closed(field_name: str, value: str) -> str:
    v = (value or '').strip().lower()
    return v if v in VALUES.get(field_name, ()) else ''


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
    """A state that can make a finding: set in this scene, by a verified quote."""
    return e is not None and e.origin == 'scene'


def render(entries: list[Entry]) -> str:
    """The stage as lines a model reads: per person, then the scene's."""
    people: dict[str, list[str]] = {}
    scene: list[str] = []
    for e in entries:
        if e.field in ('break', 'sees'):
            continue
        what = {'hand_left': 'left hand', 'hand_right': 'right hand'}.get(e.field, e.field)
        text = f'{what}{" " + e.item if e.item else ""}: {e.value}'
        if e.who:
            people.setdefault(e.who, []).append(text)
        else:
            scene.append(text)
    lines = [f'- {who}: ' + '; '.join(parts) for who, parts in people.items()]
    lines += [f'- {part}' for part in scene]
    return '\n'.join(lines) or '- (nothing recorded yet)'


def replay(events: list[Event], *, opening: list[Entry] | None = None, world=None,
           time_of_day: str = '') -> Replay:
    """Apply `events` in order to the sheet that starts at `opening`, and
    check each against it. Pure: no model, no files.

    `time_of_day` is the scene's (scenes.csv) when the scene states none;
    `world` a `world_table.World` (the defaults when None).
    """
    from storyforge.world_table import World, angle, opposite, SUN_DOWN
    world = world or World()
    opening = list(opening or [])
    sheet = _Sheet(opening)
    slips: list[Slip] = []
    beats: list[dict] = []
    unchecked = 0
    stage_at: dict[int, str] = {}
    scene_time = time_of_day.strip()

    def slip(ev: Event, against: Entry | None, why: str, kind: str = 'contradiction') -> None:
        nonlocal unchecked
        if not ev.verified or (against is not None and not against.verified):
            unchecked += 1
            return
        slips.append(Slip(ev, against, why, kind))

    def entry(ev: Event, field_name: str, value: str, item: str = '') -> Entry:
        return Entry(ev.who, field_name, item, value, ev.quote, verified=ev.verified, seq=i)

    for i, ev in enumerate(events):
        stage_at[i] = render(sheet.entries())
        changed: list[Entry] = []
        cleared = False
        who = ev.who.strip()
        f = ev.field
        name = who or 'someone'

        if who and f not in ('present', 'position'):
            gone = sheet.get(who, 'present')
            if _binding(gone) and gone.value == 'gone':
                slip(ev, gone, f'{name} acts here after leaving')

        if f == 'break':
            kept = [e for e in sheet.entries() if e.field == 'worn']
            sheet = _Sheet(kept)
            cleared = True
        elif f == 'posture' and who:
            said, to = posture(ev.from_), posture(ev.to)
            held = sheet.get(who, 'posture')
            if _binding(held):
                if said and not _posture_fits(said, held.value):
                    slip(ev, held, f'{name} {_moves(said, to)}, but is {held.value}')
                elif not said and to and not _posture_fits(to, held.value):
                    slip(ev, held, f'{name} is {to} with nothing between, but was {held.value}')
            if to:
                e = entry(ev, 'posture', to)
                sheet.put(e)
                changed.append(e)
        elif f in HANDS and who:
            said, to = _hand_value(ev.from_), _hand_value(ev.to)
            held = sheet.get(who, f)
            side = 'left' if f == 'hand_left' else 'right'
            if _binding(held):
                if said and not _hand_fits(said, held.value):
                    slip(ev, held, f'{name}\'s {side} hand {_hand_needs(said)}, but it holds '
                                   f'{held.value}')
                elif (not said and to and to != EMPTY and held.value != EMPTY
                      and not same_object(to, held.value)):
                    slip(ev, held, f'{name}\'s {side} hand holds {to}, but it already holds '
                                   f'{held.value}')
            if to:
                e = entry(ev, f, to)
                sheet.put(e)
                changed.append(e)
        elif f == 'hand_either' and who:
            changed += _either_hand(ev, sheet, slip, entry, name)
        elif f == 'worn' and who and ev.item.strip():
            said, to = _closed('worn', ev.from_), _closed('worn', ev.to)
            held = sheet.find_item(who, 'worn', ev.item)
            if _binding(held):
                if said and said != held.value:
                    slip(ev, held, f'{name} {"takes off" if said == "on" else "puts on"} '
                                   f'{ev.item}, which is already {held.value}')
                elif not said and to and to != held.value:
                    slip(ev, held, f'{name} has {ev.item} {to} with nothing between, but it '
                                   f'was {held.value}')
            if to:
                e = entry(ev, 'worn', to, held.item if held else ev.item)
                sheet.put(e)
                changed.append(e)
        elif f == 'present' and who:
            said, to = _closed('present', ev.from_), _closed('present', ev.to)
            held = sheet.get(who, 'present')
            if _binding(held) and said and said != held.value:
                slip(ev, held, f'{name} {"leaves" if said == "here" else "arrives"}, but is '
                               f'already {held.value}')
            if to:
                e = entry(ev, 'present', to)
                sheet.put(e)
                changed.append(e)
        elif f in ('light', 'door') and ev.item.strip():
            said, to = _closed(f, ev.from_), _closed(f, ev.to)
            held = sheet.find_item('', f, ev.item)
            if _binding(held):
                if said and said != held.value:
                    slip(ev, held, f'{ev.item} goes from {said}, but is {held.value}')
                elif not said and to and to != held.value:
                    slip(ev, held, f'{ev.item} is {to} with nothing between, but was '
                                   f'{held.value}')
            if to:
                e = entry(ev, f, to, held.item if held else ev.item)
                e.who = ''
                sheet.put(e)
                changed.append(e)
        elif f in ('position', 'facing') and who and ev.to.strip():
            e = entry(ev, f, ev.to.strip())
            sheet.put(e)
            changed.append(e)
        elif f == 'time' and ev.to.strip():
            e = entry(ev, 'time', ev.to.strip())
            e.who = ''
            sheet.put(e)
            changed.append(e)
        elif f in ('sun', 'shadow') and ev.to.strip():
            where = world.direction(ev.to)
            time_e = sheet.get('', 'time')
            sun_e = sheet.get('', 'sun')
            expected = world.sun(time_e.value) if time_e else world.sun(scene_time)
            basis = time_e if _binding(time_e) else None
            if f == 'sun' and where:
                if expected == SUN_DOWN:
                    pass   # a sun at night is a time question, not blocking
                elif expected and angle(where, expected) > 90:
                    when = time_e.value if time_e else scene_time
                    slip(ev, basis, f'the sun is {where} at {when}, when it is {expected}',
                         kind='impossible')
                e = entry(ev, 'sun', where)
                e.who = ''
                sheet.put(e)
                changed.append(e)
            elif f == 'shadow' and where:
                sun = sun_e.value if sun_e else (expected if expected != SUN_DOWN else None)
                against = sun_e if sun_e else basis
                if sun and angle(where, opposite(sun)) > 90:
                    slip(ev, against if _binding(against) else None,
                         f'a shadow falls {where} with the sun in the {sun}',
                         kind='impossible')
        elif f == 'sees' and who:
            detail = ev.item.strip().lower() or 'face'
            rng, far = world.sight(detail), world.distance(ev.from_, ev.to)
            if rng and far and far > rng:
                slip(ev, None, f'{name} makes out a {detail} {far:g} m away; a {detail} can '
                               f'be made out at {rng:g} m', kind='impossible')
        beat = {'quote': ev.quote, 'event': _event_json(ev),
                'set': [e.to_json() for e in changed]}
        if cleared:
            beat['cleared'] = True
        beats.append(beat)
    return Replay(opening, beats, sheet.entries(), slips, unchecked, stage_at)


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


def _either_hand(ev: Event, sheet: _Sheet, slip, entry, name: str) -> list[Entry]:
    """A hand the text doesn't name as left or right."""
    said, to = _hand_value(ev.from_), _hand_value(ev.to)
    left, right = sheet.get(ev.who, 'hand_left'), sheet.get(ev.who, 'hand_right')
    both_known = _binding(left) and _binding(right)
    hand = None
    if said == EMPTY or (not said and to):
        free = [h for h in (left, right) if h is None or h.value == EMPTY
                or (to and to != EMPTY and same_object(to, h.value))]
        if not free and both_known and said == EMPTY:
            later = max((left, right), key=lambda e: e.seq)
            slip(ev, later, f'{name} uses a free hand, but the left holds {left.value} and '
                            f'the right {right.value}')
        elif not free and both_known and to and to != EMPTY:
            slip(ev, max((left, right), key=lambda e: e.seq),
                 f'{name}\'s hand holds {to}, but the left holds {left.value} '
                            f'and the right {right.value}')
        if len(free) == 1:
            hand = 'hand_left' if free[0] is left else 'hand_right'
        elif left is None and right is not None:
            hand = 'hand_left'
        elif right is None and left is not None:
            hand = 'hand_right'
    elif said:
        holding = [h for h in (left, right) if h is not None and h.value != EMPTY
                   and same_object(said, h.value)]
        if holding:
            hand = 'hand_left' if holding[0] is left else 'hand_right'
        elif both_known:
            slip(ev, max((left, right), key=lambda e: e.seq),
                 f'{name} lets go of {said}, but the left holds {left.value} and '
                            f'the right {right.value}')
        elif left is None and right is not None:
            hand = 'hand_left'
        elif right is None and left is not None:
            hand = 'hand_right'
    if not to:
        return []
    if hand is None:
        # which hand can't be told: what either holds is now unknown
        sheet.drop(ev.who, 'hand_left')
        sheet.drop(ev.who, 'hand_right')
        return []
    e = entry(ev, hand, to)
    sheet.put(e)
    return [e]


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


def extract(scene_id: str, prose: str, *, pov: str = '', model: str,
            log_file: str = '') -> tuple[list[str], list[Event], list[Question], int]:
    """The scene's cast, events and questions, each quote verified; and how
    many questions had a quote not in the scene (they aren't asked)."""
    cast, items, qs = _call(build_prompt(scene_id, prose, pov), model, log_file,
                            max_tokens(prose), SCHEMA, f'stage sheet {scene_id}', parse,
                            f'{scene_id}: the stage sheet extraction')
    events = [Event(quote=it['quote'].strip(), who=it['who'].strip(), field=it['field'],
                    item=it['item'].strip(), from_=it['from'].strip(), to=it['to'].strip(),
                    verified=bool(it['quote'].strip()) and quote_in(prose, it['quote']))
              for it in items]
    questions, bad = [], 0
    for q in qs:
        if q['quote'].strip() and q['question'].strip() and quote_in(prose, q['quote']):
            questions.append(Question(q['quote'].strip(), q['question'].strip()))
        else:
            bad += 1
    return cast, events, questions, bad


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

def sheet_path(project_dir: str, scene_id: str) -> str:
    return os.path.join(project_dir, SHEETS_DIR, f'{scene_id}.json')


def prose_hash(prose: str) -> str:
    return hashlib.sha256(prose.strip().encode('utf-8')).hexdigest()


def build_sheet(scene_id: str, prose: str, r: Replay, *, source: str = 'extracted',
                model: str = '', cast: list[str] | None = None) -> dict:
    return {'format': FORMAT, 'scene_id': scene_id, 'source': source, 'model': model,
            'prose_sha256': prose_hash(prose), 'cast': list(cast or []),
            'opening': [e.to_json() for e in r.opening], 'beats': r.beats,
            'end': [e.to_json() for e in r.end]}


def write_sheet(project_dir: str, sheet: dict) -> str:
    """Write a sheet (LF, sorted keys). Returns its path."""
    path = sheet_path(project_dir, sheet['scene_id'])
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, 'w', encoding='utf-8', newline='\n') as f:
        json.dump(sheet, f, indent=1, ensure_ascii=False, sort_keys=True)
        f.write('\n')
    return path


def _entries(items, where: str) -> list[Entry]:
    if not isinstance(items, list):
        raise ValueError(f'{where} is not a list')
    out = []
    for it in items:
        if not (isinstance(it, dict) and it.get('field') in FIELDS
                and all(isinstance(it.get(k, ''), str)
                        for k in ('who', 'item', 'value', 'quote'))):
            raise ValueError(f'an entry in {where} is not the format: {it!r}'[:200])
        out.append(Entry(it.get('who', ''), it['field'], it.get('item', ''),
                         it.get('value', ''), it.get('quote', ''),
                         origin=it.get('origin', 'scene')))
    return out


def load_sheet(path: str) -> dict:
    """A sheet file, checked against `FORMAT`. Raises ValueError (naming the
    file) when it isn't one; OSError when it can't be read."""
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
        _entries(data.get('opening', []), 'opening')
        _entries(data.get('end', []), 'end')
        if not isinstance(data.get('beats', []), list):
            raise ValueError('beats is not a list')
        for b in data.get('beats', []):
            if not isinstance(b, dict):
                raise ValueError('a beat is not an object')
            _entries(b.get('set', []), 'a beat')
    except ValueError as e:
        raise ValueError(f'{path}: {e}') from e
    return data


def states(sheet: dict) -> list[list[Entry]]:
    """The state at the opening, then after each beat (a beat's `set`
    entries replace their keys; `cleared` ends every state but what's worn)."""
    current = {e.key(): e for e in _entries(sheet.get('opening', []), 'opening')}
    out = [list(current.values())]
    for b in sheet.get('beats', []):
        if b.get('cleared'):
            current = {k: e for k, e in current.items() if e.field == 'worn'}
        for e in _entries(b.get('set', []), 'a beat'):
            current[e.key()] = e
        out.append(list(current.values()))
    return out


def carried_opening(project_dir: str, scene_id: str) -> tuple[list[Entry], str]:
    """The previous scene's end state, carried (`origin` `carried`), and a
    note when there is a previous scene but its sheet can't be used ('' when
    carried, or when this is the first scene)."""
    from storyforge import ledger
    try:
        order = ledger.scene_order(project_dir)
    except Exception as e:   # noqa: BLE001 - a missing or odd scenes.csv: say so, carry nothing
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
    end = _entries(sheet.get('end', []), 'end')
    return [Entry(e.who, e.field, e.item, e.value, e.quote, origin='carried')
            for e in end if e.field not in ('break', 'sees')], ''


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
    return (row.get('pov') or '').strip(), (row.get('time_of_day') or '').strip()


def _overlap(a: str, b: str) -> bool:
    """Whether two quotes are on the same words (one inside the other)."""
    from storyforge.quotes import normalize
    x, y = normalize(a), normalize(b)
    return bool(x and y and (x in y or y in x))


def check_stage_sheet(project_dir: str, scene_id: str, *, prose: str | None = None,
                      model: str | None = None, log_file: str = '',
                      carry: bool = True, save: bool = False) -> StageResult:
    """Make `scene_id`'s stage sheet from its prose (its file, or `prose`),
    check it, and return the findings (`StageResult`). `carry`: open with
    the previous scene's end state (`carried_opening`). `save`: write the
    sheet to `working/stage-sheets/<scene>.json`.

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
    cast, events, questions, bad_q = extract(scene_id, prose, pov=pov, model=model,
                                             log_file=log_file)
    result.events = len(events)
    r = replay(events, opening=opening, world=world, time_of_day=time_of_day)
    for s in r.slips:
        result.findings.append(to_finding(scene_id, s))
    misquoted = sum(1 for e in events if not e.verified)
    if misquoted:
        result.notes.append(f'{misquoted} of {len(events)} event(s) quote words not in the '
                            f'scene: their states were applied but make no finding')
    if r.unchecked:
        result.notes.append(f'{r.unchecked} possible slip(s) rest on a misquoted event: not '
                            f'checked')
    if bad_q:
        result.notes.append(f'{bad_q} question(s) quote words not in the scene: not asked')
    # each question sees the stage at the first event its words share, or
    # the end state when no event does
    for q in questions:
        at = next((i for i, e in enumerate(events) if e.quote and (
            quote_in(q.quote, e.quote) or quote_in(e.quote, q.quote))), None)
        q.stage = r.stage_at[at] if at is not None else render(r.end)
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
    result.sheet = build_sheet(scene_id, prose, r, model=model, cast=cast)
    if save:
        write_sheet(project_dir, result.sheet)
    return result
