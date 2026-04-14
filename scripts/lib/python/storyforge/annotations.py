"""Reader annotation processing — fetch, reconcile, route, and exemplar promotion.

Fetches reader annotations from the Bookshelf API, maintains a stateful CSV
at working/annotations.csv, routes annotations by color intent into the
revision pipeline, and promotes strong passages as exemplars.
"""

import csv
import os
from datetime import datetime, timezone


# ============================================================================
# Color intent mapping
# ============================================================================

COLOR_LABELS = {
    'pink': 'Needs Revision',
    'orange': 'Cut / Reconsider',
    'blue': 'Research Needed',
    'green': 'Strong Passage',
    'yellow': 'Important',
}

COLOR_TO_FIX_LOCATION = {
    'pink': 'craft',
    'orange': 'structural',
    'blue': 'research',
    'green': 'protection',
    'yellow': 'craft',
}

ANNOTATIONS_HEADER = [
    'id', 'scene_id', 'chapter', 'color', 'color_label', 'text', 'note',
    'reader', 'created_at', 'status', 'fix_location', 'fetched_at',
]


def route_annotation(ann: dict) -> tuple[str, str]:
    """Determine status and fix_location for an annotation based on color and note.

    Args:
        ann: Annotation dict with at least 'color' and 'note' keys.

    Returns:
        Tuple of (status, fix_location).
    """
    color = ann.get('color', 'yellow')
    note = ann.get('note', '') or ''
    fix_location = COLOR_TO_FIX_LOCATION.get(color, 'craft')

    if color == 'yellow' and not note.strip():
        return 'skipped', fix_location

    return 'new', fix_location
