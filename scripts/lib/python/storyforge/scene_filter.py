"""Scene list building and filtering — replaces scripts/lib/scene-filter.sh.

Provides a single source of truth for building ordered scene lists and
filtering by --scenes, --act, --from-seq, etc.
"""

import os

from storyforge.common import log
from storyforge.csv_cli import DELIMITER


# Minimum word count for a scene to be included
MIN_SCENE_WORDS = int(os.environ.get('STORYFORGE_MIN_SCENE_WORDS', '50'))


def _read_csv_rows(csv_path: str) -> list[dict[str, str]]:
    """Read a pipe-delimited CSV into a list of dicts.

    Strips ``\\r`` so CRLF line endings and stray carriage returns embedded
    by awk-based CSV edits never propagate into field values.
    """
    if not os.path.isfile(csv_path):
        return []
    with open(csv_path, newline='', encoding='utf-8') as f:
        raw = f.read().replace('\r\n', '\n').replace('\r', '')
    lines = [l for l in raw.splitlines() if l.strip()]
    if not lines:
        return []
    headers = lines[0].split(DELIMITER)
    rows = []
    for line in lines[1:]:
        fields = line.split(DELIMITER)
        row = {headers[i]: (fields[i] if i < len(fields) else '') for i in range(len(headers))}
        rows.append(row)
    return rows


def build_scene_list(metadata_csv: str) -> list[str]:
    """Build ordered scene list from metadata CSV.

    Returns scene IDs sorted by seq, excluding cut/merged scenes
    and scenes below MIN_SCENE_WORDS.
    """
    if not os.path.isfile(metadata_csv):
        log(f'ERROR: Metadata CSV not found: {metadata_csv}')
        log("Run 'storyforge scenes' to create scene metadata.")
        raise SystemExit(1)

    rows = _read_csv_rows(metadata_csv)
    scenes_with_seq: list[tuple[str, int]] = []
    skipped = 0

    for row in rows:
        sid = row.get('id', '')
        if not sid:
            continue

        status = row.get('status', '')
        if status in ('cut', 'merged'):
            skipped += 1
            continue

        wc_str = row.get('word_count', '')
        if wc_str:
            try:
                wc = int(wc_str)
                if 0 < wc < MIN_SCENE_WORDS:
                    skipped += 1
                    continue
            except ValueError:
                pass

        seq_str = row.get('seq', '')
        try:
            seq = int(seq_str) if seq_str else 0
        except ValueError:
            seq = 0
        scenes_with_seq.append((sid, seq))

    scenes_with_seq.sort(key=lambda x: x[1])
    result = [s[0] for s in scenes_with_seq]

    if not result:
        log(f'ERROR: No scenes found in {metadata_csv}')
        raise SystemExit(1)

    skip_note = f' (skipped {skipped} cut/stub)' if skipped else ''
    log(f'Found {len(result)} scenes in metadata.csv{skip_note}')
    return result


def _get_field(metadata_csv: str, sid: str, field: str) -> str:
    """Read a single field from the CSV for a given scene ID."""
    rows = _read_csv_rows(metadata_csv)
    for row in rows:
        if row.get('id', '') == sid:
            return row.get(field, '')
    return ''


def apply_scene_filter(
    metadata_csv: str,
    all_scene_ids: list[str],
    mode: str,
    value: str | None = None,
    value2: str | None = None,
) -> list[str]:
    """Filter scene IDs by mode.

    Modes: all, scenes, single, act, from_seq, range
    """
    if mode == 'all':
        return list(all_scene_ids)

    if mode == 'scenes':
        # Comma-separated list
        requested = [s.strip() for s in (value or '').split(',')]
        valid = set(all_scene_ids)
        result = []
        for req in requested:
            if req in valid:
                result.append(req)
            else:
                log(f"WARNING: Scene '{req}' not found in metadata.csv, skipping")
        if not result:
            log('ERROR: None of the requested scenes were found')
            raise SystemExit(1)
        return result

    if mode == 'single':
        if value not in all_scene_ids:
            log(f"ERROR: Scene '{value}' not found in metadata.csv")
            raise SystemExit(1)
        return [value]

    if mode == 'act':
        # Read all rows once for efficiency
        rows = _read_csv_rows(metadata_csv)
        id_to_part = {r['id']: r.get('part', '') for r in rows}
        result = [sid for sid in all_scene_ids if id_to_part.get(sid) == value]
        if not result:
            log(f'ERROR: No scenes found in act/part {value}')
            raise SystemExit(1)
        log(f'Filtered to {len(result)} scenes in act/part {value}')
        return result

    if mode == 'from_seq':
        # Parse N or N-M range
        val = value or ''
        if '-' in val:
            parts = val.split('-', 1)
            seq_start, seq_end = int(parts[0]), int(parts[1])
        else:
            seq_start = int(val)
            seq_end = None

        rows = _read_csv_rows(metadata_csv)
        id_to_seq = {}
        for r in rows:
            try:
                id_to_seq[r['id']] = int(r.get('seq', '0'))
            except ValueError:
                pass

        result = []
        for sid in all_scene_ids:
            seq = id_to_seq.get(sid, 0)
            if seq >= seq_start:
                if seq_end is None or seq <= seq_end:
                    result.append(sid)

        if not result:
            range_str = f'{seq_start}-{seq_end}' if seq_end else f'>= {seq_start}'
            log(f'ERROR: No scenes found with seq {range_str}')
            raise SystemExit(1)

        range_str = f'{seq_start}-{seq_end}' if seq_end else f'>= {seq_start}'
        log(f'Filtered to {len(result)} scenes with seq {range_str}')
        return result

    if mode == 'range':
        # Inclusive range by position
        result = []
        in_range = False
        for sid in all_scene_ids:
            if sid == value:
                in_range = True
            if in_range:
                result.append(sid)
            if sid == value2:
                break

        if not result:
            log(f'ERROR: Could not find range {value} to {value2}')
            raise SystemExit(1)
        return result

    log(f'ERROR: Unknown filter mode: {mode}')
    raise SystemExit(1)
