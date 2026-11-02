"""The gate: nothing commits to the ledger without a check (rethink plan §3.2).

For one scene's prose, `gate_scene` runs:

1. **Extract** the scene's commitments with phase 4's rubric
   (`extract.build_commitments_prompt`), offered the facts in force entering
   it and the registry facts recorded for it (`extract.known_for_scene`),
   then ask of each whether it lasts beyond the scene
   (`persistence.judge`): one that doesn't is not proposed (`dropped`,
   reported).
2. **Halt** on decision 2's immediate tier: `audit.halting_conditions` on the
   proposed rows (a `fixed` fact superseded or changed). The third trigger,
   a fact extraction flagged low-confidence, is not wired: phase 4's schema
   has no confidence yet (adding it re-records E3 and E5). A contradiction
   with the plan is the checker's to find (step 3), not extraction's
   (Ben, 2026-10-30): extraction marks added detail as superseding a
   registry fact, and a registry `resolves` is the author's estimate, so a
   `supersedes` or `ends` it proposes on a registry fact is not applied:
   it goes to the checker as a dispute to rule on (a contradiction, or
   cleared), and one it doesn't rule on blocks the commit.
3. **Check** the scene against the book and its brief (`checker.check_scene`):
   contradictions and broken promises, by code. `GATE_READINGS` (2)
   independent readings, their union: one reading misses about a fifth of
   what another finds, and a finding the first check missed would otherwise
   surface only on a re-check after the fix, blocking a scene the fix can
   no longer reach.
4. **Commit** only when nothing halted, extraction left nothing unresolved
   (`UNRESOLVED`: a quote not in the scene, a `supersedes` or `ends` that
   names nothing it can apply to), and the check found nothing, verified or
   not, other than contradictions already in the book before the pass
   (`gate_scene(before=)`: `inherited`, reported as `ALREADY IN THE SCENE`
   and kept in working/gate-reported.csv; the commitments stating them are
   held back): the
   scene's commitments replace its earlier ones (`introduced_by` = the
   command that wrote the prose), each registry fact the prose was found to
   establish gets its blank quote filled (`ledger.fill_quote`), and the
   ledger is saved through `ledger.save`, so the audit log has every fact.
5. **Re-check** (Phase 4, `docs/plans/2026-10-31-phase4-safe-revision-design.md`):
   a fact restated keeps its id; the later scenes depending on what the
   scene dropped or changed are listed `RECHECK`, and `recheck_pending`
   re-gates them in reading order (report and stop, under the cost
   threshold). The caller runs it once the scene is committed.

**Fix** (plan §3.2 step 3) is the caller's: a result that didn't pass names
what to fix. The caller must also report `result.problems`' report-only
kinds (`REPORTED`) and `result.inherited` on a pass (`report_lines` has both): they don't make the ledger wrong, but the
author should know. The design is `docs/plans/2026-10-30-gate-ledger-design.md`.

Fails loud: a step that can't finish raises `GateError`, and nothing is
written. A result that didn't pass writes nothing either; it is not an
exception, because the caller decides between fixing and reporting
(advisor mode).
"""

from __future__ import annotations

import copy
import os
import re
from dataclasses import dataclass, field

from storyforge import audit, ledger, persistence
from storyforge.checker import (GATE_READINGS, CheckError, CheckResult, Dispute, Finding,
                               check_scene)

#: The commands whose prose the gate commits (`ledger.COMMITMENT_WRITERS`
#: without the extract pass)
GATE_COMMANDS = tuple(w for w in ledger.COMMITMENT_WRITERS if w != ledger.COMMITMENTS_PASS)

#: Extraction problems that would commit a wrong row: they block the commit
UNRESOLVED = ('quote', 'no quote', 'supersedes', 'ends', 'ends again', 'rejected')
#: Extraction problems reported on a pass: a link extraction proposed to a
#: registry fact, not applied (`disagrees`, `ends registry`: the checker
#: judges contradictions with the plan), a subject not in the registries
#: (an object has none), facts left out past the offer cap, facts tied to a
#: scene id that isn't a scene
REPORTED = ('disagrees', 'ends registry', 'subject', 'cap', 'unplaced')


class GateError(RuntimeError):
    """A gate step couldn't finish; nothing was written. From `gate_and_fix`,
    `.first` is the first gate run when there was one."""
    first: 'GateResult | None' = None


def _among(f: Finding, findings: list[Finding]) -> bool:
    """Whether `f` is one of `findings`, by identity: `Finding` compares
    by value, and the classified lists hold the check's own objects."""
    return any(f is g for g in findings)


@dataclass
class GateResult:
    scene_id: str
    #: the scene's commitments, as they would be (or were) committed
    proposed: list[dict[str, str]] = field(default_factory=list)
    halts: list[audit.Halt] = field(default_factory=list)
    #: extraction's problems (`extract.COMMITMENT_PROBLEMS` → strings):
    #: `UNRESOLVED` block the commit; `disagrees` and `ends registry` go to
    #: the checker as disputes; the rest of `REPORTED` are for the caller
    problems: dict[str, list[str]] = field(default_factory=dict)
    check: CheckResult | None = None
    committed: bool = False
    #: registry ids whose quote was filled on commit
    quotes_filled: list[str] = field(default_factory=list)
    #: (statement, why) for each extracted fact the persistence check judged
    #: not to last beyond the scene: not proposed, so never committed
    dropped: list[tuple[str, str]] = field(default_factory=list)
    #: on commit (Phase 4): the scene's earlier commitments this version
    #: dropped or changed, and the earlier states whose end in this scene
    #: came or went
    changed: list[str] = field(default_factory=list)
    #: on commit: the later scenes, with prose, listed pending for a re-check
    #: because their facts depend on `changed` (`recheck_pending` runs it)
    recheck: list[str] = field(default_factory=list)
    #: on commit: changed fact id → why its dependents can't all be found
    #: (`ledger.Dependents.unrelated`), for the caller to report
    unrelated: dict[str, str] = field(default_factory=dict)
    #: on commit: later scenes depending on `changed` that can't be re-checked
    #: (`scene (why)`: no prose yet, cut or merged), for the caller to report
    not_rechecked: list[str] = field(default_factory=list)
    #: on commit: what narrowed the dependents' name match
    #: (`ledger.subject_names`' notes: a missing registry, no id column),
    #: for the caller to report
    name_notes: list[str] = field(default_factory=list)
    #: on commit: registry rows (the author's) whose `supersedes`/`depends_on`
    #: names a commitment this version removed (`row → id`): a re-check
    #: replaces only commitments, so the author must fix the link
    dangling: list[str] = field(default_factory=list)
    #: verified contradictions that were in the book before the pass that
    #: wrote this prose (`_classify`): the author's to fix, reported (and
    #: kept in working/gate-reported.csv on commit) but not blocking, and
    #: never sent to the fix. A subset of `check.findings`, set once
    inherited: list[Finding] = field(default_factory=list)
    #: verified contradictions in the brief's own scripted words
    #: (`_brief_phrases`, `_is_plan_conflict`): the brief and the book
    #: disagree, so no prose edit can deliver one without breaking the
    #: other. They block, and go to the author rather than the fix. A subset
    #: of `findings`, disjoint from `inherited`
    plan_conflicts: list[Finding] = field(default_factory=list)
    #: on commit: (statement, inherited finding) for each extracted
    #: commitment stating an inherited contradiction, not recorded
    #: (`_hold_back`)
    held_back: list[tuple[str, Finding]] = field(default_factory=list)

    @property
    def findings(self) -> list[Finding]:
        """The check's verified findings, less `inherited`."""
        if not self.check:
            return []
        return [f for f in self.check.findings if not _among(f, self.inherited)]

    @property
    def fixable(self) -> list[Finding]:
        """`findings` less `plan_conflicts`: the verified ones the fix is for."""
        return [f for f in self.findings if not _among(f, self.plan_conflicts)]

    @property
    def unverified(self) -> list[Finding]:
        """Findings whose quotes didn't hold up: not shown to be wrong, so
        they block the commit like any other finding."""
        return self.check.unverified if self.check else []

    @property
    def unresolved(self) -> list[str]:
        """Extraction problems that block the commit (`UNRESOLVED`)."""
        return [f'{kind}: {item}' for kind in UNRESOLVED
                for item in self.problems.get(kind, [])]

    @property
    def unruled(self) -> list[Dispute]:
        """Registry facts extraction said the scene changes that the checker
        neither ruled a contradiction nor cleared: they block the commit."""
        return self.check.unruled if self.check else []

    @property
    def passed(self) -> bool:
        return not (self.halts or self.unresolved or self.findings or self.unverified
                    or self.unruled)


