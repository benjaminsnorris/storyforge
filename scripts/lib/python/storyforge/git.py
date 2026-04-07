"""Git branch, PR, and review workflow — replaces git ops from common.sh.

All functions take project_dir explicitly rather than relying on globals.
"""

import os
import re
import subprocess
import sys
from datetime import datetime

from storyforge.common import log, read_yaml_field, get_coaching_level, select_model


# ============================================================================
# Git helpers
# ============================================================================

def _git(project_dir: str, *args: str, check: bool = True) -> subprocess.CompletedProcess:
    """Run a git command in project_dir."""
    return subprocess.run(
        ['git', '-C', project_dir, *args],
        capture_output=True, text=True, check=check,
    )


def has_gh() -> bool:
    """Check if the gh CLI is available."""
    try:
        subprocess.run(['gh', '--version'], capture_output=True, check=True)
        return True
    except (FileNotFoundError, subprocess.CalledProcessError):
        return False


def current_branch(project_dir: str) -> str:
    r = _git(project_dir, 'rev-parse', '--abbrev-ref', 'HEAD', check=False)
    return r.stdout.strip() if r.returncode == 0 else ''


def _is_main_branch(branch: str) -> bool:
    """Check if a branch name is a main/default branch."""
    return branch in ('main', 'master')


def create_branch(command_name: str, project_dir: str) -> str:
    """Create a storyforge feature branch. Returns branch name.

    If already on any non-main branch, treats as resume.
    """
    branch = current_branch(project_dir)
    if branch and not _is_main_branch(branch):
        log(f'Resuming on branch: {branch}')
        return branch

    ts = datetime.now().strftime('%Y%m%d-%H%M')
    new_branch = f'storyforge/{command_name}-{ts}'
    r = _git(project_dir, 'checkout', '-b', new_branch, check=False)
    if r.returncode != 0:
        log(f'ERROR: Failed to create branch {new_branch}')
        return ''

    log(f'Created branch: {new_branch}')
    return new_branch


def ensure_on_branch(command_name: str, project_dir: str) -> str:
    """Ensure we are not on main before making changes.

    If on main, creates a new storyforge feature branch.
    If on any other branch, returns it unchanged.
    """
    branch = current_branch(project_dir)
    if branch and not _is_main_branch(branch):
        return branch
    return create_branch(command_name, project_dir)


def ensure_branch_pushed(project_dir: str, branch: str | None = None) -> bool:
    """Push branch with -u. Creates initial commit if needed."""
    if branch is None:
        branch = current_branch(project_dir)
    if not branch:
        log('WARNING: No branch to push')
        return False

    # Check if branch has commits ahead of base
    base = _git(project_dir, 'config', 'init.defaultBranch', check=False).stdout.strip() or 'main'
    r = _git(project_dir, 'rev-list', '--count', f'{base}..HEAD', check=False)
    ahead = int(r.stdout.strip()) if r.returncode == 0 else 0

    if ahead == 0:
        committed = False
        # Try staging pending changes
        r = _git(project_dir, 'diff', '--quiet', check=False)
        if r.returncode != 0:
            _git(project_dir, 'add', 'storyforge.yaml', check=False)
            _git(project_dir, 'add', 'CLAUDE.md', check=False)
            short = branch.removeprefix('storyforge/')
            r = _git(project_dir, 'commit', '-m', f'Start {short}', check=False)
            committed = r.returncode == 0

        if not committed:
            short = branch.removeprefix('storyforge/')
            r = _git(project_dir, 'commit', '--allow-empty', '-m', f'Start {short}', check=False)
            committed = r.returncode == 0

        if committed:
            log(f'Initial commit on {branch}')

    r = _git(project_dir, 'push', '-u', 'origin', branch, check=False)
    if r.returncode != 0:
        log(f'WARNING: Could not push branch {branch} to origin')
        return False
    return True


# ============================================================================
# Labels
# ============================================================================

_LABELS = {
    # Status
    'in-progress':    ('fef2c0', 'Autonomous work is underway'),
    'reviewing':      ('5319e7', 'Pipeline review in progress'),
    'ready-to-merge': ('0e8a16', 'Review complete — author may merge'),
    # Work type
    'drafting':       ('1d76db', 'Scene drafting session'),
    'evaluation':     ('d93f0b', 'Multi-agent evaluation panel'),
    'revision':       ('c5def5', 'Revision pass execution'),
    'assembly':       ('bfdadc', 'Manuscript assembly and production'),
    'scoring':        ('fbca04', 'Principled craft scoring'),
    'enrichment':     ('d4c5f9', 'Metadata enrichment'),
    'elaboration':    ('0075ca', 'Elaboration pipeline stage'),
    'extraction':     ('e99695', 'Reverse elaboration — prose extraction'),
    'polish':         ('c2e0c6', 'Prose polish pass'),
}


