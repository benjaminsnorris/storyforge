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
  `drafting_slice` is a scene's share of it, for the drafting prompt.
- `load` / `save` (and `load_from` / `save_to` for a `reference/` dir): the
  project's ledger. Every write through `save`, `save_to`, `write_view` and
  `migrate_files` is appended to the audit log (`storyforge.audit`,
  `working/audit-log.csv`); `write_ledger` is the bare file writer and logs
  nothing. `load` raises `NotMigratedError` while knowledge.csv or
  physical-states.csv is still on disk, so nothing reads half the facts.
- `knowledge_view` / `physical_view` (`read_view`, `view_map`): one type's
  rows in the old files' shapes, for consumers that matched on them.
  `replace_view` / `write_view` write those shapes back, changing only that
  type's rows: every other row, and every column the view doesn't carry, is
  kept.
- `migrate_registries`: `knowledge.csv` + `physical-states.csv` to ledger rows,
  with every quirk reported rather than guessed. `regenerate_knowledge` /
  `regenerate_physical` write the old files back out of the ledger, and
  `round_trip_differences` names any line that doesn't come back unchanged
  that no quirk explains. `migrate_files` is the whole step (`storyforge
  migrate`): migrate, write, verify from the written file, remove the old
  files.
"""

from __future__ import annotations

import csv
import os
import threading
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


#: The files the ledger replaced. Never written again.
LEGACY_FILES = ('knowledge.csv', 'physical-states.csv')


def ledger_path(project_dir: str) -> str:
    return os.path.join(project_dir, 'reference', LEDGER_FILE)


class LedgerError(RuntimeError):
    """The ledger can't be read as it is; the message says why and where."""


class NotMigratedError(LedgerError):
    """knowledge.csv or physical-states.csv is still in `reference/`."""


def file_problems(path: str) -> list[str]:
    """What stops `path` being read as the ledger, one string each: a header
    that isn't exactly COLUMNS, a row whose cell count differs from it, a
    blank id, an id on two rows. Missing file → []. Each would be silently
    "fixed" by reading and writing the file back (a column dropped, rows
    merged), so the ledger is not read until the author fixes them.
    """
    if not os.path.isfile(path):
        return []
    lines, _ = _raw_lines(path)
    if not lines:
        return []
    problems = []
    header = lines[0].split('|')
    if header != COLUMNS:
        unknown = [h for h in header if h not in COLUMNS]
        missing = [c for c in COLUMNS if c not in header]
        detail = '; '.join(filter(None, [
            unknown and f'columns the ledger has no place for: {", ".join(unknown)}',
            missing and f'missing columns: {", ".join(missing)}',
            not unknown and not missing and 'columns out of order or repeated']))
        problems.append(f'{LEDGER_FILE} line 1: the header must be exactly '
                        f'{"|".join(COLUMNS)} ({detail})')
        return problems
    seen: dict[str, int] = {}
    for n, line in enumerate(lines[1:], start=2):
        if not line.strip():
            continue
        cells = line.split('|')
        if len(cells) != len(COLUMNS):
            problems.append(f'{LEDGER_FILE} line {n}: {len(cells)} cells, the '
                            f'header has {len(COLUMNS)}: {line[:80]!r}')
            continue
        rid = cells[0]
        if not rid.strip():
            problems.append(f'{LEDGER_FILE} line {n}: no id: {line[:80]!r}')
        elif rid != rid.strip():
            # Writers key facts by the stripped id, so a padded one would be
            # dropped and written again as a new fact
            problems.append(f'{LEDGER_FILE} line {n}: id {rid!r} has surrounding '
                            f'whitespace')
        elif rid in seen:
            problems.append(f'{LEDGER_FILE} line {n}: id {rid!r} is also on line '
                            f'{seen[rid]}')
        else:
            seen[rid] = n
    return problems


def legacy_files(ref_dir: str) -> list[str]:
    """The replaced files still present in `ref_dir`."""
    return [f for f in LEGACY_FILES if os.path.isfile(os.path.join(ref_dir, f))]


def not_migrated_message(ref_dir: str) -> str | None:
    """Why the registries can't be read yet, or None when they can.

    The old files alone need `storyforge migrate`. The old files beside a
    ledger are a half-finished migration or a restored file; which holds the
    truth is the author's call, so nothing reads either.
    """
    old = legacy_files(ref_dir)
    if not old:
        return None
    names = ' and '.join(f'reference/{f}' for f in old)
    if os.path.isfile(os.path.join(ref_dir, LEDGER_FILE)):
        return (f'{names} {"is" if len(old) == 1 else "are"} still present beside '
                f'reference/{LEDGER_FILE}, which replaced {"it" if len(old) == 1 else "them"}. '
                f'Check that the ledger holds every fact, then delete '
                f'{"it" if len(old) == 1 else "them"} (storyforge migrate never '
                f'overwrites an existing ledger).')
    return (f'{names} must move into reference/{LEDGER_FILE} before Storyforge '
            f'can read the knowledge facts and physical states: run '
            f'`storyforge migrate`.')


