"""The re-check set on E1 cases (rethink plan §5, Phase 4 success criterion;
design: ``docs/plans/2026-10-31-phase4-safe-revision-design.md`` §4).

Every E1 error is a fact established in one scene and contradicted in a
later one. If the author rejects (or a redraft changes) the established
fact, the re-check must reach the scene that contradicted it: that is the
scene where the error was introduced, and the one a re-check exists to
catch.

For each non-holdout E1 prose case whose established and contradicted sides
are prose in different scenes, of a tree with ``reference/scenes.csv``:

1. The book is materialized at the established span's commit (the fix's
   parent, where both sides coexist) and its registries migrated (a tree
   whose migration stopped errors the suite).
2. ``place`` finds the case's scenes in the tree. A scene counts only when
   the reject flow would list it: in scenes.csv, not cut or merged, with
   prose (``gate._has_prose``). The contradicting scenes are those after
   the establishing one; a case with none is excluded, with why (most often
   its "established" side reads after the contradiction: the author kept
   the later version, and a re-check runs forward).
3. Extract phase 4 (the commitments rubric, with the persistence check) runs
   once per tree over a **subset** of its scenes in reading order: every
   case's establishing and contradicting scenes, plus up to ``CONTROLS``
   control scenes between the establishing scene and its first
   contradicting one (with more than ``CONTROLS`` there, the first and the
   last: the scenes right next to each side). The chain is the subset's:
   each scene is offered the facts in force from earlier subset scenes and
   backstory; registry facts of scenes outside the subset are offered to no
   scene (named in the notes).
4. An Opus judge reads the established quote, the case's error summary and
   the establishing scene's binding ledger rows (registry facts and
   commitments) and answers ``captured`` (rows record the fact),
   ``partial`` (rows record a related fact about the same thing in the same
   respect) or ``missing``. A scene with no binding rows at all is
   ``no_rows`` with no call (a broken extraction, not E3's miss).
5. ``cmd_audit._reject_recheck`` (what ``storyforge audit --mark rejected``
   lists, without writing) on those rows gives the scenes actually
   re-checked: those listed now (no prose to revise), or, when the
   establishing scene has prose, the ones its revision lists once it passes
   the gate (its dependents and the scenes whose brief names it, which the
   gate lists too since PR 3c). A hit is a contradicting scene in the set. Only ``captured``
   counts toward ``recall``; ``partial`` is in ``recall_with_partial``.

**Precision.** The set is only as wide as the ledger: commitments exist for
the extracted subset alone (registry facts cover the whole book), so the
set's size against the book's later scenes (``set_fraction_mean``) is a
floor on what a whole-book phase 4 would give. ``control_inclusion`` is the
share of the captured cases' control scenes the set includes: an upper
bound on needless inclusion, since the controls sit next to the two sides
(most likely to share subjects) and a control may truly depend on the fact.
Over-inclusion is by design (a needless check costs a call, a missed scene
is a silent hole), so it is reported, not gated.
"""

from __future__ import annotations

import json
import os
import re
from dataclasses import dataclass

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
NO_ROWS = 'no_rows'
BEFORE = 'contradicted only before the establishing scene (the re-check runs forward)'


@dataclass(frozen=True)
class Item:
    case: dict
    commit: str
    established: str             # the establishing scene's id in the tree
    quote: str                   # the established span's quote
    #: the contradicting scenes the reject flow could list, after
    #: `established`, in reading order; never empty
    contradicted: tuple[str, ...]
    controls: tuple[str, ...]    # scenes between, next to each side (see the module doc)
    #: contradicted spans left out though others remain, each with why
    dropped: tuple[str, ...] = ()


def prose_spans(spans: list[dict]) -> list[dict]:
    return [s for s in spans if s.get('source', 'prose') == 'prose']