def _subjects(project_dir: str) -> dict[str, str]:
    from storyforge.enrich import load_registry_alias_maps
    maps = load_registry_alias_maps(project_dir)
    return {**maps.get('locations', {}), **maps.get('characters', {})}


def _extract(project_dir: str, scene_id: str, prose: str, rows: list[dict[str, str]],
             order: dict[str, int], introduced_by: str, model: str, log_dir: str,
             problems: dict[str, list[str]],
             dropped: list[tuple[str, str]]) -> list[dict[str, str]]:
    from storyforge.api import extract_text, invoke_to_file, is_truncated
    from storyforge.elaborate import get_scene
    from storyforge.enrich import format_registries_for_prompt
    from storyforge.extract import (COMMITMENTS_SCHEMA, build_commitments_prompt,
                                    commitment_rows, known_for_scene,
                                    parse_commitments_response, unplaced_rows)
    ref_dir = os.path.join(project_dir, 'reference')
    scene = get_scene(scene_id, ref_dir) or {}
    subjects = _subjects(project_dir)
    names = [scene.get('pov', ''), scene.get('location', '')] + scene.get('on_stage', '').split(';')
    scene_subjects = {subjects[n.strip().lower()] for n in names if n.strip().lower() in subjects}
    known, recorded, left_out = known_for_scene(rows, scene_id, order, scene_subjects)
    if left_out:
        problems['cap'].append(f'{scene_id} ({left_out})')
    problems['unplaced'].extend(unplaced_rows(rows, order))
    prompt = build_commitments_prompt(
        scene_id, prose, {k: scene.get(k, '') for k in ('title', 'pov', 'location')},
        registries_text=format_registries_for_prompt(project_dir, exclude=('knowledge',)),
        known=known, recorded=recorded)
    log_file = os.path.join(log_dir, f'gate-extract-{scene_id}.json')
    try:
        response = invoke_to_file(prompt, model, log_file, 8000,
                                  output_schema=COMMITMENTS_SCHEMA, label=f'extract {scene_id}')
        if is_truncated(response):
            raise ValueError('the reply hit its token limit')
        found = parse_commitments_response(extract_text(response), scene_id)
    except (RuntimeError, ValueError) as e:   # RefusalError, an API failure, a bad reply
        raise GateError(f'{scene_id}: extraction failed: {e}') from e
    try:
        verdict = persistence.judge(scene_id, prose, found, model=model,
                                    log_file=os.path.join(log_dir,
                                                          f'gate-persistence-{scene_id}.json'))
    except persistence.PersistenceError as e:
        raise GateError(str(e)) from e
    dropped.extend((e['statement'], why) for e, why in verdict.dropped)
    return commitment_rows(verdict.kept, scene_id, prose, rows, known, recorded, subjects,
                           introduced_by, problems, own_writers=ledger.COMMITMENT_WRITERS,
                           registry_is_plan=True)


def _disputes(result: GateResult, rows: list[dict[str, str]]) -> list[Dispute]:
    """Each registry fact extraction says the scene changes, for the
    checker to rule on (Ben, 2026-10-30: the checker decides). From
    `commitment_rows`' problem strings: `disagrees` is `scene: registry-id
    (prose: proposed-id)`, `ends registry` is `scene: registry-id
    (resolves: ...)`."""
    import re
    proposed = {r['id']: r for r in result.proposed}
    out: dict[str, Dispute] = {}
    for item in result.problems.get('disagrees', []):
        m = re.match(r'[^:]+: (\S+) \(prose: (\S+)\)$', item)
        if not m:
            continue
        row = proposed.get(m.group(2), {})
        out.setdefault(m.group(1), Dispute(m.group(1), _statement(rows, m.group(1)),
                                           row.get('quote') or row.get('statement', '')))
    for item in result.problems.get('ends registry', []):
        m = re.match(r'[^:]+: (\S+) \(resolves: ([^)]*)\)$', item)
        if not m:
            continue
        out.setdefault(m.group(1), Dispute(
            m.group(1), _statement(rows, m.group(1)),
            f'the state ends in this scene (the plan says it ends at {m.group(2)})'))
    return list(out.values())


def _statement(rows: list[dict[str, str]], rid: str) -> str:
    return next((r.get('statement', '') for r in rows if r.get('id') == rid), '')


def _words(text: str) -> str:
    """`text` as lowercase words, one space apart, padded: a phrase is
    in it when `_words(phrase)` is a substring."""
    return ' ' + ' '.join(re.findall(r'\w+', text.lower())) + ' '


def _count(words: str) -> int:
    return len(words.split())


#: A quote matched against the scene before the pass needs this many words
#: in all, and each part (split at an ellipsis) `_MIN_PART_WORDS`: a short
#: one ("twelve", "the barn") turns up in old prose by accident (#480's review)
_MIN_QUOTE_WORDS = 4
_MIN_PART_WORDS = 3


def _quoted_in(quote: str, text: str) -> bool:
    """Whether `quote` is in `text`, ignoring case, punctuation and spacing:
    its parts (split at an ellipsis, as quotes are verified) in order, each
    of `_MIN_PART_WORDS` words or more and `_MIN_QUOTE_WORDS` in all. A
    shorter quote is never found: the safe answer, since a found quote
    makes a finding inherited."""
    parts = [_words(p) for p in re.split(r'\.\.\.|…', quote)]
    parts = [p for p in parts if p.strip()]
    if (not parts or sum(_count(p) for p in parts) < _MIN_QUOTE_WORDS
            or any(_count(p) < _MIN_PART_WORDS for p in parts)):
        return False
    words, at = _words(text), 0
    for p in parts:
        found = words.find(p, at)
        if found < 0:
            return False
        at = found + len(p) - 1   # the next part may start at this one's closing space
    return True


#: The fewest words a brief's own words must have to count as the source of
#: a contradiction: shorter ones ("Yes.") match by accident
_MIN_BRIEF_WORDS = 3


def _brief_phrases(project_dir: str, scene_id: str) -> list[str]:
    """The words the scene's brief scripts (`checker.PROMISE_FIELDS`), as
    phrases: each quoted span of an item, and a `key_dialogue` item that
    quotes nothing whole. An unquoted action or outcome is a paraphrase,
    not words the prose must use, so it isn't one. Phrases under
    `_MIN_BRIEF_WORDS` words are left out. A scene with no brief row
    scripts nothing."""
    from storyforge.checker import PROMISE_FIELDS, _split_cell
    from storyforge.elaborate import get_scene
    scene = get_scene(scene_id, os.path.join(project_dir, 'reference')) or {}
    phrases = []
    for col in PROMISE_FIELDS:
        for item in _split_cell(scene.get(col) or ''):
            quoted = re.findall(r'"([^"]+)"|“([^”]+)”', item)
            if quoted:
                phrases += [a or b for a, b in quoted]
            elif col == 'key_dialogue':
                phrases.append(item)
    return [p for p in phrases if _count(_words(p)) >= _MIN_BRIEF_WORDS]