def exit_if_not_migrated(project_dir: str) -> None:
    """Stop the command (exit 1) when the registries can't be read: the old
    files are still there, or the ledger has a problem `file_problems` names."""
    try:
        load(project_dir)
    except LedgerError as e:
        from storyforge.common import log
        log(f'ERROR: {e}')
        raise SystemExit(1)


def exit_if_unordered(project_dir: str) -> None:
    """Stop the command (exit 1) when scenes.csv has a scene without a
    numeric `seq`: drafting reads the ledger as of each scene
    (`drafting_slice`), and without an order what came before is a guess."""
    if not os.path.isfile(os.path.join(project_dir, 'reference', 'scenes.csv')):
        return
    try:
        scene_order(project_dir)
    except ValueError as e:
        from storyforge.common import log
        log(f'ERROR: {e}. Give every scene a number in seq.')
        raise SystemExit(1)


def load_from(ref_dir: str) -> list[dict[str, str]]:
    """The ledger in `ref_dir`; no ledger and no old files → [].

    Raises:
        NotMigratedError: while knowledge.csv or physical-states.csv is there.
        LedgerError: when the ledger has a problem `file_problems` names.
    """
    message = not_migrated_message(ref_dir)
    if message:
        raise NotMigratedError(message)
    path = os.path.join(ref_dir, LEDGER_FILE)
    problems = file_problems(path)
    if problems:
        raise LedgerError(f'reference/{LEDGER_FILE} can\'t be read until these are '
                          f'fixed: ' + '; '.join(problems))
    return read_ledger(path)


def load(project_dir: str) -> list[dict[str, str]]:
    return load_from(os.path.join(project_dir, 'reference'))


#: Serializes save_to's read-old / write / read-back / log sequence
_SAVE_LOCK = threading.Lock()


def save_to(ref_dir: str, rows: list[dict[str, str]], *, command: str) -> None:
    """Write `ref_dir`'s ledger and append the change to the audit log.

    `command` names the writer (`hone`, `extract`, `audit`, ...): the audit
    entry of every changed or removed fact carries it, and an added fact
    with no `introduced_by` does too. The log entries are a diff of the file
    before and after the write, read back, so they record what is on disk.
    The ledger is written first: a log that can't be written is a WARNING
    and the ledger write stands (`storyforge.audit` says why). A change made
    on disk since the last logged write (by hand) is logged first, as
    `command=hand-edit`, from the snapshot `audit` keeps.
    """
    from storyforge import audit
    path = os.path.join(ref_dir, LEDGER_FILE)
    project_dir = audit.project_of(ref_dir)
    with _SAVE_LOCK:
        old = read_ledger(path) if os.path.isfile(path) else []
        # What changed on disk since the last logged write was not this writer
        audit.log_hand_edits(project_dir, old)
        write_ledger(path, rows)
        written = read_ledger(path)
        audit.record(project_dir, old, written, command=command)
        audit.write_snapshot(project_dir, written)


def save(project_dir: str, rows: list[dict[str, str]], *, command: str) -> None:
    save_to(os.path.join(project_dir, 'reference'), rows, command=command)


# ============================================================================
# Read and write
# ============================================================================

def _raw_lines(path: str) -> tuple[list[str], bool]:
    """A file's lines, split on newlines only (a U+2028 inside a cell is not a
    row break), and whether it had CRLF endings."""
    with open(path, newline='', encoding='utf-8') as f:
        text = f.read()
    crlf = '\r\n' in text
    text = text.replace('\r\n', '\n').replace('\r', '')
    lines = text.split('\n')
    if lines and lines[-1] == '':
        lines.pop()
    return lines, crlf


def _read_rows(path: str) -> tuple[list[str], list[dict[str, str]]]:
    """Header (stripped) and rows of a pipe-delimited CSV; missing file → empty."""
    if not os.path.isfile(path):
        return [], []
    lines, _ = _raw_lines(path)
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
        # Only a value that would break the row is collapsed: one read from
        # the file goes back as it was
        return csv_safe(value) if ('|' in value or '\n' in value
                                   or '\r' in value) else value
    # Ids, enums and `;` lists: a `|` or newline here is corrupt data, and
    # collapsing it would hide that
    if '|' in value or '\n' in value or '\r' in value:
        raise ValueError(f'{row.get("id", "?")}: {column} holds a "|" or a '
                         f'line break: {value!r}')
    return value


