"""storyforge score (graphic-novel mode) — Deterministic craft scoring for GN projects.

Runs all six deterministic GN craft scorers against drafted panel scripts,
writes per-scene JSON output and a summary CSV, and prints a human-readable
table sorted by overall score (lowest first — most attention needed).

No API calls — all scorers are fully deterministic.

Usage (identical CLI surface to novel-mode score):
    storyforge score                      # score all drafted scenes
    storyforge score scene-id             # score one scene
    storyforge score --scenes a,b,c       # multiple scenes
    storyforge score --principles X,Y     # only certain principles
    storyforge score --dry-run            # show what would be scored
"""

import argparse
import json
import os
import sys
from datetime import datetime, timezone

from storyforge.common import (
    detect_project_root, log, set_log_file, install_signal_handlers,
    get_medium, get_plugin_dir,
)
from storyforge.script_format import parse_script
from storyforge.scoring_gn import score_scene, PRINCIPLES
from storyforge.csv_cli import get_field, get_row, update_field
from storyforge.scene_filter import build_scene_list, apply_scene_filter


# ---------------------------------------------------------------------------
# Arg parsing
# ---------------------------------------------------------------------------

def parse_args(argv):
    parser = argparse.ArgumentParser(
        prog='storyforge score',
        description='Score GN panel scripts against six craft principles.',
    )
    parser.add_argument('positional', nargs='*', default=[],
                        help='Scene ID(s) to score')
    parser.add_argument('--dry-run', action='store_true',
                        help='Show what would be scored without writing output')
    parser.add_argument('--scenes', type=str, default=None,
                        help='Comma-separated scene IDs')
    parser.add_argument('--act', '--part', type=str, default=None,
                        help='Score all scenes in act/part N')
    parser.add_argument('--from-seq', type=str, default=None,
                        help='Start from sequence number (N or N-M range)')
    parser.add_argument('--principles', type=str, default=None,
                        help='Comma-separated principles to score '
                             '(default: all six)')
    return parser.parse_args(argv)


# ---------------------------------------------------------------------------
# CSV row helper (mirrors cmd_write_gn._row_to_dict)
# ---------------------------------------------------------------------------

def _row_to_dict(csv_path, row_id):
    """Read a CSV row by ID and return as a dict. Returns {} if not found."""
    if not os.path.isfile(csv_path):
        return {}
    with open(csv_path, newline='', encoding='utf-8') as f:
        raw = f.read().replace('\r\n', '\n').replace('\r', '')
    lines = raw.splitlines()
    if not lines:
        return {}
    headers = lines[0].split('|')
    for line in lines[1:]:
        fields = line.split('|')
        if fields and fields[0] == row_id:
            return dict(zip(headers, fields))
    return {}


# ---------------------------------------------------------------------------
# Weights loading
# ---------------------------------------------------------------------------

def _load_weights(project_dir, plugin_dir):
    """Load craft weights. Project-local file takes precedence over default.

    Returns dict of principle -> weight (float, normalised so sum == 1.0).
    Falls back to equal weights if no file found.
    """
    # Try project-local overrides first
    local_path = os.path.join(project_dir, 'working', 'craft-weights.csv')
    default_path = os.path.join(plugin_dir, 'references', 'default-craft-weights-gn.csv')

    weights_path = None
    if os.path.isfile(local_path):
        weights_path = local_path
    elif os.path.isfile(default_path):
        weights_path = default_path

    if not weights_path:
        # Fallback: equal weights
        return {p: 1.0 / len(PRINCIPLES) for p in PRINCIPLES}

    raw = {}
    try:
        with open(weights_path, encoding='utf-8') as f:
            lines = f.read().replace('\r\n', '\n').replace('\r', '').splitlines()
        if not lines:
            raise ValueError('empty weights file')
        headers = lines[0].split('|')
        p_idx = headers.index('principle') if 'principle' in headers else 1
        w_idx = headers.index('weight') if 'weight' in headers else 2
        for line in lines[1:]:
            fields = line.split('|')
            if len(fields) > max(p_idx, w_idx):
                p = fields[p_idx].strip()
                w_str = fields[w_idx].strip()
                if p and w_str:
                    try:
                        raw[p] = float(w_str)
                    except ValueError:
                        pass
    except Exception as e:
        log(f'WARNING: Failed to load weights from {weights_path}: {e}')
        return {p: 1.0 / len(PRINCIPLES) for p in PRINCIPLES}

    # Keep only GN principles, fill missing with 1.0
    result = {}
    for p in PRINCIPLES:
        result[p] = raw.get(p, 1.0)

    total = sum(result.values())
    if total > 0:
        result = {p: w / total for p, w in result.items()}
    else:
        result = {p: 1.0 / len(PRINCIPLES) for p in PRINCIPLES}

    return result