def _is_plan_conflict(quote: str, phrases: list[str]) -> bool:
    """Whether a contradiction's `quote` is the brief's own words: the
    quote lies within a scripted phrase, or a scripted phrase makes up at
    least half of it (a short scripted line inside a long quote whose error
    is elsewhere is not one). A quote under `_MIN_BRIEF_WORDS` words is
    never one."""
    q = _words(quote)
    n = _count(q)
    if n < _MIN_BRIEF_WORDS:
        return False
    return any(q in p or (p in q and 2 * _count(p) >= n) for p in map(_words, phrases))


# ============================================================================
# The book before a pass: what an error already there is (Ben, 2026-11-01)
# ============================================================================

@dataclass
class Snapshot:
    """The book before a pass (`snapshot`): the baseline against which the
    gate tells an error the pass made from one already there (`inherited`)."""
    #: scene id → prose, for the scenes whose prose is a baseline: readable,
    #: and not waiting on the gate
    scenes: dict[str, str] = field(default_factory=dict)
    #: reference file name → sha1 of its bytes (None: two files share the name)
    files: dict[str, str | None] = field(default_factory=dict)
    #: scene id → why it isn't in `scenes`
    left_out: dict[str, str] = field(default_factory=dict)


def _sha1(path: str) -> str | None:
    import hashlib
    try:
        with open(path, 'rb') as f:
            return hashlib.sha1(f.read()).hexdigest()
    except OSError:
        return None


def snapshot(project_dir: str) -> Snapshot:
    """The book as it is now, taken before a command writes prose and
    passed to the gate as `before=`. Take it once per run: a scene the run
    rewrites before another is gated then counts as changed.

    A scene listed in working/gate-pending.csv is left out (#480's review):
    its prose didn't pass the gate or wasn't checked, so a retry that keeps
    its error must not pass it as inherited. With the list unreadable every
    scene is left out. A scene that isn't UTF-8 is left out too."""
    snap = Snapshot()
    try:
        waiting = pending(project_dir)
    except GateError as e:
        waiting, unreadable = None, str(e)
    scenes_dir = os.path.join(project_dir, 'scenes')
    names = sorted(os.listdir(scenes_dir)) if os.path.isdir(scenes_dir) else []
    for name in names:
        if not name.endswith('.md'):
            continue
        sid = name[:-3]
        if waiting is None:
            snap.left_out[sid] = f'the pending list is unreadable: {unreadable}'
            continue
        if sid in waiting:
            snap.left_out[sid] = f'waiting on the gate ({waiting[sid]["command"]})'
            continue
        try:
            with open(os.path.join(scenes_dir, name), encoding='utf-8') as f:
                snap.scenes[sid] = f.read()
        except (OSError, UnicodeDecodeError) as e:
            snap.left_out[sid] = f'unreadable ({type(e).__name__})'
    ref_dir = os.path.join(project_dir, 'reference')
    for root, _, files in os.walk(ref_dir):
        for name in files:
            digest = _sha1(os.path.join(root, name))
            snap.files[name] = None if name in snap.files else digest
    return snap


def _unchanged_since(project_dir: str, snap: Snapshot, source: str, scene_id: str,
                     established_quote: str) -> bool:
    """Whether the established side of a contradiction is as it was in
    `snap` (#480's review: a contradiction is new when either side changed).
    A scene other than this one: its file is unchanged. This scene: the
    established quote was in it. A reference file or the calendar: its
    bytes are unchanged. The ledger, or anything unknown: no."""
    source = (source or '').strip()
    if not source:
        return False
    if source == scene_id:
        return _quoted_in(established_quote, snap.scenes.get(scene_id, ''))
    if source in snap.scenes:
        try:
            with open(os.path.join(project_dir, 'scenes', f'{source}.md'),
                      encoding='utf-8') as f:
                return f.read() == snap.scenes[source]
        except (OSError, UnicodeDecodeError):
            return False
    old = snap.files.get(source)
    if old is None:
        return False
    found = [os.path.join(root, source) for root, _, files
             in os.walk(os.path.join(project_dir, 'reference')) if source in files]
    return len(found) == 1 and _sha1(found[0]) == old


def _classify(result: GateResult, project_dir: str, before: Snapshot | None,
              reported: list[dict[str, str]]) -> None:
    """Sort the check's verified contradictions into `inherited` and
    `plan_conflicts` (each set anew).

    Inherited: the error was in the book before this pass. Either its
    words (`_quoted_in`) were in the scene in `before` and its established
    side is unchanged since (`_unchanged_since`), or the author was already
    told of it (`reported`: the same source and quote, from
    working/gate-reported.csv). Inherited comes first: an error the pass
    didn't make doesn't stop it, whatever its source.

    Plan conflict: its words are the brief's own (`_is_plan_conflict`).

    Broken promises and unverified findings are neither."""
    result.inherited, result.plan_conflicts = [], []
    if not result.check:
        return
    old = before.scenes.get(result.scene_id) if before else None
    known = {(r['source'], _words(r['quote'])) for r in reported}
    phrases = None
    for f in result.check.findings:
        if f.kind != 'contradiction' or not f.scene_quote.strip():
            continue
        if ((f.established_scene or '', _words(f.scene_quote)) in known
                or (old is not None and _quoted_in(f.scene_quote, old)
                    and _unchanged_since(project_dir, before, f.established_scene,
                                         result.scene_id, f.established_quote))):
            result.inherited.append(f)
            continue
        if phrases is None:
            phrases = _brief_phrases(project_dir, result.scene_id)
        if _is_plan_conflict(f.scene_quote, phrases):
            result.plan_conflicts.append(f)


def _hold_back(result: GateResult) -> None:
    """Take out of `proposed` each commitment stating an inherited
    contradiction (its quote and the finding's overlap), so the ledger never
    records a fact the check showed contradicts the book (#480's review).
    They go to `held_back`, reported."""
    keep = []
    for row in result.proposed:
        quote = _words(row.get('quote') or '')
        hit = next((f for f in result.inherited if _count(quote) >= _MIN_BRIEF_WORDS
                    and (quote in _words(f.scene_quote) or _words(f.scene_quote) in quote)),
                   None)
        if hit is None:
            keep.append(row)
        else:
            result.held_back.append((row.get('statement', ''), hit))
    result.proposed = keep


def has_commitments(project_dir: str, scene_id: str) -> bool:
    """Whether the ledger holds commitments from `scene_id`'s prose."""
    return any(ledger.is_commitment(r) and (r.get('scene_id') or '').strip() == scene_id
               for r in ledger.load(project_dir))


