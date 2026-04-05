"""Structural scoring engine — story quality from CSV data.

Deterministic, no API calls. Reads scene CSVs and produces quantified
scores across 8 dimensions with diagnostic findings.

Each score_* function returns:
    {'score': float (0-1), 'findings': [{'message': str, 'scene_id': str, ...}]}
"""

import datetime
import math
import os

from storyforge.elaborate import (
    _read_csv, _read_csv_as_map, _write_csv, _FILE_MAP, DELIMITER,
)


# ---------------------------------------------------------------------------
# Field definitions for completeness scoring
# ---------------------------------------------------------------------------

# Required fields — weight 1.0 each (from intent + briefs)
REQUIRED_FIELDS = [
    'function', 'value_at_stake', 'value_shift', 'emotional_arc',
    'goal', 'conflict', 'outcome', 'crisis', 'decision',
]

# Enrichment fields — weight 0.5 each (from briefs)
ENRICHMENT_FIELDS = [
    'knowledge_in', 'knowledge_out', 'key_actions', 'key_dialogue',
    'emotions', 'motifs', 'continuity_deps', 'mice_threads',
]

REQUIRED_WEIGHT = 1.0
ENRICHMENT_WEIGHT = 0.5


# ---------------------------------------------------------------------------
# Completeness
# ---------------------------------------------------------------------------

def score_completeness(scenes_map, intent_map, briefs_map):
    """Score how completely scenes are specified across intent and brief fields.

    Args:
        scenes_map: dict from _read_csv_as_map on scenes.csv
        intent_map: dict from _read_csv_as_map on scene-intent.csv
        briefs_map: dict from _read_csv_as_map on scene-briefs.csv

    Returns:
        {'score': float 0-1, 'findings': [{'message': str, 'scene_id': str, 'severity': str}]}
    """
    findings = []
    total_weighted = 0.0
    populated_weighted = 0.0

    scene_ids = sorted(scenes_map.keys())

    for scene_id in scene_ids:
        intent = intent_map.get(scene_id, {})
        brief = briefs_map.get(scene_id, {})

        # Check required fields
        missing_required = []
        for field in REQUIRED_FIELDS:
            total_weighted += REQUIRED_WEIGHT
            value = intent.get(field, '') or brief.get(field, '')
            if value.strip():
                populated_weighted += REQUIRED_WEIGHT
            else:
                missing_required.append(field)

        if missing_required:
            findings.append({
                'message': f"Missing required fields: {', '.join(missing_required)}",
                'scene_id': scene_id,
                'severity': 'important',
                'fields': missing_required,
            })

        # Check enrichment fields
        missing_enrichment = []
        for field in ENRICHMENT_FIELDS:
            total_weighted += ENRICHMENT_WEIGHT
            value = intent.get(field, '') or brief.get(field, '')
            if value.strip():
                populated_weighted += ENRICHMENT_WEIGHT
            else:
                missing_enrichment.append(field)

        if len(missing_enrichment) >= 4:
            findings.append({
                'message': f"Missing {len(missing_enrichment)} enrichment fields: {', '.join(missing_enrichment)}",
                'scene_id': scene_id,
                'severity': 'minor',
                'fields': missing_enrichment,
            })

    score = populated_weighted / total_weighted if total_weighted > 0 else 0.0
    return {'score': score, 'findings': findings}


# ---------------------------------------------------------------------------
# Thematic Concentration
# ---------------------------------------------------------------------------

def score_thematic_concentration(intent_map):
    """Score thematic focus using Herfindahl index on value_at_stake distribution.

    Empirical basis: Archer & Jockers (2016) found bestsellers dedicate ~30%
    of text to 1-2 dominant topics.

    Args:
        intent_map: dict from _read_csv_as_map on scene-intent.csv

    Returns:
        {'score': float 0-1, 'findings': [{'message': str, 'severity': str}]}
    """
    findings = []

    # 1. Collect all non-empty value_at_stake values
    values = []
    for scene_id, intent in intent_map.items():
        v = intent.get('value_at_stake', '').strip()
        if v:
            values.append(v)

    total = len(values)
    if total == 0:
        return {'score': 0.0, 'findings': [{'message': 'No value_at_stake data found', 'severity': 'important'}]}

    # 2. Count frequency of each value
    freq = {}
    for v in values:
        freq[v] = freq.get(v, 0) + 1

    distinct_count = len(freq)

    # 3. Compute Herfindahl index: sum of (count/total)^2
    hhi = sum((c / total) ** 2 for c in freq.values())

    # 4. Check top-2 dominance: do top 2 values cover >= 30% of scenes?
    sorted_counts = sorted(freq.values(), reverse=True)
    top2_share = sum(sorted_counts[:2]) / total if len(sorted_counts) >= 2 else sorted_counts[0] / total

    # 5. Generate findings for fragmentation or narrowness
    if distinct_count > 20:
        findings.append({
            'message': f"Thematic fragmentation: {distinct_count} distinct values at stake across {total} scenes",
            'severity': 'important',
        })

    if distinct_count < 4 and total >= 10:
        findings.append({
            'message': f"Narrow thematic range: only {distinct_count} distinct values across {total} scenes",
            'severity': 'minor',
        })

    # 6. Info-level finding listing top 5 values with counts
    sorted_values = sorted(freq.items(), key=lambda x: x[1], reverse=True)
    top5 = sorted_values[:5]
    top5_str = ', '.join(f"{v} ({c})" for v, c in top5)
    findings.append({
        'message': f"Top values at stake: {top5_str}",
        'severity': 'info',
    })

    # Scoring
    hhi_score = min(1.0, hhi / 0.35)

    count_penalty = 0.0
    if distinct_count > 20:
        count_penalty = min(0.3, 0.015 * (distinct_count - 20))
    if distinct_count < 5 and total >= 10:
        count_penalty = 0.1

    score = max(0.0, min(1.0, hhi_score - count_penalty))

    return {'score': score, 'findings': findings}


