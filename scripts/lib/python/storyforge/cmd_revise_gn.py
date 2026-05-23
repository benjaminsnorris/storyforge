"""storyforge revise (graphic-novel mode) — Findings-driven panel-script revision.

Revises drafted GN scenes by feeding deterministic scorer findings and
evaluator-persona findings back into the model, then producing a revised
script that targets the issues directly. Same CLI shape as novel-mode
`revise`; routed here when project.medium == 'graphic-novel'.

Usage:
    storyforge revise                          # all drafted scenes
    storyforge revise the-blank-page           # one scene
    storyforge revise --scenes a,b,c
    storyforge revise --act 2
    storyforge revise --from-seq 3
    storyforge revise --dry-run
    storyforge revise --no-findings            # polish without findings input
"""

import argparse
import json
import os
import sys

from storyforge.common import (
    detect_project_root, log, set_log_file, select_model,
    install_signal_handlers, get_medium,
)
from storyforge.csv_cli import get_field, update_field
from storyforge.scene_filter import build_scene_list, apply_scene_filter
from storyforge.script_format import count_pages, count_panels, check_brief_fidelity
from storyforge.api import (
    invoke_to_file, extract_text_from_file,
    extract_usage, calculate_cost_from_usage,
)
from storyforge.costs import log_operation
from storyforge.prompts_gn import build_revision_prompt
from storyforge import git as git_helpers


REVISABLE_STATUSES = ('drafted', 'revised')


def parse_args(argv):
    parser = argparse.ArgumentParser(
        prog='storyforge revise (gn)',
        description='Revise drafted GN panel scripts against findings.',
    )
    parser.add_argument('positional', nargs='*', default=[],
                        help='Scene ID(s) to revise')
    parser.add_argument('--dry-run', action='store_true',
                        help='Build prompts without invoking the API')
    parser.add_argument('--scenes', type=str, default=None,
                        help='Comma-separated scene IDs')
    parser.add_argument('--act', '--part', type=str, default=None,
                        help='Revise all scenes in act/part N')
    parser.add_argument('--from-seq', type=str, default=None,
                        help='Start from sequence number (N or N-M range)')
    parser.add_argument('--no-findings', action='store_true',
                        help='Polish without findings input (blind polish)')
    parser.add_argument('--no-branch', action='store_true',
                        help='Skip branch + PR creation (useful for tests)')
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
    char_text = open(chars_path, encoding='utf-8').read() if os.path.isfile(chars_path) else ''
    world_text = open(world_path, encoding='utf-8').read() if os.path.isfile(world_path) else ''
    return char_text, world_text


def _build_voice_text(project_dir):
    voice_path = os.path.join(project_dir, 'reference', 'voice-profile.csv')
    if os.path.isfile(voice_path):
        return open(voice_path, encoding='utf-8').read()
    return ''


def _load_findings_file(path, kind):
    """Load a findings file at `path`. Returns:

      - []  when the file is absent (no findings yet — legitimate)
      - None when the file exists but is corrupt or unreadable (real error)
      - list of finding dicts otherwise
    """
    if not os.path.isfile(path):
        return []
    try:
        with open(path, encoding='utf-8') as f:
            data = json.load(f)
    except (json.JSONDecodeError, OSError) as e:
        log(f'WARNING: could not read {kind} findings at {path}: {e}')
        return None
    raw = data.get('findings', []) or []
    # Drop any non-dict entries (e.g. nulls) so downstream prompt-building
    # can't crash with AttributeError on f.get(...).
    findings = [f for f in raw if isinstance(f, dict)]
    if len(findings) != len(raw):
        log(f'WARNING: dropped {len(raw) - len(findings)} malformed '
            f'{kind} finding(s) at {path}')
    return findings


def _load_score_findings(project_dir, scene_id):
    """Load deterministic score findings for one scene.

    Returns [] when no file exists, None on parse failure, else a list.
    """
    path = os.path.join(project_dir, 'working', 'scores', 'latest', f'{scene_id}.json')
    return _load_findings_file(path, 'score')


