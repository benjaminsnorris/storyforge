"""LLM-driven boundary faithfulness scoring (#231).

Per the cascade + scoring design docs, every level boundary has *two*
checks: a deterministic downward coverage check (v1 ships these via
scoring_levels + scoring_consistency) and a semantic upward faithfulness
diff.

This module is the semantic side. It runs the LLM, builds a structured
diff between upstream and downstream content at each of the seven
boundaries, and persists the result to working/scoring-verdicts.csv via
scoring_state.

The synthesis's coaching-level-aware actor rule:

  - full   — LLM proposes a verdict; persists immediately; surfaced for
             the author to override if they disagree. The author keeps
             editorial control via working/scoring-overrides.csv.
  - coach  — LLM proposes; the verdict is NOT persisted until the
             author confirms. Returned as `proposed=True, persisted=False`.
  - strict — LLM produces the diff only; never proposes a verdict.
             Author authors verdicts directly via append_verdict.

Output contract (one record per boundary scope):

    {
        'boundary': '5->6',
        'scope': 'act1-sc01',      # 'global' for prose-tier
        'upstream_summary': str,
        'downstream_summary': str,
        'alignment': str,           # narrative on how the two compare
        'proposed_verdict': str,    # one of VALID_BOUNDARY_VERDICTS, or ''
        'rationale': str,
        'persisted': bool,
    }

Costs: every call goes through `invoke_to_file` and the cost ledger via
`log_operation`, so v2 spending is visible in `working/costs/ledger.csv`
exactly like every other LLM path. Per the engineering review of v1, a
full `score --all-boundaries` run on a 50-scene project costs ~$1-2 with
the existing model selection (Sonnet for analytical comparisons).
"""

import json
import os
import re
from datetime import datetime, timezone

from storyforge.api import (
    invoke_to_file, extract_text_from_file,
    extract_usage, calculate_cost_from_usage,
)
from storyforge.common import (
    detect_project_root, get_coaching_level, log, parse_story_summary,
    select_model,
)
from storyforge.costs import log_operation
from storyforge.elaborate import _read_csv
from storyforge.scoring_state import (
    VALID_BOUNDARY_VERDICTS, append_verdict, get_verdict,
)


# ============================================================================
# Boundary identifiers
# ============================================================================

# Boundaries the v2 LLM faithfulness pass supports. Each id is rendered
# as N->M so it matches the scoring-verdicts.csv format and the CLI flag
# the author types.
BOUNDARY_IDS = (
    '0->1',  # logline → synopsis
    '1->2',  # synopsis → act-shape
    '2->3',  # act-shape → spine
    '3->4',  # spine → architecture
    '4->5',  # architecture → scenes (map)
    '5->6',  # map → briefs
    '6->7',  # briefs → draft
)

# Prose-tier boundaries are "global" — one diff for the whole story —
# rather than per-scene. The structural-tier boundaries are per-scope.
PROSE_BOUNDARIES = frozenset({'0->1', '1->2', '2->3'})


# ============================================================================
# Public API
# ============================================================================

