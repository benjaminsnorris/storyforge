"""storyforge write — Autonomous scene drafting.

Drafts scenes using Claude via direct API or batch API. Supports parallel
wave drafting, coaching level adaptation, and brief-aware prompts.

Usage:
    storyforge write                        # Draft all remaining scenes
    storyforge write act1-sc01              # Draft a single scene
    storyforge write act1-sc01 act1-sc15    # Draft a range (by position)
    storyforge write --act 2                # Draft all scenes in act 2
    storyforge write --dry-run act1-sc01    # Build prompt without invoking
"""

import argparse
import json
import os
import subprocess
import sys
import time

from storyforge.common import (
    detect_project_root, log, set_log_file, read_yaml_field, select_model,
    get_coaching_level, install_signal_handlers,
)
from storyforge.git import (
    create_branch, ensure_branch_pushed, create_draft_pr, commit_and_push,
    update_pr_task, run_review_phase,
)
from storyforge.cli import apply_coaching_override
from storyforge.api import (
    invoke_to_file, extract_text, extract_text_from_file, extract_usage,
    calculate_cost_from_usage, submit_batch, poll_batch, download_batch_results,
)
from storyforge.costs import estimate_cost, check_threshold, log_operation, print_summary
from storyforge.scene_filter import build_scene_list, apply_scene_filter
from storyforge.csv_cli import get_field, update_field


def parse_args(argv):
    parser = argparse.ArgumentParser(
        prog='storyforge write',
        description='Draft scenes autonomously using Claude.',
    )
    parser.add_argument('positional', nargs='*', default=[],
                        help='Scene ID(s) — one for single, two for range')
    parser.add_argument('--dry-run', action='store_true',
                        help='Build prompts without invoking Claude')
    parser.add_argument('--force', action='store_true',
                        help='Re-draft scenes even if already drafted')
    parser.add_argument('--direct', action='store_true',
                        help='Use direct API calls (not batch)')
    parser.add_argument('--coaching', choices=['full', 'coach', 'strict'],
                        help='Set coaching level')
    parser.add_argument('--interactive', '-i', action='store_true',
                        help='Draft with supervision')
    parser.add_argument('--scenes', type=str, default=None,
                        help='Comma-separated scene IDs')
    parser.add_argument('--act', '--part', type=str, default=None,
                        help='Draft all scenes in act/part N')
    parser.add_argument('--from-seq', type=str, default=None,
                        help='Start from sequence number (N or N-M range)')
    return parser.parse_args(argv)


