"""storyforge extract — Extract structural data from existing prose.

Extracts structural data from scene prose into the three-file CSV model:
  scenes.csv, scene-intent.csv, scene-briefs.csv

Usage:
    storyforge extract                        # Run all phases
    storyforge extract --phase 0              # Characterize only
    storyforge extract --phase 1              # Skeleton only
    storyforge extract --phase 2              # Intent only (needs phase 1)
    storyforge extract --phase 3              # Briefs only (needs phases 1-2)
    storyforge extract --expand               # Run expansion analysis after extraction
    storyforge extract --dry-run              # Print prompts without invoking
"""

import json
import os
import subprocess
import sys
import time
from datetime import datetime

import argparse

from storyforge.common import (
    detect_project_root, log, set_log_file, read_yaml_field, select_model,
    get_coaching_level, install_signal_handlers, get_plugin_dir,
    build_shared_context,
)
from storyforge.git import (
    create_branch, ensure_branch_pushed, create_draft_pr, commit_and_push,
    update_pr_task, run_review_phase,
)
from storyforge.api import (
    invoke_to_file, extract_text, extract_text_from_file, extract_usage, is_truncated,
    calculate_cost_from_usage, submit_batch, poll_batch, download_batch_results,
    build_batch_request, stop_problem,
)
from storyforge.costs import log_operation, print_summary


def parse_args(argv):
    parser = argparse.ArgumentParser(
        prog='storyforge extract',
        description='Extract structural data from existing prose.',
    )
    parser.add_argument('--phase', type=int, default=None,
                        help='Run only phase N (0=characterize, 1=skeleton, 2=intent, 3=briefs)')
    parser.add_argument('--cleanup', action='store_true',
                        help='Run cleanup after extraction')
    parser.add_argument('--cleanup-only', action='store_true',
                        help='Run cleanup only (skip extraction)')
    parser.add_argument('--force', action='store_true',
                        help='Overwrite existing field values')
    parser.add_argument('--expand', action='store_true',
                        help='Run expansion analysis after extraction')
    parser.add_argument('--dry-run', action='store_true',
                        help='Print prompts without invoking Claude')
    return parser.parse_args(argv)


def main(argv=None):
    args = parse_args(argv if argv is not None else sys.argv[1:])
    session_start = datetime.now().strftime('%Y-%m-%dT%H:%M:%S')

    install_signal_handlers()

    if args.cleanup_only:
        args.cleanup = True

    project_dir = detect_project_root()
    log_dir = os.path.join(project_dir, 'working', 'logs')
    os.makedirs(log_dir, exist_ok=True)

    # API key check
    if not args.dry_run and not args.cleanup_only and not os.environ.get('ANTHROPIC_API_KEY'):
        log('ERROR: ANTHROPIC_API_KEY not set. Required for extraction.')
        sys.exit(1)

    title = read_yaml_field('project.title', project_dir) or 'Untitled'
    ref_dir = os.path.join(project_dir, 'reference')
    scenes_dir = os.path.join(project_dir, 'scenes')
    plugin_dir = get_plugin_dir()

    # Check for scene files
    scene_files = [f for f in os.listdir(scenes_dir) if f.endswith('.md')]
    scene_count = len(scene_files)
    if scene_count == 0:
        log(f'ERROR: No scene files found in {scenes_dir}/')
        log("  Split your manuscript into scenes first using /storyforge:scenes (setup mode)")
        sys.exit(1)

    log('============================================')
    log('Storyforge Extract')
    log(f'Project: {title}')
    log(f'Scenes: {scene_count}')
    log('============================================')

    # Branch and PR
    if not args.dry_run:
        create_branch('extract', project_dir)
        ensure_branch_pushed(project_dir)

        pr_body = f"""## Extraction: Reverse Elaboration

**Project:** {title}
**Scenes:** {scene_count}

### Tasks
- [ ] Phase 0: Characterize manuscript
- [ ] Phase 1: Extract skeleton (scenes.csv)
- [ ] Phase 2: Extract intent (scene-intent.csv)
- [ ] Phase 3: Extract briefs (scene-briefs.csv)
- [ ] Validate
- [ ] Review"""
        create_draft_pr(f'Extract: {title} ({scene_count} scenes)',
                        pr_body, project_dir, 'extraction')

    # Build sorted scene list
    sorted_scene_ids = _build_sorted_scene_ids(scenes_dir, ref_dir)

    # Profile file location
    profile_file = os.path.join(project_dir, 'working', 'extraction-profile.json')

    # Shared context for prompt caching (built once, passed to all phases)
    model = select_model('evaluation')
    system = build_shared_context(project_dir, model=model)

    validate_passed = None
    validate_failures = 0
    _unanswered.clear()

    if not args.cleanup_only:
        # Phase 0: Characterize
        if args.phase is None or args.phase == 0:
            _run_phase_0(project_dir, scenes_dir, log_dir, profile_file,
                         args.dry_run, system=system)
            if not args.dry_run:
                commit_and_push(project_dir,
                                'Extract: Phase 0 — manuscript characterization',
                                ['working/'])
                update_pr_task('Phase 0: Characterize manuscript', project_dir)

        # Phase 1: Skeleton
        if args.phase is None or args.phase == 1:
            _run_phase_1(sorted_scene_ids, project_dir, scenes_dir, ref_dir,
                         log_dir, profile_file, plugin_dir, args.force,
                         args.dry_run, system=system)
            if not args.dry_run:
                commit_and_push(project_dir,
                                'Extract: Phase 1 — skeleton and timeline (scenes.csv)',
                                ['reference/scenes.csv', 'working/'])
                update_pr_task('Phase 1: Extract skeleton', project_dir)

                # Reconcile Phase 1 registries
                log('')
                log('--- Reconciling Phase 1 registries ---')
                _run_hone(plugin_dir, phase=1)

        # Phase 2: Intent
        if args.phase is None or args.phase == 2:
            _run_phase_2(sorted_scene_ids, project_dir, scenes_dir, ref_dir,
                         log_dir, profile_file, args.force, args.dry_run,
                         system=system)
            if not args.dry_run:
                commit_and_push(project_dir,
                                'Extract: Phase 2 — intent (scene-intent.csv)',
                                ['reference/scene-intent.csv', 'working/'])
                update_pr_task('Phase 2: Extract intent', project_dir)

                log('')
                log('--- Reconciling Phase 2 registries ---')
                _run_hone(plugin_dir, phase=2)

        # Phase 3: Briefs
        if args.phase is None or args.phase == 3:
            _run_phase_3(sorted_scene_ids, project_dir, scenes_dir, ref_dir,
                         log_dir, profile_file, args.force, args.dry_run,
                         system=system)
            if not args.dry_run:
                update_pr_task('Phase 3: Extract briefs', project_dir)

                log('')
                log('--- Reconciling Phase 3 registries ---')
                _run_hone(plugin_dir, phase=3)

    # Cleanup
    if not args.dry_run and (args.cleanup or (args.phase is None and not args.cleanup_only)):
        _run_cleanup(ref_dir, project_dir)

    # Validate
    if not args.dry_run:
        validate_passed, validate_failures = _run_validation(ref_dir, project_dir)
        update_pr_task('Validate', project_dir)

    # File cleanup
    if not args.dry_run:
        _cleanup_intermediates(log_dir, ref_dir, project_dir)

    # Expansion analysis
    if args.expand and not args.dry_run:
        _run_expansion(ref_dir)

    # Review
    if not args.dry_run:
        run_review_phase('extraction', project_dir)

    # Final summary
    log('')
    log('============================================')
    log('Extraction complete.')
    if validate_passed:
        log('  All validation checks pass.')
        log("  Next: run /storyforge:elaborate to continue development.")
    else:
        log(f'  {validate_failures} validation issue(s) remain.')
        log("  Next: run /storyforge:elaborate to fill structural gaps.")
    log('============================================')

    print_summary(project_dir, 'extract', session_start=session_start)
    if _unanswered:
        log('ERROR: some scenes got no usable extraction reply (refused, cut off, '
            'failed, unreadable or empty); re-run extract for them:')
        for csv_name, ids in _unanswered.items():
            log(f'  {csv_name}: {", ".join(ids)}')
        sys.exit(1)


