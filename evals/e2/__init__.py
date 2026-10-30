"""E2 — the detection benchmark: labelled errors injected into public-domain
prose, a detector run over each edited book, recall and precision per code.

One directory per book, ``evals/fixtures/e2-<book>/``:

- ``book/``: a Storyforge project, the scene prose plus the ledger (the
  reference CSVs and timeline cues) extracted from the clean text.
- ``injections.json``: ``{"book": <slug>, "cases": [<case>, ...]}``.

A case::

    {
      "id": "e2-carol-001",
      "code": "TIM",                       # from harness.ERROR_CODES
      "summary": "...",
      "established": [<span>, ...],        # the facts the edit contradicts
      "contradicted": [<span>, ...],       # the injected text
      "injection": {"scene": <id>, "find": <verbatim>, "replace": <text>}
    }

A span is ``{"scene": <id>, "quote": <verbatim prose>}``, the shape E1 uses
without the git fields, so one scorer can serve both. An established span may
also name the gold ``commitment`` it comes from. ``find`` occurs exactly once
in its scene, each contradicted quote is part of ``replace``, and every
established quote is still in the book after the edit.

A benign case (``"benign": true``, ``"code": null``, no spans) is an edit that
contradicts nothing. Any flag on it is a false positive, so a detector that
merely notices which scene changed can't pass the precision gate.

Each case runs on its own copy of the book with one edit, and the detector is
told which scene changed, as Storyforge's own checks are after an edit. The
same scene is also run unedited as a control: a flag the control also raises
(same scene and check) is the detector's baseline noise, not a detection.

A flag counts as a detection only if it lands on the case's scenes and names
the case's code; the gates use that code-matched recall. Location alone is
reported as ``recall``. Flags are counted once per distinct (scene, check,
message), however many cases raised them.
"""

from __future__ import annotations

import json
import os
import shutil
from typing import Callable

EVALS_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
FIXTURES_DIR = os.path.join(EVALS_DIR, 'fixtures')
ERROR_CODES = ('PHY', 'TIM', 'KNO', 'REL', 'TRT', 'WLD', 'PRM', 'VOI')
# The plan's shipping gate for the checker (rethink plan §4.2)
GATED_CODES = ('PHY', 'TIM', 'KNO', 'REL', 'TRT')
RECALL_GATE = 0.9
PRECISION_GATE = 0.8
# Below this many distinct flags, precision is noise and the gate fails
MIN_FLAGS_FOR_PRECISION = 5

# A detector reads a project after an edit and returns flags
# {'scene_id', 'code', 'check', 'message'}
Detector = Callable[[str, list[str], str], list[dict]]


def fixture_dir(book: str) -> str:
    return os.path.join(FIXTURES_DIR, f'e2-{book}')


def load_cases(book: str) -> list[dict]:
    with open(os.path.join(fixture_dir(book), 'injections.json'), encoding='utf-8') as f:
        return json.load(f)['cases']


def _scene_text(book_dir: str, scene: str) -> str:
    with open(os.path.join(book_dir, 'scenes', f'{scene}.md'), encoding='utf-8') as f:
        return f.read()


def _apply(text: str, inj: dict) -> str:
    return text.replace(inj['find'], inj['replace'])


def validate_cases(cases: list[dict], book_dir: str) -> list[str]:
    """Problems with *cases* against the book's prose; empty when sound."""
    problems = []
    ids = [c.get('id') for c in cases]
    for dup in sorted({i for i in ids if ids.count(i) > 1}):
        problems.append(f'duplicate id {dup}')
    for case in cases:
        cid = case.get('id', '?')
        benign = case.get('benign', False)
        if benign:
            if case.get('code') is not None or case.get('established') or case.get('contradicted'):
                problems.append(f'{cid}: a benign case has no code and no spans')
        elif case.get('code') not in ERROR_CODES:
            problems.append(f'{cid}: unknown code {case.get("code")!r}')
        inj = case.get('injection') or {}
        try:
            text = _scene_text(book_dir, inj.get('scene', ''))
        except OSError:
            problems.append(f'{cid}: no scene {inj.get("scene")!r}')
            continue
        count = text.count(inj.get('find') or '\0')
        if count != 1:
            problems.append(f'{cid}: "find" occurs {count} times in {inj["scene"]}')
            continue
        if benign:
            continue
        if not case.get('contradicted'):
            problems.append(f'{cid}: no contradicted span')
        for span in case.get('contradicted', []):
            if span.get('scene') != inj.get('scene') or span.get('quote', '\0') not in inj.get('replace', ''):
                problems.append(f'{cid}: contradicted quote is not in the injected text')
        for span in case.get('established', []):
            scene = span.get('scene', '')
            try:
                source = _scene_text(book_dir, scene)
            except OSError:
                problems.append(f'{cid}: no scene {scene!r}')
                continue
            if span.get('quote', '\0') not in source:
                problems.append(f'{cid}: established quote not found in {scene}')
            elif scene == inj['scene'] and span['quote'] not in _apply(source, inj):
                problems.append(f'{cid}: the edit overwrites its own established quote in {scene}')
    return problems