def _load_eval_findings(project_dir, scene_id):
    """Load persona eval findings for one scene.

    Returns [] when no file exists, None on parse failure, else a list.
    """
    path = os.path.join(project_dir, 'working', 'evaluations', 'latest', f'{scene_id}.json')
    return _load_findings_file(path, 'eval')


def _resolve_target_scenes(args, metadata_csv):
    """Resolve which scenes to revise. Single-positional matches cmd_write_gn;
    two positionals become a range; --scenes / --act / --from-seq delegate to
    apply_scene_filter so unknown IDs are flagged loudly.
    """
    all_ids = build_scene_list(metadata_csv)

    if args.positional:
        if len(args.positional) == 1:
            return [args.positional[0]]
        if len(args.positional) == 2:
            return apply_scene_filter(
                metadata_csv, all_ids, 'range',
                args.positional[0], args.positional[1],
            )
        log('ERROR: Too many positional arguments. '
            'Provide one scene ID or two for a range.')
        sys.exit(1)
    if args.scenes:
        return apply_scene_filter(metadata_csv, all_ids, 'scenes', args.scenes, None)
    if args.act:
        return apply_scene_filter(metadata_csv, all_ids, 'act', args.act, None)
    if args.from_seq:
        return apply_scene_filter(
            metadata_csv, all_ids, 'from_seq', args.from_seq, None,
        )
    return list(all_ids)


