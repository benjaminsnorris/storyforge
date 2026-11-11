"""The gate set (#677): the gate alone, on prose E8 already recorded and judged.

Decision 5 of `docs/plans/2026-11-08-deterministic-gate-and-voiceprint.md`
removes the open checker once the typed checks (#648) and the question layer
(#649) match its recall on the frozen E4 and E8. Re-recording those costs
about $240, mostly to redraft prose, and #655's sessions will change drafting
again. The labelled prose is already recorded: E8's cassettes keep every past
recording's judge calls, each with the replayed scene and a verdict on one
known error (an E1 `tool-introduced` case). For a gate-only set it doesn't
matter which pipeline wrote the prose, only that it's labelled.

This is the E8 half. The E4 half (shared-dark Act 1 drafts, labelled by
E4's Opus judge) needs each run's scenes gated in order and is a follow-up.

**The set is private**, like the blocking set (#646): the prose is the
corpus books', so it lives in the private storyforge-evals repo under
`gate-set/`, with the suites' recordings beside it. This module, the suites
and the tests never quote it; what this repo keeps is code, counts and ids.

Layout of `gate-set/` (written by `build.py`, from E8's cassettes):

- `cases.json`: ``{"source": "<where it was built from>", "items": [<item>, ...]}``,
  an item being::

      {"id": "<E1 case id>-<sha1 of the prose, 8>",
       "case": "<E1 case id>",
       "family": "redraft-from-brief",   # e8.family
       "code": "TIM",                    # the case's error code
       "verdict": "reintroduced",        # e8.VERDICTS, the E8 judge's
       "evidence": "<verbatim>",         # the judge's deciding sentence ('' for not_present)
       "role": "positive",               # ROLES
       "recording": "cassettes"}         # which E8 recording it came from

- `prose/<id>.md`: the judged prose.

**Roles** (`assign_roles`; `validate` checks the stored roles against it).
A `reintroduced` item whose evidence falls at exactly one place in its prose
is a `positive`. Each positive pairs with at most one `consistent` item of
the same case whose evidence also falls at one place, taken in id order: a
`control`. A case has as many controls as it has such items, up to its
positives, so the set has fewer controls than positives. Everything else
is `spare`, kept but not run: `not_present` items (they don't touch the
fact), items whose evidence is paraphrased or at several places, and every
item of a case in `e8.EXCLUDED_CASES` (E8 doesn't replay those: for most,
the pre-pass book already has the error, so the gate is right to pass it).
A control's evidence sentence states the fact correctly, so a finding
landing on it is a false alarm on that very fact.

**What is measured.** Each run item's pre-pass book is materialized
(`e8.prepare`), its prose written in, and the gate run once on it
(`gate.gate_scene`, no fix loop), with `before` the book before the prose,
as revise passes it. A positive is `caught` when a verified finding that
blocks (`GateResult.findings`) has its scene quote overlapping the evidence
sentence's place in the normalized prose (`blocking_set.spans` and
`overlaps`: a quote sharing any words of that place counts), and `stopped`
when the gate didn't pass the scene at all (E8's measure: a stop for any
reason). A finding with no scene quote (a broken promise, under either check
method) is about the brief, not the case's error, so it can stop a scene
but never catch. A finding on the evidence that the gate classed as already
in the book (`inherited`) is counted apart: it was seen, and doesn't block.

Stated simplification: a `naturalness-upstream` replay (revise rewrites the
brief, then redrafts) is gated against the pre-pass brief, not the rewritten
one, which the recording doesn't keep. Its contradictions are checked
against the book and the ledger, which the brief rewrite doesn't change.
"""

from __future__ import annotations

import hashlib
import json
import os

import blocking_set
from harness import SuiteUnavailable

SET_NAME = 'gate-set'
ROLES = ('positive', 'control', 'spare')
#: Which `e8.family` maps to which gate command (`gate.GATE_COMMANDS`), as
#: write and revise gate them
COMMANDS = {'redraft-from-brief': 'redraft', 'naturalness-upstream': 'redraft',
            'revision-plan': 'revise'}
#: The metrics where a rise is a gain (for `floor_gates`); for the rest
#: (false alarms, control stops, unfinished) a fall is
HIGHER_IS_BETTER = frozenset({'recall', 'recall_per_case', 'cases_caught',
                              'stop_rate_positive'})


class SetMissing(SuiteUnavailable):
    """The private set isn't on this machine (``stale``, with this reason)."""


def set_dir(root: str | None = None) -> str:
    """The set's directory. Raises `SetMissing` when it or its `cases.json`
    isn't there."""
    path = os.path.join(root or blocking_set.private_dir(), SET_NAME)
    if not os.path.isfile(os.path.join(path, 'cases.json')):
        raise SetMissing(
            f'the gate set is not at {path} (no cases.json): it lives in the private '
            f'storyforge-evals repo (benjaminsnorris/storyforge-evals, {SET_NAME}/). Clone it '
            f'to ~/Developer/evals or set {blocking_set.PRIVATE_ENV} to its checkout; build it '
            f'with `python3 evals/gate_set/build.py`.')
    return path