def gate_scene(project_dir: str, scene_id: str, *, command: str, prose: str | None = None,
               log_dir: str, extract_model: str | None = None,
               check_model: str | None = None,
               introduced_by: str | None = None,
               before: Snapshot | None = None) -> GateResult:
    """Extract, halt, check and (if all clear) commit `scene_id`'s prose:
    `prose`, or the scene file when None. `command` is the command that
    wrote the prose (one of `GATE_COMMANDS`), recorded as the new rows'
    `introduced_by` and as the audit log's command.

    A redraft is extracted and checked against the ledger without its
    earlier version's commitments, and the `resolves` that version set on
    earlier commitments are cleared (this version's `ends` set them again).
    A `resolves` it set on a registry state isn't touched: the gate never
    sets one there. `introduced_by` (default `command`) is what the new rows
    record; a re-check keeps the prose's writer.

    `before` is the book before the pass that wrote `prose` (`snapshot`;
    None: a new scene, a re-check, or advisor mode). A contradiction that
    was already there is `inherited`: reported, not blocking (Ben,
    2026-11-01: a pass doesn't stop on an error it didn't make), and so is
    one already in working/gate-reported.csv, whatever the command; the
    commitments stating one aren't recorded (`held_back`). On commit the
    scene's rows in that file are replaced by this run's inherited
    findings. A contradiction in the brief's own words is a
    `plan_conflict` (`_classify`).

    On commit (Phase 4, `docs/plans/2026-10-31-phase4-safe-revision-design.md`):
    a new commitment stating the same fact as an earlier one of the scene
    (`ledger.fact_key`) keeps its id, and a later scene's end of it, so
    links to it hold. The earlier commitments with no such match, and the
    earlier states whose end in this scene came or went, are `changed`;
    the later scenes whose facts depend on them (`ledger.dependents`) and
    have prose are listed in `working/gate-pending.csv` as `recheck`
    (`recheck_pending` re-gates them). A fact new to the scene doesn't list
    anything: its own check already reads it against the later scenes.

    Raises:
        GateError: a step couldn't finish (extraction or the check failed,
            the scene has no prose, or the ledger changed on disk
            while the gate ran); nothing was written.
        ValueError: `command` isn't one of `GATE_COMMANDS`.
    """
    from storyforge.common import select_model
    from storyforge.extract import COMMITMENT_PROBLEMS
    if command not in GATE_COMMANDS:
        raise ValueError(f'command must be one of {", ".join(GATE_COMMANDS)}, not {command!r}')
    if prose is None:
        path = os.path.join(project_dir, 'scenes', f'{scene_id}.md')
        try:
            with open(path, encoding='utf-8') as f:
                prose = f.read()
        except OSError as e:
            raise GateError(f'{scene_id}: no prose to gate ({e})') from e
    if not prose.strip():
        raise GateError(f'{scene_id}: no prose to gate (the scene is empty)')
    if prose.lstrip().startswith('---\n'):
        raise GateError(f'{scene_id}: the scene starts with frontmatter; scene files are '
                        f'pure prose (`storyforge cleanup` strips it)')
    try:
        rows = ledger.load(project_dir)
        order = ledger.scene_order(project_dir)
        # read before the model calls: a commit needs both
        names, name_notes = ledger.subject_names(project_dir)
        revised_rejection = rejected_ids(pending(project_dir).get(scene_id))
        already_reported = reported(project_dir).get(scene_id, [])
    except (ledger.LedgerError, ValueError, OSError, UnicodeDecodeError) as e:
        raise GateError(f'{scene_id}: {e}') from e
    loaded = copy.deepcopy(rows)
    if scene_id not in order:
        raise GateError(f'{scene_id} is not a scene in reference/scenes.csv')

    # The scene's earlier commitments (a redraft's) aren't offered back to it
    # and are replaced on commit; what leans on them is re-checked (Phase 4)
    # (binding ones: a rejected commitment stays, the record of the
    # author's decision, and prose restating it is a problem below)
    old_rows = [copy.deepcopy(r) for r in rows if ledger.is_commitment(r)
                and r.get('status') == 'binding'
                and (r.get('scene_id') or '').strip() == scene_id]
    rejected_here = {ledger.fact_key(r): r['id'] for r in rows
                     if r.get('status') == 'rejected'
                     and (r.get('scene_id') or '').strip() == scene_id}
    old = {r['id'] for r in old_rows}
    ended_before = ledger.ended_by(rows, scene_id)
    rows = [r for r in rows if r['id'] not in old]
    # ... and the ends the earlier version set: this version's extraction
    # sets its own
    for r in rows:
        if ledger.is_commitment(r) and (r.get('resolves') or '').strip() == scene_id:
            r['resolves'] = ''

    result = GateResult(scene_id, problems={k: [] for k in COMMITMENT_PROBLEMS + ('rejected',)})
    result.proposed = _extract(project_dir, scene_id, prose, rows, order,
                               introduced_by or command,
                               extract_model or select_model('evaluation'), log_dir,
                               result.problems, result.dropped)
    # A fact the author rejected may not come back as binding
    for r in result.proposed:
        rid = rejected_here.get(ledger.fact_key(r))
        if rid:
            result.problems['rejected'].append(
                f'{scene_id}: "{r.get("quote") or r.get("statement")}" restates {rid}, '
                f'which the author rejected')
        result.halts = audit.halting_conditions(result.proposed, rows)
    try:
        result.check = check_scene(project_dir, scene_id, prose=prose, model=check_model,
                                   log_file=os.path.join(log_dir, f'gate-check-{scene_id}.json'),
                                   rows=rows, disputes=_disputes(result, rows),
                                   readings=GATE_READINGS)
    except CheckError as e:
        error = GateError(str(e))
        error.run = getattr(e, 'run', None)
        raise error from e
    _classify(result, project_dir, before, already_reported)
    if not result.passed:
        return result

    # The model calls take minutes: a ledger changed meanwhile would be
    # overwritten, and its change logged under this command
    try:
        if ledger.load(project_dir) != loaded:
            raise GateError(f'{scene_id}: reference/commitments.csv changed while the '
                            f'scene was being gated; nothing written, gate it again')
    except ledger.LedgerError as e:
        raise GateError(f'{scene_id}: {e}') from e
    _hold_back(result)
    _carry_ids(result.proposed, old_rows, rows, scene_id)
    new = rows + result.proposed
    for rid, quote in result.check.kept:
        if ledger.fill_quote(new, rid, quote):
            result.quotes_filled.append(rid)
    # the old side only: a fact new to the scene lists nothing
    new_keys = {ledger._fact_key(r) for r in result.proposed}
    result.changed = [r['id'] for r in old_rows if ledger._fact_key(r) not in new_keys]
    result.changed += sorted(ended_before ^ ledger.ended_by(new, scene_id))
    result.changed += [i for i in revised_rejection if i not in result.changed]
    if result.changed:
        found = ledger.dependents(old_rows + new, result.changed, order, names=names)
        result.unrelated = found.unrelated
        result.name_notes = name_notes
        # a rejected fact's re-check also reaches the scenes whose brief
        # names it, as `audit --mark rejected` tells the author it will
        briefs = audit.leaning_scenes(project_dir, revised_rejection) if revised_rejection else {}
        named = {b for v in briefs.values() for b in v}
        # only what follows the scene can depend on how the scene changed
        later = sorted({s for s in set(found.scenes) | named
                        if s in order and order[s] > order[scene_id]}, key=order.get)
        gone = _gone_scenes(project_dir)
        result.recheck = [s for s in later if s not in gone and _has_prose(project_dir, s)]
        result.not_rechecked = [f'{s} ({"cut or merged" if s in gone else "no prose yet"})'
                                for s in later if s not in result.recheck]
        result.not_rechecked += [f'{s} (its brief names a rejected fact, but it is not in '
                                 f'scenes.csv)' for s in sorted(named - set(order))]
        removed = set(result.changed) - {r['id'] for r in result.proposed}
        result.dangling = [f'{r["id"]} → {ref}' for r in rows if not ledger.is_commitment(r)
                           for col in ('supersedes', 'depends_on')
                           for ref in ledger._split(r.get(col, '')) if ref in removed]
    ledger.save(project_dir, new, command=command)
    result.committed = True
    try:
        record_reported(project_dir, scene_id, command, result.inherited)
    except GateError as e:   # the ledger is written; the findings were logged
        from storyforge.common import log
        log(f'WARNING: {scene_id} passed, but {REPORTED_PATH} could not be updated: {e}. '
            f'Its contradictions already in the scene are only in this log.')
    try:
        clear_pending(project_dir, scene_id)
        waiting = pending(project_dir)
        for sid in result.recheck:
            if sid not in waiting:   # one waiting for another reason stays as it is
                mark_pending(project_dir, sid, RECHECK,
                             f're-check: {scene_id} changed {len(result.changed)} fact(s) '
                             f'its facts depend on')
    except GateError as e:   # the ledger is written; say why the list wasn't updated
        from storyforge.common import log
        log(f'WARNING: {scene_id} passed, but {PENDING_PATH} could not be updated: {e}. '
            f'Fix it by hand: remove {scene_id}\'s row'
            + (f' and add {", ".join(result.recheck)} for a re-check' if result.recheck else '')
            + '.')
    return result


