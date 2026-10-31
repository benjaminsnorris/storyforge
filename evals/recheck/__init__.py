"""The re-check set on E1 cases (rethink plan §5, Phase 4 success criterion;
design: ``docs/plans/2026-10-31-phase4-safe-revision-design.md`` §4).

Every E1 error is a fact established in one scene and contradicted in a
later one. If the author rejects (or a redraft changes) the established
fact, the re-check set must contain the scene that contradicted it: that is
the scene where the error was introduced, and the one a re-check exists to
catch.

For each non-holdout E1 prose case whose established and contradicted sides
are prose in different scenes, in reading order, of a tree with
``reference/scenes.csv``:

1. The book is materialized at the established span's commit (the fix's
   parent, where both sides coexist) and its registries migrated.
2. Extract phase 4 (the commitments rubric, with the persistence check) runs
   over a **subset** of the tree's scenes in reading order: every case's
   establishing and contradicting scenes, plus up to ``CONTROLS`` scenes
   between them (evenly spaced), once per tree. The chain is the subset's:
   each scene is offered the facts the earlier extracted scenes recorded.
3. An Opus judge reads the established quote and the establishing scene's
   binding ledger rows (registry facts and commitments) and names the rows
   that record the fact. None: the fact isn't in the ledger to reject
   (E3's miss), counted apart.
4. ``cmd_audit._reject_recheck`` (what ``storyforge audit --mark rejected``
   lists, without writing) on those rows: the scenes to re-check, now or
   once the establishing scene is revised. A hit is a contradicting scene in
   that set.

**Precision.** The set is only as wide as the ledger: commitments exist for
the extracted subset alone (registry facts cover the whole book), so the
set's size against the book's later scenes is a floor on what a
whole-book phase 4 would give. The controls estimate the over-inclusion: the
share of extracted scenes between the two sides that the set includes
(``control_inclusion``). Over-inclusion is by design (a needless check costs
a call, a missed scene is a silent hole), so it is reported, not gated.
"""

from __future__ import annotations

import json
import os
import re
from dataclasses import dataclass, field

import e1
from e2.corpus import _has, _stem, tree_dir

CONTROLS = 2

JUDGE_PROMPT = """You are matching one fact from a novel to rows of the book's fact ledger.

The fact, as the book states it in scene {scene}:
"{quote}"
(Context: a later scene contradicted this; the error was: {summary})

The ledger rows established in that scene, one per line as id | type | subject | statement | quote:
{rows}

Which rows record this fact — the specific claim a later scene contradicted, in any wording?

Answer with one JSON object and nothing else:
{{"verdict": "captured" | "partial" | "missing", "ids": ["<row id>", ...]}}

"captured": the ids are rows that record the specific claim.
"partial": no row records the specific detail, but the ids are rows that record a related fact about the same person or thing in the same respect (e.g. "Hank drove to Portland" without the three hours).
"missing": no row records it or a related fact; ids is empty."""

VERDICTS = ('captured', 'partial', 'missing')


@dataclass
class Item:
    case: dict
    commit: str
    established: str           # the establishing scene's id in the tree
    contradicted: list[str]    # the contradicting scenes' ids in the tree
    controls: list[str] = field(default_factory=list)


def select(root: str | None = None) -> tuple[list[dict], dict[str, list[str]]]:
    """Cases with a prose established span and a prose contradicted span in
    another scene, and the excluded ids by reason (checks needing the tree's
    scene order are in `place`)."""
    root = root or e1.corpus_dir()
    held = set(e1.load_holdout())
    picked, excluded = [], {}
    for case in e1.load_cases():
        if case['level'] != 'prose':
            continue
        est = [s for s in case['established'] if s.get('source', 'prose') == 'prose']
        con = [s for s in case['contradicted'] if s.get('source', 'prose') == 'prose']
        repo_dir = os.path.join(root, case['repo'])
        reason = None
        if case['id'] in held:
            reason = 'holdout'
        elif not est:
            reason = 'no prose established span'
        elif not ({_stem(s) for s in con} - {_stem(est[0])}):
            reason = 'contradicted only in the establishing scene'
        elif not os.path.isdir(os.path.join(repo_dir, '.git')):
            reason = f'{case["repo"]} not cloned'
        elif not _has(repo_dir, est[0]['commit'], 'reference/scenes.csv'):
            reason = 'tree predates reference/scenes.csv'
        if reason:
            excluded.setdefault(reason, []).append(case['id'])
            continue
        picked.append(case)
    return picked, excluded


