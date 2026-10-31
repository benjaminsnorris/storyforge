"""The audit log, the digest, and the immediate-tier checks (rethink plan
decision 2, `docs/plans/2026-10-28-storyforge-rethink.md`).

**The log** (`working/audit-log.csv`) is append-only: one entry per fact
added, changed or removed, written centrally by `ledger.save_to` (and so by
`save` and `write_view`) from a diff of the ledger file before and after the
write. Nothing else writes it. Columns are `COLUMNS`; pipe-delimited, LF, every
cell through `common.csv_safe`. `change` is one of `CHANGES`:

- `added` / `removed`: the id appeared / disappeared.
- `superseded` / `rejected`: `status` became that value.
- `reviewed`: only `reviewed` changed (an audit mark).
- `changed`: anything else; `columns` names the columns that changed.
- `migrated`: one summary entry for `storyforge migrate`'s move of
  knowledge.csv and physical-states.csv into the ledger. The migrated rows
  themselves are not logged one by one: they are the ledger's starting state,
  every one carries `introduced_by=migration`, and hundreds of entries saying
  "this fact existed before the log did" would bury the entries that matter.

`command` is the row's `introduced_by` for an added row (falling back to the
writer's `command`), and the writer's `command` otherwise.

The ledger is written first and the log second. If the log can't be written
(an unwritable `working/`, a log whose header isn't `COLUMNS`), the ledger
write stands and a WARNING names the file and the fact ids whose entries
were lost. That is not a warn-and-continue past wrong output: the digest
reads the ledger's `reviewed` column, never the log, so nothing downstream
is wrong; only the history is incomplete, and the WARNING says where.

**Edits made outside Storyforge** (by hand, or by a skill that edits
commitments.csv directly) never pass through `save_to`, so its diff can't
see them. `working/.audit-snapshot.csv` holds the ledger as the log last
recorded it; before each logged write, and on every `storyforge audit` run,
`log_hand_edits` logs the snapshot-to-disk difference as `command=hand-edit`.
The snapshot is committed with the log (it is the log's baseline, and a
clone without it would treat the next hand edit as the starting state). A
project with no snapshot yet starts one, logging nothing.

**The digest** (`digest`, used by `storyforge audit`) lists binding facts with
a blank `reviewed`, in tiers (`TIERS`: `fixed` facts, then relationship and
knowledge, then physical state, then other state facts), grouped by subject
within each tier.

**The immediate tier** (`halting_conditions`) is for Phase 3's gate; nothing
but tests calls it yet.
"""

from __future__ import annotations

import os
import threading
from dataclasses import dataclass, field
from datetime import datetime, timezone

from storyforge.common import csv_safe, log

LOG_FILE = 'audit-log.csv'
#: Relative to the project root, for commit paths
LOG_PATH = f'working/{LOG_FILE}'

COLUMNS = ['timestamp', 'scene_id', 'fact_id', 'change', 'command', 'type',
           'subject', 'columns', 'statement']

CHANGES = ('added', 'changed', 'removed', 'superseded', 'rejected', 'reviewed',
           'migrated')

_LOCK = threading.Lock()


def log_path(project_dir: str) -> str:
    return os.path.join(project_dir, 'working', LOG_FILE)


def project_of(ref_dir: str) -> str:
    """The project root a `reference/` directory belongs to."""
    return os.path.dirname(os.path.abspath(ref_dir))