def _gone_scenes(project_dir: str) -> set[str]:
    from storyforge.elaborate import get_scenes
    from storyforge.prompts import _GONE
    return {r['id'] for r in get_scenes(os.path.join(project_dir, 'reference'))
            if (r.get('status') or '').strip().lower() in _GONE}


def _has_prose(project_dir: str, scene_id: str) -> bool:
    path = os.path.join(project_dir, 'scenes', f'{scene_id}.md')
    try:
        with open(path, encoding='utf-8') as f:
            return bool(f.read().strip())
    except OSError:
        return False


def _carry_ids(proposed: list[dict[str, str]], old_rows: list[dict[str, str]],
               rows: list[dict[str, str]], scene_id: str) -> None:
    """Give each proposed row that states the same fact as one of the
    scene's earlier commitments (`ledger.fact_key`) that row's id, and its
    end in a later scene when the new row has none: links to it (a later
    `supersedes`, the later scene's end) keep holding. Every other proposed
    row gets an id no other row and no earlier commitment of the scene has
    (extraction chose ids without the old rows, so one may repeat an old id:
    a later link to that id would then land on a different fact), and links
    between proposed rows follow the renames. In place."""
    from storyforge.extract import commitment_id
    by_key: dict[tuple, dict[str, str]] = {}
    for o in old_rows:
        by_key.setdefault(ledger.fact_key(o), o)
    rename: dict[str, str] = {}
    carried: set[str] = set()
    for p in proposed:
        o = by_key.get(ledger.fact_key(p))
        if o is None or o['id'] in carried:
            continue
        carried.add(o['id'])
        rename[p['id']] = o['id']
        if not (p.get('resolves') or '').strip() and ledger._ends_elsewhere(o):
            p['resolves'] = o['resolves']
    # an old id not carried is never reused: links to it must not land on
    # a different fact
    taken = {r['id'] for r in rows} | {o['id'] for o in old_rows}
    for p in proposed:
        if p['id'] in rename:
            p['id'] = rename[p['id']]
        elif p['id'] in taken:
            new_id = commitment_id(scene_id, p.get('statement', ''), taken)
            rename[p['id']] = new_id
            p['id'] = new_id
        taken.add(p['id'])
    for p in proposed:
        for col in ('supersedes', 'depends_on'):
            refs = ledger._split(p.get(col, ''))
            if any(r in rename for r in refs):
                p[col] = ';'.join(rename.get(r, r) for r in refs)


# ============================================================================
# Fix (plan §3.2 step 3): targeted edits and a re-check, up to FIX_ROUNDS times
# ============================================================================

FIX_SCHEMA = {
    'type': 'object',
    'properties': {'edits': {'type': 'array', 'items': {
        'type': 'object',
        'properties': {'problem': {'type': 'integer'}, 'find': {'type': 'string'},
                       'replace': {'type': 'string'}},
        'required': ['problem', 'find', 'replace'],
        'additionalProperties': False,
    }}},
    'required': ['edits'],
    'additionalProperties': False,
}


def problems_to_fix(result: GateResult) -> list[str]:
    """What a fix should address, one line each: halts (with the scene's
    words that set the fact), contradictions and broken promises, and
    unverified findings, marked as such with why their quotes failed. An
    extraction problem isn't a prose problem, so it isn't here: the re-check
    extracts again. Neither is a plan conflict (the brief's own words: an
    edit would break the promise) or an inherited contradiction (the
    author's, from before the pass)."""
    proposed = {r['id']: r for r in result.proposed}
    lines = []
    for h in result.halts:
        row = proposed.get(h.fact_id)
        said = (f' The scene says: "{row.get("quote") or row.get("statement")}".'
                if row else '')
        lines.append(f'The scene changes something the book fixed: {h.detail}.{said}')
    for item in result.problems.get('rejected', []):
        lines.append(f'The scene restates a fact the author rejected; change or remove it: '
                     f'{item}')
    for d in result.unruled:
        lines.append(f'UNVERIFIED (extraction thinks the scene changes this; the check gave no '
                     f'ruling; edit only if the scene clearly contradicts it): the plan records '
                     f'"{d.statement}", and the scene says "{d.claim}".')
    for f, unverified in ([(f, False) for f in result.fixable]
                          + [(f, True) for f in result.unverified]):
        tag = (f'UNVERIFIED (the check\'s quotes did not hold up: {f.problem}; edit only '
               f'if the scene clearly contradicts the book) ' if unverified else '')
        if f.kind == 'contradiction':
            lines.append(f'{tag}{f.code} contradiction: the scene says "{f.scene_quote}", '
                         f'but {f.source} establishes "{f.established_quote}". {f.explanation}')
        else:
            lines.append(f'{tag}Broken promise ({f.fact_id}): the brief promises '
                         f'"{f.established_quote}". {f.explanation}'
                         + (f' Nearest words: "{f.scene_quote}".' if f.scene_quote else ''))
    return lines


#: How many times `gate_and_fix` re-gates a scene that still fails (after a
#: fix, or for a first run failing only on extraction, a re-roll with no
#: edit). A second round sees what the first changed: one fix often moves a
#: wrong value to another wrong one ("eight days" to "five") or fixes half a
#: pronoun.
FIX_ROUNDS = 2


@dataclass
class FixRound:
    """One fix `gate_and_fix` made: the problems it was sent and its edits."""
    problems: list[str]
    edits: list[dict]


def build_fix_prompt(scene_id: str, prose: str, problems: list[str],
                     protected: list[str] | tuple = (),
                     earlier: list[FixRound] | tuple = ()) -> str:
    """The fix's prompt. `protected`: the brief's own words in the scene
    (`_brief_phrases`), which an edit must leave as they are. `earlier`: the
    fixes already made to this prose, which the check still failed."""
    listing = '\n'.join(f'{n}. {p}' for n, p in enumerate(problems, start=1))
    keep = ''
    if protected:
        keep = ('\n## Lines the brief scripts\n\nThe scene must keep these words exactly; '
                'no edit may change or remove them:\n\n'
                + '\n'.join(f'- "{p}"' for p in protected) + '\n')
    tried = ''
    if earlier:
        parts = []
        for r in earlier:
            parts.append('Problems sent:\n' + '\n'.join(f'- {p}' for p in r.problems))
            parts.append('Edits made:\n' + ('\n'.join(
                f'- "{e.get("find", "")}" became "{e.get("replace", "")}"' for e in r.edits)
                or '- none'))
        tried = ('\n## Earlier fixes\n\nThe scene below already has these edits, and the '
                 'check still found the problems above. Keep what an earlier edit fixed. '
                 'Where an earlier edit put in a value that is still wrong, don\'t guess '
                 'again: take the value the problem quotes from the book, or remove the '
                 'detail. Where it changed only part of something (one pronoun of several, '
                 'one mention of a name), change the rest.\n\n' + '\n\n'.join(parts) + '\n')
    return f"""A continuity check found these problems in scene {scene_id}. Fix each with the smallest edit to the scene's prose that resolves it.

## Problems

{listing}
{keep}{tried}
## Rules

- Change the scene so it agrees with what the book established; never assume the established fact is the one that is wrong. A problem marked UNVERIFIED may be the check's mistake: edit for it only if the scene clearly contradicts the book.
- Take the book's value, never a new one. When a name, number, age, date, duration, place or relationship is wrong, use the one the problem quotes from the book. If the problem doesn't say what the right value is, remove the detail or make it vague ("years ago", "a neighbour") instead of choosing another: any new specific you invent is one more thing that can contradict the book.
- Fix the scene's words, not the book's people: don't rename a character, change who someone is, or move an event to make a contradiction go away.
- A broken promise: add or change the fewest words that deliver it, in the scene's voice, where it fits the action.
- Each edit replaces `find`, words copied exactly from the scene that occur in it once, with `replace`. Keep `find` short: the sentence or clause that changes. Edits must not overlap.
- Change nothing else: no polishing, no other improvements. `problem` is the number of the problem the edit fixes.
- If a problem is a false alarm (the scene does not actually contradict anything), make no edit for it.

## Scene {scene_id}

{prose}"""