# ---------------------------------------------------------------------------
# Pacing Shape
# ---------------------------------------------------------------------------

# Tension lookup tables
_SHIFT_TENSION = {
    '-/--': 1.0, '+/-': 0.85, '-/-': 0.7, '-/+': 0.5, '+/+': 0.2, '+/++': 0.15,
}

_OUTCOME_TENSION = {
    'no': 0.9, 'no-and': 1.0, 'no-but': 0.7, 'yes-but': 0.5, 'yes': 0.2,
}

_TYPE_TENSION = {
    'action': 0.7, 'sequel': 0.4,
}


def _scene_tension(intent, brief):
    """Compute a 0-1 tension score for a single scene from intent + brief signals.

    Combines value_shift (50%), outcome (30%), and scene type (20%).
    Defaults to 0.5 for any missing or unknown values.
    """
    shift = intent.get('value_shift', '').strip()
    shift_t = _SHIFT_TENSION.get(shift, 0.5)

    outcome = brief.get('outcome', '').strip()
    outcome_t = _OUTCOME_TENSION.get(outcome, 0.5)

    scene_type = intent.get('action_sequel', '').strip().lower()
    type_t = _TYPE_TENSION.get(scene_type, 0.5)

    return (shift_t * 0.5) + (outcome_t * 0.3) + (type_t * 0.2)


def _beat_regularity(tensions):
    """Measure how often consecutive scenes alternate tension direction.

    Empirical basis: Archer & Jockers (2016) — bestsellers show
    near-sinusoidal oscillation in sentiment across their arc.

    Returns fraction of interior scenes where direction reverses.
    Returns 0.5 for sequences shorter than 3.
    """
    n = len(tensions)
    if n < 3:
        return 0.5

    alternations = 0
    for i in range(1, n - 1):
        delta_before = tensions[i] - tensions[i - 1]
        delta_after = tensions[i + 1] - tensions[i]
        if delta_before * delta_after < 0:
            alternations += 1

    return alternations / (n - 2)


def score_pacing(scenes_map, intent_map, briefs_map):
    """Score pacing shape across five sub-metrics.

    Sub-metrics:
        1. Act proportions — first/last parts each ~25% of total words
        2. Climax position — max tension scene ideally at 85-90% through
        3. Midpoint presence — tension at ~50% exceeds average
        4. Beat regularity — alternation frequency (Archer/Jockers)
        5. Escalation — second half mean tension > first half

    Args:
        scenes_map: dict from _read_csv_as_map on scenes.csv
        intent_map: dict from _read_csv_as_map on scene-intent.csv
        briefs_map: dict from _read_csv_as_map on scene-briefs.csv

    Returns:
        {'score': float 0-1, 'findings': [{'message': str, 'severity': str}]}
    """
    findings = []

    # Sort scenes by seq
    def _seq(item):
        try:
            return int(item[1].get('seq', 0))
        except (ValueError, TypeError):
            return 0

    ordered = sorted(scenes_map.items(), key=_seq)
    scene_ids = [sid for sid, _ in ordered]
    n = len(scene_ids)

    if n == 0:
        return {'score': 0.0, 'findings': [{'message': 'No scenes found', 'severity': 'important'}]}

    # Build tension array
    tensions = []
    for sid in scene_ids:
        intent = intent_map.get(sid, {})
        brief = briefs_map.get(sid, {})
        tensions.append(_scene_tension(intent, brief))

    # --- 1. Act proportions ---
    # Gather word counts per part
    part_words = {}
    total_words = 0
    for sid, scene in ordered:
        part = scene.get('part', '').strip() or '1'
        wc = 0
        for field in ('target_words', 'word_count'):
            try:
                wc = int(scene.get(field, 0))
                if wc > 0:
                    break
            except (ValueError, TypeError):
                continue
        part_words[part] = part_words.get(part, 0) + wc
        total_words += wc

    act_score = 1.0
    if total_words > 0 and len(part_words) >= 2:
        parts_sorted = sorted(part_words.keys())
        first_part = parts_sorted[0]
        last_part = parts_sorted[-1]
        first_ratio = part_words[first_part] / total_words
        last_ratio = part_words[last_part] / total_words

        first_dev = abs(first_ratio - 0.25)
        last_dev = abs(last_ratio - 0.25)

        # Penalize deviation > 10%
        if first_dev > 0.10:
            act_score -= min(0.5, (first_dev - 0.10) * 5)
            findings.append({
                'message': f"First act is {first_ratio:.0%} of total (ideal ~25%)",
                'severity': 'minor',
            })
        if last_dev > 0.10:
            act_score -= min(0.5, (last_dev - 0.10) * 5)
            findings.append({
                'message': f"Last act is {last_ratio:.0%} of total (ideal ~25%)",
                'severity': 'minor',
            })
        act_score = max(0.0, act_score)
    elif total_words == 0:
        act_score = 0.5  # No word count data — neutral

    # --- 2. Climax position ---
    max_tension = max(tensions)
    max_idx = tensions.index(max_tension)
    if n > 1:
        position = max_idx / (n - 1)
    else:
        position = 0.88  # Single scene — neutral

    climax_score = max(0.0, 1.0 - abs(position - 0.88) * 4)

    if position < 0.6:
        findings.append({
            'message': f"Climax at {position:.0%} through — unusually early (ideal 85-90%)",
            'severity': 'minor',
        })

    # --- 3. Midpoint presence ---
    avg_tension = sum(tensions) / n
    mid_idx = n // 2
    mid_tension = tensions[mid_idx]

    if mid_tension > avg_tension:
        midpoint_score = min(1.0, 0.5 + (mid_tension - avg_tension) * 2)
    else:
        midpoint_score = max(0.0, 0.5 - (avg_tension - mid_tension) * 2)

    # --- 4. Beat regularity ---
    regularity = _beat_regularity(tensions)
    regularity_score = regularity

    if regularity < 0.3:
        findings.append({
            'message': f"Low beat regularity ({regularity:.2f}) — tension rarely alternates direction",
            'severity': 'minor',
        })

    # --- 5. Escalation ---
    half = n // 2
    first_half_mean = sum(tensions[:half]) / half if half > 0 else 0.5
    second_half_mean = sum(tensions[half:]) / (n - half) if (n - half) > 0 else 0.5

    if second_half_mean > first_half_mean:
        escalation_score = min(1.0, 0.5 + (second_half_mean - first_half_mean) * 3)
    else:
        escalation_score = max(0.0, 0.5 - (first_half_mean - second_half_mean) * 3)

    if second_half_mean <= first_half_mean:
        findings.append({
            'message': "Second half tension does not exceed first half — no escalation",
            'severity': 'minor',
        })

    # Composite
    score = (
        act_score * 0.25 +
        climax_score * 0.25 +
        midpoint_score * 0.15 +
        regularity_score * 0.20 +
        escalation_score * 0.15
    )
    score = max(0.0, min(1.0, score))

    return {'score': score, 'findings': findings}


