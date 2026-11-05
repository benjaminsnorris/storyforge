"""The gate's source check: an adaptation's prose against the source (#557).

The gate checks a scene against what the book already says, never against
the source, so in an adaptation the first telling wins even when it is the
wrong one (B-031: a scene that told the poem's history the poem's way was
blocked by an earlier scene that hadn't), and facts misread from the prose
are committed (B-027: four facts on `grendel-takes-thirty-sleepers` the poem
contradicts). In a `faithful` adaptation (`source:` block, `mode: faithful`)
`review` makes one call (evaluation tier) for a scene mapped in
`reference/source-map.csv`, after the check, given the source scenes it
adapts (their summary, brief and prose) and, for each verified contradiction
with an earlier scene, the source scenes behind that scene. It rules:

- each proposed commitment: does the source contradict it? One it does is
  not committed (`GateResult.source_dropped`, reported);
- each verified contradiction with an earlier scene: which side the source
  backs. When it backs this scene, the finding doesn't block it
  (`GateResult.source_backed`): the commitments stating it are held back, as
  for an inherited one, and the earlier scene is listed `SOURCE_FIX` in
  working/gate-pending.csv for the author (a row that doesn't stop drafting).

A departure the version rules (`source.rules`) or the map row's treatment
or note authorize is not a contradiction. A project without a source, in
`free` mode, or a scene not mapped (or invented) makes no call, and the
check says why in a note. A call that fails is a note too, never a stop:
the consistency check stands on its own.
"""

from __future__ import annotations

import json
import os
from dataclasses import dataclass, field

#: The pending-row command for an earlier scene the source contradicts where
#: a later scene follows it (`gate._apply_source`): the author's to fix
SOURCE_FIX = 'source-fix'

#: The most source text (characters) one call is sent: past it, the earlier
#: scenes' sources are left out and contradictions with them not ruled on
MAX_SOURCE_CHARS = 60000

SCHEMA = {
    'type': 'object',
    'properties': {
        'facts': {'type': 'array', 'items': {
            'type': 'object',
            'properties': {'n': {'type': 'integer'},
                           'verdict': {'type': 'string',
                                       'enum': ['agrees', 'contradicts', 'not-in-source']},
                           'why': {'type': 'string'}},
            'required': ['n', 'verdict', 'why'], 'additionalProperties': False}},
        'contradictions': {'type': 'array', 'items': {
            'type': 'object',
            'properties': {'n': {'type': 'integer'},
                           'backs': {'type': 'string', 'enum': ['this', 'earlier', 'neither']},
                           'why': {'type': 'string'}},
            'required': ['n', 'backs', 'why'], 'additionalProperties': False}},
    },
    'required': ['facts', 'contradictions'],
    'additionalProperties': False,
}


class SourceReviewError(RuntimeError):
    """The call failed, was cut off, or its reply isn't the schema."""


@dataclass
class SourceReview:
    #: (index into the proposed rows, why) for each fact the source contradicts
    dropped: list[tuple[int, str]] = field(default_factory=list)
    #: (index into the contradictions sent, why) for each the source backs
    #: this scene on
    backs_scene: list[tuple[int, str]] = field(default_factory=list)
    #: what wasn't checked, and why
    notes: list[str] = field(default_factory=list)


@dataclass(frozen=True)
class Setup:
    """What `setup` found: the source scenes behind each scene, or why the
    check doesn't run."""
    refs: dict[str, list[tuple[str, str]]]
    rules: str
    map_rows: dict[str, dict[str, str]]
    skip: str = ''


def setup(project_dir: str) -> Setup | None:
    """None for a project with no `source:` block (nothing to say); a
    `Setup` with `skip` when the check can't run (free mode, no map, a bad
    config)."""
    from storyforge import source
    try:
        cfg = source.read_config(project_dir)
    except source.SourceError as e:
        return Setup({}, '', {}, skip=f'the source config can\'t be read ({e})')
    if cfg is None:
        return None
    if cfg.mode != 'faithful':
        return Setup({}, '', {}, skip=f'source.mode is {cfg.mode}: fidelity isn\'t checked')
    try:
        rows = source.read_source_map(project_dir)
        rules = source.read_rules(project_dir, cfg)
        cat = source.catalogue(project_dir, cfg)
    except (source.SourceError, OSError, ValueError) as e:
        return Setup({}, '', {}, skip=f'the source can\'t be read ({e})')
    if not rows:
        return Setup({}, rules, {}, skip='reference/source-map.csv is missing or empty')
    by_scene = source.map_rows_by_scene(rows)
    refs: dict[str, list[tuple[str, str]]] = {}
    for sid, row in by_scene.items():
        if row.get('treatment') == 'invent':
            continue
        found = [source.resolve_source_id(r, cat)
                 for r in source.split_ids(row.get('source_scenes', ''))]
        if found and all(found):
            refs[sid] = found
    return Setup(refs, rules, by_scene)


