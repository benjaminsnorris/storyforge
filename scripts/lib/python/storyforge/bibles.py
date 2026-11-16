"""Bibles as facts, not essays (#657, plan D2).

The character, world and systems bibles were model-written essays that every
drafting prompt and the gate's checker read whole, and their phrasing leaked
into the drafts the way briefs' did (#644). What's true about the people and
the world is now rows:

- **Facts** in the ledger (`reference/commitments.csv`): type `trait`,
  `relationship` or `world`, origin `plan`, status `binding`, a registry
  `introduced_by` (never a commitment writer): `essay_writer(name)` for an
  essay's conversion (`bibles import --essay NAME`), `WRITER` for any other
  import, `STAGE_WRITER` for an elaborate stage's, `extract_writer(name)`
  for extract phase 5's description of a finished book (#702). A secret or a reveal is a
  `knowledge` fact with `category` `secret` or `reveal`
  (`REVEAL_CATEGORIES`); `add_facts` refuses that category on any other
  type. A blank `scene_id` means true from before the first scene; a fact
  that becomes true in a scene names it. `add_facts` is the one writer,
  through `ledger.save` (so audit-logged).
- **Voices** in `reference/character-voices.csv` (`character|line`): a few
  lines of each character speaking, never a paragraph about their speech.
- **Notes** in `reference/bible-notes.md`: terse notes for what resists rows
  (a culture's feel, a history's shape). A line ending in `?` is a question
  the plan hasn't answered.

The essays stay where they are, read as before, until they are converted:
`retire` moves one to `reference/archive/` (`ARCHIVE_DIR`), where nothing
reads it and the author keeps it as reference. While an essay and rows of
its kind are both there (the mixed state every book in progress passes
through), every reader takes both: drafting's standing context, the checker
and `bible_text` carry the essay and the rows, and the two-writers test says
the essay's facts aren't seen.

Readers:
- `drafting_sections(project_dir)`: the facts true from the start (every
  subject, never a secret), the voices and the notes, for the drafting
  prompts' standing context.
- `unrevealed_secrets(...)`: the secrets a scene's drafting slice withholds
  until the scene that reveals them.
- `checker_doc(project_dir)`: the standing facts with their ids, for the
  gate's checker (`checker.reference_docs`, as `FACTS_DOC`).
- `bible_text(project_dir, name)`: one bible whole (essay and rows) for a
  reader that takes a bible (hone, scoring, illustrate's art direction).
- `plan_gaps(ref_dir)` → `(gaps, notes)`: the two-writers test, the gaps
  code can see in the plan, and what it couldn't check.
  `elaborate.validate_structure` reports both as advisory, so `validate`
  and every elaborate stage review list them.
"""

from __future__ import annotations

import os
import re
import shutil
from dataclasses import dataclass
from typing import Literal, get_args

from storyforge.common import log

#: `introduced_by` of facts imported without naming an essay
WRITER = 'bibles'
#: `introduced_by` of facts an elaborate stage writes (`cmd_elaborate`)
STAGE_WRITER = 'elaborate'
#: The `introduced_by` prefix of facts extract phase 5 writes for a
#: described book (#702, `extract_writer`)
EXTRACT_WRITER = 'extract'
#: The types a bible's standing facts take. Never `knowledge`: a secret in
#: the standing context gives the reveal away in the first scene
FACT_TYPES = ('trait', 'relationship', 'world')
#: What `add_facts` takes: the bible's types, and `knowledge` for a secret
IMPORT_TYPES = FACT_TYPES + ('knowledge',)
#: The origins of a plan's facts (the plan's, and the author's own)
PLAN_ORIGINS = ('plan', 'author')
#: The essays the rows replace, and the types that convert each
ESSAY_TYPES = {'character-bible.md': ('trait', 'relationship'),
               'world-bible.md': ('world',), 'systems-bible.md': ('world',)}
ESSAYS = tuple(ESSAY_TYPES)
#: storyforge.yaml `artifacts:` entry of each essay (`retire` sets `exists: false`)
ESSAY_ARTIFACTS = {'character-bible.md': 'character_bible', 'world-bible.md': 'world_bible',
                   'systems-bible.md': 'systems_bible'}
#: Where a converted essay goes, kept as the author's reference, read by nothing
ARCHIVE_DIR = os.path.join('reference', 'archive')
VOICES_FILE = 'character-voices.csv'
VOICES_COLUMNS = ['character', 'line']
NOTES_FILE = 'bible-notes.md'
#: The checker's name for the facts (`checker.reference_docs`): a finding
#: against one cites it, and the author finds the row in that file
FACTS_DOC = 'commitments.csv'
#: The columns `storyforge bibles import` reads (the first three required)
IMPORT_COLUMNS = ('type', 'subject', 'statement', 'known_by', 'scene_id', 'category', 'id')
#: A knowledge fact in one of these categories is a reveal even when someone
#: knows it from the start: the plan owes the scene where it comes out, and
#: drafting doesn't see it before that scene
REVEAL_CATEGORIES = ('secret', 'reveal')

#: A relationship or world rule that hasn't decided: a question, or a hedge
#: word. Narrow on purpose (#697's review): "may be summoned" is a rule,
#: "uncertain near running water" a fact, "either Dorren or no one" settled;
#: "may have known" and "might have been" are guesses about what happened
_HEDGE = re.compile(r'\?\s*$|\b(maybe|perhaps|possibly|unclear|undecided|tbd|tbc|'
                    r'not yet decided|may or may not|(?:may|might) have)\b', re.I)

GapKind = Literal['unsettled-reveal', 'ambiguous-relationship', 'open-world-rule',
                  'open-question']
GAP_KINDS: tuple[str, ...] = get_args(GapKind)
EssayState = Literal['essay', 'retired', 'template', 'none']


class BiblesError(RuntimeError):
    """Rows that can't be added as they are, or an essay that can't be
    retired; the message names each problem."""