# ============================================================================
# Helpers
# ============================================================================

def _build_sorted_scene_ids(scenes_dir: str, ref_dir: str) -> list[str]:
    """Build sorted scene ID list from scene files and optional CSV seq."""
    scene_ids = [f.removesuffix('.md') for f in os.listdir(scenes_dir)
                 if f.endswith('.md')]

    # Try to sort by seq from existing CSV
    seq_map = {}
    csv_path = os.path.join(ref_dir, 'scenes.csv')
    if os.path.isfile(csv_path):
        with open(csv_path) as f:
            lines = [l.strip() for l in f if l.strip()]
        if len(lines) > 1:
            header = lines[0].split('|')
            id_idx = header.index('id') if 'id' in header else 0
            seq_idx = header.index('seq') if 'seq' in header else 1
            for line in lines[1:]:
                fields = line.split('|')
                if len(fields) > max(id_idx, seq_idx):
                    try:
                        seq_map[fields[id_idx]] = int(fields[seq_idx])
                    except (ValueError, IndexError):
                        pass

    if seq_map:
        scene_ids.sort(key=lambda s: seq_map.get(s, 999))
    else:
        scene_ids.sort()

    return scene_ids


def _halt_chain(project_dir: str, phase: str, scene_id: str, error: Exception,
                paths: list[str]) -> None:
    """Stop a sequential extraction chain at a scene that could not be read.
    The scenes before it are complete and committed; nothing after it runs,
    since each later prompt would carry the gap."""
    log(f'ERROR: Phase {phase} stopped at {scene_id}: {error}')
    commit_and_push(project_dir, f'Extract: Phase {phase} (stopped at {scene_id})', paths)
    log('The scenes before it are saved. Fix the cause (see the log in working/logs/) '
        'and run extract again.')
    sys.exit(1)


def _log_api_usage(log_file: str, operation: str, target: str, model: str,
                   project_dir: str) -> None:
    """Log API usage/cost from a JSON response file."""
    try:
        with open(log_file) as f:
            response = json.load(f)
        usage = extract_usage(response)
        cost = calculate_cost_from_usage(usage, model)
        log_operation(
            project_dir, operation, model,
            usage['input_tokens'], usage['output_tokens'], cost,
            target=target,
            cache_read=usage.get('cache_read', 0),
            cache_create=usage.get('cache_create', 0),
        )
    except Exception:
        pass


def _run_hone(plugin_dir: str, phase: int) -> None:
    """Run storyforge-hone for a specific phase."""
    hone_script = os.path.join(plugin_dir, 'scripts', 'storyforge-hone')
    if os.path.isfile(hone_script) and os.access(hone_script, os.X_OK):
        try:
            subprocess.run([hone_script, '--phase', str(phase)],
                           capture_output=True)
        except Exception:
            log(f'WARNING: Hone phase {phase} failed')
    else:
        # Try Python cmd_hone directly
        try:
            from storyforge.cmd_hone import main as hone_main
            hone_main(['--phase', str(phase)])
        except Exception as e:
            log(f'WARNING: Hone phase {phase} failed: {e}')


