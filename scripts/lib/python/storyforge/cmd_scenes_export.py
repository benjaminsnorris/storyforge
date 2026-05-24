"""storyforge scenes-export — Export scene data to a reviewable markdown file.

Merges scenes.csv, scene-intent.csv, and scene-briefs.csv into a single
markdown file with one ## heading per scene, ordered by sequence number.

The field set per section is read from each CSV's header row at runtime, so
the export round-trips whatever columns are present — including the
graphic-novel additions (target_pages, panel_breakdown, etc.).

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
# Section definitions
# ============================================================================

# Sections that participate in the round-trip. Field lists are read from the
# CSV's own header row by get_sections() — *do not* hardcode them here.
SECTION_SPECS = [
    ('Structural', 'reference/scenes.csv'),
    ('Intent', 'reference/scene-intent.csv'),
    ('Brief', 'reference/scene-briefs.csv'),
]

DEFAULT_OUTPUT_PATH = os.path.join('reference', 'scenes-review.md')


def _read_csv_headers(csv_path):
    """Return the column names from a pipe-delimited CSV's header row.

    Returns [] if the file is missing or empty.
    """
    if not os.path.isfile(csv_path):
        return []
    with open(csv_path, encoding='utf-8') as f:
        first = f.readline().rstrip('\r\n')
    if not first:
        return []
    return [h.strip() for h in first.split('|')]


def get_sections(project_dir):
    """Return [(section_name, csv_rel, fields)] for the round-trip sections.

    `fields` is read from each CSV's header row (excluding the 'id' key),
    so any columns present in the CSV — including medium-specific additions —
    are round-tripped through export/import.
    """
    out = []
    for name, csv_rel in SECTION_SPECS:
        csv_path = os.path.join(project_dir, csv_rel)
        headers = _read_csv_headers(csv_path)
        fields = [h for h in headers if h and h != 'id']
        out.append((name, csv_rel, fields))
    return out


# ============================================================================
# Export logic
# ============================================================================

def export_scenes(project_dir, output_path, filter_mode='all',
                  filter_value=None, filter_value2=None):
    """Export scene data from the three CSVs to a single markdown file."""
    meta_csv = os.path.join(project_dir, 'reference', 'scenes.csv')
    all_ids = build_scene_list(meta_csv)
    scene_ids = apply_scene_filter(meta_csv, all_ids, filter_mode,
                                   filter_value, filter_value2)

    sections = get_sections(project_dir)

    lines = []
    for i, sid in enumerate(scene_ids):
        if i > 0:
            lines.append('')
        lines.append(f'## {sid}')

        for section_name, csv_rel, fields in sections:
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
                        help='Output path (default: reference/scenes-review.md)')
    return parser.parse_args(argv)


# ============================================================================
# Main
# ============================================================================

def main(argv=None):
    args = parse_args(argv or [])
    install_signal_handlers()
    project_dir = detect_project_root()

    output = args.output or os.path.join(project_dir, DEFAULT_OUTPUT_PATH)
    mode, value, value2 = resolve_filter_args(args)
    export_scenes(project_dir, output, mode, value, value2)
