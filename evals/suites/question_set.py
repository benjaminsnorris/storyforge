"""The gate's question layer (#649, `storyforge.questions`) on a fixed
labelled question set: an E2-style set whose answers are known.

The cases are *A Christmas Carol* (public domain), the E2 book
(`fixtures/e2-carol`), and the facts are ones Dickens establishes, written as
ledger facts of the types the question layer asks about (trait,
relationship, physical outside injury and equipment, world). Each scene is
asked about the same facts (`scenes` in `fixtures/question-set/cases.json`)
in every variant of it:

- **error**: one of E2's injected errors (`injections.json`) that breaks one
  of those facts: that fact's answer is `yes`, the others' `no`;
- **control**: the scene as Dickens wrote it: every answer `no`;
- **benign**: one of E2's benign rewordings: every answer `no`.

The suite asks each variant's questions the way the gate does
(`questions.ask_questions`: one call per asking, two askings, a finding
only when both say yes and the quote is in the scene), so what it measures
is the questions, the prompt and the model, not the selection of facts
(that is code, in `tests/test_questions.py`). A `yes` is caught when its
finding's quote lands on the injected words (overlaps a `contradicted`
quote); `recall_any` counts a finding anywhere in the scene.

The model is the question layer's default (the extraction tier) unless
`STORYFORGE_QUESTIONS_MODEL` (or `STORYFORGE_MODEL`) names another, which is
a different request and so a re-record (`--cassettes-dir` keeps it apart,
as the tier comparisons do). Gates hold each recorded value exactly
(`FLOORS`, #488).
"""

from __future__ import annotations

import json
import os

import e2
from harness import EVALS_DIR, Gate, Suite, SuiteOutput

NAME = 'question-set'
CASES_FILE = os.path.join(EVALS_DIR, 'fixtures', 'question-set', 'cases.json')

#: The recorded values, each held exactly (#488: a gain moves its floor in
#: the same commit; a loss is a decision). The plan's targets are notes:
#: recall at least the open checker's on the frozen E4/E8, no false alarms
FLOORS: dict[str, float | None] = {
    'recall': None,
    'recall_any': None,
    'false_alarms': None,
    'split': None,
}


def load_cases(path: str = CASES_FILE) -> dict:
    with open(path, encoding='utf-8') as f:
        return json.load(f)


def validate(data: dict, book_dir: str, injections: dict[str, dict]) -> list[str]:
    """Problems with the set against the book; empty when sound: a fact's
    quote not in the scene it names, a fact asked about in the scene that
    establishes it, an unknown fact, injection or `yes`, an injection whose
    `find` isn't once in its scene, or a `yes` fact the scene isn't asked."""
    from storyforge.questions import QUESTION_TYPES
    from storyforge.quotes import quote_in
    problems = []
    facts = data.get('facts', {})

    def text(scene: str) -> str:
        with open(os.path.join(book_dir, 'scenes', f'{scene}.md'), encoding='utf-8') as f:
            return f.read()
    for fid, f in facts.items():
        if f.get('type') not in QUESTION_TYPES:
            problems.append(f'{fid}: type {f.get("type")!r} is not one the layer asks about')
        if not quote_in(text(f['scene']), f['quote']):
            problems.append(f'{fid}: its quote is not in {f["scene"]}')
    for scene, ids in data.get('scenes', {}).items():
        for fid in ids:
            if fid not in facts:
                problems.append(f'{scene}: unknown fact {fid}')
            elif facts[fid]['scene'] == scene:
                problems.append(f'{scene}: asks about {fid}, which it establishes')
    ids = [v['id'] for v in data.get('variants', [])]
    for dup in sorted({i for i in ids if ids.count(i) > 1}):
        problems.append(f'duplicate variant {dup}')
    for v in data.get('variants', []):
        asked = data['scenes'].get(v['scene'])
        if asked is None:
            problems.append(f'{v["id"]}: scene {v["scene"]} has no facts')
            continue
        for fid in v['yes']:
            if fid not in asked:
                problems.append(f'{v["id"]}: yes fact {fid} is not asked in {v["scene"]}')
        if v['injection']:
            inj = injections.get(v['injection'])
            if inj is None:
                problems.append(f'{v["id"]}: unknown injection {v["injection"]}')
            elif inj['injection']['scene'] != v['scene'] \
                    or text(v['scene']).count(inj['injection']['find']) != 1:
                problems.append(f'{v["id"]}: {v["injection"]} does not apply once to '
                                f'{v["scene"]}')
        shape = {'error': (True, True), 'benign': (True, False), 'control': (False, False)}
        if shape.get(v['kind']) != (bool(v['injection']), bool(v['yes'])):
            problems.append(f'{v["id"]}: an error has an injection and a yes, a benign '
                            f'variant an injection only, a control neither')
    return problems