# ============================================================================
# Phase 0: Characterize
# ============================================================================

def _merge_fields(row: dict, result: dict, force: bool) -> bool:
    """Copy extracted values into an existing CSV row; return whether it changed.

    Empty fields are filled; populated ones are overwritten only with force.
    Keys starting with '_' (e.g. _confidence) are response metadata, not columns.
    """
    changed = False
    for k, v in result.items():
        if not v or k == 'id' or k.startswith('_'):
            continue
        if (force or not row.get(k, '').strip()) and row.get(k) != v:
            row[k] = v
            changed = True
    return changed


def _merge_batch_results(csv_path, csv_name, sorted_scene_ids, log_dir, parse,
                         alias_maps, force, new_row=None,
                         sort_key=lambda r: r.get('id', '')) -> int:
    """Merge per-scene batch responses ({log_dir}/{scene_id}.txt) into a scene CSV.

    Scenes with a row are merged per _merge_fields; scenes without one get a
    new row (new_row(row, index, scene_id) can fill extra columns). A .txt
    exists only for a reply the batch download marked ok (it removes a stale
    one), so a scene without one had no usable reply: it is left as it was
    and named in a WARNING, and the run exits 1 at the end. Returns the
    number of scenes added or changed.
    """
    from storyforge.elaborate import _read_csv_as_map, _write_csv, _FILE_MAP
    from storyforge.enrich import normalize_fields

    columns = _FILE_MAP[csv_name]
    existing = _read_csv_as_map(csv_path)
    count = 0
    unanswered = []
    for i, sid in enumerate(sorted_scene_ids):
        txt_file = os.path.join(log_dir, f'{sid}.txt')
        if not os.path.isfile(txt_file):
            unanswered.append(sid)
            continue
        with open(txt_file) as f:
            try:
                result = parse(f.read(), sid)
            except ValueError as e:  # a structured reply that can't be read
                log(f'  WARNING: {csv_name}: the reply for {sid} is unreadable: {e}')
                unanswered.append(sid)
                continue
        if not any(v for k, v in result.items() if k != 'id' and not k.startswith('_')):
            # Every field unknown or empty: nothing was extracted, which is not "nothing changed"
            log(f'  WARNING: {csv_name}: the reply for {sid} holds no values')
            unanswered.append(sid)
            continue
        normalize_fields(result, alias_maps)

        if sid in existing:
            count += _merge_fields(existing[sid], result, force)
        else:
            row = {c: '' for c in columns}
            _merge_fields(row, result, force=True)
            row['id'] = sid
            if new_row:
                new_row(row, i, sid)
            existing[sid] = row
            count += 1

    _write_csv(csv_path, sorted(existing.values(), key=sort_key), columns)
    if unanswered:
        missing = [sid for sid in unanswered if sid not in existing]
        log(f'  WARNING: {csv_name}: no usable reply for {len(unanswered)} scene(s), '
            f'left as they were: {", ".join(unanswered)}')
        if missing:
            log(f'  WARNING: {csv_name} has no row for {", ".join(missing)}')
        _unanswered.setdefault(csv_name, []).extend(unanswered)
    return count


# Scenes each CSV merge got no usable reply for in this run (csv -> ids);
# the final summary names them and the run exits 1.
_unanswered: dict[str, list[str]] = {}


def _log_merge(csv_name: str, changed: int, total: int, suffix: str = '') -> None:
    log(f'  Updated {csv_name}: {changed} of {total} scenes changed{suffix}')


def _run_phase_0(project_dir, scenes_dir, log_dir, profile_file, dry_run,
                 system=None):
    log('')
    log('--- Phase 0: Characterize manuscript ---')

    from storyforge.extract import (
        CHARACTERIZE_SCHEMA, build_characterize_prompt, parse_characterize_response,
    )

    model = select_model('synthesis')  # Opus for full-manuscript comprehension
    prompt = build_characterize_prompt(project_dir, model=model)
    if not prompt:
        log('ERROR: Could not build characterize prompt — no manuscript content found')
        sys.exit(1)

    if dry_run:
        print('===== DRY RUN: Phase 0 (characterize) =====')
        print(prompt[:500])
        print(f'... ({len(prompt)} chars total)')
        print('===== END DRY RUN =====')
        return

    char_log = os.path.join(log_dir, 'extract-phase0.json')

    log(f'  Invoking {model} for manuscript characterization...')

    response = invoke_to_file(prompt, model, char_log, 4096, system=system,
                              output_schema=CHARACTERIZE_SCHEMA)
    _log_api_usage(char_log, 'extract-characterize', 'manuscript', model, project_dir)
    # Every later phase reads this profile: a cut-off or unreadable one
    # stops the run rather than steer them with missing fields.
    try:
        if is_truncated(response):
            raise ValueError(stop_problem(response))
        profile = parse_characterize_response(extract_text(response))
        if not profile:
            raise ValueError('every field is empty or unknown')
    except ValueError as e:
        log(f'ERROR: manuscript characterization failed: {e}')
        sys.exit(1)
    with open(profile_file, 'w') as f:
        json.dump(profile, f, indent=2)

    log(f'  Characterized: {len(profile)} fields extracted')
    for k, v in sorted(profile.items()):
        log(f'  {k}: {str(v)[:80]}')


# ============================================================================
# Phase 1: Skeleton (scenes.csv)
# ============================================================================

