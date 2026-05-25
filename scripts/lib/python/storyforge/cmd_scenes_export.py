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
from storyforge.csv_cli import get_field, list_ids
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
    """Export scene data from the three CSVs to a single markdown file.

    Sections whose CSV has no row for a given scene are omitted entirely
    rather than rendered as a header followed by all-empty field lines.
    At early elaboration stages most scenes only have a Structural row,
    and dragging the reader through 25 blank lines per scene to find the
    one populated section makes the review file unreadable.
    """
    meta_csv = os.path.join(project_dir, 'reference', 'scenes.csv')
    all_ids = build_scene_list(meta_csv)
    scene_ids = apply_scene_filter(meta_csv, all_ids, filter_mode,
                                   filter_value, filter_value2)

    sections = get_sections(project_dir)

    # Pre-compute which scene_ids exist in each section's CSV so we can skip
    # rendering empty sections per scene. list_ids reads the file once each.
    section_ids = {
        csv_rel: set(list_ids(os.path.join(project_dir, csv_rel)))
        for _, csv_rel, _ in sections
    }

    lines = []
    for i, sid in enumerate(scene_ids):
        if i > 0:
            lines.append('')
        lines.append(f'## {sid}')

        for section_name, csv_rel, fields in sections:
            if sid not in section_ids[csv_rel]:
                continue  # no row in this CSV — skip section entirely
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
# Derived markdown renderings for the structural-anchor tier
# ============================================================================

def export_spine_md(project_dir: str, output_path: str | None = None) -> str:
    """Render reference/spine.csv as a markdown review file.

    Returns the output path. Skips rendering if spine.csv is absent.
    Output defaults to reference/spine.md.
    """
    spine_csv = os.path.join(project_dir, 'reference', 'spine.csv')
    if not os.path.isfile(spine_csv):
        return ''
    if output_path is None:
        output_path = os.path.join(project_dir, 'reference', 'spine.md')

    headers = _read_csv_headers(spine_csv)
    fields = [h for h in headers if h and h != 'id']

    lines = ['# Spine', '']
    lines.append('<!-- Derived from reference/spine.csv. Edit the CSV; this '
                 'file is regenerated by `storyforge sync`. -->')
    lines.append('')

    with open(spine_csv, encoding='utf-8') as f:
        raw = f.read().replace('\r\n', '\n').replace('\r', '')
    rows = raw.splitlines()[1:]  # skip header
    for i, row in enumerate(rows):
        cells = row.split('|')
        rowdict = dict(zip(headers, cells))
        sid = rowdict.get('id', '?')
        if i > 0:
            lines.append('')
        lines.append(f'## {sid}')
        lines.append('')
        for field in fields:
            value = rowdict.get(field, '')
            lines.append(f'{field}: {value}')
    lines.append('')

    os.makedirs(os.path.dirname(output_path), exist_ok=True)
    with open(output_path, 'w', encoding='utf-8') as f:
        f.write('\n'.join(lines))

    log(f'Rendered {len(rows)} spine events to {output_path}')
    return output_path


def export_architecture_md(project_dir: str, output_path: str | None = None) -> str:
    """Render reference/architecture.csv as a markdown review file.

    Same shape as export_spine_md. Skips if architecture.csv is absent.
    """
    arch_csv = os.path.join(project_dir, 'reference', 'architecture.csv')
    if not os.path.isfile(arch_csv):
        return ''
    if output_path is None:
        output_path = os.path.join(project_dir, 'reference', 'architecture.md')

    headers = _read_csv_headers(arch_csv)
    fields = [h for h in headers if h and h != 'id']

    lines = ['# Architecture', '']
    lines.append('<!-- Derived from reference/architecture.csv. Edit the CSV; '
                 'this file is regenerated by `storyforge sync`. -->')
    lines.append('')

    with open(arch_csv, encoding='utf-8') as f:
        raw = f.read().replace('\r\n', '\n').replace('\r', '')
    rows = raw.splitlines()[1:]
    for i, row in enumerate(rows):
        cells = row.split('|')
        rowdict = dict(zip(headers, cells))
        sid = rowdict.get('id', '?')
        if i > 0:
            lines.append('')
        lines.append(f'## {sid}')
        lines.append('')
        for field in fields:
            value = rowdict.get(field, '')
            lines.append(f'{field}: {value}')
    lines.append('')

    os.makedirs(os.path.dirname(output_path), exist_ok=True)
    with open(output_path, 'w', encoding='utf-8') as f:
        f.write('\n'.join(lines))

    log(f'Rendered {len(rows)} architecture anchors to {output_path}')
    return output_path