# ---------------------------------------------------------------------------
# Arc Completeness
# ---------------------------------------------------------------------------

# Valence classification for value_shift tokens
_POSITIVE_SHIFTS = {'-/+', '+/+', '+/++'}
_NEGATIVE_SHIFTS = {'+/-', '-/--', '-/-'}


def _classify_arc_shape(shifts):
    """Classify a character's value_shift sequence into a Reagan archetype.

    Maps each shift to positive/negative valence, counts sign reversals,
    and classifies into one of six shapes.

    Args:
        shifts: list of value_shift strings (e.g. ['+/-', '-/+', '+/-'])

    Returns:
        (shape_name, reversal_count, is_compound)
    """
    # Map shifts to valence: +1, -1, or 0 (unknown/empty)
    valences = []
    for s in shifts:
        s = s.strip()
        if s in _POSITIVE_SHIFTS:
            valences.append(1)
        elif s in _NEGATIVE_SHIFTS:
            valences.append(-1)
        else:
            valences.append(0)

    # Filter out zero-valence for reversal counting
    nonzero = [v for v in valences if v != 0]

    if not nonzero:
        return ('flat', 0, False)

    # Count reversals: consecutive non-zero valences that change sign
    reversals = 0
    for i in range(1, len(nonzero)):
        if nonzero[i] != nonzero[i - 1]:
            reversals += 1

    # Classify
    positive_count = sum(1 for v in nonzero if v > 0)
    negative_count = sum(1 for v in nonzero if v < 0)
    mostly_positive = positive_count >= negative_count
    ends_positive = nonzero[-1] > 0

    is_compound = reversals >= 2

    if reversals == 0:
        shape = 'rags-to-riches' if mostly_positive else 'tragedy'
    elif reversals == 1:
        # First half determines shape
        half = len(nonzero) // 2 or 1
        first_half_negative = sum(1 for v in nonzero[:half] if v < 0) > sum(1 for v in nonzero[:half] if v > 0)
        shape = 'man-in-a-hole' if first_half_negative else 'icarus'
    else:
        shape = 'cinderella' if ends_positive else 'oedipus'

    return (shape, reversals, is_compound)


def score_arcs(scenes_map, intent_map):
    """Score arc completeness across POV characters.

    Measures value variety, arc shape/reversals, and transformation signal
    for each POV character, then produces a weighted average.

    Args:
        scenes_map: dict from _read_csv_as_map on scenes.csv
        intent_map: dict from _read_csv_as_map on scene-intent.csv

    Returns:
        {'score': float 0-1, 'findings': [...], 'character_arcs': [...]}
    """
    findings = []

    # Sort scenes by seq
    def _seq(item):
        try:
            return int(item[1].get('seq', 0))
        except (ValueError, TypeError):
            return 0

    ordered = sorted(scenes_map.items(), key=_seq)

    # Group scenes by POV character
    char_scenes = {}  # character -> [(scene_id, scene, intent), ...]
    for sid, scene in ordered:
        pov = scene.get('pov', '').strip()
        if not pov:
            continue
        intent = intent_map.get(sid, {})
        if pov not in char_scenes:
            char_scenes[pov] = []
        char_scenes[pov].append((sid, scene, intent))

    if not char_scenes:
        return {'score': 0.0, 'findings': [{'message': 'No POV characters found', 'severity': 'important'}], 'character_arcs': []}

    character_arcs = []
    total_weight = 0
    weighted_sum = 0.0

    for character, scene_list in char_scenes.items():
        scene_count = len(scene_list)

        # Collect values and shifts
        values = set()
        shifts = []
        emotional_arcs = []
        for sid, scene, intent in scene_list:
            v = intent.get('value_at_stake', '').strip()
            if v:
                values.add(v)
            shifts.append(intent.get('value_shift', '').strip())
            ea = intent.get('emotional_arc', '').strip()
            if ea:
                emotional_arcs.append(ea)

        value_count = len(values)

        # --- 1. Value variety ---
        if scene_count < 4:
            variety_score = 0.7
        elif value_count == 1:
            variety_score = 0.1
        elif value_count == 2:
            variety_score = 0.4
        elif 3 <= value_count <= 6:
            variety_score = 0.9
        elif 7 <= value_count <= 10:
            variety_score = 0.7
        else:
            variety_score = 0.5

        # --- 2. Arc shape + reversals ---
        shape, reversals, is_compound = _classify_arc_shape(shifts)

        if scene_count < 4:
            reversal_score = 0.5
        elif reversals == 0:
            reversal_score = 0.2
        elif reversals == 1:
            reversal_score = 0.5
        elif reversals == 2:
            reversal_score = 0.8
        elif 3 <= reversals <= 4:
            reversal_score = 0.9
        else:
            # Diminishing returns for 5+
            reversal_score = max(0.5, 0.9 - (reversals - 4) * 0.1)

        # --- 3. Transformation signal ---
        if len(emotional_arcs) >= 2:
            first_words = set(emotional_arcs[0].lower().split()[:4])
            last_words = set(emotional_arcs[-1].lower().split()[:4])
            if first_words and last_words:
                overlap = len(first_words & last_words) / max(len(first_words), len(last_words))
                if overlap <= 0.25:
                    transform_score = 0.9
                elif overlap >= 0.75:
                    transform_score = 0.2
                else:
                    # Linear interpolation between 0.25 and 0.75
                    transform_score = 0.9 - (overlap - 0.25) * (0.7 / 0.5)
            else:
                transform_score = 0.5
        else:
            transform_score = 0.5

        # Composite per character
        arc_score = variety_score * 0.3 + reversal_score * 0.4 + transform_score * 0.3

        character_arcs.append({
            'character': character,
            'scene_count': scene_count,
            'value_count': value_count,
            'shape': shape,
            'reversals': reversals,
            'is_compound': is_compound,
            'arc_score': arc_score,
        })

        # Findings
        if value_count == 1:
            findings.append({
                'message': f"{character}: only 1 value at stake across {scene_count} scenes",
                'severity': 'important',
                'character': character,
            })
        if reversals == 0 and scene_count >= 4:
            findings.append({
                'message': f"{character}: no arc reversals ({shape})",
                'severity': 'minor',
                'character': character,
            })
        if is_compound:
            findings.append({
                'message': f"{character}: compound arc ({shape}, {reversals} reversals)",
                'severity': 'info',
                'character': character,
            })

        # Weighted by scene count
        weighted_sum += arc_score * scene_count
        total_weight += scene_count

    overall_score = weighted_sum / total_weight if total_weight > 0 else 0.0

    return {
        'score': max(0.0, min(1.0, overall_score)),
        'findings': findings,
        'character_arcs': character_arcs,
    }


