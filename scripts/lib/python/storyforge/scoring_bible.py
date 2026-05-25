"""LLM check of drafted scenes against character/world/voice bibles."""

import hashlib
import json
import os
import re
from datetime import datetime, timezone

from storyforge.api import (
    extract_text_from_file, extract_usage,
    calculate_cost_from_usage, invoke_to_file,
)
from storyforge.common import detect_project_root, log, select_model
from storyforge.costs import log_operation
from storyforge.scoring_state import is_override_accepted


# ============================================================================
# Bible loading
# ============================================================================

# The three bibles checked by v2. Each maps a file path → finding label.
BIBLES = (
    ('reference/character-bible.md', 'character-bible.md'),
    ('reference/world-bible.md', 'world-bible.md'),
    ('reference/voice-guide.md', 'voice-guide.md'),
)


def _load_bibles(project_dir: str) -> dict[str, str]:
    """Read each bible from disk. Returns {label: content} for bibles that
    exist; missing bibles are silently skipped so a partial-bibles project
    still gets a useful pass."""
    out: dict[str, str] = {}
    for rel, label in BIBLES:
        path = os.path.join(project_dir, rel)
        if not os.path.isfile(path):
            continue
        with open(path, encoding='utf-8') as f:
            content = f.read()
        if content.strip():
            out[label] = content
    return out


def _drafted_scenes(project_dir: str) -> list[tuple[str, str]]:
    """Return [(scene_id, prose), ...] for every scene with a draft on disk."""
    scenes_dir = os.path.join(project_dir, 'scenes')
    if not os.path.isdir(scenes_dir):
        return []
    results: list[tuple[str, str]] = []
    for filename in sorted(os.listdir(scenes_dir)):
        if not filename.endswith('.md'):
            continue
        sid = filename[:-3]  # strip .md
        path = os.path.join(scenes_dir, filename)
        with open(path, encoding='utf-8') as f:
            prose = f.read()
        if prose.strip():
            results.append((sid, prose))
    return results


# ============================================================================
# Public API
# ============================================================================

def score_bible_consistency(project_dir: str,
                            scope: str | None = None,
                            model: str | None = None,
                            dry_run: bool = False) -> list[dict]:
    """Run bible-consistency on one or all drafted scenes.

    Args:
        project_dir: Project root.
        scope: When set, restrict to a single scene id. When None, runs
            every drafted scene in scenes/.
        model: Optional model override. Default: select_model('evaluation')
            (Sonnet).
        dry_run: Build prompts but skip the LLM. Returns stub finding dicts
            so callers can inspect what would be sent.

    Returns:
        List of finding dicts (shape documented in the module docstring).
        Findings the author has already accepted via working/scoring-
        overrides.csv are tagged with `accepted=True` but still surface
        (the author can revisit at any time).
    """
    bibles = _load_bibles(project_dir)
    if not bibles:
        log('No bibles found; nothing to check (expected at least one of: '
            'reference/character-bible.md, reference/world-bible.md, '
            'reference/voice-guide.md)')
        return []

    scenes = _drafted_scenes(project_dir)
    if scope:
        scenes = [(sid, prose) for sid, prose in scenes if sid == scope]
    if not scenes:
        log(f'No drafted scenes to check' + (f' for scope {scope!r}' if scope else ''))
        return []

    model = model or select_model('evaluation')

    all_findings: list[dict] = []
    for scene_id, prose in scenes:
        if dry_run:
            all_findings.append({
                'scope': scene_id,
                'bible': '(dry run)',
                'claim': '(dry run — no LLM call)',
                'scene_says': prose[:120],
                'fix_location': 'either',
                'severity': 'medium',
                'finding_id': _finding_id(scene_id, '(dry run)', '(dry run)'),
            })
            continue

        scene_findings = _invoke_bible_check(
            project_dir, scene_id, prose, bibles, model,
        )
        for f in scene_findings:
            f['accepted'] = is_override_accepted(
                scope=scene_id,
                axis='bible-consistency',
                finding_id=f['finding_id'],
                project_dir=project_dir,
            )
        all_findings.extend(scene_findings)

    return all_findings


# ============================================================================
# LLM invocation with prompt caching
# ============================================================================

_BIBLE_SYSTEM_INSTRUCTIONS = """\
You are checking a drafted scene against the project's reference bibles
for inconsistencies. The bibles describe characters, the world, and the
authorial voice. The scene is what the author actually wrote.

When you find a disagreement, surface it neutrally — without privileging
the bible as authority. The author may have evolved the character through
writing (in which case the bible should update), or the scene may have
drifted (in which case the scene should update), or both could be right
(the character has multiple facets, the world rule has a known
exception, etc.).

Return JSON with this shape:

  {
    "findings": [
      {
        "bible": "character-bible.md",
        "claim": "the bible's specific statement, quoted concisely",
        "scene_says": "what the scene shows that diverges, quoted concisely",
        "fix_location": "bible" | "scene" | "either",
        "severity": "high" | "medium" | "low"
      },
      ...
    ]
  }

Severity rubric:
  - high: continuity-breaking (a character has a scar in the bible but no
          scar in the scene; world rule violated)
  - medium: tone or voice mismatch the bible documents specifically
  - low: minor flavor inconsistency the bible doesn't strongly prescribe

If everything aligns, return {"findings": []}. Return ONLY the JSON.
"""