def cassettes_dir(suite_name: str, root: str | None = None, run: str = '') -> str:
    """Where a suite's recordings live: beside the set, never in this repo."""
    return os.path.join(set_dir(root), 'cassettes', *([run] if run else []), suite_name)


def item_id(case_id: str, prose: str) -> str:
    return f'{case_id}-{hashlib.sha1(prose.encode("utf-8")).hexdigest()[:8]}'


def prose_file(path: str, iid: str) -> str:
    return os.path.join(path, 'prose', f'{iid}.md')


def load(path: str) -> list[dict]:
    """The items, each with its `prose` read in. Raises `ValueError` when
    `cases.json` has no `items` list: a misspelled key would read as an
    empty set."""
    with open(os.path.join(path, 'cases.json'), encoding='utf-8') as f:
        data = json.load(f)
    items = data.get('items') if isinstance(data, dict) else None
    if not (isinstance(items, list) and all(isinstance(i, dict) for i in items)):
        raise ValueError(f'{path}/cases.json: no "items" list')
    for item in items:
        file = prose_file(path, str(item.get('id')))
        item['prose'] = ''
        if os.path.isfile(file):
            with open(file, encoding='utf-8') as f:
                item['prose'] = f.read()
    return items


def evidence_place(prose: str, evidence: str) -> list[tuple[int, int]]:
    """The character ranges, in the normalized prose, of the one place the
    judge's evidence falls; empty when it isn't there (the judge
    paraphrased) or falls at several places (a finding at any of them would
    count, as the blocking set refuses for its quotes)."""
    from storyforge.quotes import normalize
    if not evidence.strip():
        return []
    found = blocking_set.places(normalize(prose), evidence)
    return found[0] if len(found) == 1 else []


def validate(items: list[dict], cases: dict[str, dict] | None = None) -> list[str]:
    """The structural problems that would make scoring wrong, naming ids,
    never the prose. Empty when sound. With `cases` (E1's, by id), each
    item's case must still exist with the item's family and code: a case
    renamed, relabelled or newly excluded since the build means a rebuild."""
    import copy

    from e1 import ERROR_CODES
    from e8 import EXCLUDED_CASES, VERDICTS, family
    problems = []
    if not any(i.get('role') == 'positive' for i in items):
        problems.append('the set has no positive item')
    seen = set()
    sound = []
    for n, item in enumerate(items, 1):
        iid = item.get('id')
        if not (isinstance(iid, str) and iid):
            problems.append(f'item {n}: no id')
            continue
        if iid in seen:
            problems.append(f'{iid}: listed twice')
        seen.add(iid)
        before = len(problems)
        if item.get('role') not in ROLES:
            problems.append(f'{iid}: role must be one of {ROLES}')
        if item.get('verdict') not in VERDICTS:
            problems.append(f'{iid}: verdict must be one of {VERDICTS}')
        if item.get('family') not in COMMANDS:
            problems.append(f'{iid}: family must be one of {tuple(COMMANDS)}')
        if item.get('code') not in ERROR_CODES:
            problems.append(f'{iid}: code must be one of {ERROR_CODES}')
        if not isinstance(item.get('evidence', ''), str):
            problems.append(f'{iid}: evidence must be a string')
        if not item.get('prose', '').strip():
            problems.append(f'{iid}: no prose (prose/{iid}.md)')
            continue
        if item_id(str(item.get('case')), item['prose']) != iid:
            problems.append(f'{iid}: its prose is not the prose it was built from')
        if item.get('role') == 'positive' and item.get('verdict') != 'reintroduced':
            problems.append(f'{iid}: a positive must be reintroduced')
        if item.get('role') == 'control' and item.get('verdict') != 'consistent':
            problems.append(f'{iid}: a control must be consistent')
        if item.get('role') in ('positive', 'control') and not evidence_place(
                item['prose'], str(item.get('evidence', ''))):
            problems.append(f'{iid}: its evidence is not in its prose at exactly one place')
        if cases is not None and item.get('role') != 'spare':
            case = cases.get(str(item.get('case')))
            if case is None:
                problems.append(f'{iid}: E1 has no case {item.get("case")}; rebuild the set')
            elif case['id'] in EXCLUDED_CASES:
                problems.append(f'{iid}: E8 now excludes {case["id"]}; rebuild the set')
            elif family(case) != item.get('family') or case.get('code') != item.get('code'):
                problems.append(f'{iid}: {case["id"]}\'s family or code changed; rebuild the set')
        if len(problems) == before:
            sound.append(item)
    # The stored roles must be the ones the rule gives: a positive relabelled
    # spare would leave recall's denominator without a miss
    expected = copy.deepcopy(sound)
    assign_roles(expected)
    for item, want in zip(sound, expected):
        if item['role'] != want['role']:
            problems.append(f'{item["id"]}: role {item["role"]}, but the rule gives '
                            f'{want["role"]}; rebuild the set')
    return problems


