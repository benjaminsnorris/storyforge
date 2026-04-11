"""storyforge score — Principled craft scoring for Storyforge projects.

Evaluates manuscript scenes against the craft engine's scoring rubrics,
producing per-scene, per-act, and novel-level scores in CSV format.

Three scoring modes:
  (default)     Batch API, Opus — best value and judgment
  --direct      Direct API, Sonnet — real-time results for interactive use
  --direct --deep  Direct API, Opus — real-time Opus when you need results now

Usage:
    storyforge score                        # All scenes, batch Opus
    storyforge score --direct --scenes ID   # Sonnet, one scene, real-time
    storyforge score --direct --deep --act 2
    storyforge score --dry-run              # Show what would be scored
"""

import argparse
import json
import os
import re
import subprocess
import sys
import time

from storyforge.common import (
    detect_project_root, log, set_log_file, read_yaml_field, select_model,
    get_coaching_level, get_current_cycle, install_signal_handlers,
    get_plugin_dir,
)
from storyforge.git import (
    create_branch, ensure_branch_pushed, create_draft_pr, commit_and_push,
    update_pr_task, has_gh,
)
from storyforge.cli import add_scene_filter_args, resolve_filter_args, apply_coaching_override
from storyforge.api import (
    invoke_to_file, extract_text, extract_text_from_file, extract_usage,
    calculate_cost_from_usage, submit_batch, poll_batch, download_batch_results,
)
from storyforge.costs import estimate_cost, check_threshold, log_operation, print_summary
from storyforge.scene_filter import build_scene_list, apply_scene_filter
from storyforge.csv_cli import get_field, get_column, update_field


def parse_args(argv):
    parser = argparse.ArgumentParser(
        prog='storyforge score',
        description='Score manuscript scenes against 25 craft principles.',
    )
    parser.add_argument('--dry-run', action='store_true',
                        help='Show what would be scored without invoking Claude')
    parser.add_argument('--interactive', '-i', action='store_true',
                        help='Enable interactive mode')
    parser.add_argument('--direct', action='store_true',
                        help='Direct API with Sonnet — real-time results')
    parser.add_argument('--deep', action='store_true',
                        help='Use Opus for direct API (requires --direct)')
    parser.add_argument('--scenes', type=str, default=None,
                        help='Comma-separated scene IDs')
    parser.add_argument('--act', type=str, default=None,
                        help='Score scenes in act/part N')
    parser.add_argument('--from-seq', type=str, default=None,
                        help='Start from sequence number (N or N-M range)')
    parser.add_argument('--parallel', type=int,
                        default=int(os.environ.get('STORYFORGE_SCORE_PARALLEL', '6')),
                        help='Parallel workers for direct mode (default: 6)')
    return parser.parse_args(argv)