# ---------------------------------------------------------------------------
# Character Presence
# ---------------------------------------------------------------------------

def score_character_presence(scenes_map, intent_map, ref_dir):
    """Score POV balance, antagonist visibility, presence gaps, mention-to-onstage ratio.

    Args:
        scenes_map: dict from _read_csv_as_map on scenes.csv
        intent_map: dict from _read_csv_as_map on scene-intent.csv
        ref_dir: path to reference directory (for characters.csv)

    Returns:
        {'score': float 0-1, 'findings': [...]}
    """
    findings = []

    # Sort scenes by seq
    def _seq(item):
        try:
            return int(item[1].get('seq', 0))
        except (ValueError, TypeError):
            return 0

    ordered = sorted(scenes_map.items(), key=_seq)
    scene_ids = [sid for sid, _ in ordered]
    n = len(scene_ids)

    if n == 0:
        return {'score': 0.0, 'findings': [{'message': 'No scenes found', 'severity': 'important'}]}

    # Load character roles from characters.csv if it exists
    char_roles = {}  # character_name -> role
    chars_path = os.path.join(ref_dir, 'characters.csv')
    if os.path.exists(chars_path):
        rows = _read_csv(chars_path)
        for row in rows:
            name = row.get('name', '').strip() or row.get('id', '').strip()
            role = row.get('role', '').strip().lower()
            if name:
                char_roles[name] = role

    # Count per character: POV scenes, on_stage, mentions
    pov_counts = {}   # character -> count of POV scenes
    onstage = {}      # character -> list of scene indices
    mentions = {}     # character -> list of scene indices

    for idx, sid in enumerate(scene_ids):
        scene = scenes_map[sid]
        intent = intent_map.get(sid, {})

        # POV
        pov = scene.get('pov', '').strip()
        if pov:
            pov_counts[pov] = pov_counts.get(pov, 0) + 1

        # on_stage
        on_stage_str = intent.get('on_stage', '').strip()
        if on_stage_str:
            for ch in on_stage_str.split(';'):
                ch = ch.strip()
                if ch:
                    if ch not in onstage:
                        onstage[ch] = []
                    onstage[ch].append(idx)

        # characters (mentions)
        chars_str = intent.get('characters', '').strip()
        if chars_str:
            for ch in chars_str.split(';'):
                ch = ch.strip()
                if ch:
                    if ch not in mentions:
                        mentions[ch] = []
                    mentions[ch].append(idx)

    # Identify antagonists and POV characters by role
    antagonists = set()
    pov_characters = set(pov_counts.keys())
    for name, role in char_roles.items():
        if role == 'antagonist':
            antagonists.add(name)

    # --- 1. POV balance ---
    pov_score = 1.0
    if pov_counts:
        max_pov = max(pov_counts.values())
        if max_pov / n > 0.70:
            dominant = [k for k, v in pov_counts.items() if v == max_pov][0]
            pov_score = max(0.0, 1.0 - (max_pov / n - 0.70) * 5)
            findings.append({
                'message': f"POV imbalance: {dominant} has {max_pov}/{n} scenes ({max_pov/n:.0%})",
                'severity': 'minor',
            })

    # --- 2. Antagonist visibility ---
    antag_score = 1.0
    if antagonists:
        antag_penalties = 0
        for antag in antagonists:
            antag_onstage_count = len(onstage.get(antag, []))
            ratio = antag_onstage_count / n if n > 0 else 0
            if ratio < 0.08:
                antag_penalties += 1
                findings.append({
                    'message': f"Antagonist '{antag}' on-stage in only {antag_onstage_count}/{n} scenes ({ratio:.0%}, ideal >= 8%)",
                    'severity': 'minor',
                })
        if antag_penalties > 0:
            antag_score = max(0.0, 1.0 - antag_penalties * 0.3)
    else:
        antag_score = 0.7  # No antagonist data — neutral

    # --- 3. Presence gaps ---
    gap_score = 1.0
    tracked_chars = pov_characters | antagonists
    gap_penalties = 0
    threshold = max(1, int(n * 0.20))

    for ch in tracked_chars:
        # Combine on_stage and POV indices
        present_indices = set(onstage.get(ch, []))
        for idx, sid in enumerate(scene_ids):
            if scenes_map[sid].get('pov', '').strip() == ch:
                present_indices.add(idx)

        if not present_indices:
            continue

        sorted_indices = sorted(present_indices)
        # Check gap before first appearance
        max_gap = sorted_indices[0]
        # Check gaps between appearances
        for i in range(1, len(sorted_indices)):
            gap = sorted_indices[i] - sorted_indices[i - 1] - 1
            if gap > max_gap:
                max_gap = gap
        # Check gap after last appearance
        trailing = n - 1 - sorted_indices[-1]
        if trailing > max_gap:
            max_gap = trailing

        if max_gap > threshold:
            gap_penalties += 1
            findings.append({
                'message': f"'{ch}' absent for {max_gap} consecutive scenes (threshold: {threshold})",
                'severity': 'minor',
            })

    if tracked_chars:
        gap_score = max(0.0, 1.0 - gap_penalties / len(tracked_chars))

    # --- 4. Mention-to-onstage ratio ---
    ratio_score = 1.0
    ratio_flags = 0
    for ch in set(list(mentions.keys()) + list(onstage.keys())):
        mention_count = len(mentions.get(ch, []))
        onstage_count = len(onstage.get(ch, []))
        if mention_count > 5 and onstage_count < mention_count * 0.30:
            ratio_flags += 1
            findings.append({
                'message': f"'{ch}' mentioned in {mention_count} scenes but on-stage in only {onstage_count} (<30%)",
                'severity': 'minor',
            })

    total_chars = len(set(list(mentions.keys()) + list(onstage.keys())))
    if total_chars > 0 and ratio_flags > 0:
        ratio_score = max(0.0, 1.0 - ratio_flags / total_chars)

    # Composite
    score = (pov_score + antag_score + gap_score + ratio_score) / 4.0
    score = max(0.0, min(1.0, score))

    return {'score': score, 'findings': findings}


