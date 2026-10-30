"""The commitments ledger: `reference/commitments.csv`.

One store of what the book has committed to (rethink plan §3.1,
`docs/plans/2026-10-28-storyforge-rethink.md`): facts joined to scenes by
scene id. It replaces `knowledge.csv` and `physical-states.csv`; the mapping
from those files is `docs/plans/2026-10-30-ledger-migration-proposal.md`.

- `read_ledger` / `write_ledger`: pipe-delimited, LF, prose through
  `common.csv_safe`.
- `validate_ledger`: problems as strings; an empty list means checked and clean.
- `scene_order`, `active_states`, `established_before`: derived state. Per-
  character state "as of scene N" is derived, never stored.
- `migrate_registries`: `knowledge.csv` + `physical-states.csv` to ledger rows,
  with every quirk reported rather than guessed. `regenerate_knowledge` /
  `regenerate_physical` write the old files back out of the ledger, and
  `round_trip_differences` names any line that doesn't come back unchanged
  that no quirk explains.
"""

from __future__ import annotations

import csv
import os
from dataclasses import dataclass, field

from storyforge.common import csv_safe

LEDGER_FILE = 'commitments.csv'

COLUMNS = [
    'id', 'scene_id', 'type', 'subject', 'statement', 'quote', 'origin',
    'status', 'mutable', 'known_by', 'supersedes', 'depends_on', 'reviewed',
    'introduced_by', 'category', 'aliases', 'resolves', 'action_gating',
]

TYPES = ('physical', 'timeline', 'knowledge', 'relationship', 'trait',
         'world', 'promise')
#: `migrated`: moved from knowledge.csv / physical-states.csv, where plan and
#: prose can't be told apart after the fact
ORIGINS = ('plan', 'prose', 'author', 'migrated')
STATUSES = ('binding', 'pending', 'rejected', 'superseded')
MUTABLE = ('state', 'fixed')

#: Free-text columns; `;`-joined id lists are the array columns
_PROSE_COLUMNS = ('statement', 'quote')
_ARRAY_COLUMNS = ('known_by', 'supersedes', 'depends_on', 'aliases')

KNOWLEDGE_COLUMNS = ['id', 'name', 'aliases', 'category', 'origin']
PHYSICAL_COLUMNS = ['id', 'character', 'description', 'category', 'acquired',
                    'resolves', 'action_gating']


def ledger_path(project_dir: str) -> str:
    return os.path.join(project_dir, 'reference', LEDGER_FILE)


# ============================================================================
# Read and write
# ============================================================================

def _read_rows(path: str) -> tuple[list[str], list[dict[str, str]]]:
    """Header (stripped) and rows of a pipe-delimited CSV; missing file → empty."""
    if not os.path.isfile(path):
        return [], []
    with open(path, newline='', encoding='utf-8') as f:
        lines = f.read().replace('\r\n', '\n').replace('\r', '').splitlines()
    if not lines:
        return [], []
    header = [h.strip() for h in lines[0].split('|')]
    rows = []
    for line in lines[1:]:
        if not line.strip():
            continue
        cells = line.split('|')
        rows.append({h: (cells[i] if i < len(cells) else '')
                     for i, h in enumerate(header)})
    return header, rows


def read_ledger(path: str) -> list[dict[str, str]]:
    """The ledger's rows, every column present ('' when absent)."""
    _, rows = _read_rows(path)
    return [{c: row.get(c, '') for c in COLUMNS} for row in rows]


def write_ledger(path: str, rows: list[dict[str, str]]) -> None:
    """Write the ledger: COLUMNS order, LF, one physical line per row."""
    os.makedirs(os.path.dirname(path) or '.', exist_ok=True)
    with open(path, 'w', newline='', encoding='utf-8') as f:
        f.write('|'.join(COLUMNS) + '\n')
        for row in rows:
            f.write('|'.join(_cell(row, c) for c in COLUMNS) + '\n')


def _cell(row: dict, column: str) -> str:
    value = row.get(column, '') or ''
    if column in _PROSE_COLUMNS:
        return csv_safe(value)
    # Ids, enums and `;` lists: a `|` or newline here is corrupt data, and
    # collapsing it would hide that
    if '|' in value or '\n' in value or '\r' in value:
        raise ValueError(f'{row.get("id", "?")}: {column} holds a "|" or a '
                         f'line break: {value!r}')
    return value


# ============================================================================
# Validation
# ============================================================================

