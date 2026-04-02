# Reverse Elaboration — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Extract structural data from existing prose into the three-file scene CSV model. Takes a manuscript (or existing scenes) and produces populated scenes.csv, scene-intent.csv, and scene-briefs.csv — accurate enough for the author to review and correct rather than build from scratch. Also supports novella-to-novel expansion analysis.

**Architecture:** New script `scripts/storyforge-extract` orchestrates four extraction phases (characterize → skeleton → intent → briefs). New Python module `scripts/lib/python/storyforge/extract.py` provides prompt builders and response parsers for each phase. Reuses existing enrichment infrastructure where possible. New skill `skills/extract/SKILL.md` for interactive use.

**Tech Stack:** Python 3, bash, Anthropic Messages API (batch + direct), pipe-delimited CSV

**Spec:** `docs/superpowers/specs/2026-04-01-elaboration-pipeline-design.md` (Migration section)

---

## File Structure

### New files
- `scripts/lib/python/storyforge/extract.py` — prompt builders, response parsers, and extraction logic for all phases
- `scripts/storyforge-extract` — bash CLI orchestrating the multi-phase extraction
- `skills/extract/SKILL.md` — interactive extraction skill
- `tests/test-extract.sh` — tests for extraction helpers

### Modified files
- `scripts/lib/python/storyforge/elaborate.py` — add expansion analysis function

---

## Task 1: Extraction prompt builders and parsers — `extract.py`

Create the Python module with prompt builders for each phase and parsers for extracting structured data from Claude's responses.

**Files:**
- Create: `scripts/lib/python/storyforge/extract.py`

- [ ] **Step 1: Create `extract.py` with Phase 0 (characterize) prompt and parser**