def ensure_all_labels(project_dir: str) -> None:
    if not has_gh():
        return
    for name, (color, desc) in _LABELS.items():
        subprocess.run(
            ['gh', 'label', 'create', name, '--color', color, '--description', desc],
            capture_output=True, cwd=project_dir,
        )


# ============================================================================
# Pull requests
# ============================================================================

def create_draft_pr(title: str, body: str, project_dir: str,
                    work_type: str = '') -> str:
    """Create a draft PR. Returns PR number or empty string."""
    if not has_gh():
        log('WARNING: gh CLI not available — skipping PR creation')
        return ''

    ensure_all_labels(project_dir)

    # Check for existing open PR
    r = subprocess.run(
        ['gh', 'pr', 'view', '--json', 'number,state', '--jq', 'select(.state == "OPEN") | .number'],
        capture_output=True, text=True, cwd=project_dir,
    )
    if r.returncode == 0 and r.stdout.strip():
        pr_num = r.stdout.strip()
        log(f'Found existing PR #{pr_num}')
        return pr_num

    cmd = ['gh', 'pr', 'create', '--draft', '--title', title, '--body', body,
           '--label', 'in-progress']
    if work_type:
        cmd.extend(['--label', work_type])

    r = subprocess.run(cmd, capture_output=True, text=True, cwd=project_dir)
    if r.returncode != 0:
        log('WARNING: Failed to create draft PR — continuing without PR')
        return ''

    pr_url = r.stdout.strip()
    m = re.search(r'(\d+)$', pr_url)
    pr_num = m.group(1) if m else ''

    if pr_num:
        log(f'Created draft PR #{pr_num}: {title}')
    else:
        log(f'WARNING: PR created but could not parse number from: {pr_url}')

    return pr_num


def update_pr_task(task_text: str, project_dir: str, pr_number: str = '') -> None:
    """Check off a task in the PR body."""
    if not has_gh() or not pr_number:
        return

    r = subprocess.run(
        ['gh', 'pr', 'view', pr_number, '--json', 'body', '--jq', '.body'],
        capture_output=True, text=True, cwd=project_dir,
    )
    if r.returncode != 0:
        return

    body = r.stdout
    escaped = re.escape(task_text)
    new_body = re.sub(rf'- \[ \] {escaped}', f'- [x] {task_text}', body)

    subprocess.run(
        ['gh', 'pr', 'edit', pr_number, '--body', new_body],
        capture_output=True, cwd=project_dir,
    )


# ============================================================================
# Commit helpers
# ============================================================================

def commit_and_push(project_dir: str, message: str, paths: list[str] | None = None) -> bool:
    """Stage paths (or all), commit, and push. Returns True on success."""
    if paths:
        for p in paths:
            _git(project_dir, 'add', p, check=False)
    else:
        _git(project_dir, 'add', '-A', check=False)

    r = _git(project_dir, 'commit', '-m', message, check=False)
    if r.returncode != 0:
        return False

    _git(project_dir, 'push', check=False)
    return True


def commit_partial_work(project_dir: str) -> None:
    """Commit any partial work during interrupted shutdown."""
    if not os.path.isdir(os.path.join(project_dir, '.git')):
        return

    # Check for staged or unstaged changes in key dirs
    dirs_to_check = [
        'working/evaluations/', 'working/logs/', 'working/scores/',
        'working/costs/', 'working/timeline/', 'scenes/', 'reference/',
    ]
    has_changes = False
    r = _git(project_dir, 'diff', '--cached', '--quiet', check=False)
    if r.returncode != 0:
        has_changes = True
    else:
        for d in dirs_to_check:
            r = _git(project_dir, 'status', '--porcelain', d, check=False)
            if r.stdout.strip():
                has_changes = True
                break

    if has_changes:
        log('Committing partial work before exit...')
        for d in dirs_to_check:
            _git(project_dir, 'add', d, check=False)
        _git(project_dir, 'commit', '-m', 'Interrupted: partial work saved', check=False)
        _git(project_dir, 'push', check=False)
        log('Partial work committed.')


# ============================================================================
# Review phase
# ============================================================================

