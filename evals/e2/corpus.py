"""E2 on the E1 corpus: detection of real errors in the author's books.

Each E1 prose case (holdout excluded) becomes an E2 case run against the book
tree where the error is present — the fix's parent, or HEAD when unfixed — with
the detector told which scene carries it. The control is the tree at the fix
commit, where the error is gone: a flag it also raises (same scene and check)
is baseline noise. An unfixed case has no clean tree, so no control.

E1 spans name the HEAD slug in ``scene``; inside a historical tree the scene is
the file's own stem, so spans are rewritten to that. Trees that predate
``reference/scenes.csv`` cannot be checked by current Storyforge and are
reported as excluded, like E8's.

``e2.score`` keys controls by ``injection.scene``; here every case has its own
control tree, so each case's control is keyed by its id instead.
"""

from __future__ import annotations

import os
import shutil
import subprocess

import e1
from e8 import materialize

CODE_BY_CATEGORY = {'physical_state': 'PHY', 'timeline': 'TIM', 'knowledge': 'KNO'}


def _has(repo_dir: str, commit: str, path: str) -> bool:
    return subprocess.run(['git', '-C', repo_dir, 'cat-file', '-e', f'{commit}:{path}'],
                          capture_output=True).returncode == 0


def _stem(span: dict) -> str:
    return os.path.splitext(os.path.basename(span['path']))[0]


def to_e2(case: dict) -> dict | None:
    """The E2 shape of an E1 case, or None when it has no prose span to check."""
    contradicted = [{'scene': _stem(s), 'quote': s['quote']} for s in case['contradicted']
                    if s.get('source', 'prose') == 'prose']
    if not contradicted:
        return None
    established = [{'scene': _stem(s), 'quote': s['quote']} for s in case['established']
                   if s.get('source', 'prose') == 'prose']
    return {'id': case['id'], 'code': case['code'], 'summary': case['summary'],
            'established': established, 'contradicted': contradicted,
            'injection': {'scene': case['id']}, 'target': contradicted[0]['scene']}


def select(root: str | None = None) -> tuple[list[dict], dict[str, list[str]]]:
    """E2-shaped cases with ``repo``, ``tree`` and ``control`` commits, and the
    excluded ids by reason."""
    root = root or e1.corpus_dir()
    held = set(e1.load_holdout())
    cases, excluded = [], {}
    for case in e1.load_cases():
        if case['level'] != 'prose':
            continue
        reason = None
        repo_dir = os.path.join(root, case['repo'])
        shaped = to_e2(case)
        tree = case['contradicted'][0]['commit']
        if case['id'] in held:
            reason = 'holdout'
        elif shaped is None:
            reason = 'no prose span on the contradicted side'
        elif not os.path.isdir(os.path.join(repo_dir, '.git')):
            reason = f'{case["repo"]} not cloned'
        elif not _has(repo_dir, tree, 'reference/scenes.csv'):
            reason = 'tree predates reference/scenes.csv'
        elif not _has(repo_dir, tree, f'scenes/{shaped["target"]}.md'):
            reason = 'contradicted scene file not in its tree'
        if reason:
            excluded.setdefault(reason, []).append(case['id'])
            continue
        fix = case['fix']
        shaped.update(repo=case['repo'], tree=tree,
                      control=fix['commit'] if fix['status'] != 'unfixed' else None)
        cases.append(shaped)
    return cases, excluded


def tree_dir(work_dir: str, repo: str, commit: str, root: str | None = None) -> str:
    repo_dir = os.path.join(root or e1.corpus_dir(), repo)
    return materialize(repo_dir, commit, os.path.join(work_dir, 'trees', f'{repo}-{commit[:12]}'))


def run(cases: list[dict], detector, work_dir: str, prepare_tree=None,
        root: str | None = None) -> tuple[dict, dict]:
    """Run ``detector`` on each case's tree and control; (case_flags, control_flags).

    ``prepare_tree(project_dir)`` runs once per distinct tree before any copy is
    taken (the drift check needs every scene's time cues first). Each detector
    call gets its own copy, since detectors write into the project."""
    prepared = set()

    def copy_for(repo, commit, name):
        base = tree_dir(work_dir, repo, commit, root)
        if prepare_tree and base not in prepared:
            prepare_tree(base)
            prepared.add(base)
        dest = os.path.join(work_dir, 'runs', name)
        shutil.copytree(base, dest)
        return dest

    case_flags, control_flags = {}, {}
    for case in cases:
        project = copy_for(case['repo'], case['tree'], case['id'])
        case_flags[case['id']] = detector(project, [case['target']],
                                          os.path.join(work_dir, 'logs', case['id']))
        if case['control']:
            control = copy_for(case['repo'], case['control'], f'{case["id"]}-control')
            scene = case['target'] if os.path.isfile(
                os.path.join(control, 'scenes', f'{case["target"]}.md')) else None
            control_flags[case['id']] = detector(control, [scene] if scene else [],
                                                 os.path.join(work_dir, 'logs', f'{case["id"]}-control'))
    return case_flags, control_flags


def validate_detector(project_dir: str, scenes: list[str], log_dir: str) -> list[dict]:
    """Storyforge's deterministic continuity checks (physical state, timeline,
    knowledge) over the project's CSVs. Not scoped to ``scenes``: it reports
    what it reports, and the scorer decides what lands."""
    from storyforge.elaborate import validate_structure
    return [{'scene_id': c.get('scene_id', ''), 'code': CODE_BY_CATEGORY[c['category']],
             'check': c['check'], 'message': c['message']}
            for c in validate_structure(os.path.join(project_dir, 'reference'))['checks']
            if not c['passed'] and c['category'] in CODE_BY_CATEGORY]


def bootstrap_cues(project_dir: str) -> None:
    """Read time cues for every scene, so the drift check has a calendar to
    compare against. Raises if any scene's read fails: a gap in the calendar
    would read as agreement."""
    from storyforge.common import select_model
    from storyforge.timeline import cue_prompts, extract_cues, reading_order
    order = reading_order(project_dir)
    wanted = list(cue_prompts(project_dir, order))  # scenes with any text to read
    cues = extract_cues(project_dir, wanted, select_model('extraction'),
                        os.path.join(project_dir, 'working', 'logs'))
    missing = [s for s in wanted if s not in cues]
    if missing:
        raise RuntimeError(f'time cues failed for {len(missing)} scene(s) in {project_dir}: '
                           f'{", ".join(missing[:5])}')


def suite_output(detector_name: str, cases: list[dict], excluded: dict, case_flags: dict,
                 control_flags: dict):
    """Score and gate the way ``e2-carol`` does; the plan's checker gate."""
    import e2
    from harness import Gate, SuiteOutput
    result = e2.score(cases, case_flags, control_flags, order=[])
    gates = [Gate(f'recall_{code}', result['by_code'].get(code, {}).get('recall_code_match', 0.0),
                  '>=', e2.RECALL_GATE) for code in e2.GATED_CODES]
    gates.append(Gate('precision', e2.precision_gate_value(result['metrics']), '>=', e2.PRECISION_GATE))
    found = sorted(cid for cid, hit in result['detected'].items() if hit)
    notes = [f'detector: {detector_name}',
             f'detected {len(found)} of {result["metrics"]["cases"]}: {", ".join(found) or "none"}']
    notes += [f'excluded {len(ids)}: {reason}' for reason, ids in sorted(excluded.items())]
    return SuiteOutput(metrics=result['metrics'], by_code=result['by_code'], gates=gates, notes=notes)
