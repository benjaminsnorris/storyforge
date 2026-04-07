"""storyforge enrich — Metadata enrichment for Storyforge projects.

Reads scene prose files and uses Claude to extract missing metadata,
populating the CSV files that power the manuscript dashboard.

Usage:
    storyforge enrich                        # All scenes, batch mode (50% off)
    storyforge enrich --direct               # All scenes, real-time parallel
    storyforge enrich --interactive           # All scenes, claude -p mode
    storyforge enrich --scenes 001,002       # Specific scenes only
    storyforge enrich --act 2                # Scenes in act 2 only
    storyforge enrich --fields type,value_at_stake  # Specific fields only
    storyforge enrich --force                # Re-enrich even populated fields
    storyforge enrich --dry-run              # Show what would be enriched
"""

import argparse
import json
import os
import re
import subprocess
import sys
import time

from storyforge.common import (
    detect_project_root, log, read_yaml_field, select_model,
    install_signal_handlers,
)
from storyforge.git import (
    create_branch, ensure_branch_pushed, create_draft_pr,
    update_pr_task, commit_and_push,
)
from storyforge.costs import estimate_cost, check_threshold, print_summary
from storyforge.api import (
    invoke_to_file, extract_text_from_file, submit_batch,
    poll_batch, download_batch_results, extract_usage,
    calculate_cost_from_usage,
)
from storyforge.costs import log_operation


# ============================================================================
# Constants
# ============================================================================

ALL_FIELDS = (
    'type,location,time_of_day,pov,duration,'
    'action_sequel,emotional_arc,value_at_stake,value_shift,turning_point,'
    'characters,on_stage,mice_threads,'
    'goal,conflict,outcome,crisis,decision,'
    'knowledge_in,knowledge_out,key_actions,key_dialogue,emotions,motifs'
)

METADATA_FIELDS = {'pov', 'location', 'time_of_day', 'duration', 'type'}
INTENT_FIELDS = {
    'action_sequel', 'emotional_arc', 'value_at_stake', 'value_shift',
    'turning_point', 'characters', 'on_stage', 'mice_threads',
}
BRIEFS_FIELDS = {
    'goal', 'conflict', 'outcome', 'crisis', 'decision',
    'knowledge_in', 'knowledge_out', 'key_actions', 'key_dialogue',
    'emotions', 'motifs',
}

MIN_WORDS = 50


# ============================================================================
# Helpers
# ============================================================================

def _python_lib():
    from pathlib import Path
    return str(Path(__file__).resolve().parent.parent)


def _csv_for_field(field: str, project_dir: str) -> str:
    """Return the CSV path for a given field."""
    if field in METADATA_FIELDS:
        return os.path.join(project_dir, 'reference', 'scenes.csv')
    elif field in INTENT_FIELDS:
        return os.path.join(project_dir, 'reference', 'scene-intent.csv')
    elif field in BRIEFS_FIELDS:
        return os.path.join(project_dir, 'reference', 'scene-briefs.csv')
    return ''


def _get_csv_field(csv_path: str, scene_id: str, field: str) -> str:
    """Read a single CSV cell."""
    from storyforge.csv_cli import get_field
    try:
        return get_field(csv_path, scene_id, field)
    except Exception:
        return ''


def _update_csv_field(csv_path: str, scene_id: str, field: str, value: str) -> None:
    from storyforge.csv_cli import update_field
    update_field(csv_path, scene_id, field, value)


def _list_csv_ids(csv_path: str) -> list[str]:
    from storyforge.csv_cli import list_ids
    return list_ids(csv_path)


def _get_csv_column(csv_path: str, field: str) -> list[str]:
    from storyforge.csv_cli import get_column
    return get_column(csv_path, field)


def _append_csv_row(csv_path: str, row: str) -> None:
    from storyforge.csv_cli import append_row
    append_row(csv_path, row)


def _word_count(filepath: str) -> int:
    with open(filepath) as f:
        return len(f.read().split())