def score_boundary(project_dir: str, boundary: str,
                   scope: str | None = None,
                   model: str | None = None,
                   coaching_level: str | None = None,
                   dry_run: bool = False) -> list[dict]:
    """Run the LLM faithfulness diff at one boundary.

    Args:
        project_dir: Project root.
        boundary: One of BOUNDARY_IDS, e.g., '5->6'.
        scope: For structural-tier boundaries (3->4, 4->5, 5->6, 6->7),
            a specific scope id (scene/anchor/event). When None, runs
            every scope at that boundary. Ignored for prose-tier
            boundaries (they're always global).
        model: Optional model override. Default: select_model('evaluation')
            (Sonnet).
        coaching_level: Override the project's coaching_level for this
            call. Default: read from project storyforge.yaml.
        dry_run: Build the prompt(s) but skip the API call. Returns
            stubbed diff dicts so callers can inspect what would be sent.

    Returns:
        List of diff dicts. One element for prose-tier boundaries; one
        per scope for structural-tier (filtered to the requested scope
        if provided).
    """
    if boundary not in BOUNDARY_IDS:
        raise ValueError(
            f'unknown boundary {boundary!r}; expected one of {BOUNDARY_IDS}'
        )

    coaching_level = coaching_level or get_coaching_level(project_dir)
    model = model or select_model('evaluation')

    pairs = _collect_pairs(project_dir, boundary, scope)
    if not pairs:
        log(f'No content to compare at boundary {boundary}'
            + (f' for scope {scope!r}' if scope else ''))
        return []

    results: list[dict] = []
    for scope_id, upstream, downstream in pairs:
        if not upstream.strip() or not downstream.strip():
            log(f'  [{boundary} / {scope_id}] skip: '
                'one side is empty (run the deterministic floor first)')
            continue

        # Idempotency: if a verdict is already recorded for (scope, boundary),
        # skip the LLM call. The cascade design (re-flag on content change)
        # is content-hash-based and lives in cmd_sync; for v2 the simple
        # rule is "verdict exists → trust it until explicitly cleared."
        existing = get_verdict(scope_id, boundary, project_dir=project_dir)
        if existing and not dry_run:
            log(f'  [{boundary} / {scope_id}] skip: verdict already recorded '
                f'({existing.get("verdict")!r})')
            continue

        if dry_run:
            results.append({
                'boundary': boundary, 'scope': scope_id,
                'upstream_summary': upstream[:200],
                'downstream_summary': downstream[:200],
                'alignment': '(dry run)',
                'proposed_verdict': '',
                'rationale': '',
                'persisted': False,
            })
            continue

        diff = _invoke_llm_diff(
            project_dir, boundary, scope_id, upstream, downstream,
            model=model,
        )
        if diff is None:
            continue

        diff['persisted'] = _persist_per_coaching(
            project_dir, boundary, scope_id, diff, coaching_level,
        )
        results.append(diff)

    return results


def score_all_boundaries(project_dir: str,
                         model: str | None = None,
                         coaching_level: str | None = None,
                         dry_run: bool = False) -> list[dict]:
    """Run every boundary in BOUNDARY_IDS. Returns the merged result list."""
    all_results: list[dict] = []
    for boundary in BOUNDARY_IDS:
        all_results.extend(score_boundary(
            project_dir, boundary, model=model,
            coaching_level=coaching_level, dry_run=dry_run,
        ))
    return all_results


# ============================================================================
# Content collection — what does each boundary compare?
# ============================================================================

def _collect_pairs(project_dir: str, boundary: str,
                   scope: str | None) -> list[tuple[str, str, str]]:
    """Return [(scope_id, upstream_content, downstream_content), ...].

    Prose-tier boundaries return a single-element list with scope_id='global'.
    Structural-tier boundaries return one element per affected unit (filtered
    to `scope` when provided).
    """
    summary = parse_story_summary(project_dir) or {}

    if boundary == '0->1':
        return [('global', summary.get('logline', ''), summary.get('synopsis', ''))]
    if boundary == '1->2':
        return [('global', summary.get('synopsis', ''), summary.get('act_shape', ''))]
    if boundary == '2->3':
        spine_text = _render_spine_text(project_dir)
        return [('global', summary.get('act_shape', ''), spine_text)]
    if boundary == '3->4':
        return _collect_per_spine_event(project_dir, scope)
    if boundary == '4->5':
        return _collect_per_architecture_anchor(project_dir, scope)
    if boundary == '5->6':
        return _collect_per_scene_intent_vs_brief(project_dir, scope)
    if boundary == '6->7':
        return _collect_per_brief_vs_draft(project_dir, scope)
    return []


def _render_spine_text(project_dir: str) -> str:
    """Render spine.csv as a readable bullet list for the LLM."""
    spine_path = os.path.join(project_dir, 'reference', 'spine.csv')
    if not os.path.isfile(spine_path):
        return ''
    rows = _read_csv(spine_path)
    if not rows:
        return ''
    lines = []
    for r in rows:
        sid = r.get('id', '?')
        title = r.get('title', '')
        function = r.get('function', '')
        lines.append(f'- {sid}: {title} — {function}')
    return '\n'.join(lines)


