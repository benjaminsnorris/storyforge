"""Bibles as facts, not essays (#657, plan D2).

The character, world and systems bibles were model-written essays that every
drafting prompt and the gate's checker read whole, and their phrasing leaked
into the drafts the way briefs' did (#644). What's true about the people and
the world is now rows:

- **Facts** in the ledger (`reference/commitments.csv`): type `trait`,
  `relationship` or `world` (a secret or a reveal is a `knowledge` fact),
  origin `plan`, status `binding`, `introduced_by` `bibles` (`WRITER`, a
  registry fact, never a commitment). A blank `scene_id` means true from
  before the first scene; a fact that becomes true in a scene names it.
  `add_facts` is the one writer, through `ledger.save_to` (so audit-logged).
- **Voices** in `reference/character-voices.csv` (`character|line`): a few
  lines of each character speaking, never a paragraph about their speech.
- **Notes** in `reference/bible-notes.md`: terse notes for what resists rows
  (a culture's feel, a history's shape). A line ending in `?` is a question
  the plan hasn't answered.

The essays stay where they are, read as before, until they are converted:
`retire` moves one to `reference/archive/` (`ARCHIVE_DIR`), where nothing
reads it and the author keeps it as reference.

Readers:
- `drafting_sections(project_dir)`: the facts true from the start (every
  subject, never `knowledge`, which would give away a reveal), the voices
  and the notes, for the drafting prompts' standing context.
- `checker_doc(project_dir)`: the same facts with their ids, for the gate's
  checker (`checker.reference_docs`, as `FACTS_DOC`).
- `plan_gaps(ref_dir)` → `(gaps, notes)`: the two-writers test, the gaps
  code can see in the plan (unsettled reveals, ambiguous relationships,
  world rules with no answer, open questions in the notes), and what it
  couldn't check (`notes`: an essay not yet converted, a ledger that can't
  be read). `elaborate.validate_structure` reports both as advisory, so
  `validate` and every elaborate stage review list them.
"""

from __future__ import annotations

import os
import re
import shutil
from dataclasses import dataclass

#: `introduced_by` of the facts converted from a bible or written by an
#: elaborate stage (not in `ledger.COMMITMENT_WRITERS`: a registry fact)
WRITER = 'bibles'
#: The types a bible's facts take; `knowledge` for a secret or a reveal
FACT_TYPES = ('trait', 'relationship', 'world')
IMPORT_TYPES = FACT_TYPES + ('knowledge',)
#: The origins of a plan's facts (the plan's, and the author's own)
PLAN_ORIGINS = ('plan', 'author')
#: The essays the rows replace, and the types that convert each
ESSAYS = ('character-bible.md', 'world-bible.md', 'systems-bible.md')
ESSAY_TYPES = {'character-bible.md': ('trait', 'relationship'),
               'world-bible.md': ('world',), 'systems-bible.md': ('world',)}
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
#: knows it from the start: the plan owes the scene where it comes out
REVEAL_CATEGORIES = ('secret', 'reveal')

#: A statement that hasn't decided: a question, or a hedge
_HEDGE = re.compile(r'\?|\b(maybe|perhaps|possibly|unclear|undecided|uncertain|tbd|tbc|'
                    r'not yet decided|may or may not|(?:may|might) (?:have|be)|either\b.+\bor)\b', re.I)

GAP_KINDS = ('unsettled-reveal', 'ambiguous-relationship', 'open-world-rule', 'open-question')


class BiblesError(RuntimeError):
    """Rows that can't be added as they are, or an essay that can't be
    retired; the message names each problem."""


@dataclass(frozen=True)
class Gap:
    """One gap the two-writers test sees: two writers drafting from the plan
    could disagree here. `ref` is the fact id, or `bible-notes.md line N`."""
    kind: str
    ref: str
    subject: str
    detail: str

    def message(self) -> str:
        who = f' ({self.subject})' if self.subject else ''
        return f'{self.kind}: {self.ref}{who}: {self.detail}'


# ============================================================================
# Reading
# ============================================================================

