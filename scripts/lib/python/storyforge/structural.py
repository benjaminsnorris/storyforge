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