def apply_edits(prose: str, edits: list[dict]) -> str:
    """`prose` with each edit's `find` (exactly once in `prose`) replaced.

    Raises:
        GateError: a `find` is missing, occurs more than once, or overlaps
            another edit's; nothing is applied then.
    """
    spans = []
    for e in edits:
        find = (e.get('find') or '').replace('\r\n', '\n')
        if '\r\n' in prose:
            find = find.replace('\n', '\r\n')
        count = prose.count(find) if find else 0
        if count != 1:
            raise GateError(f'a fix edit\'s text occurs {count} times in the scene: '
                            f'{find[:80]!r}')
        start = prose.index(find)
        spans.append((start, start + len(find), e.get('replace') or ''))
    spans.sort()
    for (_, end, _), (start, _, _) in zip(spans, spans[1:]):
        if start < end:
            raise GateError('two fix edits overlap')
    for start, end, replace in reversed(spans):
        prose = prose[:start] + replace + prose[end:]
    return prose


def fix_scene(scene_id: str, prose: str, result: GateResult, *, log_dir: str,
              model: str | None = None, protected: list[str] | tuple = (),
              earlier: list[FixRound] | tuple = (),
              edits_out: list[dict] | None = None) -> str:
    """The scene with targeted edits for `result`'s problems (one model call).
    `earlier`: the fixes already made (`build_fix_prompt`). The edits applied
    are appended to `edits_out` when it is given (only once they all applied;
    nothing when there was nothing to fix).

    Raises:
        GateError: the call failed, the reply was cut off or not the schema,
            or an edit can't be applied (`apply_edits`).
    """
    import json
    from storyforge.api import extract_text, invoke_to_file, is_truncated
    from storyforge.common import select_model
    problems = problems_to_fix(result)
    if not problems:
        return prose
    log_file = os.path.join(log_dir, f'gate-fix-{scene_id}.json')
    try:
        response = invoke_to_file(build_fix_prompt(scene_id, prose, problems, protected,
                                                   earlier),
                                  model or select_model('revision'), log_file, 8000,
                                  output_schema=FIX_SCHEMA, label=f'fix {scene_id}')
        if is_truncated(response):
            raise ValueError('the reply hit its token limit')
        edits = json.loads(extract_text(response))['edits']
    except (RuntimeError, ValueError, KeyError, TypeError) as e:
        raise GateError(f'{scene_id}: the fix failed: {e}') from e
    fixed = apply_edits(prose, edits)
    if edits_out is not None:
        edits_out.extend(edits)
    return fixed


@dataclass
class GatedScene:
    """`gate_and_fix`'s answer: the prose to keep and the gate's last word."""
    prose: str
    result: GateResult          # the last gate run kept (a re-check when there was one)
    first: GateResult           # the first gate run
    # whether .prose differs from the prose given (the caller writes .prose
    # only then); not `bool(rounds)`: a later fix can undo an earlier one
    fixed: bool = False
    rounds: list[FixRound] = field(default_factory=list)  # the fixes kept, in order
    #: later rounds discarded, and why (their prose and verdict are not what's
    #: kept): the caller logs these
    notes: list[str] = field(default_factory=list)


def _blocking_count(result: GateResult) -> int:
    return len(blocking_lines(report_lines(result)))


def _undone_edit(earlier: list[FixRound] | tuple, before: str, after: str) -> str | None:
    """The `find` of an earlier fix's edit that a later fix put back: words the
    earlier edit removed, absent from `before`, present again in `after`."""
    for r in earlier:
        for e in r.edits:
            find, replace = e.get('find') or '', e.get('replace') or ''
            if find and find not in replace and find not in before and find in after:
                return find
    return None


def gate_and_fix(project_dir: str, scene_id: str, *, command: str, prose: str,
                 log_dir: str, extract_model: str | None = None,
                 check_model: str | None = None, fix_model: str | None = None,
                 before: Snapshot | None = None) -> GatedScene:
    """Gate `prose`; while it doesn't pass, fix it and gate the fixed prose,
    at most `FIX_ROUNDS` times (plan §3.2 step 3). Each fix after the first is
    sent the earlier fixes' problems and edits (`rounds`, `build_fix_prompt`).

    - A first run that fails only on extraction problems (nothing for the fix)
      is re-gated without an edit: extraction runs again. That re-gate counts
      as a round; a later run with nothing for the fix stops.
    - A run with plan conflicts and nothing for the fix (extraction problems
      or not) is neither fixed nor re-gated: they are the author's (the brief
      disagrees with the book), and a re-roll that missed one would pass
      prose that has it.
    - `before` (the book before the pass, `snapshot`) goes to every run
      (`gate_scene`): an inherited contradiction doesn't block any of them.
    - A fix that changes nothing (every problem judged a false alarm) is not
      re-gated: the last verdict stands, and a re-roll of the same prose
      won't overturn it.
    - A later round never leaves things worse than the round before it: its
      fix is discarded, and the earlier prose and verdict kept, when it
      fails (`GateError`), puts back words an earlier fix removed (checked
      before its gate run, which would commit on a lucky pass), or leaves
      more blocking problems. Each discard is in `.notes`.
    - Otherwise the prose kept is the last gated, with that run's verdict.

    The caller must write `.prose` to the scene file at once, whether or not
    `.result.passed`: when it passed, the ledger was already committed with
    quotes from that prose.

    Raises:
        GateError: from the first gate run, the first fix or its re-gate; it
            carries the first run as `.first` (None when the first run itself
            failed), so its findings can still be reported.
    """
    os.makedirs(log_dir, exist_ok=True)
    first = gate_scene(project_dir, scene_id, command=command, prose=prose, log_dir=log_dir,
                       extract_model=extract_model, check_model=check_model, before=before)
    current, result, rounds, notes, run_dir = prose, first, [], [], log_dir
    try:
        for n in range(1, FIX_ROUNDS + 1):
            if result.passed:
                break
            to_fix = problems_to_fix(result)
            if not to_fix and (result.plan_conflicts or n > 1):
                break
            kept = 'the prose and verdict before it'
            # the brief's own words the scene has: the fix must keep them
            protected = [p for p in _brief_phrases(project_dir, scene_id)
                         if _quoted_in(p, current)]
            edits: list[dict] = []
            try:
                fixed = fix_scene(scene_id, current, result, log_dir=run_dir,
                                  model=fix_model, protected=protected,
                                  earlier=tuple(rounds), edits_out=edits)
            except GateError as e:
                if n == 1:
                    raise
                notes.append(f'fix round {n} failed ({e}); kept {kept}')
                break
            if to_fix and fixed == current:
                break
            undone = _undone_edit(rounds, current, fixed) if n > 1 else None
            if undone:
                notes.append(f'fix round {n} put back words an earlier fix removed '
                             f'("{_one_line(undone)[:80]}"); kept {kept}')
                break
            # each run's log (and the fix that read it) in its own directory:
            # log_dir, log_dir/recheck, log_dir/recheck-2
            next_dir = os.path.join(log_dir, 'recheck' if n == 1 else f'recheck-{n}')
            try:
                again = gate_scene(project_dir, scene_id, command=command, prose=fixed,
                                   log_dir=next_dir, extract_model=extract_model,
                                   check_model=check_model, before=before)
            except GateError as e:
                if n == 1:
                    raise
                notes.append(f'the check after fix round {n} failed ({e}); kept {kept}')
                break
            if n > 1 and not again.passed and _blocking_count(again) > _blocking_count(result):
                notes.append(f'fix round {n} left {_blocking_count(again)} problem(s), more '
                             f'than the {_blocking_count(result)} before it; kept {kept}')
                break
            if fixed != current:
                rounds.append(FixRound(to_fix, edits))
            current, result, run_dir = fixed, again, next_dir
    except GateError as e:
        e.first = first
        raise
    return GatedScene(current, result, first, fixed=current != prose, rounds=rounds,
                      notes=notes)