# ============================================================================
# Typed views: one type's rows in the old files' shapes
# ============================================================================

#: View columns per type. A physical view's `character` is the subject id.
VIEW_COLUMNS = {'knowledge': KNOWLEDGE_COLUMNS, 'physical': PHYSICAL_COLUMNS}

#: `introduced_by` of the rubric pass (extract phase 4).
COMMITMENTS_PASS = 'commitments'

#: Every `introduced_by` that writes commitments rather than registry facts:
#: the rubric pass and the gate, which tags a row with the command that wrote
#: the prose (`docs/plans/2026-10-30-gate-ledger-design.md`). Their knowledge
#: and physical facts are not registry entries: briefs don't reference them
#: by id, so the views leave them out and view writes leave them as they are.
#: Any other value, blank included (a hand-added row), is a registry fact.
COMMITMENT_WRITERS = (COMMITMENTS_PASS, 'draft', 'redraft', 'revise', 'advisor')


def is_commitment(row: dict) -> bool:
    """Whether `row` is a commitment (what the prose said), not a registry
    fact (what a brief can name)."""
    return (row.get('introduced_by') or '').strip() in COMMITMENT_WRITERS


def _in_view(row: dict, type_: str) -> bool:
    return row.get('type') == type_ and not is_commitment(row)


def view(rows: list[dict[str, str]], type_: str) -> list[dict[str, str]]:
    """`type_`'s registry rows in its view's columns, in ledger order."""
    file = _FILE_OF[type_]
    return [{c: _old_cells(r, file, 'standard')[c] for c in VIEW_COLUMNS[type_]}
            for r in rows if _in_view(r, type_)]


def knowledge_view(rows: list[dict[str, str]]) -> list[dict[str, str]]:
    """Knowledge facts as id / name / aliases / category / origin (the scene)."""
    return view(rows, 'knowledge')


def physical_view(rows: list[dict[str, str]]) -> list[dict[str, str]]:
    """Physical states as id / character / description / category /
    acquired / resolves / action_gating. `character` is the subject id, or,
    for a subject the migration couldn't resolve (blank), the name it kept
    in aliases."""
    return view(rows, 'physical')


def read_view(ref_dir: str, type_: str) -> list[dict[str, str]]:
    return view(load_from(ref_dir), type_)


def view_map(ref_dir: str, type_: str) -> dict[str, dict[str, str]]:
    """id → view row of `type_`."""
    return {r['id']: r for r in read_view(ref_dir, type_) if r['id']}


#: Which ledger column each view column is
_VIEW_TO_LEDGER = {
    'knowledge': {'name': 'statement', 'aliases': 'aliases', 'category': 'category',
                  'origin': 'scene_id'},
    'physical': {'character': 'subject', 'description': 'statement',
                 'category': 'category', 'acquired': 'scene_id',
                 'resolves': 'resolves', 'action_gating': 'action_gating'},
}


def _from_view(type_: str, cells: dict) -> dict[str, str]:
    """The ledger columns a view row sets (the view's inverse)."""
    def get(column):
        return (cells.get(column) or '').strip()
    if type_ == 'knowledge':
        origin = get('origin')
        return {'statement': get('name'), 'aliases': get('aliases'),
                'category': get('category'),
                'scene_id': '' if origin in _NO_SCENE_ORIGINS else origin}
    return {'subject': get('character'), 'statement': get('description'),
            'category': get('category'), 'scene_id': get('acquired'),
            'resolves': get('resolves'), 'action_gating': get('action_gating')}


