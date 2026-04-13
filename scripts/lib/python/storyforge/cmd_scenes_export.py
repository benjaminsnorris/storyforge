"""storyforge scenes-export — Export scene data to a reviewable markdown file.

Merges scenes.csv, scene-intent.csv, and scene-briefs.csv into a single
markdown file with one ## heading per scene, ordered by sequence number.

Usage:
    storyforge scenes-export                      # Export all scenes
    storyforge scenes-export --act 2              # Export only Act 2
    storyforge scenes-export --scenes a,b,c       # Export specific scenes
    storyforge scenes-export --from-seq 10-20     # Export sequence range
    storyforge scenes-export --output /tmp/out.md # Custom output path
"""

import argparse
import os

from storyforge.cli import add_scene_filter_args, resolve_filter_args
from storyforge.common import detect_project_root, install_signal_handlers, log
from storyforge.csv_cli import get_field
from storyforge.scene_filter import apply_scene_filter, build_scene_list


# ============================================================================
# Column definitions
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

SECTIONS = [
    ('Structural', 'reference/scenes.csv', STRUCTURAL_FIELDS),
    ('Intent', 'reference/scene-intent.csv', INTENT_FIELDS),
    ('Brief', 'reference/scene-briefs.csv', BRIEF_FIELDS),
]


# ============================================================================
# Export logic
# ============================================================================

def export_scenes(project_dir, output_path, filter_mode='all',
                  filter_value=None, filter_value2=None):
    """Export scene data from three CSVs to a single markdown file."""
    meta_csv = os.path.join(project_dir, 'reference', 'scenes.csv')
    all_ids = build_scene_list(meta_csv)
    scene_ids = apply_scene_filter(meta_csv, all_ids, filter_mode,
                                   filter_value, filter_value2)

    lines = []
    for i, sid in enumerate(scene_ids):
        if i > 0:
            lines.append('')
        lines.append(f'## {sid}')

        for section_name, csv_rel, fields in SECTIONS:
            csv_path = os.path.join(project_dir, csv_rel)
            lines.append('')
            lines.append(f'### {section_name}')
            for field in fields:
                value = get_field(csv_path, sid, field)
                lines.append(f'{field}: {value}')

    lines.append('')  # trailing newline

    os.makedirs(os.path.dirname(output_path), exist_ok=True)
    with open(output_path, 'w', encoding='utf-8') as f:
        f.write('\n'.join(lines))

    log(f'Exported {len(scene_ids)} scenes to {output_path}')


# ============================================================================
# Argument parsing
# ============================================================================

def parse_args(argv):
    parser = argparse.ArgumentParser(
        prog='storyforge scenes-export',
        description='Export scene data to a reviewable markdown file.',
    )
    add_scene_filter_args(parser)
    parser.add_argument('--output', '-o', type=str, default=None,
                        help='Output path (default: working/scenes-review.md)')
    return parser.parse_args(argv)


# ============================================================================
# Main
# ============================================================================

def main(argv=None):
    args = parse_args(argv or [])
    install_signal_handlers()
    project_dir = detect_project_root()

    output = args.output or os.path.join(project_dir, 'working', 'scenes-review.md')
    mode, value, value2 = resolve_filter_args(args)
    export_scenes(project_dir, output, mode, value, value2)
