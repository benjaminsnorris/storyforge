"""E4 — generation benchmark: draft a fixed book section end to end with
today's ``write`` and measure what a reader would trip over.

The test text is Act 1 of shared-dark (decision 7) at the commit E5 pins, so
E1, E4, E5 and E8 share a world. Every Act 1 scene's prose is removed, then
the scenes are drafted in reading order the way ``storyforge write``
drafts them: one shared, cached system context, ``cmd_write._build_prompt``
with briefs, each prompt built after the scenes before it exist, so a scene's
``continuity_deps`` read the new drafts, not the author's prose. A scene the
model refuses is counted as ``refused`` (and fails the coverage gate); any
other drafting failure errors the suite.

Metrics (plan §4.2):

- **CP10k** — contradictions per 10,000 drafted words, from an Opus judge that
  reads each scene against the Act 1 drafts before it and the book's bibles.
  ``cp10k_checker`` is the same rate for the shipped checker, the timeline
  drift check ``write`` runs after drafting (it only knows time).
- **BPS** — broken promises per scene: brief items the scene fails to deliver
  (outcome, decision, key actions, required dialogue, knowledge out), by the
  same judge call.
- **Length drift** — mean ``|words / target_words - 1|``.
- **VOI** — mean of the deterministic prose scores (rhythm, economy, passive,
  adverbs; 1–5) over the drafts; ``voi_author`` is the same over the author's
  Act 1 prose at the pinned commit, for scale.

Each draft is gated as ``write`` gates it (``gate.gate_and_fix``) before
the next prompt is built; ``gate_fixed`` and ``gate_failed`` count the
scenes the fix changed and those still failing after it.

Stated simplifications: a scene still failing the gate doesn't stop E4 as it
stops ``write``; its fixed prose is judged and drafting goes on. The judge
stands in
for the plan's human spot-check, which is still owed. Act 2 onward keeps the
author's prose; only Act 1 is drafted.
"""

from __future__ import annotations

import json
import os
import re

import e5
from e8 import materialize

REPO = e5.REPO
COMMIT = e5.COMMIT
ACT = '1'
DRAFT_MAX_TOKENS = 8192  # cmd_write's direct mode
FACT_CODES = e5.FACT_CODES
PROMISE_FIELDS = ('goal', 'outcome', 'crisis', 'decision', 'key_actions', 'key_dialogue',
                  'knowledge_out', 'physical_state_out')
# What the judge checks a scene against, besides the drafts before it
REFERENCE_FILES = ('character-bible.md', 'world-bible.md', 'systems-bible.md', 'characters.csv')

JUDGE_PROMPT = """You are checking one newly drafted scene of a novel for continuity errors and for promises its plan made that the scene does not keep.

The book's reference material (character bible, world bible, character list) is in the system prompt. These are the scenes drafted before this one, in reading order:

<earlier_scenes>
{earlier}
</earlier_scenes>

This is the plan for the scene:

<brief>
{brief}
</brief>

This is the scene:

<scene id="{scene_id}">
{scene}
</scene>

1. CONTRADICTIONS. List every fact in this scene that contradicts an earlier scene or the reference material — something a careful reader would notice: a name, number, time, date, place, who is present, who knows what, who is related to whom, a physical state or possession, a rule of the world. A fact the earlier scenes or reference never state is not a contradiction. Do not list style, emphasis, or omissions.

2. BROKEN PROMISES. List every item of the brief that the scene does not deliver: the outcome or decision does not happen, a key action is missing, a required line of dialogue (or a close paraphrase) is absent, the POV character does not reach the knowledge_out, a physical_state_out is not established. Interpretive fields (emotions, motifs, subtext) are not promises.

Answer with one JSON object and nothing else:
{{"contradictions": [{{"code": "PHY" | "TIM" | "KNO" | "REL" | "TRT" | "WLD", "fact": "<one sentence>", "quote": "<verbatim from this scene>", "against": "<verbatim from an earlier scene or the reference, with its scene id or file>"}}],
 "broken_promises": [{{"field": "goal" | "outcome" | "crisis" | "decision" | "key_actions" | "key_dialogue" | "knowledge_out" | "physical_state_out", "promise": "<the brief item>", "why": "<one sentence>"}}]}}
Empty lists are valid answers."""


