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
from dataclasses import dataclass

import gate_set
from blocking_set.runner import floor_gates
from harness import Gate, SuiteOutput, SuiteUnavailable, has_recordings, read_cassette_log

#: What each check method's per-item outcomes file is called in `results/`
OUTCOMES = {'open': 'latest.json', 'questions': 'latest-questions.json'}


@dataclass
class Unfinished:
    """The gate couldn't finish an item (a `GateError`): write and revise
    list such a scene as pending, so it doesn't pass. `reason` is the
    error's message, kept for the private results file only (it can quote
    the book)."""
    reason: str


def gate_one(item: dict, work_dir: str):
    """Gate one item's prose in its pre-pass book, as revise gates a pass's
    prose: `before` is the book before the prose is written. Returns the
    `GateResult`, or `Unfinished` on a `GateError`. Anything else raises."""
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
    except gate.GateError as e:
        return Unfinished(str(e))


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


def record_command(name: str) -> str:
    """How to record a suite. Its first recording has no `usd_if_live` in
    the baseline, so `run.py` refuses it without `--over-budget` (and Ben's
    approval, which the reason names)."""
    return (f'python3 evals/run.py --mode record --suite {name} --runs 3 '
            f'--over-budget "<who approved, why>" (the first recording has no forecast '
            f'in the baseline; later ones drop --over-budget while the budget allows)')


def run(ctx, method: str, floors: dict, min_positives: int) -> SuiteOutput:
    from storyforge import gate
    from storyforge.gate import GateResult
    from storyforge.runner import run_parallel
    path = gate_set.set_dir()
    never_recorded = all(v is None for v in floors.values())
    if ctx.mode == 'replay' and never_recorded and not has_recordings(ctx.cassette_dir):
        # Recorded on purpose, only when a decision needs it (#677). Until
        # then a replay has nothing to measure: unavailable (stale), not the
        # harness's "no recordings" error, which would fail every full run
        # and refuse --baseline over a suite deliberately left unrecorded.
        # Once FLOORS are recorded, missing recordings are a misplaced
        # directory, and the harness's error stands
        raise SuiteUnavailable(
            f'{ctx.name} is not recorded yet (no recordings at {ctx.cassette_dir}); it is '
            f'recorded when the question layer is a candidate to replace the open checker '
            f'(#677): {record_command(ctx.name)}')
    if method == 'questions' and not gate.GATE_CONTINUITY:
        # the gate would raise GateError on every item, which would read as
        # every scene stopped and nothing caught
        raise RuntimeError('the question layer needs the typed state (gate.GATE_CONTINUITY)')
    items = gate_set.load(path)
    from e1 import load_cases
    problems = gate_set.validate(items, {c['id']: c for c in load_cases()})
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
    failed = sorted(k for k in run_items
                    if not isinstance(results.get(k), (GateResult, Unfinished)))
    if failed:
        # ids and the exception's type only: its message can quote the prose
        first = results.get(failed[0])
        raise RuntimeError(f'the gate raised on {len(failed)} item(s): {", ".join(failed[:10])}; '
                           f'first: {type(first).__name__ if first is not None else "no result"}')
    unfinished = sorted(k for k, r in results.items() if isinstance(r, Unfinished))
    if len(unfinished) == len(run_items):
        raise RuntimeError(f'the gate could not finish any of the {len(run_items)} item(s) '
                           f'(reasons in the gate logs): nothing was measured')
    # A cassette miss inside the gate is logged before the gate turns it into
    # a GateError; the harness reads the log after the run and calls it
    # stale or an error. Stop here, before any outcome is written as if it
    # were a measurement
    failures = read_cassette_log(os.environ.get('STORYFORGE_CASSETTE_LOG', ''))[1] \
        if os.environ.get('STORYFORGE_CASSETTE_LOG') else []
    if failures:
        raise RuntimeError(f'{len(failures)} cassette failure(s) during the run: no outcomes '
                           f'written')
    outcomes = {iid: gate_set.outcome(run_items[iid], None if isinstance(r, Unfinished) else r)
                for iid, r in ((iid, results[iid]) for iid in run_items)}
    metrics, by_code = gate_set.score(items, outcomes)
    out_dir = os.path.join(path, 'results')
    os.makedirs(out_dir, exist_ok=True)
    with open(os.path.join(out_dir, OUTCOMES[method]), 'w', encoding='utf-8') as f:
        json.dump({'method': method,
                   'items': [{**outcomes[iid], 'case': run_items[iid]['case'],
                              'role': run_items[iid]['role'], 'code': run_items[iid]['code'],
                              **({'unfinished': results[iid].reason}
                                 if isinstance(results[iid], Unfinished) else {})}
                             for iid in sorted(outcomes)]}, f, indent=1)
        f.write('\n')
    gates, notes = floor_gates(metrics, floors, gate_set.HIGHER_IS_BETTER)
    gates.append(Gate('positives', metrics['positives'], '>=', min_positives))
    missed = sorted(iid for iid, o in outcomes.items()
                    if run_items[iid]['role'] == 'positive' and not o['caught'])
    notes.append(f'missed ({len(missed)}): {", ".join(missed)}' if missed else 'missed: none')
    alarms = sorted(iid for iid, o in outcomes.items()
                    if run_items[iid]['role'] == 'control' and o['caught'])
    if alarms:
        notes.append(f'a finding on a control\'s correct statement of the fact: {", ".join(alarms)}')
    if unfinished:
        notes.append(f'the gate could not finish ({len(unfinished)}; counted as stops, never '
                     f'caught; reasons in the private results file): {", ".join(unfinished)}')
    notes.append('labels are E8\'s Opus judge on one known error per item: a stop for another '
                 'reason is not scored (stopped_* counts it), and recall_per_case weighs each '
                 'case the same')
    notes.append(f'per-item outcomes (private): {gate_set.SET_NAME}/results/{OUTCOMES[method]} '
                 f'in the storyforge-evals repo')
    return SuiteOutput(metrics=metrics, by_code=by_code, gates=gates, notes=notes)