def replace_view(rows: list[dict[str, str]], type_: str,
                 view_rows: list[dict[str, str]], *, origin: str,
                 introduced_by: str) -> list[dict[str, str]]:
    """The ledger with `type_`'s rows replaced by `view_rows`.

    Rows of every other type, and commitments (`is_commitment`),
    stay as they are, where they are. A `type_` row whose id is still in
    `view_rows` keeps its place and every column the view doesn't carry
    (quote, known_by, status, ...), and only the cells whose view value
    changed are rewritten; one whose id is gone is dropped. A new id becomes
    a binding `state` fact with `origin` and `introduced_by`, placed after
    the type's last row.

    Raises:
        ValueError: if a new id is already a fact of another type (the ledger
            would hold one id twice), or `introduced_by` is a commitment
            writer (its rows would drop out of the view it just wrote).
    """
    if introduced_by.strip() in COMMITMENT_WRITERS:
        raise ValueError(f'{introduced_by!r} writes commitments, not registry facts: '
                         f'a view write needs a registry writer\'s name')
    wanted: dict[str, dict] = {}
    for vr in view_rows:
        rid = (vr.get('id') or '').strip()
        if rid:
            wanted[rid] = vr
    out: list[dict[str, str]] = []
    placed: set[str] = set()
    insert_at = None
    for row in rows:
        if not _in_view(row, type_):
            out.append(row)
            continue
        vr = wanted.get(row.get('id', ''))
        if vr is None or row['id'] in placed:
            continue
        # Only the cells the writer changed: an untouched row goes back as it
        # was (whitespace, a `backstory` scene_id, a name kept in aliases)
        current = view([row], type_)[0]
        mapped = _from_view(type_, vr)
        updated = dict(row)
        for vcol, lcol in _VIEW_TO_LEDGER[type_].items():
            # Compared stripped, as `_from_view` writes them: a writer that
            # strips a cell hasn't changed it (and a blank subject shown as
            # its kept alias must not become that name)
            if (vr.get(vcol) or '').strip() != current[vcol].strip():
                updated[lcol] = mapped[lcol]
        out.append(updated)
        placed.add(row['id'])
        insert_at = len(out)
    other_ids = {r.get('id', '') for r in rows if not _in_view(r, type_)}
    new = []
    for rid, vr in wanted.items():
        if rid in placed:
            continue
        if rid in other_ids:
            raise ValueError(f'{rid}: already in {LEDGER_FILE} as another type '
                             f'of fact (or a commitment); a {type_} fact needs '
                             f'its own id')
        row = _base_row(rid, type_)
        row.update(origin=origin, introduced_by=introduced_by)
        row.update(_from_view(type_, vr))
        new.append(row)
    if insert_at is None:
        insert_at = len(out)
    return out[:insert_at] + new + out[insert_at:]


def write_view(ref_dir: str, type_: str, view_rows: list[dict[str, str]], *,
               origin: str, introduced_by: str, command: str | None = None) -> None:
    """Replace `type_`'s rows in `ref_dir`'s ledger (see `replace_view`).

    The change is audit-logged under `command`, which defaults to
    `introduced_by` (the writer's name either way)."""
    rows = load_from(ref_dir)
    new = replace_view(rows, type_, view_rows, origin=origin,
                       introduced_by=introduced_by)
    if new != rows:
        save_to(ref_dir, new, command=command or introduced_by)


def fill_quote(rows: list[dict[str, str]], fact_id: str, quote: str) -> bool:
    """Set registry fact `fact_id`'s `quote` to `quote` if the cell is blank,
    in place; True if it was set. A quote already there is never replaced
    (False). This is the only change the gate makes to a registry row: a
    brief's promised fact, confirmed in the prose, gains its evidence
    (`docs/plans/2026-10-30-gate-ledger-design.md`).

    The quote is not checked against the prose here: the gate passes only
    quotes the checker found verbatim in the scene.

    Raises:
        ValueError: `fact_id` is not in `rows`; is a commitment, not a binding
            knowledge or physical registry fact (what a brief can name); or
            `quote` is blank.
    """
    if not quote.strip():
        raise ValueError(f'{fact_id}: no quote to fill')
    row = next((r for r in rows if r.get('id') == fact_id), None)
    if row is None:
        raise ValueError(f'{fact_id}: not in {LEDGER_FILE}')
    if is_commitment(row):
        raise ValueError(f'{fact_id}: a commitment, not a registry fact; its quote '
                         f'is the one extraction recorded')
    if row.get('status') != 'binding' or row.get('type') not in VIEW_COLUMNS:
        raise ValueError(f'{fact_id}: not a binding knowledge or physical registry fact '
                         f'(status {row.get("status")!r}, type {row.get("type")!r})')
    if (row.get('quote') or '').strip():
        return False
    row['quote'] = ' '.join(quote.split())
    return True


def alias_map(view_rows: list[dict[str, str]]) -> dict[str, str]:
    """Lowercased id, name and alias → id, like `enrich.load_alias_map` on a
    view (a physical view has no name: its map is its ids)."""
    out: dict[str, str] = {}
    for row in view_rows:
        rid = (row.get('id') or '').strip()
        if not rid:
            continue
        name = (row.get('name') or '').strip()
        if name:
            out[name.lower()] = rid
        out[rid.lower()] = rid
        for alias in (row.get('aliases') or '').split(';'):
            if alias.strip():
                out[alias.strip().lower()] = rid
    return out


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

    Unlike `elaborate`'s state-disappearance check, which lets a state recur
    after its one `resolves` scene, a resolved fact stays resolved here: a
    state that returns is a new fact with its own `scene_id`.

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