def _collect_per_spine_event(project_dir: str,
                              scope: str | None) -> list[tuple[str, str, str]]:
    """For each spine event, gather the architecture rows that reference it."""
    spine_path = os.path.join(project_dir, 'reference', 'spine.csv')
    arch_path = os.path.join(project_dir, 'reference', 'architecture.csv')
    if not (os.path.isfile(spine_path) and os.path.isfile(arch_path)):
        return []
    spine_rows = _read_csv(spine_path)
    arch_rows = _read_csv(arch_path)

    pairs: list[tuple[str, str, str]] = []
    for ev in spine_rows:
        ev_id = ev.get('id', '')
        if scope and ev_id != scope:
            continue
        upstream = (f'Spine event {ev_id}: {ev.get("title", "")}\n'
                    f'Function: {ev.get("function", "")}\n'
                    f'Act: {ev.get("part", "")}')
        descendants = [r for r in arch_rows
                       if r.get('spine_event', '').strip() == ev_id]
        if not descendants:
            downstream = '(no architecture anchors yet reference this spine event)'
        else:
            lines = []
            for d in descendants:
                lines.append(
                    f'- {d.get("id", "?")}: {d.get("title", "")} '
                    f'({d.get("action_sequel", "")}). '
                    f'Arc: {d.get("emotional_arc", "")}. '
                    f'Value: {d.get("value_at_stake", "")} '
                    f'{d.get("value_shift", "")}. '
                    f'Turn: {d.get("turning_point", "")}.'
                )
            downstream = '\n'.join(lines)
        pairs.append((ev_id, upstream, downstream))
    return pairs


def _collect_per_architecture_anchor(project_dir: str,
                                      scope: str | None) -> list[tuple[str, str, str]]:
    """Per architecture anchor, gather the map scenes that reference it."""
    arch_path = os.path.join(project_dir, 'reference', 'architecture.csv')
    scenes_path = os.path.join(project_dir, 'reference', 'scenes.csv')
    if not (os.path.isfile(arch_path) and os.path.isfile(scenes_path)):
        return []
    arch_rows = _read_csv(arch_path)
    scene_rows = _read_csv(scenes_path)

    pairs: list[tuple[str, str, str]] = []
    for anchor in arch_rows:
        anchor_id = anchor.get('id', '')
        if scope and anchor_id != scope:
            continue
        upstream = (
            f'Architecture anchor {anchor_id}: {anchor.get("title", "")}\n'
            f'POV: {anchor.get("pov", "")}\n'
            f'Action/sequel: {anchor.get("action_sequel", "")}\n'
            f'Emotional arc: {anchor.get("emotional_arc", "")}\n'
            f'Value at stake: {anchor.get("value_at_stake", "")} '
            f'{anchor.get("value_shift", "")}\n'
            f'Turning point: {anchor.get("turning_point", "")}'
        )
        descendants = [r for r in scene_rows
                       if r.get('architecture_scene', '').strip() == anchor_id]
        if not descendants:
            downstream = '(no map scenes yet reference this anchor)'
        else:
            lines = []
            for d in descendants:
                lines.append(
                    f'- {d.get("id", "?")}: {d.get("title", "")} '
                    f'(loc={d.get("location", "")}, '
                    f'day={d.get("timeline_day", "")}, '
                    f'type={d.get("type", "")})'
                )
            downstream = '\n'.join(lines)
        pairs.append((anchor_id, upstream, downstream))
    return pairs


