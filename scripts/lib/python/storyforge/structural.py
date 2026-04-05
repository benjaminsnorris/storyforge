"""Structural scoring engine — story quality from CSV data.

Deterministic, no API calls. Reads scene CSVs and produces quantified
scores across 8 dimensions with diagnostic findings.

Each score_* function returns:
    {'score': float (0-1), 'findings': [{'message': str, 'scene_id': str, ...}]}
"""

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