def _run_phase_1(sorted_scene_ids, project_dir, scenes_dir, ref_dir, log_dir,
                 profile_file, plugin_dir, force, dry_run, system=None):
    log('')
    log('--- Phase 1: Extract skeleton (scenes.csv) ---')

    from storyforge.extract import (
        SKELETON_SCHEMA, build_skeleton_prompt, parse_skeleton_response, skeleton_cues,
    )
    from storyforge.enrich import format_registries_for_prompt, load_registry_alias_maps, normalize_fields
    from storyforge.elaborate import _read_csv_as_map, _write_csv, _FILE_MAP

    profile = _load_profile(profile_file)
    registries = format_registries_for_prompt(project_dir)

    if dry_run:
        sample_id = sorted_scene_ids[0] if sorted_scene_ids else ''
        if sample_id:
            with open(os.path.join(scenes_dir, f'{sample_id}.md')) as f:
                sample_text = '\n'.join(f.readlines()[:20])
            prompt = build_skeleton_prompt(sample_id, sample_text, profile,
                                           registries_text=registries)
            print(f'===== DRY RUN: Phase 1 (skeleton) — sample for {sample_id} =====')
            print(prompt[:500])
            print(f'... ({len(sorted_scene_ids)} scenes total)')
            print('===== END DRY RUN =====')
        return

    model = select_model('evaluation')  # Sonnet for structured extraction

    # Build batch JSONL
    batch_file = os.path.join(log_dir, 'extract-phase1-batch.jsonl')
    _safe_remove(batch_file)

    log(f'  Building batch for {len(sorted_scene_ids)} scenes...')
    from storyforge.timeline import tail_words
    previous_text = ''
    batched = []
    for scene_id in sorted_scene_ids:
        scene_path = os.path.join(scenes_dir, f'{scene_id}.md')
        if not os.path.isfile(scene_path):
            continue
        with open(scene_path) as f:
            scene_text = f.read()
        if not scene_text:
            continue
        batched.append(scene_id)

        prompt = build_skeleton_prompt(scene_id, scene_text, profile,
                                        registries_text=registries,
                                        previous_tail=tail_words(previous_text))
        previous_text = scene_text
        request = build_batch_request(scene_id, prompt, model, 1024,
                                      system=system, output_schema=SKELETON_SCHEMA)
        with open(batch_file, 'a') as f:
            f.write(json.dumps(request) + '\n')

    log('  Submitting batch...')
    batch_id = submit_batch(batch_file)
    results_url = poll_batch(batch_id, log_fn=log)

    skel_output = os.path.join(log_dir, 'extract-phase1-output')
    os.makedirs(skel_output, exist_ok=True)
    succeeded = set(download_batch_results(results_url, skel_output, log_dir) or [])

    # Process results
    log('  Processing skeleton results...')
    alias_maps = load_registry_alias_maps(project_dir)

    def new_skeleton_row(row, i, sid):
        row['seq'] = str(i + 1)
        row['status'] = 'drafted'
        scene_file = os.path.join(scenes_dir, f'{sid}.md')
        if os.path.isfile(scene_file):
            with open(scene_file) as f:
                row['word_count'] = str(len(f.read().split()))

    count = _merge_batch_results(
        os.path.join(ref_dir, 'scenes.csv'), 'scenes.csv', sorted_scene_ids,
        log_dir, parse_skeleton_response, alias_maps, force,
        new_row=new_skeleton_row, sort_key=lambda r: int(r.get('seq') or 0))
    _log_merge('scenes.csv', count, len(sorted_scene_ids))

    # The timeline pass: store each scene's time cues, then place every scene
    # on one calendar. Nobody authored these days, so they are replaced.
    from storyforge.timeline import write_cues, run_assignment
    cues = {}
    rejected = set(_unanswered.get('scenes.csv', []))
    for sid in sorted_scene_ids:
        txt_file = os.path.join(log_dir, f'{sid}.txt')
        # Only this batch's answers (never a stale file from an earlier run),
        # and only those the scenes.csv merge accepted: a reply with cues but
        # no scene values was named as unusable there
        if sid in succeeded and sid not in rejected and os.path.isfile(txt_file):
            with open(txt_file) as f:
                try:
                    cues[sid] = skeleton_cues(f.read())
                except ValueError:
                    pass  # the scenes.csv merge above named it; no cues for it below
    write_cues(project_dir, cues)
    # A calendar is one piece: placing it without one scene's fresh cues
    # (an earlier run's, or none) would move its neighbours too, and with
    # force the wrong days would replace every scene's.
    no_cues = [sid for sid in batched if sid not in cues]
    if no_cues:
        log(f'  ERROR: timeline not placed: no fresh time cues for {len(no_cues)} scene(s) '
            f'({", ".join(no_cues)}); every day is left as it was')
        _unanswered.setdefault('timeline (not placed)', []).extend(no_cues)
    else:
        log('  Placing scenes on the calendar...')
        result = run_assignment(project_dir, select_model('evaluation'), log_dir, force=True)
        log(f'  Timeline: {result["assigned"]} value(s) set, {result["unplaced"]} scene(s) unplaced')

    _safe_remove(batch_file)
    _safe_rmdir(skel_output)


# ============================================================================
# Phase 2: Intent (scene-intent.csv)
# ============================================================================