@dataclass
class DraftingSlice:
    """What drafting `scene_id` must agree with (rethink plan §3.1, §3.3)."""
    #: subject id → its `fixed` facts established before the scene, or with a
    #: blank scene (backstory), and not superseded by then; in reading order
    fixed: dict[str, list[dict[str, str]]] = field(default_factory=dict)
    #: subject id → its `state` facts in force entering the scene
    #: (`active_states(entering=True)`: a state the scene itself supersedes
    #: is still in force entering it), in reading order
    states: dict[str, list[dict[str, str]]] = field(default_factory=dict)
    #: binding facts established in the scene itself, by its plan or by
    #: prose it already has
    scene: list[dict[str, str]] = field(default_factory=list)
    #: binding facts whose `scene_id` is neither blank nor a scene (a renamed
    #: or deleted scene): when they hold can't be told, so they are left out
    #: and the caller names them
    unplaced: list[dict[str, str]] = field(default_factory=list)


def drafting_slice(rows: list[dict[str, str]], scene_id: str,
                   order: dict[str, int], subjects: list[str]) -> DraftingSlice:
    """The binding facts about `subjects` (the scene's characters and its
    location) as of entering `scene_id`, and the facts the scene itself
    established.

    A fact is filed under its subject when that is one of `subjects`, else
    under the first of `subjects` in its `known_by` (a character's knowledge
    about someone off stage), else not at all (an object, someone off stage
    whom no one here knows about). Each fact appears once: a fact
    established in the scene goes to `scene` only. Unlike `active_states`,
    a fact whose `scene_id` is not blank and not a scene is not treated as
    backstory (it may be a later scene, renamed): it goes to `unplaced`.

    Raises:
        KeyError: if `scene_id` is not in `order`.
    """
    at = order[scene_id]
    binding, out = [], DraftingSlice()
    for r in rows:
        if r.get('status') != 'binding':
            continue
        sid = r.get('scene_id', '').strip()
        if sid and sid not in order:
            out.unplaced.append(r)
        else:
            binding.append(r)

    def pos(r: dict) -> int:
        return order.get(r.get('scene_id', '').strip(), -1)

    superseded = {old for r in binding if pos(r) <= at
                  for old in _split(r.get('supersedes', ''))}

    def owner(r: dict) -> str | None:
        if r.get('subject', '') in subjects:
            return r['subject']
        knowers = _split(r.get('known_by', ''))
        return next((s for s in subjects if s in knowers), None)

    for r in binding:
        if r.get('scene_id', '').strip() == scene_id:
            out.scene.append(r)
    earlier = sorted((r for r in binding if r.get('mutable') == 'fixed'
                      and pos(r) < at and r['id'] not in superseded),
                     key=pos)
    for r in earlier:
        who = owner(r)
        if who:
            out.fixed.setdefault(who, []).append(r)
    for r in sorted(active_states(binding, scene_id, order, entering=True), key=pos):
        who = owner(r)
        if who:
            out.states.setdefault(who, []).append(r)
    return out


# ============================================================================
# Migration from knowledge.csv and physical-states.csv
# ============================================================================

@dataclass
class Quirk:
    """Something the migration couldn't carry over as is, for the author.

    A quirk with a `column` names one cell: the old file had `old` there and
    the ledger gives back `new`. The round trip accepts exactly that change
    and no other.
    """
    file: str      # 'knowledge.csv' or 'physical-states.csv'
    kind: str
    row_id: str    # '' for a file-level quirk
    detail: str
    column: str = ''
    old: str = ''
    new: str = ''

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

_FILE_OF = {'knowledge': 'knowledge.csv', 'physical': 'physical-states.csv'}


def migrate_registries(ref_dir: str) -> Migration:
    """Ledger rows from `ref_dir`'s knowledge.csv and physical-states.csv.

    Nothing is written. Every change from the old data is a `Quirk`. A
    duplicate id whose rows differ, a row with more cells than the header,
    or a column the ledger has no place for is an error, since keeping
    either version would be a guess.
    """
    result = Migration()
    scene_ids = set(_ids(os.path.join(ref_dir, 'scenes.csv')))
    for file in _FILE_OF.values():
        path = os.path.join(ref_dir, file)
        if os.path.isfile(path):
            _migrate_file(ref_dir, file, path, scene_ids, result)
    seen: dict[str, str] = {}
    for row in result.rows:
        other = seen.get(row['id'])
        if other is not None:
            result.errors.append(f'id {row["id"]!r} is in both {other} and '
                                 f'{_FILE_OF[row["type"]]}')
        seen[row['id']] = _FILE_OF[row['type']]
    return result