def _ref(project_dir: str, *parts: str) -> str:
    return os.path.join(project_dir, 'reference', *parts)


def is_bible_fact(row: dict) -> bool:
    """A plan's fact about the people or the world: a binding `trait`,
    `relationship` or `world` row of origin `plan` or `author` that isn't a
    commitment (what the prose said)."""
    from storyforge.ledger import is_commitment
    return (row.get('type') in FACT_TYPES and row.get('origin') in PLAN_ORIGINS
            and row.get('status') == 'binding' and not is_commitment(row))


def standing_facts(rows: list[dict]) -> list[dict]:
    """The bible facts true from the start (blank `scene_id`): what a reader
    holds every scene to. A fact that becomes true in a scene reaches that
    scene and the later ones through the ledger (`drafting_slice`, the
    checker's ledger tool), never the standing context, which would show it
    before it happens."""
    return [r for r in rows if is_bible_fact(r) and not (r.get('scene_id') or '').strip()]


def _names(project_dir: str) -> dict[str, str]:
    """Registry id → display name, from characters.csv and locations.csv."""
    from storyforge.common import ReferenceDocError
    from storyforge.elaborate import _read_csv
    out = {}
    for registry in ('characters.csv', 'locations.csv'):
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


def _plain_rows(path: str) -> tuple[list[str], list[dict[str, str]]]:
    """Header and rows of a pipe-delimited file split on `|` alone: a voice
    line or a statement in quotes keeps them (the csv module would read a
    leading `"` as quoting). Missing file → ([], [])."""
    from storyforge.ledger import _read_rows
    header, rows = _read_rows(path)
    return header, [{k: (v or '').strip() for k, v in r.items()} for r in rows]


def read_voices(project_dir: str) -> tuple[dict[str, list[str]], list[str]]:
    """character id → their lines, in file order; and the problems, one
    string each (a header without `character` and `line`, a row with no
    character or no line). No file → ({}, []).

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
    for n, r in enumerate(rows, start=2):
        who, line = r.get('character', ''), r.get('line', '')
        if not who or not line:
            problems.append(f'reference/{VOICES_FILE} row {n}: '
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


def drafting_sections(project_dir: str) -> list[tuple[str, str]]:
    """The rows for the drafting prompts' standing context, as (label, text):
    'Settled Facts' (the bible facts true from the start, by subject),
    'How They Speak' (each character's lines) and 'Notes' (bible-notes.md),
    each only when there is one. A book with none gets [], so its prompts
    are as before.

    Raises:
        ledger.LedgerError: the ledger can't be read.
        common.ReferenceDocError: the voices or notes can't be read.
    """
    from storyforge import ledger
    sections = []
    facts = standing_facts(ledger.load(project_dir))
    voices, _ = read_voices(project_dir)
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


def checker_doc(project_dir: str, rows: list[dict] | None = None) -> str:
    """The bible facts true from the start, with their ids, for the gate's
    checker ('' with none).

    Raises:
        ledger.LedgerError: the ledger can't be read (when `rows` isn't given).
    """
    from storyforge import ledger
    facts = standing_facts(rows if rows is not None else ledger.load(project_dir))
    if not facts:
        return ''
    return ('The book\'s settled facts: rows of reference/commitments.csv, true from '
            'before the first scene. Cite one by its id (`fact_id`) or by this file.\n\n'
            + _grouped(facts, _names(project_dir), with_ids=True))


def bible_text(project_dir: str, name: str) -> str:
    """One bible's text, for a reader that takes a bible whole (hone, the
    novel-level character score): the essay while it's still in reference/
    (`common.reference_text`), else its rows: for character-bible.md the
    standing trait and relationship facts and the voices, for world-bible.md
    and systems-bible.md the standing world facts and the notes. '' when
    there is neither.

    Raises:
        common.ReferenceDocError: a file exists but can't be read.
        ledger.LedgerError: the ledger can't be read.
    """
    from storyforge import ledger
    from storyforge.common import reference_text
    essay = reference_text(_ref(project_dir, name))
    if essay or name not in ESSAY_TYPES:
        return essay
    types = ESSAY_TYPES[name]
    facts = [r for r in standing_facts(ledger.load(project_dir)) if r['type'] in types]
    character = name == 'character-bible.md'
    voices = read_voices(project_dir)[0] if character else {}
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


# ============================================================================
# Essays: converted or not
# ============================================================================

def essay_state(project_dir: str, name: str) -> str:
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


def retire(project_dir: str, name: str, *, force: bool = False,
           dry_run: bool = False) -> str:
    """Move a converted essay to the archive; returns its new path, relative
    to the project. Refused (BiblesError) for a name that isn't an essay, an
    essay not in reference/, one already in the archive, or (without
    `force`) one whose facts aren't rows yet: no bible fact of its types.

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
    types = ESSAY_TYPES[name]
    have = [r for r in ledger.load(project_dir) if is_bible_fact(r) and r['type'] in types]
    if not have and not force:
        raise BiblesError(
            f'reference/{name} has no rows yet: the ledger has no {" or ".join(types)} fact '
            f'from the plan. Convert it first (`storyforge bibles import FILE`), or pass '
            f'--force to retire it anyway; nothing was moved')
    if not dry_run:
        os.makedirs(os.path.dirname(dest), exist_ok=True)
        shutil.move(src, dest)
    return os.path.relpath(dest, project_dir)


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


