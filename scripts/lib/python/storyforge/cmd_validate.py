"""storyforge validate — Run structural and schema validation on scene CSVs.

Usage:
    storyforge validate                  # Both structural + schema (default)
    storyforge validate --no-schema      # Structural only
    storyforge validate --json           # Output as JSON
    storyforge validate --quiet          # Exit code only (0=pass, 1=fail)
"""

import argparse
import json
import os
import sys

from storyforge.common import detect_project_root


def parse_args(argv):
    parser = argparse.ArgumentParser(prog='storyforge validate',
                                     description='Run structural and schema validation')
    parser.add_argument('--no-schema', action='store_true', help='Skip schema validation')
    parser.add_argument('--structural', action='store_true', help='Include structural scoring')
    parser.add_argument('--json', action='store_true', dest='json_output', help='Output as JSON')
    parser.add_argument('--quiet', action='store_true', help='Exit code only')
    return parser.parse_args(argv)


def main(argv=None):
    args = parse_args(argv or [])
    project_dir = detect_project_root()
    ref_dir = os.path.join(project_dir, 'reference')

    if not os.path.isfile(os.path.join(ref_dir, 'scenes.csv')):
        print(f'Error: No scenes.csv found in {ref_dir}. Is this an elaboration pipeline project?')
        sys.exit(1)

    from storyforge.elaborate import validate_structure
    from storyforge.schema import validate_schema, validate_knowledge_granularity

    structural = validate_structure(ref_dir)

    schema = None
    if not args.no_schema:
        schema = validate_schema(ref_dir, project_dir)

    knowledge = None
    knowledge_path = os.path.join(ref_dir, 'knowledge.csv')
    if os.path.isfile(knowledge_path):
        knowledge = validate_knowledge_granularity(ref_dir, project_dir)

    structural_scores = None
    scores_previous = None
    if args.structural:
        from storyforge.structural import (
            structural_score, save_structural_scores,
            load_previous_scores, generate_structural_proposals,
        )
        scores_previous = load_previous_scores(project_dir)
        structural_scores = structural_score(ref_dir)
        save_structural_scores(structural_scores, project_dir)
        generate_structural_proposals(structural_scores, os.path.join(project_dir, 'working', 'scores'))

    combined = {
        'structural': structural,
        'schema': schema,
        'knowledge': knowledge,
        'scores': structural_scores,
        'scores_previous': scores_previous,
    }

    if args.json_output:
        print(json.dumps(combined))
    elif not args.quiet:
        _print_human_readable(combined)

    # Exit code
    structural_ok = structural['passed']
    schema_ok = schema is None or schema['failed'] == 0
    sys.exit(0 if structural_ok and schema_ok else 1)


