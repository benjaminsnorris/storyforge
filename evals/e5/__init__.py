"""E5 — roundtrip: redraft scenes from the plan and count the facts that change.

A scene redrafted from its brief and the book's reference material should
agree with the original on every fact a reader would notice. Each fact the
redraft changes is something the plan and ledger failed to pin down — a
ledger gap. E5 redrafts a fixed sample with today's redraft-from-brief pass
(the same call as E8's) and an Opus judge lists every fact the redraft
contradicts, by error code. Omissions are not mismatches: a redraft may leave
a detail out, it may not change it.

The sample is the first ``SAMPLE`` drafted scenes of Act 1 of shared-dark at a
pinned commit — the book decision 7 picked for E4, so E1, E4, E5 and E8 share a
world. The metric is a trend (plan: "should fall as the ledger improves"), so
the only gate is coverage.

**The ledger the redraft reads.** The pinned tree predates the ledger, so its
registries are migrated (``harness.migrate_tree``), and then extract phase 4
(the commitments rubric) is run over the scenes in reading order up to the
last sampled one (``commit_prose``), as an author would after drafting. Each
redraft is then given what the ledger holds for it (``prompts``'s established
facts): the states and fixed facts in force entering the scene, and the
commitments its own prose made. That is the point of the suite: a fact the
ledger pins should survive a redraft. It also means the number is not
like-for-like with runs before v1.97.0, when the redraft had only the brief
and the bibles: part of a fall comes from the redraft being shown facts read
off the very prose it is judged against. Any change to phase 4 (its rubric,
what it is offered: F-127, F-128 in v1.98.0) moves the number too.
"""

from __future__ import annotations

import csv
import json
import os
import re

import e1
from e8 import materialize, redraft

REPO = 'shared-dark'
# Pinned so replays hit. 5e9bdf39 (2026-04-07) is the last commit before
# revise's upstream brief fix ran on shared-dark: from ac569274 on it rewrote
# 21 of the 23 Act 1 briefs, 17 of them naming people the book never
# mentions, so E4's BPS measured the corrupt briefs (the previous pin,
# 0eaa3867, was after it).
COMMIT = '5e9bdf39'
SAMPLE = 10
FACT_CODES = ('PHY', 'TIM', 'KNO', 'REL', 'TRT', 'WLD')

JUDGE_PROMPT = """Compare two versions of the same scene of a novel: the author's original, and a redraft written from the scene's plan.

List every FACT on which the redraft contradicts the original — something a careful reader of the original would notice is now different: a name, number, time, date, place, who is present, who knows what, who is related to whom, a physical state or possession, a rule of the world.

Do not list: facts the redraft leaves out, differences in wording, style, emphasis, or order, or details the original never states.

<original>
{original}
</original>

<redraft>
{redraft}
</redraft>

Answer with one JSON object and nothing else:
{{"mismatches": [{{"code": "PHY" | "TIM" | "KNO" | "REL" | "TRT" | "WLD", "fact": "<the fact, one sentence>", "original": "<verbatim from the original>", "redraft": "<verbatim from the redraft>"}}]}}
An empty list is a valid answer."""


def sample(project_dir: str, n: int = SAMPLE) -> list[str]:
    """The first ``n`` Act 1 scenes in reading order that have prose and a brief
    (``part`` stands in for ``act`` on books whose scenes.csv predates it)."""
    ref = os.path.join(project_dir, 'reference')
    with open(os.path.join(ref, 'scenes.csv'), newline='', encoding='utf-8') as f:
        scenes = list(csv.DictReader(f, delimiter='|'))
    with open(os.path.join(ref, 'scene-briefs.csv'), newline='', encoding='utf-8') as f:
        briefed = {r['id'] for r in csv.DictReader(f, delimiter='|') if (r.get('goal') or '').strip()}
    picked = []
    for row in sorted(scenes, key=lambda r: float(r.get('seq') or 0)):
        sid = row['id']
        path = os.path.join(project_dir, 'scenes', f'{sid}.md')
        act = (row.get('act') or row.get('part') or '').strip()  # older books have only part
        if act == '1' and sid in briefed and os.path.isfile(path) \
                and os.path.getsize(path) > 0:
            picked.append(sid)
        if len(picked) == n:
            break
    return picked


def parse_mismatches(text: str) -> list[dict]:
    match = re.search(r'\{.*\}', text, re.DOTALL)
    if not match:
        raise ValueError(f'judge returned no JSON object: {text[:200]!r}')
    data = json.loads(match.group(0))
    items = data.get('mismatches')
    if not isinstance(items, list):
        raise ValueError('judge answer has no "mismatches" list')
    bad = [m for m in items if not isinstance(m, dict) or m.get('code') not in FACT_CODES]
    if bad:
        raise ValueError(f'judge returned {len(bad)} mismatch(es) without a fact code')
    return items


def judge(original: str, redrafted: str, scene_id: str) -> list[dict]:
    from storyforge.api import extract_text, invoke
    from storyforge.common import model_for_tier
    return parse_mismatches(extract_text(invoke(
        JUDGE_PROMPT.format(original=original, redraft=redrafted), model_for_tier('opus'),
        max_tokens=4096, label=f'e5 judge {scene_id}')))


def project(work_dir: str, root: str | None = None) -> str:
    repo_dir = os.path.join(root or e1.corpus_dir(), REPO)
    if not os.path.isdir(os.path.join(repo_dir, '.git')):
        raise RuntimeError(f'{REPO} is not cloned at {repo_dir}')
    return materialize(repo_dir, COMMIT, os.path.join(work_dir, f'{REPO}-{COMMIT}'))


def commit_prose(project_dir: str, scenes: list[str]) -> None:
    """Run extract phase 4 over every scene in reading order up to the last
    of ``scenes``, writing its commitments into the tree's ledger.

    The tree is not a git repository; phase 4's commit is replaced by
    nothing. A scene phase 4 cannot read stops it (``SystemExit`` there),
    which errors the suite.
    """
    from unittest import mock

    from storyforge import cmd_extract, ledger
    ref_dir = os.path.join(project_dir, 'reference')
    scenes_dir = os.path.join(project_dir, 'scenes')
    log_dir = os.path.join(project_dir, 'working', 'logs')
    os.makedirs(log_dir, exist_ok=True)
    order = ledger.scene_order(project_dir)   # drafting's order, seq as a number
    ordered = [s for s in sorted(order, key=order.get)
               if os.path.isfile(os.path.join(scenes_dir, f'{s}.md'))]
    last = max(ordered.index(s) for s in scenes)
    with mock.patch.object(cmd_extract, 'commit_and_push', lambda *a, **k: False):
        try:
            cmd_extract._run_phase_4(ordered[:last + 1], project_dir, scenes_dir,
                                     ref_dir, log_dir, force=False, dry_run=False)
        except SystemExit as e:
            raise RuntimeError(f'extract phase 4 stopped (exit {e.code}); '
                               f'see {log_dir}') from None


def roundtrip(project_dir: str, scene_id: str) -> tuple[str, list[dict]]:
    """Redraft one scene from its brief and judge it against the original."""
    with open(os.path.join(project_dir, 'scenes', f'{scene_id}.md'), encoding='utf-8') as f:
        original = f.read()
    redrafted = redraft(project_dir, scene_id)
    return redrafted, judge(original, redrafted, scene_id)
