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
    """Read the full manuscript by concatenating scene files in seq order."""
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

    # Truncate if extremely long — Phase 0 needs the shape, not every word
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
    continuity_deps. Must be called sequentially."""
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

    Returns a list of opportunity dicts with type, scene_id, description, priority.
    """
    from .elaborate import _read_csv_as_map

    scenes_map = _read_csv_as_map(os.path.join(ref_dir, 'scenes.csv'))
    intent_map = _read_csv_as_map(os.path.join(ref_dir, 'scene-intent.csv'))
    briefs_map = _read_csv_as_map(os.path.join(ref_dir, 'scene-briefs.csv'))

    opportunities = []
    sorted_ids = sorted(scenes_map.keys(),
                        key=lambda s: int(scenes_map[s].get('seq', 0)))

    # Compressed scenes: major value shift in under 1000 words
    for sid in sorted_ids:
        scene = scenes_map[sid]
        wc = int(scene.get('word_count', 0) or 0)
        intent = intent_map.get(sid, {})
        vs = intent.get('value_shift', '')
        if wc > 0 and wc < 1000 and vs and '/' in vs:
            parts = vs.split('/')
            if parts[0].strip() != parts[1].strip():
                opportunities.append({
                    'type': 'compressed_scene',
                    'scene_id': sid,
                    'description': f"Major value shift ({vs}) in only {wc} words",
                    'priority': 'high' if wc < 500 else 'medium',
                })

    # Knowledge jumps: 3+ new facts in one scene
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
                    'description': f"Character learns {len(new_facts)} new facts in one scene",
                    'priority': 'high' if len(new_facts) >= 5 else 'medium',
                })

    # Timeline gaps: more than 2 days between consecutive scenes
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
                'description': f"Gap of {day - prev_day} days between scenes",
                'priority': 'medium' if day - prev_day <= 7 else 'high',
            })
        prev_day = day
        prev_id = sid

    # Thin threads: appear in only 1-2 scenes
    thread_counts: dict[str, list[str]] = {}
    for sid in sorted_ids:
        intent = intent_map.get(sid, {})
        threads = intent.get('threads', '').strip()
        if threads:
            for t in threads.split(';'):
                t = t.strip()
                if t:
                    thread_counts.setdefault(t, []).append(sid)
    for thread, sids in thread_counts.items():
        if len(sids) <= 2:
            opportunities.append({
                'type': 'thin_thread',
                'scene_id': ';'.join(sids),
                'description': f"Thread '{thread}' appears in only {len(sids)} scene(s)",
                'priority': 'medium',
            })

    # Missing sequels: consecutive action scenes
    for i, sid in enumerate(sorted_ids[:-1]):
        intent = intent_map.get(sid, {})
        next_intent = intent_map.get(sorted_ids[i + 1], {})
        if intent.get('scene_type') == 'action' and next_intent.get('scene_type') == 'action':
            opportunities.append({
                'type': 'missing_sequel',
                'scene_id': sid,
                'description': f"Action scene followed by action — reaction beat may be needed between {sid} and {sorted_ids[i+1]}",
                'priority': 'low',
            })

    priority_order = {'high': 0, 'medium': 1, 'low': 2}
    opportunities.sort(key=lambda o: priority_order.get(o['priority'], 3))
    return opportunities


# ============================================================================
# Post-extraction cleanup
# ============================================================================

def cleanup_timeline(ref_dir: str) -> list[dict]:
    """Fill empty timeline_day fields by interpolating from adjacent scenes.

    Returns a list of fixes applied: [{scene_id, field, old_value, new_value}]
    """
    from .elaborate import _read_csv_as_map, _write_csv, _FILE_MAP

    scenes_map = _read_csv_as_map(os.path.join(ref_dir, 'scenes.csv'))
    sorted_ids = sorted(scenes_map.keys(),
                        key=lambda s: int(scenes_map[s].get('seq', 0)))

    fixes = []

    # Build list of (id, day_or_none)
    days = []
    for sid in sorted_ids:
        day_str = scenes_map[sid].get('timeline_day', '').strip()
        try:
            days.append((sid, int(day_str)))
        except (ValueError, TypeError):
            days.append((sid, None))

    # Fill gaps by interpolation
    for i, (sid, day) in enumerate(days):
        if day is not None:
            continue

        # Find nearest known day before and after
        prev_day = None
        for j in range(i - 1, -1, -1):
            if days[j][1] is not None:
                prev_day = days[j][1]
                break

        next_day = None
        for j in range(i + 1, len(days)):
            if days[j][1] is not None:
                next_day = days[j][1]
                break

        # Infer
        inferred = None
        if prev_day is not None and next_day is not None:
            # Between two known days — use the previous day (same day until proven otherwise)
            inferred = prev_day
        elif prev_day is not None:
            inferred = prev_day  # Assume same day as previous
        elif next_day is not None:
            inferred = next_day  # Assume same day as next

        if inferred is not None:
            old_val = scenes_map[sid].get('timeline_day', '')
            scenes_map[sid]['timeline_day'] = str(inferred)
            days[i] = (sid, inferred)
            fixes.append({
                'scene_id': sid,
                'field': 'timeline_day',
                'old_value': old_val,
                'new_value': str(inferred),
            })

    if fixes:
        ordered = sorted(scenes_map.values(), key=lambda r: int(r.get('seq', 0)))
        _write_csv(os.path.join(ref_dir, 'scenes.csv'), ordered, _FILE_MAP['scenes.csv'])

    return fixes