def main(argv=None):
    args = parse_args(argv if argv is not None else sys.argv[1:])

    install_signal_handlers()
    apply_coaching_override(args)

    project_dir = detect_project_root()
    log(f'Project root: {project_dir}')

    scenes_dir = os.path.join(project_dir, 'scenes')
    log_dir = os.path.join(project_dir, 'working', 'logs')
    os.makedirs(scenes_dir, exist_ok=True)
    os.makedirs(log_dir, exist_ok=True)
    os.makedirs(os.path.join(project_dir, 'working', 'coaching'), exist_ok=True)

    set_log_file(os.path.join(log_dir, 'drafting-log.txt'))

    # Resolve coaching level
    coaching = args.coaching or get_coaching_level(project_dir)

    # Resolve write mode
    if args.interactive:
        write_mode = 'interactive'
    elif args.direct:
        write_mode = 'direct'
    else:
        write_mode = 'batch'

    # API key check for non-interactive modes
    if not args.dry_run and write_mode != 'interactive':
        if not os.environ.get('ANTHROPIC_API_KEY'):
            log('ERROR: ANTHROPIC_API_KEY not set. Required for batch/direct API modes.')
            log('  Set it with: export ANTHROPIC_API_KEY=your-key')
            log('  Or use --interactive to run via claude -p instead.')
            sys.exit(1)

    # Check for voice guide
    _check_voice_guide(project_dir)

    # Build and filter scene list
    metadata_csv = os.path.join(project_dir, 'reference', 'scenes.csv')
    all_ids = build_scene_list(metadata_csv)

    filter_mode, filter_value, filter_value2 = _resolve_filter(args)
    filtered_ids = apply_scene_filter(metadata_csv, all_ids, filter_mode,
                                      filter_value, filter_value2)

    # Filter out already-drafted scenes (unless --force or single)
    pending_ids, skipped = _filter_pending(
        filtered_ids, project_dir, metadata_csv, args.force, filter_mode,
    )

    if not pending_ids:
        log(f'Nothing to draft — all {len(filtered_ids)} matching scenes are '
            f'already drafted ({skipped} skipped).')
        return

    # Cost forecasting
    if not args.dry_run:
        model = select_model('drafting')
        avg_words = _avg_word_count(metadata_csv)
        estimated = estimate_cost('draft', len(pending_ids), avg_words, model)
        if write_mode == 'batch':
            estimated *= 0.5  # Batch API 50% discount
        log(f'Cost forecast: ~${estimated:.2f} for {len(pending_ids)} scenes '
            f'(avg {avg_words} words, model {model}, mode {write_mode})')
        if not check_threshold(estimated):
            log('Aborting — cost threshold exceeded.')
            return

    # Session start
    session_start = time.time()

    # Branch + PR setup
    if not args.dry_run:
        create_branch('write', project_dir)

        # Advance project phase
        current_phase = read_yaml_field('phase', project_dir)
        if current_phase not in ('drafting', 'evaluation', 'revision', 'complete'):
            yaml_file = os.path.join(project_dir, 'storyforge.yaml')
            _replace_in_file(yaml_file, r'^(\s*phase:).*', r'\1 drafting')
            log('Project phase advanced to: drafting')

        ensure_branch_pushed(project_dir)

        title = (read_yaml_field('project.title', project_dir)
                 or read_yaml_field('title', project_dir) or 'Unknown')
        pr_body = f"""## Drafting Session

**Project:** {title}
**Scenes to draft:** {len(pending_ids)}

### Tasks
"""
        for sid in pending_ids:
            pr_body += f'- [ ] Draft scene {sid}\n'
        pr_body += '- [ ] Review'

        create_draft_pr(
            f'Draft: {title} ({len(pending_ids)} scenes)',
            pr_body, project_dir, 'drafting',
        )

    log('============================================')
    log('Starting Storyforge drafting session')
    title = (read_yaml_field('project.title', project_dir)
             or read_yaml_field('title', project_dir) or 'Unknown')
    log(f'Project: {title}')
    log(f'Mode: {write_mode}')
    log(f'Coaching level: {coaching}')
    log(f'Scenes to draft: {len(pending_ids)} ({skipped} already-drafted skipped)')
    log(f'Scene list: {" ".join(pending_ids)}')
    log('============================================')

    # Detect briefs
    use_briefs = _detect_briefs(project_dir)

    # Main drafting
    drafted_count = 0
    total_words = 0

    if write_mode == 'batch' and not args.dry_run:
        drafted_count, total_words = _run_batch_mode(
            pending_ids, project_dir, scenes_dir, log_dir, metadata_csv,
            coaching, use_briefs, args.force, filter_mode,
        )
    else:
        drafted_count, total_words = _run_direct_mode(
            pending_ids, project_dir, scenes_dir, log_dir, metadata_csv,
            coaching, use_briefs, args.force, filter_mode, write_mode,
            args.dry_run,
        )

    # Session summary
    elapsed = int(time.time() - session_start)
    mins, secs = divmod(elapsed, 60)

    log('============================================')
    log('Drafting session complete!')
    log(f'Scenes drafted: {drafted_count}/{len(pending_ids)}')
    log(f'Total words: {total_words}')
    log(f'Total time: {mins}m{secs}s')
    log('============================================')

    if not args.dry_run and drafted_count > 0:
        print_summary(project_dir, 'draft')
        run_review_phase('drafting', project_dir)


# ============================================================================
# Internal helpers
# ============================================================================

def _check_voice_guide(project_dir: str) -> None:
    """Warn if no voice guide is found."""
    for vg in ('reference/voice-guide.md', 'reference/persistent-prompt.md'):
        if os.path.isfile(os.path.join(project_dir, vg)):
            return
    custom_vg = read_yaml_field('reference.voice_guide', project_dir)
    if not custom_vg:
        custom_vg = read_yaml_field('voice_guide', project_dir)
    if custom_vg and os.path.isfile(os.path.join(project_dir, custom_vg)):
        return
    log('WARNING: No voice guide found. Drafting will proceed without voice constraints.')
    log('  Expected: reference/voice-guide.md or reference/persistent-prompt.md')


def _resolve_filter(args) -> tuple:
    """Resolve CLI args to (mode, value, value2)."""
    if args.scenes:
        return ('scenes', args.scenes, None)
    if args.act:
        return ('act', args.act, None)
    if args.from_seq:
        return ('from_seq', args.from_seq, None)
    positional = args.positional
    if len(positional) == 0:
        return ('all', None, None)
    if len(positional) == 1:
        return ('single', positional[0], None)
    if len(positional) == 2:
        return ('range', positional[0], positional[1])
    log('ERROR: Too many positional arguments')
    sys.exit(1)


