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
   contradictions and broken promises, by code.
4. **Commit** only when nothing halted, extraction left nothing unresolved
   (`UNRESOLVED`: a quote not in the scene, a `supersedes` or `ends` that
   names nothing it can apply to), and the check found nothing, verified or
   not: the
   scene's commitments replace its earlier ones (`introduced_by` = the
   command that wrote the prose), each registry fact the prose was found to
   establish gets its blank quote filled (`ledger.fill_quote`), and the
   ledger is saved through `ledger.save`, so the audit log has every fact.

**Fix** (plan §3.2 step 3) is the caller's: a result that didn't pass names
what to fix. The caller must also report `result.problems`' report-only
kinds (`REPORTED`) on a pass: they don't make the ledger wrong, but the
author should know. The design is `docs/plans/2026-10-30-gate-ledger-design.md`.

Fails loud: a step that can't finish raises `GateError`, and nothing is
written. A result that didn't pass writes nothing either; it is not an
exception, because the caller decides between fixing and reporting
(advisor mode).
"""

from __future__ import annotations

import copy
import os
from dataclasses import dataclass, field

from storyforge import audit, ledger, persistence
from storyforge.checker import CheckError, CheckResult, Dispute, Finding, check_scene

#: The commands whose prose the gate commits (`ledger.COMMITMENT_WRITERS`
#: without the extract pass)
GATE_COMMANDS = tuple(w for w in ledger.COMMITMENT_WRITERS if w != ledger.COMMITMENTS_PASS)

#: Extraction problems that would commit a wrong row: they block the commit
UNRESOLVED = ('quote', 'no quote', 'supersedes', 'ends', 'ends again')
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

    @property
    def findings(self) -> list[Finding]:
        return self.check.findings if self.check else []

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


def leaning_on(project_dir: str, scene_id: str) -> list[str]:
    """`fact → commitment` for each later fact that leans on (supersedes or
    depends on) one of `scene_id`'s commitments, and `scene ends → commitment`
    for each of its states a later scene ended. Non-empty means the gate
    can't replace them (Phase 4's re-check set), so redrafting the scene
    would be refused after the redraft was paid for: check first."""
    rows = ledger.load(project_dir)
    old = {r['id'] for r in rows if ledger.is_commitment(r)
           and (r.get('scene_id') or '').strip() == scene_id}
    return _leaning_on(rows, old, ledger.scene_order(project_dir))


def has_commitments(project_dir: str, scene_id: str) -> bool:
    """Whether the ledger holds commitments from `scene_id`'s prose."""
    return any(ledger.is_commitment(r) and (r.get('scene_id') or '').strip() == scene_id
               for r in ledger.load(project_dir))


def _leaning_on(rows: list[dict[str, str]], gone: set[str],
                order: dict[str, int] | None = None) -> list[str]:
    """Rows (not themselves going) whose supersedes or depends_on name `gone`,
    and each `gone` state another scene ended (`resolves` names a scene other
    than its own, and one in `order` when given: an end at a deleted scene
    is meaningless, and validate reports it): replacing it would drop that
    end, and the state would read as in force for the rest of the book."""
    leaning = [f'{r["id"]} → {ref}' for r in rows if r['id'] not in gone
               for col in ('supersedes', 'depends_on') for ref in ledger._split(r.get(col, ''))
               if ref in gone]
    for r in rows:
        ends = (r.get('resolves') or '').strip()
        if r['id'] in gone and ends not in ('', 'never', (r.get('scene_id') or '').strip()) \
                and (order is None or ends in order):
            leaning.append(f'{ends} ends → {r["id"]}')
    return leaning