def _apply_scene_filter(metadata_csv: str, filter_mode: str,
                        filter_value: str = '', project_dir: str = '') -> list[str]:
    """Apply scene filter and return list of scene IDs."""
    from storyforge.elaborate import _read_csv
    rows = _read_csv(metadata_csv)
    # Exclude cut scenes, sort by seq
    active = [r for r in rows if r.get('status', '') != 'cut']
    active.sort(key=lambda r: int(r.get('seq', 0)) if r.get('seq', '').isdigit() else 0)
    all_ids = [r['id'] for r in active]

    if filter_mode == 'all':
        return all_ids
    elif filter_mode == 'scenes':
        selected = {s.strip() for s in filter_value.split(',')}
        return [sid for sid in all_ids if sid in selected]
    elif filter_mode == 'act':
        return [r['id'] for r in active if r.get('part', '') == filter_value]
    elif filter_mode == 'from_seq':
        if '-' in filter_value:
            start, end = filter_value.split('-', 1)
            start_n, end_n = int(start), int(end)
            return [r['id'] for r in active
                    if r.get('seq', '').isdigit() and start_n <= int(r['seq']) <= end_n]
        else:
            start_n = int(filter_value)
            return [r['id'] for r in active
                    if r.get('seq', '').isdigit() and int(r['seq']) >= start_n]
    return all_ids


def _infer_time_of_day(text: str) -> str:
    """Infer time_of_day from keywords in text."""
    lower = text.lower()
    if re.search(r'dawn|sunrise|first light', lower):
        return 'dawn'
    if re.search(r'morning|breakfast|coffee.*woke|alarm clock|a\.m\b', lower):
        return 'morning'
    if re.search(r'afternoon|lunch|midday|noon', lower):
        return 'afternoon'
    if re.search(r'dusk|sunset|twilight|golden hour', lower):
        return 'dusk'
    if re.search(r'evening|dinner|supper|sundown', lower):
        return 'evening'
    if re.search(r'night|midnight|dark.*outside|moonlight|2:[0-9][0-9]\s*a|3:[0-9][0-9]\s*a|lamp.*lit|streetlight', lower):
        return 'night'
    return ''


# ============================================================================
# Argument parsing
# ============================================================================

def parse_args(argv):
    parser = argparse.ArgumentParser(
        prog='storyforge enrich',
        description='Enrich scene metadata by analyzing prose with Claude.',
    )

    # Mode
    mode_group = parser.add_argument_group('mode')
    mode_group.add_argument('--direct', action='store_true',
                            help='Direct API — real-time parallel calls')
    mode_group.add_argument('--interactive', '-i', action='store_true',
                            help='Interactive mode — uses claude -p')

    # Scope
    scope_group = parser.add_argument_group('scope')
    scope_group.add_argument('--scenes', type=str, default=None,
                             help='Enrich specific scenes only (comma-separated)')
    scope_group.add_argument('--act', type=str, default=None,
                             help='Enrich scenes in act/part N only')
    scope_group.add_argument('--from-seq', type=str, default=None,
                             help='Enrich from sequence number N onward (or N-M range)')

    # Options
    parser.add_argument('--parallel', type=int, default=None,
                        help='Concurrent workers (default: 6)')
    parser.add_argument('--fields', type=str, default=ALL_FIELDS,
                        help='Comma-separated fields to enrich (default: all)')
    parser.add_argument('--force', action='store_true',
                        help='Re-enrich scenes that already have data')
    parser.add_argument('--skip-timeline', action='store_true',
                        help='Skip the timeline_day analysis pass')
    parser.add_argument('--skip-dashboard', action='store_true',
                        help='Skip the dashboard generation')
    parser.add_argument('--dry-run', action='store_true',
                        help='Show what would be enriched without invoking Claude')

    return parser.parse_args(argv)


# ============================================================================
# Main
# ============================================================================

