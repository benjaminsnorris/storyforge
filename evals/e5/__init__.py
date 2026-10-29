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
"""

from __future__ import annotations

import csv
import json
import os
import re

import e1
from e8 import materialize, redraft

REPO = 'shared-dark'
COMMIT = '0eaa3867'  # shared-dark HEAD when E5 was recorded; pinned so replays hit
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


def roundtrip(project_dir: str, scene_id: str) -> tuple[str, list[dict]]:
    """Redraft one scene from its brief and judge it against the original."""
    with open(os.path.join(project_dir, 'scenes', f'{scene_id}.md'), encoding='utf-8') as f:
        original = f.read()
    redrafted = redraft(project_dir, scene_id)
    return redrafted, judge(original, redrafted, scene_id)