def _collect_per_scene_intent_vs_brief(
    project_dir: str, scope: str | None
) -> list[tuple[str, str, str]]:
    """For each scene with a brief, compare scene-intent (upstream) vs brief
    (downstream)."""
    intent_path = os.path.join(project_dir, 'reference', 'scene-intent.csv')
    briefs_path = os.path.join(project_dir, 'reference', 'scene-briefs.csv')
    if not (os.path.isfile(intent_path) and os.path.isfile(briefs_path)):
        return []
    intents = {r.get('id', ''): r for r in _read_csv(intent_path)}
    briefs = _read_csv(briefs_path)

    pairs: list[tuple[str, str, str]] = []
    for brief in briefs:
        sid = brief.get('id', '')
        if scope and sid != scope:
            continue
        intent = intents.get(sid, {})
        if not intent:
            continue
        upstream = (
            f'Intent for {sid}:\n'
            f'Function: {intent.get("function", "")}\n'
            f'Action/sequel: {intent.get("action_sequel", "")}\n'
            f'Emotional arc: {intent.get("emotional_arc", "")}\n'
            f'Value at stake: {intent.get("value_at_stake", "")} '
            f'{intent.get("value_shift", "")}\n'
            f'Turning point: {intent.get("turning_point", "")}\n'
            f'On stage: {intent.get("on_stage", "")}'
        )
        downstream = (
            f'Brief for {sid}:\n'
            f'Goal: {brief.get("goal", "")}\n'
            f'Conflict: {brief.get("conflict", "")}\n'
            f'Outcome: {brief.get("outcome", "")}\n'
            f'Crisis: {brief.get("crisis", "")}\n'
            f'Decision: {brief.get("decision", "")}\n'
            f'Key actions: {brief.get("key_actions", "")}\n'
            f'Key dialogue: {brief.get("key_dialogue", "")}\n'
            f'Emotions: {brief.get("emotions", "")}'
        )
        pairs.append((sid, upstream, downstream))
    return pairs


def _collect_per_brief_vs_draft(
    project_dir: str, scope: str | None
) -> list[tuple[str, str, str]]:
    """For each scene that has both a brief and a draft on disk, compare."""
    briefs_path = os.path.join(project_dir, 'reference', 'scene-briefs.csv')
    if not os.path.isfile(briefs_path):
        return []
    briefs = _read_csv(briefs_path)

    pairs: list[tuple[str, str, str]] = []
    for brief in briefs:
        sid = brief.get('id', '')
        if scope and sid != scope:
            continue
        draft_path = os.path.join(project_dir, 'scenes', f'{sid}.md')
        if not os.path.isfile(draft_path):
            continue
        upstream = (
            f'Brief for {sid}:\n'
            f'Goal: {brief.get("goal", "")}\n'
            f'Conflict: {brief.get("conflict", "")}\n'
            f'Outcome: {brief.get("outcome", "")}\n'
            f'Key actions: {brief.get("key_actions", "")}\n'
            f'Key dialogue: {brief.get("key_dialogue", "")}\n'
            f'Emotions: {brief.get("emotions", "")}\n'
            f'Subtext: {brief.get("subtext", "")}'
        )
        with open(draft_path, encoding='utf-8') as f:
            downstream = f.read()
        pairs.append((sid, upstream, downstream))
    return pairs


# ============================================================================
# LLM invocation + parsing
# ============================================================================

_BOUNDARY_PROMPT = """\
You are evaluating whether two related artifacts in a story project are
aligned, drifting, or producing creative discovery.

Boundary: {boundary} ({boundary_desc})

# Upstream content
{upstream}

# Downstream content
{downstream}

# Task
Compare the two and produce a structured JSON response with these fields:

  - upstream_summary: one-sentence summary of what the upstream says.
  - downstream_summary: one-sentence summary of what the downstream
    actually does.
  - alignment: 2-3 sentence narrative on how the two compare. Where do
    they agree? Where do they diverge? Is divergence intentional
    (discovery — the lower level found something the upper didn't
    know yet) or accidental (drift)? You cannot always tell; be honest.
  - proposed_verdict: one of:
      * "correct=upstream"      — the upstream version is right; the downstream drifted.
      * "correct=downstream"    — the downstream is a real discovery; upstream should update.
      * "both are right"        — divergence is intentional / mutually compatible.
      * "needs work"            — neither side is right yet.
  - rationale: one-sentence justification for the verdict.

Return ONLY the JSON object. No prose before or after.
"""


_BOUNDARY_DESCRIPTIONS = {
    '0->1': 'logline → synopsis',
    '1->2': 'synopsis → act-shape',
    '2->3': 'act-shape → spine',
    '3->4': 'spine event → architecture anchors',
    '4->5': 'architecture anchor → map scenes',
    '5->6': 'scene intent → scene brief',
    '6->7': 'scene brief → drafted scene',
}