@dataclass(frozen=True)
class Gap:
    """One gap the two-writers test sees: two writers drafting from the plan
    could disagree here. `ref` is the fact id, or `bible-notes.md line N`."""
    kind: GapKind
    ref: str
    subject: str
    detail: str

    def __post_init__(self):
        assert self.kind in GAP_KINDS, self.kind

    def message(self) -> str:
        who = f' ({self.subject})' if self.subject else ''
        return f'{self.kind}: {self.ref}{who}: {self.detail}'

    def slug(self) -> str:
        """`ref` as a check id's tail (no spaces or dots)."""
        return re.sub(r'[^A-Za-z0-9_-]+', '-', self.ref).strip('-')


def extract_writer(name: str) -> str:
    """The `introduced_by` of the facts extract phase 5 writes in essay
    `name`'s place (`extract:character-bible`, #702): phase 5's own rows,
    which a re-run with `--force` adds to and nothing else touches."""
    return f'{EXTRACT_WRITER}:{os.path.splitext(name)[0]}'


def essay_writer(name: str) -> str:
    """The `introduced_by` of the facts converted from essay `name`
    (`bibles:character-bible`), which `retire` looks for."""
    return f'{WRITER}:{os.path.splitext(name)[0]}'


# ============================================================================
# Reading
# ============================================================================

def _ref(project_dir: str, *parts: str) -> str:
    return os.path.join(project_dir, 'reference', *parts)


def is_secret(row: dict) -> bool:
    return (row.get('category') or '').strip().lower() in REVEAL_CATEGORIES


def is_plan_fact(row: dict) -> bool:
    """A fact the plan settled: origin `plan` or `author`, not a commitment
    (what the prose said)."""
    from storyforge.ledger import is_commitment
    return row.get('origin') in PLAN_ORIGINS and not is_commitment(row)


def is_bible_fact(row: dict) -> bool:
    """A plan's binding fact about the people or the world: a `trait`,
    `relationship` or `world` plan fact, never a secret (a hand-written row
    marked `secret` on another type is withheld too)."""
    return (row.get('type') in FACT_TYPES and row.get('status') == 'binding'
            and is_plan_fact(row) and not is_secret(row))


def standing_facts(rows: list[dict]) -> list[dict]:
    """The bible facts true from the start (blank `scene_id`): what a reader
    holds every scene to. A fact that becomes true in a scene reaches that
    scene and the later ones through the ledger (`drafting_slice`, the
    checker's ledger tool), never the standing context, which would show it
    before it happens."""
    return [r for r in rows if is_bible_fact(r) and not (r.get('scene_id') or '').strip()]


def _names(project_dir: str) -> dict[str, str]:
    """Registry id → display name, from `ledger.NAME_REGISTRIES`.

    Raises:
        common.ReferenceDocError: a registry exists but can't be read.
    """
    from storyforge.common import ReferenceDocError
    from storyforge.elaborate import _read_csv
    from storyforge.ledger import NAME_REGISTRIES
    out = {}
    for registry in NAME_REGISTRIES:
        path = _ref(project_dir, registry)
        try:
            rows = _read_csv(path)
        except (OSError, UnicodeDecodeError) as e:
            raise ReferenceDocError(path, e) from e
        for r in rows:
            if (r.get('id') or '').strip():
                out[r['id'].strip()] = (r.get('name') or '').strip() or r['id'].strip()
    return out


def _grouped(rows: list[dict], names: dict[str, str], with_ids: bool) -> str:
    """Facts grouped under their subject's name (the world last)."""
    groups: dict[str, list[str]] = {}
    for r in rows:
        subject = (r.get('subject') or '').strip()
        label = names.get(subject, subject) if subject else 'The world'
        line = f'- [{r["id"]}] {r["statement"].strip()}' if with_ids else f'- {r["statement"].strip()}'
        groups.setdefault(label, []).append(line)
    order = sorted(groups, key=lambda k: k == 'The world')   # stable: else as first named
    return '\n\n'.join(f'### {k}\n' + '\n'.join(groups[k]) for k in order)


def _plain_rows(path: str) -> tuple[list[str], list[tuple[int, dict[str, str] | str]]]:
    """Header and rows of a pipe-delimited file split on `|` alone: a voice
    line or a statement in quotes keeps them (the csv module would read a
    leading `"` as quoting). Each row is (line number, cells by column), or
    (line number, the problem) for a row whose cell count isn't the
    header's: a `|` inside a cell would shift every later cell, so such a
    row is never read as data. Missing file → ([], []).

    Raises:
        OSError, UnicodeDecodeError: the file can't be read.
    """
    from storyforge.ledger import _raw_lines
    if not os.path.isfile(path):
        return [], []
    lines, _ = _raw_lines(path)
    if not lines:
        return [], []
    header = [h.strip() for h in lines[0].lstrip('﻿').split('|')]
    rows: list[tuple[int, dict[str, str] | str]] = []
    for n, line in enumerate(lines[1:], start=2):
        if not line.strip():
            continue
        cells = line.split('|')
        if len(cells) != len(header):
            rows.append((n, f'{len(cells)} cells where the header has {len(header)} '
                            f'(a `|` inside a cell?): {line[:60]!r}'))
            continue
        rows.append((n, {h: c.strip() for h, c in zip(header, cells)}))
    return header, rows


def _import_rows(path: str, required: tuple[str, ...], allowed: tuple[str, ...]) -> list[dict]:
    """An import file's rows, refusing (BiblesError) a file that can't be
    read, a header without `required` or with a column not in `allowed`
    (a typo would lose that column's data on every row), and any row whose
    cell count isn't the header's."""
    if not os.path.isfile(path):
        raise BiblesError(f'{path} doesn\'t exist')
    try:
        header, rows = _plain_rows(path)
    except (OSError, UnicodeDecodeError) as e:
        raise BiblesError(f'{path} can\'t be read as UTF-8 text ({e})') from e
    missing = [c for c in required if c not in header]
    unknown = [c for c in header if c not in allowed]
    if missing or unknown:
        raise BiblesError(f'{path}: ' + '; '.join(filter(None, [
            missing and f'the header has no {", ".join(missing)} column',
            unknown and f'columns it doesn\'t take: {", ".join(unknown)}']))
            + f' (it takes {"|".join(allowed)}, with a header row)')
    bad = [f'line {n}: {r}' for n, r in rows if isinstance(r, str)]
    if bad:
        raise BiblesError(f'{path}: ' + '; '.join(bad) + '. Nothing was added')
    return [r for _, r in rows]


