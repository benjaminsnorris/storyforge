"""storyforge review — Run a pipeline review for the current branch.

Usage:
    storyforge review                    # Auto-detect review type
    storyforge review --type drafting    # Specify review type
    storyforge review --dry-run          # Show what would be done
"""

import argparse
import os
import subprocess
import sys

from storyforge.common import (
    detect_project_root, log, read_yaml_field, install_signal_handlers,
    set_log_file,
)
from storyforge.git import current_branch, has_gh, run_review_phase
from storyforge.runner import HealingZone


def parse_args(argv):
    parser = argparse.ArgumentParser(prog='storyforge review',
                                     description='Run a pipeline review')
    parser.add_argument('--type', dest='review_type', default='manual',
                        choices=['drafting', 'evaluation', 'revision', 'assembly', 'manual'],
                        help='Review type (default: auto-detect from branch)')
    parser.add_argument('--interactive', '-i', action='store_true',
                        help='Run interactively')
    parser.add_argument('--dry-run', action='store_true',
                        help='Show what would be done')
    return parser.parse_args(argv)


def main(argv=None):
    args = parse_args(argv or [])

    install_signal_handlers()
    project_dir = detect_project_root()

    log_dir = os.path.join(project_dir, 'working', 'logs')
    os.makedirs(log_dir, exist_ok=True)
    set_log_file(os.path.join(log_dir, 'review-log.txt'))

    log(f'Project root: {project_dir}')

    branch = current_branch(project_dir)
    if not branch:
        log('ERROR: Not in a git repository')
        sys.exit(1)

    log(f'Branch: {branch}')

    # Auto-detect review type from branch name
    review_type = args.review_type
    if review_type == 'manual' and branch.startswith('storyforge/'):
        branch_cmd = branch.split('/')[1].split('-')[0]
        type_map = {
            'write': 'drafting',
            'evaluate': 'evaluation',
            'revise': 'revision',
            'assemble': 'assembly',
        }
        if branch_cmd in type_map:
            review_type = type_map[branch_cmd]
            log(f'Auto-detected review type: {review_type} (from branch name)')

    # Find PR
    pr_number = ''
    if has_gh():
        r = subprocess.run(
            ['gh', 'pr', 'view', '--json', 'number', '--jq', '.number'],
            capture_output=True, text=True, cwd=project_dir,
        )
        if r.returncode == 0 and r.stdout.strip():
            pr_number = r.stdout.strip()
            log(f'Found PR #{pr_number}')
        else:
            log(f'No PR found for branch {branch}')

    # Set up interactive mode
    if args.interactive:
        interactive_file = os.path.join(project_dir, 'working', '.interactive')
        open(interactive_file, 'a').close()

    title = read_yaml_field('project.title', project_dir) or 'Unknown'

    log('============================================')
    log('Storyforge Pipeline Review')
    log(f'Project: {title}')
    log(f'Type: {review_type}')
    log(f'Branch: {branch}')
    if pr_number:
        log(f'PR: #{pr_number}')
    log('============================================')

    if args.dry_run:
        log('DRY RUN: would run review phase')
        return

    with HealingZone(f'running {review_type} review', project_dir):
        run_review_phase(review_type, project_dir, pr_number)