```python
"""Reverse elaboration — extract structural data from existing prose.

Four extraction phases:
  Phase 0: Characterize (full manuscript → manuscript profile)
  Phase 1: Skeleton (per scene → scenes.csv fields)
  Phase 2: Intent (per scene, parallel → scene-intent.csv fields)
  Phase 3: Briefs (per scene, knowledge chain sequential → scene-briefs.csv fields)
"""

import json
import os
import re
from typing import Any

from .prompts import read_yaml_field


def _read_file(path: str) -> str:
    if not os.path.isfile(path):
        return ''
    with open(path, encoding='utf-8') as f:
        return f.read()


def _read_all_scenes(project_dir: str) -> dict[str, str]:
    """Read all scene files, returning {scene_id: prose_text}."""
    scenes_dir = os.path.join(project_dir, 'scenes')
    if not os.path.isdir(scenes_dir):
        return {}
    result = {}
    for fname in sorted(os.listdir(scenes_dir)):
        if fname.endswith('.md'):
            scene_id = fname[:-3]
            with open(os.path.join(scenes_dir, fname), encoding='utf-8') as f:
                result[scene_id] = f.read()
    return result


def _read_manuscript(project_dir: str) -> str:
    """Read the full manuscript by concatenating all scene files in seq order,
    or reading assembled chapters if available."""
    # Try assembled chapters first
    chapters_dir = os.path.join(project_dir, 'manuscript', 'output', 'web', 'chapters')
    if os.path.isdir(chapters_dir):
        parts = []
        for fname in sorted(os.listdir(chapters_dir)):
            if fname.endswith('.html'):
                with open(os.path.join(chapters_dir, fname), encoding='utf-8') as f:
                    # Strip HTML tags for analysis
                    text = re.sub(r'<[^>]+>', ' ', f.read())
                    text = re.sub(r'\s+', ' ', text).strip()
                    parts.append(text)
        if parts:
            return '\n\n---\n\n'.join(parts)

    # Fall back to concatenating scene files in seq order
    scenes = _read_all_scenes(project_dir)
    if not scenes:
        return ''

    # Try to order by seq from scenes.csv or scene-metadata.csv
    ref_dir = os.path.join(project_dir, 'reference')
    seq_order = {}
    for csv_name in ['scenes.csv', 'scene-metadata.csv']:
        csv_path = os.path.join(ref_dir, csv_name)
        if os.path.isfile(csv_path):
            with open(csv_path, encoding='utf-8') as f:
                lines = [l.strip() for l in f if l.strip()]
            if len(lines) > 1:
                header = lines[0].split('|')
                id_idx = header.index('id') if 'id' in header else 0
                seq_idx = header.index('seq') if 'seq' in header else 1
                for line in lines[1:]:
                    fields = line.split('|')
                    if len(fields) > max(id_idx, seq_idx):
                        try:
                            seq_order[fields[id_idx]] = int(fields[seq_idx])
                        except (ValueError, IndexError):
                            pass
            break

    if seq_order:
        ordered = sorted(scenes.keys(), key=lambda s: seq_order.get(s, 999))
    else:
        ordered = sorted(scenes.keys())

    parts = []
    for sid in ordered:
        parts.append(f"=== SCENE: {sid} ===\n\n{scenes[sid]}")
    return '\n\n'.join(parts)


# ============================================================================
# Phase 0: Characterize
# ============================================================================

def build_characterize_prompt(project_dir: str) -> str:
    """Build prompt for Phase 0: manuscript characterization."""
    yaml_path = os.path.join(project_dir, 'storyforge.yaml')
    title = read_yaml_field(yaml_path, 'project.title') or 'Untitled'
    genre = read_yaml_field(yaml_path, 'project.genre') or ''

    manuscript = _read_manuscript(project_dir)
    if not manuscript:
        return ''

    # Truncate if extremely long (>200K chars) — Phase 0 needs the shape, not every word
    if len(manuscript) > 200000:
        manuscript = manuscript[:200000] + '\n\n[...truncated for characterization...]'

    return f"""You are analyzing a manuscript to characterize its structure before detailed extraction.

## Project
**Title:** {title}
**Genre:** {genre}

## Manuscript

{manuscript}

## Instructions

Analyze this manuscript and produce a structural profile. Output each field on its own labeled line.

NARRATIVE_MODE: [first-person / third-limited / third-omniscient / multiple-POV / other]
POV_CHARACTERS: [semicolon-separated list of POV characters, in order of appearance]
TIMELINE: [linear / non-linear / fragmented / frame-narrative]
TIMELINE_SPAN: [approximate time span of the story, e.g., "3 days", "6 months", "20 years"]
SCENE_BREAK_STYLE: [explicit-markers / chapter-based / unmarked / mixed]
ESTIMATED_SCENES: [approximate number of distinct scenes]
ACT_STRUCTURE: [number of acts/parts and their approximate boundaries, e.g., "3 acts: scenes 1-12, 13-28, 29-42"]
MAJOR_THREADS: [semicolon-separated list of major story threads/subplots]
CENTRAL_CONFLICT: [one sentence describing the core conflict]
PROTAGONIST_ARC: [one sentence: wound/lie → confrontation → resolution/refusal]
TONE: [1-3 words describing the overall tone]
CAST_SIZE: [approximate number of named characters]
KEY_LOCATIONS: [semicolon-separated list of major locations]
COMPRESSION_POINTS: [semicolon-separated list of moments that feel compressed or rushed — these are expansion opportunities if the work is being developed into a longer form]
STRUCTURAL_CONCERNS: [semicolon-separated list of any structural issues visible at this level — dropped threads, pacing problems, arc gaps]

Be precise. Base every field on what's actually in the text, not what you'd expect from the genre."""


def parse_characterize_response(response: str) -> dict[str, str]:
    """Parse the Phase 0 characterization response into a dict."""
    result = {}
    for line in response.split('\n'):
        line = line.strip()
        if ':' not in line:
            continue
        # Match LABEL: value pattern
        match = re.match(r'^([A-Z_]+):\s*(.*)', line)
        if match:
            key = match.group(1).lower()
            value = match.group(2).strip()
            if value and value not in ('[]', '()', 'N/A', 'none'):
                result[key] = value
    return result


# ============================================================================
# Phase 1: Skeleton (scenes.csv fields)
# ============================================================================

def build_skeleton_prompt(scene_id: str, scene_text: str,
                          profile: dict[str, str],
                          existing_metadata: dict[str, str] | None = None) -> str:
    """Build prompt for Phase 1: extract scenes.csv fields from a single scene."""
    context = f"""POV characters in this manuscript: {profile.get('pov_characters', 'unknown')}
Timeline: {profile.get('timeline', 'unknown')}
Key locations: {profile.get('key_locations', 'unknown')}"""

    existing = ''
    if existing_metadata:
        known = {k: v for k, v in existing_metadata.items() if v and k != 'id'}
        if known:
            existing = "Already known about this scene:\n" + '\n'.join(
                f"  {k}: {v}" for k, v in known.items())

    return f"""Extract structural metadata from this scene.

## Manuscript Context
{context}

## Scene: {scene_id}

{scene_text}

{existing}

## Instructions

Output each field on its own labeled line. If a value cannot be determined, output UNKNOWN.

TITLE: [a short evocative title for this scene, 3-7 words]
POV: [the POV character's full name]
LOCATION: [the primary physical location — use a consistent canonical name]
TIMELINE_DAY: [integer day number within the story chronology, starting from 1]
TIME_OF_DAY: [morning / afternoon / evening / night / dawn / dusk]
DURATION: [approximate in-story duration, e.g., "2 hours", "30 minutes", "an afternoon"]
TARGET_WORDS: [current word count is a reasonable target — output the approximate word count]
PART: [which act/part number this scene belongs to, based on its position in the story]"""


def parse_skeleton_response(response: str, scene_id: str) -> dict[str, str]:
    """Parse Phase 1 response into scenes.csv field values."""
    result = {'id': scene_id}
    label_map = {
        'TITLE': 'title',
        'POV': 'pov',
        'LOCATION': 'location',
        'TIMELINE_DAY': 'timeline_day',
        'TIME_OF_DAY': 'time_of_day',
        'DURATION': 'duration',
        'TARGET_WORDS': 'target_words',
        'PART': 'part',
    }
    for line in response.split('\n'):
        match = re.match(r'^([A-Z_]+):\s*(.*)', line.strip())
        if match:
            label = match.group(1)
            value = match.group(2).strip()
            if label in label_map and value and value.upper() != 'UNKNOWN':
                result[label_map[label]] = value
    return result


# ============================================================================
# Phase 2: Intent (scene-intent.csv fields)
# ============================================================================

def build_intent_prompt(scene_id: str, scene_text: str,
                        profile: dict[str, str],
                        skeleton: dict[str, str]) -> str:
    """Build prompt for Phase 2: extract scene-intent.csv fields."""
    context = f"""Title: {skeleton.get('title', scene_id)}
POV: {skeleton.get('pov', 'unknown')}
Location: {skeleton.get('location', 'unknown')}
Part: {skeleton.get('part', 'unknown')}
Major threads in this manuscript: {profile.get('major_threads', 'unknown')}
Central conflict: {profile.get('central_conflict', 'unknown')}"""

    return f"""Extract the narrative intent and dynamics from this scene.

## Context
{context}

## Scene: {scene_id}

{scene_text}

## Instructions

Output each field on its own labeled line. Use semicolons to separate list items.

FUNCTION: [one sentence: why this scene exists — what it accomplishes in the story. Must be specific and testable, not vague like "develops character"]
SCENE_TYPE: [action or sequel — action scenes have goal/conflict/outcome; sequel scenes have reaction/dilemma/decision]
EMOTIONAL_ARC: [starting emotion giving way to ending emotion, e.g., "controlled competence to buried unease"]
VALUE_AT_STAKE: [the abstract value being tested: safety, love, justice, truth, freedom, honor, etc.]
VALUE_SHIFT: [polarity change using +/- notation: +/- means positive to negative, -/+ means negative to positive, +/++ means good to better, -/-- means bad to worse]
TURNING_POINT: [action or revelation — action means a character does something that changes the situation; revelation means new information changes the situation]
THREADS: [semicolon-separated story threads this scene advances]
CHARACTERS: [semicolon-separated list of ALL characters present or referenced by name]
ON_STAGE: [semicolon-separated list of characters physically present in the scene — subset of CHARACTERS]
MICE_THREADS: [semicolon-separated MICE thread operations — +milieu:location-name to open, -inquiry:question to close, etc. Use + for opening, - for closing. Types: milieu, inquiry, character, event]
CONFIDENCE: [high / medium / low — your overall confidence in these extractions]"""


def parse_intent_response(response: str, scene_id: str) -> dict[str, str]:
    """Parse Phase 2 response into scene-intent.csv field values."""
    result = {'id': scene_id}
    label_map = {
        'FUNCTION': 'function',
        'SCENE_TYPE': 'scene_type',
        'EMOTIONAL_ARC': 'emotional_arc',
        'VALUE_AT_STAKE': 'value_at_stake',
        'VALUE_SHIFT': 'value_shift',
        'TURNING_POINT': 'turning_point',
        'THREADS': 'threads',
        'CHARACTERS': 'characters',
        'ON_STAGE': 'on_stage',
        'MICE_THREADS': 'mice_threads',
        'CONFIDENCE': '_confidence',
    }
    for line in response.split('\n'):
        match = re.match(r'^([A-Z_]+):\s*(.*)', line.strip())
        if match:
            label = match.group(1)
            value = match.group(2).strip()
            if label in label_map and value and value.upper() != 'UNKNOWN':
                result[label_map[label]] = value
    return result


# ============================================================================
# Phase 3a: Briefs — parallel fields
# ============================================================================

def build_brief_parallel_prompt(scene_id: str, scene_text: str,
                                 profile: dict[str, str],
                                 skeleton: dict[str, str],
                                 intent: dict[str, str]) -> str:
    """Build prompt for Phase 3a: extract brief fields that don't require
    sequential knowledge tracking."""
    context = f"""Title: {skeleton.get('title', scene_id)}
POV: {skeleton.get('pov', 'unknown')}
Function: {intent.get('function', 'unknown')}
Scene type: {intent.get('scene_type', 'unknown')}
Value at stake: {intent.get('value_at_stake', 'unknown')}
Value shift: {intent.get('value_shift', 'unknown')}
Emotional arc: {intent.get('emotional_arc', 'unknown')}"""

    return f"""Extract the drafting contract details from this scene — the specific actions, choices, and dialogue that make it work.

## Context
{context}

## Scene: {scene_id}

{scene_text}

## Instructions

Output each field on its own labeled line. Use semicolons to separate list items.

GOAL: [the POV character's concrete objective entering this scene — what are they trying to do?]
CONFLICT: [what specifically opposes the goal?]
OUTCOME: [how does the scene end for the POV character? Use: yes / no / yes-but / no-and]
CRISIS: [the key dilemma — a best bad choice or irreconcilable goods that the character faces]
DECISION: [what the character actively chooses in response to the crisis]
KEY_ACTIONS: [semicolon-separated concrete things that happen in this scene]
KEY_DIALOGUE: [semicolon-separated specific lines or exchanges that are essential to the scene — quote directly from the text]
EMOTIONS: [semicolon-separated emotional beats in sequence as they occur through the scene]
MOTIFS: [semicolon-separated recurring images, symbols, or sensory details that carry thematic weight]"""


def parse_brief_parallel_response(response: str, scene_id: str) -> dict[str, str]:
    """Parse Phase 3a response."""
    result = {'id': scene_id}
    label_map = {
        'GOAL': 'goal',
        'CONFLICT': 'conflict',
        'OUTCOME': 'outcome',
        'CRISIS': 'crisis',
        'DECISION': 'decision',
        'KEY_ACTIONS': 'key_actions',
        'KEY_DIALOGUE': 'key_dialogue',
        'EMOTIONS': 'emotions',
        'MOTIFS': 'motifs',
    }
    for line in response.split('\n'):
        match = re.match(r'^([A-Z_]+):\s*(.*)', line.strip())
        if match:
            label = match.group(1)
            value = match.group(2).strip()
            if label in label_map and value and value.upper() != 'UNKNOWN':
                result[label_map[label]] = value
    return result


# ============================================================================
# Phase 3b: Knowledge chain (sequential)
# ============================================================================

def build_knowledge_prompt(scene_id: str, scene_text: str,
                           skeleton: dict[str, str],
                           intent: dict[str, str],
                           prior_knowledge: dict[str, str],
                           prior_scene_summaries: list[str]) -> str:
    """Build prompt for Phase 3b: extract knowledge_in, knowledge_out, and
    continuity_deps. Must be called sequentially.

    Args:
        prior_knowledge: Dict mapping character names to their current
            knowledge state (accumulated from prior scenes' knowledge_out).
        prior_scene_summaries: List of "scene_id: one-line summary" for
            all prior scenes, providing narrative context.
    """
    pov = skeleton.get('pov', 'unknown')
    prior_context = '\n'.join(prior_scene_summaries[-10:]) if prior_scene_summaries else '(first scene)'

    pov_knowledge = prior_knowledge.get(pov, 'No prior knowledge established')

    return f"""Track the knowledge state of the POV character through this scene.

## POV Character: {pov}

## What {pov} knows entering this scene (from prior scenes):
{pov_knowledge}

## Recent prior scenes (for context):
{prior_context}

## Scene: {scene_id}
{scene_text}

## Instructions

Output each field on its own labeled line.

KNOWLEDGE_IN: [semicolon-separated facts that {pov} knows at the START of this scene — carry forward from prior knowledge above, including only facts relevant to this scene]
KNOWLEDGE_OUT: [semicolon-separated facts that {pov} knows at the END of this scene — includes knowledge_in plus anything new learned during the scene]
CONTINUITY_DEPS: [semicolon-separated scene IDs that this scene directly depends on — which prior scenes established facts that this scene uses?]
SCENE_SUMMARY: [one sentence summarizing what happens in this scene — this will be used as context for subsequent scenes]

IMPORTANT: Use EXACT wording for knowledge facts. If a prior scene established "the eastern readings don't match", use that exact phrase, not a paraphrase. This enables automated validation."""


def parse_knowledge_response(response: str, scene_id: str) -> dict[str, str]:
    """Parse Phase 3b response."""
    result = {'id': scene_id}
    label_map = {
        'KNOWLEDGE_IN': 'knowledge_in',
        'KNOWLEDGE_OUT': 'knowledge_out',
        'CONTINUITY_DEPS': 'continuity_deps',
        'SCENE_SUMMARY': '_summary',
    }
    for line in response.split('\n'):
        match = re.match(r'^([A-Z_]+):\s*(.*)', line.strip())
        if match:
            label = match.group(1)
            value = match.group(2).strip()
            if label in label_map and value:
                result[label_map[label]] = value
    return result


# ============================================================================
# Expansion analysis (novella-to-novel)
# ============================================================================

def analyze_expansion_opportunities(ref_dir: str) -> list[dict]:
    """Analyze extracted data for expansion opportunities.

    Identifies scenes and structural elements that suggest the work
    could be expanded. Useful for novella-to-novel development.

    Returns a list of opportunity dicts with:
      - type: compressed_scene | knowledge_jump | timeline_gap |
              thin_thread | underused_character | missing_sequel
      - scene_id: affected scene(s)
      - description: what the opportunity is
      - priority: high / medium / low
    """
    from .elaborate import _read_csv_as_map

    scenes_map = _read_csv_as_map(os.path.join(ref_dir, 'scenes.csv'))
    intent_map = _read_csv_as_map(os.path.join(ref_dir, 'scene-intent.csv'))
    briefs_map = _read_csv_as_map(os.path.join(ref_dir, 'scene-briefs.csv'))

    opportunities = []
    sorted_ids = sorted(scenes_map.keys(),
                        key=lambda s: int(scenes_map[s].get('seq', 0)))

    # 1. Compressed scenes: low word count relative to function importance
    for sid in sorted_ids:
        scene = scenes_map[sid]
        wc = int(scene.get('word_count', 0) or 0)
        intent = intent_map.get(sid, {})
        vs = intent.get('value_shift', '')

        # Major value shifts in under 1000 words suggest compression
        if wc > 0 and wc < 1000 and vs and '/' in vs:
            parts = vs.split('/')
            if parts[0].strip() != parts[1].strip():
                opportunities.append({
                    'type': 'compressed_scene',
                    'scene_id': sid,
                    'description': f"Scene has major value shift ({vs}) in only {wc} words — may need expansion",
                    'priority': 'high' if wc < 500 else 'medium',
                })

    # 2. Knowledge jumps: large knowledge_out minus knowledge_in
    for sid in sorted_ids:
        brief = briefs_map.get(sid, {})
        k_in = brief.get('knowledge_in', '').strip()
        k_out = brief.get('knowledge_out', '').strip()
        if k_in and k_out:
            in_facts = {f.strip() for f in k_in.split(';') if f.strip()}
            out_facts = {f.strip() for f in k_out.split(';') if f.strip()}
            new_facts = out_facts - in_facts
            if len(new_facts) >= 3:
                opportunities.append({
                    'type': 'knowledge_jump',
                    'scene_id': sid,
                    'description': f"Character learns {len(new_facts)} new facts in one scene — may need multiple scenes to earn these revelations",
                    'priority': 'high' if len(new_facts) >= 5 else 'medium',
                })

    # 3. Timeline gaps
    prev_day = None
    prev_id = None
    for sid in sorted_ids:
        day_str = scenes_map[sid].get('timeline_day', '').strip()
        if not day_str:
            continue
        try:
            day = int(day_str)
        except ValueError:
            continue
        if prev_day is not None and day - prev_day > 2:
            opportunities.append({
                'type': 'timeline_gap',
                'scene_id': f"{prev_id}→{sid}",
                'description': f"Gap of {day - prev_day} days between scenes — bridging scenes may be needed",
                'priority': 'medium' if day - prev_day <= 7 else 'high',
            })
        prev_day = day
        prev_id = sid

    # 4. Thin threads: appear in only 1-2 scenes
    thread_counts: dict[str, list[str]] = {}
    for sid in sorted_ids:
        intent = intent_map.get(sid, {})
        threads = intent.get('threads', '').strip()
        if threads:
            for t in threads.split(';'):
                t = t.strip()
                if t:
                    thread_counts.setdefault(t, []).append(sid)

    for thread, scene_ids in thread_counts.items():
        if len(scene_ids) <= 2:
            opportunities.append({
                'type': 'thin_thread',
                'scene_id': ';'.join(scene_ids),
                'description': f"Thread '{thread}' appears in only {len(scene_ids)} scene(s) — may be underdeveloped",
                'priority': 'medium',
            })

    # 5. Missing sequels: action scenes without a following sequel
    for i, sid in enumerate(sorted_ids[:-1]):
        intent = intent_map.get(sid, {})
        next_intent = intent_map.get(sorted_ids[i + 1], {})
        if intent.get('scene_type') == 'action' and next_intent.get('scene_type') == 'action':
            opportunities.append({
                'type': 'missing_sequel',
                'scene_id': sid,
                'description': f"Action scene followed by another action scene — reaction/processing beat may be needed between {sid} and {sorted_ids[i+1]}",
                'priority': 'low',
            })

    # Sort by priority
    priority_order = {'high': 0, 'medium': 1, 'low': 2}
    opportunities.sort(key=lambda o: priority_order.get(o['priority'], 3))

    return opportunities
```