def block_rows(label: str, text: str, required: tuple[str, ...],
               allowed: tuple[str, ...]) -> list[dict]:
    """A stage reply's bible block as rows, checked as `_import_rows`
    checks a file (BiblesError naming the block's line)."""
    lines = [l for l in (text or '').strip().split('\n') if l.strip()]
    if not lines:
        return []
    header = [h.strip() for h in lines[0].split('|')]
    missing = [c for c in required if c not in header]
    unknown = [c for c in header if c not in allowed]
    if missing or unknown:
        raise BiblesError(f'the {label} block: ' + '; '.join(filter(None, [
            missing and f'the header has no {", ".join(missing)} column',
            unknown and f'columns it doesn\'t take: {", ".join(unknown)}'])))
    rows, bad = [], []
    for n, line in enumerate(lines[1:], start=2):
        cells = line.split('|')
        if len(cells) != len(header):
            bad.append(f'line {n}: {len(cells)} cells where the header has {len(header)}: '
                       f'{line.strip()[:60]!r}')
            continue
        rows.append({h: c.strip() for h, c in zip(header, cells)})
    if bad:
        raise BiblesError(f'the {label} block: ' + '; '.join(bad))
    return rows


def read_voices(project_dir: str) -> tuple[dict[str, list[str]], list[str]]:
    """character id → their lines, in file order; and the problems, one
    string each (a header without `character` and `line`: nothing in the
    file is read; a row with no character, no line, or the wrong number of
    cells: left out). No file → ({}, []). Validate reports the problems
    (`elaborate._validate_plan_gaps`); drafting WARNs them.

    Raises:
        common.ReferenceDocError: the file exists but can't be read.
    """
    from storyforge.common import ReferenceDocError
    path = _ref(project_dir, VOICES_FILE)
    if not os.path.isfile(path):
        return {}, []
    try:
        header, rows = _plain_rows(path)
    except (OSError, UnicodeDecodeError) as e:
        raise ReferenceDocError(path, e) from e
    if not header:
        return {}, []
    if not set(VOICES_COLUMNS) <= set(header):
        return {}, [f'reference/{VOICES_FILE}: the header must be {"|".join(VOICES_COLUMNS)} '
                    f'(it is {"|".join(header)}); no line in it is read']
    voices: dict[str, list[str]] = {}
    problems = []
    for n, r in rows:
        if isinstance(r, str):
            problems.append(f'reference/{VOICES_FILE} line {n}: {r}; left out')
            continue
        who, line = r.get('character', ''), r.get('line', '')
        if not who or not line:
            problems.append(f'reference/{VOICES_FILE} line {n}: '
                            + ('no character' if not who else 'no line') + '; left out')
            continue
        voices.setdefault(who, []).append(line)
    return voices, problems


def notes_text(project_dir: str) -> str:
    """bible-notes.md's text ('' when missing or empty).

    Raises:
        common.ReferenceDocError: it exists but can't be read.
    """
    from storyforge.common import reference_text
    return reference_text(_ref(project_dir, NOTES_FILE))


def _voices_said(project_dir: str) -> dict[str, list[str]]:
    """The voices, with each problem logged as a WARNING (a reader that
    leaves a line out says so)."""
    voices, problems = read_voices(project_dir)
    for p in problems:
        log(f'WARNING: {p}')
    return voices


def drafting_sections(project_dir: str) -> list[tuple[str, str]]:
    """The rows for the drafting prompts' standing context, as (label, text):
    'Settled Facts' (the bible facts true from the start, by subject),
    'How They Speak' (each character's lines) and 'Notes' (bible-notes.md),
    each only when there is one. A book with none gets [], so its prompts
    are as before. An essay not yet retired is still read beside these by
    the callers that read it (the mixed state).

    Raises:
        ledger.LedgerError: the ledger can't be read.
        common.ReferenceDocError: the voices, notes or a registry can't be read.
    """
    from storyforge import ledger
    sections = []
    facts = standing_facts(ledger.load(project_dir))
    voices = _voices_said(project_dir)
    names = _names(project_dir) if facts or voices else {}
    if facts:
        sections.append(('Settled Facts',
                         'What is true from the start about the people and the world: facts '
                         'to honour, not lines or images to reuse.\n\n'
                         + _grouped(facts, names, with_ids=False)))
    if voices:
        parts = [f'{names.get(who, who)}:\n' + '\n'.join(f'> {line}' for line in lines)
                 for who, lines in voices.items()]
        sections.append(('How They Speak',
                         "A few lines in each character's own voice, to hear them by: not "
                         'lines to reuse.\n\n' + '\n\n'.join(parts)))
    notes = notes_text(project_dir)
    if notes:
        sections.append(('Notes', notes))
    return sections


def drafting_text(project_dir: str, heading: str = '##') -> str:
    """`drafting_sections` as one prompt section ('' with none)."""
    return '\n\n'.join(f'{heading} {label}\n\n{text}'
                       for label, text in drafting_sections(project_dir))