# ---------------------------------------------------------------------------
# MICE Health
# ---------------------------------------------------------------------------

def score_mice_health(scenes_map, intent_map):
    """Score MICE thread effectiveness — close ratio, dormancy, type balance, resolution positioning.

    Args:
        scenes_map: dict from _read_csv_as_map on scenes.csv
        intent_map: dict from _read_csv_as_map on scene-intent.csv

    Returns:
        {'score': float 0-1, 'findings': [...]}
    """
    findings = []

    # Sort scenes by seq
    def _seq(item):
        try:
            return int(item[1].get('seq', 0))
        except (ValueError, TypeError):
            return 0

    ordered = sorted(scenes_map.items(), key=_seq)
    scene_ids = [sid for sid, _ in ordered]
    n = len(scene_ids)

    if n == 0:
        return {'score': 0.0, 'findings': [{'message': 'No scenes found', 'severity': 'important'}]}

    # Parse all mice_threads entries
    # Track per thread: open_idx, close_idx, mention_indices, type
    threads = {}  # thread_name -> {'open': idx|None, 'close': idx|None, 'mentions': [idx], 'type': str}

    for idx, sid in enumerate(scene_ids):
        intent = intent_map.get(sid, {})
        mice_str = intent.get('mice_threads', '').strip()
        if not mice_str:
            continue
        for entry in mice_str.split(';'):
            entry = entry.strip()
            if not entry:
                continue
            if entry.startswith('+'):
                tag = entry[1:]
                thread_type = tag.split(':')[0] if ':' in tag else 'unknown'
                if tag not in threads:
                    threads[tag] = {'open': idx, 'close': None, 'mentions': [idx], 'type': thread_type}
                else:
                    threads[tag]['mentions'].append(idx)
                    if threads[tag]['open'] is None:
                        threads[tag]['open'] = idx
            elif entry.startswith('-'):
                tag = entry[1:]
                thread_type = tag.split(':')[0] if ':' in tag else 'unknown'
                if tag not in threads:
                    threads[tag] = {'open': None, 'close': idx, 'mentions': [idx], 'type': thread_type}
                else:
                    threads[tag]['close'] = idx
                    threads[tag]['mentions'].append(idx)
            else:
                # Plain mention (no +/-)
                tag = entry
                thread_type = tag.split(':')[0] if ':' in tag else 'unknown'
                if tag not in threads:
                    threads[tag] = {'open': None, 'close': None, 'mentions': [idx], 'type': thread_type}
                else:
                    threads[tag]['mentions'].append(idx)

    total_threads = len(threads)
    if total_threads == 0:
        return {'score': 0.5, 'findings': [{'message': 'No MICE threads found', 'severity': 'minor'}]}

    # --- 1. Close ratio ---
    opened = sum(1 for t in threads.values() if t['open'] is not None)
    closed = sum(1 for t in threads.values() if t['close'] is not None)
    close_ratio = closed / opened if opened > 0 else 0.0

    if close_ratio < 0.5:
        findings.append({
            'message': f"Only {closed}/{opened} threads closed ({close_ratio:.0%}) — many unresolved threads",
            'severity': 'important',
        })

    # --- 2. Dormancy ---
    dormant_count = 0
    for tag, info in threads.items():
        mention_list = sorted(set(info['mentions']))
        if len(mention_list) >= 2:
            max_gap = 0
            for i in range(1, len(mention_list)):
                gap = mention_list[i] - mention_list[i - 1]
                if gap > max_gap:
                    max_gap = gap
            if max_gap > 10:
                dormant_count += 1
                findings.append({
                    'message': f"Thread '{tag}' dormant for {max_gap} scenes",
                    'severity': 'minor',
                })

    dormancy_score = max(0.0, 1.0 - dormant_count / total_threads * 2)

    # --- 3. Type balance ---
    type_counts = {}
    for info in threads.values():
        t = info['type']
        type_counts[t] = type_counts.get(t, 0) + 1

    type_count = len(type_counts)
    type_balance = min(1.0, type_count / 3)

    if type_count == 1 and total_threads > 5:
        dominant_type = list(type_counts.keys())[0]
        findings.append({
            'message': f"All {total_threads} threads are type '{dominant_type}' — no MICE variety",
            'severity': 'minor',
        })

    # --- 4. Resolution positioning ---
    cutoff = int(n * 0.70)  # final 30% starts here
    if closed > 0:
        late_closures = sum(
            1 for t in threads.values()
            if t['close'] is not None and t['close'] >= cutoff
        )
        resolution_score = late_closures / closed
    else:
        resolution_score = 0.0

    if closed > 0 and resolution_score < 0.3:
        findings.append({
            'message': f"Only {resolution_score:.0%} of threads close in the final 30% of scenes",
            'severity': 'minor',
        })

    # Composite
    score = close_ratio * 0.35 + dormancy_score * 0.25 + type_balance * 0.20 + resolution_score * 0.20
    score = max(0.0, min(1.0, score))

    return {'score': score, 'findings': findings}