def _read_rows(path: str) -> list[dict]:
    from storyforge.elaborate import _read_csv  # Storyforge CSVs are unquoted
    return _read_csv(path)


def _read(path: str) -> str:
    with open(path, encoding='utf-8') as f:
        return f.read()


def act_scenes(project_dir: str, act: str = ACT) -> list[dict]:
    """The act's scenes.csv rows in reading order (``part`` stands in for
    ``act`` on books whose scenes.csv predates it)."""
    rows = _read_rows(os.path.join(project_dir, 'reference', 'scenes.csv'))
    return [r for r in sorted(rows, key=lambda r: float(r.get('seq') or 0))
            if (r.get('act') or r.get('part') or '').strip() == act]


def project(work_dir: str, root: str | None = None) -> str:
    return e5.project(work_dir, root)


def clear_prose(project_dir: str, scene_ids: list[str]) -> dict[str, str]:
    """Remove the scenes' prose; return the author's text by id."""
    original = {}
    for sid in scene_ids:
        path = os.path.join(project_dir, 'scenes', f'{sid}.md')
        if os.path.isfile(path):
            original[sid] = _read(path)
            os.remove(path)
    return original


def draft(project_dir: str, scene_ids: list[str], gated: dict | None = None,
          log_dir: str = '') -> tuple[dict[str, str], dict[str, str]]:
    """Draft the scenes in order as ``write --direct`` does. Returns (prose by
    id, refusal reason by id). Like ``write``, E4 records a refused scene and
    drafts on; a refused scene has no prose and is not judged. Unlike
    ``write``, E4 sends no refusal fallback, so every refusal by the requested
    model counts as ``refused`` (a cassette strips the fallback anyway). Unlike
    ``write``, E4 does not apply the cut-off guard
    (``cmd_write._extract_scene_from_response``), so it can judge a draft that
    ``write`` would refuse to save; no recorded draft has been cut off.

    With ``gated`` (a dict to fill), each draft goes through ``write``'s gate
    (``gate.gate_and_fix``: extract, check, fix once, re-check, commit to the
    ledger when clean) before the next scene's prompt is built, and
    ``gated[scene_id]`` is its ``GatedScene``. Unlike ``write``, a scene that
    still fails doesn't stop E4: the fixed prose is judged and the next scene
    drafted (``write`` would stop and wait for the author), and the count is
    reported. A ``GateError`` errors the suite."""
    from storyforge import gate
    from storyforge.api import RefusalError, extract_text, invoke
    from storyforge.cmd_write import _build_prompt
    from storyforge.common import build_shared_context, select_model
    from storyforge.csv_cli import update_field
    from storyforge.parsing import clean_scene_content, extract_single_scene

    model = select_model('drafting')
    system = build_shared_context(project_dir, model=model)
    metadata_csv = os.path.join(project_dir, 'reference', 'scenes.csv')
    drafts = {}
    refused = {}
    for sid in scene_ids:
        prompt = _build_prompt(sid, project_dir, 'full', use_briefs=True,
                               system_context=bool(system))
        if not prompt:
            raise RuntimeError(f'could not build a drafting prompt for {sid}')
        try:
            text = extract_text(invoke(prompt, model, max_tokens=DRAFT_MAX_TOKENS,
                                       label=f'e4 draft {sid}', system=system or None))
        except RefusalError as e:
            refused[sid] = str(e)
            continue
        prose = clean_scene_content(extract_single_scene(text) or text) if text else ''
        words = len(prose.split())
        if words < 100:  # cmd_write's _MIN_SCENE_WORDS
            raise RuntimeError(f'draft of {sid} is {words} words')
        with open(os.path.join(project_dir, 'scenes', f'{sid}.md'), 'w', encoding='utf-8') as f:
            f.write(prose)
        if gated is not None:
            out = gate.gate_and_fix(project_dir, sid, command='draft', prose=prose,
                                    log_dir=os.path.join(log_dir or os.path.join(
                                        project_dir, 'working', 'logs', 'gate'), sid))
            prose = out.prose
            with open(os.path.join(project_dir, 'scenes', f'{sid}.md'), 'w',
                      encoding='utf-8') as f:
                f.write(prose)
            words = len(prose.split())
            gated[sid] = out
        update_field(metadata_csv, sid, 'word_count', str(words))
        update_field(metadata_csv, sid, 'status', 'drafted')
        drafts[sid] = prose
    return drafts, refused


