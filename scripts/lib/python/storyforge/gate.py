"""The gate: nothing commits to the ledger without a check (rethink plan §3.2).

For one scene's prose, `gate_scene` runs:

1. **Extract** the scene's commitments with phase 4's rubric
   (`extract.build_commitments_prompt`), offered the facts in force entering
   it and the registry facts recorded for it (`extract.known_for_scene`).
2. **Halt** on decision 2's immediate tier: `audit.halting_conditions` on the
   proposed rows (a `fixed` fact superseded or changed), plus
   `plan-contradiction`: the prose supersedes a registry fact (one recorded
   for the scene, or in force entering it), or ends a registry state its
   `resolves` doesn't end there. The third trigger, a fact extraction
   flagged low-confidence, is not wired: phase 4's schema has no confidence
   yet (adding it re-records E3 and E5).
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

from storyforge import audit, ledger
from storyforge.checker import CheckError, CheckResult, Finding, check_scene

#: The commands whose prose the gate commits (`ledger.COMMITMENT_WRITERS`
#: without the extract pass)
GATE_COMMANDS = tuple(w for w in ledger.COMMITMENT_WRITERS if w != ledger.COMMITMENTS_PASS)

#: Extraction problems that mean the prose contradicts the plan
PLAN_PROBLEMS = ('disagrees', 'ends registry')
#: Extraction problems that would commit a wrong row: they block the commit
UNRESOLVED = ('quote', 'no quote', 'supersedes', 'ends', 'ends again')
#: Extraction problems reported on a pass: a subject not in the registries
#: (an object has none), facts left out past the offer cap, facts tied to a
#: scene id that isn't a scene
REPORTED = ('subject', 'cap', 'unplaced')


class GateError(RuntimeError):
    """A gate step couldn't finish; nothing was written."""


@dataclass
class GateResult:
    scene_id: str
    #: the scene's commitments, as they would be (or were) committed
    proposed: list[dict[str, str]] = field(default_factory=list)
    halts: list[audit.Halt] = field(default_factory=list)
    #: extraction's problems (`extract.COMMITMENT_PROBLEMS` → strings): the
    #: plan ones are also `halts`, `UNRESOLVED` block the commit, `REPORTED`
    #: are for the caller to report
    problems: dict[str, list[str]] = field(default_factory=dict)
    check: CheckResult | None = None
    committed: bool = False
    #: registry ids whose quote was filled on commit
    quotes_filled: list[str] = field(default_factory=list)

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
    def passed(self) -> bool:
        return not (self.halts or self.unresolved or self.findings or self.unverified)


def _subjects(project_dir: str) -> dict[str, str]:
    from storyforge.enrich import load_registry_alias_maps
    maps = load_registry_alias_maps(project_dir)
    return {**maps.get('locations', {}), **maps.get('characters', {})}


def _extract(project_dir: str, scene_id: str, prose: str, rows: list[dict[str, str]],
             order: dict[str, int], introduced_by: str, model: str, log_dir: str,
             problems: dict[str, list[str]]) -> list[dict[str, str]]:
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
    return commitment_rows(found, scene_id, prose, rows, known, recorded, subjects,
                           introduced_by, problems, own_writers=ledger.COMMITMENT_WRITERS,
                           registry_is_plan=True)


def _plan_halts(problems: dict[str, list[str]]) -> list[audit.Halt]:
    """`plan-contradiction` halts from `commitment_rows`' problem strings:
    `disagrees` is `scene: registry-id (prose: proposed-id)`, `ends registry`
    is `scene: registry-id (resolves: ...)`. A halt's `fact_id` is the
    proposed fact where there is one, else the registry fact."""
    import re
    halts = []
    for item in problems.get('disagrees', []):
        m = re.match(r'[^:]+: (\S+) \(prose: (\S+)\)$', item)
        reg, proposed = (m.group(1), m.group(2)) if m else (item, item)
        halts.append(audit.Halt('plan-contradiction', proposed,
                                f'the prose supersedes the registry fact {reg}'))
    for item in problems.get('ends registry', []):
        m = re.match(r'[^:]+: (\S+) \(resolves: ([^)]*)\)$', item)
        reg, ends = (m.group(1), m.group(2)) if m else (item, '?')
        halts.append(audit.Halt('plan-contradiction', reg,
                                f'the prose ends the registry state {reg} here; its '
                                f'resolves says {ends}'))
    return halts