def place(case: dict, project_dir: str, order: dict[str, int]) -> Item | str:
    """The case's scenes in the tree, or why it can't be measured there."""
    est = next(s for s in case['established'] if s.get('source', 'prose') == 'prose')
    scene = _stem(est)
    if scene not in order:
        return 'establishing scene not in scenes.csv'
    if not os.path.isfile(os.path.join(project_dir, 'scenes', f'{scene}.md')):
        return 'establishing scene has no prose in its tree'
    later = sorted({_stem(s) for s in case['contradicted']
                    if s.get('source', 'prose') == 'prose'
                    and _stem(s) in order and order[_stem(s)] > order[scene]
                    and os.path.isfile(os.path.join(project_dir, 'scenes', f'{_stem(s)}.md'))},
                   key=order.get)
    if not later:
        # Labeled by which side the author kept: a re-check runs forward, so
        # an "established" side read after its contradiction isn't its case
        return 'contradicted only before the establishing scene (the re-check runs forward)'
    between = [s for s in sorted(order, key=order.get)
               if order[scene] < order[s] < order[later[0]]
               and os.path.isfile(os.path.join(project_dir, 'scenes', f'{s}.md'))]
    controls = ([between[round(i * (len(between) - 1) / (CONTROLS - 1))]
                 for i in range(CONTROLS)] if len(between) > CONTROLS else between)
    return Item(case, est['commit'], scene, later, sorted(set(controls), key=order.get))


def commit_subset(project_dir: str, scenes: list[str]) -> None:
    """Extract phase 4 over ``scenes`` (in reading order), writing their
    commitments into the tree's ledger. As E5's ``commit_prose``: no git
    commit, and a scene phase 4 can't read errors the suite."""
    from unittest import mock

    from storyforge import cmd_extract
    log_dir = os.path.join(project_dir, 'working', 'logs')
    os.makedirs(log_dir, exist_ok=True)
    with mock.patch.object(cmd_extract, 'commit_and_push', lambda *a, **k: False):
        try:
            cmd_extract._run_phase_4(scenes, project_dir, os.path.join(project_dir, 'scenes'),
                                     os.path.join(project_dir, 'reference'), log_dir,
                                     force=False, dry_run=False)
        except SystemExit as e:
            raise RuntimeError(f'extract phase 4 stopped (exit {e.code}); '
                               f'see {log_dir}') from None


def format_rows(rows: list[dict]) -> str:
    def cell(v):
        return ' '.join((v or '').split())
    return '\n'.join(' | '.join(cell(r.get(k)) for k in ('id', 'type', 'subject', 'statement', 'quote'))
                     for r in rows)


def parse_verdict(text: str, offered: set[str]) -> dict:
    match = re.search(r'\{.*\}', text, re.DOTALL)
    if not match:
        raise ValueError(f'judge returned no JSON object: {text[:200]!r}')
    verdict = json.loads(match.group(0))
    if verdict.get('verdict') not in VERDICTS:
        raise ValueError(f'judge verdict {verdict.get("verdict")!r} is not one of {VERDICTS}')
    ids = verdict.get('ids')
    if not isinstance(ids, list) or not all(isinstance(i, str) for i in ids):
        raise ValueError(f'judge ids {ids!r} is not a list of strings')
    unknown = [i for i in ids if i not in offered]
    if unknown:
        raise ValueError(f'judge named rows it wasn\'t offered: {unknown}')
    if (verdict['verdict'] == 'missing') != (not ids):
        raise ValueError(f'judge verdict {verdict["verdict"]!r} with ids {ids!r}')
    return verdict


def judge(item: Item, rows: list[dict]) -> dict:
    """Which of the establishing scene's binding rows record the case's fact."""
    from storyforge.api import extract_text, invoke
    from storyforge.common import model_for_tier
    mine = [r for r in rows if r.get('status') == 'binding'
            and (r.get('scene_id') or '').strip() == item.established]
    if not mine:
        return {'verdict': 'missing', 'ids': []}
    est = next(s for s in item.case['established'] if s.get('source', 'prose') == 'prose')
    prompt = JUDGE_PROMPT.format(scene=item.established, quote=est['quote'],
                                 summary=item.case['summary'], rows=format_rows(mine))
    return parse_verdict(extract_text(invoke(prompt, model_for_tier('opus'), max_tokens=512,
                                             label=f'recheck judge {item.case["id"]}')),
                         {r['id'] for r in mine})


def recheck_set(project_dir: str, rows: list[dict], fact_ids: list[str]) -> tuple[list[str], list[str]]:
    """What rejecting ``fact_ids`` lists for a re-check (now, or once the
    establishing scene is revised), in reading order, and the reasons any
    dependents can't all be traced."""
    from storyforge import cmd_audit, ledger
    found = cmd_audit._reject_recheck(project_dir, rows, fact_ids)
    order = ledger.scene_order(project_dir)
    scenes = {s for info in found.values() for s in info['recheck'] + info['later']}
    unrelated = [f'{fid}: {info["unrelated"]}' for fid, info in found.items() if info['unrelated']]
    return sorted(scenes, key=order.get), unrelated


def later_with_prose(project_dir: str, scene: str, order: dict[str, int]) -> int:
    return sum(1 for s in order if order[s] > order[scene]
               and os.path.isfile(os.path.join(project_dir, 'scenes', f'{s}.md')))


def project_for(case: dict, commit: str, work_dir: str, root: str | None = None) -> str:
    return tree_dir(work_dir, case['repo'], commit, root)