def brief_block(project_dir: str, scene_id: str) -> str:
    rows = {r['id']: r for r in _read_rows(os.path.join(project_dir, 'reference',
                                                        'scene-briefs.csv'))}
    row = rows.get(scene_id, {})
    return '\n'.join(f'{k}: {(row.get(k) or "").strip()}' for k in PROMISE_FIELDS
                     if (row.get(k) or '').strip())


def judge_system(project_dir: str) -> list[dict]:
    ref = os.path.join(project_dir, 'reference')
    parts = [f'## {name}\n\n{_read(os.path.join(ref, name))}'
             for name in REFERENCE_FILES if os.path.isfile(os.path.join(ref, name))]
    if not parts:
        raise RuntimeError(f'no reference files for the E4 judge in {ref}')
    return [{'type': 'text', 'text': '\n\n'.join(parts),
             'cache_control': {'type': 'ephemeral'}}]


def judge_prompt(earlier: list[tuple[str, str]], brief: str, scene_id: str, scene: str) -> str:
    text = '\n\n'.join(f'<scene id="{sid}">\n{prose}\n</scene>' for sid, prose in earlier)
    return JUDGE_PROMPT.format(earlier=text or '(none: this is the first scene)',
                               brief=brief, scene_id=scene_id, scene=scene)


def parse_judgment(text: str) -> dict:
    """The judge's JSON. Raises ValueError rather than guessing: an unreadable
    answer must error the suite, never count as clean."""
    match = re.search(r'\{.*\}', text, re.DOTALL)
    if not match:
        raise ValueError(f'judge returned no JSON object: {text[:200]!r}')
    data = json.loads(match.group(0))
    contradictions = data.get('contradictions')
    promises = data.get('broken_promises')
    if not isinstance(contradictions, list) or not isinstance(promises, list):
        raise ValueError('judge answer needs "contradictions" and "broken_promises" lists')
    if any(not isinstance(c, dict) or c.get('code') not in FACT_CODES for c in contradictions):
        raise ValueError('judge returned a contradiction without a fact code')
    if any(not isinstance(p, dict) or p.get('field') not in PROMISE_FIELDS for p in promises):
        raise ValueError('judge returned a broken promise without a brief field')
    return {'contradictions': contradictions, 'broken_promises': promises}


def judge(project_dir: str, scene_ids: list[str], drafts: dict[str, str]) -> dict[str, dict]:
    from storyforge.api import extract_text, invoke
    from storyforge.common import model_for_tier
    system = judge_system(project_dir)
    model = model_for_tier('opus')
    results = {}
    scene_ids = [s for s in scene_ids if s in drafts]
    for i, sid in enumerate(scene_ids):
        earlier = [(s, drafts[s]) for s in scene_ids[:i]]
        prompt = judge_prompt(earlier, brief_block(project_dir, sid), sid, drafts[sid])
        results[sid] = parse_judgment(extract_text(invoke(
            prompt, model, max_tokens=4096, label=f'e4 judge {sid}', system=system)))
    return results


def checker_flags(project_dir: str, scene_ids: list[str]) -> list[dict]:
    """The shipped checker ``write`` runs after drafting: the timeline drift check."""
    import e2
    return e2.drift_check(project_dir, scene_ids,
                          os.path.join(project_dir, 'working', 'logs'))


def voice_score(text: str, ai_tell_words: list[dict]) -> float:
    """Mean of the deterministic prose scores (1–5) for one scene."""
    from storyforge.scoring_adverbs import score_avoid_adverbs
    from storyforge.scoring_economy import score_economy_clarity
    from storyforge.scoring_passive import score_avoid_passive
    from storyforge.scoring_rhythm import score_sentence_as_thought
    scores = (score_sentence_as_thought(text)['score'],
              score_economy_clarity(text, ai_tell_words=ai_tell_words)['score'],
              score_avoid_passive(text)['score'],
              score_avoid_adverbs(text)['score'])
    return sum(scores) / len(scores)


