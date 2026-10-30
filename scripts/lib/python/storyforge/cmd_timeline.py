"""storyforge timeline — put every scene on one calendar.

Two steps (docs/plans/timeline-pass.md):
  Cues (Haiku, per scene): what each scene's text says about time — its
    relation to the scene before, the gap, anchors, a span, an EDTF date.
    Read from prose, or from the summary when a scene isn't drafted yet.
    Stored in working/timeline-cues.csv.
  Assignment (Sonnet, in reading order): code walks a running present; the
    model places what code can't, in batches, so no call grows with the book.

Days and modes already set are never overwritten without --force: the
proposal goes to working/timeline-proposed.csv instead.

Usage:
    storyforge timeline                     # All scenes, autonomous
    storyforge timeline --check             # Compare prose with the calendar; change nothing
    storyforge timeline --check --scenes a,b
    storyforge timeline --force             # Replace days and modes already set
    storyforge timeline --skip-phase1       # Reuse stored cues
    storyforge timeline --phase1-only       # Read cues only
    storyforge timeline --embedded          # Called from enrich (no branch/PR)
    storyforge timeline --dry-run           # Show plan without invoking Claude
"""

import argparse
import json
import os
import sys
from datetime import datetime

from storyforge.common import (
    detect_project_root, log, read_yaml_field, select_model,
    install_signal_handlers, is_shutting_down,
    show_interactive_banner, offer_interactive,
    build_interactive_system_prompt, build_shared_context,
)
from storyforge.cli import add_scene_filter_args, resolve_filter_args
from storyforge.scene_filter import build_scene_list, apply_scene_filter
from storyforge.csv_cli import get_field
from storyforge.costs import estimate_cost, check_threshold, print_summary
from storyforge.git import (
    create_branch, ensure_branch_pushed, create_draft_pr,
    update_pr_task, commit_and_push,
)
from storyforge.api import (
    submit_batch, poll_batch, download_batch_results, build_batch_request,
)
from storyforge.timeline import (
    CUES_FILE, CHECK_CUES_FILE, cue_prompts, extract_cues, has_cues, parse_cues, write_cues, read_cues,
    run_assignment, check_timeline, report_findings, reading_order,
)


def parse_args(argv):
    parser = argparse.ArgumentParser(
        prog='storyforge timeline',
        description='Put every scene on one calendar: time cues per scene, then '
                    'day assignment in reading order.',
    )

    # Scene selection (limits which scenes' cues are read; the calendar is
    # always assigned over the whole book)
    add_scene_filter_args(parser)

    parser.add_argument('--interactive', '-i', action='store_true',
                        help='Interactive mode with review checkpoints')
    parser.add_argument('--direct', action='store_true',
                        help='Use direct API calls instead of batch (default: batch)')
    parser.add_argument('--parallel', type=int, default=None,
                        help='Cue extraction workers (default: 6)')
    parser.add_argument('--force', action='store_true',
                        help='Replace timeline_day and time_mode values already set')
    parser.add_argument('--check', action='store_true',
                        help='Read cues from the current prose and report where the '
                             'calendar disagrees; change nothing in scenes.csv')
    parser.add_argument('--dry-run', action='store_true',
                        help='Show what would happen without invoking Claude')
    parser.add_argument('--skip-phase1', action='store_true',
                        help='Skip cue extraction; reuse working/timeline-cues.csv')
    parser.add_argument('--phase1-only', action='store_true',
                        help='Read and store cues only; assign nothing')
    parser.add_argument('--embedded', action='store_true',
                        help='Called as subprocess (skip branch/PR/commit)')

    return parser.parse_args(argv)