def main(argv=None):
    args = parse_args(argv if argv is not None else sys.argv[1:])

    install_signal_handlers()

    # Resolve score mode
    if args.direct and args.deep:
        score_mode = 'direct-deep'
    elif args.direct:
        score_mode = 'direct'
    else:
        score_mode = 'batch'

    project_dir = detect_project_root()
    log(f'Project root: {project_dir}')

    title = (read_yaml_field('project.title', project_dir)
             or read_yaml_field('title', project_dir) or 'Unknown')

    # Branch + PR
    if not args.dry_run:
        create_branch('score', project_dir)
        ensure_branch_pushed(project_dir)

    plugin_dir = get_plugin_dir()
    scripts_dir = os.path.join(plugin_dir, 'scripts')
    prompts_dir = os.path.join(scripts_dir, 'prompts', 'scoring')

    # Model selection
    sonnet_model = select_model('evaluation')
    opus_model = 'claude-opus-4-6'

    if score_mode == 'batch':
        eval_model = opus_model
    elif score_mode == 'direct':
        eval_model = sonnet_model
    else:
        eval_model = opus_model

    log(f'Mode: {score_mode}, Model: {eval_model}')

    # Initialize craft weights
    from storyforge.scoring import init_craft_weights
    init_craft_weights(project_dir, plugin_dir)
    weights_file = os.path.join(project_dir, 'working', 'craft-weights.csv')

    # Build scene list
    metadata_csv = os.path.join(project_dir, 'reference', 'scenes.csv')
    intent_csv = os.path.join(project_dir, 'reference', 'scene-intent.csv')
    briefs_csv = os.path.join(project_dir, 'reference', 'scene-briefs.csv')
    has_briefs = os.path.isfile(briefs_csv)
    scenes_dir = os.path.join(project_dir, 'scenes')

    all_ids = build_scene_list(metadata_csv)

    # Filter scenes
    filter_mode, filter_value, _ = _resolve_filter(args)
    filtered_ids = apply_scene_filter(metadata_csv, all_ids, filter_mode, filter_value)

    # Keep only drafted scenes
    scene_ids = []
    missing = []
    for sid in filtered_ids:
        if os.path.isfile(os.path.join(scenes_dir, f'{sid}.md')):
            scene_ids.append(sid)
        else:
            missing.append(sid)

    if not scene_ids:
        log('ERROR: No drafted scene files found for the selected scope.')
        if missing:
            log(f'Missing scenes: {" ".join(missing)}')
        sys.exit(1)

    if missing:
        log(f'WARNING: {len(missing)} scenes not yet drafted (skipping): {" ".join(missing)}')

    scene_count = len(scene_ids)
    log(f'Scoring {scene_count} scenes in {score_mode} mode')

    # Determine cycle number
    cycle = _determine_cycle(project_dir)
    cycle_dir = os.path.join(project_dir, 'working', 'scores', f'cycle-{cycle}')
    log_dir = os.path.join(project_dir, 'working', 'logs')
    os.makedirs(cycle_dir, exist_ok=True)
    os.makedirs(log_dir, exist_ok=True)

    log(f'Cycle: {cycle} -> {cycle_dir}')

    # Cost forecast
    avg_words = _avg_word_count(metadata_csv, scene_ids, scenes_dir)
    scene_cost = estimate_cost('score', scene_count, avg_words, eval_model)
    if score_mode == 'batch':
        scene_cost *= 0.5
        log(f'Cost forecast: ~${scene_cost:.2f} ({scene_count} Opus calls via Batch API, 50% off)')
    else:
        log(f'Cost forecast: ~${scene_cost:.2f} ({scene_count} {eval_model} calls via Direct API)')

    if not args.dry_run:
        if not check_threshold(scene_cost):
            log('Cost threshold check declined. Aborting.')
            sys.exit(1)

    # API key check
    if not args.dry_run and not os.environ.get('ANTHROPIC_API_KEY'):
        log('ERROR: ANTHROPIC_API_KEY not set.')
        sys.exit(1)

    # Draft PR
    if not args.dry_run:
        pr_body = f"""## Principled Scoring

**Project:** {title}
**Mode:** {score_mode}
**Scenes:** {scene_count}
**Estimated cost:** ~${scene_cost:.2f}

### Tasks
- [ ] Scene-level scoring ({scene_count} scenes)
- [ ] Act-level scoring
- [ ] Novel-level scoring
- [ ] Diagnosis and proposals
- [ ] Improvement cycle
- [ ] Review"""
        create_draft_pr(
            f'Score: {title} ({score_mode}, {scene_count} scenes)',
            pr_body, project_dir, 'scoring',
        )

    # Dry-run summary
    if args.dry_run:
        _print_dry_run(score_mode, scene_count, args.parallel, cycle,
                       eval_model, scene_cost, scene_ids, metadata_csv,
                       cycle_dir)
        return

    # Load evaluation template and criteria
    diagnostics_csv = os.path.join(plugin_dir, 'references', 'diagnostics.csv')
    guide_file = os.path.join(plugin_dir, 'references', 'principle-guide.md')
    eval_template_file = os.path.join(prompts_dir, 'scene-evaluation.md')

    for f, label in [(diagnostics_csv, 'Diagnostics CSV'),
                     (eval_template_file, 'Scene evaluation template')]:
        if not os.path.isfile(f):
            log(f'ERROR: {label} not found: {f}')
            sys.exit(1)

    with open(eval_template_file) as f:
        eval_template = f.read()

    from storyforge.scoring import build_evaluation_criteria, build_weighted_text
    evaluation_criteria = build_evaluation_criteria(diagnostics_csv, guide_file)
    weighted_text_str = build_weighted_text(weights_file, exclude_section='narrative')

    log(f'Evaluation model: {eval_model} (mode: {score_mode})')

    # =========================================================================
    # Scene-Level Scoring
    # =========================================================================

    log('')
    log('============================================')
    log('Scene-Level Scoring')
    log('============================================')

    score_start = time.time()
    scored = 0
    failed = 0

    if score_mode == 'batch':
        scored, failed = _score_batch(
            scene_ids, eval_model, eval_template, evaluation_criteria,
            weighted_text_str, metadata_csv, intent_csv, scenes_dir,
            cycle_dir, log_dir, diagnostics_csv, plugin_dir,
        )
    else:
        scored, failed = _score_direct(
            scene_ids, eval_model, eval_template, evaluation_criteria,
            weighted_text_str, metadata_csv, intent_csv, scenes_dir,
            cycle_dir, log_dir, diagnostics_csv, plugin_dir,
            args.parallel, score_start,
        )

    log('')
    log(f'Scene scoring complete: {scored} scenes scored, {failed} failures')
    update_pr_task(f'Scene-level scoring ({scene_count} scenes)', project_dir)

    # =========================================================================
    # Brief fidelity scoring
    # =========================================================================

    if has_briefs:
        _run_fidelity_scoring(
            filtered_ids, project_dir, scenes_dir, log_dir, cycle_dir,
            briefs_csv, score_mode, sonnet_model, plugin_dir,
        )

    # =========================================================================
    # Act-level scoring
    # =========================================================================

    log('Running act-level scoring...')
    _run_act_scoring(
        scene_ids, metadata_csv, scenes_dir, cycle_dir, log_dir,
        prompts_dir, weights_file, sonnet_model, plugin_dir, args.dry_run,
    )
    update_pr_task('Act-level scoring', project_dir)

    # =========================================================================
    # Novel-level scoring
    # =========================================================================

    log('Running novel-level scoring...')
    _run_novel_scoring(
        scene_count, metadata_csv, intent_csv, project_dir, cycle_dir,
        log_dir, prompts_dir, weights_file, sonnet_model, plugin_dir,
        args.dry_run,
    )
    update_pr_task('Novel-level scoring', project_dir)

    # =========================================================================
    # Narrative framework scoring
    # =========================================================================

    log('')
    log('============================================')
    log('Narrative Framework Scoring')
    log('============================================')

    _run_narrative_scoring(
        title, metadata_csv, project_dir, cycle_dir, log_dir, prompts_dir,
        weights_file, args.dry_run,
    )

    # Update latest symlink
    latest_link = os.path.join(project_dir, 'working', 'scores', 'latest')
    target = f'cycle-{cycle}'
    if os.path.islink(latest_link):
        os.remove(latest_link)
    os.symlink(target, latest_link)
    log(f'Updated latest symlink -> {target}')

    # Cost summary
    print('')
    print_summary(project_dir, 'score')

    # Append to score history for cross-cycle tracking
    from storyforge.history import append_cycle
    history_count = append_cycle(cycle_dir, cycle, project_dir)
    if history_count:
        log(f'Score history: appended {history_count} entries (cycle {cycle})')

    # =========================================================================
    # Improvement cycle
    # =========================================================================

    log('Running improvement cycle...')
    _run_improvement_cycle(
        cycle, cycle_dir, project_dir, weights_file, plugin_dir,
        intent_csv, title,
    )
    update_pr_task('Diagnosis and proposals', project_dir)
    update_pr_task('Improvement cycle', project_dir)

    # =========================================================================
    # Report, commit, and finish
    # =========================================================================

    _generate_report_and_comment(
        cycle, cycle_dir, project_dir, score_mode, scene_count,
    )
    update_pr_task('Review', project_dir)

    # Regenerate dashboard
    visualize_script = os.path.join(scripts_dir, 'storyforge-visualize')
    if os.path.isfile(visualize_script) and os.access(visualize_script, os.X_OK):
        log('Regenerating manuscript dashboard...')
        try:
            subprocess.run([visualize_script], capture_output=True, cwd=project_dir)
        except Exception:
            log('WARNING: Dashboard generation failed')

    # Final commit
    log('Committing scoring results...')
    commit_and_push(project_dir,
                    f'Score: cycle {cycle}, {scene_count} scenes ({score_mode} mode)',
                    ['working/scores/', 'working/craft-weights.csv', 'working/costs/',
                     'working/logs/', 'working/tuning.csv', 'working/overrides.csv',
                     'working/exemplars.csv'])

    log('============================================')
    log(f'Scoring cycle {cycle} complete')
    log(f'Results: {cycle_dir}')
    log('============================================')