def _source_text(project_dir: str, refs: list[tuple[str, str]]) -> str:
    from storyforge.prompts_source import source_scene_block
    return '\n\n'.join(source_scene_block(project_dir, slug, sid, prose=True)
                       for slug, sid in refs)


def build_prompt(scene_id: str, prose: str, facts: list[dict[str, str]],
                 contradictions: list[tuple[str, str, str, str]], this_source: str,
                 earlier_sources: dict[str, str], rules: str, treatment: str,
                 note: str) -> str:
    """`contradictions`: (this scene's words, the earlier scene, its words,
    the check's explanation). `earlier_sources`: earlier scene id → the
    source text behind it."""
    fact_lines = '\n'.join(f'{n}. {f.get("statement", "")} (the scene\'s words: '
                           f'"{f.get("quote", "")}")'
                           for n, f in enumerate(facts, start=1)) or '(none)'
    con_lines = '\n'.join(
        f'{n}. This scene says "{q}"; earlier scene {sid} says "{eq}". The check: {why}'
        for n, (q, sid, eq, why) in enumerate(contradictions, start=1)) or '(none)'
    earlier = '\n\n'.join(f'### The source behind {sid}\n\n{text}'
                          for sid, text in earlier_sources.items()) or '(none)'
    return f"""Scene {scene_id} of a faithful adaptation is checked against its source. Rule on two lists.

1. Facts: each was read from the scene's prose and will bind later scenes. Does the source contradict it? `contradicts` only when the source says otherwise (a different person, count, place, order, cause or outcome), not when the source is silent or the fact adds detail (`not-in-source`). A departure the version rules or the map's treatment or note allow is not a contradiction.
2. Contradictions: each is between this scene and an earlier scene of the adaptation. Which side does the source back? `this` when the source tells it this scene's way, `earlier` when the earlier scene's, `neither` when the source backs neither or is silent.

Give each `why` in one sentence, quoting the source.

## Version rules

{rules or '(none)'}

## The map

Treatment: {treatment or '(none)'}. Note: {note or '(none)'}.

## The source this scene adapts

{this_source}

## Earlier scenes' sources

{earlier}

## Scene {scene_id}

{prose}

## Facts

{fact_lines}

## Contradictions

{con_lines}"""


def review(project_dir: str, scene_id: str, prose: str, facts: list[dict[str, str]],
           contradictions: list, *, model: str, log_file: str,
           ctx: Setup) -> SourceReview:
    """Rule on `facts` (the proposed rows) and `contradictions` (verified
    `checker.Finding`s with an earlier scene, by index) for `scene_id`.
    `ctx` must have no `skip` and map the scene (`setup`).

    Raises:
        SourceReviewError: the call failed or its reply can't be used.
    """
    from storyforge.api import extract_text, invoke_to_file, is_truncated
    out = SourceReview()
    this = _source_text(project_dir, ctx.refs[scene_id])
    budget = MAX_SOURCE_CHARS - len(this)
    earlier: dict[str, str] = {}
    sent: list[int] = []
    for i, f in enumerate(contradictions):
        sid = f.established_scene
        if sid not in earlier:
            if sid not in ctx.refs:
                out.notes.append(f'{sid} is not mapped to the source: its contradiction '
                                 f'with {scene_id} isn\'t ruled on')
                continue
            text = _source_text(project_dir, ctx.refs[sid])
            if len(text) > budget:
                out.notes.append(f'the source behind {sid} would pass {MAX_SOURCE_CHARS} '
                                 f'characters: its contradiction isn\'t ruled on')
                continue
            budget -= len(text)
            earlier[sid] = text
        sent.append(i)
    row = ctx.map_rows.get(scene_id, {})
    prompt = build_prompt(scene_id, prose, facts,
                          [(contradictions[i].scene_quote, contradictions[i].established_scene,
                            contradictions[i].established_quote,
                            contradictions[i].explanation) for i in sent],
                          this, earlier, ctx.rules, row.get('treatment', ''),
                          row.get('note', ''))
    try:
        response = invoke_to_file(prompt, model, log_file, 4000, output_schema=SCHEMA,
                                  label=f'source check {scene_id}')
        if is_truncated(response):
            raise ValueError('the reply hit its token limit')
        reply = json.loads(extract_text(response))
        for item in reply['facts']:
            n = int(item['n'])
            if item['verdict'] == 'contradicts' and 1 <= n <= len(facts):
                out.dropped.append((n - 1, str(item.get('why', ''))))
        for item in reply['contradictions']:
            n = int(item['n'])
            if item['backs'] == 'this' and 1 <= n <= len(sent):
                out.backs_scene.append((sent[n - 1], str(item.get('why', ''))))
    except (RuntimeError, ValueError, KeyError, TypeError) as e:
        raise SourceReviewError(f'{scene_id}: the source check failed: {e}') from e
    return out


def log_file(log_dir: str, scene_id: str) -> str:
    return os.path.join(log_dir, f'gate-source-{scene_id}.json')
