"""`storyforge bibles convert`: a bible essay into rows, by a model (#702).

#657 made a prose book's bibles rows (`storyforge.bibles`), and converting an
essay was done with the author in the elaborate skill. This is the paid
first pass: one structured call reads the essay beside the registries and
returns the facts it settles, the lines it quotes a character saying, and
terse notes for what resists rows. Code then holds the reply to the same
rules the import does, and to two of its own:

- **A voice line is the essay's words.** A line that isn't one of the
  essay's quotations (or a part of one at least `MIN_PART_WORDS` long) is
  left out and said, so neither its narration nor a model's line gets in: a model's line in `character-voices.csv`
  would be read as the character's own voice (#702: voice lines are the
  author's, never a model's). A description of how someone speaks isn't a
  line, and the prompt says so.
- **Nothing is imported unseen by default.** The rows go to
  `working/bibles/<essay>/` (`facts.csv`, `voices.csv`, `notes.md`,
  `left-out.md`) for the author to read and edit, then `bibles import
  ... --essay NAME`; `--import` imports them at once (the checks `bibles
  import` makes, all before anything is written).

How well it converts is measured on a labelled set of synthetic essays
(`evals/suites/bibles_convert.py`): facts found, typed and placed, voice
lines kept, interpretation left out.
"""

from __future__ import annotations

import json
import os
from dataclasses import dataclass, field

from storyforge.bibles import ESSAYS, IMPORT_TYPES, REVEAL_CATEGORIES, VOICES_COLUMNS

#: The task's model tier (`common.select_model`): reading an essay and
#: sorting fact from interpretation, as evaluation does
MODEL_TASK = 'evaluation'
#: The reply's budget: an essay of a few thousand words is about 60-150 rows
MAX_TOKENS = 12_000
#: Where the conversion is written for review, under the project
REVIEW_DIR = os.path.join('working', 'bibles')
#: The facts file's columns (`bibles import` reads it)
FACT_COLUMNS = ('type', 'subject', 'statement', 'known_by', 'category')
#: Categories that mark a description of how someone speaks: never a fact
#: (#657: a voice is lines of them speaking), so such a row is left out
SPEECH_CATEGORIES = ('voice', 'speech', 'dialogue', 'diction')
#: Why a voice line the essay doesn't quote is left out; the eval suite
#: counts invented lines by it (`invented_lines`)
NOT_QUOTED = 'not quoted in the essay as written, so not the author\'s line'
#: Forecast: tokens per character of prompt, and the reply's tokens
_TOKENS_PER_CHAR = 0.3
FORECAST_OUTPUT = 4_000

_STRING = {'type': 'string'}


def _object(properties: dict) -> dict:
    return {'type': 'object', 'additionalProperties': False,
            'required': list(properties), 'properties': properties}


SCHEMA = _object({
    'facts': {'type': 'array', 'items': _object({
        'type': {'type': 'string', 'enum': list(IMPORT_TYPES)},
        'subject': _STRING, 'statement': _STRING, 'known_by': _STRING,
        'category': _STRING})},
    'voices': {'type': 'array', 'items': _object({'character': _STRING, 'line': _STRING})},
    'notes': {'type': 'array', 'items': _STRING},
})


class ConvertError(RuntimeError):
    """An essay that can't be converted (not there, not an essay, a graphic
    novel's) or a reply that can't be used; the message says which.
    `response` is the paid reply when there was one (a refusal, a reply cut
    off), so its cost can still be logged."""

    def __init__(self, message: str, response: dict | None = None):
        super().__init__(message)
        self.response = response


@dataclass
class Conversion:
    """What the reply gave, held to the rules: `facts` (dicts of
    `FACT_COLUMNS`), `voices` ((character, line) pairs, each in the essay as
    written), `notes` (terse lines), and `left_out` (each item the reply gave
    that isn't kept, with why)."""
    essay: str
    facts: list[dict] = field(default_factory=list)
    voices: list[tuple[str, str]] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)
    left_out: list[str] = field(default_factory=list)


def essay_text(project_dir: str, name: str) -> str:
    """The essay's text, refusing (ConvertError) a name that isn't a bible
    essay, a graphic novel (its script reads the essays' Visual sections),
    and an essay that isn't in reference/ with the author's text."""
    from storyforge.bibles import essay_state
    from storyforge.common import ReferenceDocError, get_medium, reference_text
    if name not in ESSAYS:
        raise ConvertError(f'{name} is not a bible essay (one of {", ".join(ESSAYS)})')
    if get_medium(project_dir) == 'graphic-novel':
        raise ConvertError('a graphic novel keeps its bible essays: its script reads their '
                           'Visual sections')
    state = essay_state(project_dir, name)
    if state != 'essay':
        raise ConvertError(f'reference/{name} is {_STATE_WORDS[state]}: nothing to convert')
    try:
        return reference_text(os.path.join(project_dir, 'reference', name))
    except ReferenceDocError as e:
        raise ConvertError(str(e)) from e