def _run_phase_2(sorted_scene_ids, project_dir, scenes_dir, ref_dir, log_dir,
                 profile_file, force, dry_run, system=None):
    log('')
    log('--- Phase 2: Extract intent (scene-intent.csv) ---')

    if dry_run:
        print(f'===== DRY RUN: Phase 2 (intent) — {len(sorted_scene_ids)} scenes =====')
        print('===== END DRY RUN =====')
        return

    from storyforge.extract import INTENT_SCHEMA, build_intent_prompt, parse_intent_response
    from storyforge.elaborate import get_scene, _read_csv_as_map, _write_csv, _FILE_MAP
    from storyforge.enrich import format_registries_for_prompt, load_registry_alias_maps, normalize_fields

    model = select_model('evaluation')
    profile = _load_profile(profile_file)
    registries = format_registries_for_prompt(project_dir)

    batch_file = os.path.join(log_dir, 'extract-phase2-batch.jsonl')
    _safe_remove(batch_file)

    log(f'  Building batch for {len(sorted_scene_ids)} scenes...')
    for scene_id in sorted_scene_ids:
        skeleton = get_scene(scene_id, ref_dir) or {}
        scene_path = os.path.join(scenes_dir, f'{scene_id}.md')
        if not os.path.isfile(scene_path):
            continue
        with open(scene_path) as f:
            scene_text = f.read()

        prompt = build_intent_prompt(scene_id, scene_text, profile, skeleton,
                                      registries_text=registries)
        request = build_batch_request(scene_id, prompt, model, 1024,
                                      system=system, output_schema=INTENT_SCHEMA)
        with open(batch_file, 'a') as f:
            f.write(json.dumps(request) + '\n')

    log('  Submitting batch...')
    batch_id = submit_batch(batch_file)
    results_url = poll_batch(batch_id, log_fn=log)

    intent_output = os.path.join(log_dir, 'extract-phase2-output')
    os.makedirs(intent_output, exist_ok=True)
    download_batch_results(results_url, intent_output, log_dir)

    # Process results
    log('  Processing intent results...')
    alias_maps = load_registry_alias_maps(project_dir)

    count = _merge_batch_results(
        os.path.join(ref_dir, 'scene-intent.csv'), 'scene-intent.csv',
        sorted_scene_ids, log_dir, parse_intent_response, alias_maps, force)
    _log_merge('scene-intent.csv', count, len(sorted_scene_ids))

    _safe_remove(batch_file)
    _safe_rmdir(intent_output)


# ============================================================================
# Phase 3: Briefs (scene-briefs.csv)
# ============================================================================

def _record_physical_states(phys_csv, scene_id, new_states, resolved, character_aliases):
    """Add a scene's new physical states to the registry and record where
    states resolve.

    A state the scene resolves gets ``resolves`` set to the scene, unless an
    earlier scene already resolved it. Without this every state stayed
    ``never``, and validate flagged each one as vanishing in the scene the
    text ends it (F-057).
    """
    from storyforge.elaborate import _read_csv_as_map, _write_csv
    from storyforge.enrich import normalize_aliases

    if not new_states and not resolved:
        return
    columns = ['id', 'character', 'description', 'category',
               'acquired', 'resolves', 'action_gating']
    existing_phys = _read_csv_as_map(phys_csv)
    for ns in new_states:
        sid_key = ns.get('id', '').strip()
        if not sid_key or sid_key in existing_phys:
            continue
        row = {c: '' for c in columns}
        row['id'] = sid_key
        row['character'] = normalize_aliases(character_aliases, ns.get('character', ''))
        row['description'] = ns.get('description', '')
        row['category'] = ns.get('category', '')
        row['acquired'] = scene_id
        row['resolves'] = 'never'
        row['action_gating'] = ns.get('action_gating', 'false')
        existing_phys[sid_key] = row
    for state_id in (r.strip() for r in resolved):
        row = existing_phys.get(state_id)
        if row is not None and row.get('resolves', '').strip() in ('', 'never'):
            row['resolves'] = scene_id
    _write_csv(phys_csv, list(existing_phys.values()), columns)


def _prune_registries(ref_dir, created_facts, created_states):
    """After a forced phase 3, drop registry entries nothing uses (F-083).

    A forced re-extraction seeds knowledge.csv and physical-states.csv from
    the last run, so old entries piled up beside the new ones: under two
    names, and still active by their old acquired/resolves scenes, which
    validate then flagged. Keep an entry a brief references or this pass
    declared; drop the rest and log their ids. Hand edits on an entry still
    in use survive, and a scene this run didn't touch keeps what it uses.
    """
    from storyforge.elaborate import _read_csv_as_map, _write_csv

    briefs = _read_csv_as_map(os.path.join(ref_dir, 'scene-briefs.csv'))
    for name, fields, created in (
            ('knowledge.csv', ('knowledge_in', 'knowledge_out'), created_facts),
            ('physical-states.csv', ('physical_state_in', 'physical_state_out'),
             created_states)):
        path = os.path.join(ref_dir, name)
        if not os.path.isfile(path):
            continue
        used = {i.strip() for row in briefs.values() for f in fields
                for i in (row.get(f) or '').split(';') if i.strip()}
        registry = _read_csv_as_map(path)
        keep = {k: r for k, r in registry.items() if k in used or k in created}
        dropped = sorted(set(registry) - set(keep))
        if not dropped:
            continue
        with open(path) as f:
            columns = f.readline().strip().split('|')
        _write_csv(path, list(keep.values()), columns)
        log(f'  {name}: dropped {len(dropped)} entries no brief uses '
            f'(left from the previous extraction): {", ".join(dropped)}')


def _update_chain_fields(scene_id, ref_dir, result, force, keys):
    """Write a 3b/3c chain reply's fields to the scene's brief.

    The parsers leave out empty fields, so without force an empty answer
    keeps what the brief had. With force the reply is the scene's whole
    answer: an empty field clears the old value. Otherwise a re-extraction
    keeps the last run's knowledge and states wherever the new reply found
    none (Gatsby's lunch with Wolfshiem kept Myrtle's broken nose).
    """
    from storyforge.elaborate import update_scene
    updates = {k: result.get(k, '') for k in keys if force or result.get(k)}
    if updates:
        update_scene(scene_id, ref_dir, updates)