def select(root: str | None = None) -> tuple[list[dict], dict[str, list[str]]]:
    """Cases with a prose established span and a prose contradicted span in
    another scene, and the excluded ids by reason (checks needing the tree
    are in `place`)."""
    root = root or e1.corpus_dir()
    held = set(e1.load_holdout())
    picked, excluded = [], {}
    for case in e1.load_cases():
        if case['level'] != 'prose':
            continue
        est = prose_spans(case['established'])
        con = prose_spans(case['contradicted'])
        repo_dir = os.path.join(root, case['repo'])
        reason = None
        if case['id'] in held:
            reason = 'holdout'
        elif not est:
            reason = 'no prose established span'
        elif not con:
            reason = 'no prose contradicted span'
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


def gone_scenes(project_dir: str) -> set[str]:
    from storyforge import gate
    return gate._gone_scenes(project_dir)


def unusable(project_dir: str, scene: str, order: dict[str, int], gone: set[str]) -> str:
    """Why the reject flow would never list `scene` ('' when it would)."""
    from storyforge import gate
    if scene not in order:
        return 'not in scenes.csv'
    if scene in gone:
        return 'cut or merged'
    if not gate._has_prose(project_dir, scene):
        return 'no prose in its tree'
    return ''


def place(case: dict, project_dir: str, order: dict[str, int],
          gone: set[str] | None = None) -> Item | str:
    """The case's scenes in the tree, or why it can't be measured there."""
    gone = gone_scenes(project_dir) if gone is None else gone
    est = prose_spans(case['established'])[0]
    scene = _stem(est)
    why = unusable(project_dir, scene, order, gone)
    if why:
        return f'establishing scene {why}'
    later, dropped = [], []
    for sid in dict.fromkeys(_stem(s) for s in prose_spans(case['contradicted'])):
        if sid == scene:
            continue
        why = unusable(project_dir, sid, order, gone) or (
            'before the establishing scene' if order[sid] < order[scene] else '')
        if why:
            dropped.append(f'{sid}: {why}')
        else:
            later.append(sid)
    later.sort(key=order.get)
    if not later:
        if all(d.endswith(': before the establishing scene') for d in dropped):
            return BEFORE
        return 'no usable contradicting scene (' + '; '.join(dropped) + ')'
    between = [s for s in sorted(order, key=order.get)
               if order[scene] < order[s] < order[later[0]]
               and not unusable(project_dir, s, order, gone)]
    if len(between) <= CONTROLS:
        controls = between
    elif CONTROLS == 1:
        controls = [between[0]]
    else:
        controls = [between[round(i * (len(between) - 1) / (CONTROLS - 1))]
                    for i in range(CONTROLS)]
    return Item(case, est['commit'], scene, est['quote'], tuple(later),
                tuple(sorted(set(controls), key=order.get)), tuple(dropped))


def check_migrated(project_dir: str) -> None:
    """Raise when the tree kept its old registries (`harness.migrate_tree`
    stopped): its ledger would hold no registry facts, so the judge and the
    graph would see commitments only."""
    ref = os.path.join(project_dir, 'reference')
    left = [f for f in ('knowledge.csv', 'physical-states.csv')
            if os.path.isfile(os.path.join(ref, f))]
    if left:
        raise RuntimeError(f'{project_dir}: the ledger migration stopped '
                           f'({", ".join(left)} kept); see the suite notes')


def commit_subset(project_dir: str, scenes: list[str]) -> None:
    """Extract phase 4 over ``scenes`` (in reading order), writing their
    commitments into the tree's ledger. As E5's ``commit_prose``: no git
    commit, and a scene phase 4 can't read errors the suite.

    Raises when a scene already has commitments (phase 4 would skip it and
    keep the old rows) or when phase 4 didn't extract one (it skips a
    missing or blank scene without a word)."""
    from unittest import mock

    from storyforge import cmd_extract, ledger
    ref_dir = os.path.join(project_dir, 'reference')
    had = sorted({r['scene_id'] for r in ledger.load_from(ref_dir)
                  if r.get('introduced_by') == ledger.COMMITMENTS_PASS} & set(scenes))
    if had:
        raise RuntimeError(f'{project_dir}: scenes already have commitments, which phase 4 '
                           f'would keep: {", ".join(had)}')
    log_dir = os.path.join(project_dir, 'working', 'logs')
    os.makedirs(log_dir, exist_ok=True)
    with mock.patch.object(cmd_extract, 'commit_and_push', lambda *a, **k: False):
        try:
            cmd_extract._run_phase_4(scenes, project_dir, os.path.join(project_dir, 'scenes'),
                                     ref_dir, log_dir, force=False, dry_run=False)
        except SystemExit as e:
            raise RuntimeError(f'extract phase 4 stopped (exit {e.code}); '
                               f'see {log_dir}') from None
    skipped = [s for s in scenes if not os.path.isfile(
        os.path.join(log_dir, f'extract-commitments-{s}.json'))]
    if skipped:
        raise RuntimeError(f'extract phase 4 skipped {", ".join(skipped)} (no log); '
                           f'see {log_dir}')