_STATE_WORDS = {'retired': 'retired to reference/archive/ (converted already)',
                'template': "the template, unfilled", 'none': 'not there', 'essay': 'an essay'}


def _registry(project_dir: str, name: str) -> list[dict]:
    from storyforge.common import ReferenceDocError
    from storyforge.elaborate import _read_csv
    path = os.path.join(project_dir, 'reference', name)
    try:
        return [r for r in _read_csv(path) if (r.get('id') or '').strip()]
    except (OSError, UnicodeDecodeError) as e:
        raise ReferenceDocError(path, e) from e


def _registry_lines(rows: list[dict]) -> str:
    return '\n'.join(f'- {r["id"].strip()}: {(r.get("name") or "").strip()}'
                     + (f' (also {r["aliases"].strip()})' if (r.get('aliases') or '').strip()
                        else '') for r in rows) or '(none)'


def build_prompt(name: str, essay: str, characters: list[dict], places: list[dict]) -> str:
    """The conversion prompt: the essay, the registries' ids, and the rules
    the rows keep (the elaborate stages' `BIBLE_ROWS_FORMAT`, as fields)."""
    kind = {'character-bible.md': 'character bible', 'world-bible.md': 'world bible',
            'systems-bible.md': 'systems bible'}[name]
    return f"""A novel's {kind} is an essay. Turn it into rows: the facts it settles, the lines it quotes a character saying, and terse notes for what really resists rows. Drafting reads the rows as the book's settled facts, so a row must say only what the essay settles, in a few plain words.

## The characters (use the id as a subject)

{_registry_lines(characters)}

## The places (use the id as a subject)

{_registry_lines(places)}

## The essay (reference/{name})

<essay>
{essay}
</essay>

## What to return

**facts**: one row for each fact the essay settles. Every settled fact, not a sample: a person's age, kin, history, want, need, wound, lie; who is related to whom, who owes whom; each rule of the world or of a system, each cost and limit.
- `type`: `trait` (about one person), `relationship` (between people; the statement names both), `world` (a rule of the world, a place, an institution, a system and its costs) or `knowledge` (a secret: something someone knows that others don't).
- `subject`: the character's or place's id from the lists above; empty for the world as a whole. A relationship's subject is one of the two.
- `statement`: the fact in a few plain words, in your own words, never a sentence lifted for its style. No interpretation: leave out what a character represents or symbolises, what a theme means, what the arc does for the reader, whose point of view a scene takes, and advice to the writer. How someone speaks is not a fact either: leave it out (their quoted lines go in voices).
- `known_by`: only for `knowledge`, the ids of who knows it from the start, `;`-separated.
- `category`: one word for the kind (want, need, wound, lie, age, kinship, history, rule, cost, limit, institution, ...). A secret is `knowledge` with category `secret`.
- A question the essay leaves open is a row whose statement ends in `?`.
- No `|` in any field.

**voices**: the lines the essay quotes a character saying, each copied exactly as the essay has it, word for word, with the character's id. Never write a line, finish one or tidy one; a description of how someone speaks is not a line (leave it out). None when the essay quotes no one.

**notes**: only what resists rows (a culture's feel, a history's shape), each a terse line. Interpretation is not a note either: leave out arcs, themes, symbols, point-of-view plans, how a scene should feel and advice to the writer. None is fine.
"""


def _normal(text: str) -> str:
    """Text for finding a quoted line in the essay: curly quotes straight,
    dashes as `-`, whitespace collapsed, outer quotes off, case kept."""
    text = (text.replace('‘', "'").replace('’', "'").replace('“', '"')
            .replace('”', '"').replace('—', '-').replace('–', '-'))
    return ' '.join(text.split()).strip().strip('"\'').strip()


def quoted_spans(essay: str) -> list[str]:
    """What the essay puts in double quotes (`prose_analysis.dialogue_spans`,
    straight or curly), each `_normal`: a voice line must be inside one, so
    a phrase of the essay's own narration ("counts the drawers twice") is
    never taken for a character's line."""
    from storyforge.prose_analysis import dialogue_spans
    return [_normal(inner) for _, _, inner in dialogue_spans(essay)]