def _revise_one_scene(scene_id, project_dir, model, args):
    """Revise a single scene.

    Side effects (only on the success path, all gated past the dry-run return):
      - overwrites scenes/{scene_id}.md with the revised script
      - writes the API response JSON to working/logs/revise-gn/{scene_id}.json
      - appends a row to the cost ledger via log_operation

    Returns (scene_id, result_dict) where result_dict has exactly one of:
      - {'skipped': True, 'reason': str} — scene intentionally not processed
      - {'error': str}                   — recoverable per-scene failure
      - {'dry_run': True, 'prompt': str, 'score_findings': int, 'eval_findings': int}
      - {'revised': True, 'pages': int, 'panels': int, ...} — success
    """
    ref_dir = os.path.join(project_dir, 'reference')
    scenes_csv = os.path.join(ref_dir, 'scenes.csv')

    status = get_field(scenes_csv, scene_id, 'status') or ''
    if status not in REVISABLE_STATUSES:
        return scene_id, {
            'skipped': True,
            'reason': f'status is "{status}" (not in {REVISABLE_STATUSES})',
        }

    scene_path = os.path.join(project_dir, 'scenes', f'{scene_id}.md')
    if not os.path.isfile(scene_path):
        return scene_id, {'error': 'scene file not found'}

    scene_row = _row_to_dict(scenes_csv, scene_id)
    intent_row = _row_to_dict(os.path.join(ref_dir, 'scene-intent.csv'), scene_id)
    brief_row = _row_to_dict(os.path.join(ref_dir, 'scene-briefs.csv'), scene_id)

    if not scene_row:
        return scene_id, {'error': 'missing row in scenes.csv'}
    if not brief_row:
        return scene_id, {'error': 'missing brief row in scene-briefs.csv'}

    with open(scene_path, encoding='utf-8') as f:
        script_text = f.read()

    if args.no_findings:
        score_findings = []
        eval_findings = []
    else:
        score_findings = _load_score_findings(project_dir, scene_id)
        eval_findings = _load_eval_findings(project_dir, scene_id)
        # _load_*_findings returns None when the file exists but is corrupt.
        # Surface that as a real error instead of treating it like "no findings."
        if score_findings is None or eval_findings is None:
            broken = []
            if score_findings is None:
                broken.append('score')
            if eval_findings is None:
                broken.append('eval')
            return scene_id, {
                'error': (
                    f'corrupt {"/".join(broken)} findings file (see WARNING above) — '
                    f're-run scoring/evaluation or delete the file to clear it'
                ),
            }
        if not score_findings and not eval_findings:
            return scene_id, {
                'skipped': True,
                'reason': (
                    'no findings found — run `storyforge score` and/or '
                    '`storyforge evaluate` first, or pass --no-findings to '
                    'polish blind'
                ),
            }

    char_visuals, loc_visuals = _build_visual_refs(project_dir)
    voice_text = _build_voice_text(project_dir)

    prompt = build_revision_prompt(
        scene_id=scene_id,
        scene_row=scene_row,
        intent_row=intent_row,
        brief_row=brief_row,
        script_text=script_text,
        character_visuals=char_visuals,
        location_visuals=loc_visuals,
        voice_profile_text=voice_text,
        score_findings=score_findings,
        eval_findings=eval_findings,
    )

    if args.dry_run:
        return scene_id, {
            'dry_run': True,
            'prompt': prompt,
            'score_findings': len(score_findings),
            'eval_findings': len(eval_findings),
        }

    log_dir = os.path.join(project_dir, 'working', 'logs', 'revise-gn')
    os.makedirs(log_dir, exist_ok=True)
    log_file = os.path.join(log_dir, f'{scene_id}.json')

    try:
        invoke_to_file(prompt, model, log_file, max_tokens=8192)
    except Exception as e:
        return scene_id, {'error': f'API call failed: {e}'}

    revised_text = extract_text_from_file(log_file)
    if not revised_text:
        return scene_id, {'error': 'empty API response'}

    with open(scene_path, 'w', encoding='utf-8') as f:
        f.write(revised_text)

    pages = count_pages(revised_text)
    panels = count_panels(revised_text)
    failures = check_brief_fidelity(brief_row, revised_text)

    # Cost tracking (best-effort)
    try:
        with open(log_file, encoding='utf-8') as f:
            resp = json.load(f)
        usage = extract_usage(resp)
        cost = calculate_cost_from_usage(usage, model)
        log_operation(
            project_dir, 'revise-gn', model,
            usage['input_tokens'], usage['output_tokens'], cost,
            target=scene_id,
            cache_read=usage.get('cache_read', 0),
            cache_create=usage.get('cache_create', 0),
        )
    except Exception:
        pass

    return scene_id, {
        'revised': True,
        'pages': pages,
        'panels': panels,
        'fidelity_failures': len(failures),
        'score_findings': len(score_findings),
        'eval_findings': len(eval_findings),
    }


def _build_pr_body(scene_ids):
    """Build a PR body with a per-scene task list."""
    lines = ['## Revision pass — graphic-novel mode', '']
    lines.append('Findings-driven revision: each scene gets one polish pass '
                 'using deterministic scorer + evaluator persona findings.')
    lines.append('')
    lines.append('## Tasks')
    for sid in scene_ids:
        lines.append(f'- [ ] Revise: {sid}')
    lines.append('')
    return '\n'.join(lines)