def validate_ledger(rows: list[dict[str, str]], *,
                    scene_ids: set[str] | None = None,
                    character_ids: set[str] | None = None) -> list[str]:
    """Every problem in the ledger, one string each.

    `scene_ids` / `character_ids`: when given, `scene_id`, `resolves` and a
    physical row's `subject` are checked against them; when None, those
    checks are not run (the caller says so if it matters).
    """
    problems: list[str] = []
    ids: dict[str, int] = {}
    for n, row in enumerate(rows, start=2):
        rid = row.get('id', '').strip()
        where = f'line {n}' + (f' ({rid})' if rid else '')
        if not rid:
            problems.append(f'{where}: no id')
        elif rid in ids:
            problems.append(f'{where}: id also on line {ids[rid]}')
        else:
            ids[rid] = n
        for column, allowed in (('type', TYPES), ('origin', ORIGINS),
                                ('status', STATUSES), ('mutable', MUTABLE)):
            value = row.get(column, '').strip()
            if value not in allowed:
                problems.append(f'{where}: {column} {value!r} is not one of '
                                f'{", ".join(allowed)}')
        if not row.get('statement', '').strip():
            problems.append(f'{where}: no statement')
        gating = row.get('action_gating', '').strip()
        if gating not in ('', 'true', 'false'):
            problems.append(f'{where}: action_gating {gating!r} is not true or false')
        if scene_ids is not None:
            sid = row.get('scene_id', '').strip()
            if sid and sid not in scene_ids:
                problems.append(f'{where}: scene_id {sid!r} is not a scene')
            resolves = row.get('resolves', '').strip()
            if resolves and resolves != 'never' and resolves not in scene_ids:
                problems.append(f'{where}: resolves {resolves!r} is not a scene '
                                f'or "never"')
        if (character_ids is not None and row.get('type') == 'physical'
                and row.get('subject', '').strip() not in character_ids):
            problems.append(f'{where}: subject {row.get("subject", "")!r} is not '
                            f'a character id')
    for n, row in enumerate(rows, start=2):
        for column in ('supersedes', 'depends_on'):
            for ref in _split(row.get(column, '')):
                if ref not in ids:
                    problems.append(f'line {n} ({row.get("id", "")}): {column} '
                                    f'names {ref!r}, which is not in the ledger')
    return problems


def _split(value: str) -> list[str]:
    return [v.strip() for v in (value or '').split(';') if v.strip()]


# ============================================================================
# Derived state
# ============================================================================

def scene_order(project_dir: str) -> dict[str, int]:
    """Scene id → reading position, from `reference/scenes.csv`'s `seq`.

    Raises:
        ValueError: if a scene's `seq` is missing or not a number (the order
            would be a guess).
    """
    _, rows = _read_rows(os.path.join(project_dir, 'reference', 'scenes.csv'))
    keyed = []
    for row in rows:
        sid = row.get('id', '').strip()
        if not sid:
            continue
        try:
            keyed.append((float(row.get('seq', '')), sid))
        except ValueError:
            raise ValueError(f'scenes.csv: {sid} has no numeric seq '
                             f'({row.get("seq", "")!r})') from None
    return {sid: i for i, (_, sid) in enumerate(sorted(keyed))}


def active_states(rows: list[dict[str, str]], scene_id: str,
                  order: dict[str, int], *, subject: str | None = None,
                  entering: bool = False) -> list[dict[str, str]]:
    """The binding `state` facts in force after `scene_id` (or entering it).

    A fact is in force from its `scene_id` until it is superseded by a fact
    established no later than the point asked about, or until its `resolves`
    scene. A state resolves *in* that scene: entering it the state still
    holds, after it the state is gone. A fact whose scene isn't in `order`
    (blank, `backstory`, a renamed scene) holds from before the first scene.

    Raises:
        KeyError: if `scene_id` is not in `order`.
    """
    at = order[scene_id]
    point = at - 0.5 if entering else at

    def pos(sid: str) -> float:
        return order.get(sid.strip(), -1)

    live = [r for r in rows
            if r.get('status') == 'binding' and r.get('mutable') == 'state'
            and (subject is None or r.get('subject') == subject)
            and pos(r.get('scene_id', '')) <= point]
    superseded = {old for r in live for old in _split(r.get('supersedes', ''))}
    out = []
    for r in live:
        if r['id'] in superseded:
            continue
        resolves = r.get('resolves', '').strip()
        if resolves and resolves != 'never' and resolves in order \
                and order[resolves] <= point:
            continue
        out.append(r)
    return out


