"""storyforge elaborate — Run elaboration stages (spine/architecture/map/briefs).

Each stage creates a branch, invokes Claude, parses structured output into CSVs,
runs validation, and opens a PR.

Usage:
    storyforge elaborate --stage spine              # Build the spine
    storyforge elaborate --stage architecture       # Expand to architecture
    storyforge elaborate --stage map                # Full scene map
    storyforge elaborate --stage briefs             # Write drafting briefs
    storyforge elaborate --stage gap-fill           # Fill missing fields
    storyforge elaborate --stage mice-fill          # Fix MICE dormancy gaps
    storyforge elaborate --stage spine --dry-run    # Print prompt, don't invoke
    storyforge elaborate --stage spine -i           # Interactive mode
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
    install_signal_handlers, get_plugin_dir, build_shared_context,
)
from storyforge.git import (
    create_branch, ensure_branch_pushed, create_draft_pr,
    update_pr_task, commit_and_push, run_review_phase,
)
from storyforge.costs import print_summary


# ============================================================================
# Helpers
# ============================================================================

def _python_lib():
    from pathlib import Path
    return str(Path(__file__).resolve().parent.parent)


VALID_STAGES = {'spine', 'architecture', 'map', 'briefs', 'gap-fill', 'mice-fill'}


# ============================================================================
# Argument parsing
# ============================================================================

def parse_args(argv):
    parser = argparse.ArgumentParser(
        prog='storyforge elaborate',
        description='Run an elaboration stage.',
    )
    parser.add_argument('--stage', type=str, default=None,
                        help='Which elaboration stage to run (spine|architecture|map|briefs|gap-fill|mice-fill)')
    # Accept stages as direct flags (e.g. --mice-fill, --gap-fill, --briefs)
    for stage in sorted(VALID_STAGES):
        parser.add_argument(f'--{stage}', action='store_true', dest=f'stage_{stage.replace("-", "_")}',
                            help=argparse.SUPPRESS)
    parser.add_argument('--seed', type=str, default='',
                        help='Seed text for spine stage (overrides logline)')
    parser.add_argument('--dry-run', action='store_true',
                        help='Print the prompt without invoking Claude')
    parser.add_argument('--interactive', '-i', action='store_true',
                        help='Run interactively via claude -p')
    parser.add_argument('--coaching', type=str, default=None,
                        choices=['full', 'coach', 'strict'],
                        help='Override coaching level')
    args = parser.parse_args(argv)

    # Resolve stage from direct flags if --stage not given
    if not args.stage:
        for stage in VALID_STAGES:
            if getattr(args, f'stage_{stage.replace("-", "_")}', False):
                args.stage = stage
                break
    if not args.stage:
        parser.error('a stage is required: --stage STAGE or --STAGE (e.g. --mice-fill)')

    return args


# ============================================================================
# MICE dormancy fill
# ============================================================================

def _run_mice_fill(project_dir: str, ref_dir: str, dry_run: bool,
                   max_passes: int = 5) -> None:
    """Detect MICE thread dormancy gaps and add thread mentions.

    Runs iteratively until gaps converge (large gaps split into smaller
    sub-gaps that need subsequent passes to fill).
    """
    log_dir = os.path.join(project_dir, 'working', 'logs')
    os.makedirs(log_dir, exist_ok=True)

    from storyforge.hone import detect_mice_dormancy, build_mice_fill_prompt, parse_mice_fill_response
    from storyforge.elaborate import _read_csv_as_map, _read_csv, _write_csv, _FILE_MAP, get_scene
    from storyforge.api import invoke_to_file, extract_text_from_file

    # Initial detection
    gaps = detect_mice_dormancy(ref_dir)
    if not gaps:
        log('No MICE dormancy gaps found.')
        return

    if dry_run:
        log(f'Found {len(gaps)} dormancy gaps.')
        for g in gaps:
            log(f'  {g["thread_id"]}: {g["gap_size"]} scenes between {g["before_scene"]} and {g["after_scene"]}')
        log('DRY RUN — would fill these dormancy gaps')
        return

    create_branch('mice-fill', project_dir)
    ensure_branch_pushed(project_dir)

    mice_model = select_model('evaluation')
    # Build shared context once for all MICE fill API calls (prompt caching)
    system = build_shared_context(project_dir, model=mice_model)
    grand_total = 0
    baseline_gaps = len(gaps)

    for pass_num in range(1, max_passes + 1):
        gaps = detect_mice_dormancy(ref_dir)
        gap_count = len(gaps)

        if gap_count == 0:
            log(f'  No gaps remaining — converged after {pass_num - 1} passes')
            break

        log(f'\n--- Pass {pass_num}/{max_passes} ({gap_count} gaps) ---')

        # Enrich gap scenes
        for g in gaps:
            enriched = []
            for sid in g['gap_scenes']:
                scene = get_scene(sid, ref_dir) or {}
                enriched.append({
                    'id': sid,
                    'title': scene.get('title', sid),
                    'goal': scene.get('goal', ''),
                    'function': scene.get('function', ''),
                })
            g['gap_scenes'] = enriched

        intent_map = _read_csv_as_map(os.path.join(ref_dir, 'scene-intent.csv'))
        pass_mentions = 0

        for gap in gaps:
            prompt = build_mice_fill_prompt(
                thread_id=gap['thread_id'],
                thread_name=gap['thread_name'],
                thread_type=gap['thread_type'],
                gap_scenes=gap['gap_scenes'],
                before_scene=gap['before_scene'],
                after_scene=gap['after_scene'],
            )

            log_file = os.path.join(log_dir, f'mice-fill-{gap["thread_id"]}.json')
            invoke_to_file(prompt, mice_model, log_file, max_tokens=512,
                           label=f'mice-fill {gap["thread_id"]}', system=system)
            response = extract_text_from_file(log_file)

            scene_ids = parse_mice_fill_response(response)
            if not scene_ids:
                log(f'  {gap["thread_id"]}: no scenes recommended')
                continue

            # Use bare thread name (without type: prefix) to match existing intent format
            bare_id = gap['thread_id']
            if ':' in bare_id:
                bare_id = bare_id.split(':', 1)[1]

            for sid in scene_ids:
                if sid not in intent_map:
                    continue
                current = intent_map[sid].get('mice_threads', '').strip()
                entries = [e.strip() for e in current.split(';') if e.strip()] if current else []
                if bare_id not in entries:
                    entries.append(bare_id)
                    intent_map[sid]['mice_threads'] = ';'.join(entries)
                    pass_mentions += 1

            log(f'  {gap["thread_id"]}: added mentions in {len(scene_ids)} scenes ({", ".join(scene_ids)})')

        # Write back and commit this pass
        if pass_mentions > 0:
            rows = list(intent_map.values())
            rows.sort(key=lambda r: r.get('id', ''))
            _write_csv(os.path.join(ref_dir, 'scene-intent.csv'), rows, _FILE_MAP['scene-intent.csv'])
            commit_and_push(project_dir,
                            f'Elaborate: MICE dormancy fill pass {pass_num} — {pass_mentions} mentions added',
                            ['reference/', 'working/'])

        grand_total += pass_mentions
        log(f'  Pass {pass_num}: {pass_mentions} mentions added')

        if pass_mentions == 0:
            log('  Nothing added — converged')
            break
    else:
        log(f'\n  Reached max passes ({max_passes})')

    # Final summary
    final_gaps = len(detect_mice_dormancy(ref_dir))
    log(f'\nMICE dormancy fill complete.')
    log(f'  Before: {baseline_gaps} gaps')
    log(f'  After:  {final_gaps} gaps')
    log(f'  Total mentions added: {grand_total} across {pass_num} passes')


# ============================================================================
# Gap-fill
# ============================================================================

def _run_gap_fill(project_dir: str, ref_dir: str, dry_run: bool,
                  session_start: str | None = None) -> None:
    """Analyze gaps, batch-fill parallel fields, sequential knowledge fix."""
    scenes_dir = os.path.join(project_dir, 'scenes')
    gap_dir = os.path.join(project_dir, 'working', 'gap-fill')
    log_dir = os.path.join(project_dir, 'working', 'logs')
    os.makedirs(gap_dir, exist_ok=True)
    os.makedirs(log_dir, exist_ok=True)

    log('Analyzing gaps...')

    from storyforge.elaborate import analyze_gaps, validate_structure, update_scene, get_scenes
    from storyforge.api import submit_batch, poll_batch, download_batch_results, invoke, extract_text, build_batch_request
    from storyforge.prompts_elaborate import build_gap_fill_prompt, build_knowledge_fix_prompt, csv_block_to_rows
    from storyforge.enrich import format_registries_for_prompt, load_registry_alias_maps, normalize_fields

    gap_analysis = analyze_gaps(ref_dir)
    total_gaps = gap_analysis['total_gaps']
    groups = gap_analysis['groups']
    group_count = len(groups)

    if total_gaps == 0 and group_count == 0:
        log('No gaps found — all validation checks pass.')
    else:
        log(f'Found {total_gaps} field gaps across {group_count} group(s)')
        for name, group in groups.items():
            scene_count = len(group['scenes'])
            count = group['count']
            log(f'  {name}: {count} missing field(s) across {scene_count} scene(s)')

        if dry_run:
            log('DRY RUN — would fill these gaps')
            for name, group in groups.items():
                log(f'=== {name} ({group["batch_type"]}) ===')
                for sid, gap_fields in group['scenes'].items():
                    log(f'  {sid}: {gap_fields}')
            return

        # Branch and PR
        create_branch('gap-fill', project_dir)
        ensure_branch_pushed(project_dir)

        project_title = read_yaml_field('project.title', project_dir) or 'Untitled'
        pr_body = (
            f'## Gap-Fill: {project_title}\n\n'
            f'**Gaps found:** {total_gaps} across {group_count} group(s)\n\n'
            f'### Tasks\n'
            f'- [ ] Fill parallel field gaps\n'
            f'- [ ] Fix knowledge chain\n'
            f'- [ ] Validate'
        )
        pr_number = create_draft_pr(
            f'Elaborate: {project_title} — gap-fill', pr_body, project_dir, 'elaboration'
        )

        gap_model = select_model('evaluation')
        alias_maps = load_registry_alias_maps(project_dir)

        # Build shared context once for all gap-fill API calls (prompt caching)
        system = build_shared_context(project_dir, model=gap_model)

        # Parallel gap groups: build single batch
        parallel_groups = {k: v for k, v in groups.items() if v['batch_type'] == 'parallel'}
        parallel_count = sum(len(v['scenes']) for v in parallel_groups.values())

        if parallel_count > 0:
            log(f'Building batch for {parallel_count} parallel gap-fill requests...')
            registries = format_registries_for_prompt(project_dir)

            batch_file = os.path.join(gap_dir, 'gap-fill-batch.jsonl')
            batch_output = os.path.join(gap_dir, 'batch-output')
            batch_logs = os.path.join(gap_dir, 'batch-logs')
            os.makedirs(batch_output, exist_ok=True)
            os.makedirs(batch_logs, exist_ok=True)

            with open(batch_file, 'w') as bf:
                for group_name, group_data in parallel_groups.items():
                    for scene_id, missing_fields in group_data['scenes'].items():
                        prompt = build_gap_fill_prompt(
                            scene_id=scene_id,
                            gap_group=group_name,
                            missing_fields=missing_fields,
                            project_dir=project_dir,
                            scenes_dir=scenes_dir,
                            registries_text=registries,
                        )
                        custom_id = f'{group_name}__{scene_id}'
                        req = build_batch_request(custom_id, prompt, gap_model,
                                                  max_tokens=256, system=system)
                        bf.write(json.dumps(req) + '\n')

            log('Submitting batch...')
            batch_id = submit_batch(batch_file)
            log(f'Batch ID: {batch_id}')

            log('Polling batch...')
            results_url = poll_batch(batch_id, log_fn=log)

            log('Downloading results...')
            succeeded = download_batch_results(results_url, batch_output, batch_logs)

            log('Applying parallel gap-fill results...')
            applied = 0
            for fname in os.listdir(batch_logs):
                if not fname.endswith('.txt'):
                    continue
                custom_id = fname[:-4]
                status_file = os.path.join(batch_output, f'.status-{custom_id}')
                if not os.path.isfile(status_file) or open(status_file).read().strip() != 'ok':
                    continue

                text = open(os.path.join(batch_logs, fname)).read().strip()
                rows = csv_block_to_rows(text)
                if not rows:
                    continue

                row = rows[0]
                normalize_fields(row, alias_maps)
                scene_id = row.get('id', '')
                if not scene_id:
                    scene_id = custom_id.split('__', 1)[-1] if '__' in custom_id else ''
                if not scene_id:
                    continue

                updates = {k: v for k, v in row.items() if k != 'id' and v.strip()}
                if updates:
                    update_scene(scene_id, ref_dir, updates)
                    applied += 1

            log(f'  Applied {applied} gap-fill results')
            update_pr_task('Fill parallel field gaps', project_dir, pr_number)

        # Sequential knowledge fix
        knowledge_group = groups.get('knowledge', {})
        knowledge_count = len(knowledge_group.get('scenes', {}))
        knowledge_failures = len([
            f for f in gap_analysis.get('validation', {}).get('failures', [])
            if f.get('category') == 'knowledge'
        ])

        if knowledge_count > 0 or knowledge_failures > 0:
            log(f'Running sequential knowledge fix ({knowledge_count} empty fields, {knowledge_failures} wording mismatches)...')

            all_scenes = get_scenes(ref_dir, columns=[
                'id', 'seq', 'knowledge_in', 'knowledge_out', 'continuity_deps',
            ])
            knowledge_log_dir = os.path.join(gap_dir, 'knowledge-logs')
            os.makedirs(knowledge_log_dir, exist_ok=True)

            available_knowledge = set()
            fixed = 0

            for scene in all_scenes:
                sid = scene['id']
                kin = scene.get('knowledge_in', '').strip()
                kout = scene.get('knowledge_out', '').strip()

                needs_fix = False
                seq_val = scene.get('seq', '0')
                seq_int = int(seq_val) if seq_val.isdigit() else 0
                if not kin and seq_int > 1:
                    needs_fix = True
                elif not kout:
                    needs_fix = True
                elif kin and available_knowledge:
                    facts_in = {f.strip() for f in kin.split(';') if f.strip()}
                    if not facts_in.issubset(available_knowledge):
                        needs_fix = True

                if needs_fix:
                    prompt = build_knowledge_fix_prompt(
                        scene_id=sid,
                        project_dir=project_dir,
                        scenes_dir=scenes_dir,
                        available_knowledge=available_knowledge,
                    )

                    response = invoke(prompt, gap_model, max_tokens=512, system=system)
                    klog_file = os.path.join(knowledge_log_dir, f'{sid}.json')
                    with open(klog_file, 'w') as f:
                        json.dump(response, f)

                    text = extract_text(response)
                    rows = csv_block_to_rows(text)
                    if rows:
                        row = rows[0]
                        updates = {k: v for k, v in row.items() if k != 'id' and v.strip()}
                        if updates:
                            update_scene(sid, ref_dir, updates)
                            fixed += 1
                            new_kout = updates.get('knowledge_out', kout)
                            if new_kout:
                                for fact in new_kout.split(';'):
                                    fact = fact.strip()
                                    if fact:
                                        available_knowledge.add(fact)
                            continue

                if kout:
                    for fact in kout.split(';'):
                        fact = fact.strip()
                        if fact:
                            available_knowledge.add(fact)

            log(f'  Fixed {fixed} scenes')
            update_pr_task('Fix knowledge chain', project_dir, pr_number)

        # Commit gap-fill results
        commit_and_push(project_dir, 'Elaborate: gap-fill pass')

    # ========================================================================
    # Validate (always runs)
    # ========================================================================
    log('Running validation...')
    report = validate_structure(ref_dir)
    validate_passed = report['passed']
    validate_failures = len(report['failures'])
    initial_gaps = total_gaps

    if validate_passed:
        log('Validation passed — all gaps filled.')
    else:
        log(f'Validation: {validate_failures} issue(s) remaining (started with {initial_gaps} field gaps)')
        for f in report['failures']:
            sev = f.get('severity', 'blocking')
            scene = f.get('scene_id', '')
            prefix = f'  [{sev}]'
            if scene:
                prefix += f' {scene}:'
            log(f'{prefix} {f["message"]}')
        log('')
        log('Run gap-fill again to continue filling remaining gaps.')

    update_pr_task('Validate', project_dir, pr_number if 'pr_number' in dir() else '')

    # Save validation report
    from datetime import datetime
    validate_dir = os.path.join(project_dir, 'working', 'validation')
    os.makedirs(validate_dir, exist_ok=True)
    validate_file = os.path.join(validate_dir, f'validate-{datetime.now().strftime("%Y%m%d-%H%M%S")}.md')

    with open(validate_file, 'w') as f:
        f.write('# Validation Report: gap-fill\n\n')
        f.write(f'**Passed:** {validate_passed}\n')
        f.write(f'**Checks:** {len(report["checks"])}\n')
        f.write(f'**Failures:** {validate_failures}\n\n')
        if report['failures']:
            f.write('## Failures\n\n')
            for fail in report['failures']:
                sev = fail.get('severity', 'blocking')
                scene = fail.get('scene_id', '')
                msg = fail['message']
                if scene:
                    f.write(f'- **[{sev}]** {scene}: {msg}\n')
                else:
                    f.write(f'- **[{sev}]** {msg}\n')

    commit_and_push(project_dir, 'Elaborate: gap-fill validation report')

    run_review_phase('elaboration', project_dir)

    log('')
    log('============================================')
    log('Gap-fill complete.')
    if validate_passed:
        log('Validation: PASSED')
    else:
        log(f'Validation: {validate_failures} issue(s) remaining — run again to continue')
    log('============================================')

    print_summary(project_dir, 'elaborate-gap-fill', session_start=session_start)


# ============================================================================
# Main stage execution (spine/architecture/map/briefs)
# ============================================================================

def _run_main_stage(stage: str, project_dir: str, ref_dir: str,
                    dry_run: bool, interactive: bool, seed: str,
                    session_start: str | None = None) -> None:
    """Run a standard elaboration stage (spine/architecture/map/briefs)."""
    plugin_dir = get_plugin_dir()
    log_dir = os.path.join(project_dir, 'working', 'logs')
    os.makedirs(log_dir, exist_ok=True)

    project_title = read_yaml_field('project.title', project_dir) or 'Untitled'

    # Build prompt
    log(f'Building {stage} prompt...')

    from storyforge.prompts_elaborate import (
        build_spine_prompt, build_architecture_prompt,
        build_map_prompt, build_briefs_prompt,
        parse_stage_response, csv_block_to_rows,
    )
    from storyforge.enrich import format_registries_for_prompt, load_registry_alias_maps, normalize_fields
    from storyforge.elaborate import (
        _read_csv, _write_csv, _read_csv_as_map, _FILE_MAP, validate_structure,
    )

    registries = format_registries_for_prompt(project_dir)

    # Build shared context once for all stage API calls (prompt caching)
    stage_model = select_model('drafting')  # Opus for creative work
    system = build_shared_context(project_dir, model=stage_model)

    if stage == 'spine':
        prompt = build_spine_prompt(project_dir, plugin_dir, seed, system_context=True)
    elif stage == 'architecture':
        prompt = build_architecture_prompt(project_dir, plugin_dir, registries_text=registries,
                                           system_context=True)
    elif stage == 'map':
        prompt = build_map_prompt(project_dir, plugin_dir, registries_text=registries,
                                  system_context=True)
    elif stage == 'briefs':
        prompt = build_briefs_prompt(project_dir, plugin_dir, registries_text=registries,
                                     system_context=True)
    else:
        log(f'ERROR: Unknown stage: {stage}')
        sys.exit(1)

    if dry_run:
        print(f'===== DRY RUN: elaborate {stage} =====')
        print(prompt)
        print(f'===== END DRY RUN =====')
        return

    # Branch and PR
    create_branch(f'elaborate-{stage}', project_dir)
    ensure_branch_pushed(project_dir)

    pr_body = (
        f'## Elaboration: {stage}\n\n'
        f'**Project:** {project_title}\n'
        f'**Stage:** {stage}\n\n'
        f'### Tasks\n'
        f'- [ ] Run {stage} stage\n'
        f'- [ ] Validate\n'
        f'- [ ] Review'
    )
    pr_number = create_draft_pr(
        f'Elaborate: {project_title} — {stage}', pr_body, project_dir, 'elaboration'
    )

    # Invoke Claude
    stage_log = os.path.join(log_dir, f'elaborate-{stage}.log')

    from storyforge.api import invoke_to_file, extract_text_from_file, invoke_api
    from storyforge.costs import log_operation

    if interactive:
        log(f'Invoking interactive claude for {stage}...')
        proc = subprocess.Popen(
            ['claude', '-p', prompt,
             '--model', stage_model,
             '--dangerously-skip-permissions',
             '--output-format', 'stream-json',
             '--verbose'],
            stdout=open(stage_log, 'w'),
            stderr=subprocess.STDOUT,
        )
        proc.wait()
        claude_rc = proc.returncode
    else:
        log(f'Invoking API for {stage} (model: {stage_model})...')
        try:
            invoke_to_file(prompt, stage_model, stage_log, max_tokens=16384, system=system)
            claude_rc = 0
        except Exception as e:
            log(f'ERROR: API invocation failed: {e}')
            claude_rc = 1

    from storyforge.common import is_shutting_down
    if is_shutting_down():
        log(f'Interrupted during {stage} — partial work may be committed')
        sys.exit(130)

    if claude_rc != 0:
        log(f'ERROR: Claude invocation failed (exit code {claude_rc})')
        log(f'See: {stage_log}')
        sys.exit(1)

    # Log cost
    if os.path.isfile(stage_log):
        try:
            from storyforge.api import extract_usage, calculate_cost_from_usage
            with open(stage_log) as f:
                resp = json.load(f)
            usage = extract_usage(resp)
            cost = calculate_cost_from_usage(usage, stage_model)
            log_operation(project_dir, f'elaborate-{stage}', stage_model,
                          usage['input_tokens'], usage['output_tokens'],
                          cost, target=stage)
        except Exception:
            pass

    # Parse response
    log(f'Parsing {stage} response...')

    response = ''
    if os.path.isfile(stage_log):
        try:
            with open(stage_log, encoding='utf-8') as f:
                raw = f.read()
            # Try API JSON format
            try:
                data = json.loads(raw)
                texts = []
                for item in data.get('content', []):
                    if item.get('type') == 'text':
                        texts.append(item.get('text', ''))
                if texts:
                    response = '\n'.join(texts)
            except (json.JSONDecodeError, KeyError):
                pass

            # Try stream-json format
            if not response:
                lines = raw.strip().split('\n')
                texts = []
                for line in lines:
                    try:
                        obj = json.loads(line)
                        if obj.get('type') == 'content_block_delta':
                            texts.append(obj.get('delta', {}).get('text', ''))
                    except json.JSONDecodeError:
                        pass
                if texts:
                    response = ''.join(texts)

            # Fallback: use as plain text
            if not response:
                response = raw
        except Exception:
            pass

    if not response:
        log(f'ERROR: Could not extract response from {stage_log}')
        sys.exit(1)

    alias_maps = load_registry_alias_maps(project_dir)
    blocks = parse_stage_response(response)
    written = []

    # Apply CSV blocks
    for label, content in blocks.items():
        if label == 'scenes-csv':
            rows = csv_block_to_rows(content)
            if rows:
                path = os.path.join(ref_dir, 'scenes.csv')
                existing = _read_csv_as_map(path)
                for row in rows:
                    normalize_fields(row, alias_maps)
                    sid = row.get('id', '')
                    if not sid:
                        continue
                    if sid in existing:
                        existing[sid].update({k: v for k, v in row.items() if v})
                    else:
                        new = {c: '' for c in _FILE_MAP['scenes.csv']}
                        new.update(row)
                        existing[sid] = new
                ordered = sorted(existing.values(), key=lambda r: int(r.get('seq', 0)) if r.get('seq', '').isdigit() else 0)
                _write_csv(path, ordered, _FILE_MAP['scenes.csv'])
                written.append(f'scenes.csv ({len(rows)} rows)')

        elif label == 'intent-csv':
            rows = csv_block_to_rows(content)
            if rows:
                path = os.path.join(ref_dir, 'scene-intent.csv')
                existing = _read_csv_as_map(path)
                for row in rows:
                    normalize_fields(row, alias_maps)
                    sid = row.get('id', '')
                    if not sid:
                        continue
                    if sid in existing:
                        existing[sid].update({k: v for k, v in row.items() if v})
                    else:
                        new = {c: '' for c in _FILE_MAP['scene-intent.csv']}
                        new.update(row)
                        existing[sid] = new
                ordered = sorted(existing.values(), key=lambda r: r.get('id', ''))
                _write_csv(path, ordered, _FILE_MAP['scene-intent.csv'])
                written.append(f'scene-intent.csv ({len(rows)} rows)')

        elif label == 'briefs-csv':
            rows = csv_block_to_rows(content)
            if rows:
                path = os.path.join(ref_dir, 'scene-briefs.csv')
                existing = _read_csv_as_map(path)
                for row in rows:
                    normalize_fields(row, alias_maps)
                    sid = row.get('id', '')
                    if not sid:
                        continue
                    if sid in existing:
                        existing[sid].update({k: v for k, v in row.items() if v})
                    else:
                        new = {c: '' for c in _FILE_MAP['scene-briefs.csv']}
                        new.update(row)
                        existing[sid] = new
                ordered = sorted(existing.values(), key=lambda r: r.get('id', ''))
                _write_csv(path, ordered, _FILE_MAP['scene-briefs.csv'])
                written.append(f'scene-briefs.csv ({len(rows)} rows)')

        elif label == 'scenes-csv-update':
            rows = csv_block_to_rows(content)
            if rows:
                path = os.path.join(ref_dir, 'scenes.csv')
                existing = _read_csv_as_map(path)
                for row in rows:
                    sid = row.get('id', '')
                    if sid in existing:
                        existing[sid].update({k: v for k, v in row.items() if v and k != 'id'})
                ordered = sorted(existing.values(), key=lambda r: int(r.get('seq', 0)) if r.get('seq', '').isdigit() else 0)
                _write_csv(path, ordered, _FILE_MAP['scenes.csv'])
                written.append(f'scenes.csv status updates ({len(rows)} rows)')

        elif label in ('story-architecture', 'character-bible', 'world-bible', 'voice-guide'):
            filename = label + '.md'
            path = os.path.join(ref_dir, filename)
            with open(path, 'w', encoding='utf-8') as f:
                f.write(content + '\n')
            written.append(filename)

    if written:
        log(f'  Updated: {", ".join(written)}')
    else:
        log('  WARNING: No structured output blocks found in response')

    # ========================================================================
    # Validate
    # ========================================================================
    log('Running validation...')
    report = validate_structure(ref_dir)
    validate_passed = report['passed']
    validate_failures = len(report['failures'])

    if validate_passed:
        log('Validation passed')
    else:
        log(f'Validation found {validate_failures} issue(s):')
        for fail in report['failures']:
            sev = fail.get('severity', 'blocking')
            scene = fail.get('scene_id', '')
            prefix = f'  [{sev}]'
            if scene:
                prefix += f' {scene}:'
            log(f'{prefix} {fail["message"]}')

    # Save validation report
    from datetime import datetime
    validate_dir = os.path.join(project_dir, 'working', 'validation')
    os.makedirs(validate_dir, exist_ok=True)
    validate_file = os.path.join(validate_dir, f'validate-{datetime.now().strftime("%Y%m%d-%H%M%S")}.md')

    with open(validate_file, 'w') as f:
        f.write(f'# Validation Report: {stage}\n\n')
        f.write(f'**Passed:** {validate_passed}\n')
        f.write(f'**Checks:** {len(report["checks"])}\n')
        f.write(f'**Failures:** {validate_failures}\n\n')
        if report['failures']:
            f.write('## Failures\n\n')
            for fail in report['failures']:
                sev = fail.get('severity', 'blocking')
                scene = fail.get('scene_id', '')
                msg = fail['message']
                if scene:
                    f.write(f'- **[{sev}]** {scene}: {msg}\n')
                else:
                    f.write(f'- **[{sev}]** {msg}\n')

    # ========================================================================
    # Commit and update PR
    # ========================================================================
    log(f'Committing {stage} results...')
    commit_and_push(project_dir, f'Elaborate: {stage} stage')

    update_pr_task(f'Run {stage} stage', project_dir, pr_number)
    update_pr_task('Validate', project_dir, pr_number)

    # ========================================================================
    # Update phase in storyforge.yaml
    # ========================================================================
    next_phase_map = {
        'spine': 'architecture',
        'architecture': 'scene-map',
        'map': 'briefs',
        'briefs': 'drafting',
    }
    next_phase = next_phase_map.get(stage)

    if validate_passed and next_phase:
        current_phase = read_yaml_field('phase', project_dir)
        if current_phase in (stage, 'spine', 'development'):
            yaml_path = os.path.join(project_dir, 'storyforge.yaml')
            if os.path.isfile(yaml_path):
                with open(yaml_path) as f:
                    content = f.read()
                content = re.sub(r'^phase:.*', f'phase: {next_phase}', content, flags=re.MULTILINE)
                with open(yaml_path, 'w') as f:
                    f.write(content)
                commit_and_push(project_dir, f'Elaborate: advance phase to {next_phase}',
                                ['storyforge.yaml'])
                log(f'Phase advanced to: {next_phase}')

    # ========================================================================
    # Review phase
    # ========================================================================
    run_review_phase('elaboration', project_dir)

    # ========================================================================
    # Summary
    # ========================================================================
    log('')
    log('============================================')
    log(f'Elaboration {stage} complete.')
    if validate_passed:
        log('Validation: PASSED')
    else:
        log(f'Validation: {validate_failures} issue(s) — review before advancing')
    log('============================================')

    print_summary(project_dir, f'elaborate-{stage}', session_start=session_start)


# ============================================================================
# Main
# ============================================================================

def main(argv=None):
    args = parse_args(argv or [])

    install_signal_handlers()

    from datetime import datetime
    session_start = datetime.now().strftime('%Y-%m-%dT%H:%M:%S')

    project_dir = detect_project_root()
    ref_dir = os.path.join(project_dir, 'reference')

    if args.stage not in VALID_STAGES:
        print(f'ERROR: Unknown stage: {args.stage} (expected: {"|".join(sorted(VALID_STAGES))})',
              file=sys.stderr)
        sys.exit(1)

    # API key required for non-interactive, non-dry-run
    if not args.dry_run and not args.interactive and not os.environ.get('ANTHROPIC_API_KEY'):
        log('ERROR: ANTHROPIC_API_KEY not set. Required for autonomous mode.')
        log('  Set it with: export ANTHROPIC_API_KEY=your-key')
        log('  Or use --interactive to run via claude -p.')
        sys.exit(1)

    # Coaching
    if args.coaching:
        os.environ['STORYFORGE_COACHING'] = args.coaching

    project_title = read_yaml_field('project.title', project_dir) or 'Untitled'
    plugin_dir = get_plugin_dir()

    log('============================================')
    log(f'Storyforge Elaborate: {args.stage}')
    log(f'Project: {project_title}')
    log('============================================')

    if args.stage == 'mice-fill':
        _run_mice_fill(project_dir, ref_dir, args.dry_run)
    elif args.stage == 'gap-fill':
        _run_gap_fill(project_dir, ref_dir, args.dry_run, session_start=session_start)
    else:
        _run_main_stage(args.stage, project_dir, ref_dir,
                        args.dry_run, args.interactive, args.seed,
                        session_start=session_start)