def gate_scene(project_dir: str, scene_id: str, *, command: str, prose: str | None = None,
               log_dir: str, extract_model: str | None = None,
               check_model: str | None = None) -> GateResult:
    """Extract, halt, check and (if all clear) commit `scene_id`'s prose:
    `prose`, or the scene file when None. `command` is the command that
    wrote the prose (one of `GATE_COMMANDS`), recorded as the new rows'
    `introduced_by` and as the audit log's command.

    A redraft is extracted and checked against the ledger without its
    earlier version's commitments, and the `resolves` that version set on
    earlier commitments are cleared (this version's `ends` set them again).
    A `resolves` it set on a registry state isn't touched: the gate never
    sets one there.

    Raises:
        GateError: a step couldn't finish (extraction or the check failed,
            the scene has no prose, a later fact leans on one of the scene's
            commitments this would replace or a later scene ended one of its
            states, or the ledger changed on disk
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
    except (ledger.LedgerError, ValueError) as e:
        raise GateError(f'{scene_id}: {e}') from e
    loaded = copy.deepcopy(rows)
    if scene_id not in order:
        raise GateError(f'{scene_id} is not a scene in reference/scenes.csv')

    # The scene's earlier commitments (a redraft's) aren't offered back to it
    # and are replaced on commit; a later fact leaning on one, or a later
    # scene's end of one of its states, is Phase 4's re-check, which doesn't
    # exist yet, so it stops here
    old = {r['id'] for r in rows if ledger.is_commitment(r)
           and (r.get('scene_id') or '').strip() == scene_id}
    leaning = _leaning_on(rows, old, order)
    if leaning:
        raise GateError(f'{scene_id}: later facts lean on commitments this scene would '
                        f'replace: {", ".join(leaning[:10])}')
    rows = [r for r in rows if r['id'] not in old]
    # ... and the ends the earlier version set: this version's extraction
    # sets its own
    for r in rows:
        if ledger.is_commitment(r) and (r.get('resolves') or '').strip() == scene_id:
            r['resolves'] = ''

    result = GateResult(scene_id, problems={k: [] for k in COMMITMENT_PROBLEMS})
    result.proposed = _extract(project_dir, scene_id, prose, rows, order, command,
                               extract_model or select_model('evaluation'), log_dir,
                               result.problems, result.dropped)
    result.halts = audit.halting_conditions(result.proposed, rows)
    try:
        result.check = check_scene(project_dir, scene_id, prose=prose, model=check_model,
                                   log_file=os.path.join(log_dir, f'gate-check-{scene_id}.json'),
                                   rows=rows, disputes=_disputes(result, rows))
    except CheckError as e:
        error = GateError(str(e))
        error.run = getattr(e, 'run', None)
        raise error from e
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
    new = rows + result.proposed
    for rid, quote in result.check.kept:
        if ledger.fill_quote(new, rid, quote):
            result.quotes_filled.append(rid)
    ledger.save(project_dir, new, command=command)
    result.committed = True
    try:
        clear_pending(project_dir, scene_id)
    except GateError as e:   # the ledger is written; say why the list wasn't updated
        from storyforge.common import log
        log(f'WARNING: {scene_id} passed, but {PENDING_PATH} could not be updated: {e}. '
            f'Remove its row by hand.')
    return result


# ============================================================================
# Fix (plan §3.2 step 3): targeted edits, then one re-check
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
    extracts again."""
    proposed = {r['id']: r for r in result.proposed}
    lines = []
    for h in result.halts:
        row = proposed.get(h.fact_id)
        said = (f' The scene says: "{row.get("quote") or row.get("statement")}".'
                if row else '')
        lines.append(f'The scene changes something the book fixed: {h.detail}.{said}')
    for d in result.unruled:
        lines.append(f'UNVERIFIED (extraction thinks the scene changes this; the check gave no '
                     f'ruling; edit only if the scene clearly contradicts it): the plan records '
                     f'"{d.statement}", and the scene says "{d.claim}".')
    for f, unverified in ([(f, False) for f in result.findings]
                          + [(f, True) for f in result.unverified]):
        tag = (f'UNVERIFIED (the check\'s quotes did not hold up: {f.problem}; edit only '
               f'if the scene clearly contradicts the book) ' if unverified else '')
        if f.kind == 'contradiction':
            where = f.established_scene or 'the ledger'
            lines.append(f'{tag}{f.code} contradiction: the scene says "{f.scene_quote}", '
                         f'but {where} establishes "{f.established_quote}". {f.explanation}')
        else:
            lines.append(f'{tag}Broken promise ({f.fact_id}): the brief promises '
                         f'"{f.established_quote}". {f.explanation}'
                         + (f' Nearest words: "{f.scene_quote}".' if f.scene_quote else ''))
    return lines