def _ids(path: str) -> list[str]:
    _, rows = _read_rows(path)
    return [r.get('id', '').strip() for r in rows if r.get('id', '').strip()]


def _base_row(rid: str, type_: str) -> dict[str, str]:
    row = {c: '' for c in COLUMNS}
    row.update(id=rid, type=type_, origin='migrated', status='binding',
               mutable='state', introduced_by='migration')
    return row


def _old_rows(path: str, file: str, result: Migration):
    """(header, layout, [(id, cells by column)]) of an old file, with its
    structural quirks and errors recorded. `layout`: 'standard', 'fact'
    (lantern-folk) or 'slug' (understory); None when it can't be migrated."""
    lines, crlf = _raw_lines(path)
    if not lines:
        return [], None, []
    if crlf:
        result.quirks.append(Quirk(file, 'crlf', '', 'CRLF line endings (the '
                                   'ledger writes LF)'))
    raw_header = lines[0].split('|')
    header = [h.strip() for h in raw_header]
    if raw_header != header:
        result.quirks.append(Quirk(file, 'header', '',
                                   f'header {lines[0]!r} has stray whitespace'))
    known = KNOWLEDGE_COLUMNS + ['fact'] if file == 'knowledge.csv' else PHYSICAL_COLUMNS
    extra = [h for h in header if h not in known]
    if extra or 'id' not in header:
        result.errors.append(f'{file}: columns the ledger has no place for: '
                             f'{", ".join(extra) or "(no id column)"}')
        return header, None, []
    rows = []
    for n, line in enumerate(lines[1:], start=2):
        if not line.strip():
            continue
        cells = line.split('|')
        if len(cells) > len(header):
            result.errors.append(f'{file} line {n}: {len(cells)} cells, the '
                                 f'header has {len(header)}: {line[:80]!r}')
            continue
        by_col = {h: (cells[i] if i < len(cells) else '') for i, h in enumerate(header)}
        rid = by_col['id'].strip()
        if not rid:
            result.errors.append(f'{file} line {n}: no id: {line[:80]!r}')
            continue
        rows.append((rid, by_col))
    layout = 'standard'
    if file == 'knowledge.csv' and 'fact' in header:
        layout = 'fact'
        result.quirks.append(Quirk(file, 'fact-column', '',
                                   'statements taken from the `fact` column'))
        for rid, cells in rows:
            if cells.get('name', '').strip():
                result.errors.append(f'{file} {rid}: both `fact` and `name` hold '
                                     f'text; which is the statement is a guess')
    elif file == 'knowledge.csv' and rows and all(
            _is_slug(c.get('name', '')) and _split(c.get('aliases', ''))
            for _, c in rows):
        layout = 'slug'
        result.quirks.append(Quirk(
            file, 'slug-names', '',
            '`name` holds slugs: statements taken from the first alias, and '
            'each slug kept as the first alias'))
    return header, layout, rows


def _dedupe(rows, file, result):
    """Drop exact duplicate rows (reported); a differing duplicate is an error."""
    kept: dict[str, dict] = {}
    for rid, cells in rows:
        if rid in kept:
            if kept[rid] == cells:
                result.quirks.append(Quirk(file, 'duplicate', rid,
                                           'exact duplicate row dropped'))
            else:
                result.errors.append(f'{file}: id {rid!r} is on two rows that differ')
            continue
        kept[rid] = cells
    return list(kept.items())


def _migrate_file(ref_dir, file, path, scene_ids, result):
    header, layout, rows = _old_rows(path, file, result)
    if layout is None:
        return
    characters = {}
    if file == 'physical-states.csv':
        from storyforge.enrich import load_alias_map
        characters = load_alias_map(os.path.join(ref_dir, 'characters.csv'))
    for rid, cells in _dedupe(rows, file, result):
        clean = {}
        for column, value in cells.items():
            clean[column] = value.strip()
            if column != 'id' and value != value.strip():
                result.quirks.append(Quirk(
                    file, 'whitespace', rid, f'{column}: surrounding whitespace '
                    f'removed', column=column, old=value, new=value.strip()))
        if rid != cells['id']:
            result.quirks.append(Quirk(file, 'whitespace', rid, 'id: surrounding '
                                       'whitespace removed', column='id',
                                       old=cells['id'], new=rid))
        if file == 'knowledge.csv':
            result.rows.append(_knowledge_row(rid, clean, layout, scene_ids, file, result))
        else:
            result.rows.append(_physical_row(rid, clean, characters, scene_ids, file, result))