def _leaning_on(rows: list[dict[str, str]], gone: set[str]) -> list[str]:
    """Rows (not themselves going) whose supersedes or depends_on name `gone`."""
    return [f'{r["id"]} → {ref}' for r in rows if r['id'] not in gone
            for col in ('supersedes', 'depends_on') for ref in ledger._split(r.get(col, ''))
            if ref in gone]


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
            commitments this would replace, or the ledger changed on disk
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
    try:
        rows = ledger.load(project_dir)
        order = ledger.scene_order(project_dir)
    except (ledger.LedgerError, ValueError) as e:
        raise GateError(f'{scene_id}: {e}') from e
    loaded = copy.deepcopy(rows)
    if scene_id not in order:
        raise GateError(f'{scene_id} is not a scene in reference/scenes.csv')

    # The scene's earlier commitments (a redraft's) aren't offered back to it
    # and are replaced on commit; a later fact leaning on one is Phase 4's
    # re-check, which doesn't exist yet, so it stops here
    old = {r['id'] for r in rows if ledger.is_commitment(r)
           and (r.get('scene_id') or '').strip() == scene_id}
    leaning = _leaning_on(rows, old)
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
                               result.problems)
    result.halts = audit.halting_conditions(result.proposed, rows) + _plan_halts(result.problems)
    try:
        result.check = check_scene(project_dir, scene_id, prose=prose, model=check_model,
                                   log_file=os.path.join(log_dir, f'gate-check-{scene_id}.json'),
                                   rows=rows)
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
    """What a fix should address, one line each: halts, contradictions and
    broken promises, unverified findings (the checker may be right). An
    extraction problem isn't a prose problem, so it isn't here: the re-check
    extracts again."""
    lines = [f'Stop: {h.detail} (fact {h.fact_id})' for h in result.halts]
    for f in result.findings + result.unverified:
        if f.kind == 'contradiction':
            where = f.established_scene or 'the ledger'
            lines.append(f'{f.code} contradiction: the scene says "{f.scene_quote}", but '
                         f'{where} establishes "{f.established_quote}". {f.explanation}')
        else:
            lines.append(f'Broken promise ({f.fact_id}): the brief promises '
                         f'"{f.established_quote}". {f.explanation}'
                         + (f' Nearest words: "{f.scene_quote}".' if f.scene_quote else ''))
    return lines


def build_fix_prompt(scene_id: str, prose: str, problems: list[str]) -> str:
    listing = '\n'.join(f'{n}. {p}' for n, p in enumerate(problems, start=1))
    return f"""A continuity check found these problems in scene {scene_id}. Fix each with the smallest edit to the scene's prose that resolves it.

## Problems

{listing}

## Rules

- Change the scene so it agrees with what the book established; never assume the established fact is the one that is wrong.
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
        find = e.get('find') or ''
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
    result: GateResult          # the last gate run (the re-check when fixed)
    first: GateResult           # the first gate run
    fixed: bool = False         # whether the fix changed the prose


def gate_and_fix(project_dir: str, scene_id: str, *, command: str, prose: str,
                 log_dir: str, extract_model: str | None = None,
                 check_model: str | None = None, fix_model: str | None = None) -> GatedScene:
    """Gate `prose`; if it doesn't pass, fix it once and gate the fixed prose
    (plan §3.2 step 3). The caller writes `.prose` to the scene file: the
    ledger is committed only when `.result.passed`. A first run that fails
    only on extraction problems is re-gated without an edit.

    Raises:
        GateError: from either gate run or the fix.
    """
    os.makedirs(log_dir, exist_ok=True)
    first = gate_scene(project_dir, scene_id, command=command, prose=prose, log_dir=log_dir,
                       extract_model=extract_model, check_model=check_model)
    if first.passed:
        return GatedScene(prose, first, first)
    fixed = fix_scene(scene_id, prose, first, log_dir=log_dir, model=fix_model)
    again = gate_scene(project_dir, scene_id, command=command, prose=fixed,
                       log_dir=os.path.join(log_dir, 'recheck'),
                       extract_model=extract_model, check_model=check_model)
    return GatedScene(fixed, again, first, fixed=fixed != prose)


def report_lines(result: GateResult) -> list[str]:
    """The gate's verdict on a scene as log lines: everything that stopped
    the commit, then what is reported either way. Empty only for a pass
    with nothing to report."""
    from storyforge.common import csv_safe
    lines = []
    for h in result.halts:
        lines.append(f'HALT ({h.kind}): {csv_safe(str(h))}')
    for item in result.unresolved:
        lines.append(f'EXTRACTION: {csv_safe(item)}')
    for f in result.findings:
        lines.append(f'{f.kind.upper()}: {csv_safe(f.message())}')
    for f in result.unverified:
        lines.append(f'UNVERIFIED ({f.problem}): {csv_safe(f.message())}')
    for kind in REPORTED:
        items = result.problems.get(kind, [])
        if items:
            lines.append(f'NOTE ({kind}): ' + '; '.join(csv_safe(i) for i in items[:20])
                         + (' ...' if len(items) > 20 else ''))
    if result.check:
        for rid, quote, why in result.check.kept_unverified:
            lines.append(f'NOTE (kept, not filled): {rid}: {why}')
        if result.check.unknown_brief_items:
            lines.append('NOTE (brief items no binding fact matches, not checked): '
                         + '; '.join(result.check.unknown_brief_items))
    return lines
