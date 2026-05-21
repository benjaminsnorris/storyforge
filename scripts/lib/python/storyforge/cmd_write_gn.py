"""storyforge write (graphic-novel mode) — Autonomous panel-script drafting.

Drafts panel scripts per scene. Same CLI as the novel-mode `write` command
but routed here when project.medium == 'graphic-novel'. Output goes to
scenes/{id}.md as a structured panel script.

Usage (identical to novel-mode write):
    storyforge write
    storyforge write the-blank-page
    storyforge write --scenes a,b,c
    storyforge write --act 2
    storyforge write --dry-run the-blank-page
"""

import argparse
import os
import sys

from storyforge.common import (
    detect_project_root, log, set_log_file, select_model,
    install_signal_handlers, get_medium,
)
from storyforge.runner import run_parallel
from storyforge.csv_cli import get_field, update_field, list_ids
from storyforge.scene_filter import build_scene_list, apply_scene_filter
from storyforge.script_format import count_pages, count_panels, check_brief_fidelity
from storyforge.api import invoke_to_file, extract_text_from_file
from storyforge.prompts_gn import build_drafting_prompt


def parse_args(argv):
    parser = argparse.ArgumentParser(
        prog='storyforge write (gn)',
        description='Draft GN panel scripts autonomously.',
    )
    parser.add_argument('positional', nargs='*', default=[],
                        help='Scene ID(s) to draft')
    parser.add_argument('--dry-run', action='store_true',
                        help='Build prompts without invoking Claude')
    parser.add_argument('--force', action='store_true',
                        help='Re-draft scenes even if already drafted')
    parser.add_argument('--direct', action='store_true',
                        help='Use direct API calls (not batch)')
    parser.add_argument('--scenes', type=str, default=None,
                        help='Comma-separated scene IDs')
    parser.add_argument('--act', '--part', type=str, default=None,
                        help='Draft all scenes in act/part N')
    parser.add_argument('--from-seq', type=str, default=None,
                        help='Start from sequence number (N or N-M range)')
    parser.add_argument('--parallel', type=int, default=1,
                        help='Number of parallel workers (default: 1)')
    return parser.parse_args(argv)


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


def _build_visual_refs(project_dir):
    """Read character-bible.md and world-bible.md for visual reference."""
    ref_dir = os.path.join(project_dir, 'reference')
    chars_path = os.path.join(ref_dir, 'character-bible.md')
    world_path = os.path.join(ref_dir, 'world-bible.md')
    char_text = open(chars_path).read() if os.path.isfile(chars_path) else ''
    world_text = open(world_path).read() if os.path.isfile(world_path) else ''
    return char_text, world_text


def _build_voice_text(project_dir):
    """Read voice-profile.csv as raw text for the prompt."""
    voice_path = os.path.join(project_dir, 'reference', 'voice-profile.csv')
    if os.path.isfile(voice_path):
        return open(voice_path).read()
    return ''


def _draft_one_scene(args_tuple):
    """Worker: draft one GN scene. Returns (scene_id, result_dict).

    This function is called both directly (sequential) and via
    run_parallel (multiprocess). All imports are local to stay picklable.
    """
    scene_id, project_dir, force, dry_run, model = args_tuple

    from storyforge.csv_cli import get_field, update_field
    from storyforge.script_format import count_pages, count_panels, check_brief_fidelity
    from storyforge.api import invoke_to_file, extract_text_from_file
    from storyforge.prompts_gn import build_drafting_prompt
    from storyforge.common import log

    ref_dir = os.path.join(project_dir, 'reference')
    scenes_csv = os.path.join(ref_dir, 'scenes.csv')

    # Skip already-drafted unless --force
    if not force:
        status = get_field(scenes_csv, scene_id, 'status')
        if status in ('drafted', 'revised', 'final'):
            return scene_id, {'skipped': True, 'reason': f'already {status}'}

    # Load CSV rows as dicts
    scene_row = _row_to_dict(scenes_csv, scene_id)
    intent_row = _row_to_dict(os.path.join(ref_dir, 'scene-intent.csv'), scene_id)
    brief_row = _row_to_dict(os.path.join(ref_dir, 'scene-briefs.csv'), scene_id)

    if not scene_row:
        return scene_id, {'error': 'missing scene row in scenes.csv'}
    if not brief_row:
        return scene_id, {'error': 'missing brief row in scene-briefs.csv'}

    char_visuals, loc_visuals = _build_visual_refs(project_dir)
    voice_text = _build_voice_text(project_dir)

    prompt = build_drafting_prompt(
        project_dir=project_dir,
        scene_id=scene_id,
        scene_row=scene_row,
        intent_row=intent_row,
        brief_row=brief_row,
        character_visuals=char_visuals,
        location_visuals=loc_visuals,
        voice_profile_text=voice_text,
    )

    if dry_run:
        return scene_id, {'dry_run': True, 'prompt': prompt}

    log_dir = os.path.join(project_dir, 'working', 'logs', 'write-gn')
    os.makedirs(log_dir, exist_ok=True)
    log_file = os.path.join(log_dir, f'{scene_id}.json')

    try:
        invoke_to_file(prompt, model, log_file, max_tokens=8192)
    except Exception as e:
        return scene_id, {'error': f'API call failed: {e}'}

    script_text = extract_text_from_file(log_file)
    if not script_text:
        return scene_id, {'error': 'empty API response'}

    # Write the scene file
    scenes_dir = os.path.join(project_dir, 'scenes')
    os.makedirs(scenes_dir, exist_ok=True)
    scene_path = os.path.join(scenes_dir, f'{scene_id}.md')
    with open(scene_path, 'w') as f:
        f.write(script_text)

    # Update CSV: page_count, panel_count, status
    pages = count_pages(script_text)
    panels = count_panels(script_text)
    update_field(scenes_csv, scene_id, 'page_count', str(pages))
    update_field(scenes_csv, scene_id, 'panel_count', str(panels))
    update_field(scenes_csv, scene_id, 'status', 'drafted')

    log(f'  {scene_id}: wrote {pages} pages, {panels} panels → scenes/{scene_id}.md')

    # Brief-fidelity check
    failures = check_brief_fidelity(brief_row, script_text)
    if failures:
        log(f'  {scene_id}: {len(failures)} fidelity warning(s)')
        for flaw in failures:
            log(f'    [{flaw["severity"]}] {flaw["kind"]}: {flaw["detail"]}')

    # Cost tracking (best-effort; don't fail drafting if ledger write fails)
    try:
        import json as _json
        from storyforge.api import extract_usage, calculate_cost_from_usage
        from storyforge.costs import log_operation
        with open(log_file) as f:
            resp = _json.load(f)
        usage = extract_usage(resp)
        cost = calculate_cost_from_usage(usage, model)
        log_operation(
            project_dir, 'write-gn', model,
            usage['input_tokens'], usage['output_tokens'], cost,
            target=scene_id,
            cache_read=usage.get('cache_read', 0),
            cache_create=usage.get('cache_create', 0),
        )
    except Exception:
        pass

    return scene_id, {
        'drafted': True,
        'pages': pages,
        'panels': panels,
        'fidelity_failures': len(failures),
    }