def _filter_pending(filtered_ids, project_dir, metadata_csv, force, filter_mode):
    """Filter out already-drafted scenes. Returns (pending_ids, skipped_count)."""
    from storyforge.prompts import get_scene_status

    pending = []
    skipped = 0

    for sid in filtered_ids:
        status = get_scene_status(sid, project_dir)
        if status in ('drafted', 'revised', 'final'):
            if force or filter_mode == 'single':
                pending.append(sid)
                if force:
                    log(f"NOTE: Scene {sid} has status '{status}' — re-drafting (--force)")
                if filter_mode == 'single':
                    log(f"NOTE: Scene {sid} has status '{status}' but was explicitly requested")
            else:
                skipped += 1
        else:
            pending.append(sid)

    return pending, skipped


def _avg_word_count(metadata_csv: str) -> int:
    """Calculate average target word count from metadata CSV."""
    from storyforge.csv_cli import get_column
    values = get_column(metadata_csv, 'target_words')
    nums = []
    for v in values:
        try:
            n = int(v)
            if n > 0:
                nums.append(n)
        except (ValueError, TypeError):
            pass
    return int(sum(nums) / len(nums)) if nums else 2000


def _detect_briefs(project_dir: str) -> bool:
    """Check if scene briefs exist for brief-aware drafting."""
    briefs_csv = os.path.join(project_dir, 'reference', 'scene-briefs.csv')
    if not os.path.isfile(briefs_csv):
        return False
    with open(briefs_csv) as f:
        lines = [l.strip() for l in f if l.strip()]
    # At least one non-empty data row
    for line in lines[1:]:
        fields = line.split('|')
        if len(fields) > 1 and any(f.strip() for f in fields[1:]):
            log(f'Detected scene briefs — using brief-aware drafting')
            return True
    return False


def _build_prompt(scene_id: str, project_dir: str, coaching: str,
                  use_briefs: bool) -> str:
    """Build the drafting prompt for a scene."""
    from storyforge.common import get_plugin_dir
    plugin_dir = get_plugin_dir()

    if use_briefs:
        from storyforge.prompts import build_scene_prompt_from_briefs
        from storyforge.elaborate import get_scene
        scene = get_scene(scene_id, os.path.join(project_dir, 'reference'))
        deps = scene.get('continuity_deps', '') if scene else ''
        dep_scenes = [d.strip() for d in deps.split(';') if d.strip()] if deps else None
        return build_scene_prompt_from_briefs(scene_id, project_dir, plugin_dir,
                                              coaching, dep_scenes=dep_scenes)
    else:
        from storyforge.prompts import build_scene_prompt
        return build_scene_prompt(scene_id, project_dir, coaching,
                                  api_mode=True)


def _extract_scene_from_response(log_file: str, scene_file: str) -> None:
    """Extract scene prose from API response."""
    try:
        from storyforge.parsing import extract_single_scene
        extract_single_scene(log_file, scene_file)
        log(f'Wrote scene file: {scene_file}')
    except Exception:
        text = extract_text_from_file(log_file)
        if text:
            with open(scene_file, 'w') as f:
                f.write(text)
        log(f'WARNING: Python scene extraction failed, fell back to raw response')


def _verify_and_commit_scene(scene_id: str, project_dir: str, scenes_dir: str,
                             metadata_csv: str, coaching: str,
                             head_before: str) -> tuple:
    """Verify and commit a drafted scene. Returns (word_count, success)."""
    scene_file = os.path.join(scenes_dir, f'{scene_id}.md')
    word_count = 0

    if coaching in ('coach', 'strict'):
        if coaching == 'coach':
            coaching_file = os.path.join(project_dir, 'working', 'coaching',
                                         f'brief-{scene_id}.md')
        else:
            coaching_file = os.path.join(project_dir, 'working', 'coaching',
                                         f'constraints-{scene_id}.md')
        if not os.path.isfile(coaching_file):
            log(f'WARNING: Coaching output not created: {coaching_file}')
        if os.path.isfile(coaching_file):
            with open(coaching_file) as f:
                word_count = len(f.read().split())
    else:
        if not os.path.isfile(scene_file):
            log(f'ERROR: Scene file not created: {scene_file}')
            return 0, False
        with open(scene_file) as f:
            word_count = len(f.read().split())
        if word_count < 100:
            log(f'ERROR: Scene file suspiciously short ({word_count} words): {scene_file}')
            return 0, False
        update_field(metadata_csv, scene_id, 'word_count', str(word_count))
        update_field(metadata_csv, scene_id, 'status', 'drafted')
        log(f'Updated metadata.csv: {scene_id} word_count={word_count} status=drafted')

    # Check if commit already happened
    from storyforge.git import _git
    r = _git(project_dir, 'rev-parse', 'HEAD', check=False)
    head_after = r.stdout.strip() if r.returncode == 0 else 'none'

    if head_before == head_after:
        log(f'Creating commit for scene {scene_id}...')
        if coaching in ('coach', 'strict'):
            paths = ['working/coaching/', 'working/logs/']
            msg = f'{coaching.capitalize()}: {scene_id}'
        else:
            paths = [f'scenes/{scene_id}.md', 'reference/', 'working/logs/']
            msg = f'Draft scene {scene_id}'

        from storyforge.git import commit_and_push
        commit_and_push(project_dir, msg, paths)

    # Push
    _git(project_dir, 'push', check=False)

    r = _git(project_dir, 'rev-parse', '--short', 'HEAD', check=False)
    commit_short = r.stdout.strip() if r.returncode == 0 else 'unknown'
    log(f'SUCCESS: Scene {scene_id} — {word_count} words, commit {commit_short}')

    update_pr_task(f'Draft scene {scene_id}', project_dir)

    return word_count, True