def _reveal_positions(ref_dir: str, order: dict[str, int]) -> dict[str, int]:
    """Fact id → the earliest reading position of a live brief whose
    `knowledge_out` names it."""
    from storyforge.elaborate import _read_csv
    from storyforge.ledger import _split
    from storyforge.schema import INACTIVE_STATUSES
    inactive = {(r.get('id') or '').strip() for r in _read_csv(os.path.join(ref_dir, 'scenes.csv'))
                if (r.get('status') or '').strip() in INACTIVE_STATUSES}
    out: dict[str, int] = {}
    for b in _read_csv(os.path.join(ref_dir, 'scene-briefs.csv')):
        sid = (b.get('id') or '').strip()
        pos = order.get(sid)
        if pos is None or sid in inactive:
            continue
        for fid in _split(b.get('knowledge_out', '')):
            out[fid] = min(out.get(fid, pos), pos)
    return out


def unrevealed_secrets(ref_dir: str, rows: list[dict], scene_id: str,
                       order: dict[str, int]) -> set[str]:
    """The ids of the secrets (`REVEAL_CATEGORIES`, any type) that scene
    `scene_id` mustn't see yet: no scene at or before it establishes the
    fact (`scene_id`) or reveals it (a live brief's `knowledge_out`; a cut
    or merged scene reveals nothing). A secret no scene reveals is withheld
    everywhere. `order` is the reading order (`ledger.scene_order`).

    Raises:
        OSError, UnicodeDecodeError: scenes.csv or scene-briefs.csv can't be read.
    """
    secrets = [r for r in rows if is_secret(r)]
    if not secrets or scene_id not in order:
        return {r['id'] for r in secrets}
    at = order[scene_id]
    reveals = _reveal_positions(ref_dir, order)
    withheld = set()
    for r in secrets:
        positions = [p for p in (order.get((r.get('scene_id') or '').strip()),
                                 reveals.get(r['id'])) if p is not None]
        if not positions or min(positions) > at:
            withheld.add(r['id'])
    return withheld


def checker_doc(project_dir: str, rows: list[dict] | None = None) -> str:
    """The bible facts true from the start, with their ids, for the gate's
    checker ('' with none).

    Raises:
        ledger.LedgerError: the ledger can't be read (when `rows` isn't given).
        common.ReferenceDocError: a registry can't be read.
    """
    from storyforge import ledger
    facts = standing_facts(rows if rows is not None else ledger.load(project_dir))
    if not facts:
        return ''
    return ('The book\'s settled facts: rows of reference/commitments.csv, true from '
            'before the first scene. Cite one by its id (`fact_id`) or by this file.\n\n'
            + _grouped(facts, _names(project_dir), with_ids=True))


def rows_text(project_dir: str, name: str) -> str:
    """What stands in for essay `name` as rows ('' with none): for
    character-bible.md the standing trait and relationship facts and the
    voices, for world-bible.md and systems-bible.md the standing world facts
    and the notes.

    Raises:
        common.ReferenceDocError: the voices, notes or a registry can't be read.
        ledger.LedgerError: the ledger can't be read.
    """
    from storyforge import ledger
    if name not in ESSAY_TYPES:
        return ''
    types = ESSAY_TYPES[name]
    facts = [r for r in standing_facts(ledger.load(project_dir)) if r['type'] in types]
    character = name == 'character-bible.md'
    voices = _voices_said(project_dir) if character else {}
    names = _names(project_dir) if facts or voices else {}
    parts = []
    if facts:
        parts.append(_grouped(facts, names, with_ids=False))
    if voices:
        parts.append('### How they speak\n' + '\n'.join(
            f'{names.get(who, who)}: {line}' for who, lines in voices.items() for line in lines))
    if not character:
        notes = notes_text(project_dir)
        if notes:
            parts.append(notes)
    return '\n\n'.join(parts)


def bible_text(project_dir: str, name: str) -> str:
    """One bible's text, for a reader that takes a bible whole (hone, the
    novel-level character score, `score --bible-consistency`, illustrate's
    art direction): the essay while it's still in reference/
    (`common.reference_text`), then its rows (`rows_text`). Both when both
    are there (the mixed state), the rows under their own heading. '' when
    there is neither.

    Raises:
        common.ReferenceDocError: a file exists but can't be read.
        ledger.LedgerError: the ledger can't be read.
    """
    from storyforge.common import reference_text
    essay = reference_text(_ref(project_dir, name))
    rows = rows_text(project_dir, name)
    if essay and rows:
        return (f'{essay}\n\n## Facts as rows (reference/commitments.csv; the essay above is '
                f'not converted yet)\n\n{rows}')
    return essay or rows


# ============================================================================
# Essays: converted or not
# ============================================================================

def essay_state(project_dir: str, name: str) -> EssayState:
    """'essay' (in reference/ with the author's text, still read), 'retired'
    (in the archive, read by nothing), 'template' (init's copy, unfilled) or
    'none'."""
    from storyforge.common import is_unfilled_template
    path = _ref(project_dir, name)
    if os.path.isfile(path):
        if is_unfilled_template(path):
            return 'template'
        try:
            with open(path, encoding='utf-8-sig') as f:
                return 'essay' if f.read().strip() else 'none'
        except (OSError, UnicodeDecodeError):
            return 'essay'   # can't be read: the readers say so
    if os.path.isfile(os.path.join(project_dir, ARCHIVE_DIR, name)):
        return 'retired'
    return 'none'


def unconverted(project_dir: str) -> list[str]:
    """The essays still in reference/ with the author's text."""
    return [n for n in ESSAYS if essay_state(project_dir, n) == 'essay']


_HEADING = re.compile(r'^##\s+(.+?)\s*$', re.M)


def _essay_characters(text: str, project_dir: str) -> tuple[list[str], list[str]]:
    """The registry character ids an essay's `##` headings name, and the
    headings no characters.csv character matches."""
    from storyforge.elaborate import _read_csv
    from storyforge.ledger import _norm, _split
    keys: dict[str, str] = {}
    for c in _read_csv(_ref(project_dir, 'characters.csv')):
        cid = (c.get('id') or '').strip()
        for p in [cid, c.get('name', '')] + _split(c.get('aliases', '')):
            if _norm(p):
                keys.setdefault(_norm(p), cid)
    ids, unmatched = [], []
    for heading in _HEADING.findall(text):
        name = re.split(r'\s*[:(—–-]\s', heading, maxsplit=1)[0]
        cid = keys.get(_norm(name)) or keys.get(_norm(heading))
        if cid:
            if cid not in ids:
                ids.append(cid)
        else:
            unmatched.append(heading)
    return ids, unmatched


