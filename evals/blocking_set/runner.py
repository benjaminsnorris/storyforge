"""Running a blocking check over the blocking set, for the suites that
measure one (`evals/suites/blocking_set.py`: the whole-scene blocking read;
`evals/suites/blocking_set_sheet.py`: the stage sheet, #647).

Both score the same way (`blocking_set.score`), gate on their own recorded
values, and write per-case outcomes to the private set's `results/` (never
to this repo). Run side by side, the read first (suites run in name order),
the sheet's notes compare the two case by case, in counts and case ids.
"""

from __future__ import annotations

import json
import os

import blocking_set
from harness import Gate, SuiteOutput

#: What each method's per-case outcomes file is called in `results/`
OUTCOMES = {'read': 'latest.json', 'stage-sheet': 'latest-stage-sheet.json'}


def make_project(work_dir: str, book: str, scenes: list[dict]) -> str:
    """A project with just `reference/scenes.csv` (id and pov): each check
    takes the prose as given and reads only the POV from the project (the
    stage sheet would read `time_of_day` too, which the set doesn't carry,
    and the world table's defaults)."""
    project = os.path.join(work_dir, book)
    os.makedirs(os.path.join(project, 'reference'), exist_ok=True)
    with open(os.path.join(project, 'reference', 'scenes.csv'), 'w', encoding='utf-8',
              newline='') as f:
        f.write('id|pov\n')
        for s in scenes:
            f.write(f'{s["scene"]}|{s.get("pov", "")}\n')
    return project


def _check_one(method: str, project: str, scene: dict):
    if method == 'stage-sheet':
        from storyforge import stage_sheet
        # each scene stands alone: the set's scenes aren't consecutive
        return stage_sheet.check_stage_sheet(project, scene['scene'], prose=scene['text'],
                                             carry=False)
    from storyforge import blocking
    return blocking.check_blocking(project, scene['scene'], prose=scene['text'])


def check_all(scenes: list[dict], work_dir: str, method: str = 'read'
              ) -> tuple[dict[tuple[str, str], list[dict]], dict[tuple[str, str], object]]:
    """Run `method` on every scene: its findings as ``{"quotes", "verified",
    "explanation"}`` per (book, scene), and each scene's result. A scene the
    check couldn't finish raises, naming how many: a scene left out would
    read as one with no flags."""
    from storyforge.runner import run_parallel
    projects = {book: make_project(work_dir, book, [s for s in scenes if s['book'] == book])
                for book in sorted({s['book'] for s in scenes})}
    by_label = {f'{s["book"]}/{s["scene"]}': s for s in scenes}

    def check(label):
        s = by_label[label]
        return _check_one(method, projects[s['book']], s)

    results = run_parallel(sorted(by_label), check, label='scene')
    failed = sorted(k for k in by_label
                    if results.get(k) is None or isinstance(results.get(k), BaseException))
    if failed:
        # The exception's type only: its message can carry the reply, which
        # quotes the private prose, and this message reaches the report
        first = results.get(failed[0])
        what = 'blocking read' if method == 'read' else 'stage sheet'
        raise RuntimeError(f'the {what} did not finish on {len(failed)} scene(s); '
                           f'first: {type(first).__name__ if first is not None else "no result"}')
    flags, by_key = {}, {}
    for label, result in results.items():
        s = by_label[label]
        by_key[(s['book'], s['scene'])] = result
        flags[(s['book'], s['scene'])] = [
            {'quotes': [f.scene_quote, f.established_quote], 'verified': verified,
             'explanation': f.explanation}
            for verified, group in ((True, result.findings), (False, result.unverified))
            for f in group]
    return flags, by_key


def floor_gates(metrics: dict, floors: dict) -> tuple[list[Gate], list[str]]:
    gates, notes = [], []
    for name, floor in floors.items():
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


def write_outcomes(path: str, cases, outcomes, flags, file_name: str,
                   extra: dict | None = None) -> str:
    """The run's per-case outcomes beside the private set (gitignored there)."""
    out_dir = os.path.join(path, 'results')
    os.makedirs(out_dir, exist_ok=True)
    found = {f'{b}/{s}': v for (b, s), v in flags.items()}
    data = {'cases': [{**o, 'category': c['category'], 'verdict': c['verdict'],
                       'scene': f'{c["book"]}/{c["scene"]}'}
                      for c, o in zip(cases, outcomes)],
            'findings': found, **(extra or {})}
    file = os.path.join(out_dir, file_name)
    with open(file, 'w', encoding='utf-8') as f:
        json.dump(data, f, indent=1, ensure_ascii=False)
        f.write('\n')
    return file