def variant_prose(book_dir: str, v: dict, injections: dict[str, dict]) -> str:
    with open(os.path.join(book_dir, 'scenes', f'{v["scene"]}.md'), encoding='utf-8') as f:
        text = f.read()
    return e2._apply(text, injections[v['injection']]['injection']) if v['injection'] else text


def questions_for(data: dict, scene: str) -> list:
    from storyforge.questions import question_for
    out = []
    for fid in data['scenes'][scene]:
        f = data['facts'][fid]
        out.append(question_for({'id': fid, 'scene_id': f['scene'], 'type': f['type'],
                                 'subject': f['subject'], 'statement': f['statement'],
                                 'quote': f['quote']}, f['name']))
    return out


def score(data: dict, outcomes: dict[str, dict], injections: dict[str, dict]) -> dict:
    """`outcomes`: variant id → {'findings': {fact id: scene quote},
    'split': n, 'misquoted': n}. Returns metrics, by_code and the missed /
    false-alarm lists."""
    from storyforge.checker import CODE_OF_TYPE
    from storyforge.continuity import overlaps
    yes_total = caught = caught_any = 0
    false = {'control': 0, 'benign': 0, 'error': 0}
    by_code: dict[str, dict] = {}
    missed, alarms = [], []
    for v in data['variants']:
        got = outcomes[v['id']]
        for fid in data['scenes'][v['scene']]:
            quote = got['findings'].get(fid)
            if fid in v['yes']:
                code = CODE_OF_TYPE[data['facts'][fid]['type']]
                row = by_code.setdefault(code, {'cases': 0, 'caught': 0})
                row['cases'] += 1
                yes_total += 1
                where = [c['quote'] for c in injections[v['injection']].get('contradicted', [])]
                if quote is not None:
                    caught_any += 1
                    if any(overlaps(quote, w) for w in where):
                        caught += 1
                        row['caught'] += 1
                        continue
                missed.append(v['id'])
            elif quote is not None:
                false[v['kind']] += 1
                alarms.append(f'{v["id"]}:{fid}')
    n_no = sum(len(data['scenes'][v['scene']]) for v in data['variants']) - yes_total
    metrics = {
        'variants': len(data['variants']),
        'questions': yes_total + n_no,
        'yes_questions': yes_total,
        'recall': round(caught / yes_total, 4) if yes_total else 0.0,
        'recall_any': round(caught_any / yes_total, 4) if yes_total else 0.0,
        'false_alarms': sum(false.values()),
        'false_alarms_control': false['control'],
        'false_alarms_benign': false['benign'],
        'false_alarms_other_facts': false['error'],
        'split': sum(o['split'] for o in outcomes.values()),
        'misquoted': sum(o['misquoted'] for o in outcomes.values()),
    }
    codes = {c: {'cases': r['cases'], 'recall': round(r['caught'] / r['cases'], 4)}
             for c, r in sorted(by_code.items())}
    return {'metrics': metrics, 'by_code': codes, 'missed': missed, 'alarms': alarms}


def floor_gates(metrics: dict, floors: dict) -> tuple[list[Gate], list[str]]:
    gates, notes = [], []
    for name, floor in floors.items():
        value = metrics.get(name)
        gates.append(Gate(name, -1 if value is None else value, '==',
                          -1 if floor is None else floor))
        if floor is None:
            notes.append(f'{name} {value}: no floor recorded; set FLOORS[{name!r}] = {value}')
        elif value != floor:
            notes.append(f'{name} {value}, FLOORS {floor}: a change; moving the floor is a '
                         f'decision (see FLOORS)')
    return gates, notes


def run(ctx):
    from storyforge import questions
    book_dir = os.path.join(e2.fixture_dir('carol'), 'book')
    injections = {c['id']: c for c in e2.load_cases('carol')}
    data = load_cases()
    problems = validate(data, book_dir, injections)
    if problems:
        raise ValueError('question-set fixtures: ' + '; '.join(problems))
    model = questions.resolve_model()
    outcomes = {}
    for v in data['variants']:
        prose = variant_prose(book_dir, v, injections)
        r = questions.ask_questions(v['scene'], prose, questions_for(data, v['scene']),
                                    model=model)
        outcomes[v['id']] = {'findings': {f.fact_id: f.scene_quote for f in r.findings},
                             'split': r.split, 'misquoted': r.misquoted}
    result = score(data, outcomes, injections)
    gates, notes = floor_gates(result['metrics'], FLOORS)
    m = result['metrics']
    notes += [f'model: {model}',
              f'missed {len(result["missed"])} of {m["yes_questions"]}: '
              + ', '.join(result['missed']),
              f'false alarms ({m["false_alarms"]}): ' + ', '.join(result['alarms']),
              'plan target (not gated): with the typed checks, the open checker\'s recall on the '
              'frozen E4/E8, with fewer false alarms']
    return SuiteOutput(metrics=m, by_code=result['by_code'], gates=gates, notes=notes)


SUITE = Suite(NAME, 'The gate\'s yes/no question layer (#649) on a labelled question set from '
                    'A Christmas Carol', run)
