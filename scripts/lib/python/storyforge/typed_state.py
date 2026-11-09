"""Typed state: the facts of a scene as records code can compare (#648, plan A1).

The ledger's `statement` is prose a model reads. These are small structured
records, one fixed schema, read from each scene's prose by one structured
call on a small model (`extract`), every record quoted and the quote
verified (`quotes.quote_in`). `storyforge.continuity` compares them, free
and the same every run.

Record types (`RECORD_TYPES`), with `who`, `item`, `value` and `detail`:

| type | who | item | value | detail |
|---|---|---|---|---|
| `alive` | the person | | `dead` (dies, or is found dead), `alive` (back from death) | |
| `at` | a living person acting, speaking or spoken to as present | where they are ('' if unsaid) | | |
| `holds` | the holder: a person, or a place an object lies | a particular object | `gets`, `has`, `gives`, `loses`, `destroyed` | who it goes to (`gives`) |
| `knows` | the POV character | a fact id the prompt offers | `learns`, `uses` (acts on it or narrates it) | |
| `injury` | the person | the body part | `minor`, `serious`, `disabling`, `healed` | `left`, `right` or '' |
| `uses` | the person | an injured body part | `full` (at full strength), `impaired` | `left`, `right` or '' |
| `named` | the person | | the proper name the text calls them | |
| `elapsed` | | the scene id the count runs from ('' if none shows it) | the phrase ("three days ago") | |

The plan's other records come from data the book already has, and aren't
extracted again: `when` is scenes.csv (`timeline_day`, `time_of_day`), a
death the author recorded is characters.csv's `death_scene`, what a
character knows comes from the ledger's knowledge facts (`known_by`) and the
briefs' `knowledge_in`/`knowledge_out` too (`continuity.learned_at`), and
`named`'s canonical forms are the character registry, the ledger's aliases
and an adaptation's name map. `wears` and the hands within a scene are the
stage sheet's (#647, `storyforge.stage_sheet`): the possession check reads a
saved sheet's hands for the objects it tracks rather than asking again.

**Why not a ledger column.** The ledger's header is exact (`ledger.COLUMNS`,
`ledger.file_problems`), so a new column would stop every book until it was
migrated, and the frozen E4 and E8 suites (#645) send ledger rows in their
prompts. The records live beside it, one file per scene
(`working/typed-state/<scene>.json`, `FORMAT`), joined to the ledger by
scene id and, for `knows`, by fact id. A file is of the prose it was read
from (`prose_sha256`): another scene's records are read only while its file
still holds that prose (`current`), and a re-check of unchanged prose reads
its own file again instead of paying for the call.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
from dataclasses import dataclass, field

from storyforge.quotes import quote_in

FORMAT = 1
STATE_DIR = os.path.join('working', 'typed-state')
#: Overrides the extraction model (default the extraction tier)
MODEL_ENV = 'STORYFORGE_TYPED_STATE_MODEL'

RECORD_TYPES = ('alive', 'at', 'holds', 'knows', 'injury', 'uses', 'named', 'elapsed')
#: The values each closed type takes
VALUES = {
    'alive': ('dead', 'alive'),
    'holds': ('gets', 'has', 'gives', 'loses', 'destroyed'),
    'knows': ('learns', 'uses'),
    'injury': ('minor', 'serious', 'disabling', 'healed'),
    'uses': ('full', 'impaired'),
}
SIDES = ('left', 'right')
#: The most facts offered to `knows`, and injuries to `uses` (the rest are
#: counted in the notes)
MAX_OFFERED_FACTS = 40
MAX_OFFERED_INJURIES = 30

_RECORD = {
    'type': 'object',
    'properties': {
        'type': {'type': 'string', 'enum': list(RECORD_TYPES)},
        'who': {'type': 'string'},
        'item': {'type': 'string'},
        'value': {'type': 'string'},
        'detail': {'type': 'string'},
        'quote': {'type': 'string'},
    },
    'required': ['type', 'who', 'item', 'value', 'detail', 'quote'],
    'additionalProperties': False,
}
SCHEMA = {
    'type': 'object',
    'properties': {'records': {'type': 'array', 'items': _RECORD}},
    'required': ['records'],
    'additionalProperties': False,
}

PROMPT = """You record the facts of one scene of a novel as typed records, for code that checks continuity across the book. Record only what this scene's text says happens in its present; code does the comparing, so never fix or smooth over what you read.