def _invoke_llm_diff(project_dir: str, boundary: str, scope: str,
                     upstream: str, downstream: str, model: str) -> dict | None:
    """One API call: compare upstream + downstream, return parsed result.

    Returns None on parse failure / empty response (logs an ERROR — the
    caller treats it as a per-scope skip rather than aborting the whole
    boundary).
    """
    prompt = _BOUNDARY_PROMPT.format(
        boundary=boundary,
        boundary_desc=_BOUNDARY_DESCRIPTIONS.get(boundary, boundary),
        upstream=upstream,
        downstream=downstream,
    )

    log_dir = os.path.join(project_dir, 'working', 'logs', 'boundary-scoring')
    os.makedirs(log_dir, exist_ok=True)
    safe_scope = scope.replace('/', '-').replace(' ', '-')
    safe_boundary = boundary.replace('>', '_to_')
    log_file = os.path.join(log_dir, f'{safe_boundary}-{safe_scope}.json')

    try:
        invoke_to_file(prompt, model, log_file, max_tokens=2048)
    except Exception as e:
        log(f'  [{boundary} / {scope}] ERROR — API call failed: {e}')
        return None

    text = extract_text_from_file(log_file)
    if not text:
        log(f'  [{boundary} / {scope}] ERROR — empty API response')
        return None

    parsed = _parse_diff_response(text)
    if parsed is None:
        log(f'  [{boundary} / {scope}] ERROR — could not parse JSON response')
        return None

    # Cost tracking
    try:
        with open(log_file, encoding='utf-8') as f:
            resp = json.load(f)
        usage = extract_usage(resp)
        cost = calculate_cost_from_usage(usage, model)
        log_operation(
            project_dir, 'score-boundary', model,
            usage['input_tokens'], usage['output_tokens'], cost,
            target=f'{boundary}/{scope}',
            cache_read=usage.get('cache_read', 0),
            cache_create=usage.get('cache_create', 0),
        )
    except Exception as e:
        log(f'  WARNING: cost ledger update failed: {e}')

    return {
        'boundary': boundary,
        'scope': scope,
        'upstream_summary': parsed.get('upstream_summary', '').strip(),
        'downstream_summary': parsed.get('downstream_summary', '').strip(),
        'alignment': parsed.get('alignment', '').strip(),
        'proposed_verdict': parsed.get('proposed_verdict', '').strip(),
        'rationale': parsed.get('rationale', '').strip(),
    }


def _parse_diff_response(text: str) -> dict | None:
    """Extract the JSON body from the model's response.

    Tolerates fenced code blocks (```json ... ```) and stray prose before
    or after the JSON object.
    """
    # Direct parse
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        pass
    # Fenced block
    m = re.search(r'```(?:json)?\s*\n(.*?)\n```', text, re.DOTALL)
    if m:
        try:
            return json.loads(m.group(1).strip())
        except json.JSONDecodeError:
            pass
    # Greedy first-object match
    m = re.search(r'\{.*\}', text, re.DOTALL)
    if m:
        try:
            return json.loads(m.group(0))
        except json.JSONDecodeError:
            pass
    return None


# ============================================================================
# Persistence — coaching-level-aware verdict recording
# ============================================================================

def _persist_per_coaching(project_dir: str, boundary: str, scope: str,
                          diff: dict, coaching_level: str) -> bool:
    """Persist the verdict to scoring-verdicts.csv per coaching level.

    Returns True if a verdict was written, False otherwise (in which case
    the diff still surfaces — the author is expected to author the verdict
    via append_verdict directly).

    Per the synthesis:
      - full:   LLM-proposed verdict is persisted immediately as actor='llm'.
                The author can override later via append_verdict('author',
                ...) or accept via working/scoring-overrides.csv.
      - coach:  LLM-proposed verdict is NOT persisted. The diff is
                surfaced; the author confirms or overrides explicitly.
      - strict: same as coach. The LLM never authors verdicts.
    """
    verdict = diff.get('proposed_verdict', '')
    if verdict not in VALID_BOUNDARY_VERDICTS:
        return False
    if coaching_level != 'full':
        return False

    now = datetime.now(timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ')
    append_verdict(
        scope=scope, boundary=boundary, verdict=verdict,
        rationale=diff.get('rationale', ''),
        actor='llm', coaching_level=coaching_level,
        recorded_at=now, project_dir=project_dir,
    )
    return True
