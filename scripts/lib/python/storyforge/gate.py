"""The gate: nothing commits to the ledger without a check (rethink plan §3.2).

For one scene's prose, `gate_scene` runs:

1. **Extract** the scene's commitments with phase 4's rubric
   (`extract.build_commitments_prompt`), offered the facts in force entering
   it and the registry facts recorded for it (`extract.known_for_scene`).
2. **Halt** on decision 2's immediate tier: `audit.halting_conditions` on the
   proposed rows (a `fixed` fact superseded or changed), plus
   `plan-contradiction`: the prose disagrees with a registry fact recorded
   for the scene, or ends a registry state its `resolves` doesn't end there.
3. **Check** the scene against the book and its brief (`checker.check_scene`):
   contradictions and broken promises, by code.
4. **Commit** only when nothing halted and the check found nothing: the
   scene's commitments replace its earlier ones (`introduced_by` = the
   command that wrote the prose), each registry fact the prose was found to
   establish gets its blank quote filled (`ledger.fill_quote`), and the
   ledger is saved through `ledger.save`, so the audit log has every fact.

**Fix** (plan §3.2 step 3) is the caller's: a result that didn't pass names
what to fix. The design is `docs/plans/2026-10-30-gate-ledger-design.md`.

Fails loud: a step that can't finish raises `GateError`, and nothing is
written. A result that didn't pass writes nothing either; it is not an
exception, because the caller decides between fixing and reporting
(advisor mode).
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field

from storyforge import audit, ledger
from storyforge.checker import CheckError, CheckResult, Finding, check_scene

#: The commands whose prose the gate commits (`ledger.COMMITMENT_WRITERS`
#: without the extract pass)
GATE_COMMANDS = tuple(w for w in ledger.COMMITMENT_WRITERS if w != ledger.COMMITMENTS_PASS)

#: Extraction problems that mean the prose contradicts the plan
PLAN_PROBLEMS = ('disagrees', 'ends registry')


class GateError(RuntimeError):
    """A gate step couldn't finish; nothing was written."""


@dataclass
class GateResult:
    scene_id: str
    #: the scene's commitments, as they would be (or were) committed
    proposed: list[dict[str, str]] = field(default_factory=list)
    halts: list[audit.Halt] = field(default_factory=list)
    #: extraction's other problems (`extract.COMMITMENT_PROBLEMS` → strings),
    #: reported, not halting: a quote not found, an unresolved subject, ...
    problems: dict[str, list[str]] = field(default_factory=dict)
    check: CheckResult | None = None
    committed: bool = False
    #: registry ids whose quote was filled on commit
    quotes_filled: list[str] = field(default_factory=list)

    @property
    def findings(self) -> list[Finding]:
        return self.check.findings if self.check else []

    @property
    def passed(self) -> bool:
        return not self.halts and not self.findings


def _subjects(project_dir: str) -> dict[str, str]:
    from storyforge.enrich import load_registry_alias_maps
    maps = load_registry_alias_maps(project_dir)
    return {**maps.get('locations', {}), **maps.get('characters', {})}


def _extract(project_dir: str, scene_id: str, prose: str, rows: list[dict[str, str]],
             order: dict[str, int], introduced_by: str, model: str, log_dir: str,
             problems: dict[str, list[str]]) -> list[dict[str, str]]:
    from storyforge.api import RefusalError, extract_text, invoke_to_file, is_truncated
    from storyforge.elaborate import get_scene
    from storyforge.enrich import format_registries_for_prompt
    from storyforge.extract import (COMMITMENTS_SCHEMA, build_commitments_prompt,
                                    commitment_rows, known_for_scene,
                                    parse_commitments_response)
    ref_dir = os.path.join(project_dir, 'reference')
    scene = get_scene(scene_id, ref_dir) or {}
    subjects = _subjects(project_dir)
    names = [scene.get('pov', ''), scene.get('location', '')] + scene.get('on_stage', '').split(';')
    scene_subjects = {subjects[n.strip().lower()] for n in names if n.strip().lower() in subjects}
    known, recorded, left_out = known_for_scene(rows, scene_id, order, scene_subjects)
    if left_out:
        problems['cap'].append(f'{scene_id} ({left_out})')
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
    except (RefusalError, ValueError) as e:
        raise GateError(f'{scene_id}: extraction failed: {e}') from e
    return commitment_rows(found, scene_id, prose, rows, known, recorded, subjects,
                           introduced_by, problems, own_writers=ledger.COMMITMENT_WRITERS)


def _plan_halts(problems: dict[str, list[str]]) -> list[audit.Halt]:
    halts = []
    for kind in PLAN_PROBLEMS:
        for item in problems.get(kind, []):
            what = ('the prose disagrees with a registry fact recorded for the scene'
                    if kind == 'disagrees' else
                    'the prose ends a registry state its resolves does not end here')
            halts.append(audit.Halt('plan-contradiction', item.split(': ', 1)[-1], what))
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

    Not yet handled (Phase 4, safe revision): the check reads the ledger as
    it is, so a redraft is checked against its earlier version's
    commitments too, and a `resolves` the earlier version set on an earlier
    state stays.

    Raises:
        GateError: a step couldn't finish (extraction or the check failed,
            the scene has no prose, or a later fact leans on one of the
            scene's commitments this would replace); nothing was written.
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

    result = GateResult(scene_id, problems={k: [] for k in COMMITMENT_PROBLEMS})
    result.proposed = _extract(project_dir, scene_id, prose, rows, order, command,
                               extract_model or select_model('evaluation'), log_dir,
                               result.problems)
    result.halts = audit.halting_conditions(result.proposed, rows) + _plan_halts(result.problems)
    try:
        result.check = check_scene(project_dir, scene_id, prose=prose, model=check_model,
                                   log_file=os.path.join(log_dir, f'gate-check-{scene_id}.json'))
    except CheckError as e:
        raise GateError(str(e)) from e
    if not result.passed:
        return result

    new = rows + result.proposed
    for rid, quote in result.check.kept:
        if ledger.fill_quote(new, rid, quote):
            result.quotes_filled.append(rid)
    ledger.save(project_dir, new, command=command)
    result.committed = True
    return result