def main(argv=None):
    args = parse_args(argv if argv is not None else sys.argv[1:])
    install_signal_handlers()

    project_dir = detect_project_root()

    medium = get_medium(project_dir)
    if medium != 'graphic-novel':
        log(f'ERROR: This command is only for graphic-novel projects '
            f'(project.medium = "{medium}").')
        log('For novel projects, use the standard `storyforge revise` command.')
        sys.exit(1)

    log(f'Project root: {project_dir}')
    log('Medium: graphic-novel — using GN revision pass')

    log_dir = os.path.join(project_dir, 'working', 'logs')
    os.makedirs(log_dir, exist_ok=True)
    set_log_file(os.path.join(log_dir, 'revise-gn-log.txt'))

    metadata_csv = os.path.join(project_dir, 'reference', 'scenes.csv')

    candidate_ids = _resolve_target_scenes(args, metadata_csv)

    # Filter to scenes that actually have a draft on disk and a revisable status
    scenes_dir = os.path.join(project_dir, 'scenes')
    scene_ids = []
    for sid in candidate_ids:
        status = get_field(metadata_csv, sid, 'status') or ''
        if status not in REVISABLE_STATUSES:
            log(f'  SKIP {sid}: status is "{status}" (not in {REVISABLE_STATUSES})')
            continue
        if not os.path.isfile(os.path.join(scenes_dir, f'{sid}.md')):
            log(f'  SKIP {sid}: scene file not found')
            continue
        scene_ids.append(sid)

    if not scene_ids:
        log('ERROR: No revisable scenes found for the selected scope.')
        sys.exit(1)

    log(f'Scenes to revise: {len(scene_ids)}')

    if args.dry_run:
        log('DRY RUN — no API calls will be made, no files will be written')
        for sid in scene_ids:
            title = get_field(metadata_csv, sid, 'title') or sid
            log(f'  - {sid} ({title})')

    model = select_model('revision') if not args.dry_run else 'dry-run'
    log(f'Model: {model}')

    # Branch + draft PR (unless --no-branch or dry-run). Refuse to proceed if
    # branch creation fails — committing revisions to the current branch
    # (possibly main) would violate the project's git policy.
    pr_number = ''
    if not args.dry_run and not args.no_branch:
        branch = git_helpers.create_branch('revise-gn', project_dir)
        if not branch:
            log('ERROR: Could not create or resume a feature branch. '
                'Refusing to commit revisions to the current branch. '
                'Check `git status` for a dirty working tree, or pass '
                '--no-branch to run without git operations.')
            sys.exit(1)
        git_helpers.ensure_branch_pushed(project_dir, branch)
        pr_number = git_helpers.create_draft_pr(
            title=f'Revise (GN): {len(scene_ids)} scene(s)',
            body=_build_pr_body(scene_ids),
            project_dir=project_dir,
            work_type='revision',
        )

    # Revise each scene sequentially. Sequential is simpler than parallel for
    # the first version and keeps commit ordering deterministic — the LLM call
    # is the cost driver, not loop overhead.
    revised_count = 0
    for sid in scene_ids:
        log(f'  Revising {sid}...')
        _, result = _revise_one_scene(sid, project_dir, model, args)

        if args.dry_run and result.get('dry_run'):
            print(f'===== DRY RUN: {sid} =====')
            print(f'  score findings: {result["score_findings"]}')
            print(f'  eval findings: {result["eval_findings"]}')
            print('--- prompt ---')
            print(result['prompt'])
            print(f'===== END DRY RUN: {sid} =====')
            print()
            continue

        if result.get('skipped'):
            log(f'  SKIP {sid}: {result["reason"]}')
            continue
        if result.get('error'):
            log(f'  ERROR {sid}: {result["error"]}')
            continue

        update_field(metadata_csv, sid, 'page_count', str(result['pages']))
        update_field(metadata_csv, sid, 'panel_count', str(result['panels']))
        update_field(metadata_csv, sid, 'status', 'revised')

        fidelity_note = (
            f', {result["fidelity_failures"]} fidelity warning(s)'
            if result['fidelity_failures'] else ''
        )
        log(
            f'  {sid}: revised {result["pages"]} page(s), '
            f'{result["panels"]} panel(s) '
            f'(score: {result["score_findings"]}, eval: {result["eval_findings"]} '
            f'findings){fidelity_note}'
        )

        if not args.no_branch:
            git_helpers.commit_and_push(
                project_dir,
                f'Revision: {sid} (GN)',
                paths=[
                    os.path.join('scenes', f'{sid}.md'),
                    os.path.join('reference', 'scenes.csv'),
                ],
            )
            if pr_number:
                git_helpers.update_pr_task(f'Revise: {sid}', project_dir, pr_number)

        revised_count += 1

    if not args.dry_run:
        log(f'Done. {revised_count}/{len(scene_ids)} scene(s) revised.')


if __name__ == '__main__':
    main()