def _one_line(text: str) -> str:
    return ' '.join(str(text).split())


#: `report_lines`' prefixes for what is reported either way, not what
#: stopped the commit
_NOT_BLOCKING = ('NOTE', 'COMMITTED', 'ALREADY IN THE SCENE')


def blocking_lines(lines: list[str]) -> list[str]:
    """The `report_lines` that name what stopped the commit."""
    return [line for line in lines if not line.startswith(_NOT_BLOCKING)]


def report_lines(result: GateResult) -> list[str]:
    """The gate's verdict on a scene as one-line strings (log lines, list
    items): everything that stopped the commit, then what is reported
    either way, then what was committed."""
    lines = []
    for h in result.halts:
        lines.append(f'HALT ({h.kind}): {_one_line(h)}')
    for item in result.unresolved:
        lines.append(f'EXTRACTION: {_one_line(item)}')
    for f in result.findings:
        if _among(f, result.plan_conflicts):
            lines.append(f'PLAN CONFLICT (the brief\'s own words contradict the book; fix the '
                         f'brief or {f.source}): {_one_line(f.message())}')
        else:
            lines.append(f'{f.kind.upper()}: {_one_line(f.message())}')
    for f in result.unverified:
        lines.append(f'UNVERIFIED ({f.problem}): {_one_line(f.message())}')
    for d in result.unruled:
        lines.append(f'UNRULED: the scene may change the plan\'s {d.fact_id} '
                     f'("{_one_line(d.statement)}"): "{_one_line(d.claim)}"; the check gave '
                     f'no ruling')
    for f in result.inherited:
        lines.append(f'ALREADY IN THE SCENE (before this pass, or reported before; not '
                     f'blocking, the author\'s to fix; listed in {REPORTED_PATH} on commit): '
                     f'{_one_line(f.message())}')
    if result.held_back:
        lines.append('NOTE (not recorded: states a contradiction already in the scene): '
                     + '; '.join(_one_line(st) for st, _ in result.held_back))
    if result.check:
        for d in result.check.cleared:
            lines.append(f'NOTE (plan fact kept, link not applied; the check found no '
                         f'contradiction): {d.fact_id} ("{_one_line(d.statement)}") vs '
                         f'"{_one_line(d.claim)}"')
    for kind in REPORTED:
        if kind in ('disagrees', 'ends registry'):
            continue    # every one is a dispute: a finding, UNRULED or the note above
        items = result.problems.get(kind, [])
        if items:
            lines.append(f'NOTE ({kind}): ' + '; '.join(_one_line(i) for i in items[:20])
                         + (' ...' if len(items) > 20 else ''))
    if result.check:
        for rid, quote, why in result.check.kept_unverified:
            lines.append(f'NOTE (kept, not filled): {rid}: {why}')
        if result.check.unknown_brief_items:
            lines.append('NOTE (brief items in words, no ledger fact; checked as words): '
                         + _one_line('; '.join(result.check.unknown_brief_items)))
        if result.check.stale_brief_items:
            lines.append('NOTE (brief items naming a fact that is not binding; not checked, '
                         'fix the brief): ' + _one_line('; '.join(result.check.stale_brief_items)))
    if result.dropped:
        lines.append(f'NOTE (not recorded, judged not to last beyond the scene): '
                     + '; '.join(f'{_one_line(st)} ({_one_line(why)})'
                                 for st, why in result.dropped[:20])
                     + (' ...' if len(result.dropped) > 20 else ''))
    if result.committed:
        lines.append(f'COMMITTED: {len(result.proposed)} fact(s)'
                     + (f'; quotes filled: {", ".join(result.quotes_filled)}'
                        if result.quotes_filled else ''))
    return lines


# ============================================================================
# Scenes waiting on the gate: working/gate-pending.csv
# ============================================================================

#: Scenes whose prose is on disk but didn't pass the gate, so their facts
#: aren't in the ledger. `write` won't draft a scene after one (it would be
#: drafted from an incomplete ledger); a pass, through `write` or
#: `storyforge check`, takes it off.
PENDING_PATH = 'working/gate-pending.csv'
_PENDING_COLUMNS = ['scene_id', 'command', 'reason']


def _pending_file(project_dir: str) -> str:
    return os.path.join(project_dir, PENDING_PATH)


def pending(project_dir: str) -> dict[str, dict[str, str]]:
    """Scene id → {scene_id, command, reason} for each scene waiting on the gate."""
    path = _pending_file(project_dir)
    if not os.path.isfile(path):
        return {}
    with open(path, encoding='utf-8') as f:
        lines = [line.rstrip('\n') for line in f if line.strip()]
    if not lines or lines[0].split('|') != _PENDING_COLUMNS:
        raise GateError(f'{PENDING_PATH}: the header must be {"|".join(_PENDING_COLUMNS)}')
    out = {}
    for line in lines[1:]:
        cells = line.split('|')
        if len(cells) != len(_PENDING_COLUMNS):
            raise GateError(f'{PENDING_PATH}: a row with {len(cells)} cells: {line[:80]!r}')
        out[cells[0]] = dict(zip(_PENDING_COLUMNS, cells))
    return out


def _write_pending(project_dir: str, rows: dict[str, dict[str, str]]) -> None:
    path = _pending_file(project_dir)
    if not rows:
        if os.path.isfile(path):
            os.remove(path)
        return
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, 'w', encoding='utf-8', newline='') as f:
        f.write('|'.join(_PENDING_COLUMNS) + '\n')
        for row in rows.values():
            f.write('|'.join(row[c] for c in _PENDING_COLUMNS) + '\n')


def mark_pending(project_dir: str, scene_id: str, command: str, reason: str) -> None:
    """List `scene_id`. A `REVISE_REJECTED` row keeps that command and its
    rejected fact ids whatever replaces it (a failed check of the revision):
    the ids are what lists the dependents once the scene passes."""
    from storyforge.common import csv_safe
    rows = pending(project_dir)
    old = rows.get(scene_id)
    ids = rejected_ids(old) + (rejected_ids({'command': command, 'reason': reason})
                               if command == REVISE_REJECTED else [])
    if ids:
        command = REVISE_REJECTED
        reason = re.sub(r'\s*\[rejected: [^\]]*\]', '', reason) \
            + f' [rejected: {";".join(dict.fromkeys(ids))}]'
    rows[scene_id] = {'scene_id': scene_id, 'command': command, 'reason': csv_safe(reason)}
    _write_pending(project_dir, rows)


def rejected_ids(row: dict[str, str] | None) -> list[str]:
    """The rejected fact ids a `REVISE_REJECTED` pending row carries."""
    if not row or row.get('command') != REVISE_REJECTED:
        return []
    ids = [i for group in re.findall(r'\[rejected: ([^\]]*)\]', row.get('reason', ''))
           for i in group.split(';') if i]
    return list(dict.fromkeys(ids))


def clear_pending(project_dir: str, scene_id: str) -> None:
    rows = pending(project_dir)
    if rows.pop(scene_id, None) is not None:
        _write_pending(project_dir, rows)


# ============================================================================
# Errors already in the book: working/gate-reported.csv
# ============================================================================

#: The contradictions a gate run found already in the book (`inherited`)
#: and let through, one row each, so the author has them after the run's
#: log scrolls by. Not a block: `write` and `revise` go on past them. A
#: scene's rows are replaced each time it commits; a gate run of the scene
#: that finds one of them again (same source and quote, any command) counts
#: it inherited.
REPORTED_PATH = 'working/gate-reported.csv'
_REPORTED_COLUMNS = ['scene_id', 'command', 'source', 'quote', 'finding']