def retire(project_dir: str, name: str, *, force: bool = False,
           dry_run: bool = False) -> tuple[str, list[str]]:
    """Move a converted essay to the archive and set its storyforge.yaml
    artifact's `exists: false`; returns (its new path relative to the
    project, notes on what the rows cover).

    Refused (BiblesError) for a name that isn't an essay, an essay not in
    reference/, one already in the archive, and, without `force`, one not
    converted: no fact `bibles import --essay NAME` wrote
    (`essay_writer(name)`; facts an elaborate stage or a plain import wrote
    don't count, since they say nothing of this essay), or, for
    character-bible.md, a character one of its `##` headings names with no
    bible fact. The notes say how many facts each covered character has and
    which headings match no character (not checked).

    Raises:
        BiblesError: as above.
        ledger.LedgerError: the ledger can't be read.
    """
    from storyforge import ledger
    if name not in ESSAYS:
        raise BiblesError(f'{name} is not a bible essay (one of {", ".join(ESSAYS)})')
    src = _ref(project_dir, name)
    dest = os.path.join(project_dir, ARCHIVE_DIR, name)
    if os.path.exists(dest):
        raise BiblesError(f'{ARCHIVE_DIR}/{name} already exists: nothing was moved')
    if not os.path.isfile(src):
        raise BiblesError(f'reference/{name} doesn\'t exist: nothing to retire')
    rows = ledger.load(project_dir)
    types = ESSAY_TYPES[name]
    facts = [r for r in rows if is_bible_fact(r) and r['type'] in types]
    converted = [r for r in rows if is_plan_fact(r)
                 and (r.get('introduced_by') or '') == essay_writer(name)]
    problems, notes = [], []
    if not converted:
        problems.append(f'no fact was converted from it (`storyforge bibles import FILE '
                        f'--essay {name}`)')
    if name == 'character-bible.md':
        try:
            with open(src, encoding='utf-8-sig') as f:
                text = f.read()
        except (OSError, UnicodeDecodeError) as e:
            raise BiblesError(f'reference/{name} can\'t be read ({e}): nothing was moved') from e
        ids, unmatched = _essay_characters(text, project_dir)
        by_subject = {cid: sum(r.get('subject') == cid for r in facts) for cid in ids}
        bare = [cid for cid, n in by_subject.items() if not n]
        if bare:
            problems.append(f'its characters with no fact as a row: {", ".join(bare)}')
        if by_subject:
            notes.append('facts per character: ' + ', '.join(f'{c} {n}' for c, n in by_subject.items()))
        if unmatched:
            notes.append(f'headings no characters.csv character matches (not checked): '
                         f'{", ".join(unmatched)}')
    else:
        notes.append(f'{len(facts)} world fact(s) from the plan in the ledger')
    if problems and not force:
        raise BiblesError(f'reference/{name} isn\'t converted: ' + '; '.join(problems)
                          + '. Convert it first, or pass --force to retire it anyway; '
                          'nothing was moved')
    if problems:
        notes.append('retired with --force although ' + '; '.join(problems))
    if not dry_run:
        os.makedirs(os.path.dirname(dest), exist_ok=True)
        shutil.move(src, dest)
        from storyforge.common import update_artifact_entry
        update_artifact_entry(project_dir, ESSAY_ARTIFACTS[name], exists=False)
    return os.path.relpath(dest, project_dir), notes


# ============================================================================
# Writing facts
# ============================================================================

def _slug(text: str, words: int = 6) -> str:
    tokens = re.findall(r'[a-z0-9]+', (text or '').lower())
    return '-'.join(tokens[:words])


def _new_id(subject: str, type_: str, statement: str, taken: set[str]) -> str:
    base = '-'.join(filter(None, [_slug(subject, 3), _slug(statement, 5)])) or type_
    rid, n = base, 2
    while rid in taken:
        rid, n = f'{base}-{n}', n + 1
    return rid


_BAD_ID = re.compile(r'[\s;|]')