def build_fix_prompt(scene_id: str, prose: str, problems: list[str]) -> str:
    listing = '\n'.join(f'{n}. {p}' for n, p in enumerate(problems, start=1))
    return f"""A continuity check found these problems in scene {scene_id}. Fix each with the smallest edit to the scene's prose that resolves it.

## Problems

{listing}

## Rules

- Change the scene so it agrees with what the book established; never assume the established fact is the one that is wrong. A problem marked UNVERIFIED may be the check's mistake: edit for it only if the scene clearly contradicts the book.
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
              model: str | None = None) -> str:
    """The scene with targeted edits for `result`'s problems (one model call).

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
        response = invoke_to_file(build_fix_prompt(scene_id, prose, problems),
                                  model or select_model('revision'), log_file, 8000,
                                  output_schema=FIX_SCHEMA, label=f'fix {scene_id}')
        if is_truncated(response):
            raise ValueError('the reply hit its token limit')
        edits = json.loads(extract_text(response))['edits']
    except (RuntimeError, ValueError, KeyError, TypeError) as e:
        raise GateError(f'{scene_id}: the fix failed: {e}') from e
    return apply_edits(prose, edits)


@dataclass
class GatedScene:
    """`gate_and_fix`'s answer: the prose to keep and the gate's last word."""
    prose: str
    result: GateResult          # the last gate run (the re-check when there was one)
    first: GateResult           # the first gate run
    fixed: bool = False         # whether the fix changed the prose


def gate_and_fix(project_dir: str, scene_id: str, *, command: str, prose: str,
                 log_dir: str, extract_model: str | None = None,
                 check_model: str | None = None, fix_model: str | None = None) -> GatedScene:
    """Gate `prose`; if it doesn't pass, fix it once and gate the fixed prose
    (plan §3.2 step 3).

    - A first run that fails only on extraction problems (nothing for the fix)
      is re-gated without an edit: extraction runs again.
    - A fix that changes nothing (every problem judged a false alarm) is not
      re-gated: the first verdict stands, and a re-roll of the same prose
      won't overturn it.

    The caller must write `.prose` to the scene file at once, whether or not
    `.result.passed`: when it passed, the ledger was already committed with
    quotes from that prose.

    Raises:
        GateError: from either gate run or the fix; it carries the first run
            as `.first` (None when the first run itself failed), so its
            findings can still be reported.
    """
    os.makedirs(log_dir, exist_ok=True)
    first = gate_scene(project_dir, scene_id, command=command, prose=prose, log_dir=log_dir,
                       extract_model=extract_model, check_model=check_model)
    if first.passed:
        return GatedScene(prose, first, first)
    try:
        fixed = fix_scene(scene_id, prose, first, log_dir=log_dir, model=fix_model)
        if problems_to_fix(first) and fixed == prose:
            return GatedScene(prose, first, first)
        again = gate_scene(project_dir, scene_id, command=command, prose=fixed,
                           log_dir=os.path.join(log_dir, 'recheck'),
                           extract_model=extract_model, check_model=check_model)
    except GateError as e:
        e.first = first
        raise
    return GatedScene(fixed, again, first, fixed=fixed != prose)


def _one_line(text: str) -> str:
    return ' '.join(str(text).split())


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
        lines.append(f'{f.kind.upper()}: {_one_line(f.message())}')
    for f in result.unverified:
        lines.append(f'UNVERIFIED ({f.problem}): {_one_line(f.message())}')
    for d in result.unruled:
        lines.append(f'UNRULED: the scene may change the plan\'s {d.fact_id} '
                     f'("{_one_line(d.statement)}"): "{_one_line(d.claim)}"; the check gave '
                     f'no ruling')
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
    from storyforge.common import csv_safe
    rows = pending(project_dir)
    rows[scene_id] = {'scene_id': scene_id, 'command': command, 'reason': csv_safe(reason)}
    _write_pending(project_dir, rows)


def clear_pending(project_dir: str, scene_id: str) -> None:
    rows = pending(project_dir)
    if rows.pop(scene_id, None) is not None:
        _write_pending(project_dir, rows)
