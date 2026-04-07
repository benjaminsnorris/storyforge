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

import argparse

from storyforge.common import (
    detect_project_root, log, set_log_file, read_yaml_field, select_model,
    get_coaching_level, install_signal_handlers, get_plugin_dir,
)
from storyforge.git import (
    create_branch, ensure_branch_pushed, create_draft_pr, commit_and_push,
    update_pr_task, run_review_phase,
)
from storyforge.api import (
    invoke_to_file, extract_text, extract_text_from_file, extract_usage,
    calculate_cost_from_usage, submit_batch, poll_batch, download_batch_results,
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

    validate_passed = None
    validate_failures = 0

    if not args.cleanup_only:
        # Phase 0: Characterize
        if args.phase is None or args.phase == 0:
            _run_phase_0(project_dir, scenes_dir, log_dir, profile_file,
                         args.dry_run)
            if not args.dry_run:
                commit_and_push(project_dir,
                                'Extract: Phase 0 — manuscript characterization',
                                ['working/'])
                update_pr_task('Phase 0: Characterize manuscript', project_dir)

        # Phase 1: Skeleton
        if args.phase is None or args.phase == 1:
            _run_phase_1(sorted_scene_ids, project_dir, scenes_dir, ref_dir,
                         log_dir, profile_file, plugin_dir, args.force,
                         args.dry_run)
            if not args.dry_run:
                commit_and_push(project_dir,
                                'Extract: Phase 1 — skeleton (scenes.csv)',
                                ['reference/scenes.csv', 'working/'])
                update_pr_task('Phase 1: Extract skeleton', project_dir)

                # Reconcile Phase 1 registries
                log('')
                log('--- Reconciling Phase 1 registries ---')
                _run_hone(plugin_dir, phase=1)

        # Phase 2: Intent
        if args.phase is None or args.phase == 2:
            _run_phase_2(sorted_scene_ids, project_dir, scenes_dir, ref_dir,
                         log_dir, profile_file, args.dry_run)
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
                         log_dir, profile_file, args.force, args.dry_run)
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

    print_summary(project_dir, 'extract')


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

def _run_phase_0(project_dir, scenes_dir, log_dir, profile_file, dry_run):
    log('')
    log('--- Phase 0: Characterize manuscript ---')

    from storyforge.extract import build_characterize_prompt, parse_characterize_response

    prompt = build_characterize_prompt(project_dir)
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
    model = select_model('synthesis')  # Opus for full-manuscript comprehension

    log(f'  Invoking {model} for manuscript characterization...')

    response = invoke_to_file(prompt, model, char_log, 4096)
    text = extract_text(response)
    _log_api_usage(char_log, 'extract-characterize', 'manuscript', model, project_dir)

    profile = parse_characterize_response(text)
    with open(profile_file, 'w') as f:
        json.dump(profile, f, indent=2)

    log(f'  Characterized: {len(profile)} fields extracted')
    for k, v in sorted(profile.items()):
        log(f'  {k}: {str(v)[:80]}')


# ============================================================================
# Phase 1: Skeleton (scenes.csv)
# ============================================================================

def _run_phase_1(sorted_scene_ids, project_dir, scenes_dir, ref_dir, log_dir,
                 profile_file, plugin_dir, force, dry_run):
    log('')
    log('--- Phase 1: Extract skeleton (scenes.csv) ---')

    from storyforge.extract import build_skeleton_prompt, parse_skeleton_response
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
    for scene_id in sorted_scene_ids:
        scene_path = os.path.join(scenes_dir, f'{scene_id}.md')
        if not os.path.isfile(scene_path):
            continue
        with open(scene_path) as f:
            scene_text = f.read()
        if not scene_text:
            continue

        prompt = build_skeleton_prompt(scene_id, scene_text, profile,
                                        registries_text=registries)
        request = {
            'custom_id': scene_id,
            'params': {
                'model': model,
                'max_tokens': 1024,
                'messages': [{'role': 'user', 'content': prompt}],
            },
        }
        with open(batch_file, 'a') as f:
            f.write(json.dumps(request) + '\n')

    log('  Submitting batch...')
    batch_id = submit_batch(batch_file)
    results_url = poll_batch(batch_id, log_fn=log)

    skel_output = os.path.join(log_dir, 'extract-phase1-output')
    os.makedirs(skel_output, exist_ok=True)
    download_batch_results(results_url, skel_output, log_dir)

    # Process results
    log('  Processing skeleton results...')
    alias_maps = load_registry_alias_maps(project_dir)
    existing = _read_csv_as_map(os.path.join(ref_dir, 'scenes.csv'))

    count = 0
    for i, sid in enumerate(sorted_scene_ids):
        txt_file = os.path.join(log_dir, f'{sid}.txt')
        if not os.path.isfile(txt_file):
            continue
        with open(txt_file) as f:
            response_text = f.read()
        result = parse_skeleton_response(response_text, sid)
        normalize_fields(result, alias_maps)

        if sid in existing:
            for k, v in result.items():
                if v and k != 'id' and (force or not existing[sid].get(k, '').strip()):
                    existing[sid][k] = v
        elif not existing:
            row = {c: '' for c in _FILE_MAP['scenes.csv']}
            row.update(result)
            row['seq'] = str(i + 1)
            row['status'] = 'drafted'
            scene_file = os.path.join(scenes_dir, f'{sid}.md')
            if os.path.isfile(scene_file):
                with open(scene_file) as f:
                    row['word_count'] = str(len(f.read().split()))
            existing[sid] = row
        else:
            continue
        count += 1

    ordered = sorted(existing.values(), key=lambda r: int(r.get('seq', 0)))
    _write_csv(os.path.join(ref_dir, 'scenes.csv'), ordered, _FILE_MAP['scenes.csv'])
    log(f'  Updated scenes.csv: {count} scenes')

    _safe_remove(batch_file)
    _safe_rmdir(skel_output)