def add_facts(project_dir: str, items: list[dict], *, command: str,
              writer: str = WRITER, dry_run: bool = False) -> tuple[list[str], list[str]]:
    """Add plan facts to the ledger: each item has `type` (`IMPORT_TYPES`),
    `subject` (a registry id, or blank for the world), `statement`, and
    optionally `known_by` (`;` ids), `scene_id`, `category` and `id`.

    Each row is origin `plan`, status `binding`, `introduced_by` `writer`,
    mutable `fixed` (`state` for knowledge, as the migration writes it). An
    id is made from the subject and statement when not given. Returns (the
    ids added, or that would be with `dry_run`; notes): a subject, `known_by`
    or `scene_id` no registry or scene names is added as written and noted;
    a fact that states what a registry row already states (`ledger.fact_key`:
    case, spacing and end punctuation aside), or an earlier item does, is
    skipped and noted, so a re-run adds nothing. A commitment (what the
    prose said) or a rejected or superseded row doesn't count.

    Raises:
        BiblesError: an item that can't be a row (no statement, a type that
            isn't one, a `|` or a line break in a cell, a secret's category
            on a type other than knowledge, an id with a space or `;`, an id
            the ledger has or an earlier item gave), each named; nothing is
            written.
        ledger.LedgerError: the ledger can't be read or written.
        common.ReferenceDocError: a registry can't be read.
    """
    from storyforge import ledger
    from storyforge.elaborate import _read_csv
    rows = ledger.load(project_dir)
    ledger_ids = {r['id'] for r in rows}
    stated = {ledger.fact_key(r): r['id'] for r in rows
              if not ledger.is_commitment(r) and r.get('status') not in ('rejected', 'superseded')}
    names = _names(project_dir)
    scenes = {(r.get('id') or '').strip() for r in _read_csv(_ref(project_dir, 'scenes.csv'))}
    problems, notes, new = [], [], []
    batch_ids: dict[str, int] = {}
    batch_facts: dict[tuple, int] = {}
    for n, item in enumerate(items, start=1):
        where = f'item {n}' + (f' ({item.get("id")})' if item.get('id') else '')
        cells = {k: (item.get(k) or '').strip() for k in IMPORT_COLUMNS}
        bad = [k for k, v in item.items() if isinstance(v, str) and ('|' in v or '\n' in v)]
        if bad:
            problems.append(f'{where}: a `|` or a line break in {", ".join(sorted(bad))}')
            continue
        if cells['type'] not in IMPORT_TYPES:
            problems.append(f'{where}: type {cells["type"]!r} is not one of {", ".join(IMPORT_TYPES)}')
            continue
        if not cells['statement']:
            problems.append(f'{where}: no statement')
            continue
        if cells['type'] != 'knowledge' and cells['category'].lower() in REVEAL_CATEGORIES:
            problems.append(f'{where}: category {cells["category"]!r} on a {cells["type"]} fact: '
                            f'a secret is a knowledge fact (drafting withholds it until the '
                            f'scene that reveals it)')
            continue
        rid = cells['id']
        if rid and _BAD_ID.search(rid):
            problems.append(f'{where}: id {rid!r} has a space, `;` or `|`')
            continue
        if rid in ledger_ids:
            problems.append(f'{where}: id {rid!r} is already in the ledger')
            continue
        if rid in batch_ids:
            problems.append(f'{where}: id {rid!r} is also item {batch_ids[rid]}\'s')
            continue
        key = ledger.fact_key({'subject': cells['subject'], 'type': cells['type'],
                               'statement': cells['statement']})
        if key in stated:
            notes.append(f'{where}: the ledger already states this fact ({stated[key]}); skipped')
            continue
        if key in batch_facts:
            notes.append(f'{where}: item {batch_facts[key]} states this fact; skipped')
            continue
        rid = rid or _new_id(cells['subject'], cells['type'], cells['statement'],
                             ledger_ids | set(batch_ids))
        batch_ids[rid] = n
        batch_facts[key] = n
        if cells['subject'] and cells['subject'] not in names:
            notes.append(f'{rid}: subject {cells["subject"]!r} is in no registry '
                         f'(characters.csv, locations.csv); added as written')
        unknown = [k for k in ledger._split(cells['known_by']) if k not in names]
        if unknown:
            notes.append(f'{rid}: known_by {", ".join(unknown)} in no registry; added as written')
        if cells['scene_id'] and cells['scene_id'] not in scenes:
            notes.append(f'{rid}: scene_id {cells["scene_id"]!r} is not a scene in scenes.csv; '
                         f'added as written')
        row = {c: '' for c in ledger.COLUMNS}
        row.update(id=rid, scene_id=cells['scene_id'], type=cells['type'],
                   subject=cells['subject'], statement=cells['statement'], origin='plan',
                   status='binding',
                   mutable='state' if cells['type'] == 'knowledge' else 'fixed',
                   known_by=cells['known_by'], introduced_by=writer,
                   category=cells['category'])
        new.append(row)
    if problems:
        raise BiblesError('; '.join(problems) + '. Nothing was added')
    if new and not dry_run:
        ledger.save(project_dir, rows + new, command=command)
    return [r['id'] for r in new], notes


def read_import(path: str) -> list[dict]:
    """A pipe-delimited file of facts for `add_facts`, with a header row
    (`IMPORT_COLUMNS`, the first three required, no others).

    Raises:
        BiblesError: as `_import_rows`.
    """
    return _import_rows(path, IMPORT_COLUMNS[:3], IMPORT_COLUMNS)


def read_voice_import(path: str) -> list[tuple[str, str]]:
    """(character, line) pairs from a `character|line` file for `add_voices`.

    Raises:
        BiblesError: as `_import_rows`.
    """
    rows = _import_rows(path, tuple(VOICES_COLUMNS), tuple(VOICES_COLUMNS))
    return [(r.get('character', ''), r.get('line', '')) for r in rows]


def add_voices(project_dir: str, lines: list[tuple[str, str]], *,
               dry_run: bool = False) -> tuple[int, list[str]]:
    """Append (character, line) rows to character-voices.csv (made with its
    header when missing). Returns (the lines added, or that would be with
    `dry_run`; notes): each line skipped (blank, or one the file already
    has) and each character no registry names.

    Raises:
        BiblesError: a `|` or line break in a cell, or a voices file whose
            header or rows `read_voices` can't read (lines added there would
            never be read); nothing is written.
        common.ReferenceDocError: the voices file or a registry can't be read.
    """
    bad = [f'{who}: {line[:40]!r}' for who, line in lines if '|' in who + line
           or '\n' in who + line]
    if bad:
        raise BiblesError('a `|` or a line break in a voice line: ' + '; '.join(bad)
                          + '. Nothing was added')
    voices, problems = read_voices(project_dir)
    if problems:
        raise BiblesError(f'reference/{VOICES_FILE} can\'t be read as it is ('
                          + '; '.join(problems) + '): fix it first; nothing was added')
    names = _names(project_dir)
    notes, new = [], []
    for n, (who, line) in enumerate(((w.strip(), l.strip()) for w, l in lines), start=1):
        if not who or not line:
            notes.append(f'voice line {n}: ' + ('no character' if not who else 'no line')
                         + '; skipped')
            continue
        if line in voices.get(who, []):
            notes.append(f'{who}: {line[:40]!r} is already in {VOICES_FILE}; skipped')
            continue
        if who not in names:
            notes.append(f'{VOICES_FILE}: {who!r} is in no registry (characters.csv); added as written')
        voices.setdefault(who, []).append(line)
        new.append(f'{who}|{line}')
    if new and not dry_run:
        path = _ref(project_dir, VOICES_FILE)
        text = ''
        if os.path.isfile(path):
            with open(path, encoding='utf-8-sig') as f:
                text = f.read()
        prefix = ('|'.join(VOICES_COLUMNS) + '\n' if not text.strip()
                  else ('' if text.endswith('\n') else '\n'))
        with open(path, 'w' if not text.strip() else 'a', encoding='utf-8', newline='') as f:
            f.write(prefix + '\n'.join(new) + '\n')
    return len(new), notes