def _run_phase_3(sorted_scene_ids, project_dir, scenes_dir, ref_dir, log_dir,
                 profile_file, force, dry_run, system=None):
    """Run Phase 3a (parallel briefs) + 3b (knowledge chain) + 3c (physical state)."""

    # Phase 3a: Parallel brief fields
    log('')
    log('--- Phase 3a: Extract briefs (parallel fields) ---')

    if dry_run:
        print(f'===== DRY RUN: Phase 3a (briefs parallel) — {len(sorted_scene_ids)} scenes =====')
        print('===== END DRY RUN =====')
        return

    from storyforge.extract import (
        BRIEF_PARALLEL_SCHEMA, build_brief_parallel_prompt, parse_brief_parallel_response,
        build_knowledge_prompt, parse_knowledge_response, KNOWLEDGE_SCHEMA,
        merge_new_knowledge_facts, resolve_knowledge_ids, KNOWLEDGE_COLUMNS,
        build_physical_state_prompt, parse_physical_state_response, PHYSICAL_STATE_SCHEMA,
    )
    from storyforge.elaborate import (
        get_scene, update_scene, _read_csv_as_map, _write_csv, _FILE_MAP,
    )
    from storyforge.enrich import (
        format_registries_for_prompt, load_registry_alias_maps, normalize_aliases,
        normalize_fields,
    )

    model = select_model('evaluation')
    profile = _load_profile(profile_file)
    registries = format_registries_for_prompt(project_dir)
    alias_maps = load_registry_alias_maps(project_dir)

    # 3a: Batch parallel fields
    batch_file = os.path.join(log_dir, 'extract-phase3a-batch.jsonl')
    _safe_remove(batch_file)

    log(f'  Building batch for {len(sorted_scene_ids)} scenes...')
    for scene_id in sorted_scene_ids:
        scene_data = get_scene(scene_id, ref_dir) or {}
        skeleton = {k: scene_data.get(k, '') for k in ['title', 'pov', 'location', 'act']}
        intent = {k: scene_data.get(k, '') for k in
                  ['function', 'action_sequel', 'value_at_stake', 'value_shift', 'emotional_arc']}

        scene_path = os.path.join(scenes_dir, f'{scene_id}.md')
        if not os.path.isfile(scene_path):
            continue
        with open(scene_path) as f:
            scene_text = f.read()

        prompt = build_brief_parallel_prompt(scene_id, scene_text, profile,
                                              skeleton, intent,
                                              registries_text=registries)
        request = build_batch_request(scene_id, prompt, model, 1024,
                                      system=system, output_schema=BRIEF_PARALLEL_SCHEMA)
        with open(batch_file, 'a') as f:
            f.write(json.dumps(request) + '\n')

    log('  Submitting batch...')
    batch_id = submit_batch(batch_file)
    results_url = poll_batch(batch_id, log_fn=log)

    brief_output = os.path.join(log_dir, 'extract-phase3a-output')
    os.makedirs(brief_output, exist_ok=True)
    download_batch_results(results_url, brief_output, log_dir)

    # Process results
    log('  Processing brief results...')
    count = _merge_batch_results(
        os.path.join(ref_dir, 'scene-briefs.csv'), 'scene-briefs.csv',
        sorted_scene_ids, log_dir, parse_brief_parallel_response, alias_maps, force)
    _log_merge('scene-briefs.csv', count, len(sorted_scene_ids),
               ' (knowledge fields pending)')

    commit_and_push(project_dir,
                    'Extract: Phase 3a — briefs (parallel fields)',
                    ['reference/scene-briefs.csv', 'working/'])
    _safe_remove(batch_file)
    _safe_rmdir(brief_output)

    # --- Phase 3b: Knowledge chain (sequential) ---
    log('')
    log('--- Phase 3b: Extract knowledge chain (sequential) ---')

    knowledge_model = select_model('evaluation')
    knowledge_state = {}
    summaries = []
    # knowledge_in/out are registry-backed: build knowledge.csv as the chain
    # is extracted, so each scene's prompt can offer the ids established so
    # far and the fields are written as ids, not sentences. Seeded from an
    # existing registry so a re-extraction reuses its ids.
    knowledge_csv = os.path.join(ref_dir, 'knowledge.csv')
    knowledge_registry = {fid: row for fid, row in _read_csv_as_map(knowledge_csv).items()
                          if fid}
    knowledge_registries = format_registries_for_prompt(
        project_dir, exclude=('knowledge.csv',))
    created_facts = set()   # knowledge ids this pass declared

    for scene_id in sorted_scene_ids:
        scene_path = os.path.join(scenes_dir, f'{scene_id}.md')
        if not os.path.isfile(scene_path):
            continue
        with open(scene_path) as f:
            scene_text = f.read()
        if not scene_text:
            continue

        scene_data = get_scene(scene_id, ref_dir) or {}
        skeleton = {k: scene_data.get(k, '') for k in ['title', 'pov', 'location', 'act']}
        intent = {k: scene_data.get(k, '') for k in ['function', 'action_sequel']}

        prompt = build_knowledge_prompt(
            scene_id, scene_text, skeleton, intent, knowledge_state, summaries,
            registries_text=knowledge_registries,
            known_facts={fid: row.get('name', '')
                         for fid, row in knowledge_registry.items()})

        knowledge_log = os.path.join(log_dir, f'extract-knowledge-{scene_id}.json')

        # Each scene's prompt carries the chain so far: a scene that fails
        # can't be skipped without every later scene inheriting the gap
        try:
            response = invoke_to_file(prompt, knowledge_model, knowledge_log,
                                      1024, system=system,
                                      output_schema=KNOWLEDGE_SCHEMA)
            _log_api_usage(knowledge_log, 'extract-knowledge', scene_id,
                           knowledge_model, project_dir)
            if is_truncated(response):
                raise ValueError('the reply hit its token limit')
            result = parse_knowledge_response(extract_text(response), scene_id)
        except Exception as e:
            _halt_chain(project_dir, '3b — knowledge chain', scene_id, e,
                        ['reference/scene-briefs.csv', 'reference/knowledge.csv', 'working/'])

        # Register the scene's new facts, then resolve both fields to ids
        added = merge_new_knowledge_facts(knowledge_registry,
                                          result.get('_new_facts', []), scene_id)
        created_facts.update(added)
        if added:
            _write_csv(knowledge_csv, list(knowledge_registry.values()),
                       KNOWLEDGE_COLUMNS)
        for k in ('knowledge_in', 'knowledge_out'):
            if result.get(k):
                result[k] = resolve_knowledge_ids(knowledge_registry, result[k])

        # Update briefs CSV
        _update_chain_fields(scene_id, ref_dir, result, force,
                             ('knowledge_in', 'knowledge_out', 'continuity_deps'))

        # Accumulate state
        pov = scene_data.get('pov', '')
        k_out = result.get('knowledge_out', '')
        if pov and k_out:
            knowledge_state[pov] = k_out

        summary = result.get('_summary', '')
        if summary:
            summaries.append(f'{scene_id}: {summary}')

        log(f'  {scene_id}: knowledge extracted')

    commit_and_push(project_dir,
                    'Extract: Phase 3b — knowledge chain',
                    ['reference/scene-briefs.csv', 'reference/knowledge.csv',
                     'working/'])

    # --- Phase 3c: Physical state chain (sequential) ---
    log('')
    log('--- Phase 3c: Extract physical state chain (sequential) ---')

    phys_model = select_model('evaluation')
    phys_states = {}  # dict[str, set[str]]: character -> active state IDs
    created_states = set()   # state ids this pass declared
    phys_summaries = []

    for scene_id in sorted_scene_ids:
        scene_path = os.path.join(scenes_dir, f'{scene_id}.md')
        if not os.path.isfile(scene_path):
            continue
        with open(scene_path) as f:
            scene_text = f.read()
        if not scene_text:
            continue

        scene_data = get_scene(scene_id, ref_dir) or {}
        skeleton = {k: scene_data.get(k, '')
                    for k in ['title', 'pov', 'location', 'act', 'on_stage']}

        prompt = build_physical_state_prompt(scene_id, scene_text, skeleton,
                                              phys_states, phys_summaries,
                                              registries_text=registries)

        phys_log = os.path.join(log_dir, f'extract-physical-{scene_id}.json')

        try:
            response = invoke_to_file(prompt, phys_model, phys_log, 1024,
                                      system=system,
                                      output_schema=PHYSICAL_STATE_SCHEMA)
            _log_api_usage(phys_log, 'extract-physical', scene_id,
                           phys_model, project_dir)
            if is_truncated(response):
                raise ValueError('the reply hit its token limit')
            result = parse_physical_state_response(extract_text(response), scene_id)
        except Exception as e:
            _halt_chain(project_dir, '3c — physical state chain', scene_id, e,
                        ['reference/scene-briefs.csv', 'reference/physical-states.csv',
                         'working/'])

        # Update briefs CSV
        _update_chain_fields(scene_id, ref_dir, result, force,
                             ('physical_state_in', 'physical_state_out'))

        new_states = result.get('_new_states', [])
        resolved = result.get('_resolved', [])
        _record_physical_states(os.path.join(ref_dir, 'physical-states.csv'),
                                scene_id, new_states, resolved,
                                alias_maps.get('characters', {}))

        # Accumulate state
        for ns in new_states:
            sid_key = ns.get('id', '').strip()
            created_states.add(sid_key)
            char = ns.get('character', '').strip()
            if sid_key and char:
                phys_states.setdefault(char, set())
                phys_states[char].add(sid_key)
        for r in resolved:
            r = r.strip()
            for char in phys_states:
                phys_states[char].discard(r)

        # Summary
        acquired_ids = [ns.get('id', '') for ns in new_states]
        summary_parts = []
        if acquired_ids:
            summary_parts.append('acquired: ' + ', '.join(acquired_ids))
        if resolved:
            summary_parts.append('resolved: ' + ', '.join(resolved))
        summary = '; '.join(summary_parts) if summary_parts else 'no state changes'
        phys_summaries.append(f'{scene_id}: {summary}')

        log(f'  {scene_id}: physical states extracted')

    if force:
        _prune_registries(ref_dir, created_facts, created_states)

    commit_and_push(project_dir,
                    'Extract: Phase 3c — physical state chain',
                    ['reference/scene-briefs.csv', 'reference/physical-states.csv',
                     'reference/knowledge.csv', 'working/'])


