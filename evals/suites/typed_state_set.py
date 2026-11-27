"""The typed-state set (#744): the gate's typed-state checks replayed on
*Wrath Like Smoke*'s overnight gate runs, each finding scored against a
reader's verdict. See ``evals/typed_state_set``.

Free in every mode: the extraction is answered from each run's saved typed
state, and nothing else calls a model. The set is private (the author's
unpublished prose) and lives in the storyforge-evals repo; without it the
suite is unavailable (``stale``, exit code unaffected). Per-run findings,
with quotes, go to ``typed-state-set/results/latest.json`` there; notes here
carry label ids, scene ids and counts only.

Built 2026-11-26 from each scene's final gate run (43 runs; the earlier 57
runs' replies are in the gitignored gate logs), so 17 of the review's 65
typed-state verdicts are on a run in the set: 14 possession, 2 injury, 1
life, all false or debatable. Recall is not measured: the one real
typed-state catch (a time finding) was in a first run.
"""

from __future__ import annotations

import json
import os
from concurrent.futures import ProcessPoolExecutor

import typed_state_set as tss
from blocking_set.runner import floor_gates
from harness import Suite, SuiteOutput

NAME = 'typed-state-set'

#: The gates: today's values, each held exactly (#488). A fall in a
#: findings, false or unlabelled count is a gain, as is a rise in a real
#: count; a gain moves the value here in the same commit, a loss is a
#: decision. Measured 2026-11-26 on main before #732 (possession: 14
#: findings, all false) and #733 (injury decay, deaths by id): every finding
#: the replay makes is one the review labelled, and none is real. Measured
#: again with #732 (owner-scoped objects; an unowned name held again in a
#: later scene a note): possession makes none. Measured again with #733 (a
#: serious injury carried only when its scene shows it lasting; a death and
#: a presence bind one character id; a presence in the death's paragraph is
#: the death): injury keeps the one debatable finding, life makes none.
#: #748 changed the extraction prompt (owners named, one record per
#: handover), which this set can't measure: it replays the logged replies.
#: A one-off re-extraction of its 43 scenes (docs/history.md, #748) made 0
#: possession findings once a person's own bare kind stopped blocking
#: across scenes.
FLOORS: dict[str, float | None] = {
    'findings': 1, 'false_alarms': 0, 'debatable_found': 1, 'real_kept': 0,
    'unlabelled': 0,
    'possession_findings': 0, 'possession_false': 0,
    'injury_findings': 1, 'injury_false': 0, 'injury_debatable': 1,
    'life_findings': 0, 'life_false': 0,
    'time_findings': 0, 'travel_findings': 0, 'knowledge_findings': 0,
    'names_findings': 0, 'sky_findings': 0,
}
#: Processes replaying runs at once
WORKERS = 8
#: Metrics where a rise is the gain
HIGHER_IS_BETTER = {'real_kept'} | {f'{c}_real' for c in tss.CHECKS}

#: The set FLOORS were measured on (`typed_state_set.fingerprint`): another
#: set errors. Rebuilding sets it again
RECORDED_SET = '711d394923d5f6d40e1056e79b3aec055837d8aa9b6275660c77550ecf9a816e'


def run_set(path: str, work_dir: str) -> tuple[dict, dict[str, list[dict]], dict]:
    """Replay every run; (the set, findings by run id, notes by run id). A
    run that can't be replayed raises, naming it: a run left out would read
    as one with no findings."""
    data = tss.load(path)
    problems = tss.validate(data)
    if problems:
        raise RuntimeError(f'the typed-state set has {len(problems)} problem(s), e.g. '
                           f'{problems[0]}')
    runs = data['runs']
    dests = [os.path.join(work_dir, f'run-{n:03d}') for n in range(len(runs))]
    # A run is seconds of regex over the book (a late scene about 12), so
    # processes, not threads: about a minute instead of three
    with ProcessPoolExecutor(max_workers=max(1, min(WORKERS, os.cpu_count() or 1))) as pool:
        outs = list(pool.map(tss.replay_run, [path] * len(runs), runs, dests))
    failed = [f'{run["id"]} ({out["error"]})' for run, out in zip(runs, outs) if 'error' in out]
    if failed:
        raise RuntimeError(f'{len(failed)} run(s) could not be replayed: {", ".join(failed)}')
    found = {run['id']: out['findings'] for run, out in zip(runs, outs)}
    notes = {run['id']: out['notes'] for run, out in zip(runs, outs)}
    return data, found, notes


def run(ctx):
    path = tss.set_dir()
    got = tss.fingerprint(path)
    if RECORDED_SET and got != RECORDED_SET:
        raise RuntimeError(
            f'the typed-state set at {path} is not the one FLOORS were measured on (fingerprint '
            f'{got[:12]}, measured {RECORDED_SET[:12]}): check out the storyforge-evals commit '
            f'they were measured on, or measure again and set FLOORS and RECORDED_SET')
    data, found, run_notes = run_set(path, ctx.work_dir)
    metrics, ids = tss.score(data, found)
    out_dir = os.path.join(path, 'results')
    os.makedirs(out_dir, exist_ok=True)
    with open(os.path.join(out_dir, 'latest.json'), 'w', encoding='utf-8') as f:
        json.dump({'metrics': metrics, 'ids': ids, 'findings': found, 'notes': run_notes},
                  f, indent=1, ensure_ascii=False)
        f.write('\n')
    gates, notes = floor_gates(metrics, FLOORS, HIGHER_IS_BETTER)
    by_check = [f'{c} {int(metrics[f"{c}_findings"])} ({int(metrics[f"{c}_false"])} false, '
                f'{int(metrics[f"{c}_debatable"])} debatable, {int(metrics[f"{c}_real"])} real, '
                f'{int(metrics[f"{c}_unlabelled"])} unlabelled)'
                for c in tss.CHECKS if metrics[f'{c}_findings']]
    notes.append('findings by check: ' + ('; '.join(by_check) if by_check else 'none'))
    for key, what in (('false', 'false alarms still made'), ('debatable', 'debatable still made'),
                      ('real', 'real catches kept'), ('real_missed', 'real catches lost'),
                      ('cleared', 'labelled false or debatable findings no longer made'),
                      ('unlabelled', 'findings no label covers (a new kind: read them in the '
                                     'private results)')):
        if ids[key]:
            notes.append(f'{what} ({len(ids[key])}): {", ".join(ids[key])}')
    left = len(data['labels']) - int(metrics['labels_in_set'])
    notes.append(f'{int(metrics["labels_in_set"])} of {len(data["labels"])} labels are on a run '
                 f'in the set; {left} are on earlier gate runs not in it '
                 f'({len(data["not_replayable"])} runs left out, each with why, in set.json)')
    if not any(lab['verdict'] == 'real' for lab in tss.replayable(data)):
        notes.append('recall is not measured: no real typed-state catch is on a run in the set')
    unchecked = sum(1 for ns in run_notes.values() if any('not checked' in n for n in ns))
    notes.append(f'{unchecked} of {len(run_notes)} runs had something a check could not '
                 f'check (per run, private: notes in results/latest.json)')
    notes.append('per-run findings (private): typed-state-set/results/latest.json in the '
                 'storyforge-evals repo')
    return SuiteOutput(metrics=metrics, gates=gates, notes=notes)


SUITE = Suite(NAME, 'Typed-state checks replayed on Wrath\'s gate runs vs a reader\'s verdicts; '
                    'private set, free', run,
              cassettes=lambda run: os.path.join(tss.set_dir(), 'cassettes', run or '', NAME))