def established_before(rows: list[dict[str, str]], scene_id: str,
                       order: dict[str, int], *,
                       type_: str | None = None) -> list[dict[str, str]]:
    """Binding facts established in a scene before `scene_id`, in reading order.

    For offering a scene's prompt only what the book has already shown: a
    fact established in this scene or later is left out, so a re-extraction
    can't read ahead (F-123). A fact with no scene in `order` is left out too;
    the caller decides whether backstory belongs.
    """
    at = order[scene_id]
    found = [r for r in rows
             if r.get('status') == 'binding'
             and (type_ is None or r.get('type') == type_)
             and r.get('scene_id', '').strip() in order
             and order[r['scene_id'].strip()] < at]
    return sorted(found, key=lambda r: order[r['scene_id'].strip()])


# ============================================================================
# Migration from knowledge.csv and physical-states.csv
# ============================================================================

@dataclass
class Quirk:
    """Something the migration couldn't carry over as is, for the author."""
    file: str      # 'knowledge.csv' or 'physical-states.csv'
    kind: str
    row_id: str    # '' for a file-level quirk
    detail: str

    def __str__(self) -> str:
        return (f'{self.file}' + (f' {self.row_id}' if self.row_id else '')
                + f': {self.detail}')


@dataclass
class Migration:
    rows: list[dict[str, str]] = field(default_factory=list)
    quirks: list[Quirk] = field(default_factory=list)
    #: Problems that stop the migration (the old files must stay)
    errors: list[str] = field(default_factory=list)


#: Knowledge `origin` values that mean "before the story", not a scene
_NO_SCENE_ORIGINS = ('backstory', 'before')


def migrate_registries(ref_dir: str) -> Migration:
    """Ledger rows from `ref_dir`'s knowledge.csv and physical-states.csv.

    Nothing is written. Every change from the old data is a `Quirk`; a
    duplicate id whose rows differ is an error, since keeping either would
    be a guess.
    """
    result = Migration()
    scene_ids = set(_ids(os.path.join(ref_dir, 'scenes.csv')))
    _migrate_knowledge(os.path.join(ref_dir, 'knowledge.csv'), scene_ids, result)
    _migrate_physical(ref_dir, scene_ids, result)
    seen: dict[str, str] = {}
    for row in result.rows:
        other = seen.get(row['id'])
        if other is not None:
            result.errors.append(f'id {row["id"]!r} is in both {other} and '
                                 f'{_FILE_OF[row["type"]]}')
        seen[row['id']] = _FILE_OF[row['type']]
    return result


_FILE_OF = {'knowledge': 'knowledge.csv', 'physical': 'physical-states.csv'}


def _ids(path: str) -> list[str]:
    _, rows = _read_rows(path)
    return [r.get('id', '').strip() for r in rows if r.get('id', '').strip()]


def _base_row(rid: str, type_: str) -> dict[str, str]:
    row = {c: '' for c in COLUMNS}
    row.update(id=rid, type=type_, origin='migrated', status='binding',
               mutable='state', introduced_by='migration')
    return row


def _dedupe(rows, file, result):
    """Drop exact duplicate rows (reported); a differing duplicate is an error."""
    kept: dict[str, dict] = {}
    for row in rows:
        rid = row.get('id', '').strip()
        if not rid:
            result.errors.append(f'{file}: a row has no id: {"|".join(row.values())[:80]!r}')
            continue
        if rid in kept:
            if kept[rid] == row:
                result.quirks.append(Quirk(file, 'duplicate', rid,
                                           'exact duplicate row dropped'))
            else:
                result.errors.append(f'{file}: id {rid!r} is on two rows that differ')
            continue
        kept[rid] = row
    return list(kept.values())