def unplaced(rows: list[dict], scenes: list[str]) -> int:
    """How many binding facts name a scene outside the subset: no extracted
    scene was offered them."""
    from storyforge.extract import unplaced_rows
    return len(unplaced_rows(rows, {s: i for i, s in enumerate(scenes)}))


def format_rows(rows: list[dict]) -> str:
    def cell(v):
        return ' '.join((v or '').split())
    return '\n'.join(' | '.join(cell(r.get(k)) for k in ('id', 'type', 'subject', 'statement', 'quote'))
                     for r in rows)


def parse_verdict(text: str, offered: set[str]) -> dict:
    """`{'verdict', 'ids'}` from the judge's reply, checked: a known verdict,
    ids it was offered, and ids empty exactly when the fact is missing."""
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
    return {'verdict': verdict['verdict'], 'ids': ids}


def judge(item: Item, rows: list[dict]) -> dict:
    """Which of the establishing scene's binding rows record the case's fact."""
    from storyforge.api import extract_text, invoke, is_truncated
    from storyforge.common import model_for_tier
    mine = [r for r in rows if r.get('status') == 'binding'
            and (r.get('scene_id') or '').strip() == item.established]
    if not mine:
        return {'verdict': NO_ROWS, 'ids': []}
    prompt = JUDGE_PROMPT.format(scene=item.established, quote=item.quote,
                                 summary=item.case['summary'], rows=format_rows(mine))
    response = invoke(prompt, model_for_tier('opus'), max_tokens=512,
                      label=f'recheck judge {item.case["id"]}')
    if is_truncated(response):
        raise ValueError(f'{item.case["id"]}: the judge reply hit max_tokens')
    return parse_verdict(extract_text(response), {r['id'] for r in mine})


@dataclass(frozen=True)
class RecheckSet:
    #: the scenes re-checked, in reading order
    scenes: tuple[str, ...]
    #: fact id: why its dependents can't all be traced
    unrelated: tuple[str, ...]
    #: candidates it doesn't list, each with why (cut, no prose, waiting)
    not_listed: tuple[str, ...]


def recheck_set(project_dir: str, rows: list[dict], fact_ids: list[str],
                order: dict[str, int]) -> RecheckSet:
    """What rejecting ``fact_ids`` gets re-checked: listed now, or, when the
    establishing scene has prose, by its revision's gate pass."""
    from storyforge import cmd_audit
    found = cmd_audit._reject_recheck(project_dir, rows, fact_ids)
    scenes = {s for info in found.values() for s in info['recheck'] + info['later']}
    return RecheckSet(
        tuple(sorted(scenes, key=order.get)),
        tuple(f'{fid}: {info["unrelated"]}' for fid, info in found.items() if info['unrelated']),
        tuple(n for info in found.values() for n in info['not_listed']))


def later_usable(project_dir: str, scene: str, order: dict[str, int], gone: set[str]) -> int:
    """How many scenes after `scene` the reject flow could list."""
    return sum(1 for s in order if order[s] > order[scene]
               and not unusable(project_dir, s, order, gone))


def project_for(case: dict, commit: str, work_dir: str, root: str | None = None) -> str:
    return tree_dir(work_dir, case['repo'], commit, root)