# ============================================================================
# Phase 2: Intent (scene-intent.csv)
# ============================================================================

def _run_phase_2(sorted_scene_ids, project_dir, scenes_dir, ref_dir, log_dir,
                 profile_file, dry_run):
    log('')
    log('--- Phase 2: Extract intent (scene-intent.csv) ---')

    if dry_run:
        print(f'===== DRY RUN: Phase 2 (intent) — {len(sorted_scene_ids)} scenes =====')
        print('===== END DRY RUN =====')
        return

    from storyforge.extract import build_intent_prompt, parse_intent_response
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
        request = {
            'custom_id': scene_id,
            'params': {
                'model': model,
                'max_tokens': 1024,
                'messages': [{'role': 'user', 'content': prompt}],
            },
        }
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
    force = False  # Phase 2 doesn't use --force for intent

    existing = _read_csv_as_map(os.path.join(ref_dir, 'scene-intent.csv'))

    count = 0
    for sid in sorted_scene_ids:
        txt_file = os.path.join(log_dir, f'{sid}.txt')
        if not os.path.isfile(txt_file):
            continue
        with open(txt_file) as f:
            response_text = f.read()
        result = parse_intent_response(response_text, sid)
        normalize_fields(result, alias_maps)

        if sid in existing:
            for k, v in result.items():
                if v and k != 'id' and not k.startswith('_'):
                    if force or not existing[sid].get(k, '').strip():
                        existing[sid][k] = v
        elif not existing:
            row = {c: '' for c in _FILE_MAP['scene-intent.csv']}
            row.update({k: v for k, v in result.items() if not k.startswith('_')})
            existing[sid] = row
        else:
            continue
        count += 1

    ordered = sorted(existing.values(), key=lambda r: r.get('id', ''))
    _write_csv(os.path.join(ref_dir, 'scene-intent.csv'), ordered,
               _FILE_MAP['scene-intent.csv'])
    log(f'  Updated scene-intent.csv: {count} scenes')

    _safe_remove(batch_file)
    _safe_rmdir(intent_output)


# ============================================================================
# Phase 3: Briefs (scene-briefs.csv)
# ============================================================================

