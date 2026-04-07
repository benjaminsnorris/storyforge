"""storyforge timeline — Timeline day assignment for scenes.

Two-phase architecture:
  Phase 1 (Haiku): Extract temporal indicators from each scene in parallel
  Phase 2 (Sonnet): Assign timeline_day values via multi-scene analysis

Usage:
    storyforge timeline                     # All scenes, autonomous
    storyforge timeline --interactive       # Interactive with review checkpoints
    storyforge timeline --act 2             # Scenes in act 2 only
    storyforge timeline --embedded          # Called from enrich (no branch/PR)
    storyforge timeline --dry-run           # Show plan without invoking Claude
"""

import argparse
import json
import os
import sys
import time

from storyforge.common import (
    detect_project_root, log, read_yaml_field, select_model,
    install_signal_handlers, is_shutting_down,
    show_interactive_banner, offer_interactive,
    build_interactive_system_prompt,
)
from storyforge.cli import add_scene_filter_args, resolve_filter_args
from storyforge.scene_filter import build_scene_list, apply_scene_filter
from storyforge.csv_cli import get_field, update_field
from storyforge.costs import estimate_cost, check_threshold, print_summary
from storyforge.git import (
    create_branch, ensure_branch_pushed, create_draft_pr,
    update_pr_task, commit_and_push,
)
from storyforge.api import (
    invoke_api, invoke_to_file, extract_text_from_file,
    submit_batch, poll_batch, download_batch_results,
    extract_usage, calculate_cost_from_usage,
)
from storyforge.costs import log_operation
from storyforge.timeline import (
    build_phase1_prompt, parse_indicators,
    build_phase2_prompt, parse_timeline_assignments,
)


def parse_args(argv):
    parser = argparse.ArgumentParser(
        prog='storyforge timeline',
        description='Assign timeline_day values to scenes via two-phase Claude analysis.',
    )

    # Scene selection
    add_scene_filter_args(parser)

    # Options
    parser.add_argument('--interactive', '-i', action='store_true',
                        help='Interactive mode with review checkpoints')
    parser.add_argument('--direct', action='store_true',
                        help='Use direct API calls instead of batch (default: batch)')
    parser.add_argument('--parallel', type=int, default=None,
                        help='Haiku extraction workers (default: 6)')
    parser.add_argument('--force', action='store_true',
                        help='Overwrite existing timeline_day values')
    parser.add_argument('--dry-run', action='store_true',
                        help='Show what would happen without invoking Claude')
    parser.add_argument('--skip-phase1', action='store_true',
                        help='Skip Haiku extraction; reuse cached indicators')
    parser.add_argument('--phase1-only', action='store_true',
                        help='Run Phase 1 only; keep indicator files for review')
    parser.add_argument('--embedded', action='store_true',
                        help='Called as subprocess (skip branch/PR/commit)')

    return parser.parse_args(argv)