def _now() -> str:
    return datetime.now(timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ')


# ============================================================================
# Writing the log
# ============================================================================

def diff_entries(old: list[dict[str, str]], new: list[dict[str, str]], *,
                 command: str, timestamp: str | None = None) -> list[dict[str, str]]:
    """Log entries for the change from ledger rows `old` to `new`.

    Rows are matched by id. New rows come first, in `new`'s order (added or
    changed), then removed rows in `old`'s order. A row that is the same in
    every column gives no entry.
    """
    from storyforge.ledger import COLUMNS as LEDGER_COLUMNS
    ts = timestamp or _now()
    before = {r.get('id', ''): r for r in old}
    after_ids = {r.get('id', '') for r in new}
    out = []

    def entry(row, change, cmd, columns=()):
        return {'timestamp': ts, 'scene_id': row.get('scene_id', ''),
                'fact_id': row.get('id', ''), 'change': change, 'command': cmd,
                'type': row.get('type', ''), 'subject': row.get('subject', ''),
                'columns': ';'.join(columns), 'statement': row.get('statement', '')}

    for row in new:
        rid = row.get('id', '')
        prev = before.get(rid)
        if prev is None:
            out.append(entry(row, 'added', row.get('introduced_by') or command))
            continue
        changed = [c for c in LEDGER_COLUMNS
                   if (prev.get(c) or '') != (row.get(c) or '')]
        if not changed:
            continue
        status = (row.get('status') or '').strip()
        if 'status' in changed and status in ('superseded', 'rejected'):
            kind = status
        elif changed == ['reviewed']:
            kind = 'reviewed'
        else:
            kind = 'changed'
        out.append(entry(row, kind, command, changed))
    for row in old:
        if row.get('id', '') not in after_ids:
            out.append(entry(row, 'removed', command))
    return out


class AuditLogError(OSError):
    """The log exists but can't be appended to as it is."""


def append_entries(project_dir: str, entries: list[dict[str, str]]) -> None:
    """Append `entries` to the project's log, creating it with its header.

    Raises:
        OSError: the file can't be written.
        AuditLogError: the existing file's header isn't `COLUMNS` (appending
            would put cells under the wrong columns).
    """
    if not entries:
        return
    path = log_path(project_dir)
    with _LOCK:
        os.makedirs(os.path.dirname(path), exist_ok=True)
        exists = os.path.isfile(path) and os.path.getsize(path) > 0
        if exists:
            with open(path, newline='', encoding='utf-8') as f:
                header = f.readline().rstrip('\r\n')
            if header != '|'.join(COLUMNS):
                raise AuditLogError(f'its header is {header!r}, not '
                                    f'{"|".join(COLUMNS)!r}')
        with open(path, 'a', newline='', encoding='utf-8') as f:
            if not exists:
                f.write('|'.join(COLUMNS) + '\n')
            for e in entries:
                f.write('|'.join(csv_safe(str(e.get(c, '') or '')) for c in COLUMNS)
                        + '\n')


def record(project_dir: str, old: list[dict[str, str]], new: list[dict[str, str]],
           *, command: str) -> list[dict[str, str]]:
    """Diff `old` → `new` and append the entries. Never raises: a failure is
    a WARNING naming the file and the facts whose entries were lost (see the
    module docstring for why the ledger write stands). Returns the entries."""
    entries = diff_entries(old, new, command=command)
    _append_or_warn(project_dir, entries)
    return entries


def record_migration(project_dir: str, rows: list[dict[str, str]],
                     removed: list[str]) -> list[dict[str, str]]:
    """The one `migrated` entry for `storyforge migrate`'s ledger step."""
    from collections import Counter
    counts = Counter(r.get('type', '') for r in rows)
    what = ', '.join(f'{n} {t}' for t, n in sorted(counts.items())) or 'no facts'
    entries = [{'timestamp': _now(), 'change': 'migrated', 'command': 'migrate',
                'statement': f'{len(rows)} facts ({what}) moved into the ledger '
                             f'from {" and ".join(removed)}; each has '
                             f'introduced_by=migration'}]
    _append_or_warn(project_dir, entries)
    return entries


def _append_or_warn(project_dir, entries):
    try:
        append_entries(project_dir, entries)
    except OSError as e:
        ids = [e_['fact_id'] for e_ in entries if e_.get('fact_id')]
        listed = ', '.join(ids[:20]) + (f' and {len(ids) - 20} more' if len(ids) > 20 else '')
        log(f'WARNING: {LOG_PATH} was not written ({e}); the ledger change stands, '
            f'but its {len(entries)} audit entr{"y" if len(entries) == 1 else "ies"} '
            f'{"were" if len(entries) != 1 else "was"} lost'
            + (f': {listed}' if listed else ''))


# ============================================================================
# The snapshot: catching edits made outside Storyforge
# ============================================================================

SNAPSHOT_FILE = '.audit-snapshot.csv'
#: Relative to the project root, for commit paths
SNAPSHOT_PATH = f'working/{SNAPSHOT_FILE}'

#: The writer named for a change found between the snapshot and the ledger
HAND_EDIT = 'hand-edit'


def snapshot_path(project_dir: str) -> str:
    return os.path.join(project_dir, 'working', SNAPSHOT_FILE)


def read_snapshot(project_dir: str) -> list[dict[str, str]] | None:
    """The ledger as the log last recorded it; None when there is none yet."""
    from storyforge.ledger import read_ledger
    path = snapshot_path(project_dir)
    return read_ledger(path) if os.path.isfile(path) else None


def write_snapshot(project_dir: str, rows: list[dict[str, str]]) -> None:
    """Record `rows` as what the log has seen. A failure is a WARNING: the
    next write then can't tell a hand edit from its own change, and says so
    by naming the file now."""
    from storyforge.ledger import write_ledger
    try:
        with _LOCK:
            write_ledger(snapshot_path(project_dir), rows)
    except (OSError, ValueError) as e:
        log(f'WARNING: {SNAPSHOT_PATH} was not written ({e}); an edit made to '
            f'reference/commitments.csv by hand before the next ledger write '
            f'will not be logged')


def log_hand_edits(project_dir: str, disk: list[dict[str, str]]) -> list[dict[str, str]]:
    """Log, as `command=hand-edit`, how the ledger on disk (`disk`) differs
    from the snapshot of the last logged write, then snapshot `disk`.

    Catches what no Storyforge writer saw: an edit by hand, or by a skill
    told to edit commitments.csv directly. With no snapshot yet (a project
    whose ledger predates the log) there is nothing to compare: `disk`
    becomes the snapshot and nothing is logged. Returns the entries.
    """
    snap = read_snapshot(project_dir)
    if snap is None:
        write_snapshot(project_dir, disk)
        return []
    entries = diff_entries(snap, disk, command=HAND_EDIT)
    for e in entries:
        # An added row's introduced_by is what the editor typed, not who wrote it
        e['command'] = HAND_EDIT
    if entries:
        _append_or_warn(project_dir, entries)
        write_snapshot(project_dir, disk)
    return entries


def read_log(project_dir: str) -> list[dict[str, str]]:
    """The log's entries; no log → []."""
    path = log_path(project_dir)
    if not os.path.isfile(path):
        return []
    with open(path, newline='', encoding='utf-8') as f:
        lines = f.read().split('\n')
    if not lines or not lines[0]:
        return []
    header = lines[0].rstrip('\r').split('|')
    return [dict(zip(header, line.rstrip('\r').split('|')))
            for line in lines[1:] if line.strip()]


# ============================================================================
# The digest
# ============================================================================

#: (key, label), in the order decision 2 surfaces them
TIERS = [
    ('fixed', 'Fixed facts'),
    ('relationship-knowledge', 'Relationship and knowledge'),
    ('physical', 'Physical state'),
    ('other', 'Other state facts'),
]


def tier_of(row: dict[str, str]) -> str:
    if (row.get('mutable') or '').strip() == 'fixed':
        return 'fixed'
    type_ = (row.get('type') or '').strip()
    if type_ in ('relationship', 'knowledge'):
        return 'relationship-knowledge'
    if type_ == 'physical':
        return 'physical'
    return 'other'


@dataclass
class Scope:
    """What `select` narrows to. Every given field narrows (AND)."""
    character: str | None = None
    scenes: tuple[str, str] | None = None
    thread: str | None = None
    act: str | None = None
    #: Every act at once, not the per-act default
    all_acts: bool = False
    #: Drop the `reviewed` blank / `status=binding` filter
    include_reviewed: bool = False
    #: Keep `origin=migrated` facts, left out by default
    include_migrated: bool = False

    def narrowed(self) -> bool:
        return bool(self.character or self.scenes or self.thread or self.act
                    or self.all_acts)


@dataclass
class Digest:
    facts: list[dict[str, str]] = field(default_factory=list)
    #: What the listing covers, for the heading
    title: str = ''
    #: The act the per-act default chose (None when another scope was given)
    act: str | None = None
    notes: list[str] = field(default_factory=list)
    #: act → unreviewed facts left after this digest (per-act default only)
    remaining: dict[str, int] = field(default_factory=dict)


def is_unreviewed(row: dict[str, str]) -> bool:
    return (row.get('status') == 'binding'
            and not (row.get('reviewed') or '').strip())


class ScopeError(ValueError):
    """A scope that names something that isn't there (an unknown scene)."""


def _read(project_dir, name):
    from storyforge.ledger import _read_rows
    return _read_rows(os.path.join(project_dir, 'reference', name))


def act_column(project_dir: str) -> str | None:
    """The scenes.csv column that holds acts: `act`, or `part` in a project
    without one (thornwall), or None when there is neither."""
    header, _ = _read(project_dir, 'scenes.csv')
    for column in ('act', 'part'):
        if column in header:
            return column
    return None


def scene_acts(project_dir: str, column: str | None = None) -> dict[str, str]:
    """Scene id → act (from `column`, default `act_column`); '' when blank."""
    column = column or act_column(project_dir)
    _, rows = _read(project_dir, 'scenes.csv')
    return {r.get('id', '').strip(): ((r.get(column) or '').strip() if column else '')
            for r in rows if r.get('id', '').strip()}


def thread_ids(project_dir: str) -> set[str]:
    """Thread ids in mice-threads.csv."""
    _, rows = _read(project_dir, 'mice-threads.csv')
    return {r.get('id', '').strip() for r in rows if r.get('id', '').strip()}


def resolve_character(project_dir: str, value: str) -> str:
    """The characters.csv id `value` names (id, name or alias).

    Raises:
        ScopeError: no character is named that.
    """
    from storyforge.enrich import load_alias_map
    path = os.path.join(project_dir, 'reference', 'characters.csv')
    found = load_alias_map(path).get(value.strip().lower()) if os.path.isfile(path) else None
    if not found:
        raise ScopeError(f'{value!r} is not a character id, name or alias in '
                         f'reference/characters.csv')
    return found


def thread_scenes(project_dir: str, thread: str) -> set[str]:
    """Scenes whose scene-intent `mice_threads` carries `thread` (an entry
    like `+inquiry:map-anomaly` carries `map-anomaly`)."""
    _, rows = _read(project_dir, 'scene-intent.csv')
    out = set()
    for r in rows:
        for entry in (r.get('mice_threads') or '').split(';'):
            name = entry.strip().lstrip('+-').split(':')[-1].strip()
            if name and name == thread:
                out.add(r.get('id', '').strip())
    return out


def select(rows: list[dict[str, str]], project_dir: str, scope: Scope,
           order: dict[str, int]) -> Digest:
    """The facts `scope` covers, in reading order (facts with no placed scene
    first: they hold from before scene 1).

    With no narrowing scope this is the per-act digest: the earliest act, in
    reading order, that has an unreviewed fact. Facts with no scene in
    `order` (backstory, a renamed scene) belong to the first digest, since
    they hold from before scene 1.

    Raises:
        ScopeError: a scope naming something that isn't there: a `--scenes`
            end that isn't a scene, an unknown character or thread, an act
            no scene has, or `--act` with no act column.
    """
    digest = Digest()
    pool = [r for r in rows if scope.include_reviewed or is_unreviewed(r)]
    if not scope.include_migrated:
        migrated = [r for r in pool if r.get('origin') == 'migrated']
        if migrated:
            digest.notes.append(
                f'{len(migrated)} migrated fact(s) left out (moved from knowledge.csv '
                f'and physical-states.csv, never extracted under the rubric); '
                f'--include-migrated shows them')
        pool = [r for r in pool if r.get('origin') != 'migrated']

    def pos(r):
        return order.get((r.get('scene_id') or '').strip(), -1)

    titles = []
    if scope.character:
        c = resolve_character(project_dir, scope.character)
        from storyforge.enrich import load_alias_map
        names = load_alias_map(os.path.join(project_dir, 'reference', 'characters.csv'))

        def knows(r):
            return c in [names.get(k.strip().lower(), k.strip())
                         for k in (r.get('known_by') or '').split(';')]
        pool = [r for r in pool if (r.get('subject') or '').strip() == c or knows(r)]
        titles.append(f'character {c}')
    if scope.scenes:
        a, b = scope.scenes
        for end in (a, b):
            if end not in order:
                raise ScopeError(f'{end!r} is not a scene in reference/scenes.csv')
        lo, hi = sorted((order[a], order[b]))
        pool = [r for r in pool if lo <= pos(r) <= hi]
        titles.append(f'scenes {a}..{b}' if a != b else f'scene {a}')
    if scope.thread:
        scenes = thread_scenes(project_dir, scope.thread)
        if not scenes and scope.thread not in thread_ids(project_dir):
            raise ScopeError(f'{scope.thread!r} is not a thread in '
                             f'reference/mice-threads.csv or scene-intent.csv')
        if not scenes:
            digest.notes.append(f'no scene in scene-intent.csv carries the thread '
                                f'{scope.thread!r}')
        pool = [r for r in pool if (r.get('scene_id') or '').strip() in scenes]
        titles.append(f'thread {scope.thread} (facts established in the '
                      f'{len(scenes)} scene(s) that carry it)')
    column = act_column(project_dir)
    if column == 'part':
        digest.notes.append('acts read from scenes.csv `part` (it has no `act` column)')
    acts = scene_acts(project_dir, column)

    def act_of(r):
        return acts.get((r.get('scene_id') or '').strip(), '')

    if scope.act:
        if column is None:
            raise ScopeError('reference/scenes.csv has no `act` or `part` column, '
                             'so there are no acts to scope to')
        known = sorted({a for a in acts.values() if a})
        if scope.act not in known:
            raise ScopeError(f'no scene in reference/scenes.csv has {column} '
                             f'{scope.act!r} ({column}s: {", ".join(known) or "none"})')
        pool = [r for r in pool if act_of(r) == scope.act]
        titles.append(f'act {scope.act}')
    elif not scope.narrowed() and column is None:
        digest.notes.append('reference/scenes.csv has no `act` or `part` column, so '
                            'the digest is not split per act: every unreviewed '
                            'fact is listed')
        titles.append('all acts')
    elif not scope.narrowed():
        placed = [r for r in pool if pos(r) >= 0]
        unplaced = [r for r in pool if pos(r) < 0]
        no_act = sorted({(r.get('scene_id') or '').strip() for r in placed
                         if not act_of(r)})
        if no_act:
            digest.notes.append(
                f'scenes with no act in scenes.csv ({", ".join(no_act[:5])}'
                f'{", ..." if len(no_act) > 5 else ""}), so the digest is not split '
                f'per act: every unreviewed fact is listed')
            titles.append('all acts')
        elif placed:
            first = min(placed, key=pos)
            digest.act = act_of(first)
            pool = unplaced + [r for r in placed if act_of(r) == digest.act]
            titles.append(f'act {digest.act}')
            for r in placed:
                if act_of(r) != digest.act:
                    digest.remaining[act_of(r)] = digest.remaining.get(act_of(r), 0) + 1
        elif unplaced:
            titles.append('facts with no scene')
    if scope.all_acts:
        titles.append('all acts')
    digest.title = ', '.join(titles) or 'every act'
    digest.facts = sorted(pool, key=pos)
    return digest


def group(facts: list[dict[str, str]]) -> list[dict]:
    """Tiers in `TIERS` order, each with its subjects (in order of their first
    fact) and their facts. Empty tiers are left out. A blank subject is
    `''`."""
    out = []
    for key, label in TIERS:
        in_tier = [r for r in facts if tier_of(r) == key]
        if not in_tier:
            continue
        subjects: dict[str, list] = {}
        for r in in_tier:
            subjects.setdefault((r.get('subject') or '').strip(), []).append(r)
        # A blank subject goes last: it is usually most knowledge facts
        names = sorted(subjects, key=lambda s: s == '')
        out.append({'tier': key, 'label': label,
                    'subjects': [{'subject': s, 'facts': subjects[s]} for s in names]})
    return out


# ============================================================================
# Marking (the audit)
# ============================================================================

VERDICTS = ('seen', 'rejected')


def mark(rows: list[dict[str, str]], ids: list[str], verdict: str, *,
         date: str | None = None) -> list[str]:
    """Set `reviewed` to `<verdict>:<date>` on `ids` (in place); `rejected`
    also sets `status=rejected`. Returns the ids changed.

    A fact already marked with `verdict` is left as it is (not re-dated).

    Raises:
        ValueError: an unknown verdict, an id not in the ledger, `seen` on
            a rejected fact (marking it seen would not make it binding again,
            and silently leaving it rejected would read as if it had), or
            `rejected` on a superseded fact (its status would have to stop
            saying it was replaced; reject its successor instead).
    """
    if verdict not in VERDICTS:
        raise ValueError(f'{verdict!r} is not one of {", ".join(VERDICTS)}')
    by_id = {r.get('id', ''): r for r in rows}
    missing = [i for i in ids if i not in by_id]
    if missing:
        raise ValueError(f'not in the ledger: {", ".join(missing)}')
    if verdict == 'seen':
        rejected = [i for i in ids if by_id[i].get('status') == 'rejected']
        if rejected:
            raise ValueError(f'already rejected: {", ".join(rejected)} (to restore a '
                             f'fact, set its status back to binding in '
                             f'reference/commitments.csv)')
    else:
        superseded = [i for i in ids if by_id[i].get('status') == 'superseded']
        if superseded:
            raise ValueError(
                f'superseded, so no longer binding: {", ".join(superseded)}. '
                f'Rejecting it would lose that a later fact replaced it; reject '
                f'the fact that superseded it, or mark this one seen')
    stamp = f'{verdict}:{date or datetime.now().strftime("%Y-%m-%d")}'
    changed = []
    for i in dict.fromkeys(ids):
        row = by_id[i]
        if (row.get('reviewed') or '').startswith(f'{verdict}:') and (
                verdict == 'seen' or row.get('status') == 'rejected'):
            continue   # already marked so: a re-mark is a no-op, not a new date
        before = (row.get('reviewed'), row.get('status'))
        row['reviewed'] = stamp
        if verdict == 'rejected':
            row['status'] = 'rejected'
        if (row.get('reviewed'), row.get('status')) != before:
            changed.append(i)
    return changed


def leaning_scenes(project_dir: str, ids: list[str]) -> dict[str, list[str]]:
    """fact id → scenes whose brief names it in knowledge_in/out or
    physical_state_in/out. What a rejected fact's scenes are until Phase 4's
    dependency graph (`depends_on`) exists."""
    _, briefs = _read(project_dir, 'scene-briefs.csv')
    wanted = set(ids)
    out: dict[str, list[str]] = {i: [] for i in ids}
    for b in briefs:
        for col in ('knowledge_in', 'knowledge_out', 'physical_state_in',
                    'physical_state_out'):
            for ref in (b.get(col) or '').split(';'):
                ref = ref.strip()
                if ref in wanted and b.get('id', '') not in out[ref]:
                    out[ref].append(b.get('id', '').strip())
    return out


# ============================================================================
# The immediate tier (Phase 3's gate calls this)
# ============================================================================

HALT_KINDS = ('supersedes-fixed', 'changes-fixed', 'low-confidence')


@dataclass(frozen=True)
class Halt:
    kind: str      # one of HALT_KINDS
    fact_id: str   # the proposed fact
    detail: str

    def __str__(self) -> str:
        return f'{self.fact_id}: {self.detail}'


def halting_conditions(proposed: list[dict[str, str]],
                       rows: list[dict[str, str]]) -> list[Halt]:
    """The conditions in `proposed` that stop the run in any mode (decision
    2's immediate tier), one `Halt` each; [] means none.

    - `supersedes-fixed`: a proposed fact's `supersedes` names a binding
      `fixed` fact.
    - `changes-fixed`: a proposed fact reuses a binding `fixed` fact's id with
      a different statement, subject or type (superseding it in place).
    - `low-confidence`: the proposal's `confidence` is `low`. Confidence lives
      on the proposal (extraction's output), not in the ledger: no column is
      added, and a fact that reaches the ledger has passed this check.

    The third trigger, a contradiction with the plan, needs extraction and
    the checker: the gate's checker reports it as a finding, which blocks
    the commit like a halt.
    """
    fixed = {r.get('id', ''): r for r in rows
             if r.get('status') == 'binding' and r.get('mutable') == 'fixed'}
    halts = []
    for p in proposed:
        pid = (p.get('id') or '').strip()
        for old in (s.strip() for s in (p.get('supersedes') or '').split(';')):
            if old in fixed:
                halts.append(Halt('supersedes-fixed', pid,
                                  f'supersedes the fixed fact {old} '
                                  f'({fixed[old].get("statement", "")!r})'))
        prev = fixed.get(pid)
        if prev is not None:
            diffs = [c for c in ('statement', 'subject', 'type')
                     if (p.get(c) or '').strip() != (prev.get(c) or '').strip()]
            if diffs:
                halts.append(Halt('changes-fixed', pid,
                                  f'changes the fixed fact\'s {", ".join(diffs)} '
                                  f'(was {prev.get("statement", "")!r})'))
        if (p.get('confidence') or '').strip().lower() == 'low':
            halts.append(Halt('low-confidence', pid,
                              f'extraction flagged it low-confidence: '
                              f'{p.get("statement", "")!r}'))
    return halts