def run_review_phase(review_type: str, project_dir: str, pr_number: str = '') -> None:
    """Run the review phase at the end of an autonomous process.

    Sequence: label swap -> Claude review -> cleanup -> recommend -> label swap
    """
    from storyforge.common import (
        get_current_cycle, update_cycle_field, get_cycle_plan_file,
    )
    from storyforge.api import invoke_api, extract_response

    ts = datetime.now().strftime('%Y%m%d-%H%M%S')
    review_file = os.path.join(project_dir, 'working', 'reviews', f'pipeline-review-{ts}.md')
    review_log = os.path.join(project_dir, 'working', 'logs', f'review-{ts}.log')
    os.makedirs(os.path.dirname(review_file), exist_ok=True)
    os.makedirs(os.path.dirname(review_log), exist_ok=True)

    cycle_id = get_current_cycle(project_dir)
    log(f'Starting review phase ({review_type})...')

    # Step 1: PR label swap
    if has_gh() and pr_number:
        log(f'Updating PR #{pr_number}: in-progress → reviewing')
        subprocess.run(
            ['gh', 'pr', 'edit', pr_number, '--remove-label', 'in-progress', '--add-label', 'reviewing'],
            capture_output=True, cwd=project_dir,
        )
        subprocess.run(['gh', 'pr', 'ready', pr_number], capture_output=True, cwd=project_dir)

    # Step 2: Build review prompt
    diff_stat = _git(project_dir, 'diff', 'origin/main...HEAD', '--stat', check=False).stdout or '(no diff available)'
    changed_files = _git(project_dir, 'diff', 'origin/main...HEAD', '--name-only', check=False).stdout or ''

    title = read_yaml_field('project.title', project_dir) or read_yaml_field('title', project_dir) or 'Unknown'
    genre = read_yaml_field('project.genre', project_dir) or read_yaml_field('genre', project_dir) or ''

    criteria_map = {
        'drafting': """   - Voice consistency across drafted scenes
   - Continuity with existing scenes and reference materials
   - Scene function clarity — does each scene earn its place?
   - Word count vs. targets""",
        'evaluation': """   - Completeness — did all evaluators produce substantive reports?
   - Coverage — are all key aspects of the manuscript addressed?
   - Synthesis quality — does the synthesis accurately reflect individual reports?
   - Actionability — are findings specific enough to act on?""",
        'revision': """   - Were revision targets met (word count reductions, instance counts, etc.)?
   - Was voice preserved during revision?
   - Were continuity and reference materials updated?
   - Are there new issues introduced by the revision?""",
        'assembly': """   - Chapter structure — do chapters have logical boundaries?
   - Scene breaks — are they consistent and appropriate?
   - Front/back matter completeness
   - Metadata accuracy (title, author, copyright)""",
    }
    review_criteria = criteria_map.get(review_type, """   - Overall quality of the changes
   - Consistency with project conventions
   - Any issues or concerns""")

    # Inline file contents for API mode
    inline_files = ''
    for fname in changed_files.strip().splitlines():
        fname = fname.strip()
        if not fname:
            continue
        fpath = os.path.join(project_dir, fname)
        if os.path.isfile(fpath):
            fsize = os.path.getsize(fpath)
            if fsize < 51200:
                with open(fpath) as f:
                    content = f.read()
                inline_files += f'\n=== FILE: {fname} ===\n{content}\n=== END FILE ===\n'
            else:
                inline_files += f'\n=== FILE: {fname} ===\n({fsize} bytes — too large to inline, skipped)\n=== END FILE ===\n'

    genre_note = f' ({genre})' if genre else ''
    review_prompt = f"""You are performing a pipeline review for "{title}"{genre_note}. This is a quality check at the end of a {review_type} session.

## Changed Files

{changed_files}

## Diff Summary

{diff_stat}

## File Contents

{inline_files}

## Instructions

1. Review the file contents provided above.
2. Based on the review type ({review_type}), assess:
{review_criteria}

3. Write a structured review with these sections:
   - **Summary**: 2-3 sentences on what was done
   - **Quality Signals**: What looks good
   - **Concerns**: Any issues found (with specifics — cite files and details)
   - **Recommendation**: Ready to merge, needs attention, or needs rework

4. After your main review, add one final section:

## Fixable Items

List specific items that can be fixed automatically without author input.
Format each as a checkbox:
- [ ] {{specific file}}: {{what needs to change}}

If nothing is auto-fixable, write: "None — all concerns require author judgment."
"""

    # Run review
    model = select_model('review')
    log(f'Invoking claude for review (model: {model})...')

    response = invoke_api(review_prompt, model, max_tokens=16384)
    if response:
        os.makedirs(os.path.dirname(review_file), exist_ok=True)
        with open(review_file, 'w') as f:
            f.write(response)
        log(f'Review saved to {os.path.basename(review_file)}')

        # Save log
        with open(review_log, 'w') as f:
            f.write(response)

    # Commit review
    commit_and_push(project_dir, f'Review: pipeline review ({review_type})',
                    ['working/reviews/', 'working/logs/', 'working/pipeline.csv'])

    if cycle_id and os.path.isfile(review_file):
        update_cycle_field(project_dir, cycle_id, 'review', os.path.basename(review_file))

    # Step 3: Cleanup + recommend (full coaching only)
    coaching = get_coaching_level(project_dir)
    if coaching == 'full' and os.path.isfile(review_file):
        _run_cleanup_if_needed(review_file, review_type, project_dir)
        _run_recommend_step(review_type, project_dir, cycle_id)
    elif cycle_id:
        update_cycle_field(project_dir, cycle_id, 'status', 'complete')

    # Step 4: PR label swap
    if has_gh() and pr_number:
        # Post comment
        if os.path.isfile(review_file):
            with open(review_file) as f:
                comment = f.read()
            subprocess.run(
                ['gh', 'pr', 'comment', pr_number, '--body', comment],
                capture_output=True, cwd=project_dir,
            )

        subprocess.run(
            ['gh', 'pr', 'edit', pr_number, '--remove-label', 'reviewing', '--add-label', 'ready-to-merge'],
            capture_output=True, cwd=project_dir,
        )
        log(f'PR #{pr_number} marked ready-to-merge')

    update_pr_task('Review', project_dir, pr_number)

    if os.path.isfile(review_file):
        log(f'Review saved: {review_file}')
    else:
        log('WARNING: Review file was not created')