def _run_phase_3(sorted_scene_ids, project_dir, scenes_dir, ref_dir, log_dir,
                 profile_file, force, dry_run):
    """Run Phase 3a (parallel briefs) + 3b (knowledge chain) + 3c (physical state)."""

    # Phase 3a: Parallel brief fields
    log('')
    log('--- Phase 3a: Extract briefs (parallel fields) ---')

    if dry_run:
        print(f'===== DRY RUN: Phase 3a (briefs parallel) — {len(sorted_scene_ids)} scenes =====')
        print('===== END DRY RUN =====')
        return

    from storyforge.extract import (
        build_brief_parallel_prompt, parse_brief_parallel_response,
        build_knowledge_prompt, parse_knowledge_response,
        build_physical_state_prompt, parse_physical_state_response,
    )
    from storyforge.elaborate import (
        get_scene, update_scene, _read_csv_as_map, _write_csv, _FILE_MAP,
    )
    from storyforge.enrich import (
        format_registries_for_prompt, load_registry_alias_maps, normalize_fields,
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
        skeleton = {k: scene_data.get(k, '') for k in ['title', 'pov', 'location', 'part']}
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
        request = {
            'custom_id': scene_id,
            'params': {
                'model': model,
                'max_tokens': 1024,
                'messages': [{'role': 'user', 'content': prompt}],
            },
        }
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
    existing = _read_csv_as_map(os.path.join(ref_dir, 'scene-briefs.csv'))

    count = 0
    for sid in sorted_scene_ids:
        txt_file = os.path.join(log_dir, f'{sid}.txt')
        if not os.path.isfile(txt_file):
            continue
        with open(txt_file) as f:
            response_text = f.read()
        result = parse_brief_parallel_response(response_text, sid)
        normalize_fields(result, alias_maps)

        if sid in existing:
            for k, v in result.items():
                if v and k != 'id' and (force or not existing[sid].get(k, '').strip()):
                    existing[sid][k] = v
        elif not existing:
            row = {c: '' for c in _FILE_MAP['scene-briefs.csv']}
            row.update(result)
            existing[sid] = row
        else:
            continue
        count += 1

    ordered = sorted(existing.values(), key=lambda r: r.get('id', ''))
    _write_csv(os.path.join(ref_dir, 'scene-briefs.csv'), ordered,
               _FILE_MAP['scene-briefs.csv'])
    log(f'  Updated scene-briefs.csv: {count} scenes (knowledge fields pending)')

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

    for scene_id in sorted_scene_ids:
        scene_path = os.path.join(scenes_dir, f'{scene_id}.md')
        if not os.path.isfile(scene_path):
            continue
        with open(scene_path) as f:
            scene_text = f.read()
        if not scene_text:
            continue

        scene_data = get_scene(scene_id, ref_dir) or {}
        skeleton = {k: scene_data.get(k, '') for k in ['title', 'pov', 'location', 'part']}
        intent = {k: scene_data.get(k, '') for k in ['function', 'action_sequel']}

        prompt = build_knowledge_prompt(scene_id, scene_text, skeleton, intent,
                                         knowledge_state, summaries,
                                         registries_text=registries)

        knowledge_log = os.path.join(log_dir, f'extract-knowledge-{scene_id}.json')

        try:
            response = invoke_to_file(prompt, knowledge_model, knowledge_log, 1024)
            text = extract_text(response)
            _log_api_usage(knowledge_log, 'extract-knowledge', scene_id,
                           knowledge_model, project_dir)
        except Exception:
            log(f'  WARNING: Knowledge extraction failed for {scene_id}')
            continue

        result = parse_knowledge_response(text, scene_id)

        # Update briefs CSV
        updates = {}
        for k in ('knowledge_in', 'knowledge_out', 'continuity_deps'):
            if result.get(k):
                updates[k] = result[k]
        if updates:
            update_scene(scene_id, ref_dir, updates)

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
                    ['reference/scene-briefs.csv', 'working/'])

    # --- Phase 3c: Physical state chain (sequential) ---
    log('')
    log('--- Phase 3c: Extract physical state chain (sequential) ---')

    phys_model = select_model('evaluation')
    phys_states = {}  # dict[str, set[str]]: character -> active state IDs
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
                    for k in ['title', 'pov', 'location', 'part', 'on_stage']}

        prompt = build_physical_state_prompt(scene_id, scene_text, skeleton,
                                              phys_states, phys_summaries,
                                              registries_text=registries)

        phys_log = os.path.join(log_dir, f'extract-physical-{scene_id}.json')

        try:
            response = invoke_to_file(prompt, phys_model, phys_log, 1024)
            text = extract_text(response)
            _log_api_usage(phys_log, 'extract-physical', scene_id,
                           phys_model, project_dir)
        except Exception:
            log(f'  WARNING: Physical state extraction failed for {scene_id}')
            continue

        result = parse_physical_state_response(text, scene_id)

        # Update briefs CSV
        updates = {}
        for k in ('physical_state_in', 'physical_state_out'):
            if result.get(k):
                updates[k] = result[k]
        if updates:
            update_scene(scene_id, ref_dir, updates)

        # Append new physical states to registry
        new_states = result.get('_new_states', [])
        if new_states:
            phys_csv = os.path.join(ref_dir, 'physical-states.csv')
            columns = ['id', 'character', 'description', 'category',
                       'acquired', 'resolves', 'action_gating']
            existing_phys = _read_csv_as_map(phys_csv)
            for ns in new_states:
                sid_key = ns.get('id', '').strip()
                if not sid_key or sid_key in existing_phys:
                    continue
                row = {c: '' for c in columns}
                row['id'] = sid_key
                row['character'] = ns.get('character', '')
                row['description'] = ns.get('description', '')
                row['category'] = ns.get('category', '')
                row['acquired'] = scene_id
                row['resolves'] = 'never'
                row['action_gating'] = ns.get('action_gating', 'false')
                existing_phys[sid_key] = row
            _write_csv(phys_csv, list(existing_phys.values()), columns)

        # Accumulate state
        resolved = result.get('_resolved', [])
        for ns in new_states:
            sid_key = ns.get('id', '').strip()
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

    commit_and_push(project_dir,
                    'Extract: Phase 3c — physical state chain',
                    ['reference/scene-briefs.csv', 'reference/physical-states.csv',
                     'working/'])


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
    report = validate_structure(ref_dir)

    passed = report['passed']
    failures = len(report['failures'])

    if passed:
        log('Validation passed')
    else:
        log(f'Validation found {failures} issue(s) — review recommended')

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
    """Load extraction profile if it exists."""
    if os.path.isfile(profile_file):
        with open(profile_file) as f:
            return json.load(f)
    return {}


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