@dataclass(frozen=True)
class VoiceLine:
    """A line a character speaks in a passage the author wrote or chose
    (#702): `character` an id, `line` the words as written, `source` the
    file it was found in (relative to the project)."""
    character: str
    line: str
    source: str


def anchor_voices(project_dir: str) -> tuple[list[VoiceLine], list[str]]:
    """The lines each character speaks in the voice anchors
    (`reference/voice/anchors/*.md`, `voice_book.read_folder`): passages the
    author wrote or chose (`voice sample` promotes a take only when they
    pick it; extract phase 5 takes them from the book's own prose). Never a
    model's words: a line is quoted speech copied from the anchor.

    A line is a character's when a speech tag beside it names them
    (`extract_describe._speech`: "said Mara", "Mara said,", a lead-in
    ending in a colon; names from characters.csv: the name, aliases and
    the name's own words); "I said" is the anchor's `pov:` character's (by id, name or alias).
    Lines under four words are left out. Returns the lines in anchor order
    and the notes: no anchors, an anchor left out, a line two characters'
    tags both claim (left out), an anchor with no line any tag attributes.

    Raises:
        common.ReferenceDocError: the anchors or characters.csv can't be read.
    """
    from storyforge.common import ReferenceDocError
    from storyforge.elaborate import _read_csv
    from storyforge.extract_describe import _speaker_names, _speech
    from storyforge.voice_book import ANCHORS_DIR, read_folder
    folder = read_folder(project_dir)
    notes = list(folder.skipped)
    if not folder.anchors:
        return [], notes + [f'no anchor in {ANCHORS_DIR}/ to take lines from (find one with '
                            f'`storyforge voice sample`, then save the take you pick as an '
                            f'anchor)']
    path = _ref(project_dir, 'characters.csv')
    try:
        characters = [r for r in _read_csv(path) if (r.get('id') or '').strip()]
    except (OSError, UnicodeDecodeError) as e:
        raise ReferenceDocError(path, e) from e
    if not characters:
        return [], notes + ['reference/characters.csv has no characters, so no line can be '
                            'attributed to one']
    characters = [{**c, 'id': c['id'].strip()} for c in characters]
    names = _speaker_names(characters)
    out: list[VoiceLine] = []
    for anchor in folder.anchors:
        found: dict[str, list[str]] = {}
        for c in characters:
            own = names.get(c['id'], [])
            pov = anchor.pov.strip().lower()
            if pov and pov in {n.lower() for n in [c['id'], *own]}:
                own = own + ['I']   # a first-person anchor's "I said"
            others = [n for o, ns in names.items() if o != c['id'] for n in ns]
            for line in _speech(anchor.text, own, others):
                found.setdefault(line, []).append(c['id'])
        shared = [line for line, who in found.items() if len(set(who)) > 1]
        for line in shared:
            notes.append(f'{anchor.path}: {line[:50]!r} has tags naming '
                         f'{", ".join(sorted(set(found[line])))}; left out')
        kept = [VoiceLine(who[0], line, anchor.path) for line, who in found.items()
                if len(set(who)) == 1]
        if not kept and not shared:
            notes.append(f'{anchor.path}: no line with a speech tag naming a character')
        out += kept
    return out, notes


def add_notes(project_dir: str, text: str, *, dry_run: bool = False) -> int:
    """Append `text`'s lines to bible-notes.md, leaving out blank lines
    and any line the file already has, so a re-run adds nothing; a missing
    or empty file takes the text as written. Returns the number of lines added (or that would be).

    Raises:
        common.ReferenceDocError: bible-notes.md can't be read.
    """
    from storyforge.common import ReferenceDocError
    path = _ref(project_dir, NOTES_FILE)
    existing = ''
    if os.path.isfile(path):
        try:
            with open(path, encoding='utf-8-sig') as f:
                existing = f.read()
        except (OSError, UnicodeDecodeError) as e:
            raise ReferenceDocError(path, e) from e
    if not existing.strip():
        # a new file takes the text as written, its blank lines included
        body = (text or '').strip('\n')
        count = sum(1 for l in body.splitlines() if l.strip())
        if count and not dry_run:
            with open(path, 'w', encoding='utf-8', newline='') as f:
                f.write(body.rstrip() + '\n')
        return count
    have = {l.strip() for l in existing.splitlines() if l.strip()}
    new = []
    for line in (text or '').splitlines():
        if line.strip() and line.strip() not in have:
            new.append(line.rstrip())
            have.add(line.strip())
    if new and not dry_run:
        body = existing.rstrip('\n')
        with open(path, 'w', encoding='utf-8', newline='') as f:
            f.write((body + '\n\n' if body else '') + '\n'.join(new) + '\n')
    return len(new)


# ============================================================================
# The two-writers test
# ============================================================================

def _whole_word(phrase: str, text: str) -> bool:
    return bool(phrase) and re.search(r'(?<!\w)' + re.escape(phrase) + r'(?!\w)', text) is not None