def add_facts(project_dir: str, items: list[dict], *, command: str,
              dry_run: bool = False) -> tuple[list[str], list[str]]:
    """Add plan facts to the ledger: each item has `type` (`IMPORT_TYPES`),
    `subject` (a registry id, or blank for the world), `statement`, and
    optionally `known_by` (`;` ids), `scene_id`, `category` and `id`.

    Each row is origin `plan`, status `binding`, `introduced_by` `WRITER`,
    mutable `fixed` (`state` for knowledge, as the migration writes it). An
    id is made from the subject and statement when not given. Returns (the
    ids added, notes): a subject or `known_by` no registry names is added as
    written and noted; a fact whose type, subject and statement match one
    already in the ledger is skipped and noted, so a re-run adds nothing.

    Raises:
        BiblesError: an item that can't be a row (no statement, a type that
            isn't one, a `|` or a line break in a cell, an id the ledger
            already has or two items share), each named; nothing is written.
        ledger.LedgerError: the ledger can't be read or written.
    """
    from storyforge import ledger
    rows = ledger.load(project_dir)
    taken = {r['id'] for r in rows}
    existing = {(r.get('type'), (r.get('subject') or '').strip(), ledger._norm(r.get('statement', '')))
                for r in rows}
    names = _names(project_dir)
    from storyforge.elaborate import _read_csv
    scenes = {(r.get('id') or '').strip() for r in _read_csv(_ref(project_dir, 'scenes.csv'))}
    problems, notes, new = [], [], []
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
        key = (cells['type'], cells['subject'], ledger._norm(cells['statement']))
        if key in existing:
            notes.append(f'{where}: the ledger already has this fact; skipped')
            continue
        rid = cells['id']
        if rid and rid in taken:
            problems.append(f'{where}: id {rid!r} is already in the ledger')
            continue
        rid = rid or _new_id(cells['subject'], cells['type'], cells['statement'], taken)
        taken.add(rid)
        existing.add(key)
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
                   known_by=cells['known_by'], introduced_by=WRITER,
                   category=cells['category'])
        new.append(row)
    if problems:
        raise BiblesError('; '.join(problems) + '. Nothing was added')
    if new and not dry_run:
        ledger.save(project_dir, rows + new, command=command)
    return [r['id'] for r in new], notes


def read_import(path: str) -> list[dict]:
    """A pipe-delimited file of facts for `add_facts` (`IMPORT_COLUMNS`; the
    first three required in the header).

    Raises:
        BiblesError: no such file, or a header without type, subject and
            statement.
    """
    if not os.path.isfile(path):
        raise BiblesError(f'{path} doesn\'t exist')
    header, rows = _plain_rows(path)
    missing = [c for c in IMPORT_COLUMNS[:3] if c not in header]
    if missing:
        raise BiblesError(f'{path}: the header has no {", ".join(missing)} column '
                          f'(it takes {"|".join(IMPORT_COLUMNS)})')
    return rows