Write this to `scripts/lib/python/storyforge/extract.py`.

- [ ] **Step 2: Commit**

```bash
git add scripts/lib/python/storyforge/extract.py
git commit -m "Add extraction prompt builders and parsers for reverse elaboration"
```

---

## Task 2: Tests for extraction helpers

**Files:**
- Create: `tests/test-extract.sh`

- [ ] **Step 1: Write tests for response parsers and expansion analysis**

```bash
#!/bin/bash
# test-extract.sh — Tests for reverse elaboration extraction helpers

PY="import sys; sys.path.insert(0, '${PLUGIN_DIR}/scripts/lib/python'"

# ============================================================================
# parse_characterize_response
# ============================================================================

RESULT=$(python3 -c "
${PY})
from storyforge.extract import parse_characterize_response
response = '''NARRATIVE_MODE: third-limited
POV_CHARACTERS: Dorren Hayle;Tessa Merrin
TIMELINE: linear
TIMELINE_SPAN: 3 weeks
SCENE_BREAK_STYLE: explicit-markers
ESTIMATED_SCENES: 42
MAJOR_THREADS: institutional-failure;chosen-blindness;the-anomaly
CENTRAL_CONFLICT: A cartographer must choose between institutional loyalty and truth
CAST_SIZE: 12'''
result = parse_characterize_response(response)
print(result.get('narrative_mode', ''))
print(result.get('pov_characters', ''))
print(result.get('estimated_scenes', ''))
print(result.get('major_threads', ''))
")

assert_contains "$RESULT" "third-limited" "parse_characterize: extracts narrative mode"
assert_contains "$RESULT" "Dorren Hayle;Tessa Merrin" "parse_characterize: extracts POV characters"
assert_contains "$RESULT" "42" "parse_characterize: extracts scene count"
assert_contains "$RESULT" "institutional-failure" "parse_characterize: extracts threads"

# ============================================================================
# parse_skeleton_response
# ============================================================================

RESULT=$(python3 -c "
${PY})
from storyforge.extract import parse_skeleton_response
response = '''TITLE: The Arranged Dead
POV: Emmett Slade
LOCATION: Alkali Flat
TIMELINE_DAY: 1
TIME_OF_DAY: afternoon
DURATION: 2 hours
TARGET_WORDS: 1300
PART: 1'''
result = parse_skeleton_response(response, 'arranged-dead')
print(result.get('id', ''))
print(result.get('title', ''))
print(result.get('pov', ''))
print(result.get('timeline_day', ''))
print(result.get('part', ''))
")

assert_equals "arranged-dead" "$(echo "$RESULT" | head -1)" "parse_skeleton: preserves scene id"
assert_contains "$RESULT" "The Arranged Dead" "parse_skeleton: extracts title"
assert_contains "$RESULT" "Emmett Slade" "parse_skeleton: extracts POV"

# ============================================================================
# parse_intent_response
# ============================================================================

RESULT=$(python3 -c "
${PY})
from storyforge.extract import parse_intent_response
response = '''FUNCTION: Emmett reads the staged crime scene and connects the murder to a disappearance
SCENE_TYPE: action
EMOTIONAL_ARC: Professional detachment to resolved determination
VALUE_AT_STAKE: truth
VALUE_SHIFT: +/-
TURNING_POINT: revelation
THREADS: murder-investigation;land-fraud
CHARACTERS: Emmett Slade;Samuel Orcutt;Colson
ON_STAGE: Emmett Slade;Colson
MICE_THREADS: +inquiry:who-killed-orcutt
CONFIDENCE: high'''
result = parse_intent_response(response, 'arranged-dead')
print(result.get('function', ''))
print(result.get('scene_type', ''))
print(result.get('value_shift', ''))
print(result.get('threads', ''))
print(result.get('_confidence', ''))
")

assert_contains "$RESULT" "staged crime scene" "parse_intent: extracts function"
assert_contains "$RESULT" "action" "parse_intent: extracts scene type"
assert_contains "$RESULT" "+/-" "parse_intent: extracts value shift"
assert_contains "$RESULT" "murder-investigation" "parse_intent: extracts threads"
assert_contains "$RESULT" "high" "parse_intent: extracts confidence"

# ============================================================================
# parse_brief_parallel_response
# ============================================================================

RESULT=$(python3 -c "
${PY})
from storyforge.extract import parse_brief_parallel_response
response = '''GOAL: Determine cause of death and establish whether it's murder
CONFLICT: The crime scene has been deliberately staged to look accidental
OUTCOME: no-and
CRISIS: Report the staging and alert the territorial marshal, or investigate quietly
DECISION: Investigates quietly — keeps the staging knowledge to himself
KEY_ACTIONS: Examines body;Notes staged positioning;Finds survey equipment;Interviews Colson
KEY_DIALOGUE: \"The body was found like this?\";\"Exactly like this, Sheriff\"
EMOTIONS: professional-calm;suspicion;recognition;quiet-resolve
MOTIFS: arranged-bodies;survey-equipment;patience'''
result = parse_brief_parallel_response(response, 'arranged-dead')
print(result.get('goal', ''))
print(result.get('outcome', ''))
print(result.get('crisis', ''))
")

assert_contains "$RESULT" "cause of death" "parse_brief: extracts goal"
assert_contains "$RESULT" "no-and" "parse_brief: extracts outcome"
assert_contains "$RESULT" "Report the staging" "parse_brief: extracts crisis"

# ============================================================================
# parse_knowledge_response
# ============================================================================

RESULT=$(python3 -c "
${PY})
from storyforge.extract import parse_knowledge_response
response = '''KNOWLEDGE_IN: Orcutt was found dead at the alkali flat
KNOWLEDGE_OUT: Orcutt was found dead at the alkali flat;the body was deliberately staged;survey equipment was present at the scene
CONTINUITY_DEPS: discovery-at-flat
SCENE_SUMMARY: Emmett examines the staged crime scene and decides to investigate quietly'''
result = parse_knowledge_response(response, 'arranged-dead')
print(result.get('knowledge_in', ''))
print(result.get('knowledge_out', ''))
print(result.get('continuity_deps', ''))
print(result.get('_summary', ''))
")

assert_contains "$RESULT" "Orcutt was found dead" "parse_knowledge: extracts knowledge_in"
assert_contains "$RESULT" "deliberately staged" "parse_knowledge: extracts knowledge_out"
assert_contains "$RESULT" "discovery-at-flat" "parse_knowledge: extracts continuity_deps"
assert_contains "$RESULT" "examines the staged" "parse_knowledge: extracts summary"

# ============================================================================
# analyze_expansion_opportunities
# ============================================================================

RESULT=$(python3 -c "
${PY})
from storyforge.extract import analyze_expansion_opportunities
import json
opps = analyze_expansion_opportunities('${FIXTURE_DIR}/reference')
for o in opps:
    print(f\"{o['type']}: {o['priority']} — {o['scene_id']}\")
")

# Fixture has scenes — check that analysis runs without error
assert_not_empty "$RESULT" "analyze_expansion: produces output"

# ============================================================================
# build_characterize_prompt
# ============================================================================

RESULT=$(python3 -c "
${PY})
from storyforge.extract import build_characterize_prompt
prompt = build_characterize_prompt('${FIXTURE_DIR}')
print(len(prompt))
")

# Fixtures have scene files, so prompt should be non-empty
assert_not_empty "$RESULT" "build_characterize: produces non-empty prompt"
```