def cleanup_knowledge(ref_dir: str) -> list[dict]:
    """Normalize knowledge wording so knowledge_in matches prior knowledge_out.

    Uses fuzzy matching: if a knowledge_in fact is >80% similar to a
    knowledge_out fact from a prior scene, replace it with the exact
    knowledge_out wording.

    Returns a list of fixes applied.
    """
    from .elaborate import _read_csv_as_map, _write_csv, _FILE_MAP

    scenes_map = _read_csv_as_map(os.path.join(ref_dir, 'scenes.csv'))
    briefs_map = _read_csv_as_map(os.path.join(ref_dir, 'scene-briefs.csv'))
    sorted_ids = sorted(scenes_map.keys(),
                        key=lambda s: int(scenes_map[s].get('seq', 0)))

    fixes = []

    # Build cumulative knowledge pool with exact wording
    knowledge_pool = set()

    for sid in sorted_ids:
        brief = briefs_map.get(sid, {})
        knowledge_in = brief.get('knowledge_in', '').strip()

        if knowledge_in and knowledge_pool:
            facts_in = [f.strip() for f in knowledge_in.split(';') if f.strip()]
            new_facts = []
            changed = False

            for fact in facts_in:
                if fact in knowledge_pool:
                    new_facts.append(fact)
                    continue

                # Fuzzy match against pool
                best_match = None
                best_score = 0.0
                fact_lower = fact.lower()
                for pool_fact in knowledge_pool:
                    score = _similarity(fact_lower, pool_fact.lower())
                    if score > best_score:
                        best_score = score
                        best_match = pool_fact

                if best_match and best_score >= 0.7:
                    new_facts.append(best_match)
                    changed = True
                else:
                    new_facts.append(fact)

            if changed:
                old_val = knowledge_in
                new_val = '; '.join(new_facts)
                briefs_map[sid]['knowledge_in'] = new_val
                fixes.append({
                    'scene_id': sid,
                    'field': 'knowledge_in',
                    'old_value': old_val[:80] + '...' if len(old_val) > 80 else old_val,
                    'new_value': new_val[:80] + '...' if len(new_val) > 80 else new_val,
                })

        # Add this scene's knowledge_out to pool
        knowledge_out = brief.get('knowledge_out', '').strip()
        if knowledge_out:
            for fact in knowledge_out.split(';'):
                fact = fact.strip()
                if fact:
                    knowledge_pool.add(fact)

    if fixes:
        ordered = sorted(briefs_map.values(), key=lambda r: r.get('id', ''))
        _write_csv(os.path.join(ref_dir, 'scene-briefs.csv'), ordered, _FILE_MAP['scene-briefs.csv'])

    return fixes


def _similarity(a: str, b: str) -> float:
    """Simple word-overlap similarity between two strings. Returns 0.0-1.0."""
    words_a = set(a.split())
    words_b = set(b.split())
    if not words_a or not words_b:
        return 0.0
    intersection = words_a & words_b
    union = words_a | words_b
    return len(intersection) / len(union)


def cleanup_mice_threads(ref_dir: str) -> list[dict]:
    """Fix unambiguous MICE thread nesting violations.

    - Remove duplicate opens (thread opened twice without close)
    - Remove closes for threads that were never opened
    - Reorder closes when the fix is unambiguous (only one thread to close)

    Returns a list of fixes applied.
    """
    from .elaborate import _read_csv_as_map, _write_csv, _FILE_MAP

    intent_map = _read_csv_as_map(os.path.join(ref_dir, 'scene-intent.csv'))
    scenes_map = _read_csv_as_map(os.path.join(ref_dir, 'scenes.csv'))
    sorted_ids = sorted(scenes_map.keys(),
                        key=lambda s: int(scenes_map[s].get('seq', 0)))

    fixes = []
    open_threads = set()  # currently open thread names

    for sid in sorted_ids:
        intent = intent_map.get(sid, {})
        mice = intent.get('mice_threads', '').strip()
        if not mice:
            continue

        entries = [e.strip() for e in mice.split(';') if e.strip()]
        new_entries = []
        changed = False

        for entry in entries:
            if entry.startswith('+'):
                thread_name = entry[1:]
                if thread_name in open_threads:
                    # Duplicate open — skip it
                    changed = True
                    fixes.append({
                        'scene_id': sid,
                        'field': 'mice_threads',
                        'old_value': entry,
                        'new_value': '(removed duplicate open)',
                    })
                else:
                    open_threads.add(thread_name)
                    new_entries.append(entry)
            elif entry.startswith('-'):
                thread_name = entry[1:]
                if thread_name not in open_threads:
                    # Close for unopened thread — skip it
                    changed = True
                    fixes.append({
                        'scene_id': sid,
                        'field': 'mice_threads',
                        'old_value': entry,
                        'new_value': '(removed close for unopened thread)',
                    })
                else:
                    open_threads.discard(thread_name)
                    new_entries.append(entry)
            else:
                new_entries.append(entry)

        if changed:
            intent_map[sid]['mice_threads'] = ';'.join(new_entries)

    if fixes:
        ordered = sorted(intent_map.values(), key=lambda r: r.get('id', ''))
        _write_csv(os.path.join(ref_dir, 'scene-intent.csv'), ordered, _FILE_MAP['scene-intent.csv'])

    return fixes


def run_cleanup(ref_dir: str) -> dict:
    """Run all cleanup passes. Returns a summary dict."""
    timeline_fixes = cleanup_timeline(ref_dir)
    knowledge_fixes = cleanup_knowledge(ref_dir)
    mice_fixes = cleanup_mice_threads(ref_dir)

    return {
        'timeline': {'count': len(timeline_fixes), 'fixes': timeline_fixes},
        'knowledge': {'count': len(knowledge_fixes), 'fixes': knowledge_fixes},
        'mice_threads': {'count': len(mice_fixes), 'fixes': mice_fixes},
        'total_fixes': len(timeline_fixes) + len(knowledge_fixes) + len(mice_fixes),
    }