def assign_roles(items: list[dict]) -> None:
    """Set each item's `role` (the module doc's rule), in place."""
    from e8 import EXCLUDED_CASES
    positives: dict[str, int] = {}
    for item in sorted(items, key=lambda i: i['id']):
        placed = bool(evidence_place(item['prose'], item.get('evidence', '')))
        if item['case'] in EXCLUDED_CASES:
            item['role'] = 'spare'
        elif item['verdict'] == 'reintroduced' and placed:
            item['role'] = 'positive'
            positives[item['case']] = positives.get(item['case'], 0) + 1
        else:
            item['role'] = 'spare'
    for item in sorted(items, key=lambda i: i['id']):
        if (item['role'] == 'spare' and item['verdict'] == 'consistent'
                and positives.get(item['case'], 0) > 0
                and evidence_place(item['prose'], item.get('evidence', ''))):
            item['role'] = 'control'
            positives[item['case']] -= 1


# --- scoring ----------------------------------------------------------------

def _outcome(iid: str, *, finished: bool, stopped: bool, caught: bool,
             inherited_on: bool, findings: int) -> dict:
    """The one shape of an item's outcome, for `score` and the results file."""
    return {'id': iid, 'finished': finished, 'stopped': stopped, 'caught': caught,
            'inherited_on': inherited_on, 'findings': findings}


def outcome(item: dict, result) -> dict:
    """What the gate did with one item (a `gate.GateResult`, or None when it
    couldn't finish): `stopped`, `caught` (a blocking verified finding on
    the evidence), `inherited_on` (a finding on the evidence the gate classed
    as already in the book), `findings` (blocking, verified). A finding with
    no scene quote (a broken promise) can't land on the evidence."""
    from storyforge.quotes import normalize
    if result is None:
        return _outcome(item['id'], finished=False, stopped=True, caught=False,
                        inherited_on=False, findings=0)
    place = evidence_place(item['prose'], item.get('evidence', ''))
    norm = normalize(item['prose'])

    def on_evidence(findings) -> bool:
        return any(blocking_set.overlaps(blocking_set.spans(norm, f.scene_quote), place)
                   for f in findings if f.scene_quote)

    return _outcome(item['id'], finished=True, stopped=not result.passed,
                    caught=on_evidence(result.findings),
                    inherited_on=on_evidence(result.inherited),
                    findings=len(result.findings))


def _rate(hit: int, of: int) -> float:
    return round(hit / of, 4) if of else 0.0


def score(items: list[dict], outcomes: dict[str, dict]) -> tuple[dict, dict]:
    """Metrics and a by-code breakdown over the run items (positives and
    controls). Every run item must have an outcome, or this raises: an item
    left out would read as one the gate passed."""
    run = [i for i in items if i['role'] in ('positive', 'control')]
    missing = [i['id'] for i in run if i['id'] not in outcomes]
    if missing:
        raise ValueError(f'{len(missing)} item(s) have no outcome')
    pos = [i for i in run if i['role'] == 'positive']
    ctl = [i for i in run if i['role'] == 'control']

    def count(group, key):
        return sum(1 for i in group if outcomes[i['id']][key])

    # Positives cluster on a few cases (one case's error reintroduced by
    # most of its replays), so recall is also given per case: each case
    # weighs the same, whatever its number of replays
    per_case: dict[str, list[int]] = {}
    for i in pos:
        per_case.setdefault(i['case'], []).append(int(outcomes[i['id']]['caught']))
    metrics = {
        'positives': len(pos),
        'controls': len(ctl),
        'cases': len(per_case),
        'cases_caught': sum(1 for v in per_case.values() if any(v)),
        'recall_per_case': (round(sum(sum(v) / len(v) for v in per_case.values())
                                  / len(per_case), 4) if per_case else 0.0),
        'caught': count(pos, 'caught'),
        'recall': _rate(count(pos, 'caught'), len(pos)),
        'stopped_positive': count(pos, 'stopped'),
        'stop_rate_positive': _rate(count(pos, 'stopped'), len(pos)),
        'inherited_on_positive': count(pos, 'inherited_on'),
        'false_alarm_on_fact': count(ctl, 'caught'),
        'stopped_control': count(ctl, 'stopped'),
        'stop_rate_control': _rate(count(ctl, 'stopped'), len(ctl)),
        'unfinished': sum(1 for i in run if not outcomes[i['id']]['finished']),
    }
    by_code: dict[str, dict[str, int | float]] = {}
    for i in pos:
        row = by_code.setdefault(i['code'], {'positives': 0, 'caught': 0})
        row['positives'] += 1
        row['caught'] += outcomes[i['id']]['caught']
    for row in by_code.values():
        row['recall'] = _rate(row['caught'], row['positives'])
    return metrics, by_code