def export_outline_md(project_dir: str, output_path: str | None = None) -> str:
    """Render the expanding outline — the `summary` column from spine.csv,
    architecture.csv, and scenes.csv — into a single read-only markdown
    file with three numbered sections.

    Returns the output path. Renders even when one or two of the source
    CSVs are absent (the missing sections render as empty lists with a
    note). Returns '' only when all three sources are absent.

    Output defaults to reference/outline.md. The file is one-way — the
    author edits summaries in the CSVs; sync regenerates this file.
    """
    spine_csv = os.path.join(project_dir, 'reference', 'spine.csv')
    arch_csv = os.path.join(project_dir, 'reference', 'architecture.csv')
    scenes_csv = os.path.join(project_dir, 'reference', 'scenes.csv')
    if not any(os.path.isfile(p) for p in (spine_csv, arch_csv, scenes_csv)):
        return ''
    if output_path is None:
        output_path = os.path.join(project_dir, 'reference', 'outline.md')

    lines: list[str] = ['# Story outline', '']
    lines.append('<!-- Derived from the `summary` column of spine.csv, '
                 'architecture.csv, and scenes.csv. Edit the CSVs; this '
                 'file is regenerated by `storyforge sync`. -->')
    lines.append('')

    for label, csv_path in (
        ('Spine', spine_csv),
        ('Architecture', arch_csv),
        ('Scenes', scenes_csv),
    ):
        lines.append(f'## {label}')
        lines.append('')
        if not os.path.isfile(csv_path):
            lines.append('_(no source file yet)_')
            lines.append('')
            continue
        rows = _outline_rows(csv_path)
        if not rows:
            lines.append('_(no rows yet)_')
            lines.append('')
            continue
        for seq, summary in rows:
            marker = str(seq) if seq is not None else '?'
            lines.append(f'{marker}. {summary or "_(missing)_"}')
        lines.append('')

    os.makedirs(os.path.dirname(output_path), exist_ok=True)
    with open(output_path, 'w', encoding='utf-8') as f:
        f.write('\n'.join(lines))
    log(f'Rendered outline to {output_path}')
    return output_path


def _outline_rows(csv_path: str) -> list[tuple[int | None, str]]:
    """Return [(seq, summary), ...] sorted by seq for an outline-eligible CSV.

    `seq` is None when the source row's seq cell is missing/non-integer.
    Such rows sort after rows with a parseable seq (stable within group).
    Empty summary cells are passed through; the renderer marks them.
    Rows whose column count doesn't match the header are logged + skipped.
    """
    headers = _read_csv_headers(csv_path)
    if 'summary' not in headers:
        return []
    with open(csv_path, encoding='utf-8') as f:
        raw = f.read().replace('\r\n', '\n').replace('\r', '')
    out: list[tuple[int | None, str]] = []
    for lineno, line in enumerate(raw.splitlines()[1:], start=2):
        if not line.strip():
            continue
        cells = line.split('|')
        if len(cells) != len(headers):
            log(f'WARNING: {csv_path}:{lineno} has {len(cells)} fields, '
                f'expected {len(headers)}; row skipped')
            continue
        row = dict(zip(headers, cells))
        seq_str = row.get('seq', '').strip()
        seq: int | None
        try:
            seq = int(seq_str) if seq_str else None
        except ValueError:
            seq = None
        out.append((seq, row.get('summary', '').strip()))
    # Stable sort: parseable seqs first (ascending), then unparseable.
    out.sort(key=lambda x: (x[0] is None, x[0] if x[0] is not None else 0))
    return out


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

    # Derived structural-anchor renderings. Silently skip if the
    # underlying CSV doesn't exist yet (project hasn't reached that level).
    if args.output is None:
        export_spine_md(project_dir)
        export_architecture_md(project_dir)