def _knowledge_row(rid, cells, layout, scene_ids, file, result):
    row = _base_row(rid, 'knowledge')
    row['category'] = cells.get('category', '')
    aliases = cells.get('aliases', '')
    if layout == 'fact':
        row['statement'] = cells.get('fact', '')
    elif layout == 'slug':
        row['statement'] = _split(aliases)[0]
        aliases = f'{cells["name"]};{aliases}'
    else:
        row['statement'] = cells.get('name', '')
    row['aliases'] = aliases
    origin = cells.get('origin', '')
    if origin in _NO_SCENE_ORIGINS or not origin:
        result.quirks.append(Quirk(
            file, 'no-scene', rid,
            f'origin {origin!r} names no scene: scene_id left blank'
            if origin else 'no origin: scene_id left blank',
            column='origin', old=origin, new=''))
    else:
        row['scene_id'] = origin
        if origin not in scene_ids:
            result.quirks.append(Quirk(
                file, 'unknown-scene', rid,
                f'origin {origin!r} is not a scene id (renamed or removed '
                f'scene?): kept as scene_id'))
    return row


def _physical_row(rid, cells, characters, scene_ids, file, result):
    row = _base_row(rid, 'physical')
    name = cells.get('character', '')
    subject = characters.get(name.lower(), '')
    if not subject:
        # Kept in aliases so the name isn't lost; validate reports the row
        result.quirks.append(Quirk(
            file, 'unresolved-character', rid,
            f'character {name!r} is not in characters.csv (name, id or '
            f'alias): subject left blank, the name kept in aliases'))
    elif subject != name:
        result.quirks.append(Quirk(
            file, 'character-id', rid, f'character {name!r} is written as its '
            f'id {subject!r}', column='character', old=name, new=subject))
    row['subject'] = subject
    if not subject and name:
        row['aliases'] = name
    row['statement'] = cells.get('description', '')
    row['category'] = cells.get('category', '')
    row['scene_id'] = cells.get('acquired', '')
    row['resolves'] = cells.get('resolves', '')
    row['action_gating'] = cells.get('action_gating', '')
    for column, sid in (('acquired', row['scene_id']), ('resolves', row['resolves'])):
        if sid and sid != 'never' and sid not in scene_ids:
            result.quirks.append(Quirk(file, 'unknown-scene', rid,
                                       f'{column} {sid!r} is not a scene id: kept'))
    return row


def _is_slug(value: str) -> bool:
    value = value.strip()
    return bool(value) and ' ' not in value and value == value.lower()


# ============================================================================
# Round trip
# ============================================================================

def regenerate_knowledge(rows: list[dict[str, str]]) -> str:
    """knowledge.csv's text (standard columns), written back out of the ledger."""
    lines = ['|'.join(KNOWLEDGE_COLUMNS)]
    for r in rows:
        if r.get('type') == 'knowledge':
            cells = _old_cells(r, 'knowledge.csv', 'standard')
            lines.append('|'.join(cells[c] for c in KNOWLEDGE_COLUMNS))
    return '\n'.join(lines) + '\n'


def regenerate_physical(rows: list[dict[str, str]]) -> str:
    """physical-states.csv's text, written back out of the ledger (with the
    character as its id)."""
    lines = ['|'.join(PHYSICAL_COLUMNS)]
    for r in rows:
        if r.get('type') == 'physical':
            cells = _old_cells(r, 'physical-states.csv', 'standard')
            lines.append('|'.join(cells[c] for c in PHYSICAL_COLUMNS))
    return '\n'.join(lines) + '\n'


def _old_cells(row: dict, file: str, layout: str) -> dict[str, str]:
    """A ledger row in the old file's columns (the migration, inverted)."""
    if file == 'physical-states.csv':
        # A subject that couldn't be resolved keeps its name in aliases
        return {'id': row['id'], 'character': row['subject'] or row['aliases'],
                'description': row['statement'], 'category': row['category'],
                'acquired': row['scene_id'], 'resolves': row['resolves'],
                'action_gating': row['action_gating']}
    cells = {'id': row['id'], 'name': row['statement'], 'aliases': row['aliases'],
             'category': row['category'], 'origin': row['scene_id'], 'fact': ''}
    if layout == 'fact':
        cells.update(fact=row['statement'], name='')
    elif layout == 'slug':
        slug, _, rest = row['aliases'].partition(';')
        cells.update(name=slug, aliases=rest)
    return cells