def mean_voice(texts: list[str]) -> float:
    from storyforge.common import get_plugin_dir
    from storyforge.prose_analysis import load_ai_tell_words
    if not texts:
        return 0.0
    words = load_ai_tell_words(get_plugin_dir())
    return round(sum(voice_score(t, words) for t in texts) / len(texts), 3)


def length_drift(rows: list[dict], drafts: dict[str, str]) -> float:
    """Mean ``|words / target - 1|`` over the drafted scenes with a target."""
    drifts = [abs(len(drafts[r['id']].split()) / int(r['target_words']) - 1)
              for r in rows if r['id'] in drafts and (r.get('target_words') or '').strip().isdigit()
              and int(r['target_words']) > 0]
    return round(sum(drifts) / len(drifts), 3) if drifts else 0.0


def per_10k(count: int, words: int) -> float:
    return round(count * 10000 / words, 3) if words else 0.0


def gate_measure(scene_ids: list[str], drafts: dict[str, str], judged: dict[str, dict],
                 failed: set[str]) -> dict:
    """Read the judge against the gate, the way ``write`` would have run.

    ``write`` stops at the first scene still failing the gate (keeping its
    prose, committing nothing), so the **headline** counts the drafted scenes
    through that one, inclusive; with no failure it is every drafted scene.
    E4 drafts on past it, from a ledger missing that scene's facts, and the
    ``*_all`` figures count every drafted scene (the pre-#450 headline).

    ``passed`` are the drafted scenes the gate let through, anywhere in the
    act: ``cp10k_passed`` is the rate in prose ``write`` would commit.

    The gate's catch rate is per scene, against the judge's contradictions:
    a scene the judge finds a contradiction in is ``caught`` when the gate
    failed it and ``missed`` when the gate passed it; a scene the gate failed
    but the judge found clean is a ``false_alarm`` (the gate also blocks on
    broken promises and extraction problems, so not every false alarm is the
    checker's error). Returns the metrics, a label per scene and the
    headline's scene ids."""
    drafted = [s for s in scene_ids if s in drafts]
    first = next((i for i, s in enumerate(drafted) if s in failed), len(drafted) - 1)
    headline = drafted[:first + 1]
    passed = [s for s in drafted if s not in failed]

    def words(ids):
        return sum(len(drafts[s].split()) for s in ids)

    def contradictions(ids):
        return sum(len(judged[s]['contradictions']) for s in ids)

    def promises(ids):
        return sum(len(judged[s]['broken_promises']) for s in ids)

    labels = {}
    for sid in drafted:
        flagged = bool(judged[sid]['contradictions'])
        if sid in failed:
            labels[sid] = 'caught' if flagged else 'false_alarm'
        else:
            labels[sid] = 'missed' if flagged else 'clean'
    count = {k: sum(1 for v in labels.values() if v == k)
             for k in ('caught', 'missed', 'false_alarm', 'clean')}
    judged_bad = count['caught'] + count['missed']
    return {
        'metrics': {
            'scenes_to_first_gate_failure': len(headline),
            'words': words(headline),
            'contradictions': contradictions(headline),
            'cp10k': per_10k(contradictions(headline), words(headline)),
            'broken_promises': promises(headline),
            'bps': round(promises(headline) / len(headline), 3) if headline else 0.0,
            'words_all': words(drafted),
            'contradictions_all': contradictions(drafted),
            'cp10k_all': per_10k(contradictions(drafted), words(drafted)),
            'broken_promises_all': promises(drafted),
            'bps_all': round(promises(drafted) / len(drafted), 3) if drafted else 0.0,
            'scenes_passed': len(passed),
            'contradictions_passed': contradictions(passed),
            'cp10k_passed': per_10k(contradictions(passed), words(passed)),
            'contradictions_in_failed': contradictions([s for s in drafted if s in failed]),
            'gate_caught': count['caught'],
            'gate_missed': count['missed'],
            'gate_false_alarm': count['false_alarm'],
            'gate_catch_rate': round(count['caught'] / judged_bad, 3) if judged_bad else 0.0,
        },
        'labels': labels,
        'headline': headline,
    }