def copy_book(book_dir: str, dest: str, case: dict | None = None) -> str:
    """Copy the book to *dest*, applying *case*'s injection if given, with
    its registries moved into the ledger (``harness.migrate_tree``)."""
    from harness import migrate_tree
    shutil.copytree(book_dir, dest)
    migrate_tree(dest, os.path.basename(os.path.dirname(book_dir)))
    if case:
        inj = case['injection']
        path = os.path.join(dest, 'scenes', f'{inj["scene"]}.md')
        with open(path, encoding='utf-8') as f:
            text = f.read()
        if text.count(inj['find']) != 1:
            raise ValueError(f'{case["id"]}: "find" is not unique in {inj["scene"]}')
        with open(path, 'w', encoding='utf-8') as f:
            f.write(_apply(text, inj))
    return dest


def case_scenes(case: dict, order: list[str]) -> set[str]:
    """Scenes where a flag counts as finding *case*: the contradicted and
    established scenes, and the scene after each contradicted one (a check
    on a changed scene may surface at its neighbour)."""
    scenes = {s['scene'] for s in case['contradicted']} | {s['scene'] for s in case['established']}
    for span in case['contradicted']:
        if span['scene'] in order:
            i = order.index(span['scene'])
            if i + 1 < len(order):
                scenes.add(order[i + 1])
    return scenes


def _key(flag: dict) -> tuple[str, str]:
    return flag.get('scene_id', ''), flag.get('check', '')


def _identity(flag: dict) -> tuple[str, str, str]:
    return flag.get('scene_id', ''), flag.get('check', ''), flag.get('message', '')


def score(cases: list[dict], case_flags: dict[str, list[dict]],
          control_flags: dict[str, list[dict]], order: list[str]) -> dict:
    """Recall and precision, overall and per code.

    *case_flags*: case id → the detector's flags on the edited book.
    *control_flags*: scene → its flags on the unedited book. A case flag the
    control for its scene also raised is not counted at all; every control
    flag is a false positive (the book has no errors).

    A flag is true when it lands on its case's scenes with the case's code.
    Everything else is false: a flag elsewhere, a flag with the wrong code,
    any flag on a benign case. Each distinct flag counts once.
    """
    true_flags, false_flags = {}, {}
    detected, code_matched = {}, {}
    real = [c for c in cases if not c.get('benign')]
    benign = [c for c in cases if c.get('benign')]
    benign_flagged = 0
    for case in cases:
        scene = case['injection']['scene']
        baseline = {_key(f) for f in control_flags.get(scene, [])}
        new = [f for f in case_flags.get(case['id'], []) if _key(f) not in baseline]
        if case.get('benign'):
            benign_flagged += bool(new)
            for f in new:
                false_flags.setdefault(_identity(f), f)
            continue
        where = case_scenes(case, order)
        located = [f for f in new if f.get('scene_id') in where]
        hits = [f for f in located if f.get('code') == case['code']]
        for f in new:
            (true_flags if f in hits else false_flags).setdefault(_identity(f), f)
        detected[case['id']] = bool(located)
        code_matched[case['id']] = bool(hits)
    for flags in control_flags.values():
        for f in flags:
            false_flags.setdefault(_identity(f), f)
    # A flag true for one case and false for another counts as true
    for key in true_flags:
        false_flags.pop(key, None)

    def ratio(n, d):
        return round(n / d, 4) if d else 0.0

    by_code = {}
    for code in ERROR_CODES:
        mine = [c for c in real if c['code'] == code]
        tp = sum(1 for f in true_flags.values() if f.get('code') == code)
        fp = sum(1 for f in false_flags.values() if f.get('code') == code)
        if not mine and not tp + fp:
            continue
        entry = {'cases': len(mine),
                 'recall': ratio(sum(detected[c['id']] for c in mine), len(mine)),
                 'recall_code_match': ratio(sum(code_matched[c['id']] for c in mine), len(mine))}
        if tp + fp:
            entry['precision'] = ratio(tp, tp + fp)
        by_code[code] = entry
    flagged = len(true_flags) + len(false_flags)
    return {
        'metrics': {
            'cases': len(real),
            'benign_cases': len(benign),
            'recall': ratio(sum(detected.values()), len(real)),
            'recall_code_match': ratio(sum(code_matched.values()), len(real)),
            'precision': ratio(len(true_flags), flagged),
            'flags_true': len(true_flags),
            'flags_false': len(false_flags),
            'control_flags': sum(len(f) for f in control_flags.values()),
            'benign_flagged': benign_flagged,
        },
        'by_code': by_code,
        'detected': code_matched,
    }