# ---------------------------------------------------------------------------
# Knowledge Chain
# ---------------------------------------------------------------------------

def score_knowledge_chain(scenes_map, briefs_map):
    """Score knowledge flow through scenes — coverage, fact utilization, density.

    Args:
        scenes_map: dict from _read_csv_as_map on scenes.csv
        briefs_map: dict from _read_csv_as_map on scene-briefs.csv

    Returns:
        {'score': float 0-1, 'findings': [...]}
    """
    findings = []

    # Sort scenes by seq
    def _seq(item):
        try:
            return int(item[1].get('seq', 0))
        except (ValueError, TypeError):
            return 0

    ordered = sorted(scenes_map.items(), key=_seq)
    scene_ids = [sid for sid, _ in ordered]
    n = len(scene_ids)

    if n == 0:
        return {'score': 0.0, 'findings': [{'message': 'No scenes found', 'severity': 'important'}]}

    # --- 1. Coverage ---
    has_kin = 0
    has_kout = 0
    all_facts = {}  # fact -> list of scene indices

    for idx, sid in enumerate(scene_ids):
        brief = briefs_map.get(sid, {})
        kin = brief.get('knowledge_in', '').strip()
        kout = brief.get('knowledge_out', '').strip()
        if kin:
            has_kin += 1
            for fact in kin.split(';'):
                fact = fact.strip()
                if fact:
                    if fact not in all_facts:
                        all_facts[fact] = []
                    all_facts[fact].append(idx)
        if kout:
            has_kout += 1
            for fact in kout.split(';'):
                fact = fact.strip()
                if fact:
                    if fact not in all_facts:
                        all_facts[fact] = []
                    all_facts[fact].append(idx)

    coverage_in = has_kin / n if n > 0 else 0.0
    coverage_out = has_kout / n if n > 0 else 0.0
    coverage = (coverage_in + coverage_out) / 2.0

    if coverage < 0.3:
        findings.append({
            'message': f"Low knowledge coverage: {has_kin}/{n} scenes have knowledge_in, {has_kout}/{n} have knowledge_out",
            'severity': 'important',
        })

    # --- 2. Fact utilization ---
    total_facts = len(all_facts)
    reused_facts = sum(1 for indices in all_facts.values() if len(indices) >= 2)
    utilization = reused_facts / total_facts if total_facts > 0 else 0.0

    if total_facts >= 10 and utilization < 0.3:
        findings.append({
            'message': f"Low fact utilization: only {reused_facts}/{total_facts} facts appear in 2+ scenes",
            'severity': 'minor',
        })

    # --- 3. Backstory check ---
    if scene_ids:
        first_sid = scene_ids[0]
        first_brief = briefs_map.get(first_sid, {})
        first_kin = first_brief.get('knowledge_in', '').strip()
        if first_kin:
            first_facts = [f.strip() for f in first_kin.split(';') if f.strip()]
            if len(first_facts) > 5:
                findings.append({
                    'message': f"Scene 1 knowledge_in has {len(first_facts)} facts — possible backstory dump",
                    'severity': 'minor',
                })

    # --- 4. Fact density ---
    density = min(1.0, total_facts / (n * 0.5)) if n > 0 else 0.0

    # Composite
    score = coverage * 0.4 + utilization * 0.35 + density * 0.25
    score = max(0.0, min(1.0, score))

    return {'score': score, 'findings': findings}


# ---------------------------------------------------------------------------
# Function Variety
# ---------------------------------------------------------------------------