def _invoke_bible_check(project_dir: str, scene_id: str, prose: str,
                       bibles: dict[str, str], model: str) -> list[dict]:
    """One LLM call: scene prose vs. cached bibles → list of findings.

    The bibles are sent as cached system content blocks. With prompt
    caching, the first scene pays for the bibles; every subsequent scene
    only pays for its own scene content. This is the design's
    "mandatory caching" requirement.
    """
    # Build system blocks. Each block has cache_control so the API can
    # cache them and reuse the cached prefix on subsequent calls.
    system_blocks: list[dict] = [
        {'type': 'text', 'text': _BIBLE_SYSTEM_INSTRUCTIONS,
         'cache_control': {'type': 'ephemeral'}},
    ]
    for label, content in bibles.items():
        system_blocks.append({
            'type': 'text',
            'text': f'# Bible: {label}\n\n{content}',
            'cache_control': {'type': 'ephemeral'},
        })

    user_prompt = (
        f'# Scene: {scene_id}\n\n{prose}\n\n'
        'Check this scene against the bibles above. Return JSON.'
    )

    log_dir = os.path.join(project_dir, 'working', 'logs', 'bible-consistency')
    os.makedirs(log_dir, exist_ok=True)
    log_file = os.path.join(log_dir, f'{scene_id}.json')

    try:
        invoke_to_file(user_prompt, model, log_file,
                       max_tokens=2048, system=system_blocks)
    except Exception as e:
        log(f'  [bible / {scene_id}] ERROR — API call failed: {e}')
        return []

    text = extract_text_from_file(log_file)
    if not text:
        log(f'  [bible / {scene_id}] ERROR — empty API response')
        return []

    parsed = _parse_bible_response(text)
    if parsed is None:
        log(f'  [bible / {scene_id}] ERROR — could not parse JSON')
        return []

    # Cost tracking — captures cache hits so subsequent scenes show the
    # expected savings.
    try:
        with open(log_file, encoding='utf-8') as f:
            resp = json.load(f)
        usage = extract_usage(resp)
        cost = calculate_cost_from_usage(usage, model)
        log_operation(
            project_dir, 'score-bible', model,
            usage['input_tokens'], usage['output_tokens'], cost,
            target=scene_id,
            cache_read=usage.get('cache_read', 0),
            cache_create=usage.get('cache_create', 0),
        )
    except Exception as e:
        log(f'  WARNING: cost ledger update failed: {e}')

    findings: list[dict] = []
    dropped_count = 0
    for raw in parsed:
        if not isinstance(raw, dict):
            dropped_count += 1
            log(f'  [bible / {scene_id}] WARNING: dropped non-dict entry from LLM response')
            continue
        bible = str(raw.get('bible', '')).strip()
        claim = str(raw.get('claim', '')).strip()
        scene_says = str(raw.get('scene_says', '')).strip()
        if not (bible and claim and scene_says):
            dropped_count += 1
            missing = [k for k, v in
                       (('bible', bible), ('claim', claim), ('scene_says', scene_says))
                       if not v]
            log(f'  [bible / {scene_id}] WARNING: dropped finding missing required '
                f'field(s) {missing}')
            continue
        severity_raw = str(raw.get('severity', 'medium')).strip().lower()
        if severity_raw not in ('high', 'medium', 'low'):
            log(f'  [bible / {scene_id}] WARNING: coerced invalid severity '
                f'{severity_raw!r} to "medium"')
            severity = 'medium'
        else:
            severity = severity_raw
        fix_location_raw = str(raw.get('fix_location', 'either')).strip().lower()
        if fix_location_raw not in ('bible', 'scene', 'either'):
            log(f'  [bible / {scene_id}] WARNING: coerced invalid fix_location '
                f'{fix_location_raw!r} to "either"')
            fix_location = 'either'
        else:
            fix_location = fix_location_raw
        findings.append({
            'scope': scene_id,
            'bible': bible,
            'claim': claim,
            'scene_says': scene_says,
            'fix_location': fix_location,
            'severity': severity,
            'finding_id': _finding_id(scene_id, bible, claim),
        })
    return findings


def _parse_bible_response(text: str) -> list[dict] | None:
    """Extract the `findings` list from the model's response."""
    def _take(obj):
        if isinstance(obj, dict):
            inner = obj.get('findings')
            if isinstance(inner, list):
                return inner
        return None

    try:
        return _take(json.loads(text))
    except json.JSONDecodeError:
        pass
    m = re.search(r'```(?:json)?\s*\n(.*?)\n```', text, re.DOTALL)
    if m:
        try:
            return _take(json.loads(m.group(1).strip()))
        except json.JSONDecodeError:
            pass
    m = re.search(r'\{.*\}', text, re.DOTALL)
    if m:
        try:
            return _take(json.loads(m.group(0)))
        except json.JSONDecodeError:
            pass
    return None


def _finding_id(scope: str, bible: str, claim: str) -> str:
    """Build a stable id from (scope, bible, claim) so overrides persist
    across runs. Uses sha1 → 12 hex chars (collision-resistant enough
    at this scale; not security-sensitive)."""
    raw = f'{scope}|{bible}|{claim.strip()[:200]}'
    return hashlib.sha1(raw.encode('utf-8')).hexdigest()[:12]