def _migrate_knowledge(path, scene_ids, result):
    file = 'knowledge.csv'
    header, rows = _read_rows(path)
    if not header:
        return
    raw_header = _raw_header(path)
    if raw_header != '|'.join(header):
        result.quirks.append(Quirk(file, 'header', '',
                                   f'header {raw_header!r} has stray whitespace'))
    extra = [h for h in header if h not in KNOWLEDGE_COLUMNS]
    if 'fact' in header:
        # lantern-folk: the statement is in `fact`
        result.quirks.append(Quirk(file, 'header', '',
                                   'statements taken from the `fact` column'))
        extra.remove('fact')
    if extra:
        result.errors.append(f'{file}: columns the ledger has no place for: '
                             f'{", ".join(extra)}')
        return
    # understory: `name` holds slugs and the statement is the first alias
    slug_names = bool(rows) and all(
        _is_slug(r.get('name', '')) and _split(r.get('aliases', ''))
        for r in rows)
    if slug_names:
        result.quirks.append(Quirk(
            file, 'slug-names', '',
            '`name` holds slugs: statements taken from the first alias, and '
            'each slug kept as an alias'))
    for r in _dedupe(rows, file, result):
        row = _base_row(r['id'].strip(), 'knowledge')
        row['category'] = r.get('category', '').strip()
        # Kept verbatim (spacing included), so the round trip is exact
        aliases = r.get('aliases', '').strip()
        if 'fact' in header:
            row['statement'] = r.get('fact', '').strip()
            if r.get('name', '').strip():
                aliases = ';'.join(filter(None, [r['name'].strip(), aliases]))
        elif slug_names:
            row['statement'] = _split(aliases)[0]
            aliases = f'{r["name"].strip()};{aliases}'
        else:
            row['statement'] = r.get('name', '').strip()
        row['aliases'] = aliases
        origin = r.get('origin', '').strip()
        if origin in _NO_SCENE_ORIGINS or not origin:
            result.quirks.append(Quirk(
                file, 'no-scene', row['id'],
                f'origin {origin!r} names no scene: scene_id left blank'
                if origin else 'no origin: scene_id left blank'))
        else:
            row['scene_id'] = origin
            if origin not in scene_ids:
                result.quirks.append(Quirk(
                    file, 'unknown-scene', row['id'],
                    f'origin {origin!r} is not a scene id (renamed or removed '
                    f'scene?): kept as scene_id'))
        result.rows.append(row)


def _migrate_physical(ref_dir, scene_ids, result):
    from storyforge.enrich import load_alias_map
    file = 'physical-states.csv'
    path = os.path.join(ref_dir, file)
    header, rows = _read_rows(path)
    if not header:
        return
    if _raw_header(path) != '|'.join(header):
        result.quirks.append(Quirk(file, 'header', '',
                                   'header has stray whitespace'))
    extra = [h for h in header if h not in PHYSICAL_COLUMNS]
    if extra:
        result.errors.append(f'{file}: columns the ledger has no place for: '
                             f'{", ".join(extra)}')
        return
    characters = load_alias_map(os.path.join(ref_dir, 'characters.csv'))
    normalized: dict[str, str] = {}
    for r in _dedupe(rows, file, result):
        row = _base_row(r['id'].strip(), 'physical')
        name = r.get('character', '').strip()
        subject = characters.get(name.lower(), '')
        if not subject:
            result.quirks.append(Quirk(
                file, 'unresolved-character', row['id'],
                f'character {name!r} is not in characters.csv (name, id or '
                f'alias): subject left blank'))
        elif subject != name:
            normalized[name] = subject
        row['subject'] = subject
        row['statement'] = r.get('description', '').strip()
        row['category'] = r.get('category', '').strip()
        row['scene_id'] = r.get('acquired', '').strip()
        row['resolves'] = r.get('resolves', '').strip()
        row['action_gating'] = r.get('action_gating', '').strip()
        for column, sid in (('acquired', row['scene_id']), ('resolves', row['resolves'])):
            if sid and sid != 'never' and sid not in scene_ids:
                result.quirks.append(Quirk(file, 'unknown-scene', row['id'],
                                           f'{column} {sid!r} is not a scene id: kept'))
        result.rows.append(row)
    for name, subject in sorted(normalized.items()):
        count = sum(1 for r in rows if r.get('character', '').strip() == name)
        result.quirks.append(Quirk(
            file, 'character-id', '',
            f'character {name!r} is written as its id {subject!r} ({count} row(s))'))


def _raw_header(path: str) -> str:
    with open(path, newline='', encoding='utf-8') as f:
        return f.readline().rstrip('\r\n')


def _is_slug(value: str) -> bool:
    value = value.strip()
    return bool(value) and ' ' not in value and value == value.lower()


# ============================================================================
# Round trip
# ============================================================================

def regenerate_knowledge(rows: list[dict[str, str]]) -> str:
    """knowledge.csv's text, written back out of the ledger."""
    lines = ['|'.join(KNOWLEDGE_COLUMNS)]
    for r in rows:
        if r.get('type') == 'knowledge':
            lines.append('|'.join([r['id'], r['statement'], r['aliases'],
                                   r['category'], r['scene_id']]))
    return '\n'.join(lines) + '\n'