# ============================================================================
# Cleanup, validation, expansion
# ============================================================================

def _run_cleanup(ref_dir: str, project_dir: str) -> None:
    """Run post-extraction cleanup."""
    log('')
    log('--- Post-extraction cleanup ---')

    coaching = get_coaching_level(project_dir)

    if coaching == 'strict':
        log('  Coaching level: strict — reporting issues only')
        from storyforge.elaborate import validate_structure
        report = validate_structure(ref_dir)
        categories = {}
        for f in report['failures']:
            cat = f['category']
            categories.setdefault(cat, []).append(f)
        for cat, failures in sorted(categories.items()):
            log(f'  {cat}: {len(failures)} issue(s)')
            for fail in failures[:3]:
                scene = fail.get('scene_id', '')
                log(f'    [{scene}] {fail["message"][:100]}')
            if len(failures) > 3:
                log(f'    ... and {len(failures) - 3} more')
        log(f'  Total: {len(report["failures"])} issues for author to review')
    else:
        from storyforge.extract import run_cleanup
        result = run_cleanup(ref_dir)
        total_fixes = result.get('total_fixes', 0)

        if total_fixes > 0:
            log(f'  Cleanup applied {total_fixes} fixes:')
            for cat in ('timeline', 'knowledge', 'mice_threads'):
                data = result.get(cat, {})
                if data.get('count', 0) > 0:
                    log(f'    {cat}: {data["count"]} fixes')
                    for fix in data.get('fixes', [])[:3]:
                        sid = fix.get('scene_id', '')
                        old = fix.get('old_value', '')
                        new = fix.get('new_value', '')
                        log(f'      {sid}: {old[:40]} -> {new[:40]}')
                    if data['count'] > 3:
                        log(f'      ... and {data["count"] - 3} more')

            commit_and_push(project_dir,
                            f'Extract: cleanup — {total_fixes} fixes (timeline, knowledge, MICE)',
                            ['reference/'])
        else:
            log('  No cleanup fixes needed')