def plan_gaps(ref_dir: str) -> tuple[list[Gap], list[str]]:
    """The gaps the two-writers test can see in the plan, and what it
    couldn't check.

    Gaps, only in the plan's facts (`is_plan_fact`, binding or planned;
    facts the prose established, or migrated ones, aren't the plan's to
    settle):
    - `unsettled-reveal`: a knowledge fact with no learned_in, that is no
      live scene where it comes out: its `scene_id` names no live scene, and
      no live brief's `knowledge_out` names it (nor `knowledge_in`, for a
      fact that isn't a secret), while no one knows it from the start
      (blank `known_by`) or it is a secret (`REVEAL_CATEGORIES`).
    - `ambiguous-relationship`: a relationship hedged (`_HEDGE`: a question,
      maybe, perhaps, may have) or naming only one side (the subject and no
      other registry character or place, by id, name or alias).
    - `open-world-rule`: a world fact that is a question or hedged.
    - `open-question`: a trait or knowledge fact that is a question, or a
      bible-notes.md line ending in `?`.

    Notes: each essay still in reference/ (its gaps can't be seen; with
    rows of its kind beside it, both are read), each essay retired with no
    plan facts of its kind (nothing stands in for it), a ledger, registry,
    scenes, briefs or notes file that can't be read, a registry missing
    (only ids are matched). A graphic novel keeps its essays by design, so
    they aren't noted.
    """
    from storyforge import ledger
    from storyforge.common import get_medium
    from storyforge.elaborate import _read_csv
    from storyforge.schema import INACTIVE_STATUSES
    project_dir = os.path.dirname(os.path.abspath(ref_dir))
    notes: list[str] = []
    try:
        rows = ledger.load_from(ref_dir)
    except ledger.LedgerError as e:
        return [], [f'the plan\'s facts can\'t be checked for gaps: {e}']
    plan = [r for r in rows if is_plan_fact(r) and r.get('status') in ('binding', 'planned')]
    if get_medium(project_dir) != 'graphic-novel':
        for name in ESSAYS:
            state = essay_state(project_dir, name)
            kind = sum(r.get('type') in ESSAY_TYPES[name] for r in plan)
            if state == 'essay':
                notes.append(
                    f'reference/{name} is still an essay: Storyforge reads it, but its facts '
                    f'aren\'t rows, so its gaps can\'t be seen'
                    + (f'; drafting and the checker read it beside {kind} plan fact(s) of its '
                       f'kind, and a contradiction between the two isn\'t seen here' if kind else '')
                    + f' (convert it: `storyforge bibles import FILE --essay {name}`, then '
                    f'`storyforge bibles retire {name}`)')
            elif state == 'retired' and not kind:
                notes.append(f'reference/{name} is retired but the ledger has no plan fact of '
                             f'its kind: nothing stands in for it, so nothing was checked')
    gaps: list[Gap] = []

    def read(name: str, missing: str) -> list[dict]:
        try:
            return _read_csv(os.path.join(ref_dir, name))
        except (OSError, UnicodeDecodeError) as e:
            notes.append(f'reference/{name} can\'t be read ({e}): {missing}')
            return []

    scenes = read('scenes.csv', 'no scene counts as settling a reveal')
    live = {r['id'] for r in scenes if (r.get('id') or '').strip()
            and (r.get('status') or '').strip() not in INACTIVE_STATUSES}
    briefs = [b for b in read('scene-briefs.csv', 'no brief counts as settling a reveal')
              if b.get('id') in live]

    def named_in(col: str) -> set[str]:
        return {x for b in briefs for x in ledger._split(b.get(col, ''))}
    learned, entering = named_in('knowledge_out'), named_in('knowledge_in')

    names: dict[str, set[str]] = {}
    if any(r.get('type') == 'relationship' for r in plan):
        try:
            names, name_notes = ledger.subject_names(project_dir)
            notes.extend(name_notes)
        except (OSError, UnicodeDecodeError) as e:
            notes.append(f'a registry can\'t be read ({e}): a relationship\'s other side '
                         f'can\'t be found, so only hedged relationships are listed')

    for r in plan:
        rid, type_ = r['id'], r.get('type')
        subject = (r.get('subject') or '').strip()
        statement = (r.get('statement') or '').strip()
        question = statement.endswith('?')
        if type_ == 'knowledge':
            secret = is_secret(r)
            if question:
                gaps.append(Gap('open-question', rid, subject, f'{statement!r} has no answer yet'))
            if (r.get('scene_id') or '').strip() in live or rid in learned:
                continue
            if not secret and rid in entering:
                continue
            if secret or not ledger._split(r.get('known_by', '')):
                gaps.append(Gap('unsettled-reveal', rid, subject,
                                f'{statement!r}: no scene where it comes out (no live scene '
                                f'establishes it, and no live brief\'s knowledge_out names it)'
                                + ('' if secret else ', and no one knows it from the start')))
        elif type_ == 'relationship':
            if _HEDGE.search(statement):
                gaps.append(Gap('ambiguous-relationship', rid, subject,
                                f'{statement!r} doesn\'t decide it'))
            elif names:
                text = ledger._norm(statement)
                sides = {sid for sid, phrases in names.items()
                         if any(_whole_word(p, text) for p in phrases | {sid})}
                if subject:
                    sides.add(ledger._norm(subject))
                if len(sides) < 2:
                    gaps.append(Gap('ambiguous-relationship', rid, subject,
                                    f'{statement!r} names only one side (no other character '
                                    f'or place the registries name)'))
        elif type_ == 'world' and _HEDGE.search(statement):
            gaps.append(Gap('open-world-rule', rid, subject, f'{statement!r} has no answer yet'))
        elif type_ == 'trait' and question:
            gaps.append(Gap('open-question', rid, subject, f'{statement!r} has no answer yet'))

    path = _ref(project_dir, NOTES_FILE)
    if os.path.isfile(path):
        try:
            with open(path, encoding='utf-8-sig') as f:
                lines = f.read().splitlines()
        except (OSError, UnicodeDecodeError) as e:
            notes.append(f'reference/{NOTES_FILE} can\'t be read ({e}): its open questions '
                         f'aren\'t listed')
            lines = []
        for n, line in enumerate(lines, start=1):
            text = line.strip().lstrip('-*').strip()
            if text.endswith('?') and not text.startswith('#'):
                gaps.append(Gap('open-question', f'{NOTES_FILE} line {n}', '',
                                f'{text!r} has no answer yet'))
    return gaps, notes