def reported(project_dir: str) -> dict[str, list[dict[str, str]]]:
    """Scene id → its rows in `REPORTED_PATH`.

    Raises:
        GateError: the file is malformed or unreadable.
    """
    path = os.path.join(project_dir, REPORTED_PATH)
    if not os.path.isfile(path):
        return {}
    try:
        with open(path, encoding='utf-8') as f:
            lines = [line.rstrip('\n') for line in f if line.strip()]
    except (OSError, UnicodeDecodeError) as e:
        raise GateError(f'{REPORTED_PATH}: {e}') from e
    if not lines or lines[0].split('|') != _REPORTED_COLUMNS:
        raise GateError(f'{REPORTED_PATH}: the header must be {"|".join(_REPORTED_COLUMNS)}')
    out: dict[str, list[dict[str, str]]] = {}
    for line in lines[1:]:
        cells = line.split('|')
        if len(cells) != len(_REPORTED_COLUMNS):
            raise GateError(f'{REPORTED_PATH}: a row with {len(cells)} cells: {line[:80]!r}')
        row = dict(zip(_REPORTED_COLUMNS, cells))
        out.setdefault(row['scene_id'], []).append(row)
    return out


def record_reported(project_dir: str, scene_id: str, command: str,
                    findings: list[Finding]) -> None:
    """Replace `scene_id`'s rows in `REPORTED_PATH` with `findings`
    (none: its rows go). The file goes when it has no rows."""
    from storyforge.common import csv_safe
    rows = reported(project_dir)
    rows.pop(scene_id, None)
    if findings:
        rows[scene_id] = [{'scene_id': scene_id, 'command': command,
                           'source': csv_safe(f.established_scene or ''),
                           'quote': csv_safe(_one_line(f.scene_quote)),
                           'finding': csv_safe(_one_line(f.message()))} for f in findings]
    path = os.path.join(project_dir, REPORTED_PATH)
    if not rows:
        if os.path.isfile(path):
            os.remove(path)
        return
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, 'w', encoding='utf-8', newline='') as f:
        f.write('|'.join(_REPORTED_COLUMNS) + '\n')
        for sid in sorted(rows):
            for row in rows[sid]:
                f.write('|'.join(row[c] for c in _REPORTED_COLUMNS) + '\n')


# ============================================================================
# The re-check (Phase 4, docs/plans/2026-10-31-phase4-safe-revision-design.md §3)
# ============================================================================

#: What one re-gated scene is forecast to cost: an extraction and a
#: persistence call (Sonnet) and a check (Opus, the story so far cached).
#: E4's gate ran about $0.35-0.45 a scene on shared-dark; rounded up.
RECHECK_COST_PER_SCENE = 0.6


#: A pending row's command for a scene listed for a re-check, and for one
#: whose re-check didn't pass (not re-run until the author acts:
#: `storyforge check --pending` or a redraft)
RECHECK, RECHECK_FAILED = 'recheck', 'recheck-failed'
#: A scene whose prose states a fact the author rejected: the author revises
#: it; when it passes the gate, the scenes depending on the rejection are
#: listed (its reason carries `[rejected: ids]`, kept by `mark_pending`)
REVISE_REJECTED = 'revise-rejected'


@dataclass
class Recheck:
    """`recheck_pending`'s answer."""
    passed: list[str] = field(default_factory=list)
    #: the scene that didn't pass, and why ('' when none failed)
    failed: str = ''
    why: str = ''
    result: GateResult | None = None
    #: the re-check scenes still pending when it stopped
    left: list[str] = field(default_factory=list)
    #: the forecast was over the cost threshold, so it stopped before a scene
    over_budget: bool = False
    forecast: float = 0.0
    #: what the run is forecast to have spent, `spent_before` included
    spent: float = 0.0


def recheck_queue(project_dir: str, skip: set[str] | frozenset[str] = frozenset()) -> list[str]:
    """The scenes pending a re-check (`RECHECK`, not `RECHECK_FAILED`), in
    reading order, without `skip`."""
    order = ledger.scene_order(project_dir)
    return sorted((s for s, r in pending(project_dir).items()
                   if r['command'] == RECHECK and s not in skip and s in order),
                  key=order.get)


def recheck_pending(project_dir: str, *, log_dir: str, skip: set[str] | frozenset[str] = frozenset(),
                    spent_before: float = 0.0, extract_model: str | None = None,
                    check_model: str | None = None) -> Recheck:
    """Re-gate the scenes pending a re-check (design §3), one at a time in
    reading order, never editing their prose: each one's commitments are
    extracted again against the ledger as it now is, checked, and committed
    when clean, which may list later scenes in turn (the cascade only moves
    forward: a scene lists only scenes after it). Stops at the first scene
    that doesn't pass, listed `RECHECK_FAILED` with the reason so it isn't
    re-run until the author acts (Ben, 2026-10-31: report and stop); the
    rest stay pending. `skip` is scenes the caller is about to redraft.

    Cost (Ben: forecast, and run under the threshold): the forecast is
    logged first; before each scene, `spent_before` (what the caller's run
    already spent on re-checks) plus this call's spend plus the queue left
    at `RECHECK_COST_PER_SCENE` must be within `costs.check_threshold`,
    otherwise it stops with `over_budget` and everything stays pending for
    `storyforge check --pending`."""
    from storyforge.common import log
    from storyforge.costs import check_threshold
    run = Recheck(spent=spent_before)
    announced = False
    while True:
        queue = recheck_queue(project_dir, skip)
        if not queue:
            return run
        run.forecast = run.spent + len(queue) * RECHECK_COST_PER_SCENE
        if not check_threshold(run.forecast):
            run.over_budget, run.left = True, queue
            log(f'WARNING: re-checking {len(queue)} scene(s) ({", ".join(queue[:8])}) would '
                f'bring this run\'s re-checks to about ${run.forecast:.2f}, over the cost '
                f'threshold: not run. They stay in {PENDING_PATH}; run `storyforge check '
                f'--pending` (with STORYFORGE_COST_THRESHOLD raised if needed).')
            return run
        if not announced:
            log(f'Re-checking {len(queue)} scene(s) whose facts depend on what changed, '
                f'forecast about ${len(queue) * RECHECK_COST_PER_SCENE:.2f}: {", ".join(queue)}')
            announced = True
        sid = queue[0]
        log(f'Re-checking {sid}...')
        run.spent += RECHECK_COST_PER_SCENE   # paid whether or not it finishes
        try:
            result = gate_scene(project_dir, sid, command='recheck',
                                log_dir=os.path.join(log_dir, 'recheck', sid),
                                extract_model=extract_model, check_model=check_model,
                                introduced_by=_writer(project_dir, sid))
        except GateError as e:
            why = ' '.join(str(e).split())
            mark_pending(project_dir, sid, RECHECK_FAILED, f're-check could not run: {why}')
            run.failed, run.why, run.left = sid, why, recheck_queue(project_dir, skip)
            return run
        if not result.passed:
            lines = blocking_lines(report_lines(result))
            mark_pending(project_dir, sid, RECHECK_FAILED,
                         f're-check did not pass: {len(lines)} problem(s): '
                         + '; '.join(_one_line(x) for x in lines[:3]))
            run.failed, run.why, run.result = sid, '; '.join(lines[:3]), result
            run.left = recheck_queue(project_dir, skip)
            return run
        run.passed.append(sid)


def _writer(project_dir: str, scene_id: str) -> str:
    """The command that wrote `scene_id`'s prose, as its commitments record
    it (the most common), so a re-check keeps it; `recheck` when none do."""
    from collections import Counter
    writers = Counter((r.get('introduced_by') or '').strip() for r in ledger.load(project_dir)
                      if ledger.is_commitment(r) and (r.get('scene_id') or '').strip() == scene_id)
    return writers.most_common(1)[0][0] if writers else 'recheck'