def regenerate_physical(rows: list[dict[str, str]]) -> str:
    """physical-states.csv's text, written back out of the ledger (with the
    character as its id)."""
    lines = ['|'.join(PHYSICAL_COLUMNS)]
    for r in rows:
        if r.get('type') == 'physical':
            lines.append('|'.join([r['id'], r['subject'], r['statement'],
                                   r['category'], r['scene_id'], r['resolves'],
                                   r['action_gating']]))
    return '\n'.join(lines) + '\n'


def round_trip_differences(ref_dir: str, migration: Migration) -> list[str]:
    """Lines of the old files that don't come back from the ledger unchanged
    and that no quirk explains. Empty means the round trip holds.

    A file-level quirk (header, `fact` column, slug names) explains every
    line of its file; a row quirk explains that row; a `character-id` quirk
    explains the rows whose character it names.
    """
    out = []
    for file, regenerate in (('knowledge.csv', regenerate_knowledge),
                             ('physical-states.csv', regenerate_physical)):
        path = os.path.join(ref_dir, file)
        if not os.path.isfile(path):
            continue
        with open(path, newline='', encoding='utf-8') as f:
            original = f.read()
        quirks = [q for q in migration.quirks if q.file == file]
        file_level = {q.kind for q in quirks if not q.row_id}
        explained = {q.row_id for q in quirks if q.row_id}
        if file_level & {'header', 'slug-names'}:
            # The lines can't come back as they were; check each row's
            # fields reached the ledger instead
            out += _field_differences(path, file, migration.rows, explained)
            continue
        # character-id quirks: name → the id it is written as
        renamed = {q.detail.split("'")[1]: q.detail.split("'")[3]
                   for q in quirks if q.kind == 'character-id'}
        if '\r\n' in original:
            out.append(f'{file}: CRLF line endings (the ledger writes LF)')
            original = original.replace('\r\n', '\n')
        old_lines = original.splitlines()
        new_lines = regenerate(migration.rows).splitlines()
        if old_lines[:1] != new_lines[:1]:
            out.append(f'{file}: header {old_lines[0]!r} came back as {new_lines[0]!r}')
        new_by_id = {line.split('|', 1)[0]: line for line in new_lines[1:]}
        for line in old_lines[1:]:
            if not line.strip():
                continue
            rid = line.split('|', 1)[0].strip()
            if new_by_id.get(rid) == line or rid in explained:
                continue
            if file == 'physical-states.csv':
                cells = line.split('|')
                if len(cells) > 1 and cells[1].strip() in renamed:
                    cells[1] = renamed[cells[1].strip()]
                    if new_by_id.get(rid) == '|'.join(cells):
                        continue
            out.append(f'{file} {rid}: {line!r} came back as '
                       f'{new_by_id.get(rid, "(missing)")!r}')
        if [l.split('|', 1)[0] for l in old_lines[1:] if l.strip()] != \
                [l.split('|', 1)[0] for l in new_lines[1:]] and 'duplicate' not in \
                {q.kind for q in quirks}:
            out.append(f'{file}: rows came back in a different order')
    return out


def _field_differences(path, file, rows, explained):
    """For a file whose lines can't round-trip (a non-standard header): every
    old row's values must be in its ledger row, in the column the migration
    maps them to."""
    by_id = {r['id']: r for r in rows}
    _, old_rows = _read_rows(path)
    out = []
    for old in old_rows:
        rid = old.get('id', '').strip()
        new = by_id.get(rid)
        if new is None:
            out.append(f'{file} {rid}: missing from the ledger')
            continue
        if file == 'knowledge.csv':
            text = ';'.join([new['statement'], new['aliases']])
            checks = [('category', new['category'])]
            if rid not in explained:
                checks.append(('origin', new['scene_id']))
            carried = [c for c in ('fact', 'name', 'aliases') if c in old]
        else:
            text = new['statement']
            checks = [('category', new['category']), ('acquired', new['scene_id']),
                      ('resolves', new['resolves']),
                      ('action_gating', new['action_gating'])]
            carried = ['description']
        for column, value in checks:
            if old.get(column, '').strip() != value:
                out.append(f'{file} {rid}: {column} {old.get(column, "")!r} '
                           f'came back as {value!r}')
        for column in carried:
            for part in _split(old.get(column, '')):
                if part not in text:
                    out.append(f'{file} {rid}: {column} text {part!r} is not '
                               f'in the ledger row')
    return out
