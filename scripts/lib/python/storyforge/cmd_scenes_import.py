"""storyforge scenes-import — Import edited markdown back into scene CSVs.

Parses a markdown file produced by scenes-export, diffs against the current
CSV values, and updates only fields that changed.

Usage:
    storyforge scenes-import                      # Import from default path
    storyforge scenes-import --dry-run            # Show changes without writing
    storyforge scenes-import --input /tmp/out.md  # Custom input path
"""

import argparse
import os
import re

from storyforge.common import detect_project_root, install_signal_handlers, log
from storyforge.csv_cli import get_field, list_ids, update_field


# ============================================================================
# Column definitions (must match cmd_scenes_export.py)
# ============================================================================

STRUCTURAL_FIELDS = [
    'seq', 'title', 'part', 'pov', 'location', 'timeline_day',
    'time_of_day', 'duration', 'type', 'status', 'word_count', 'target_words',
]

INTENT_FIELDS = [
    'function', 'action_sequel', 'emotional_arc', 'value_at_stake',
    'value_shift', 'turning_point', 'characters', 'on_stage', 'mice_threads',
]

BRIEF_FIELDS = [
    'goal', 'conflict', 'outcome', 'crisis', 'decision', 'knowledge_in',
    'knowledge_out', 'key_actions', 'key_dialogue', 'emotions', 'motifs',
    'subtext', 'continuity_deps', 'has_overflow', 'physical_state_in',
    'physical_state_out',
]

# Section name -> (csv relative path, known field names)
SECTION_MAP = {
    'Structural': ('reference/scenes.csv', set(STRUCTURAL_FIELDS)),
    'Intent': ('reference/scene-intent.csv', set(INTENT_FIELDS)),
    'Brief': ('reference/scene-briefs.csv', set(BRIEF_FIELDS)),
}


# ============================================================================
# Markdown parser
# ============================================================================

def parse_markdown(text):
    """Parse scenes-review markdown into a nested dict.

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
            if current_scene and section_name in SECTION_MAP:
                current_section = section_name
                scenes[current_scene][current_section] = {}
                last_field = None
            continue

        # Blank line
        if not line.strip():
            continue

        # Field line or continuation
        if current_scene and current_section:
            known_fields = SECTION_MAP[current_section][1]
            # Try to match "field_name: value"
            match = re.match(r'^([a-z_]+):\s?(.*)', line)
            if match and match.group(1) in known_fields:
                field_name = match.group(1)
                value = match.group(2)
                scenes[current_scene][current_section][field_name] = value
                last_field = field_name
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

    Each change is a tuple: (scene_id, csv_rel, field, old_value, new_value)
    """
    with open(input_path, encoding='utf-8') as f:
        text = f.read()

    parsed = parse_markdown(text)
    changes = []

    # Build lookup of valid scene IDs per CSV
    csv_ids = {}
    for section_name, (csv_rel, _fields) in SECTION_MAP.items():
        csv_path = os.path.join(project_dir, csv_rel)
        csv_ids[csv_rel] = set(list_ids(csv_path))

    for scene_id, sections in parsed.items():
        for section_name, fields in sections.items():
            csv_rel, _known = SECTION_MAP[section_name]
            csv_path = os.path.join(project_dir, csv_rel)

            if scene_id not in csv_ids.get(csv_rel, set()):
                log(f'WARNING: Scene {scene_id} not found in {csv_rel}, skipping')
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
    parser.add_argument('--input', '-i', type=str, default=None,
                        help='Input path (default: working/scenes-review.md)')
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

    input_path = args.input or os.path.join(project_dir, 'working',
                                            'scenes-review.md')
    if not os.path.isfile(input_path):
        log(f'ERROR: Input file not found: {input_path}')
        log("Run 'storyforge scenes-export' first.")
        raise SystemExit(1)

    changes = import_scenes(project_dir, input_path, dry_run=args.dry_run)

    if not changes:
        log('No changes detected.')
    else:
        for scene_id, csv_rel, field, old_val, new_val in changes:
            old_display = old_val if old_val else '(empty)'
            new_display = new_val if new_val else '(empty)'
            log(f'  {scene_id}: {field} "{old_display}" -> "{new_display}"')

        action = 'Would update' if args.dry_run else 'Updated'
        log(f'{action} {len(changes)} field(s).')