# ---------------------------------------------------------------------------
# Per-scene scoring
# ---------------------------------------------------------------------------

def _score_one_scene(scene_id, project_dir, briefs_csv, principles_filter, weights):
    """Score a single scene. Returns the output dict, or None on failure."""
    scene_path = os.path.join(project_dir, 'scenes', f'{scene_id}.md')
    if not os.path.isfile(scene_path):
        log(f'  SKIP {scene_id}: scene file not found')
        return None

    with open(scene_path, encoding='utf-8') as f:
        script_text = f.read()

    try:
        parsed = parse_script(script_text)
    except Exception as e:
        log(f'  WARNING: parse_script failed for {scene_id}: {e}')
        parsed = {'pages': []}

    brief_row = _row_to_dict(briefs_csv, scene_id)
    has_brief = bool(brief_row)

    # Run scorers (filtered or all)
    active_principles = principles_filter if principles_filter else list(PRINCIPLES)

    # score_scene returns all six; we filter after
    all_scores = score_scene(scene_id, parsed, brief_row, script_text)

    scores_out = {}
    all_findings = []
    weighted_sum = 0.0
    weight_used = 0.0

    for p in active_principles:
        if p == 'brief_fidelity' and not has_brief:
            log(f'  NOTE {scene_id}: no brief row — skipping brief_fidelity')
            continue
        result = all_scores.get(p)
        if result is None:
            continue
        scores_out[p] = {
            'score': result['score'],
            'findings': result.get('findings', []),
        }
        all_findings.extend(result.get('findings', []))
        w = weights.get(p, 0.0)
        weighted_sum += result['score'] * w
        weight_used += w

    overall = weighted_sum / weight_used if weight_used > 0 else 0.0

    return {
        'scene_id': scene_id,
        'scored_at': datetime.now(timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ'),
        'scores': scores_out,
        'overall_score': round(overall, 4),
        'findings': all_findings,
    }


# ---------------------------------------------------------------------------
# Summary CSV
# ---------------------------------------------------------------------------

def _write_summary_csv(results, output_dir, principles_filter):
    """Write working/scores/latest/summary.csv."""
    active = list(principles_filter) if principles_filter else list(PRINCIPLES)
    header = 'scene_id|overall_score|' + '|'.join(active)
    lines = [header]
    for r in results:
        parts = [r['scene_id'], f"{r['overall_score']:.4f}"]
        for p in active:
            s = r['scores'].get(p, {}).get('score', '')
            parts.append(f'{s:.4f}' if isinstance(s, float) else '')
        lines.append('|'.join(parts))
    path = os.path.join(output_dir, 'summary.csv')
    with open(path, 'w', encoding='utf-8') as f:
        f.write('\n'.join(lines) + '\n')
    return path


# ---------------------------------------------------------------------------
# Human-readable table
# ---------------------------------------------------------------------------

def _print_summary_table(results, principles_filter):
    """Print sorted table (lowest overall first — most attention needed)."""
    active = list(principles_filter) if principles_filter else list(PRINCIPLES)
    sorted_results = sorted(results, key=lambda r: r['overall_score'])

    # Column widths
    id_width = max(len('scene'), max(len(r['scene_id']) for r in results))
    col_width = 7  # e.g. '0.8234'

    # Header
    cols = ['scene'.ljust(id_width), 'overall'.rjust(col_width)]
    for p in active:
        short = p[:col_width].rjust(col_width)
        cols.append(short)
    print('')
    print('  ' + '  '.join(cols))
    print('  ' + '-' * (id_width + (col_width + 2) * (len(active) + 1)))

    for r in sorted_results:
        row = [r['scene_id'].ljust(id_width),
               f"{r['overall_score']:.4f}".rjust(col_width)]
        for p in active:
            s = r['scores'].get(p, {}).get('score', None)
            val = f'{s:.4f}'.rjust(col_width) if s is not None else '     —'.rjust(col_width)
            row.append(val)
        print('  ' + '  '.join(row))

    print('')
    if results:
        avg = sum(r['overall_score'] for r in results) / len(results)
        print(f'  Average overall: {avg:.4f}  ({len(results)} scenes)')
    print('')


# ---------------------------------------------------------------------------
# Scene resolution
# ---------------------------------------------------------------------------

def _resolve_target_scenes(args, metadata_csv):
    """Resolve which scenes to score, in priority order:
      1. Positional args
      2. --scenes flag
      3. All scenes in metadata (default to all, not just drafted)
    """
    all_ids = build_scene_list(metadata_csv)

    if args.positional:
        # Single or multiple positional args
        mode = 'scenes'
        value = ','.join(args.positional)
    elif args.scenes:
        mode = 'scenes'
        value = args.scenes
    elif args.act:
        mode = 'act'
        value = args.act
    elif hasattr(args, 'from_seq') and args.from_seq:
        mode = 'from_seq'
        value = args.from_seq
    else:
        mode = 'all'
        value = None

    filtered = apply_scene_filter(metadata_csv, all_ids, mode, value)
    return filtered


# ---------------------------------------------------------------------------
# main
# ---------------------------------------------------------------------------

def main(argv=None):
    args = parse_args(argv if argv is not None else sys.argv[1:])

    install_signal_handlers()

    project_dir = detect_project_root()

    # GN guard
    medium = get_medium(project_dir)
    if medium != 'graphic-novel':
        log(f'ERROR: This command is only for graphic-novel projects '
            f'(project.medium = "{medium}").')
        log('For novel projects, use the standard `storyforge score` command.')
        sys.exit(1)

    log(f'Project root: {project_dir}')
    log('Medium: graphic-novel — using GN scoring pipeline')

    plugin_dir = get_plugin_dir()

    # Parse --principles filter
    principles_filter = None
    if args.principles:
        requested = [p.strip() for p in args.principles.split(',') if p.strip()]
        unknown = [p for p in requested if p not in PRINCIPLES]
        if unknown:
            log(f'ERROR: Unknown GN principle(s): {", ".join(unknown)}')
            log(f'Known GN principles: {", ".join(PRINCIPLES)}')
            sys.exit(1)
        principles_filter = requested
        log(f'Filtering to principles: {", ".join(principles_filter)}')

    # Resolve scenes
    metadata_csv = os.path.join(project_dir, 'reference', 'scenes.csv')
    briefs_csv = os.path.join(project_dir, 'reference', 'scene-briefs.csv')

    candidate_ids = _resolve_target_scenes(args, metadata_csv)

    # Filter to only drafted scenes
    scenes_dir = os.path.join(project_dir, 'scenes')
    scene_ids = []
    for sid in candidate_ids:
        status = get_field(metadata_csv, sid, 'status') or ''
        if status != 'drafted':
            log(f'  SKIP {sid}: status is "{status}" (not drafted)')
            continue
        if not os.path.isfile(os.path.join(scenes_dir, f'{sid}.md')):
            log(f'  SKIP {sid}: scene file not found')
            continue
        scene_ids.append(sid)

    if not scene_ids:
        log('ERROR: No drafted scenes found for the selected scope.')
        sys.exit(1)

    log(f'Scenes to score: {len(scene_ids)}')

    # Dry-run: print plan and exit
    if args.dry_run:
        log('DRY RUN — no output files will be written')
        for sid in scene_ids:
            title = get_field(metadata_csv, sid, 'title') or sid
            log(f'  - {sid} ({title})')
        active = principles_filter if principles_filter else list(PRINCIPLES)
        log(f'Principles: {", ".join(active)}')
        return

    # Load weights
    weights = _load_weights(project_dir, plugin_dir)

    # Prepare output directory
    output_dir = os.path.join(project_dir, 'working', 'scores', 'latest')
    os.makedirs(output_dir, exist_ok=True)

    log_dir = os.path.join(project_dir, 'working', 'logs')
    os.makedirs(log_dir, exist_ok=True)

    # Score each scene
    results = []
    for sid in scene_ids:
        log(f'  Scoring {sid}...')
        result = _score_one_scene(sid, project_dir, briefs_csv,
                                  principles_filter, weights)
        if result is None:
            continue

        # Write per-scene JSON
        json_path = os.path.join(output_dir, f'{sid}.json')
        with open(json_path, 'w', encoding='utf-8') as f:
            json.dump(result, f, indent=2)

        results.append(result)
        finding_count = len(result['findings'])
        log(f'  {sid}: overall={result["overall_score"]:.3f}, '
            f'{finding_count} finding(s)')

    if not results:
        log('ERROR: No scenes were successfully scored.')
        sys.exit(1)

    # Write summary CSV
    summary_path = _write_summary_csv(results, output_dir, principles_filter)
    log(f'Summary: {summary_path}')

    # Print human-readable table
    _print_summary_table(results, principles_filter)

    log(f'Scoring complete. Results in {output_dir}')
