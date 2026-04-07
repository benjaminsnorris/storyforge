"""Scene list building and filtering — replaces scripts/lib/scene-filter.sh.

Provides a single source of truth for building ordered scene lists and
filtering by --scenes, --act, --from-seq, etc.
"""

import os

from storyforge.common import log
from storyforge.csv_cli import get_field, list_ids


# Minimum word count for a scene to be included
MIN_SCENE_WORDS = int(os.environ.get('STORYFORGE_MIN_SCENE_WORDS', '50'))


def build_scene_list(metadata_csv: str) -> list[str]:
    """Build ordered scene list from metadata CSV.

    Returns scene IDs sorted by seq, excluding cut/merged scenes
    and scenes below MIN_SCENE_WORDS.
    """
    if not os.path.isfile(metadata_csv):
        log(f'ERROR: Metadata CSV not found: {metadata_csv}')
        log("Run 'storyforge scenes' to create scene metadata.")
        raise SystemExit(1)

    # Read all IDs and their seq values for sorting
    all_ids = list_ids(metadata_csv)
    scenes_with_seq: list[tuple[str, int]] = []
    skipped = 0

    for sid in all_ids:
        status = get_field(metadata_csv, sid, 'status')
        if status in ('cut', 'merged'):
            skipped += 1
            continue

        wc_str = get_field(metadata_csv, sid, 'word_count')
        if wc_str:
            try:
                wc = int(wc_str)
                if 0 < wc < MIN_SCENE_WORDS:
                    skipped += 1
                    continue
            except ValueError:
                pass

        seq_str = get_field(metadata_csv, sid, 'seq')
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
        result = []
        for sid in all_scene_ids:
            part = get_field(metadata_csv, sid, 'part')
            if part == value:
                result.append(sid)
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

        result = []
        for sid in all_scene_ids:
            seq_str = get_field(metadata_csv, sid, 'seq')
            if seq_str:
                try:
                    seq = int(seq_str)
                    if seq >= seq_start:
                        if seq_end is None or seq <= seq_end:
                            result.append(sid)
                except ValueError:
                    pass

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