# ============================================================================
# Internal helpers
# ============================================================================

def _resolve_filter(args):
    if args.scenes:
        return ('scenes', args.scenes, None)
    if args.act:
        return ('act', args.act, None)
    if hasattr(args, 'from_seq') and args.from_seq:
        return ('from_seq', args.from_seq, None)
    return ('all', None, None)


def _determine_cycle(project_dir: str) -> int:
    """Determine the scoring cycle number."""
    cycle = get_current_cycle(project_dir)
    if cycle == 0:
        cycle = 1

    scores_dir = os.path.join(project_dir, 'working', 'scores')
    if cycle == 1 and os.path.isdir(scores_dir):
        highest = 0
        for name in os.listdir(scores_dir):
            if name.startswith('cycle-'):
                try:
                    n = int(name.removeprefix('cycle-'))
                    highest = max(highest, n)
                except ValueError:
                    pass
        if highest > 0:
            cycle = highest + 1

    return cycle


def _avg_word_count(metadata_csv: str, scene_ids: list, scenes_dir: str) -> int:
    """Calculate average word count from metadata or scene files."""
    values = get_column(metadata_csv, 'word_count')
    nums = [int(v) for v in values if v and v != '0'
            and v.isdigit()]
    if nums:
        return sum(nums) // len(nums)

    # Fallback: measure from scene files
    total = 0
    count = 0
    for sid in scene_ids:
        sf = os.path.join(scenes_dir, f'{sid}.md')
        if os.path.isfile(sf):
            with open(sf) as f:
                total += len(f.read().split())
            count += 1
    return (total // count) if count > 0 else 3000


def _build_scene_prompt(scene_id: str, eval_template: str,
                        evaluation_criteria: str, weighted_text_str: str,
                        metadata_csv: str, intent_csv: str,
                        scenes_dir: str) -> str:
    """Build the evaluation prompt for a single scene."""
    scene_file = os.path.join(scenes_dir, f'{scene_id}.md')
    scene_text = ''
    if os.path.isfile(scene_file):
        with open(scene_file) as f:
            scene_text = f.read()

    scene_title = get_field(metadata_csv, scene_id, 'title') or 'Unknown'
    scene_pov = get_field(metadata_csv, scene_id, 'pov') or 'Unknown'
    scene_function = ''
    scene_emotional_arc = ''
    if os.path.isfile(intent_csv):
        scene_function = get_field(intent_csv, scene_id, 'function') or 'Not specified'
        scene_emotional_arc = get_field(intent_csv, scene_id, 'emotional_arc') or 'Not specified'

    # Number lines
    numbered = '\n'.join(f'{i+1}: {line}' for i, line in enumerate(scene_text.splitlines()))

    prompt = eval_template
    prompt = prompt.replace('{{SCENE_TITLE}}', scene_title)
    prompt = prompt.replace('{{SCENE_POV}}', scene_pov)
    prompt = prompt.replace('{{SCENE_FUNCTION}}', scene_function or 'Not specified')
    prompt = prompt.replace('{{SCENE_EMOTIONAL_ARC}}', scene_emotional_arc or 'Not specified')
    prompt = prompt.replace('{{EVALUATION_CRITERIA}}', evaluation_criteria)
    prompt = prompt.replace('{{WEIGHTED_PRINCIPLES}}', weighted_text_str)
    prompt = prompt.replace('{{SCENE_TEXT}}', numbered)
    return prompt


def _parse_scene_evaluation(text_content: str, output_scores: str,
                            output_rationale: str, scene_id: str,
                            diagnostics_csv: str) -> bool:
    """Parse scene evaluation text into score/rationale CSVs."""
    from storyforge.scoring import parse_scene_evaluation
    try:
        scores_csv, rationale_csv = parse_scene_evaluation(
            text_content, scene_id, diagnostics_csv)
        if scores_csv:
            with open(output_scores, 'w') as f:
                f.write(scores_csv)
        if rationale_csv:
            with open(output_rationale, 'w') as f:
                f.write(rationale_csv)
        return bool(scores_csv)
    except Exception as e:
        log(f'WARNING: Parse failed for {scene_id}: {e}')
        return False


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


# ============================================================================
# Scoring modes
# ============================================================================

def _score_batch(scene_ids, eval_model, eval_template, evaluation_criteria,
                 weighted_text_str, metadata_csv, intent_csv, scenes_dir,
                 cycle_dir, log_dir, diagnostics_csv, plugin_dir):
    """Batch mode scoring. Returns (scored, failed)."""
    log('')
    log(f'Building batch request for {len(scene_ids)} scenes...')

    batch_file = os.path.join(cycle_dir, '.batch-requests.jsonl')
    _safe_remove(batch_file)

    for sid in scene_ids:
        prompt = _build_scene_prompt(sid, eval_template, evaluation_criteria,
                                     weighted_text_str, metadata_csv, intent_csv,
                                     scenes_dir)
        request = {
            'custom_id': sid,
            'params': {
                'model': eval_model,
                'max_tokens': 4096,
                'messages': [{'role': 'user', 'content': prompt}],
            },
        }
        with open(batch_file, 'a') as f:
            f.write(json.dumps(request) + '\n')

    log(f'Submitting batch ({os.path.getsize(batch_file)} bytes)...')
    batch_id = submit_batch(batch_file)
    log(f'Batch submitted: {batch_id}')
    log('Polling for results...')
    results_url = poll_batch(batch_id, log_fn=log)
    log('Results downloaded. Parsing...')
    download_batch_results(results_url, cycle_dir, log_dir)

    scored = 0
    failed = 0
    from storyforge.scoring import merge_score_files

    for sid in scene_ids:
        scene_title = get_field(metadata_csv, sid, 'title') or sid
        status_file = os.path.join(cycle_dir, f'.status-{sid}')
        text_file = os.path.join(log_dir, f'{sid}.txt')
        json_file = os.path.join(log_dir, f'{sid}.json')

        status_ok = (os.path.isfile(status_file) and
                     open(status_file).read().strip() == 'ok' and
                     os.path.isfile(text_file))

        if status_ok:
            # Log usage
            if os.path.isfile(json_file):
                _log_api_usage(json_file, 'score', sid, eval_model,
                               os.path.dirname(os.path.dirname(cycle_dir)))

            text_content = open(text_file).read()
            tmp_scores = os.path.join(cycle_dir, f'.tmp-scores-{sid}.csv')
            tmp_rationale = os.path.join(cycle_dir, f'.tmp-rationale-{sid}.csv')

            if _parse_scene_evaluation(text_content, tmp_scores, tmp_rationale,
                                       sid, diagnostics_csv):
                merge_score_files(os.path.join(cycle_dir, 'scene-scores.csv'), tmp_scores)
                merge_score_files(os.path.join(cycle_dir, 'scene-rationale.csv'), tmp_rationale)
                scored += 1
                log(f'  {scene_title} scored ({scored}/{len(scene_ids)})')
            else:
                failed += 1
                log(f'  WARNING: Failed to parse {sid}')
            _safe_remove(tmp_scores)
            _safe_remove(tmp_rationale)
        else:
            failed += 1
            log(f'  WARNING: Failed {sid}')
        _safe_remove(status_file)

    _safe_remove(batch_file)
    return scored, failed


def _score_direct(scene_ids, eval_model, eval_template, evaluation_criteria,
                  weighted_text_str, metadata_csv, intent_csv, scenes_dir,
                  cycle_dir, log_dir, diagnostics_csv, plugin_dir,
                  parallel, score_start):
    """Direct mode scoring with parallel workers. Returns (scored, failed)."""
    from storyforge.runner import run_batched
    from storyforge.scoring import merge_score_files

    log(f'Parallel workers: {parallel}')

    scored = 0
    failed = 0
    project_dir = os.path.dirname(os.path.dirname(cycle_dir))

    def score_one(sid):
        prompt = _build_scene_prompt(sid, eval_template, evaluation_criteria,
                                     weighted_text_str, metadata_csv, intent_csv,
                                     scenes_dir)
        log_file = os.path.join(log_dir, f'score-{sid}.json')

        try:
            response = invoke_to_file(prompt, eval_model, log_file, 4096)
            _log_api_usage(log_file, 'score', sid, eval_model, project_dir)

            text = extract_text(response)
            tmp_scores = os.path.join(cycle_dir, f'.tmp-scores-{sid}.csv')
            tmp_rationale = os.path.join(cycle_dir, f'.tmp-rationale-{sid}.csv')

            ok = _parse_scene_evaluation(text, tmp_scores, tmp_rationale,
                                         sid, diagnostics_csv)
            return {'ok': ok, 'scores': tmp_scores, 'rationale': tmp_rationale}
        except Exception as e:
            log(f'    [{sid}] FAILED (API error): {e}')
            return {'ok': False}

    def merge_one(sid, result):
        nonlocal scored, failed
        scene_title = get_field(metadata_csv, sid, 'title') or sid

        if isinstance(result, Exception) or not result.get('ok'):
            failed += 1
            log(f'  WARNING: Failed to score {sid}')
            return

        merge_score_files(os.path.join(cycle_dir, 'scene-scores.csv'),
                          result['scores'])
        merge_score_files(os.path.join(cycle_dir, 'scene-rationale.csv'),
                          result['rationale'])
        scored += 1
        log(f'  {scene_title} scored ({scored}/{len(scene_ids)})')
        _safe_remove(result.get('scores', ''))
        _safe_remove(result.get('rationale', ''))

    run_batched(scene_ids, score_one, merge_fn=merge_one,
                batch_size=parallel, label='scene')

    return scored, failed


# ============================================================================
# Higher-level scoring phases
# ============================================================================

def _run_fidelity_scoring(filtered_ids, project_dir, scenes_dir, log_dir,
                          cycle_dir, briefs_csv, score_mode, sonnet_model,
                          plugin_dir):
    """Run brief fidelity scoring."""
    # Count scenes with brief data
    brief_count = 0
    with open(briefs_csv) as f:
        header = None
        goal_idx = 1  # fallback
        for i, line in enumerate(f):
            if i == 0:
                header = line.strip().split('|')
                if 'goal' in header:
                    goal_idx = header.index('goal')
                continue
            fields = line.strip().split('|')
            if len(fields) > goal_idx and fields[goal_idx].strip():
                brief_count += 1

    if brief_count == 0:
        log('No scenes with brief data — skipping fidelity scoring')
        return

    log(f'Running brief fidelity scoring ({brief_count} scenes with briefs)...')

    from storyforge.scoring import (
        build_fidelity_prompt, parse_fidelity_response,
        write_fidelity_csv, generate_fidelity_diagnosis,
    )

    if score_mode == 'batch':
        fidelity_batch = os.path.join(log_dir, f'fidelity-batch-{os.getpid()}.jsonl')
        _safe_remove(fidelity_batch)

        for sid in filtered_ids:
            if not os.path.isfile(os.path.join(scenes_dir, f'{sid}.md')):
                continue
            prompt = build_fidelity_prompt(sid, project_dir, plugin_dir)
            if not prompt:
                continue
            request = {
                'custom_id': f'fidelity-{sid}',
                'params': {
                    'model': sonnet_model,
                    'max_tokens': 2048,
                    'messages': [{'role': 'user', 'content': prompt}],
                },
            }
            with open(fidelity_batch, 'a') as f:
                f.write(json.dumps(request) + '\n')

        if os.path.isfile(fidelity_batch):
            line_count = sum(1 for _ in open(fidelity_batch))
            if line_count > 0:
                log(f'  Submitting fidelity batch ({line_count} scenes)...')
                batch_id = submit_batch(fidelity_batch)
                results_url = poll_batch(batch_id, log_fn=log)
                fidelity_output = os.path.join(log_dir, 'fidelity-output')
                os.makedirs(fidelity_output, exist_ok=True)
                download_batch_results(results_url, fidelity_output, log_dir)
            _safe_remove(fidelity_batch)
    else:
        for sid in filtered_ids:
            if not os.path.isfile(os.path.join(scenes_dir, f'{sid}.md')):
                continue
            prompt = build_fidelity_prompt(sid, project_dir, plugin_dir)
            if not prompt:
                continue
            fidelity_log = os.path.join(log_dir, f'fidelity-{sid}.json')
            try:
                invoke_to_file(prompt, sonnet_model, fidelity_log, 2048)
                _log_api_usage(fidelity_log, 'score-fidelity', sid,
                               sonnet_model, project_dir)
            except Exception:
                log(f'  WARNING: Fidelity scoring failed for {sid}')

    # Process results
    results = []
    for sid in filtered_ids:
        for path in [os.path.join(log_dir, f'fidelity-{sid}.txt'),
                     os.path.join(log_dir, f'fidelity-{sid}.json')]:
            if not os.path.isfile(path):
                continue
            text = open(path).read()
            try:
                data = json.loads(text)
                text = ''.join(item.get('text', '')
                               for item in data.get('content', [])
                               if item.get('type') == 'text')
            except (json.JSONDecodeError, KeyError):
                pass
            if text:
                result = parse_fidelity_response(text, sid)
                if result.get('scores'):
                    results.append(result)
                break

    if results:
        write_fidelity_csv(results, cycle_dir)
        diagnosis = generate_fidelity_diagnosis(results)
        avg_overall = sum(r['overall'] for r in results) / len(results)
        log(f'  Fidelity: {len(results)} scenes scored, avg {avg_overall:.1f}/5')
        high_priority = [d for d in diagnosis if d.get('priority') == 'high']
        if high_priority:
            log('  High-priority fidelity gaps:')
            for d in high_priority:
                log(f'    {d["element"]}: avg {d["avg_score"]}/5 '
                    f'({d["weak_count"]}/{d["total_scenes"]} weak)')
    else:
        log('  No fidelity results to process')


def _run_act_scoring(scene_ids, metadata_csv, scenes_dir, cycle_dir, log_dir,
                     prompts_dir, weights_file, sonnet_model, plugin_dir,
                     dry_run):
    """Run act-level scoring."""
    act_template_file = os.path.join(prompts_dir, 'act-level.md')
    if not os.path.isfile(act_template_file):
        log('WARNING: Act-level template not found, skipping')
        return

    with open(act_template_file) as f:
        act_template = f.read()

    # Discover unique acts
    act_values = get_column(metadata_csv, 'part')
    acts = list(dict.fromkeys(v for v in act_values if v))  # unique, ordered

    from storyforge.scoring import (
        extract_rubric_section, build_weighted_text, parse_score_output, merge_score_files,
    )

    for act_label in acts:
        act_scenes_text = ''
        act_scene_count = 0
        act_id = f'act-{act_label}'

        for sid in scene_ids:
            scene_part = get_field(metadata_csv, sid, 'part')
            if scene_part != act_label:
                continue
            scene_file = os.path.join(scenes_dir, f'{sid}.md')
            if not os.path.isfile(scene_file):
                continue
            scene_title = get_field(metadata_csv, sid, 'title') or sid
            with open(scene_file) as f:
                act_scenes_text += f'\n\n--- Scene: {scene_title} ({sid}) ---\n\n{f.read()}'
            act_scene_count += 1

        if act_scene_count == 0:
            log(f'  Skipping act {act_label}: no scored scenes')
            continue

        narrative_rubric = extract_rubric_section('Narrative Frameworks', plugin_dir)
        character_rubric = extract_rubric_section('Character Craft', plugin_dir)
        wt = build_weighted_text(weights_file)

        prompt = act_template
        prompt = prompt.replace('{{NARRATIVE_FRAMEWORKS_RUBRIC}}', narrative_rubric)
        prompt = prompt.replace('{{CHARACTER_CRAFT_ACT_RUBRIC}}', character_rubric)
        prompt = prompt.replace('{{ACT_LABEL}}', act_label)
        prompt = prompt.replace('{{SCENE_COUNT}}', str(act_scene_count))
        prompt = prompt.replace('{{ACT_SCENES_TEXT}}', act_scenes_text)
        prompt = prompt.replace('{{WEIGHTED_PRINCIPLES}}', wt)
        prompt = prompt.replace('{{ACT_ID}}', act_id)

        log(f'  Scoring act {act_label} ({act_scene_count} scenes)...')

        if dry_run:
            continue

        log_file = os.path.join(log_dir, f'score-{act_id}.json')
        project_dir = os.path.dirname(os.path.dirname(cycle_dir))

        try:
            response = invoke_to_file(prompt, sonnet_model, log_file, 4096)
            text = extract_text(response)
            _log_api_usage(log_file, 'score', act_id, sonnet_model, project_dir)

            tmp_scores = os.path.join(cycle_dir, f'.tmp-act-scores-{act_label}.csv')
            tmp_rationale = os.path.join(cycle_dir, f'.tmp-act-rationale-{act_label}.csv')

            scores_csv, rationale_csv = parse_score_output(text)
            if scores_csv:
                with open(tmp_scores, 'w') as f:
                    f.write(scores_csv)
                merge_score_files(os.path.join(cycle_dir, 'act-scores.csv'), tmp_scores)
                _safe_remove(tmp_scores)
            if rationale_csv:
                with open(tmp_rationale, 'w') as f:
                    f.write(rationale_csv)
                merge_score_files(os.path.join(cycle_dir, 'act-rationale.csv'), tmp_rationale)
                _safe_remove(tmp_rationale)
            log(f'  Act {act_label} scored')
        except Exception as e:
            log(f'  WARNING: Failed to score act {act_label}: {e}')


def _run_novel_scoring(scene_count, metadata_csv, intent_csv, project_dir,
                       cycle_dir, log_dir, prompts_dir, weights_file,
                       sonnet_model, plugin_dir, dry_run):
    """Run novel-level character + genre scoring."""
    novel_template_file = os.path.join(prompts_dir, 'novel-level.md')
    if not os.path.isfile(novel_template_file):
        log('WARNING: Novel-level template not found, skipping')
        return

    with open(novel_template_file) as f:
        novel_template = f.read()

    manuscript_summary = f'Scene count: {scene_count}'

    # Character list from intent.csv
    if os.path.isfile(intent_csv):
        chars = get_column(intent_csv, 'characters')
        all_chars = set()
        for c in chars:
            for name in c.split(';'):
                name = name.strip()
                if name:
                    all_chars.add(name)
        if all_chars:
            char_list = sorted(all_chars)[:20]
            manuscript_summary += '\n\nCharacters mentioned across scenes:\n'
            manuscript_summary += '\n'.join(f'- {c}' for c in char_list)

    # Character bible and story architecture
    character_bible = _read_reference(project_dir, ['reference/character-bible.md',
                                                     'references/character-bible.md'])
    story_architecture = _read_reference(project_dir, ['reference/story-architecture.md',
                                                        'references/story-architecture.md'])

    from storyforge.scoring import extract_rubric_section, build_weighted_text, parse_score_output

    char_rubric = extract_rubric_section('Character Craft', plugin_dir)
    genre_rubric = extract_rubric_section('Tropes and Genre', plugin_dir)
    wt = build_weighted_text(weights_file)

    prompt = novel_template
    prompt = prompt.replace('{{CHARACTER_CRAFT_NOVEL_RUBRIC}}', char_rubric)
    prompt = prompt.replace('{{GENRE_RUBRIC}}', genre_rubric)
    prompt = prompt.replace('{{MANUSCRIPT_SUMMARY}}', manuscript_summary)
    prompt = prompt.replace('{{CHARACTER_BIBLE}}', character_bible or 'No character bible found.')
    prompt = prompt.replace('{{STORY_ARCHITECTURE}}', story_architecture or 'No story architecture found.')
    prompt = prompt.replace('{{WEIGHTED_PRINCIPLES}}', wt)

    if dry_run:
        return

    log('  Scoring novel-level character + genre...')
    log_file = os.path.join(log_dir, 'score-novel-level.json')

    try:
        response = invoke_to_file(prompt, sonnet_model, log_file, 4096)
        text = extract_text(response)
        _log_api_usage(log_file, 'score', 'novel-level', sonnet_model, project_dir)

        # Write text for parse_output
        text_log = os.path.join(log_dir, 'score-novel-level.log')
        with open(text_log, 'w') as f:
            f.write(text)

        # Parse character scores
        for section, marker_prefix in [('character', 'CHARACTER'), ('genre', 'GENRE')]:
            scores_csv, rationale_csv = parse_score_output(
                text,
                score_marker=f'{marker_prefix}_SCORES',
                rationale_marker=f'{marker_prefix}_RATIONALE',
            )
            if scores_csv:
                with open(os.path.join(cycle_dir, f'{section}-scores.csv'), 'w') as f:
                    f.write(scores_csv)
            if rationale_csv:
                with open(os.path.join(cycle_dir, f'{section}-rationale.csv'), 'w') as f:
                    f.write(rationale_csv)

        log('  Novel-level scoring complete')
    except Exception as e:
        log(f'  WARNING: Novel-level scoring failed: {e}')


def _run_narrative_scoring(title, metadata_csv, project_dir, cycle_dir,
                           log_dir, prompts_dir, weights_file, dry_run):
    """Run novel-level narrative framework scoring."""
    narrative_template_file = os.path.join(prompts_dir, 'novel-narrative.md')
    if not os.path.isfile(narrative_template_file):
        log(f'WARNING: Narrative template not found at {narrative_template_file}, skipping')
        return

    with open(narrative_template_file) as f:
        narrative_template = f.read()

    story_arch = _read_reference(project_dir, ['reference/story-architecture.md',
                                                'references/story-architecture.md'])
    scene_index = ''
    if os.path.isfile(metadata_csv):
        with open(metadata_csv) as f:
            lines = f.readlines()
        scene_index = ''.join(l for i, l in enumerate(lines)
                              if i == 0 or not l.strip().endswith('cut'))

    chapter_map = ''
    chapter_map_file = os.path.join(project_dir, 'reference', 'chapter-map.csv')
    if os.path.isfile(chapter_map_file):
        with open(chapter_map_file) as f:
            chapter_map = f.read()

    from storyforge.scoring import build_weighted_text, parse_score_output

    wt = build_weighted_text(weights_file)

    prompt = narrative_template
    prompt = prompt.replace('{{PROJECT_TITLE}}', title)
    prompt = prompt.replace('{{STORY_ARCHITECTURE}}', story_arch or 'No story architecture found.')
    prompt = prompt.replace('{{SCENE_INDEX}}', scene_index or 'No scene metadata available.')
    prompt = prompt.replace('{{CHAPTER_MAP}}', chapter_map or 'No chapter map available.')
    prompt = prompt.replace('{{WEIGHTED_PRINCIPLES}}', wt)

    narrative_model = select_model('evaluation')
    log(f'  Scoring narrative frameworks (model: {narrative_model})...')

    if dry_run:
        return

    log_file = os.path.join(log_dir, 'score-narrative.json')
    narr_scores = os.path.join(cycle_dir, 'narrative-scores.csv')
    narr_rationale = os.path.join(cycle_dir, 'narrative-rationale.csv')

    try:
        response = invoke_to_file(prompt, narrative_model, log_file, 4096)
        text = extract_text(response)
        _log_api_usage(log_file, 'score', 'narrative', narrative_model, project_dir)

        text_log = os.path.join(log_dir, 'score-narrative.log')
        with open(text_log, 'w') as f:
            f.write(text)

        scores_csv, rationale_csv = parse_score_output(text)
        if scores_csv:
            with open(narr_scores, 'w') as f:
                f.write(scores_csv)
        if rationale_csv:
            with open(narr_rationale, 'w') as f:
                f.write(rationale_csv)
        if os.path.isfile(narr_scores):
            log(f'  Narrative scores saved to {os.path.basename(narr_scores)}')
        else:
            log('  WARNING: Failed to parse narrative scores')
    except Exception as e:
        log(f'  WARNING: Narrative scoring API call failed: {e}')


def _run_improvement_cycle(cycle, cycle_dir, project_dir, weights_file,
                           plugin_dir, intent_csv, title):
    """Run diagnosis, proposals, and apply approved changes."""
    from storyforge.scoring import generate_diagnosis, generate_proposals
    from storyforge.csv_cli import update_field as csv_update

    # Previous cycle
    prev_dir = ''
    if cycle > 1:
        prev_dir = os.path.join(project_dir, 'working', 'scores', f'cycle-{cycle - 1}')
        if not os.path.isdir(prev_dir):
            prev_dir = ''

    generate_diagnosis(cycle_dir, prev_dir or '-', weights_file)
    generate_proposals(cycle_dir, weights_file)

    proposals_file = os.path.join(cycle_dir, 'proposals.csv')
    diagnosis_file = os.path.join(cycle_dir, 'diagnosis.csv')

    if not os.path.isfile(proposals_file):
        log('No proposals generated')
        return

    # Count proposals
    with open(proposals_file) as f:
        lines = [l.strip() for l in f if l.strip()]
    proposal_count = len(lines) - 1  # subtract header
    log(f'Generated {proposal_count} improvement proposals')

    if proposal_count <= 0:
        return

    coaching = get_coaching_level(project_dir)

    if coaching == 'full':
        log('Coaching level: full — auto-approving all proposals')
        _approve_all_proposals(proposals_file)
    elif coaching == 'coach':
        log('Coaching level: coach — proposals require interactive approval')
        # In non-interactive script, just report
    elif coaching == 'strict':
        log('Coaching level: strict — diagnosis and proposals generated as report only')
        _print_strict_report(diagnosis_file, proposals_file)
        return

    # Apply approved proposals
    if coaching != 'strict':
        applied = _apply_proposals(proposals_file, weights_file, intent_csv,
                                   project_dir)
        log(f'{applied} proposals applied. Run storyforge write to rewrite with updated guidance.')

    # Collect exemplars
    from storyforge.scoring import collect_exemplars
    collect_exemplars(cycle_dir, project_dir, str(cycle))

    # Check for validated patterns
    from storyforge.scoring import check_validated_patterns
    validated = check_validated_patterns(project_dir)
    if validated:
        log('Validated tuning patterns found:')
        for line in validated.strip().split('\n'):
            if not line.strip():
                continue
            parts = line.split('|')
            if len(parts) >= 3:
                log(f'  {parts[0]} ({parts[1]}): avg improvement {parts[2]}')


def _approve_all_proposals(proposals_file: str) -> None:
    """Set all pending proposals to approved."""
    with open(proposals_file) as f:
        lines = f.readlines()
    header = lines[0].strip().split('|') if lines else []
    status_idx = header.index('status') if 'status' in header else 6
    with open(proposals_file, 'w') as f:
        for i, line in enumerate(lines):
            if i == 0:
                f.write(line)
                continue
            fields = line.rstrip('\n').split('|')
            if len(fields) > status_idx:
                fields[status_idx] = 'approved'
            f.write('|'.join(fields) + '\n')


def _print_strict_report(diagnosis_file: str, proposals_file: str) -> None:
    """Print diagnosis and proposals for strict mode."""
    print('\n=== Diagnosis Summary ===')
    if os.path.isfile(diagnosis_file):
        with open(diagnosis_file) as f:
            lines = f.readlines()
        if lines:
            d_header = lines[0].strip().split('|')
            d_col = {name: i for i, name in enumerate(d_header)}
            for line in lines[1:]:
                fields = line.strip().split('|')
                priority = fields[d_col['priority']] if 'priority' in d_col and d_col['priority'] < len(fields) else ''
                if priority in ('high', 'medium'):
                    principle = fields[d_col.get('principle', 0)] if d_col.get('principle', 0) < len(fields) else ''
                    scale = fields[d_col.get('scale', 1)] if d_col.get('scale', 1) < len(fields) else ''
                    avg_score = fields[d_col.get('avg_score', 2)] if d_col.get('avg_score', 2) < len(fields) else ''
                    print(f'  {principle} ({scale}): avg {avg_score}, priority {priority}')
    print('\n=== Proposals (not applied in strict mode) ===')
    if os.path.isfile(proposals_file):
        with open(proposals_file) as f:
            lines = f.readlines()
        if lines:
            p_header = lines[0].strip().split('|')
            p_col = {name: i for i, name in enumerate(p_header)}
            for line in lines[1:]:
                fields = line.strip().split('|')
                pid = fields[p_col.get('id', 0)] if p_col.get('id', 0) < len(fields) else ''
                principle = fields[p_col.get('principle', 1)] if p_col.get('principle', 1) < len(fields) else ''
                change = fields[p_col.get('change', 4)] if p_col.get('change', 4) < len(fields) else ''
                rationale = fields[p_col.get('rationale', 5)] if p_col.get('rationale', 5) < len(fields) else ''
                print(f'  {pid}: {principle} — {change} ({rationale})')
    print()


def _apply_proposals(proposals_file, weights_file, intent_csv, project_dir):
    """Apply approved proposals. Returns count applied."""
    applied = 0

    with open(proposals_file) as f:
        lines = f.readlines()

    if not lines:
        return applied
    header = lines[0].strip().split('|')
    col = {name: i for i, name in enumerate(header)}

    for line in lines[1:]:
        fields = line.strip().split('|')
        if len(fields) < len(header):
            continue
        pid = fields[col.get('id', 0)]
        principle = fields[col.get('principle', 1)]
        lever = fields[col.get('lever', 2)]
        target = fields[col.get('target', 3)]
        change = fields[col.get('change', 4)]
        rationale = fields[col.get('rationale', 5)]
        status = fields[col.get('status', 6)]
        if status != 'approved':
            continue

        if lever == 'craft_weight':
            import re
            m = re.search(r'→\s*(\d+)', change)
            if m:
                update_field(weights_file, principle, 'weight', m.group(1),
                             key_col='principle')
                applied += 1
                update_field(proposals_file, pid, 'status', 'applied')
        elif lever in ('scene_intent', 'voice_guide', 'override'):
            overrides_file = os.path.join(project_dir, 'working', 'overrides.csv')
            if not os.path.isfile(overrides_file):
                with open(overrides_file, 'w') as f:
                    f.write('id|principle|directive|source\n')
            target_id = target if lever == 'scene_intent' else 'global'
            if lever == 'override':
                target_id = target
            with open(overrides_file, 'a') as f:
                f.write(f'{target_id}|{principle}|{change}|{pid}\n')
            applied += 1
            update_field(proposals_file, pid, 'status', 'applied')

    return applied


def _generate_report_and_comment(cycle, cycle_dir, project_dir, score_mode,
                                 scene_count):
    """Generate scoring report and post PR comment."""
    # Calculate total cost
    ledger = os.path.join(project_dir, 'working', 'costs', 'ledger.csv')
    total_cost = 0.0
    if os.path.isfile(ledger):
        with open(ledger) as f:
            lines = f.readlines()
        if lines:
            l_header = lines[0].strip().split('|')
            l_col = {name: i for i, name in enumerate(l_header)}
            op_idx = l_col.get('operation', 1)
            cost_idx = l_col.get('cost_usd', 8)
            for line in lines[1:]:
                parts = line.strip().split('|')
                if len(parts) > max(op_idx, cost_idx) and parts[op_idx] == 'score':
                    try:
                        total_cost += float(parts[cost_idx])
                    except (ValueError, IndexError):
                        pass

    from storyforge.scoring import generate_score_report, build_score_pr_comment
    generate_score_report(cycle_dir, project_dir, str(cycle), score_mode,
                          scene_count, f'{total_cost:.2f}')

    if has_gh():
        comment = build_score_pr_comment(cycle_dir, project_dir, str(cycle),
                                          score_mode, scene_count,
                                          f'{total_cost:.2f}')
        if comment:
            r = subprocess.run(
                ['gh', 'pr', 'view', '--json', 'number', '-q', '.number'],
                capture_output=True, text=True, cwd=project_dir,
            )
            pr_num = r.stdout.strip() if r.returncode == 0 else ''
            if pr_num:
                subprocess.run(
                    ['gh', 'pr', 'comment', pr_num, '--body', comment],
                    capture_output=True, cwd=project_dir,
                )
                log(f'Posted scoring summary to PR #{pr_num}')


def _read_reference(project_dir: str, candidates: list) -> str:
    """Read the first existing reference file."""
    for ref in candidates:
        path = os.path.join(project_dir, ref)
        if os.path.isfile(path):
            with open(path) as f:
                return f.read()
    return ''


def _print_dry_run(score_mode, scene_count, parallel, cycle, eval_model,
                   scene_cost, scene_ids, metadata_csv, cycle_dir):
    """Print dry-run summary."""
    log('============================================')
    log('DRY RUN — Scoring Plan')
    log('============================================')
    log(f'Mode:     {score_mode}')
    log(f'Scenes:   {scene_count}')
    log(f'Parallel: {parallel}')
    log(f'Cycle:    {cycle}')
    log(f'Model:    {eval_model}')
    log(f'Estimate: ~${scene_cost:.2f}')
    log('')
    log('Scenes to score:')
    for sid in scene_ids:
        title = get_field(metadata_csv, sid, 'title') or 'untitled'
        log(f'  - {sid} ({title})')
    log('')
    if score_mode == 'batch':
        log(f'Batch mode: {scene_count} Opus calls via Batch API (50% off)')
        log('  Results typically arrive in 2-10 minutes')
    elif score_mode == 'direct':
        log(f'Direct mode: {scene_count} Sonnet calls, real-time, {parallel} parallel')
    else:
        log(f'Direct+deep mode: {scene_count} Opus calls, real-time, {parallel} parallel')
    log('')
    log('After scene scoring:')
    log('  - Act-level scoring')
    log('  - Novel-level character + genre scoring (1 invocation)')
    log('  - Novel-level narrative framework scoring (1 invocation)')
    log('')
    log(f'Output directory: {cycle_dir}')
    log('============================================')


def _safe_remove(path: str) -> None:
    try:
        if path:
            os.remove(path)
    except OSError:
        pass


if __name__ == '__main__':
    main()