def _run_validation(ref_dir: str, project_dir: str) -> tuple:
    """Run validation. Returns (passed: bool, failure_count: int)."""
    log('')
    log('--- Running validation ---')

    from storyforge.elaborate import validate_structure
    from storyforge.schema import validate_schema
    report = validate_structure(ref_dir)
    # The schema check too, as `storyforge validate` runs it: without it,
    # extraction reported a clean pass over invalid cells (F-058)
    schema = validate_schema(ref_dir, project_dir)

    passed = report['passed'] and schema['failed'] == 0
    # A passing structural report still lists its advisories; count them
    # only when they fail it
    failures = (0 if report['passed'] else len(report['failures'])) + schema['failed']

    if passed:
        log('Validation passed')
    else:
        log(f'Validation found {failures} issue(s) — review recommended')
        for err in schema['errors'][:5]:
            log(f'  schema: {err["file"]} {err["row"]} {err["column"]} = {str(err["value"])[:60]}')
        if schema['failed'] > 5:
            log(f'  ... and {schema["failed"] - 5} more (run ./storyforge validate)')

    return passed, failures


def _cleanup_intermediates(log_dir: str, ref_dir: str, project_dir: str) -> None:
    """Remove intermediate extraction files."""
    log('')
    log('--- Cleaning up ---')

    cleaned = 0

    # Intermediate files
    for f in [
        os.path.join(log_dir, '.knowledge-state.json'),
        os.path.join(log_dir, '.scene-summaries.txt'),
        os.path.join(log_dir, '.physical-state.json'),
        os.path.join(log_dir, '.physical-summaries.txt'),
        os.path.join(log_dir, 'extract-phase0.log'),
        os.path.join(log_dir, 'extract-phase1-batch.jsonl'),
        os.path.join(log_dir, 'extract-phase2-batch.jsonl'),
        os.path.join(log_dir, 'extract-phase3a-batch.jsonl'),
    ]:
        if os.path.isfile(f):
            os.remove(f)
            cleaned += 1

    # Batch output directories
    for d in ['phase1-output', 'phase1-logs', 'phase2-output',
              'phase2-logs', 'phase3a-output', 'phase3a-logs']:
        path = os.path.join(log_dir, d)
        if os.path.isdir(path):
            import shutil
            shutil.rmtree(path)
            cleaned += 1

    # Legacy files
    if os.path.isfile(os.path.join(ref_dir, 'scenes.csv')):
        for f in [
            os.path.join(ref_dir, 'scene-metadata.csv'),
            os.path.join(ref_dir, 'scenes', 'intent.csv'),
            os.path.join(project_dir, 'working', 'pipeline.yaml'),
            os.path.join(project_dir, 'working', 'assemble.py'),
        ]:
            if os.path.isfile(f):
                log(f'  Removing legacy file: {os.path.basename(f)}')
                os.remove(f)
                cleaned += 1

    if cleaned > 0:
        log(f'  Removed {cleaned} intermediate/legacy file(s)')


def _run_expansion(ref_dir: str) -> None:
    """Run expansion analysis."""
    log('')
    log('--- Expansion analysis ---')

    from storyforge.extract import analyze_expansion_opportunities
    opps = analyze_expansion_opportunities(ref_dir)

    if not opps:
        log('No expansion opportunities identified.')
    else:
        log(f'{len(opps)} expansion opportunities:')
        for o in opps:
            log(f'  [{o["priority"]}] {o["type"]}: {o["description"]} ({o["scene_id"]})')


# ============================================================================
# Utility
# ============================================================================

def _load_profile(profile_file: str) -> dict:
    """Load the extraction profile (Phase 0). A missing one is reported, since
    the later phases' prompts then go without the manuscript's context; an
    unreadable one stops the run."""
    if not os.path.isfile(profile_file):
        log(f'  WARNING: no manuscript profile at {profile_file}; this phase runs '
            f'without it. Run extract --phase 0 first for better results.')
        return {}
    try:
        with open(profile_file) as f:
            profile = json.load(f)
        if not isinstance(profile, dict):
            raise ValueError('not a JSON object')
        return profile
    except ValueError as e:
        log(f'ERROR: the manuscript profile at {profile_file} is unreadable ({e}); '
            f're-run extract --phase 0')
        sys.exit(1)


def _safe_remove(path: str) -> None:
    try:
        if path:
            os.remove(path)
    except OSError:
        pass


def _safe_rmdir(path: str) -> None:
    import shutil
    try:
        if path:
            shutil.rmtree(path)
    except OSError:
        pass


if __name__ == '__main__':
    main()