def precision_gate_value(metrics: dict) -> float:
    """Precision for the gate: 0 when too few flags to measure it."""
    flagged = metrics['flags_true'] + metrics['flags_false']
    return metrics['precision'] if flagged >= MIN_FLAGS_FOR_PRECISION else 0.0


def run_detector(book: str, detector: Detector, work_dir: str,
                 cases: list[dict] | None = None) -> tuple[dict, dict]:
    """Run *detector* on every case's edited copy and on a clean control
    per edited scene. Returns (case_flags, control_flags)."""
    book_dir = os.path.join(fixture_dir(book), 'book')
    cases = load_cases(book) if cases is None else cases
    case_flags, control_flags = {}, {}
    for case in cases:
        scene = case['injection']['scene']
        if scene not in control_flags:
            dest = copy_book(book_dir, os.path.join(work_dir, 'control', scene))
            control_flags[scene] = detector(dest, [scene], os.path.join(work_dir, 'logs', 'control', scene))
        dest = copy_book(book_dir, os.path.join(work_dir, 'cases', case['id']), case)
        case_flags[case['id']] = detector(dest, [scene], os.path.join(work_dir, 'logs', case['id']))
    return case_flags, control_flags


def reading_order(book_dir: str) -> list[str]:
    import csv
    with open(os.path.join(book_dir, 'reference', 'scenes.csv'), newline='', encoding='utf-8') as f:
        rows = list(csv.DictReader(f, delimiter='|'))
    return [r['id'] for r in sorted(rows, key=lambda r: float(r.get('seq') or 0))]


def drift_check(project_dir: str, scenes: list[str], log_dir: str) -> list[dict]:
    """Baseline detector: Storyforge's check after an edit, the timeline
    drift check (re-read the changed scenes' time cues, compare with the
    calendar). It only knows time, so every flag is TIM.

    The pass logs a failed cue read and carries on with whatever cues are on
    disk, which would score as a confident miss. So the edited scenes' cues
    are cleared first, and a scene that comes back without any is an error.
    """
    from storyforge.common import select_model
    from storyforge.timeline import check_scenes, read_cues, write_cues
    cues = read_cues(project_dir)
    for scene in scenes:
        cues.pop(scene, None)
    cues_file = os.path.join(project_dir, 'working', 'timeline-cues.csv')
    if os.path.exists(cues_file):
        os.remove(cues_file)
    write_cues(project_dir, cues)
    findings = check_scenes(project_dir, scenes, select_model('extraction'), log_dir)
    after = read_cues(project_dir)
    # Every cue read gives a relation (continues, later, earlier, frame)
    empty = [s for s in scenes if not (after.get(s, {}).get('relation') or '').strip()]
    if empty:
        raise RuntimeError(f'drift check: no time cues read for {", ".join(empty)}')
    return [{'scene_id': f['scene_id'], 'code': 'TIM', 'check': f['check'],
             'message': f['message']} for f in findings]


DETECTORS: dict[str, Detector] = {'drift-check': drift_check}