def _run_cleanup_if_needed(review_file: str, review_type: str, project_dir: str) -> None:
    """Run a single cleanup pass if fixable items exist."""
    with open(review_file) as f:
        content = f.read()

    # Extract fixable items section
    m = re.search(r'## Fixable Items\n(.*?)(?=\n## |\Z)', content, re.DOTALL)
    if not m:
        return
    section = m.group(1).strip()
    if not section or section.lower().startswith('none') or '- [ ]' not in section:
        return

    item_count = section.count('- [ ]')
    log(f'Review found {item_count} fixable item(s). Running cleanup...')

    from storyforge.api import invoke_api
    cleanup_prompt = f"""You are performing cleanup pass 1 on a Storyforge project after a {review_type} review.

Read the review report below and fix ONLY items in the "Fixable Items" section:

{content}

Rules:
- Only fix items listed in "Fixable Items" — nothing else
- Do not make subjective changes, creative edits, or prose improvements
- Do not modify scene prose content
- If an item is ambiguous or requires author judgment, skip it
"""
    model = select_model('review')
    response = invoke_api(cleanup_prompt, model, max_tokens=16384)
    if response:
        log('Cleanup complete.')


def _run_recommend_step(review_type: str, project_dir: str, cycle_id: int) -> None:
    """Write next-step recommendations."""
    from storyforge.common import update_cycle_field
    from storyforge.api import invoke_api

    title = read_yaml_field('project.title', project_dir) or 'Unknown'
    today = datetime.now().strftime('%Y-%m-%d')

    recommend_file = 'working/recommendations.md'
    if cycle_id:
        recommend_file = f'working/recommendations-{cycle_id}.md'

    model = select_model('review')

    # Gather context files
    context_parts = []
    for fpath, label in [
        (os.path.join(project_dir, 'storyforge.yaml'), 'storyforge.yaml'),
        (os.path.join(project_dir, 'CLAUDE.md'), 'CLAUDE.md'),
        (get_pipeline_file(project_dir), 'working/pipeline.csv'),
        (os.path.join(project_dir, 'reference', 'key-decisions.md'), 'reference/key-decisions.md'),
    ]:
        if os.path.isfile(fpath) and os.path.getsize(fpath) < 51200:
            with open(fpath) as f:
                context_parts.append(f'=== FILE: {label} ===\n{f.read()}\n=== END FILE ===')

    context = '\n'.join(context_parts)

    prompt = f"""You are writing next-step recommendations for a Storyforge novel project after a {review_type} pipeline run.

{context}

## Write the Recommendation

Use this exact format:

# Next Steps — {title}
**After:** {review_type} pipeline (cycle {cycle_id})
**Date:** {today}

## Recommended Next Step
[One clear recommendation with rationale.]

## Other Options
- [Next priority from the framework, with brief rationale]

## Project Health
[One sentence assessment of where the manuscript stands]
"""

    log('Running recommend step...')
    response = invoke_api(prompt, model, max_tokens=4096)
    if response:
        out_path = os.path.join(project_dir, recommend_file)
        os.makedirs(os.path.dirname(out_path), exist_ok=True)
        with open(out_path, 'w') as f:
            f.write(response)
        log(f'Recommendations saved to {recommend_file}')

    commit_and_push(project_dir, f'Recommend: next steps after {review_type} (cycle {cycle_id})',
                    [recommend_file, 'working/logs/', 'working/pipeline.csv'])

    if cycle_id:
        update_cycle_field(project_dir, cycle_id, 'recommendations', os.path.basename(recommend_file))
        update_cycle_field(project_dir, cycle_id, 'status', 'complete')