def read_voice_import(path: str) -> list[tuple[str, str]]:
    """(character, line) pairs from a `character|line` file for `add_voices`.

    Raises:
        BiblesError: no such file, or a header without both columns.
    """
    if not os.path.isfile(path):
        raise BiblesError(f'{path} doesn\'t exist')
    header, rows = _plain_rows(path)
    if not set(VOICES_COLUMNS) <= set(header):
        raise BiblesError(f'{path}: the header must have {"|".join(VOICES_COLUMNS)}')
    return [(r.get('character', ''), r.get('line', '')) for r in rows]


def add_voices(project_dir: str, lines: list[tuple[str, str]], *, dry_run: bool = False) -> list[str]:
    """Append (character, line) rows to character-voices.csv (made with its
    header when missing), skipping a line the file already has. Returns
    notes: each line skipped, each character no registry names.

    Raises:
        BiblesError: a `|` or line break in a cell; nothing is written.
    """
    bad = [f'{who}: {line[:40]!r}' for who, line in lines if '|' in who + line
           or '\n' in who + line]
    if bad:
        raise BiblesError('a `|` or a line break in a voice line: ' + '; '.join(bad)
                          + '. Nothing was added')
    voices, _ = read_voices(project_dir)
    names = _names(project_dir)
    notes, new = [], []
    for who, line in ((w.strip(), l.strip()) for w, l in lines):
        if not who or not line:
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
        fresh = not os.path.isfile(path) or not open(path, encoding='utf-8').read().strip()
        with open(path, 'a' if not fresh else 'w', encoding='utf-8', newline='') as f:
            if fresh:
                f.write('|'.join(VOICES_COLUMNS) + '\n')
            else:
                with open(path, 'rb') as r:
                    r.seek(-1, os.SEEK_END)
                    if r.read(1) != b'\n':
                        f.write('\n')
            f.write('\n'.join(new) + '\n')
    return notes


def add_notes(project_dir: str, text: str, *, dry_run: bool = False) -> bool:
    """Append `text` to bible-notes.md (made when missing); False when there
    is nothing to add."""
    text = (text or '').strip()
    if not text:
        return False
    if not dry_run:
        path = _ref(project_dir, NOTES_FILE)
        existing = ''
        if os.path.isfile(path):
            with open(path, encoding='utf-8') as f:
                existing = f.read().rstrip('\n')
        with open(path, 'w', encoding='utf-8', newline='') as f:
            f.write((existing + '\n\n' if existing else '') + text + '\n')
    return True


# ============================================================================
# The two-writers test
# ============================================================================

def _whole_word(phrase: str, text: str) -> bool:
    return bool(phrase) and re.search(r'(?<!\w)' + re.escape(phrase) + r'(?!\w)', text) is not None


def _named_characters(statement: str, chars: dict[str, set[str]]) -> set[str]:
    """The characters.csv ids a statement names (id, name or alias, whole
    words, case folded)."""
    from storyforge.ledger import _norm
    text = _norm(statement)
    return {cid for cid, phrases in chars.items() if any(_whole_word(p, text) for p in phrases)}