def score_function_variety(intent_map, briefs_map):
    """Score variety of scene functions — action/sequel balance, outcome variety, turning point variety.

    Args:
        intent_map: dict from _read_csv_as_map on scene-intent.csv
        briefs_map: dict from _read_csv_as_map on scene-briefs.csv

    Returns:
        {'score': float 0-1, 'findings': [...]}
    """
    findings = []

    scene_ids = sorted(intent_map.keys())
    n = len(scene_ids)

    if n == 0:
        return {'score': 0.0, 'findings': [{'message': 'No scenes found', 'severity': 'important'}]}

    # --- 1. Action/sequel balance ---
    action_count = 0
    sequel_count = 0
    for sid in scene_ids:
        intent = intent_map[sid]
        as_type = intent.get('action_sequel', '').strip().lower()
        if as_type == 'action':
            action_count += 1
        elif as_type == 'sequel':
            sequel_count += 1

    typed_total = action_count + sequel_count
    if typed_total > 0:
        action_ratio = action_count / typed_total
        type_balance = max(0.0, 1.0 - abs(action_ratio - 0.5) * 2)
        if action_ratio > 0.8:
            findings.append({
                'message': f"Action-heavy: {action_count}/{typed_total} scenes are action ({action_ratio:.0%})",
                'severity': 'minor',
            })
        elif action_ratio < 0.2:
            findings.append({
                'message': f"Sequel-heavy: {sequel_count}/{typed_total} scenes are sequel ({1-action_ratio:.0%})",
                'severity': 'minor',
            })
    else:
        type_balance = 0.5  # No data — neutral

    # --- 2. Outcome variety (Shannon entropy) ---
    outcome_freq = {}
    for sid in scene_ids:
        brief = briefs_map.get(sid, {})
        outcome = brief.get('outcome', '').strip().lower()
        if outcome:
            outcome_freq[outcome] = outcome_freq.get(outcome, 0) + 1

    outcome_total = sum(outcome_freq.values())
    if outcome_total > 0 and len(outcome_freq) > 1:
        entropy = 0.0
        for count in outcome_freq.values():
            p = count / outcome_total
            if p > 0:
                entropy -= p * math.log2(p)
        max_entropy = math.log2(len(outcome_freq))
        outcome_variety = entropy / max_entropy if max_entropy > 0 else 0.0

        # Check dominant outcome
        max_outcome_count = max(outcome_freq.values())
        dominant_ratio = max_outcome_count / outcome_total
        if dominant_ratio > 0.60:
            dominant = [k for k, v in outcome_freq.items() if v == max_outcome_count][0]
            findings.append({
                'message': f"Dominant outcome '{dominant}' in {max_outcome_count}/{outcome_total} scenes ({dominant_ratio:.0%})",
                'severity': 'minor',
            })
    elif outcome_total > 0:
        outcome_variety = 0.0  # Only one distinct outcome
    else:
        outcome_variety = 0.5  # No data — neutral

    # --- 3. Turning point variety ---
    tp_freq = {}
    for sid in scene_ids:
        intent = intent_map[sid]
        tp = intent.get('turning_point', '').strip().lower()
        if tp:
            tp_freq[tp] = tp_freq.get(tp, 0) + 1

    tp_total = sum(tp_freq.values())
    if tp_total > 0 and len(tp_freq) > 1:
        max_tp_count = max(tp_freq.values())
        dominant_tp_ratio = max_tp_count / tp_total
        tp_variety = 1.0 - dominant_tp_ratio

        if dominant_tp_ratio > 0.75:
            dominant_tp = [k for k, v in tp_freq.items() if v == max_tp_count][0]
            findings.append({
                'message': f"Dominant turning point '{dominant_tp}' in {max_tp_count}/{tp_total} scenes ({dominant_tp_ratio:.0%})",
                'severity': 'minor',
            })
    elif tp_total > 0:
        tp_variety = 0.0  # Only one type
    else:
        tp_variety = 0.5  # No data — neutral

    # Composite
    score = type_balance * 0.35 + outcome_variety * 0.35 + tp_variety * 0.30
    score = max(0.0, min(1.0, score))

    return {'score': score, 'findings': findings}


# ---------------------------------------------------------------------------
# Orchestrator constants
# ---------------------------------------------------------------------------

_DEFAULT_WEIGHTS = {
    'arc_completeness': 1.0,
    'thematic_concentration': 0.8,
    'pacing_shape': 1.0,
    'character_presence': 0.7,
    'mice_health': 0.6,
    'knowledge_chain': 0.5,
    'function_variety': 0.7,
    'completeness': 0.3,
}

_DIMENSION_LABELS = {
    'arc_completeness': 'Arc Completeness',
    'thematic_concentration': 'Thematic Concentration',
    'pacing_shape': 'Pacing Shape',
    'character_presence': 'Character Presence',
    'mice_health': 'MICE Thread Health',
    'knowledge_chain': 'Knowledge Chain',
    'function_variety': 'Scene Function Variety',
    'completeness': 'Structural Completeness',
}

_DIMENSION_TARGETS = {
    'arc_completeness': 0.80,
    'thematic_concentration': 0.60,
    'pacing_shape': 0.75,
    'character_presence': 0.70,
    'mice_health': 0.60,
    'knowledge_chain': 0.60,
    'function_variety': 0.65,
    'completeness': 0.80,
}


# ---------------------------------------------------------------------------
# Orchestrator
# ---------------------------------------------------------------------------

def structural_score(ref_dir, weights=None):
    """Run all 8 structural scoring dimensions and compute weighted average.

    Args:
        ref_dir: path to reference directory containing scenes.csv,
                 scene-intent.csv, scene-briefs.csv, and optionally characters.csv
        weights: optional dict overriding _DEFAULT_WEIGHTS

    Returns:
        {
            'overall_score': float,
            'dimensions': [{'name', 'label', 'score', 'weight', 'target', 'findings'}, ...],
            'top_findings': [{'dimension', 'dimension_score', 'message'}, ...],
        }
    """
    w = dict(_DEFAULT_WEIGHTS)
    if weights:
        w.update(weights)

    # Read CSVs once
    scenes_map = _read_csv_as_map(os.path.join(ref_dir, 'scenes.csv'))
    intent_map = _read_csv_as_map(os.path.join(ref_dir, 'scene-intent.csv'))
    briefs_path = os.path.join(ref_dir, 'scene-briefs.csv')
    briefs_map = _read_csv_as_map(briefs_path) if os.path.exists(briefs_path) else {}

    # Call all 8 scoring functions
    results = {
        'completeness': score_completeness(scenes_map, intent_map, briefs_map),
        'thematic_concentration': score_thematic_concentration(intent_map),
        'pacing_shape': score_pacing(scenes_map, intent_map, briefs_map),
        'arc_completeness': score_arcs(scenes_map, intent_map),
        'character_presence': score_character_presence(scenes_map, intent_map, ref_dir),
        'mice_health': score_mice_health(scenes_map, intent_map),
        'knowledge_chain': score_knowledge_chain(scenes_map, briefs_map),
        'function_variety': score_function_variety(intent_map, briefs_map),
    }

    # Build dimensions list and compute weighted average
    dimensions = []
    weighted_sum = 0.0
    total_weight = 0.0
    top_findings = []

    for name in _DEFAULT_WEIGHTS:
        result = results[name]
        dim_weight = w.get(name, 0.0)
        dim_score = result['score']
        dim_findings = result.get('findings', [])

        dimensions.append({
            'name': name,
            'label': _DIMENSION_LABELS.get(name, name),
            'score': dim_score,
            'weight': dim_weight,
            'target': _DIMENSION_TARGETS.get(name, 0.70),
            'findings': dim_findings,
        })

        weighted_sum += dim_score * dim_weight
        total_weight += dim_weight

        # Collect important findings
        for f in dim_findings:
            if f.get('severity') == 'important':
                top_findings.append({
                    'dimension': name,
                    'dimension_score': dim_score,
                    'message': f['message'],
                })

    overall = weighted_sum / total_weight if total_weight > 0 else 0.0

    return {
        'overall_score': max(0.0, min(1.0, overall)),
        'dimensions': dimensions,
        'top_findings': top_findings,
    }