def round_trip_differences(ref_dir: str, migration: Migration) -> list[str]:
    """Every cell of the old files that doesn't come back from the ledger
    unchanged and that no quirk names. Empty means the round trip holds.

    Each old row is written back in its own file's columns and compared cell
    by cell. A cell quirk accepts exactly its `old` → `new` change; an exact
    duplicate row compares against the one ledger row it became. Rows the
    ledger lost or gained, and a change of order, are differences too.
    """
    out = []
    for type_, file in _FILE_OF.items():
        path = os.path.join(ref_dir, file)
        if not os.path.isfile(path):
            continue
        scratch = Migration()
        header, layout, rows = _old_rows(path, file, scratch)
        if layout is None:
            out += [f'{e} (not migrated)' for e in scratch.errors]
            continue
        accepted = {(q.row_id, q.column): (q.old, q.new)
                    for q in migration.quirks if q.file == file and q.column}
        ledger_rows = [r for r in migration.rows if r.get('type') == type_]
        by_id = {r['id']: r for r in ledger_rows}
        for rid, cells in rows:
            new = by_id.get(rid)
            if new is None:
                out.append(f'{file} {rid}: missing from the ledger')
                continue
            back = _old_cells(new, file, layout)
            if layout == 'slug' and _split(back['aliases'])[:1] != [new['statement']]:
                # The statement is the first alias, so a changed one shows only here
                out.append(f'{file} {rid}: statement {new["statement"]!r} is not '
                           f'the first alias')
            for column in header:
                old_value, new_value = cells[column], back[column]
                if old_value == new_value or accepted.get((rid, column)) == (
                        old_value, new_value):
                    continue
                out.append(f'{file} {rid}: {column} {old_value!r} came back as '
                           f'{new_value!r}')
        old_ids = list(dict.fromkeys(rid for rid, _ in rows))
        new_ids = [r['id'] for r in ledger_rows]
        for rid in new_ids:
            if rid not in old_ids:
                out.append(f'{file} {rid}: in the ledger but not in the old file')
        if [i for i in new_ids if i in old_ids] != [i for i in old_ids if i in new_ids]:
            out.append(f'{file}: rows came back in a different order')
    return out


# ============================================================================
# The migration step (storyforge migrate)
# ============================================================================

@dataclass
class FileMigration:
    """What `migrate_files` did. `status`: 'skip' (no old files), 'stopped'
    (nothing changed; `problems` says why), 'dry-run' or 'done'."""
    status: str
    rows: list[dict[str, str]] = field(default_factory=list)
    quirks: list[Quirk] = field(default_factory=list)
    problems: list[str] = field(default_factory=list)
    removed: list[str] = field(default_factory=list)


def migration_blockers(ref_dir: str) -> tuple[Migration | None, list[str]]:
    """Run the migration without writing: (migration, problems that stop it).

    None when there is nothing to migrate. A ledger already beside the old
    files stops it: merging into an existing ledger would be a guess.
    """
    old = legacy_files(ref_dir)
    if not old:
        return None, []
    if os.path.isfile(os.path.join(ref_dir, LEDGER_FILE)):
        return None, [not_migrated_message(ref_dir)]
    migration = migrate_registries(ref_dir)
    problems = list(migration.errors)
    if not problems:
        problems = round_trip_differences(ref_dir, migration)
    return migration, problems


def migrate_files(ref_dir: str, *, dry_run: bool = False) -> FileMigration:
    """Move knowledge.csv and physical-states.csv into commitments.csv.

    Stops, changing nothing, on a migration error, on a ledger that already
    exists, or when the round trip doesn't hold. Otherwise writes the ledger,
    checks the round trip again from the written file (a cell the writer
    changed shows there), and only then deletes the old files. Idempotent:
    with no old files it is a skip.
    """
    old = legacy_files(ref_dir)
    if not old:
        return FileMigration('skip')
    migration, problems = migration_blockers(ref_dir)
    if problems:
        return FileMigration('stopped', problems=problems,
                             quirks=migration.quirks if migration else [])
    result = FileMigration('dry-run' if dry_run else 'done', rows=migration.rows,
                           quirks=migration.quirks)
    if dry_run:
        result.removed = old
        return result
    path = os.path.join(ref_dir, LEDGER_FILE)
    write_ledger(path, migration.rows)
    written = Migration(read_ledger(path), migration.quirks, migration.errors)
    problems = round_trip_differences(ref_dir, written)
    if problems:
        os.remove(path)
        result.status, result.problems = 'stopped', problems
        return result
    for file in old:
        os.remove(os.path.join(ref_dir, file))
    result.removed = old
    # One summary entry, not one per row (`storyforge.audit` says why)
    from storyforge import audit
    audit.record_migration(audit.project_of(ref_dir), migration.rows, old)
    audit.write_snapshot(audit.project_of(ref_dir), read_ledger(path))
    return result