def plan_gaps(ref_dir: str) -> tuple[list[Gap], list[str]]:
    """The gaps the two-writers test can see in the plan, and what it
    couldn't check.

    Gaps (only in the plan's facts: origin `plan` or `author`, binding or
    planned; facts the prose established, or migrated ones, aren't the
    plan's to settle):
    - `unsettled-reveal`: a knowledge fact with no learned_in, that is no
      live scene where it comes out: its `scene_id` names no live scene, and
      no live brief's `knowledge_out` names it (nor `knowledge_in`, for a
      fact that isn't a secret), while no one knows it from the start
      (blank `known_by`) or it is a secret (`REVEAL_CATEGORIES`).
    - `ambiguous-relationship`: a relationship hedged (a question, "maybe",
      "either ... or") or naming only one side (the subject and no other
      character characters.csv names).
    - `open-world-rule`: a world fact that is a question or hedged.
    - `open-question`: a bible-notes.md line ending in `?`.

    Notes: each essay still in reference/ (its facts aren't rows, so its
    gaps can't be seen), a ledger or registry that can't be read.
    """
    from storyforge import ledger
    from storyforge.elaborate import _read_csv
    from storyforge.schema import INACTIVE_STATUSES
    project_dir = os.path.dirname(os.path.abspath(ref_dir))
    notes = [f'reference/{n} is still an essay: Storyforge reads it, but its facts aren\'t '
             f'rows, so its gaps can\'t be seen (convert it: `storyforge bibles import`, '
             f'then `storyforge bibles retire {n}`)' for n in unconverted(project_dir)]
    try:
        rows = ledger.load_from(ref_dir)
    except ledger.LedgerError as e:
        return [], notes + [f'the plan\'s facts can\'t be checked for gaps: {e}']
    plan = [r for r in rows if r.get('origin') in PLAN_ORIGINS
            and r.get('status') in ('binding', 'planned') and not ledger.is_commitment(r)]
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

    chars: dict[str, set[str]] = {}
    for c in read('characters.csv', 'a relationship\'s other side can\'t be found'):
        cid = (c.get('id') or '').strip()
        if cid:
            chars[cid] = {ledger._norm(p) for p in
                          [cid, c.get('name', '')] + ledger._split(c.get('aliases', ''))
                          if ledger._norm(p)}
    if (not chars and any(r.get('type') == 'relationship' for r in plan)
            and not any(n.startswith('reference/characters.csv') for n in notes)):
        notes.append('characters.csv has no characters: a relationship\'s other side can\'t '
                     'be found, so only hedged relationships are listed')

    for r in plan:
        rid, type_ = r['id'], r.get('type')
        subject = (r.get('subject') or '').strip()
        statement = (r.get('statement') or '').strip()
        if type_ == 'knowledge':
            secret = (r.get('category') or '').strip().lower() in REVEAL_CATEGORIES
            if (r.get('scene_id') or '').strip() in live or rid in learned:
                continue
            if not secret and rid in entering:
                continue
            if secret or not ledger._split(r.get('known_by', '')):
                gaps.append(Gap('unsettled-reveal', rid, subject,
                                f'{statement!r}: no scene where it comes out (no live scene '
                                f'establishes it, and no brief\'s knowledge_out names it)'
                                + ('' if secret else ', and no one knows it from the start')))
        elif type_ == 'relationship':
            if _HEDGE.search(statement):
                gaps.append(Gap('ambiguous-relationship', rid, subject,
                                f'{statement!r} doesn\'t decide it'))
            elif chars:
                sides = _named_characters(statement, chars) | ({subject} if subject else set())
                if len(sides) < 2:
                    gaps.append(Gap('ambiguous-relationship', rid, subject,
                                    f'{statement!r} names only one side (no other character '
                                    f'characters.csv names)'))
        elif type_ == 'world' and _HEDGE.search(statement):
            gaps.append(Gap('open-world-rule', rid, subject,
                            f'{statement!r} has no answer yet'))

    from storyforge.common import ReferenceDocError
    try:
        notes_doc = notes_text(project_dir)
    except ReferenceDocError as e:   # said, never a stop: validate goes on
        notes.append(f'reference/{NOTES_FILE} can\'t be read ({e}): its open questions '
                     f'aren\'t listed')
        notes_doc = ''
    if notes_doc:
        path = _ref(project_dir, NOTES_FILE)
        with open(path, encoding='utf-8-sig') as f:
            for n, line in enumerate(f, start=1):
                text = line.strip().lstrip('-*').strip()
                if text.endswith('?') and not text.startswith('#'):
                    gaps.append(Gap('open-question', f'{NOTES_FILE} line {n}', '',
                                    f'{text!r} has no answer yet'))
    return gaps, notes