def main(argv=None):
    args = parse_args(argv if argv is not None else sys.argv[1:])
    install_signal_handlers()

    project_dir = detect_project_root()

    if get_medium(project_dir) != 'graphic-novel':
        log('ERROR: cmd_write_gn invoked on a non-graphic-novel project. '
            'Set project.medium: graphic-novel in storyforge.yaml.')
        sys.exit(1)

    ref_dir = os.path.join(project_dir, 'reference')
    scenes_csv = os.path.join(ref_dir, 'scenes.csv')

    log_dir = os.path.join(project_dir, 'working', 'logs')
    os.makedirs(log_dir, exist_ok=True)
    set_log_file(os.path.join(log_dir, 'write-gn-log.txt'))

    # Resolve scene IDs from CLI flags
    all_ids = build_scene_list(scenes_csv)

    if args.positional:
        if len(args.positional) == 1:
            ids = [args.positional[0]]
        elif len(args.positional) == 2:
            ids = apply_scene_filter(scenes_csv, all_ids, 'range',
                                     args.positional[0], args.positional[1])
        else:
            log('ERROR: Too many positional arguments. '
                'Provide one scene ID or two for a range.')
            sys.exit(1)
    elif args.scenes:
        ids = [s.strip() for s in args.scenes.split(',') if s.strip()]
    elif args.act:
        ids = apply_scene_filter(scenes_csv, all_ids, 'act', args.act, None)
    elif args.from_seq:
        ids = apply_scene_filter(scenes_csv, all_ids, 'from_seq',
                                 args.from_seq, None)
    else:
        ids = list(all_ids)

    if not ids:
        log('No scenes to draft.')
        return

    model = select_model('drafting')
    log(f'GN write: {len(ids)} scene(s), model={model}, '
        f'parallel={args.parallel}, dry_run={args.dry_run}')

    work = [
        (sid, project_dir, args.force, args.dry_run, model)
        for sid in ids
    ]

    if args.parallel > 1 and not args.dry_run:
        results = run_parallel(work, _draft_one_scene,
                               max_workers=args.parallel, label='scene')
    else:
        results = [_draft_one_scene(item) for item in work]

    # Report results
    drafted = 0
    for sid, result in results:
        if args.dry_run and result.get('dry_run'):
            print(f'===== DRY RUN: {sid} =====')
            print(result['prompt'])
            print(f'===== END DRY RUN: {sid} =====')
            print()
        elif result.get('skipped'):
            log(f'{sid}: skipped — {result["reason"]}')
        elif result.get('error'):
            log(f'{sid}: ERROR — {result["error"]}')
        elif result.get('drafted'):
            drafted += 1
            fidelity_note = (
                f', {result["fidelity_failures"]} fidelity warning(s)'
                if result['fidelity_failures'] else ''
            )
            log(f'{sid}: drafted {result["pages"]} page(s), '
                f'{result["panels"]} panel(s){fidelity_note}')

    if not args.dry_run:
        log(f'Done. {drafted}/{len(ids)} scene(s) drafted.')


if __name__ == '__main__':
    main()