def main(argv=None):
    args = parse_args(argv or [])

    install_signal_handlers()
    project_dir = detect_project_root()

    # Determine API mode
    parallel = args.parallel or int(os.environ.get('STORYFORGE_TIMELINE_PARALLEL', '6'))
    if args.interactive:
        timeline_mode = 'interactive'
    elif args.direct:
        timeline_mode = 'direct'
    else:
        timeline_mode = 'batch'

    # API key check
    if not args.dry_run and not args.interactive and not args.embedded:
        if not os.environ.get('ANTHROPIC_API_KEY'):
            log('ERROR: ANTHROPIC_API_KEY is required for autonomous mode (batch/direct API).')
            log('  Set it with: export ANTHROPIC_API_KEY=your-key')
            log('  Or use --interactive mode which uses claude -p instead.')
            sys.exit(1)

    title = read_yaml_field('project.title', project_dir) or read_yaml_field('title', project_dir) or 'Unknown'

    # Resolve paths
    metadata_csv = os.path.join(project_dir, 'reference', 'scenes.csv')
    scenes_dir = os.path.join(project_dir, 'scenes')
    log_dir = os.path.join(project_dir, 'working', 'logs')
    timeline_dir = os.path.join(project_dir, 'working', 'timeline')
    os.makedirs(log_dir, exist_ok=True)
    os.makedirs(timeline_dir, exist_ok=True)

    if not os.path.isfile(metadata_csv):
        log('ERROR: reference/scenes.csv not found.')
        sys.exit(1)

    # Interactive mode file
    interactive_file = os.path.join(project_dir, 'working', '.interactive')
    if not args.embedded:
        try:
            os.remove(interactive_file)
        except FileNotFoundError:
            pass
        if args.interactive:
            open(interactive_file, 'w').close()

    # Build and filter scene list
    all_ids = build_scene_list(metadata_csv)
    filter_mode, filter_val, filter_val2 = resolve_filter_args(args)
    scene_ids = apply_scene_filter(metadata_csv, all_ids, filter_mode, filter_val, filter_val2)
    scene_count = len(scene_ids)

    if scene_count == 0:
        log('No scenes match the filter. Nothing to do.')
        sys.exit(0)

    # Model selection
    haiku_model = select_model('extraction')
    sonnet_model = select_model('evaluation')

    log('============================================')
    log('Storyforge Timeline')
    log('============================================')
    log(f'Project: {title}')
    log(f'Scenes: {scene_count}')
    log(f'Phase 1 model: {haiku_model}')
    log(f'Phase 2 model: {sonnet_model}')
    log(f'API mode: {timeline_mode}')
    mode_label = 'interactive' if os.path.isfile(interactive_file) else 'autonomous'
    log(f'Mode: {mode_label}')
    if args.embedded:
        log('Running embedded (no branch/PR)')
    log('============================================')

    # --- Dry run ---
    if args.dry_run:
        log('')
        log('DRY RUN -- would analyze these scenes:')
        for sid in scene_ids:
            stitle = get_field(metadata_csv, sid, 'title') or ''
            seq = get_field(metadata_csv, sid, 'seq') or ''
            existing = get_field(metadata_csv, sid, 'timeline_day') or 'unset'
            log(f'  SEQ {seq}: {sid} -- {stitle or "untitled"} (current day: {existing})')
        log('')
        if args.skip_phase1:
            log('Phase 1: SKIPPED (reusing cached indicators)')
        elif timeline_mode == 'batch':
            log(f'Phase 1: {scene_count} Haiku calls (batch API, 50% discount)')
        elif timeline_mode == 'direct':
            log(f'Phase 1: {scene_count} Haiku calls (direct API, {parallel} workers)')
        else:
            log(f'Phase 1: {scene_count} Haiku calls (claude -p, {parallel} workers)')
        if args.phase1_only:
            log('Phase 2: DEFERRED (--phase1-only)')
        else:
            log('Phase 2: 1 Sonnet call (all scenes)')
        sys.exit(0)

    # --- Cost forecast ---
    total_words = 0
    for sid in scene_ids:
        sf = os.path.join(scenes_dir, f'{sid}.md')
        if os.path.isfile(sf):
            with open(sf) as f:
                total_words += len(f.read().split())

    avg_words = total_words // max(scene_count, 1)
    if avg_words < 100:
        avg_words = 100

    phase1_cost = estimate_cost('extraction', scene_count, avg_words, haiku_model)
    if timeline_mode == 'batch':
        phase1_cost *= 0.5
    phase2_cost = estimate_cost('evaluation', 1, scene_count * 50, sonnet_model)

    if args.skip_phase1:
        log(f'Cost forecast: Phase 2 ~${phase2_cost:.6f} (Phase 1 skipped)')
        if not check_threshold(phase2_cost):
            log('Cost threshold exceeded. Aborting.')
            sys.exit(1)
    elif args.phase1_only:
        log(f'Cost forecast: Phase 1 ~${phase1_cost:.6f} (Phase 2 deferred)')
        if not check_threshold(phase1_cost):
            log('Cost threshold exceeded. Aborting.')
            sys.exit(1)
    else:
        log(f'Cost forecast: Phase 1 ~${phase1_cost:.6f}, Phase 2 ~${phase2_cost:.6f}')
        if not check_threshold(phase1_cost):
            log('Cost threshold exceeded. Aborting.')
            sys.exit(1)

    # --- Branch & PR (standalone mode only) ---
    if not args.embedded:
        create_branch('timeline', project_dir)
        ensure_branch_pushed(project_dir)

        pr_body = f"""## Timeline Assignment

**Project:** {title}
**Scenes:** {scene_count}

### Tasks
- [ ] Phase 1: Extract temporal indicators (Haiku)
- [ ] Phase 2: Assign timeline_day values (Sonnet)
"""
        create_draft_pr(f'Enrich: timeline for {title}', pr_body, project_dir, 'enrichment')

    # --- Pre-build previous scene context ---
    prev_summaries = []
    for i, sid in enumerate(scene_ids):
        if i == 0:
            prev_summaries.append(None)
        else:
            prev_id = scene_ids[i - 1]
            pt = get_field(metadata_csv, prev_id, 'title') or 'untitled'
            ptod = get_field(metadata_csv, prev_id, 'time_of_day') or 'unknown'
            cur_title = get_field(metadata_csv, sid, 'title') or 'untitled'
            cur_pov = get_field(metadata_csv, sid, 'pov') or 'unknown'
            cur_tod = get_field(metadata_csv, sid, 'time_of_day') or 'unknown'
            prev_summaries.append({
                'title': pt,
                'time_of_day': ptod,
                'scene_title': cur_title,
                'scene_pov': cur_pov,
                'scene_tod': cur_tod,
            })
        # For the first scene, still need current scene metadata
        if i == 0:
            cur_title = get_field(metadata_csv, sid, 'title') or 'untitled'
            cur_pov = get_field(metadata_csv, sid, 'pov') or 'unknown'
            cur_tod = get_field(metadata_csv, sid, 'time_of_day') or 'unknown'
            prev_summaries[0] = {
                'title': '(first scene)',
                'time_of_day': 'unknown',
                'scene_title': cur_title,
                'scene_pov': cur_pov,
                'scene_tod': cur_tod,
            }

    # ==================================================================
    # Phase 1: Haiku temporal indicator extraction
    # ==================================================================

    def _run_phase1():
        log('')
        log(f'Phase 1: Temporal analysis ({scene_count} scenes, mode: {timeline_mode})')
        log('--------------------------------------------')

        if timeline_mode == 'batch':
            _run_phase1_batch()
        else:
            _run_phase1_parallel()

    def _build_prompt(idx):
        """Build phase 1 prompt for scene at index idx."""
        sid = scene_ids[idx]
        scene_file = os.path.join(scenes_dir, f'{sid}.md')
        prose = ''
        if os.path.isfile(scene_file):
            with open(scene_file) as f:
                prose = f.read()
        if not prose.strip():
            return ''
        return build_phase1_prompt(sid, prose, prev_summaries[idx])

    def _save_indicators(sid, indicators):
        """Write indicator file for a scene."""
        indicator_line = (
            f"DELTA: {indicators['delta']} | "
            f"EVIDENCE: {indicators['evidence']} | "
            f"ANCHOR: {indicators['anchor']}"
        )
        ind_file = os.path.join(timeline_dir, f'.indicators-{sid}')
        with open(ind_file, 'w') as f:
            f.write(indicator_line)
        status_file = os.path.join(timeline_dir, f'.status-{sid}')
        with open(status_file, 'w') as f:
            f.write('ok')

    def _save_no_prose(sid):
        ind_file = os.path.join(timeline_dir, f'.indicators-{sid}')
        with open(ind_file, 'w') as f:
            f.write('DELTA: unknown | EVIDENCE: (no prose) | ANCHOR: none')
        status_file = os.path.join(timeline_dir, f'.status-{sid}')
        with open(status_file, 'w') as f:
            f.write('ok')

    def _run_phase1_batch():
        """Phase 1 via Batch API."""
        import tempfile
        log(f'Building batch request for {scene_count} scenes...')

        batch_file = os.path.join(log_dir, 'timeline-phase1-batch.jsonl')
        skipped_ids = []

        with open(batch_file, 'w') as bf:
            for i, sid in enumerate(scene_ids):
                prompt = _build_prompt(i)
                if not prompt:
                    _save_no_prose(sid)
                    skipped_ids.append(sid)
                    continue
                import json as _json
                request = {
                    'custom_id': sid,
                    'params': {
                        'model': haiku_model,
                        'max_tokens': 1024,
                        'messages': [{'role': 'user', 'content': prompt}],
                    },
                }
                bf.write(_json.dumps(request) + '\n')

        # Count API requests
        with open(batch_file) as f:
            api_count = sum(1 for line in f if line.strip())

        if api_count == 0:
            log('No scenes with prose to analyze -- all skipped')
        else:
            log(f'Submitting batch with {api_count} requests...')
            batch_id = submit_batch(batch_file)
            log(f'Batch submitted: {batch_id}')

            log('Polling for completion...')
            results_url = poll_batch(batch_id, log_fn=log)

            log('Downloading results...')
            succeeded = download_batch_results(results_url, timeline_dir, log_dir)

            # Parse results
            skipped_set = set(skipped_ids)
            for sid in scene_ids:
                if sid in skipped_set:
                    continue
                txt_file = os.path.join(log_dir, f'{sid}.txt')
                json_file = os.path.join(log_dir, f'{sid}.json')

                if os.path.isfile(txt_file):
                    with open(txt_file) as f:
                        response = f.read()
                    indicators = parse_indicators(response, sid)
                    _save_indicators(sid, indicators)
                    # Log usage
                    if os.path.isfile(json_file):
                        with open(json_file) as f:
                            resp_data = json.load(f)
                        usage = extract_usage(resp_data)
                        cost = calculate_cost_from_usage(usage, haiku_model)
                        log_operation(project_dir, 'timeline-phase1', haiku_model,
                                      usage['input_tokens'], usage['output_tokens'],
                                      cost, target=sid,
                                      cache_read=usage.get('cache_read', 0),
                                      cache_create=usage.get('cache_create', 0))
                else:
                    log(f'  WARNING: No result for {sid}')
                    ind_file = os.path.join(timeline_dir, f'.indicators-{sid}')
                    with open(ind_file, 'w') as f:
                        f.write('DELTA: unknown | EVIDENCE: (extraction failed) | ANCHOR: none')
                    status_file = os.path.join(timeline_dir, f'.status-{sid}')
                    with open(status_file, 'w') as f:
                        f.write('fail')

        # Report
        _report_phase1_results()

    def _run_phase1_parallel():
        """Phase 1 via direct API or interactive (parallel workers)."""
        from storyforge.runner import run_batched

        def _worker(idx_str):
            idx = int(idx_str)
            sid = scene_ids[idx]
            prompt = _build_prompt(idx)
            if not prompt:
                _save_no_prose(sid)
                return {'sid': sid, 'status': 'skipped'}

            lf = os.path.join(log_dir, f'timeline-phase1-{sid}.json')

            if timeline_mode == 'direct':
                response_data = invoke_to_file(prompt, haiku_model, lf, max_tokens=1024)
                from storyforge.api import extract_text
                response = extract_text(response_data)
                usage = extract_usage(response_data)
                cost = calculate_cost_from_usage(usage, haiku_model)
                log_operation(project_dir, 'timeline-phase1', haiku_model,
                              usage['input_tokens'], usage['output_tokens'],
                              cost, target=sid,
                              cache_read=usage.get('cache_read', 0),
                              cache_create=usage.get('cache_create', 0))
            else:
                # Interactive mode -- use invoke_api (simplified)
                response = invoke_api(prompt, haiku_model, max_tokens=1024)

            indicators = parse_indicators(response, sid)
            _save_indicators(sid, indicators)
            return {'sid': sid, 'status': 'ok'}

        # Build index list as strings (run_batched expects str items)
        idx_items = [str(i) for i in range(scene_count)]
        run_batched(idx_items, _worker, batch_size=parallel, label='scene')

        _report_phase1_results()

    def _report_phase1_results():
        completed = 0
        for sid in scene_ids:
            completed += 1
            ind_file = os.path.join(timeline_dir, f'.indicators-{sid}')
            if os.path.isfile(ind_file):
                with open(ind_file) as f:
                    indicators = f.read().strip()
                log(f'  [{completed}/{scene_count}] {sid}: {indicators}')
            else:
                log(f'  [{completed}/{scene_count}] {sid}: (extraction failed)')
        log(f'Phase 1 complete: {completed} scenes processed')

    # ==================================================================
    # Phase 2: Sonnet timeline_day assignment
    # ==================================================================

    def _run_phase2():
        log('')
        log('Phase 2: Assigning timeline_day values (single Sonnet pass)')
        log('--------------------------------------------')

        # Build scene summaries
        summaries = []
        for sid in scene_ids:
            stitle = get_field(metadata_csv, sid, 'title') or 'untitled'
            seq = get_field(metadata_csv, sid, 'seq') or '?'
            tod = get_field(metadata_csv, sid, 'time_of_day') or 'unknown'
            existing = get_field(metadata_csv, sid, 'timeline_day') or ''

            # Read indicators
            ind_file = os.path.join(timeline_dir, f'.indicators-{sid}')
            delta = 'unknown'
            evidence = 'none'
            anchor = 'none'
            if os.path.isfile(ind_file):
                with open(ind_file) as f:
                    raw = f.read().strip()
                # Parse "DELTA: x | EVIDENCE: y | ANCHOR: z"
                for part in raw.split('|'):
                    part = part.strip()
                    if part.upper().startswith('DELTA:'):
                        delta = part.split(':', 1)[1].strip()
                    elif part.upper().startswith('EVIDENCE:'):
                        evidence = part.split(':', 1)[1].strip()
                    elif part.upper().startswith('ANCHOR:'):
                        anchor = part.split(':', 1)[1].strip()

            summaries.append({
                'id': sid,
                'title': stitle,
                'seq': seq,
                'time_of_day': tod,
                'existing_day': existing,
                'delta': delta,
                'evidence': evidence,
                'anchor': anchor,
            })

        prompt = build_phase2_prompt(summaries, title)
        tl_log = os.path.join(log_dir, 'timeline-phase2.json')

        log(f'Sending {scene_count} scene summaries to Sonnet...')

        if timeline_mode == 'interactive':
            response = invoke_api(prompt, sonnet_model, max_tokens=4096)
        else:
            response_data = invoke_to_file(prompt, sonnet_model, tl_log, max_tokens=4096)
            from storyforge.api import extract_text
            response = extract_text(response_data)
            usage = extract_usage(response_data)
            cost = calculate_cost_from_usage(usage, sonnet_model)
            log_operation(project_dir, 'timeline-phase2', sonnet_model,
                          usage['input_tokens'], usage['output_tokens'],
                          cost, target='all',
                          cache_read=usage.get('cache_read', 0),
                          cache_create=usage.get('cache_create', 0))

        if not response:
            log('WARNING: No response from Sonnet for timeline assignment')
            return 0, 0

        # Parse assignments
        assignments = parse_timeline_assignments(response)

        assigned = 0
        skipped = 0
        for sid in scene_ids:
            day_val = assignments.get(sid)
            if day_val is None:
                continue
            existing = get_field(metadata_csv, sid, 'timeline_day') or ''
            if existing and not args.force:
                skipped += 1
            else:
                update_field(metadata_csv, sid, 'timeline_day', str(day_val))
                assigned += 1

        log(f'Phase 2 complete: {assigned} assigned, {skipped} skipped (already set)')
        return assigned, skipped

    # ==================================================================
    # Build indicator display (for interactive checkpoints)
    # ==================================================================

    def _build_indicator_display():
        lines = []
        for sid in scene_ids:
            seq = get_field(metadata_csv, sid, 'seq') or '?'
            stitle = get_field(metadata_csv, sid, 'title') or 'untitled'
            ind_file = os.path.join(timeline_dir, f'.indicators-{sid}')
            indicators = '(not extracted)'
            if os.path.isfile(ind_file):
                with open(ind_file) as f:
                    indicators = f.read().strip()
            lines.append(f'SEQ {seq}: {stitle} ({sid})')
            lines.append(f'  Indicators: {indicators}')
            lines.append('')
        return '\n'.join(lines)

    # ==================================================================
    # Main execution flow
    # ==================================================================

    # --- Phase 1 ---
    if args.skip_phase1:
        cached = sum(1 for sid in scene_ids
                     if os.path.isfile(os.path.join(timeline_dir, f'.indicators-{sid}')))
        if cached > 0:
            log(f'Skipping Phase 1: using {cached} cached indicator files')
        else:
            log('Skipping Phase 1: no cached indicators, Phase 2 will use raw metadata')
    else:
        _run_phase1()

    # --- Phase 1 only: stop here ---
    if args.phase1_only:
        display = _build_indicator_display()
        log('')
        log(f'Phase 1 complete. Indicator files saved to: {timeline_dir}/')
        log('')
        log('Results:')
        print(display)
        log('')
        log('Review and edit indicator files as needed, then run Phase 2:')
        log('  storyforge timeline --skip-phase1 [same scene filters]')
        if not args.embedded:
            print_summary(project_dir, 'timeline-phase1')
            try:
                os.remove(interactive_file)
            except FileNotFoundError:
                pass
        sys.exit(0)

    # --- Interactive checkpoint 1 (after Phase 1) ---
    if os.path.isfile(interactive_file):
        show_interactive_banner('Timeline -- Phase 1: Temporal Indicators', 'single')
        log('Phase 1 indicator results are ready for review.')
        print(_build_indicator_display())

    # --- Offer interactive rejoin between phases (autonomous mode) ---
    if not os.path.isfile(interactive_file) and not args.embedded:
        if offer_interactive(project_dir, 'Phase 2: Sonnet timeline assignment'):
            show_interactive_banner('Timeline -- Phase 1: Temporal Indicators', 'single')
            print(_build_indicator_display())

    # Update PR task
    if not args.embedded:
        update_pr_task('Phase 1: Extract temporal indicators (Haiku)', project_dir)

    # --- Phase 2 ---
    assigned, skipped_count = _run_phase2()

    # --- Interactive checkpoint 2 (after Phase 2) ---
    if os.path.isfile(interactive_file):
        lines = ['Timeline assignments:', '']
        for sid in scene_ids:
            seq = get_field(metadata_csv, sid, 'seq') or '?'
            stitle = get_field(metadata_csv, sid, 'title') or 'untitled'
            day = get_field(metadata_csv, sid, 'timeline_day') or '?'
            lines.append(f'  SEQ {seq}: Day {day} -- {stitle} ({sid})')
        show_interactive_banner('Timeline -- Phase 2: Timeline Assignments', 'single')
        print('\n'.join(lines))

    # ==================================================================
    # Commit & cleanup
    # ==================================================================

    if not args.embedded:
        commit_and_push(project_dir, 'Enrich: timeline_day assignment',
                        ['reference/scenes.csv', 'working/logs/'])
        update_pr_task('Phase 2: Assign timeline_day values (Sonnet)', project_dir)

    # Clean up temp files
    for sid in scene_ids:
        for prefix in ('.indicators-', '.status-'):
            path = os.path.join(timeline_dir, f'{prefix}{sid}')
            try:
                os.remove(path)
            except FileNotFoundError:
                pass

    # Cleanup interactive file
    if not args.embedded:
        try:
            os.remove(interactive_file)
        except FileNotFoundError:
            pass

    # ==================================================================
    # Summary
    # ==================================================================

    log('')
    log('============================================')
    log('Timeline assignment complete')
    log(f'  Scenes analyzed: {scene_count}')
    log(f'  Assigned: {assigned}')
    log(f'  Skipped: {skipped_count}')
    log('============================================')

    if not args.embedded:
        print_summary(project_dir, 'timeline-phase1')
        print_summary(project_dir, 'timeline-phase2')
