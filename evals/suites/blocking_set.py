"""The blocking set (#646): today's blocking read (`storyforge.blocking`,
two readings per scene) against known blocking slips from *A Year and a
Day* (gawain) and *Wrath Like Smoke* (iliad-adult), and clean scenes for
false alarms. See ``evals/blocking_set``.

The set and its recordings are private (the author's unpublished prose) and
live in the storyforge-evals repo; a machine without it errors here, saying
where to put it. The suite writes each case's outcome, with the findings'
quotes, to ``blocking-set/results/latest.json`` there (gitignored), never to
this repo: notes carry counts and case ids only.
"""

from __future__ import annotations

import json
import os

import blocking_set
from harness import Gate, Suite, SuiteOutput

NAME = 'blocking-set'
#: The set must keep its size: the plan measures the stage sheet on "gawain's
#: 35 and Wrath's 70"
MIN_CASES = 100

#: The gates: the recorded baseline's values, each to be held exactly
#: (#488: a gain moves its floor up in the same commit; a drop is a
#: decision). `None` until the baseline is recorded: the gate then fails and
#: the note says what to write here.
FLOORS: dict[str, float | None] = {
    'recall': None,
    'recall_hands': None, 'recall_posture': None, 'recall_sightline': None,
    'recall_worn': None, 'recall_position': None, 'recall_light': None,
    'recall_other': None,
    'false_alarms_per_10k': None,
    'left_flagged': None,
    'flags': None,
}


def _project(work_dir: str, book: str, scenes: list[dict]) -> str:
    """A project with just `reference/scenes.csv` (id and pov): the blocking
    read takes the prose as given and reads only the POV from the project."""
    project = os.path.join(work_dir, book)
    os.makedirs(os.path.join(project, 'reference'), exist_ok=True)
    with open(os.path.join(project, 'reference', 'scenes.csv'), 'w', encoding='utf-8',
              newline='') as f:
        f.write('id|pov\n')
        for s in scenes:
            f.write(f'{s["scene"]}|{s.get("pov", "")}\n')
    return project


def check_all(scenes: list[dict], work_dir: str) -> dict[tuple[str, str], list[dict]]:
    """Run the blocking read on every scene; its findings as
    ``{"quotes", "verified", "explanation"}`` per (book, scene). A scene the
    read couldn't finish raises, naming how many: a scene left out would
    read as one with no flags."""
    from storyforge import blocking
    from storyforge.runner import run_parallel
    projects = {book: _project(work_dir, book, [s for s in scenes if s['book'] == book])
                for book in sorted({s['book'] for s in scenes})}
    by_label = {f'{s["book"]}/{s["scene"]}': s for s in scenes}

    def check(label):
        s = by_label[label]
        return blocking.check_blocking(projects[s['book']], s['scene'], prose=s['text'])

    results = run_parallel(sorted(by_label), check, label='scene')
    failed = sorted(k for k in by_label if not isinstance(results.get(k), blocking.BlockingResult))
    if failed:
        # The exception's type only: its message can carry the reply, which
        # quotes the private prose, and this message reaches the report
        first = results.get(failed[0])
        raise RuntimeError(f'the blocking read did not finish on {len(failed)} scene(s); '
                           f'first: {type(first).__name__ if first is not None else "no result"}')
    flags = {}
    for label, result in results.items():
        s = by_label[label]
        flags[(s['book'], s['scene'])] = [
            {'quotes': [f.scene_quote, f.established_quote], 'verified': verified,
             'explanation': f.explanation}
            for verified, group in ((True, result.findings), (False, result.unverified))
            for f in group]
    return flags


def floor_gates(metrics: dict) -> tuple[list[Gate], list[str]]:
    gates, notes = [], []
    for name, floor in FLOORS.items():
        value = metrics.get(name)
        gates.append(Gate(name, -1 if value is None else value, '==',
                          -1 if floor is None else floor))
        if value is None:
            notes.append(f'{name}: FLOORS has {floor} but the run has no such metric')
        elif floor is None:
            notes.append(f'{name} {value}: no floor recorded; set FLOORS[{name!r}] = {value} '
                         f'with the baseline')
        elif value != floor:
            notes.append(f'{name} {value}, FLOORS {floor}: '
                         + ('raise its floor in the same commit' if value > floor and name.startswith('recall')
                            else 'a change; moving the floor is a decision (see FLOORS)'))
    return gates, notes


def _write_outcomes(path: str, cases, outcomes, flags) -> str:
    """The run's per-case outcomes beside the private set (gitignored there)."""
    out_dir = os.path.join(path, 'results')
    os.makedirs(out_dir, exist_ok=True)
    found = {f'{b}/{s}': v for (b, s), v in flags.items()}
    data = {'cases': [{**o, 'category': c['category'], 'verdict': c['verdict'],
                       'scene': f'{c["book"]}/{c["scene"]}'}
                      for c, o in zip(cases, outcomes)],
            'findings': found}
    file = os.path.join(out_dir, 'latest.json')
    with open(file, 'w', encoding='utf-8') as f:
        json.dump(data, f, indent=1, ensure_ascii=False)
        f.write('\n')
    return file


def run(ctx):
    path = blocking_set.set_dir()
    cases, scenes = blocking_set.load(path)
    problems = blocking_set.validate(cases, scenes)
    if problems:
        # Scoring a malformed set would give a confident number over
        # whatever parsed; the problems name ids, never the prose
        raise RuntimeError(f'the blocking set has {len(problems)} problem(s), e.g. {problems[0]}')
    flags = check_all(scenes, ctx.work_dir)
    metrics, outcomes = blocking_set.score(cases, scenes, flags)
    _write_outcomes(path, cases, outcomes, flags)
    gates, notes = floor_gates(metrics)
    gates.append(Gate('cases', metrics['cases'], '>=', MIN_CASES))
    missed = [o['id'] for c, o in zip(cases, outcomes)
              if c['verdict'] == 'fixed' and c.get('scope', 'scene') == 'scene' and not o['caught']]
    notes.append(f'missed ({len(missed)}): {", ".join(missed)}' if missed else 'missed: none')
    flagged_left = [o['id'] for c, o in zip(cases, outcomes) if c['verdict'] == 'left' and o['caught']]
    if flagged_left:
        notes.append(f'flagged a reading left as plausible: {", ".join(flagged_left)}')
    notes.append(f'book-scope cases (need other scenes; not in recall): '
                 f'{metrics["book_scope_caught"]} of {metrics["book_scope_cases"]} caught')
    notes.append('per-case outcomes and findings (private): blocking-set/results/latest.json '
                 'in the storyforge-evals repo')
    return SuiteOutput(metrics=metrics, gates=gates, notes=notes)


SUITE = Suite(NAME, 'Blocking read vs known blocking slips (gawain, Wrath) and clean scenes; '
                    'private set', run, cassettes=lambda: blocking_set.cassettes_dir(NAME))
