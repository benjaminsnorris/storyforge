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