def _print_human_readable(combined):
    r = combined['structural']
    schema = combined['schema']
    knowledge = combined.get('knowledge')

    total = len(r['checks'])
    fail_count = len(r['failures'])

    print('--- Structural validation ---')
    if r['passed']:
        print(f'  Passed ({total} checks, 0 failures)')
    else:
        print(f'  Failed ({total} checks, {fail_count} failure(s)):')
        for f in r['failures']:
            severity = f.get('severity', 'blocking')
            scene = f.get('scene_id', '')
            prefix = f'    [{severity}]'
            if scene:
                prefix += f' {scene}:'
            print(f"{prefix} {f['message']}")

    if schema is not None:
        print()
        print('--- Schema validation ---')
        if schema['failed'] == 0:
            print(f'  Passed ({schema["passed"]} cells validated, {schema["skipped"]} skipped)')
        else:
            print(f'  Failed ({schema["passed"]} passed, {schema["failed"]} failed, {schema["skipped"]} skipped)')
            by_file: dict[str, list] = {}
            for e in schema['errors']:
                by_file.setdefault(e['file'], []).append(e)
            for fname, errs in sorted(by_file.items()):
                print(f'  {fname}:')
                for e in errs:
                    if e['constraint'] == 'enum':
                        allowed = ', '.join(e['allowed'])
                        print(f'    {e["row"]} | {e["column"]}: "{e["value"]}" — not in ({allowed})')
                    elif e['constraint'] == 'registry':
                        unresolved = ', '.join(e.get('unresolved', [e['value']]))
                        print(f'    {e["row"]} | {e["column"]}: "{unresolved}" — not in {e["registry"]}')
                    elif e['constraint'] == 'integer':
                        print(f'    {e["row"]} | {e["column"]}: "{e["value"]}" — expected integer')
                    elif e['constraint'] == 'boolean':
                        print(f'    {e["row"]} | {e["column"]}: "{e["value"]}" — expected true/false')
                    elif e['constraint'] == 'mice':
                        for p in e.get('problems', []):
                            print(f'    {e["row"]} | {e["column"]}: "{p["entry"]}" — {p["reason"]}')
                    elif e['constraint'] == 'scene_ids':
                        unresolved = ', '.join(e.get('unresolved', []))
                        print(f'    {e["row"]} | {e["column"]}: "{unresolved}" — not in scenes.csv')

    if knowledge is not None:
        print()
        print('--- Knowledge granularity ---')
        tf = knowledge['total_facts']
        ts = knowledge['total_scenes']
        fps = knowledge['facts_per_scene']
        warnings = knowledge['warnings']
        health = 'healthy' if not warnings else 'has warnings'
        print(f'  {tf} facts across {ts} scenes ({fps} facts/scene) — {health}')
        if warnings:
            print()
            print('  Warnings:')
            long_names = [w for w in warnings if w['type'] == 'long_name']
            too_many = [w for w in warnings if w['type'] == 'too_many_new_facts']
            if long_names:
                print('    Long fact names (may be too granular):')
                for w in long_names:
                    print(f'      {w["id"]} ({w["word_count"]} words)')
            if too_many:
                print('    Scenes with 5+ new facts:')
                for w in too_many:
                    print(f'      {w["scene_id"]}: {w["new_fact_count"]} new facts')

    scores = combined.get('scores')
    if scores is not None:
        prev = combined.get('scores_previous')
        print()
        print('--- Structural scoring ---')
        overall_line = f'  Overall: {scores["overall_score"]:.2f} / 1.00'
        if prev is not None and 'overall' in prev:
            delta = scores['overall_score'] - prev['overall']
            if abs(delta) < 0.005:
                overall_line += '  no change'
            elif delta > 0:
                overall_line += f'  +{delta:.2f} \u25b2'
            else:
                overall_line += f'  {delta:.2f} \u25bc'
        print(overall_line)
        print()
        for dim in scores['dimensions']:
            bar_full = int(dim['score'] * 10)
            bar = '\u2588' * bar_full + '\u2591' * (10 - bar_full)
            status = '' if dim['score'] >= dim['target'] else '(below target)'
            line = f'  {dim["label"]:24s} {dim["score"]:.2f}  {bar}  {status}'
            if prev is not None and dim['name'] in prev:
                delta = dim['score'] - prev[dim['name']]
                if abs(delta) < 0.005:
                    line += '  no change'
                elif delta > 0:
                    line += f'  +{delta:.2f} \u25b2'
                else:
                    line += f'  {delta:.2f} \u25bc'
            print(line)
        if scores['top_findings']:
            print()
            print('  Top findings:')
            for f in scores['top_findings'][:5]:
                print(f'    {f["dimension"]}: {f["message"]}')

        # MICE dormancy recommendation
        dormant = []
        for dim in scores['dimensions']:
            for f in dim.get('findings', []):
                msg = f.get('message', '') if isinstance(f, dict) else str(f)
                if 'dormant' in msg.lower():
                    dormant.append(msg)
        if dormant:
            print()
            print(f'  MICE dormancy: {len(dormant)} threads need intermediate mentions.')
            print('  Run: storyforge elaborate --mice-fill')
        low_dims = [d for d in scores['dimensions'] if d['score'] < d['target']]
        brief_dims = [d for d in low_dims if d['name'] not in ('mice_health', 'pacing_shape', 'function_variety')]
        if brief_dims:
            names = ', '.join(d['label'] for d in brief_dims)
            print()
            print(f'  Below target: {names}')
            print('  Run: storyforge hone --diagnose (for detailed field-level issues)')