def _run_batch_mode(pending_ids, project_dir, scenes_dir, log_dir,
                    metadata_csv, coaching, use_briefs, force, filter_mode):
    """Run batch API mode. Returns (drafted_count, total_words)."""
    log('Building prompts for batch submission...')

    batch_file = os.path.join(log_dir, f'drafting-batch-{os.getpid()}.jsonl')
    model = select_model('drafting')
    batch_scene_ids = []

    for scene_id in pending_ids:
        scene_file = os.path.join(scenes_dir, f'{scene_id}.md')

        # Skip already-drafted unless --force
        if not force and os.path.isfile(scene_file) and filter_mode != 'single':
            with open(scene_file) as f:
                existing_wc = len(f.read().split())
            if existing_wc > 200:
                log(f'Scene {scene_id} already has {existing_wc} words, skipping')
                continue

        prompt = _build_prompt(scene_id, project_dir, coaching, use_briefs)
        if not prompt:
            log(f'ERROR: Failed to build prompt for scene {scene_id}')
            sys.exit(1)

        # Build JSONL line
        request = {
            'custom_id': scene_id,
            'params': {
                'model': model,
                'max_tokens': 8192,
                'messages': [{'role': 'user', 'content': prompt}],
            },
        }
        with open(batch_file, 'a') as f:
            f.write(json.dumps(request) + '\n')
        batch_scene_ids.append(scene_id)

    if not batch_scene_ids:
        log('No scenes to submit in batch.')
        return 0, 0

    log(f'Submitting batch with {len(batch_scene_ids)} scenes...')

    batch_id = submit_batch(batch_file)
    if not batch_id:
        log('ERROR: Failed to submit batch.')
        sys.exit(1)
    log(f'Batch submitted: {batch_id}')

    log('Polling batch for completion...')
    results_url = poll_batch(batch_id, log_fn=log)
    log('Batch complete. Downloading results...')

    batch_output_dir = os.path.join(log_dir, f'batch-{os.getpid()}')
    os.makedirs(batch_output_dir, exist_ok=True)
    download_batch_results(results_url, batch_output_dir, batch_output_dir)

    # Process each scene result
    drafted_count = 0
    total_words = 0
    from storyforge.git import _git

    for scene_id in batch_scene_ids:
        scene_file = os.path.join(scenes_dir, f'{scene_id}.md')
        scene_json = os.path.join(batch_output_dir, f'{scene_id}.json')

        r = _git(project_dir, 'rev-parse', 'HEAD', check=False)
        head_before = r.stdout.strip() if r.returncode == 0 else 'none'

        # Check batch status
        status_file = os.path.join(batch_output_dir, f'.status-{scene_id}')
        batch_status = 'fail'
        if os.path.isfile(status_file):
            with open(status_file) as f:
                batch_status = f.read().strip()

        if batch_status != 'ok':
            log(f'ERROR: Batch failed for scene {scene_id}. Skipping.')
            continue

        # Extract scene text
        if os.path.isfile(scene_json):
            _extract_scene_from_response(scene_json, scene_file)

        # Log usage
        if os.path.isfile(scene_json):
            _log_api_usage(scene_json, 'draft', scene_id, model, project_dir)

        # Verify and commit
        wc, ok = _verify_and_commit_scene(
            scene_id, project_dir, scenes_dir, metadata_csv, coaching,
            head_before,
        )
        if ok:
            drafted_count += 1
            total_words += wc

    # Cleanup
    _safe_remove(batch_file)
    _safe_rmdir(batch_output_dir)

    return drafted_count, total_words