- [ ] **Step 2: Run tests**

```bash
./tests/run-tests.sh tests/test-extract.sh
```

- [ ] **Step 3: Commit**

```bash
git add tests/test-extract.sh
git commit -m "Add tests for extraction parsers and expansion analysis"
```

---

## Task 3: The `storyforge-extract` CLI script

**Files:**
- Create: `scripts/storyforge-extract`

The script orchestrates all four phases. Each phase produces output, commits, and the next phase reads from the committed data.

Key design decisions:
- Phase 0 uses Opus (full manuscript comprehension)
- Phases 1-2 use batch API with Sonnet (parallel, structured extraction)
- Phase 3a uses batch API with Sonnet (parallel)
- Phase 3b uses direct API with Sonnet (sequential — each scene needs prior knowledge state)
- Each phase commits its results before the next phase starts
- `--phase 0|1|2|3` flag allows running individual phases
- `--dry-run` prints prompts without invoking
- Expansion analysis runs after Phase 3 completes

The script follows the same patterns as storyforge-enrich and storyforge-elaborate: source common.sh, detect_project_root, create_branch, create_draft_pr, batch submission, result processing, commit per phase, run_review_phase at end.

---

## Task 4: The `extract` skill

**Files:**
- Create: `skills/extract/SKILL.md`

Interactive skill that guides the author through extraction. Offers:
- Full extraction (all phases) — delegates to the script
- Phase-by-phase with review between phases
- Expansion analysis for novella-to-novel work
- Review and correction of extracted data

Coaching levels:
- Full: Run extraction autonomously, present results for review
- Coach: Run extraction, walk through results with author, discuss concerns
- Strict: Run extraction, present raw data for author correction

---

## Task 5: Add expansion analysis to elaborate.py

**Files:**
- Modify: `scripts/lib/python/storyforge/elaborate.py`

Add an `analyze_expansion` function that wraps the extraction module's expansion analysis and formats it as a validation-style report.

---

## Task 6: Tests, version bump, final verification

- [ ] Run full test suite
- [ ] Bump version to 0.44.0
- [ ] Commit and push
- [ ] Create PR