def main(argv=None):
    args = parse_args(argv or [])
    session_start = datetime.now().strftime('%Y-%m-%dT%H:%M:%S')

    install_signal_handlers()
    project_dir = detect_project_root()

    parallel = args.parallel or int(os.environ.get('STORYFORGE_TIMELINE_PARALLEL', '6'))
    os.environ.setdefault('STORYFORGE_PARALLEL', str(parallel))
    if args.interactive:
        timeline_mode = 'interactive'
    elif args.direct or args.check:
        timeline_mode = 'direct'
    else:
        timeline_mode = 'batch'

    # Every mode calls the API (interactive only adds review checkpoints);
    # embedded runs inherit the caller's check
    if not args.dry_run and not args.embedded:
        if not os.environ.get('ANTHROPIC_API_KEY'):
            log('ERROR: ANTHROPIC_API_KEY is required (the timeline pass calls the API).')
            log('  Set it with: export ANTHROPIC_API_KEY=your-key')
            sys.exit(1)

    title = read_yaml_field('project.title', project_dir) or read_yaml_field('title', project_dir) or 'Unknown'

    metadata_csv = os.path.join(project_dir, 'reference', 'scenes.csv')
    log_dir = os.path.join(project_dir, 'working', 'logs')
    os.makedirs(log_dir, exist_ok=True)

    if not os.path.isfile(metadata_csv):
        log('ERROR: reference/scenes.csv not found.')
        sys.exit(1)

    interactive_file = os.path.join(project_dir, 'working', '.interactive')
    if not args.embedded:
        try:
            os.remove(interactive_file)
        except FileNotFoundError:
            pass
        if args.interactive:
            open(interactive_file, 'w').close()

    # Every scene happens on some day, however short: a 41-word scene left
    # out kept a stale cue and set the present for the scenes after it
    # (Plastic Age's helen-memory-fades-college, F-107)
    all_ids = build_scene_list(metadata_csv, min_words=1)
    filter_mode, filter_val, filter_val2 = resolve_filter_args(args)
    scene_ids = apply_scene_filter(metadata_csv, all_ids, filter_mode, filter_val, filter_val2)
    scene_count = len(scene_ids)

    if scene_count == 0:
        log('No scenes match the filter. Nothing to do.')
        sys.exit(0)

    cue_model = select_model('extraction')
    assign_model = select_model('evaluation')

    log('============================================')
    log('Storyforge Timeline')
    log('============================================')
    log(f'Project: {title}')
    log(f'Scenes: {scene_count}')
    log(f'Cue model: {cue_model}')
    log(f'Assignment model: {assign_model}')
    log(f'API mode: {timeline_mode}')
    log(f'Mode: {"check (read-only)" if args.check else "interactive" if args.interactive else "autonomous"}')
    if args.embedded:
        log('Running embedded (no branch/PR)')
    log('============================================')

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
            log(f'Cues: SKIPPED (reusing {CUES_FILE})')
        else:
            log(f'Cues: {scene_count} {cue_model} calls ({timeline_mode})')
        if args.phase1_only:
            log('Assignment: DEFERRED (--phase1-only)')
        elif args.check:
            log('Assignment: none (--check compares only)')
        else:
            batches = -(-len(all_ids) // 40)
            log(f'Assignment: {batches} {assign_model} call(s), batches of 40 scenes')
        sys.exit(0)

    # --- Cost forecast ---
    total_words = 0
    for sid in scene_ids:
        sf = os.path.join(project_dir, 'scenes', f'{sid}.md')
        if os.path.isfile(sf):
            with open(sf) as f:
                total_words += len(f.read().split())
    avg_words = max(total_words // max(scene_count, 1), 100)
    cue_cost = 0.0 if args.skip_phase1 else estimate_cost('extraction', scene_count, avg_words, cue_model)
    if timeline_mode == 'batch':
        cue_cost *= 0.5
    assign_cost = 0.0 if (args.phase1_only or args.check) else estimate_cost(
        'evaluation', -(-len(all_ids) // 40), 40 * 60, assign_model)
    log(f'Cost forecast: cues ~${cue_cost:.6f}, assignment ~${assign_cost:.6f}')
    if not check_threshold(cue_cost + assign_cost):
        log('Cost threshold exceeded. Aborting.')
        sys.exit(1)

    if args.check:
        _run_check(project_dir, scene_ids, cue_model, log_dir)
        return

    if not args.embedded:
        create_branch('timeline', project_dir)
        ensure_branch_pushed(project_dir)
        pr_body = f"""## Timeline

**Project:** {title}
**Scenes:** {scene_count}

### Tasks
- [ ] Read time cues per scene
- [ ] Place scenes on one calendar
"""
        create_draft_pr(f'Enrich: timeline for {title}', pr_body, project_dir, 'enrichment')

    # --- Cues ---
    stale_cues: list[str] = []
    if args.skip_phase1:
        cached = sum(1 for sid in scene_ids if sid in read_cues(project_dir))
        log(f'Skipping cue extraction: {cached} of {scene_count} scenes have stored cues')
    else:
        log('')
        log(f'Cues: reading time cues ({scene_count} scenes, mode: {timeline_mode})')
        if timeline_mode == 'batch':
            fresh = _extract_cues_batch(project_dir, scene_ids, cue_model, log_dir)
        else:
            fresh = extract_cues(project_dir, scene_ids, cue_model, log_dir)
        # A scene whose read failed keeps its earlier stored cues, if any,
        # which may describe older prose.
        stale_cues = [sid for sid in scene_ids if sid not in fresh]

    if args.phase1_only:
        if stale_cues:
            log(f'WARNING: no fresh cues for {len(stale_cues)} scene(s); they keep their '
                f'earlier cues, if any: {", ".join(stale_cues)}')
        log(f'Cues stored in {CUES_FILE}. Review or edit them, then run:')
        log('  storyforge timeline --skip-phase1')
        sys.exit(0)

    if not args.embedded:
        update_pr_task('Read time cues per scene', project_dir)
        if not os.path.isfile(interactive_file) and offer_interactive(
                project_dir, 'Assignment: place scenes on one calendar'):
            show_interactive_banner('Timeline -- Cues', 'single')

    # --- Assignment ---
    log('')
    log('Assignment: placing scenes on one calendar')
    result = run_assignment(project_dir, assign_model, log_dir, force=args.force)

    if os.path.isfile(interactive_file):
        lines = ['Timeline:', '']
        for sid in reading_order(project_dir):
            day = get_field(metadata_csv, sid, 'timeline_day') or '?'
            mode = get_field(metadata_csv, sid, 'time_mode') or 'scene'
            lines.append(f'  Day {day} ({mode}) -- {sid}')
        show_interactive_banner('Timeline -- Calendar', 'single')
        print('\n'.join(lines))

    if not args.embedded:
        commit_and_push(project_dir, 'Enrich: timeline (days and time modes)',
                        ['reference/scenes.csv', 'working/'])
        update_pr_task('Place scenes on one calendar', project_dir)
        try:
            os.remove(interactive_file)
        except FileNotFoundError:
            pass

    log('')
    log('============================================')
    log('Timeline complete')
    log(f'  Values set: {result["assigned"]}')
    log(f'  Proposed (already set, not changed): {result["proposed"]}')
    log(f'  Unplaced: {result["unplaced"]}')
    log(f'  Inconsistencies reported: {result["findings"]}')
    if stale_cues:
        log(f'  WARNING: no fresh cues for {len(stale_cues)} scene(s); the calendar '
            f'used their earlier cues, if any: {", ".join(stale_cues)}')
    log('============================================')

    if not args.embedded:
        print_summary(project_dir, 'timeline', session_start=session_start)


def _extract_cues_batch(project_dir, scene_ids, model, log_dir):
    """Cues via the Batch API (half price, slower). Returns the cues read."""
    prompts = cue_prompts(project_dir, scene_ids)
    if not prompts:
        log('No scenes with prose or a summary to read')
        return {}
    batch_file = os.path.join(log_dir, 'timeline-cues-batch.jsonl')
    with open(batch_file, 'w') as bf:
        for sid, prompt in prompts.items():
            bf.write(json.dumps(build_batch_request(sid, prompt, model, max_tokens=1024)) + '\n')
    log(f'Submitting batch with {len(prompts)} requests...')
    batch_id = submit_batch(batch_file)
    results_url = poll_batch(batch_id, log_fn=log)
    out_dir = os.path.join(log_dir, 'timeline-cues')
    os.makedirs(out_dir, exist_ok=True)
    # Only this batch's successes: a {sid}.txt left by an earlier extract or
    # score run must not be read as this scene's cues
    succeeded = set(download_batch_results(results_url, out_dir, log_dir) or [])
    cues = {}
    for sid in prompts:
        txt = os.path.join(log_dir, f'{sid}.txt')
        text = ''
        if sid in succeeded and os.path.isfile(txt):
            with open(txt) as f:
                text = f.read()
        if has_cues(text):
            cues[sid] = parse_cues(text)
        else:
            log(f'  WARNING: no cue result for {sid}')
    write_cues(project_dir, cues)
    log(f'Cues stored for {len(cues)} of {len(prompts)} scenes')
    return cues


def _run_check(project_dir, scene_ids, model, log_dir):
    """--check: read cues from the current prose, compare with the calendar.
    The stored cues, which the calendar was built from, are left alone; the
    check's own go to working/timeline-check-cues.csv."""
    from storyforge.elaborate import _read_csv
    fresh = extract_cues(project_dir, scene_ids, model, log_dir, store=False)
    write_cues(project_dir, fresh, CHECK_CUES_FILE)
    cues = {**read_cues(project_dir), **fresh}
    order = reading_order(project_dir)
    rows = {r['id']: r for r in _read_csv(os.path.join(project_dir, 'reference', 'scenes.csv'))}
    findings = check_timeline([rows[s] for s in order if s in rows], cues)
    report_findings(findings, limit=100)
    unread = [sid for sid in scene_ids if sid not in fresh]
    if unread:
        log(f'WARNING: no fresh cues for {len(unread)} scene(s), so they were checked '
            f'against their stored cues, which may describe older prose: {", ".join(unread)}')