#: The fewest words a voice line that is only part of a quotation may have:
#: a fragment ("the") says nothing of a voice. A whole quotation may be
#: shorter ("Bah!"), as the author wrote it
MIN_PART_WORDS = 4


def _quoted(line: str, quoted: list[str]) -> bool:
    """Whether `line` is one of the essay's quotations, or a part of one at
    least `MIN_PART_WORDS` words long."""
    text = _normal(line)
    if not text:
        return False
    return any(text == q or (text in q and len(text.split()) >= MIN_PART_WORDS)
               for q in quoted)


def _resolver(rows: list[dict]) -> dict[str, str]:
    """Lowercase id, name or alias → id."""
    out: dict[str, str] = {}
    for r in rows:
        rid = r['id'].strip()
        for n in [rid, r.get('name', '')] + (r.get('aliases') or '').split(';'):
            if n.strip():
                out.setdefault(n.strip().lower(), rid)
    return out


def parse_reply(reply: str, name: str, essay: str, characters: list[dict],
                places: list[dict]) -> Conversion:
    """Hold a reply to the rules. Raises ConvertError when it isn't the
    schema's JSON object; every item left out is in `left_out` with why: a
    fact with no statement, a `|`, a secret's category on a type that isn't
    knowledge, a repeat; a voice line the essay doesn't quote as written, or
    whose speaker is no character, given twice; a `known_by` on a fact
    that isn't knowledge (dropped, the fact kept); a fact of a speech category
    (`SPEECH_CATEGORIES`: a description of how someone speaks); an empty
    note. A subject or `known_by`
    given as a name is turned into its id."""
    try:
        data = json.loads(reply)
    except ValueError as e:
        raise ConvertError(f'the reply isn\'t JSON ({e})') from e
    if not isinstance(data, dict) or not all(isinstance(data.get(k), list)
                                             for k in ('facts', 'voices', 'notes')):
        raise ConvertError('the reply isn\'t an object with facts, voices and notes lists')
    conv = Conversion(name)
    people = _resolver(characters)
    anyone = {**_resolver(places), **people}
    seen = set()
    for n, f in enumerate(data['facts'], start=1):
        if not isinstance(f, dict):
            conv.left_out.append(f'fact {n}: not an object')
            continue
        row = {k: ' '.join(str(f.get(k) or '').split()) for k in FACT_COLUMNS}
        where = f'fact {n} ({row["statement"][:50]!r})'
        if not row['statement']:
            conv.left_out.append(f'fact {n}: no statement')
            continue
        if row['type'] not in IMPORT_TYPES:
            conv.left_out.append(f'{where}: type {row["type"]!r} is not one of '
                                 f'{", ".join(IMPORT_TYPES)}')
            continue
        if any('|' in v for v in row.values()):
            conv.left_out.append(f'{where}: a `|` in a field')
            continue
        if row['type'] != 'knowledge' and row['category'].lower() in REVEAL_CATEGORIES:
            conv.left_out.append(f'{where}: category {row["category"]!r} on a {row["type"]} '
                                 f'fact (a secret is a knowledge fact)')
            continue
        if row['category'].lower() in SPEECH_CATEGORIES:
            conv.left_out.append(f'{where}: a description of how someone speaks (category '
                                 f'{row["category"]!r}); a voice is lines, never a fact')
            continue
        row['subject'] = anyone.get(row['subject'].lower(), row['subject'])
        if row['type'] == 'knowledge':
            row['known_by'] = ';'.join(people.get(k.strip().lower(), k.strip())
                                       for k in row['known_by'].split(';') if k.strip())
        elif row['known_by']:
            conv.left_out.append(f'{where}: known_by {row["known_by"]!r} dropped (only a '
                                 f'knowledge fact has one; a secret is a knowledge fact)')
            row['known_by'] = ''
        key = (row['type'], row['subject'], row['statement'].lower().rstrip('.'))
        if key in seen:
            conv.left_out.append(f'{where}: given twice')
            continue
        seen.add(key)
        conv.facts.append(row)
    quoted = quoted_spans(essay)
    for n, v in enumerate(data['voices'], start=1):
        if not isinstance(v, dict):
            conv.left_out.append(f'voice {n}: not an object')
            continue
        who = str(v.get('character') or '').strip()
        line = ' '.join(str(v.get('line') or '').split())
        cid = people.get(who.lower())
        if not line:
            conv.left_out.append(f'voice {n}: no line')
        elif not cid:
            conv.left_out.append(f'voice {n} ({line[:50]!r}): {who!r} is no character in '
                                 f'characters.csv')
        elif not _quoted(line, quoted):
            conv.left_out.append(f'voice {n} ({line[:50]!r}): {NOT_QUOTED}')
        elif '|' in line:
            conv.left_out.append(f'voice {n} ({line[:50]!r}): a `|` in the line')
        elif (cid, line) in conv.voices:
            conv.left_out.append(f'voice {n} ({line[:50]!r}): given twice')
        else:
            conv.voices.append((cid, line))
    for n, note in enumerate(data['notes'], start=1):
        text = ' '.join(str(note or '').split()).lstrip('-* ').strip()
        if text:
            conv.notes.append(text)
        else:
            conv.left_out.append(f'note {n}: empty')
    return conv


