"""storyforge scenes-import — Import edited markdown back into scene CSVs.

Parses a markdown file produced by scenes-export, diffs against the current
CSV values, and updates only fields that changed. The field set per section
is read from each CSV's header row at runtime, so any columns present in the
CSVs (including graphic-novel additions) are imported.

Usage:
    storyforge scenes-import                      # Import from default path
    storyforge scenes-import --dry-run            # Show changes without writing
    storyforge scenes-import --input /tmp/out.md  # Custom input path
"""

import argparse
import os
import re

from storyforge.cmd_scenes_export import DEFAULT_OUTPUT_PATH, get_sections
from storyforge.common import detect_project_root, install_signal_handlers, log
from storyforge.csv_cli import get_field, list_ids, update_field


# ============================================================================
# Markdown parser
# ============================================================================

def parse_markdown(text, section_map=None):
    """Parse scenes-review markdown into a nested dict.

    `section_map` is {section_name: (csv_rel, set(known_field_names))} — if
    provided, only those section names are recognized and only the listed
    fields are treated as fields. When None, every `### Name` opens a section
    and every `field: value` line is a field — useful as a generic parser or
    in tests where the CSVs aren't on hand.

    A line that looks like `field: value` but whose `field` isn't in the
    section's known set is logged as a WARNING and skipped (it does NOT get
    merged into the previous field's value — that would silently corrupt
    CSV cells when an author types review notes into the MD). True multi-
    line field values still work as long as the continuation line does not
    start with `[a-z_]+:`.

    Returns: {scene_id: {section_name: {field: value}}}
    """
    scenes = {}
    current_scene = None
    current_section = None
    last_field = None

    for line in text.splitlines():
        # Scene heading
        if line.startswith('## '):
            current_scene = line[3:].strip()
            scenes[current_scene] = {}
            current_section = None
            last_field = None
            continue

        # Section heading
        if line.startswith('### '):
            section_name = line[4:].strip()
            if current_scene and (section_map is None or section_name in section_map):
                current_section = section_name
                scenes[current_scene][current_section] = {}
                last_field = None
            continue

        # Blank line
        if not line.strip():
            continue

        # Field line or continuation
        if current_scene and current_section:
            # Try to match "field_name: value"
            match = re.match(r'^([a-z_]+):\s?(.*)', line)
            if match:
                field_name = match.group(1)
                if section_map is None or field_name in section_map[current_section][1]:
                    value = match.group(2)
                    scenes[current_scene][current_section][field_name] = value
                    last_field = field_name
                else:
                    # field: value-shaped line, but the field isn't known.
                    # Don't merge into last_field — that silently rewrites
                    # whatever the previous real field was. Warn + skip.
                    log(f'WARNING: {current_scene} / {current_section}: '
                        f'unknown field "{field_name}" — line skipped')
                    last_field = None
            elif last_field is not None:
                # Continuation line — append to previous field
                prev = scenes[current_scene][current_section][last_field]
                scenes[current_scene][current_section][last_field] = \
                    prev + ' ' + line.strip()

    return scenes


# ============================================================================
# Import logic
# ============================================================================

def import_scenes(project_dir, input_path, dry_run=False):
    """Import edited markdown back into CSVs. Returns list of changes.

    Each change is a tuple: (scene_id, csv_rel, field, old_value, new_value).

    Raises RuntimeError when the markdown references a scene_id that does
    not exist in any of the three CSVs — silently skipping such IDs would
    let an author "rename" a scene by editing its `## heading` while leaving
    the canonical CSV row unchanged (a phantom rename). The user must edit
    CSVs directly to rename.
    """
    with open(input_path, encoding='utf-8') as f:
        text = f.read()

    # Build section_map from the project's actual CSV headers so columns added
    # by graphic-novel mode (or future schema changes) are recognized.
    section_map = {
        name: (csv_rel, set(fields))
        for name, csv_rel, fields in get_sections(project_dir)
    }

    parsed = parse_markdown(text, section_map)

    # Build lookup of valid scene IDs per CSV. Also build the union for the
    # rename-detection check below.
    csv_ids = {}
    all_known_ids = set()
    for section_name, (csv_rel, _fields) in section_map.items():
        csv_path = os.path.join(project_dir, csv_rel)
        ids = set(list_ids(csv_path))
        csv_ids[csv_rel] = ids
        all_known_ids |= ids

    unknown_ids = sorted(sid for sid in parsed if sid not in all_known_ids)
    if unknown_ids:
        raise RuntimeError(
            f'Markdown references scene ID(s) not present in any CSV: '
            f'{", ".join(unknown_ids)}. '
            'To rename a scene, edit the CSV rows directly — renaming in '
            'the MD alone would leave the canonical data untouched.'
        )

    changes = []
    for scene_id, sections in parsed.items():
        for section_name, fields in sections.items():
            csv_rel, _known = section_map[section_name]
            csv_path = os.path.join(project_dir, csv_rel)

            # A scene may legitimately be missing from one CSV (e.g. no
            # intent row yet) but present in another. Skip silently in that
            # case — there's nothing to update on that side.
            if scene_id not in csv_ids.get(csv_rel, set()):
                continue

            for field_name, new_value in fields.items():
                old_value = get_field(csv_path, scene_id, field_name)
                if new_value != old_value:
                    changes.append((scene_id, csv_rel, field_name,
                                    old_value, new_value))
                    if not dry_run:
                        update_field(csv_path, scene_id, field_name, new_value)

    return changes


# ============================================================================
# Argument parsing
# ============================================================================

def parse_args(argv):
    parser = argparse.ArgumentParser(
        prog='storyforge scenes-import',
        description='Import edited markdown back into scene CSVs.',
    )
    parser.add_argument('--input', type=str, default=None,
                        help='Input path (default: reference/scenes-review.md)')
    parser.add_argument('--dry-run', action='store_true',
                        help='Show changes without writing')
    return parser.parse_args(argv)


# ============================================================================
# Main
# ============================================================================

def main(argv=None):
    args = parse_args(argv or [])
    install_signal_handlers()
    project_dir = detect_project_root()

    input_path = args.input or os.path.join(project_dir, DEFAULT_OUTPUT_PATH)
    if not os.path.isfile(input_path):
        log(f'ERROR: Input file not found: {input_path}')
        log("Run 'storyforge scenes-export' first.")
        raise SystemExit(1)

    try:
        changes = import_scenes(project_dir, input_path, dry_run=args.dry_run)
    except RuntimeError as e:
        log(f'ERROR: {e}')
        raise SystemExit(1)

    if not changes:
        log('No changes detected.')
    else:
        for scene_id, csv_rel, field, old_val, new_val in changes:
            old_display = old_val if old_val else '(empty)'
            new_display = new_val if new_val else '(empty)'
            log(f'  {scene_id}: {field} "{old_display}" -> "{new_display}"')

        action = 'Would update' if args.dry_run else 'Updated'
        log(f'{action} {len(changes)} field(s).')
