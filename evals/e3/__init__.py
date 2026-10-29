"""E3 — extraction: does today's extraction put into the ledger the facts
that later mattered?

Every E1 error implies a fact the ledger should have held: its established
side. For each non-holdout E1 prose case with a prose established span, the
book is materialized at that span's commit and today's two ledger prompts —
knowledge (``extract.build_knowledge_prompt``) and physical state
(``build_physical_state_prompt``) — are run on the establishing scene. An Opus
judge reads the established quote and both raw responses and says whether the
fact was captured.

**Scene-local, a stated simplification.** ``storyforge extract`` runs these
prompts as a chain, each scene seeing the knowledge and states the earlier
scenes produced. Replaying the chain up to every establishing scene would cost
the whole book per case, so each prompt here starts from an empty chain (the
tree's own knowledge registry is still offered as known ids). A fact the chain
would have carried in from earlier scenes may therefore read as missing.

Gate (plan, Phase 2): recall >= 0.85.
"""

from __future__ import annotations

import json
import os
import re

import e1
from e2.corpus import _has, _stem, tree_dir

JUDGE_PROMPT = """You are checking whether a story-data extraction captured one fact.

The fact, as the book states it in scene {scene}:
"{quote}"
(Context: a later scene contradicted this; the error was: {summary})

Below is everything the extraction produced for that scene: a knowledge pass and a physical-state pass.

<knowledge>
{knowledge}
</knowledge>

<physical_states>
{physical}
</physical_states>

Did the extraction record this fact — the specific claim, in any wording, as a fact or a state?

Answer with one JSON object and nothing else:
{{"verdict": "captured" | "partial" | "missing", "evidence": "<the extracted line that records it, or empty>"}}

"captured": the specific claim is recorded.
"partial": a related fact is recorded but the specific detail a later scene contradicted is not (e.g. "Hank drove to Portland" without the three hours).
"missing": nothing records it."""

VERDICTS = ('captured', 'partial', 'missing')


def select(root: str | None = None) -> tuple[list[dict], dict[str, list[str]]]:
    """One item per case: the case, its establishing scene and tree commit."""
    root = root or e1.corpus_dir()
    held = set(e1.load_holdout())
    items, excluded = [], {}
    for case in e1.load_cases():
        if case['level'] != 'prose':
            continue
        spans = [s for s in case['established'] if s.get('source', 'prose') == 'prose']
        repo_dir = os.path.join(root, case['repo'])
        reason = None
        if case['id'] in held:
            reason = 'holdout'
        elif not spans:
            reason = 'no prose established span'
        elif not os.path.isdir(os.path.join(repo_dir, '.git')):
            reason = f'{case["repo"]} not cloned'
        elif not _has(repo_dir, spans[0]['commit'], 'reference/scenes.csv'):
            reason = 'tree predates reference/scenes.csv'
        elif not _has(repo_dir, spans[0]['commit'], spans[0]['path']):
            reason = 'establishing scene file not in its tree'
        if reason:
            excluded.setdefault(reason, []).append(case['id'])
            continue
        items.append({'case': case, 'span': spans[0], 'scene': _stem(spans[0]),
                      'commit': spans[0]['commit']})
    return items, excluded


def extract(project_dir: str, scene_id: str) -> tuple[str, str]:
    """Today's knowledge and physical-state responses for one scene, scene-local."""
    from storyforge.api import extract_text, invoke
    from storyforge.common import select_model
    from storyforge.elaborate import _read_csv_as_map, get_scene
    from storyforge.extract import build_knowledge_prompt, build_physical_state_prompt
    from storyforge.enrich import format_registries_for_prompt

    ref_dir = os.path.join(project_dir, 'reference')
    with open(os.path.join(project_dir, 'scenes', f'{scene_id}.md'), encoding='utf-8') as f:
        text = f.read()
    scene = get_scene(scene_id, ref_dir) or {}
    model = select_model('evaluation')
    known = {fid: row.get('name', '') for fid, row in
             _read_csv_as_map(os.path.join(ref_dir, 'knowledge.csv')).items() if fid}
    knowledge_prompt = build_knowledge_prompt(
        scene_id, text, {k: scene.get(k, '') for k in ('title', 'pov', 'location', 'act')},
        {k: scene.get(k, '') for k in ('function', 'action_sequel')}, {}, [],
        registries_text=format_registries_for_prompt(project_dir, exclude=('knowledge.csv',)),
        known_facts=known)
    physical_prompt = build_physical_state_prompt(
        scene_id, text, {k: scene.get(k, '') for k in ('title', 'pov', 'location', 'act', 'on_stage')},
        {}, [], registries_text=format_registries_for_prompt(project_dir))
    out = []
    for prompt, kind in ((knowledge_prompt, 'knowledge'), (physical_prompt, 'physical')):
        response = extract_text(invoke(prompt, model, max_tokens=1024,
                                       label=f'e3 {kind} {scene_id}'))
        if not response.strip():
            raise RuntimeError(f'empty {kind} extraction for {scene_id}')
        out.append(response)
    return out[0], out[1]


def parse_verdict(text: str) -> dict:
    match = re.search(r'\{.*\}', text, re.DOTALL)
    if not match:
        raise ValueError(f'judge returned no JSON object: {text[:200]!r}')
    verdict = json.loads(match.group(0))
    if verdict.get('verdict') not in VERDICTS:
        raise ValueError(f'judge verdict {verdict.get("verdict")!r} is not one of {VERDICTS}')
    return verdict


def judge(item: dict, knowledge: str, physical: str) -> dict:
    from storyforge.api import extract_text, invoke
    from storyforge.common import LATEST_MODELS
    prompt = JUDGE_PROMPT.format(scene=item['scene'], quote=item['span']['quote'],
                                 summary=item['case']['summary'],
                                 knowledge=knowledge, physical=physical)
    return parse_verdict(extract_text(invoke(prompt, LATEST_MODELS['opus'], max_tokens=512,
                                             label=f'e3 judge {item["case"]["id"]}')))


def project_for(item: dict, work_dir: str, root: str | None = None) -> str:
    return tree_dir(work_dir, item['case']['repo'], item['commit'], root)