def forecast(model: str, prompt: str) -> float:
    """What the call would cost, in US dollars (a forecast: the reply varies)."""
    from storyforge.costs import calculate_cost
    return calculate_cost(model, int(len(prompt) * _TOKENS_PER_CHAR), FORECAST_OUTPUT)


def convert(project_dir: str, name: str, model: str, log_file: str = '',
            ) -> tuple[Conversion, dict]:
    """Ask the model to convert essay `name` and hold the reply to the
    rules. Returns the conversion and the response (for its cost).

    Raises:
        ConvertError: the essay can't be converted, or the reply can't be
            used (cut off, not JSON, a refusal).
        common.ReferenceDocError: the essay or a registry can't be read.
        RuntimeError: the API call failed.
    """
    from storyforge import api
    essay = essay_text(project_dir, name)
    characters = _registry(project_dir, 'characters.csv')
    places = _registry(project_dir, 'locations.csv')
    prompt = build_prompt(name, essay, characters, places)
    try:
        response = (api.invoke_to_file(prompt, model, log_file, MAX_TOKENS, label=f'convert {name}',
                                       output_schema=SCHEMA) if log_file else
                    api.invoke(prompt, model, MAX_TOKENS, label=f'convert {name}',
                               output_schema=SCHEMA))
    except api.RefusalError as e:
        raise ConvertError(f'the model refused to convert {name} ({e})', e.response) from e
    problem = api.stop_problem(response)
    if problem:
        raise ConvertError(f'the reply can\'t be used: {problem}', response)
    try:
        conv = parse_reply(api.extract_text(response), name, essay, characters, places)
    except ConvertError as e:
        raise ConvertError(str(e), response) from e
    return conv, response


def existing_review(project_dir: str, name: str) -> list[str]:
    """The review files an earlier `convert` of `name` left (which the
    author may have edited): a new conversion refuses to replace them
    without `--overwrite`."""
    return [p for p in review_paths(project_dir, name).values() if os.path.exists(p)]


def review_paths(project_dir: str, name: str) -> dict[str, str]:
    """Where `write_review` puts each file, by kind."""
    base = os.path.join(project_dir, REVIEW_DIR, os.path.splitext(name)[0])
    return {'facts': os.path.join(base, 'facts.csv'),
            'voices': os.path.join(base, 'voices.csv'),
            'notes': os.path.join(base, 'notes.md'),
            'left_out': os.path.join(base, 'left-out.md')}


def write_review(project_dir: str, conv: Conversion) -> dict[str, str]:
    """Write the conversion where `bibles import` reads it (LF, pipe CSV
    with headers; a file with nothing in it isn't written, and an older one
    is removed so it can't be imported by mistake: the command asks for
    `--overwrite` before any older file is replaced, `existing_review`).
    Returns (the paths written, by kind; the older files removed)."""
    paths = review_paths(project_dir, conv.essay)
    os.makedirs(os.path.dirname(paths['facts']), exist_ok=True)
    bodies = {
        'facts': ('|'.join(FACT_COLUMNS) + '\n'
                  + ''.join('|'.join(f[c] for c in FACT_COLUMNS) + '\n' for f in conv.facts)
                  if conv.facts else ''),
        'voices': ('|'.join(VOICES_COLUMNS) + '\n'
                   + ''.join(f'{who}|{line}\n' for who, line in conv.voices)
                   if conv.voices else ''),
        'notes': ''.join(f'- {n}\n' for n in conv.notes),
        'left_out': (f'# Left out of the conversion of {conv.essay}\n\n'
                     + ''.join(f'- {x}\n' for x in conv.left_out) if conv.left_out else ''),
    }
    written, removed = {}, []
    for kind, body in bodies.items():
        path = paths[kind]
        if body:
            with open(path, 'w', encoding='utf-8', newline='') as f:
                f.write(body)
            written[kind] = path
        elif os.path.exists(path):
            os.remove(path)
            removed.append(path)
    return written, removed