## Scene: {scene_id}{pov_line}

{prose}

## The book's people

{cast}
{offered}
## What to record

Every record has `type`, `who`, `item`, `value`, `detail` and `quote`. `quote` is the scene's own words, copied exactly: the shortest clause that shows the fact. `who` is a person's name as listed above (or as the scene names someone not listed). Leave a field empty when the type doesn't use it. In the scene's order:

- `alive`: a person dies, is killed or is found dead here: `value` `dead`. One shown alive after being dead: `alive`.
- `at`: each living person who acts, speaks or is spoken to as present in the scene, once per place they are in: `item` where they are, as the scene names it ('' if it doesn't). Never a corpse, and never someone only remembered, mentioned, dreamed or imagined.
- `holds`: a particular object a later scene could track (a named weapon, the ring, the letter, Hector's helmet; not "a spear" among many): `who` the holder (a person, or the place it lies), `item` the object, named the same way every time, `value` `gets` (takes it, is given it, picks it up), `has` (holds, carries, uses or wears it, with no taking shown), `gives` (hands it over; `detail` who to), `loses` (drops it for good, has it taken) or `destroyed` (broken, burned, sunk).
- `knows`: only for the facts listed under "Facts {pov_name} has not learned" above: when {pov_name} learns one in this scene, `value` `learns`; when {pov_name} acts on one, says it, or the narration gives it as {pov_name}'s thought, `value` `uses`. `item` the fact's id exactly as listed.
- `injury`: a person is hurt: `item` the body part (arm, hand, leg, eye, ribs...), `detail` `left`, `right` or '', `value` `minor`, `serious` or `disabling`; an injury that has healed: `healed`.
- `uses`: a person uses a body part listed under "Injuries in force" above, or one injured earlier in this scene: `item` the part, `detail` the side, `value` `full` (as if unhurt: grips, swings, runs, lifts at full strength) or `impaired` (favours it, winces, uses it weakly).
- `named`: each proper name the scene calls a person by, once per name: `who` the person, `value` the name exactly as written (a nickname or patronymic used as a name counts; a pronoun or a description doesn't).
- `elapsed`: each phrase that counts time with a number ("three days ago", "nine nights since", "in a week", "the tenth day"): `value` the phrase exactly as written, `item` the id of the scene in the calendar above where the event it counts from happens, or '' when no scene shows it.

Never record what happens in a memory, dream, story told, plan or simile as the scene's present; record `named` and `elapsed` wherever they are."""


class TypedStateError(RuntimeError):
    """The scene's typed state could not be read; the message says why."""


@dataclass
class Record:
    type: str
    who: str = ''
    item: str = ''
    value: str = ''
    detail: str = ''
    quote: str = ''
    scene_id: str = ''
    #: the quote is in the scene's prose
    verified: bool = True
    #: `prose` (read from the scene), `registry` (characters.csv), `brief`,
    #: `ledger`, `stage-sheet`
    origin: str = 'prose'
    #: the record's place in its scene (-1: before the scene opens; a large
    #: number: by its end)
    index: int = 0

    def to_json(self) -> dict:
        out = {'type': self.type, 'who': self.who, 'item': self.item, 'value': self.value,
               'detail': self.detail, 'quote': self.quote}
        if not self.verified:
            out['verified'] = False
        return out


@dataclass
class ExtractResult:
    records: list[Record] = field(default_factory=list)
    #: what wasn't offered or couldn't be used (never silent)
    notes: list[str] = field(default_factory=list)


# ============================================================================
# The prompt
# ============================================================================

def build_prompt(scene_id: str, prose: str, *, pov: str = '', cast: list[str] | None = None,
                 calendar: list[str] | None = None, facts: list[tuple[str, str]] | None = None,
                 injuries: list[str] | None = None) -> str:
    """The extraction prompt. `cast`: the registry's names; `calendar`: the
    calendar lines (`prompts.calendar_lines`, this scene marked); `facts`:
    (id, statement) the POV hasn't learned yet; `injuries`: lines naming
    injuries in force."""
    pov = pov.strip()
    pov_name = pov or 'the point-of-view character'
    pov_line = f'\n\nPoint of view: {pov}' if pov else ''
    cast_text = ('\n'.join(f'- {c}' for c in cast) if cast else
                 '(no character registry: use the names the scene uses)')
    parts = []
    if calendar:
        parts.append('## The calendar (scenes.csv, reading order)\n\n' + '\n'.join(calendar))
    if facts:
        parts.append(f'## Facts {pov_name} has not learned before this scene\n\n'
                     + '\n'.join(f'- {fid}: {st}' for fid, st in facts))
    if injuries:
        parts.append('## Injuries in force\n\n' + '\n'.join(f'- {i}' for i in injuries))
    offered = ('\n' + '\n\n'.join(parts) + '\n') if parts else ''
    return PROMPT.format(scene_id=scene_id, pov_line=pov_line, prose=prose.strip(),
                         cast=cast_text, offered=offered, pov_name=pov_name)


def parse(text: str) -> list[dict]:
    """The records from a reply. Raises ValueError when it isn't the schema."""
    try:
        items = json.loads(text)['records']
    except (TypeError, ValueError, KeyError) as e:
        raise ValueError(f'reply is not the schema ({e})') from e
    if not isinstance(items, list):
        raise ValueError('records must be a list')
    for it in items:
        if (not isinstance(it, dict) or it.get('type') not in RECORD_TYPES
                or not all(isinstance(it.get(k), str)
                           for k in ('who', 'item', 'value', 'detail', 'quote'))):
            raise ValueError(f'a record is not the schema: {it!r}'[:200])
    return items


def max_tokens(prose: str) -> int:
    return min(24000, 4000 + len(prose.split()) * 4)


def resolve_model(model: str | None = None) -> str:
    from storyforge.common import select_model
    return model or os.environ.get(MODEL_ENV) or select_model('extraction')


def _call(prompt: str, model: str, log_file: str, tokens: int, label: str) -> list[dict]:
    """One structured call, retried once on an unusable reply."""
    from storyforge import api
    for attempt in (1, 2):
        try:
            if log_file:
                response = api.invoke_to_file(prompt, model, log_file, tokens,
                                              output_schema=SCHEMA, label=label)
            else:
                response = api.invoke(prompt, model, tokens, output_schema=SCHEMA, label=label)
            if api.is_truncated(response):
                raise ValueError('the reply hit its token limit')
            return parse(api.extract_text(response))
        except ValueError as e:
            if attempt == 2:
                raise TypedStateError(f'{label} failed twice: {e}') from e
            prompt = prompt + f'\n\nYour last answer was not usable: {e}. Answer in the schema.'
        except RuntimeError as e:   # RefusalError, an API failure
            raise TypedStateError(f'{label} failed: {e}') from e
    raise AssertionError('unreachable')


def _clean(rec: Record) -> str:
    """Why a record can't be used ('' when it can): a closed type's value
    outside its set, or a type missing what it needs."""
    allowed = VALUES.get(rec.type)
    if allowed and rec.value not in allowed:
        return f'{rec.type} value "{rec.value}" is not one of {", ".join(allowed)}'
    if rec.type in ('alive', 'at', 'holds', 'knows', 'injury', 'uses', 'named') and not rec.who:
        return f'{rec.type} names no one'
    if rec.type in ('holds', 'knows', 'injury', 'uses') and not rec.item:
        return f'{rec.type} names no {"fact" if rec.type == "knows" else "object or part"}'
    if rec.type in ('named', 'elapsed') and not rec.value:
        return f'{rec.type} gives no {"name" if rec.type == "named" else "phrase"}'
    return ''


def extract(scene_id: str, prose: str, *, model: str, log_file: str = '', pov: str = '',
            cast: list[str] | None = None, calendar: list[str] | None = None,
            facts: list[tuple[str, str]] | None = None,
            injuries: list[str] | None = None) -> ExtractResult:
    """The scene's records, each quote verified against `prose`. A record
    off its type's values is left out and counted in the notes; a misquoted
    one is kept, marked unverified (the checks make no finding on it, and
    say so)."""
    items = _call(build_prompt(scene_id, prose, pov=pov, cast=cast, calendar=calendar,
                               facts=facts, injuries=injuries),
                  model, log_file, max_tokens(prose), f'{scene_id}: the typed state extraction')
    out = ExtractResult()
    unusable: list[str] = []
    for n, it in enumerate(items):
        rec = Record(type=it['type'], who=it['who'].strip(), item=it['item'].strip(),
                     value=it['value'].strip().lower() if it['type'] in VALUES
                     else it['value'].strip(),
                     detail=it['detail'].strip().lower() if it['type'] in ('injury', 'uses')
                     else it['detail'].strip(),
                     quote=it['quote'].strip(), scene_id=scene_id, index=n)
        rec.verified = bool(rec.quote) and quote_in(prose, rec.quote)
        why = _clean(rec)
        if why:
            unusable.append(why)
            continue
        out.records.append(rec)
    if unusable:
        out.notes.append(f'{len(unusable)} record(s) off the schema, left out: '
                         + '; '.join(unusable[:5]) + (' ...' if len(unusable) > 5 else ''))
    return out


# ============================================================================
# The files
# ============================================================================

def state_path(project_dir: str, scene_id: str) -> str:
    return os.path.join(project_dir, STATE_DIR, f'{scene_id}.json')


def prose_hash(prose: str) -> str:
    return hashlib.sha256(prose.strip().encode('utf-8')).hexdigest()


def write_state(project_dir: str, scene_id: str, prose: str, records: list[Record], *,
                model: str = '') -> str:
    """Write a scene's records (LF, sorted keys). Returns the path."""
    path = state_path(project_dir, scene_id)
    os.makedirs(os.path.dirname(path), exist_ok=True)
    data = {'format': FORMAT, 'scene_id': scene_id, 'model': model,
            'prose_sha256': prose_hash(prose), 'records': [r.to_json() for r in records]}
    with open(path, 'w', encoding='utf-8', newline='\n') as f:
        json.dump(data, f, indent=1, ensure_ascii=False, sort_keys=True)
        f.write('\n')
    return path


def load_state(path: str) -> dict:
    """A state file, checked against `FORMAT`; its `records` as `Record`s.
    Raises ValueError (naming the file) when it isn't one, OSError when it
    can't be read."""
    with open(path, encoding='utf-8') as f:
        try:
            data = json.load(f)
        except ValueError as e:
            raise ValueError(f'{path}: not JSON ({e})') from e
    try:
        if not isinstance(data, dict) or data.get('format') != FORMAT:
            raise ValueError(f'format is not {FORMAT}')
        sid = data.get('scene_id')
        if not isinstance(sid, str) or not sid:
            raise ValueError('no scene_id')
        items = data.get('records')
        if not isinstance(items, list):
            raise ValueError('records is not a list')
        records = []
        for n, it in enumerate(items):
            if not (isinstance(it, dict) and it.get('type') in RECORD_TYPES
                    and all(isinstance(it.get(k, ''), str)
                            for k in ('who', 'item', 'value', 'detail', 'quote'))):
                raise ValueError(f'a record is not the format: {it!r}'[:200])
            records.append(Record(it['type'], it.get('who', ''), it.get('item', ''),
                                  it.get('value', ''), it.get('detail', ''),
                                  it.get('quote', ''), sid,
                                  verified=it.get('verified', True) is not False, index=n))
        data = dict(data, records=records)
    except ValueError as e:
        raise ValueError(f'{path}: {e}') from e
    return data


def current(project_dir: str, scene_id: str, prose: str | None = None
            ) -> tuple[list[Record] | None, str]:
    """The scene's records when its file is of `prose` (default the scene
    file as it is), else None and why ('' when it simply has none yet)."""
    path = state_path(project_dir, scene_id)
    if not os.path.isfile(path):
        return None, ''
    if prose is None:
        from storyforge.illustrations import read_scene_raw
        try:
            prose = read_scene_raw(project_dir, scene_id)
        except (OSError, UnicodeDecodeError) as e:
            return None, f'its prose could not be read ({e})'
        if prose is None:
            return None, 'it has no prose'
    try:
        data = load_state(path)
    except (OSError, ValueError) as e:
        return None, f'its typed state could not be used ({e})'
    if data.get('prose_sha256') != prose_hash(prose):
        return None, 'its typed state is of earlier prose'
    return data['records'], ''


# ============================================================================
# Records from what the book already has
# ============================================================================

def registry_deaths(project_dir: str) -> list[Record]:
    """characters.csv's `death_scene` as `alive` records (`origin`
    `registry`), each by the end of its scene."""
    from storyforge.elaborate import _read_csv
    path = os.path.join(project_dir, 'reference', 'characters.csv')
    out = []
    for row in _read_csv(path):
        who = (row.get('id') or '').strip()
        scene = (row.get('death_scene') or '').strip()
        if who and scene:
            out.append(Record('alive', who=who, value='dead', scene_id=scene,
                              quote=f'death_scene {scene}', origin='registry', index=10 ** 6))
    return out


def sheet_holdings(project_dir: str, scene_id: str, objects: set[str]
                   ) -> tuple[list[Record], str]:
    """`holds has` records for the objects in `objects` (keys, `object_key`)
    a hand holds on the scene's saved stage sheet (#647), when the sheet is
    of the scene's current prose; and why none were read ('' when there is
    no sheet, or it was read)."""
    from storyforge import stage_sheet
    path = stage_sheet.sheet_path(project_dir, scene_id)
    if not objects or not os.path.isfile(path):
        return [], ''
    try:
        sheet = stage_sheet.load_sheet(path)
        from storyforge.illustrations import read_scene_raw
        prose = read_scene_raw(project_dir, scene_id)
    except (OSError, ValueError, UnicodeDecodeError) as e:
        return [], f'{scene_id}\'s stage sheet could not be read ({e})'
    if prose is None or sheet.get('prose_sha256') != stage_sheet.prose_hash(prose):
        return [], ''   # a sheet of earlier prose: its hands say nothing now
    out = []
    for n, beat in enumerate(sheet.get('beats', [])):
        for e in beat.get('set', []):
            if (e.get('field') in stage_sheet.HANDS and e.get('who')
                    and object_key(e.get('value', '')) in objects):
                out.append(Record('holds', who=e['who'], item=e['value'], value='has',
                                  quote=e.get('quote', ''), scene_id=scene_id,
                                  origin='stage-sheet', index=n))
    return out, ''


def object_key(name: str) -> str:
    """An object's key: the stage sheet's (`stage_sheet._obj`: lower case,
    no articles or possessives)."""
    from storyforge.stage_sheet import _obj
    return _obj(name)


def part_key(name: str) -> str:
    """A body part's key: lower case, singular, without articles or a side
    word ("his left hand" → "hand")."""
    words = [w for w in re.findall(r"[a-z']+", (name or '').lower())
             if w not in ('the', 'a', 'an', 'his', 'her', 'their', 'its', 'my', 'your',
                          'left', 'right', 'of')]
    words = [w[:-1] if len(w) > 3 and w.endswith('s') and not w.endswith('ss') else w
             for w in words]
    return ' '.join(words)