def compare(path: str, cases, outcomes, other: str = 'read') -> list[str]:
    """Notes comparing this run's catches with `other`'s last run on the set
    (its outcomes file in `results/`), case by case, in counts and ids. One
    line saying why when there's nothing to compare with."""
    file = os.path.join(path, 'results', OUTCOMES[other])
    try:
        with open(file, encoding='utf-8') as f:
            theirs = {c['id']: c for c in json.load(f)['cases']}
    except (OSError, ValueError, KeyError, TypeError):
        return [f'side by side: no {other} run to compare with (run '
                f'`python3 evals/run.py --suite blocking-set --suite blocking-set-sheet`)']
    in_scene = [(c, o) for c, o in zip(cases, outcomes)
                if c['verdict'] == 'fixed' and c.get('scope', 'scene') == 'scene']
    missing = [c['id'] for c, _ in in_scene if c['id'] not in theirs]
    if missing:
        return [f'side by side: the {other} run has no outcome for {len(missing)} case(s) '
                f'(another version of the set?): not compared']
    both = [c['id'] for c, o in in_scene if o['caught'] and theirs[c['id']]['caught']]
    only_here = [c['id'] for c, o in in_scene if o['caught'] and not theirs[c['id']]['caught']]
    only_there = [c['id'] for c, o in in_scene if not o['caught'] and theirs[c['id']]['caught']]
    lines = [f'side by side with the {other} (its last run): caught by both {len(both)}, '
             f'only here {len(only_here)}, only by the {other} {len(only_there)}, of '
             f'{len(in_scene)}']
    if only_there:
        lines.append(f'only the {other} caught: {", ".join(only_there)}')
    if only_here:
        lines.append(f'only this caught: {", ".join(only_here)}')
    left_here = sum(1 for c, o in zip(cases, outcomes) if c['verdict'] == 'left' and o['caught'])
    left_there = sum(1 for c in cases if c['verdict'] == 'left'
                     and theirs.get(c['id'], {}).get('caught'))
    lines.append(f'left readings flagged: here {left_here}, by the {other} {left_there}')
    return lines


def run(ctx, method: str, floors: dict, min_cases: int) -> SuiteOutput:
    path = blocking_set.set_dir()
    cases, scenes = blocking_set.load(path)
    problems = blocking_set.validate(cases, scenes)
    if problems:
        # Scoring a malformed set would give a confident number over
        # whatever parsed; the problems name ids, never the prose
        raise RuntimeError(f'the blocking set has {len(problems)} problem(s), e.g. {problems[0]}')
    flags, results = check_all(scenes, ctx.work_dir, method)
    metrics, outcomes = blocking_set.score(cases, scenes, flags)
    extra = None
    if method == 'stage-sheet':
        notes_by_scene = {f'{b}/{s}': r.notes for (b, s), r in results.items() if r.notes}
        metrics['events'] = sum(r.events for r in results.values())
        metrics['questions_asked'] = sum(r.asked for r in results.values())
        metrics['scenes_with_unchecked'] = len(notes_by_scene)
        extra = {'not_checked': notes_by_scene}
    write_outcomes(path, cases, outcomes, flags, OUTCOMES[method], extra)
    gates, notes = floor_gates(metrics, floors)
    gates.append(Gate('cases', metrics['cases'], '>=', min_cases))
    missed = [o['id'] for c, o in zip(cases, outcomes)
              if c['verdict'] == 'fixed' and c.get('scope', 'scene') == 'scene' and not o['caught']]
    notes.append(f'missed ({len(missed)}): {", ".join(missed)}' if missed else 'missed: none')
    flagged_left = [o['id'] for c, o in zip(cases, outcomes) if c['verdict'] == 'left' and o['caught']]
    if flagged_left:
        notes.append(f'flagged a reading left as plausible: {", ".join(flagged_left)}')
    notes.append(f'book-scope cases (need other scenes; not in recall): '
                 f'{metrics["book_scope_caught"]} of {metrics["book_scope_cases"]} caught')
    if method == 'stage-sheet':
        notes += compare(path, cases, outcomes, 'read')
        if metrics['scenes_with_unchecked']:
            notes.append(f'{metrics["scenes_with_unchecked"]} scene(s) had something the '
                         f'sheet could not check (counts per scene, private: not_checked in '
                         f'results/{OUTCOMES[method]})')
    notes.append(f'per-case outcomes and findings (private): blocking-set/results/'
                 f'{OUTCOMES[method]} in the storyforge-evals repo')
    return SuiteOutput(metrics=metrics, gates=gates, notes=notes)
