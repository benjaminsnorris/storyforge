"""Running the gate over the gate set, for the suites that measure one
configuration of it (`evals/suites/gate_set.py`: the open checker, today's
default; `evals/suites/gate_set_questions.py`: the question layer, #649).

Both score the same way (`gate_set.score`), gate on their own recorded
values (`blocking_set.runner.floor_gates`, #488), and write per-item
outcomes to the private set's `results/` (never to this repo).
"""

from __future__ import annotations

import json
import os

import gate_set
from blocking_set.runner import floor_gates
from harness import Gate, SuiteOutput, SuiteUnavailable, has_recordings

#: What each check method's per-item outcomes file is called in `results/`
OUTCOMES = {'open': 'latest.json', 'questions': 'latest-questions.json'}


def gate_one(item: dict, work_dir: str):
    """Gate one item's prose in its pre-pass book, as revise gates a pass's
    prose: `before` is the book before the prose is written. Returns the
    `GateResult`, or None when the gate couldn't finish (a `GateError`,
    which write and revise list as pending: it doesn't pass)."""
    from e8 import prepare
    from storyforge import gate
    case = e1_case(item['case'])
    project, scene_id = prepare(case, os.path.join(work_dir, item['id']))
    before = gate.snapshot(project)
    with open(os.path.join(project, 'scenes', f'{scene_id}.md'), 'w', encoding='utf-8') as f:
        f.write(item['prose'])
    try:
        return gate.gate_scene(project, scene_id, command=gate_set.COMMANDS[item['family']],
                               prose=item['prose'], before=before,
                               log_dir=os.path.join(project, 'working', 'logs', 'gate'))
    except gate.GateError:
        return None


_CASES: dict[str, dict] = {}


def e1_case(case_id: str) -> dict:
    """The E1 case by id. Raises `LookupError` when E1 no longer has it (a
    case renamed or dropped since the set was built: rebuild the set)."""
    if not _CASES:
        from e1 import load_cases
        _CASES.update({c['id']: c for c in load_cases()})
    if case_id not in _CASES:
        raise LookupError(f'E1 has no case {case_id}: rebuild the gate set')
    return _CASES[case_id]


def run(ctx, method: str, floors: dict, min_positives: int) -> SuiteOutput:
    from storyforge import gate
    from storyforge.runner import run_parallel
    path = gate_set.set_dir()
    if ctx.mode == 'replay' and not has_recordings(ctx.cassette_dir):
        # Recorded on purpose, only when a decision needs it (#677). Until
        # then a replay has nothing to measure: unavailable (stale), not the
        # harness's "no recordings" error, which would fail every full run
        # and refuse --baseline over a suite deliberately left unrecorded
        raise SuiteUnavailable(
            f'{ctx.name} is not recorded yet (no recordings at {ctx.cassette_dir}); it is '
            f'recorded when the question layer is a candidate to replace the open checker '
            f'(#677): python3 evals/run.py --mode record --suite {ctx.name} --runs 3')
    items = gate_set.load(path)
    problems = gate_set.validate(items)
    if problems:
        raise RuntimeError(f'the gate set has {len(problems)} problem(s), e.g. {problems[0]}')
    run_items = {i['id']: i for i in items if i['role'] in ('positive', 'control')}
    saved = gate.GATE_CHECK_METHOD
    gate.GATE_CHECK_METHOD = method
    try:
        results = run_parallel(sorted(run_items), lambda iid: gate_one(run_items[iid], ctx.work_dir),
                               label='item')
    finally:
        gate.GATE_CHECK_METHOD = saved
    from storyforge.gate import GateResult
    failed = sorted(k for k, r in results.items() if r is not None and not isinstance(r, GateResult))
    if failed:
        # ids and the exception's type only: its message can quote the prose
        first = results[failed[0]]
        raise RuntimeError(f'the gate raised on {len(failed)} item(s): {", ".join(failed[:10])}; '
                           f'first: {type(first).__name__}')
    outcomes = {iid: gate_set.outcome(run_items[iid], results[iid]) for iid in run_items}
    metrics, by_code = gate_set.score(items, outcomes)
    out_dir = os.path.join(path, 'results')
    os.makedirs(out_dir, exist_ok=True)
    with open(os.path.join(out_dir, OUTCOMES[method]), 'w', encoding='utf-8') as f:
        json.dump({'method': method,
                   'items': [{**outcomes[iid], 'case': run_items[iid]['case'],
                              'role': run_items[iid]['role'], 'code': run_items[iid]['code']}
                             for iid in sorted(outcomes)]}, f, indent=1)
        f.write('\n')
    gates, notes = floor_gates(metrics, floors)
    gates.append(Gate('positives', metrics['positives'], '>=', min_positives))
    missed = sorted(iid for iid, o in outcomes.items()
                    if run_items[iid]['role'] == 'positive' and not o['caught'])
    notes.append(f'missed ({len(missed)}): {", ".join(missed)}' if missed else 'missed: none')
    alarms = sorted(iid for iid, o in outcomes.items()
                    if run_items[iid]['role'] == 'control' and o['caught'])
    if alarms:
        notes.append(f'a finding on a control\'s correct statement of the fact: {", ".join(alarms)}')
    notes.append('labels are E8\'s Opus judge on one known error per item: a stop for another '
                 'reason is not scored (stopped_* counts it), and recall_per_case weighs each '
                 'case the same')
    notes.append(f'per-item outcomes (private): {gate_set.SET_NAME}/results/{OUTCOMES[method]} '
                 f'in the storyforge-evals repo')
    return SuiteOutput(metrics=metrics, by_code=by_code, gates=gates, notes=notes)