def _run_direct_mode(pending_ids, project_dir, scenes_dir, log_dir,
                     metadata_csv, coaching, use_briefs, force, filter_mode,
                     write_mode, dry_run):
    """Run direct/interactive mode. Returns (drafted_count, total_words)."""
    drafted_count = 0
    total_words = 0
    from storyforge.git import _git

    for i, scene_id in enumerate(pending_ids):
        scene_file = os.path.join(scenes_dir, f'{scene_id}.md')
        scene_num = i + 1

        log(f'--- Scene {scene_id} ({scene_num}/{len(pending_ids)}) ---')

        # Skip already-drafted
        if not force and os.path.isfile(scene_file) and filter_mode != 'single':
            with open(scene_file) as f:
                existing_wc = len(f.read().split())
            if existing_wc > 200:
                log(f'Scene file already has {existing_wc} words, skipping')
                continue

        prompt = _build_prompt(scene_id, project_dir, coaching, use_briefs)
        if not prompt:
            log(f'ERROR: Failed to build prompt for scene {scene_id}')
            log('Stopping — prompt generation failed.')
            sys.exit(1)

        # Dry-run mode
        if dry_run:
            print(f'===== DRY RUN: {scene_id} =====')
            print(prompt)
            print(f'===== END DRY RUN: {scene_id} =====')
            print()
            drafted_count += 1
            continue

        r = _git(project_dir, 'rev-parse', 'HEAD', check=False)
        head_before = r.stdout.strip() if r.returncode == 0 else 'none'

        scene_log = os.path.join(log_dir, f'drafting-{scene_id}.json')
        model = select_model('drafting')
        start_time = time.time()

        log(f'Invoking API for scene {scene_id} (model: {model})...')
        log(f'  Per-scene log: {scene_log}')

        if write_mode == 'interactive':
            # Interactive mode — invoke claude CLI
            exit_code = _invoke_interactive(prompt, model, project_dir)
        else:
            # Direct API mode
            try:
                max_tokens = 16384 if write_mode != 'direct' else 8192
                invoke_to_file(prompt, model, scene_log, max_tokens)
                _extract_scene_from_response(scene_log, scene_file)
                _log_api_usage(scene_log, 'draft', scene_id, model, project_dir)
                exit_code = 0
            except Exception as e:
                log(f'ERROR: API call failed: {e}')
                exit_code = 1

        elapsed = int(time.time() - start_time)
        mins, secs = divmod(elapsed, 60)

        if exit_code != 0:
            log(f'ERROR: API call failed with code {exit_code} for scene {scene_id} '
                f'after {mins}m{secs}s')
            log(f'See full output: {scene_log}')
            log('Stopping — continuity may be broken.')
            break

        wc, ok = _verify_and_commit_scene(
            scene_id, project_dir, scenes_dir, metadata_csv, coaching,
            head_before,
        )
        if ok:
            drafted_count += 1
            total_words += wc

        log(f'  Time: {mins}m{secs}s')

        # Pause between scenes in headless mode
        if i < len(pending_ids) - 1 and write_mode != 'interactive':
            log('Pausing 10s before next scene...')
            time.sleep(10)

    return drafted_count, total_words


def _invoke_interactive(prompt: str, model: str, project_dir: str) -> int:
    """Invoke Claude CLI in interactive mode. Returns exit code."""
    try:
        result = subprocess.run(
            ['claude', prompt, '--model', model,
             '--dangerously-skip-permissions'],
            cwd=project_dir,
        )
        return result.returncode
    except FileNotFoundError:
        log('ERROR: claude CLI not found — install Claude Code first')
        return 1


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


def _replace_in_file(filepath: str, pattern: str, replacement: str) -> None:
    """Regex-replace in a file (like sed -i)."""
    import re
    if not os.path.isfile(filepath):
        return
    with open(filepath) as f:
        content = f.read()
    new_content = re.sub(pattern, replacement, content, flags=re.MULTILINE)
    if new_content != content:
        with open(filepath, 'w') as f:
            f.write(new_content)


def _safe_remove(path: str) -> None:
    try:
        os.remove(path)
    except OSError:
        pass


def _safe_rmdir(path: str) -> None:
    import shutil
    try:
        shutil.rmtree(path)
    except OSError:
        pass


if __name__ == '__main__':
    main()