# ---------------------------------------------------------------------------
# Score persistence
# ---------------------------------------------------------------------------

def save_structural_scores(report, project_dir):
    """Save structural scores to a timestamped CSV and update latest.

    Args:
        report: dict from structural_score()
        project_dir: path to project root

    Returns:
        path to the saved timestamped CSV file
    """
    scores_dir = os.path.join(project_dir, 'working', 'scores')
    os.makedirs(scores_dir, exist_ok=True)

    timestamp = datetime.datetime.now().strftime('%Y%m%d-%H%M%S')
    filename = f'structural-{timestamp}.csv'
    filepath = os.path.join(scores_dir, filename)

    lines = ['dimension|score|target|weight']
    for dim in report['dimensions']:
        lines.append(f"{dim['name']}|{dim['score']:.4f}|{dim['target']:.2f}|{dim['weight']:.1f}")
    lines.append(f"overall|{report['overall_score']:.4f}|0.70|1.0")

    content = '\n'.join(lines) + '\n'

    with open(filepath, 'w') as f:
        f.write(content)

    # Overwrite latest
    latest_path = os.path.join(scores_dir, 'structural-latest.csv')
    with open(latest_path, 'w') as f:
        f.write(content)

    return filepath


def load_previous_scores(project_dir):
    """Load the most recent structural scores.

    Args:
        project_dir: path to project root

    Returns:
        dict mapping dimension name to score, or None if no previous scores
    """
    latest_path = os.path.join(project_dir, 'working', 'scores', 'structural-latest.csv')
    if not os.path.isfile(latest_path):
        return None

    result = {}
    with open(latest_path, 'r') as f:
        header = None
        for line in f:
            line = line.strip()
            if not line:
                continue
            if header is None:
                header = line.split('|')
                continue
            parts = line.split('|')
            if len(parts) >= 2:
                name = parts[0]
                try:
                    score = float(parts[1])
                except ValueError:
                    continue
                result[name] = score

    return result if result else None


# ---------------------------------------------------------------------------
# Output formatters
# ---------------------------------------------------------------------------

def format_scorecard(report, previous=None):
    """Format a structural score report as a terminal-printable scorecard.

    Args:
        report: dict from structural_score()
        previous: optional dict from load_previous_scores() for delta display

    Returns:
        str with bar chart and scores, including deltas when previous is provided
    """
    lines = []
    lines.append(f"Structural Score: {report['overall_score']:.2f} / 1.00")

    # Show overall delta if previous exists
    if previous is not None and 'overall' in previous:
        delta = report['overall_score'] - previous['overall']
        if abs(delta) < 0.005:
            lines[-1] += '  no change'
        elif delta > 0:
            lines[-1] += f'  +{delta:.2f} \u25b2'
        else:
            lines[-1] += f'  {delta:.2f} \u25bc'

    lines.append('')

    for dim in report['dimensions']:
        label = dim['label'].ljust(24)
        score = dim['score']
        target = dim['target']

        filled = int(round(score * 10))
        empty = 10 - filled
        bar = '\u2588' * filled + '\u2591' * empty

        line = f"  {label}  {score:.2f}  {bar}  (target: {target:.2f}+)"

        if previous is not None and dim['name'] in previous:
            delta = score - previous[dim['name']]
            if abs(delta) < 0.005:
                line += '  no change'
            elif delta > 0:
                line += f'  +{delta:.2f} \u25b2'
            else:
                line += f'  {delta:.2f} \u25bc'

        lines.append(line)

    return '\n'.join(lines)


def format_diagnosis(report, coaching_level='full'):
    """Format structural findings for display, adapted to coaching level.

    Args:
        report: dict from structural_score()
        coaching_level: 'full', 'coach', or 'strict'

    Returns:
        str with formatted findings
    """
    lines = []

    if coaching_level == 'strict':
        lines.append('## Data')
        lines.append('')
        for dim in report['dimensions']:
            if dim['score'] < dim['target']:
                lines.append(f"- {dim['name']}: {dim['score']:.2f} (target: {dim['target']:.2f})")
        if not any(dim['score'] < dim['target'] for dim in report['dimensions']):
            lines.append('All dimensions at or above target.')
        return '\n'.join(lines)

    findings = report.get('top_findings', [])[:5]

    if coaching_level == 'coach':
        lines.append('## Questions to Consider')
        lines.append('')
        for i, f in enumerate(findings, 1):
            lines.append(f"{i}. **{_DIMENSION_LABELS.get(f['dimension'], f['dimension'])}** ({f['dimension_score']:.2f}): {f['message']}")
        if not findings:
            lines.append('No critical findings to discuss.')
        return '\n'.join(lines)

    # full
    lines.append('## Top Findings')
    lines.append('')
    for i, f in enumerate(findings, 1):
        lines.append(f"{i}. **{_DIMENSION_LABELS.get(f['dimension'], f['dimension'])}** ({f['dimension_score']:.2f}): {f['message']}")
    if not findings:
        lines.append('No critical findings detected.')
    return '\n'.join(lines)