def main(argv=None):
    args = parse_args(argv or [])

    install_signal_handlers()
    project_dir = detect_project_root()
    log(f'Project root: {project_dir}')

    # Resolve mode
    if args.interactive:
        enrich_mode = 'interactive'
    elif args.direct:
        enrich_mode = 'direct'
    else:
        enrich_mode = 'batch'

    parallel = args.parallel or int(os.environ.get('STORYFORGE_ENRICH_PARALLEL', '6'))

    # Parse fields
    fields = [f.strip() for f in args.fields.split(',')]
    valid_fields = set(ALL_FIELDS.split(','))
    for f in fields:
        if f not in valid_fields:
            print(f'ERROR: Invalid field \'{f}\'. Valid fields: {ALL_FIELDS}', file=sys.stderr)
            sys.exit(1)

    # Require API key for batch/direct modes
    if not args.dry_run and enrich_mode != 'interactive' and not os.environ.get('ANTHROPIC_API_KEY'):
        log('ERROR: ANTHROPIC_API_KEY not set.')
        log('  Enrichment uses the Anthropic API directly (batch mode by default).')
        log('  Set it with: export ANTHROPIC_API_KEY=your-key')
        log('  Or use --interactive for claude -p mode.')
        sys.exit(1)

    # Project info
    project_title = (
        read_yaml_field('project.title', project_dir)
        or read_yaml_field('title', project_dir)
        or 'Unknown'
    )

    # Paths
    metadata_csv = os.path.join(project_dir, 'reference', 'scenes.csv')
    intent_csv = os.path.join(project_dir, 'reference', 'scene-intent.csv')
    scenes_dir = os.path.join(project_dir, 'scenes')
    log_dir = os.path.join(project_dir, 'working', 'logs')
    enrich_dir = os.path.join(project_dir, 'working', 'enrich')
    os.makedirs(log_dir, exist_ok=True)
    os.makedirs(enrich_dir, exist_ok=True)

    if not os.path.isfile(metadata_csv):
        log('ERROR: reference/scenes.csv not found.')
        sys.exit(1)
    if not os.path.isfile(intent_csv):
        log('ERROR: reference/scene-intent.csv not found.')
        sys.exit(1)

    model = select_model('extraction')
    log(f'Enrichment model: {model} (mode: {enrich_mode})')

    # ========================================================================
    # Step 1: Discover scenes
    # ========================================================================
    log('Discovering scenes...')

    existing_meta_ids = set(_list_csv_ids(metadata_csv))
    existing_intent_ids = set(_list_csv_ids(intent_csv))

    # Find max seq
    max_seq = 0
    for val in _get_csv_column(metadata_csv, 'seq'):
        if val.isdigit() and int(val) > max_seq:
            max_seq = int(val)

    # Scan for scene files not yet in CSVs
    added_rows = 0
    if os.path.isdir(scenes_dir):
        for fname in sorted(os.listdir(scenes_dir)):
            if not fname.endswith('.md'):
                continue
            scene_id = fname[:-3]
            if not re.match(r'^[0-9]', scene_id):
                continue

            if scene_id not in existing_meta_ids:
                max_seq += 1
                scene_file = os.path.join(scenes_dir, fname)
                title = scene_id
                with open(scene_file) as f:
                    for line in f:
                        if line.startswith('#'):
                            title = re.sub(r'^#+\s*', '', line.strip()) or scene_id
                            break
                _append_csv_row(metadata_csv,
                                f'{scene_id}|{max_seq}|{title}||||||||')
                added_rows += 1
                log(f'  Added metadata row for {scene_id}')

            if scene_id not in existing_intent_ids:
                _append_csv_row(intent_csv, f'{scene_id}||||||')
                log(f'  Added intent row for {scene_id}')

    if added_rows > 0:
        log(f'Added {added_rows} new rows to CSVs')

    # ========================================================================
    # Step 2: Build scene list and apply filters
    # ========================================================================
    if args.scenes:
        filter_mode, filter_value = 'scenes', args.scenes
    elif args.act:
        filter_mode, filter_value = 'act', args.act
    elif args.from_seq:
        filter_mode, filter_value = 'from_seq', args.from_seq
    else:
        filter_mode, filter_value = 'all', ''

    filtered_ids = _apply_scene_filter(metadata_csv, filter_mode, filter_value, project_dir)

    # ========================================================================
    # Identify which scenes need enrichment
    # ========================================================================
    scene_ids = []
    missing_scenes = []
    skipped_short = []

    for sid in filtered_ids:
        scene_file = os.path.join(scenes_dir, f'{sid}.md')
        if not os.path.isfile(scene_file):
            missing_scenes.append(sid)
            continue

        wc = _word_count(scene_file)
        if wc < MIN_WORDS:
            skipped_short.append(sid)
            continue

        needs_enrichment = False
        for field in fields:
            csv_path = _csv_for_field(field, project_dir)
            current = ''
            if csv_path and os.path.isfile(csv_path):
                current = _get_csv_field(csv_path, sid, field)
            if not current or args.force:
                needs_enrichment = True
                break

        if needs_enrichment:
            scene_ids.append(sid)

    if missing_scenes:
        log(f'WARNING: {len(missing_scenes)} scenes have metadata but no prose file: {" ".join(missing_scenes)}')
    if skipped_short:
        log(f'WARNING: {len(skipped_short)} scenes too short (<{MIN_WORDS} words): {" ".join(skipped_short)}')

    if not scene_ids:
        log('No scenes need enrichment. All requested fields are already populated.')
        log('Use --force to re-enrich existing data.')
        return

    scene_count = len(scene_ids)
    log(f'{scene_count} scenes need enrichment')

    # ========================================================================
    # Step 3: Dry-run
    # ========================================================================
    if args.dry_run:
        avg_words = 800
        total_wc = 0
        for sid in scene_ids:
            sf = os.path.join(scenes_dir, f'{sid}.md')
            if os.path.isfile(sf):
                total_wc += _word_count(sf)
        if scene_count > 0:
            avg_words = total_wc // scene_count

        enrich_cost = estimate_cost('evaluate', scene_count, avg_words, model)
        if enrich_mode == 'batch':
            enrich_cost *= 0.5

        log('============================================')
        log('DRY RUN — Enrichment Plan')
        log('============================================')
        log(f'Mode:     {enrich_mode}')
        log(f'Scenes needing enrichment: {scene_count}')
        log(f'Fields:   {args.fields}')
        log(f'Parallel: {parallel}')
        log(f'Force:    {args.force}')
        log(f'Model:    {model}')
        log(f'Max cost: ~${enrich_cost:.2f} (actual will be lower — free heuristics run first)')
        log('')
        log('Phase 1 (free): word_count updates, time_of_day inference from keywords')
        log('Phase 2 (Claude): fields that can\'t be inferred from heuristics')
        log('')
        log('Scenes to enrich:')
        for sid in scene_ids:
            local_title = _get_csv_field(metadata_csv, sid, 'title')
            missing_fields = []
            for field in fields:
                csv_path = _csv_for_field(field, project_dir)
                current = ''
                if csv_path and os.path.isfile(csv_path):
                    current = _get_csv_field(csv_path, sid, field)
                if not current or args.force:
                    missing_fields.append(field)
            log(f'  - {sid} ({local_title or "untitled"}) — missing: {", ".join(missing_fields)}')
        log('')
        log('============================================')
        return

    # ========================================================================
    # Step 4: Create branch and PR
    # ========================================================================
    create_branch('enrich', project_dir)

    # Commit discovery changes
    commit_and_push(project_dir, 'Enrich: discover new scenes',
                    ['reference/scenes.csv', 'reference/scene-intent.csv'])

    ensure_branch_pushed(project_dir)

    # ========================================================================
    # Step 5: Free enrichment (no Claude needed)
    # ========================================================================
    log('============================================')
    log('Phase 1: Free enrichment (no API calls)')
    log('============================================')

    free_enriched = 0

    # Update word_count
    for sid in scene_ids:
        scene_file = os.path.join(scenes_dir, f'{sid}.md')
        if not os.path.isfile(scene_file):
            continue
        current_wc = _get_csv_field(metadata_csv, sid, 'word_count')
        actual_wc = str(_word_count(scene_file))
        if not current_wc or current_wc == '0':
            _update_csv_field(metadata_csv, sid, 'word_count', actual_wc)

    # Infer time_of_day
    for sid in scene_ids:
        current_tod = _get_csv_field(metadata_csv, sid, 'time_of_day')
        if current_tod and not args.force:
            continue
        setting_val = _get_csv_field(metadata_csv, sid, 'location')
        inferred = _infer_time_of_day(setting_val)
        if not inferred:
            scene_file = os.path.join(scenes_dir, f'{sid}.md')
            if os.path.isfile(scene_file):
                with open(scene_file) as f:
                    head_text = f.read(1000)
                inferred = _infer_time_of_day(head_text)
        if inferred:
            _update_csv_field(metadata_csv, sid, 'time_of_day', inferred)
            free_enriched += 1

    log(f'Free enrichment: {free_enriched} fields updated (word count + time_of_day)')

    # ========================================================================
    # Step 6: Re-check which scenes still need Claude enrichment
    # ========================================================================
    claude_ids = []
    for sid in scene_ids:
        still_needs = False
        for field in fields:
            csv_path = _csv_for_field(field, project_dir)
            current = ''
            if csv_path and os.path.isfile(csv_path):
                current = _get_csv_field(csv_path, sid, field)
            if not current or args.force:
                still_needs = True
                break
        if still_needs:
            claude_ids.append(sid)

    claude_count = len(claude_ids)
    enriched = 0
    failed = 0

    if claude_count == 0:
        log('All remaining fields populated by free enrichment. No Claude calls needed.')
    else:
        log(f'{claude_count} scenes still need Claude enrichment (reduced from {scene_count})')

        # Cost forecast
        total_wc = 0
        wc_count = 0
        for sid in claude_ids:
            sf = os.path.join(scenes_dir, f'{sid}.md')
            if os.path.isfile(sf):
                total_wc += _word_count(sf)
                wc_count += 1
        avg_words = total_wc // wc_count if wc_count > 0 else 800

        enrich_cost = estimate_cost('evaluate', claude_count, avg_words, model)
        if enrich_mode == 'batch':
            enrich_cost *= 0.5
            log(f'Cost forecast: ~${enrich_cost:.2f} ({claude_count} calls via Batch API, 50% off, avg {avg_words} words/scene)')
        else:
            mode_label = enrich_mode.capitalize()
            log(f'Cost forecast: ~${enrich_cost:.2f} ({claude_count} {model} calls via {mode_label} API, avg {avg_words} words/scene)')

        if not check_threshold(enrich_cost):
            log('Cost threshold check declined. Aborting.')
            sys.exit(1)

        # Create draft PR
        pr_body = (
            f'## Metadata Enrichment\n\n'
            f'**Project:** {project_title}\n'
            f'**Mode:** {enrich_mode}\n'
            f'**Phase 1 (free):** {free_enriched} fields updated (word count, time_of_day)\n'
            f'**Phase 2 (Claude):** {claude_count} scenes (of {scene_count} total)\n'
            f'**Fields:** {args.fields}\n'
            f'**Estimated cost:** ~${enrich_cost:.2f}\n\n'
            f'### Tasks\n'
            f'- [x] Free enrichment (word count, time_of_day keywords)\n'
            f'- [ ] Claude enrichment ({claude_count} scenes)\n'
            f'- [ ] Commit and push results\n'
            f'- [ ] Review'
        )
        create_draft_pr(
            f'Enrich: {project_title} ({claude_count} scenes)',
            pr_body, project_dir, 'enrichment',
        )

        # Step 6.5: Load alias maps
        alias_maps_json = os.path.join(enrich_dir, '.alias-maps.json')
        env = os.environ.copy()
        env['PYTHONPATH'] = _python_lib()
        r = subprocess.run(
            [sys.executable, '-m', 'storyforge.enrich', 'load-alias-maps', project_dir],
            capture_output=True, text=True, env=env,
        )
        if r.returncode == 0 and r.stdout.strip():
            with open(alias_maps_json, 'w') as f:
                f.write(r.stdout)
        else:
            with open(alias_maps_json, 'w') as f:
                f.write('{}')

        log('============================================')
        log(f'Phase 2: Claude enrichment ({claude_count} scenes, mode: {enrich_mode})')
        log('============================================')

        # Build prompt helper
        def _build_prompt(scene_id):
            force_flag = '--force' if args.force else ''
            r = subprocess.run(
                [sys.executable, '-m', 'storyforge.enrich', 'build-prompt',
                 scene_id, project_dir, '--fields', args.fields] +
                ([force_flag] if force_flag else []),
                capture_output=True, text=True,
                env={**os.environ, 'PYTHONPATH': _python_lib()},
            )
            return r.stdout.strip()

        # Parse response helper
        def _parse_response(response_text, result_file):
            if not response_text:
                with open(result_file, 'w') as f:
                    f.write('STATUS|fail\n')
                return

            tmp_response = result_file + '.response'
            with open(tmp_response, 'w') as f:
                f.write(response_text)

            r = subprocess.run(
                [sys.executable, '-m', 'storyforge.enrich', 'apply-response',
                 tmp_response, 'placeholder', project_dir,
                 '--aliases', alias_maps_json,
                 '--result-file', result_file,
                 '--parse-only'],
                capture_output=True, text=True,
                env={**os.environ, 'PYTHONPATH': _python_lib()},
            )
            if r.returncode != 0:
                with open(result_file, 'w') as f:
                    f.write('STATUS|fail\n')
            os.unlink(tmp_response) if os.path.exists(tmp_response) else None

        # Apply result helper
        def _apply_result(sid, result_file):
            nonlocal enriched, failed
            local_title = _get_csv_field(metadata_csv, sid, 'title')

            if not os.path.isfile(result_file):
                failed += 1
                log(f'  WARNING: No results for {sid}')
                return

            with open(result_file) as f:
                lines = f.readlines()

            result_map = {}
            for line in lines:
                line = line.strip()
                if '|' in line:
                    key, _, val = line.partition('|')
                    result_map[key] = val

            if result_map.get('STATUS') != 'ok':
                failed += 1
                log(f'  WARNING: Failed to enrich {sid}')
                if os.path.isfile(result_file):
                    os.remove(result_file)
                return

            for field in fields:
                result_key = field.upper()
                new_val = result_map.get(result_key, '')
                if not new_val:
                    continue

                csv_path = _csv_for_field(field, project_dir)
                current = ''
                if csv_path and os.path.isfile(csv_path):
                    current = _get_csv_field(csv_path, sid, field)
                if current and not args.force:
                    continue
                if csv_path and os.path.isfile(csv_path):
                    _update_csv_field(csv_path, sid, field, new_val)

            enriched += 1
            log(f'  Enriched {local_title or sid} ({enriched}/{claude_count})')
            if os.path.isfile(result_file):
                os.remove(result_file)

        # ================================================================
        # BATCH MODE
        # ================================================================
        if enrich_mode == 'batch':
            log('')
            log(f'Building batch request for {claude_count} scenes...')

            batch_file = os.path.join(enrich_dir, '.batch-requests.jsonl')
            with open(batch_file, 'w') as bf:
                for sid in claude_ids:
                    prompt = _build_prompt(sid)
                    req = {
                        'custom_id': sid,
                        'params': {
                            'model': model,
                            'max_tokens': 4096,
                            'messages': [{'role': 'user', 'content': prompt}],
                        },
                    }
                    bf.write(json.dumps(req) + '\n')

            log(f'Submitting batch ({os.path.getsize(batch_file)} bytes)...')
            batch_id = submit_batch(batch_file)
            log(f'Batch submitted: {batch_id}')
            log('Polling for results...')
            results_url = poll_batch(batch_id, log_fn=log)
            log('Batch complete. Downloading results...')
            succeeded = download_batch_results(results_url, enrich_dir, log_dir)

            for sid in claude_ids:
                status_file = os.path.join(enrich_dir, f'.status-{sid}')
                text_file = os.path.join(log_dir, f'{sid}.txt')
                json_file = os.path.join(log_dir, f'{sid}.json')
                result_file = os.path.join(enrich_dir, f'.enrich-{sid}.txt')

                if (os.path.isfile(status_file)
                        and open(status_file).read().strip() == 'ok'
                        and os.path.isfile(text_file)):
                    # Log usage
                    if os.path.isfile(json_file):
                        try:
                            with open(json_file) as jf:
                                resp = json.load(jf)
                            usage = extract_usage(resp)
                            cost = calculate_cost_from_usage(usage, model)
                            log_operation(project_dir, 'enrich', model,
                                          usage['input_tokens'], usage['output_tokens'],
                                          cost, target=sid)
                        except Exception:
                            pass

                    response = open(text_file).read()
                    _parse_response(response, result_file)
                    _apply_result(sid, result_file)
                else:
                    failed += 1
                    log(f'  WARNING: Failed {sid}')

                # Clean up temp files
                for fp in (status_file, text_file, json_file):
                    if os.path.isfile(fp):
                        os.remove(fp)

            if os.path.isfile(batch_file):
                os.remove(batch_file)

        # ================================================================
        # DIRECT MODE: Parallel real-time API calls
        # ================================================================
        elif enrich_mode == 'direct':
            log(f'Parallel workers: {parallel}')
            log('')

            from storyforge.runner import run_batched

            def _enrich_worker(sid):
                prompt = _build_prompt(sid)
                log_file = os.path.join(log_dir, f'enrich-{sid}.json')
                result_file = os.path.join(enrich_dir, f'.enrich-{sid}.txt')

                try:
                    resp = invoke_to_file(prompt, model, log_file, max_tokens=4096)
                    response_text = extract_text_from_file(log_file)

                    # Log usage
                    if os.path.isfile(log_file):
                        try:
                            with open(log_file) as jf:
                                api_resp = json.load(jf)
                            usage = extract_usage(api_resp)
                            cost = calculate_cost_from_usage(usage, model)
                            log_operation(project_dir, 'enrich', model,
                                          usage['input_tokens'], usage['output_tokens'],
                                          cost, target=sid)
                        except Exception:
                            pass

                    _parse_response(response_text, result_file)
                    return result_file
                except Exception as e:
                    with open(result_file, 'w') as f:
                        f.write('STATUS|fail\n')
                    return result_file

            def _merge_result(sid, result_file):
                _apply_result(sid, result_file)

            run_batched(claude_ids, _enrich_worker, _merge_result,
                        batch_size=parallel, label='scene')

        # ================================================================
        # INTERACTIVE MODE: claude -p
        # ================================================================
        elif enrich_mode == 'interactive':
            log(f'Parallel workers: {parallel}')
            log('')

            for i in range(0, claude_count, parallel):
                batch = claude_ids[i:i + parallel]
                procs = []

                for sid in batch:
                    prompt = _build_prompt(sid)
                    log_file = os.path.join(log_dir, f'enrich-{sid}.log')
                    result_file = os.path.join(enrich_dir, f'.enrich-{sid}.txt')
                    local_title = _get_csv_field(metadata_csv, sid, 'title')
                    log(f'  Launching enrichment for {local_title or sid}...')

                    proc = subprocess.Popen(
                        ['claude', '-p', prompt,
                         '--model', model,
                         '--dangerously-skip-permissions',
                         '--output-format', 'stream-json',
                         '--verbose'],
                        stdout=open(log_file, 'w'),
                        stderr=subprocess.STDOUT,
                    )
                    procs.append((sid, proc, log_file, result_file))

                # Wait for batch
                for sid, proc, log_file, result_file in procs:
                    proc.wait()

                    # Extract response using common.sh-equivalent
                    env = os.environ.copy()
                    env['PYTHONPATH'] = _python_lib()
                    r = subprocess.run(
                        [sys.executable, '-c',
                         f'from storyforge.common import extract_stream_json_response; '
                         f'print(extract_stream_json_response("{log_file}"))'],
                        capture_output=True, text=True, env=env,
                    )
                    response = r.stdout.strip() if r.returncode == 0 else ''
                    _parse_response(response, result_file)

                # Apply results
                for sid, proc, log_file, result_file in procs:
                    _apply_result(sid, result_file)

        log('')
        log(f'Enrichment complete: {enriched} scenes enriched, {failed} failures')

    # ========================================================================
    # Step 8: Timeline pass
    # ========================================================================
    if not args.skip_timeline and not args.dry_run:
        log('')
        log('Step 8: Timeline analysis (delegating to storyforge-timeline)...')
        from storyforge.common import get_plugin_dir
        timeline_script = os.path.join(get_plugin_dir(), 'scripts', 'storyforge-timeline')
        if os.path.isfile(timeline_script) and os.access(timeline_script, os.X_OK):
            timeline_args = ['--embedded']
            if args.force:
                timeline_args.append('--force')
            if args.scenes:
                timeline_args.extend(['--scenes', args.scenes])
            elif args.act:
                timeline_args.extend(['--act', args.act])
            elif args.from_seq:
                timeline_args.extend(['--from-seq', args.from_seq])
            r = subprocess.run([timeline_script] + timeline_args, capture_output=True, text=True)
            if r.returncode != 0:
                log('WARNING: Timeline analysis failed (non-fatal, continuing)')
        else:
            log(f'WARNING: storyforge-timeline not found, skipping timeline')
    elif args.skip_timeline:
        log('')
        log('Step 8: Timeline analysis (skipped via --skip-timeline)')

    # ========================================================================
    # Step 9: Dashboard generation
    # ========================================================================
    if not args.skip_dashboard and not args.dry_run:
        log('')
        log('Step 9: Generating manuscript dashboard...')
        from storyforge.common import get_plugin_dir
        viz_script = os.path.join(get_plugin_dir(), 'scripts', 'storyforge-visualize')
        if os.path.isfile(viz_script) and os.access(viz_script, os.X_OK):
            r = subprocess.run([viz_script], capture_output=True, text=True)
            if r.returncode != 0:
                log('WARNING: Dashboard generation failed (non-fatal, continuing)')
        else:
            log('WARNING: storyforge-visualize not found, skipping dashboard')
    elif args.skip_dashboard:
        log('')
        log('Step 9: Dashboard generation (skipped via --skip-dashboard)')

    # ========================================================================
    # Update PR tasks
    # ========================================================================
    update_pr_task(f'Enrich metadata ({scene_count} scenes)', project_dir)

    # ========================================================================
    # Cost summary
    # ========================================================================
    print('')
    print_summary(project_dir, 'enrich')

    # ========================================================================
    # Seed alias CSVs from enriched data
    # ========================================================================
    _seed_alias_csv(os.path.join(project_dir, 'reference', 'characters.csv'),
                    intent_csv, 'characters', 'id|name|aliases|role')
    _seed_alias_csv(os.path.join(project_dir, 'reference', 'motif-taxonomy.csv'),
                    os.path.join(project_dir, 'reference', 'scene-briefs.csv'),
                    'motifs', 'id|name|aliases|tier')
    _seed_alias_csv(os.path.join(project_dir, 'reference', 'locations.csv'),
                    metadata_csv, 'location', 'id|name|aliases')
    _seed_alias_csv(os.path.join(project_dir, 'reference', 'values.csv'),
                    intent_csv, 'value_at_stake', 'id|name|aliases')

    # ========================================================================
    # Commit and push
    # ========================================================================
    log('Committing enrichment results...')
    commit_and_push(
        project_dir,
        f'Enrich: metadata for {enriched} scenes ({enrich_mode} mode, {args.fields})',
        [
            'reference/scenes.csv', 'reference/scene-intent.csv',
            'reference/scene-briefs.csv', 'reference/characters.csv',
            'reference/motif-taxonomy.csv', 'reference/locations.csv',
            'reference/values.csv', 'reference/knowledge.csv',
            'reference/mice-threads.csv', 'working/costs/', 'working/logs/',
            'working/enrich/',
        ],
    )

    update_pr_task('Commit and push results', project_dir)
    update_pr_task('Review', project_dir)

    log('============================================')
    log('Enrichment complete')
    log(f'  Scenes enriched: {enriched}')
    log(f'  Failures: {failed}')
    log(f'  Fields: {args.fields}')
    log('============================================')


def _seed_alias_csv(csv_file: str, source_csv: str, source_field: str, header: str) -> None:
    """Seed a registry CSV from enriched data if it's header-only."""
    if not os.path.isfile(csv_file):
        return
    with open(csv_file) as f:
        lines = [l for l in f if l.strip()]
    if len(lines) > 1:
        return

    if not os.path.isfile(source_csv):
        return

    values_raw = _get_csv_column(source_csv, source_field)
    all_names = set()
    for val in values_raw:
        for name in val.split(';'):
            name = name.strip()
            if name:
                all_names.add(name)

    if not all_names:
        return

    count = 0
    with open(csv_file, 'a') as f:
        for name in sorted(all_names):
            sid = re.sub(r'[^a-z0-9-]', '',
                         re.sub(r'[-]+', '-',
                                re.sub(r'\s+', '-', name.lower())))
            sid = sid.strip('-')
            f.write(f'{sid}|{name}|\n')
            count += 1

    if count > 0:
        log(f'Seeded {os.path.basename(csv_file)} with {count} entries from enriched data')
