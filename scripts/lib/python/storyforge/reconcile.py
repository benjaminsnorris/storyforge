"""Post-extraction reconciliation — build registries and normalize fields.

Domains:
- characters, locations (after Phase 1)
- values, mice-threads (after Phase 2)
- knowledge, outcomes (after Phase 3)
"""

import csv
import os
import re

from storyforge.elaborate import (
    _read_csv, _read_csv_as_map, _write_csv, _FILE_MAP, DELIMITER,
)

# ============================================================================
# Outcome normalization (deterministic — no API call)
# ============================================================================

_OUTCOME_ENUM = {'yes', 'yes-but', 'no', 'no-and'}
_OUTCOME_RE = re.compile(
    r'^\[?(yes-but|no-and|yes|no)\b',
    re.IGNORECASE,
)


def normalize_outcomes(raw: str) -> str:
    """Extract enum value from a possibly-elaborated outcome string.

    Handles: 'yes-but — long elaboration', '[no-and]', 'yes', etc.
    Returns the raw string unchanged if no enum is recognized.
    """
    raw = raw.strip()
    if not raw:
        return raw
    m = _OUTCOME_RE.match(raw)
    if m:
        return m.group(1).lower()
    return raw


def reconcile_outcomes(ref_dir: str) -> int:
    """Normalize all outcome fields in scene-briefs.csv to enum values.

    Returns the number of rows changed.
    """
    briefs_path = os.path.join(ref_dir, 'scene-briefs.csv')
    rows = _read_csv(briefs_path)
    if not rows:
        return 0

    changed = 0
    for row in rows:
        raw = row.get('outcome', '')
        normalized = normalize_outcomes(raw)
        if normalized != raw:
            row['outcome'] = normalized
            changed += 1

    if changed:
        _write_csv(briefs_path, rows, _FILE_MAP['scene-briefs.csv'])
    return changed
