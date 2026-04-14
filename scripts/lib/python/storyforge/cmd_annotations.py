"""storyforge annotations — Fetch and process reader annotations from Bookshelf.

Fetches reader annotations, reconciles against working/annotations.csv,
routes by color intent, and promotes exemplar candidates.

Usage:
    storyforge annotations                    # Fetch and reconcile
    storyforge annotations --status new       # Show only unaddressed
    storyforge annotations --color pink       # Filter by color
    storyforge annotations --scene arrival    # Filter by scene
    storyforge annotations --dry-run          # Show what would be fetched
"""

import argparse
import os
import re
import sys

from storyforge.common import (
    detect_project_root, install_signal_handlers, log, read_yaml_field,
    get_coaching_level,
)


def parse_args(argv):
    parser = argparse.ArgumentParser(
        prog='storyforge annotations',
        description='Fetch and process reader annotations from Bookshelf.',
    )
    parser.add_argument('--status', choices=['new', 'addressed', 'skipped',
                                              'protected', 'exemplar', 'removed'],
                        help='Filter display to one status')
    parser.add_argument('--color', choices=['pink', 'orange', 'blue', 'green', 'yellow'],
                        help='Filter display to one color')
    parser.add_argument('--scene', help='Filter display to one scene ID')
    parser.add_argument('--dry-run', action='store_true',
                        help='Fetch and display without writing CSV')
    return parser.parse_args(argv)


def main(argv=None):
    args = parse_args(argv or [])
    install_signal_handlers()
    project_dir = detect_project_root()

    from storyforge.bookshelf import authenticate, check_env, get_annotations
    from storyforge.annotations import (
        load_annotations_csv, save_annotations_csv, reconcile,
        promote_exemplars, COLOR_LABELS,
    )

    # Derive book slug from title
    title = (read_yaml_field('project.title', project_dir)
             or read_yaml_field('title', project_dir) or '')
    if not title:
        log('ERROR: No project title found in storyforge.yaml')
        sys.exit(1)
    slug = re.sub(r'[^a-z0-9]+', '-', title.lower()).strip('-')

    # Authenticate
    env = check_env()
    log('Authenticating with Supabase...')
    try:
        token = authenticate(
            env['BOOKSHELF_SUPABASE_URL'],
            env['BOOKSHELF_SUPABASE_ANON_KEY'],
            env['BOOKSHELF_EMAIL'],
            env['BOOKSHELF_PASSWORD'],
        )
    except RuntimeError as e:
        log(f'Authentication failed: {e}')
        sys.exit(1)

    # Fetch annotations
    log(f'Fetching annotations for "{title}" (slug: {slug})...')
    try:
        data = get_annotations(env['BOOKSHELF_URL'], token, slug)
    except RuntimeError as e:
        log(f'Failed to fetch annotations: {e}')
        sys.exit(1)

    api_annotations = data.get('annotations', [])
    log(f'API returned {len(api_annotations)} annotation(s)')

    # Reconcile
    existing = load_annotations_csv(project_dir)
    updated, summary = reconcile(existing, api_annotations)

    log(f'Reconciliation: {summary["new"]} new, '
        f'{summary["existing"]} existing, '
        f'{summary["removed"]} removed, '
        f'{summary["total"]} total')

    # Exemplar promotion
    coaching_level = get_coaching_level(project_dir)
    promoted = promote_exemplars(project_dir, updated, coaching_level)
    for ann_id in promoted:
        updated[ann_id]['status'] = 'exemplar'
        updated[ann_id]['fix_location'] = 'exemplar'

    if promoted:
        log(f'Promoted {len(promoted)} passage(s) to exemplars')

    # Save
    if not args.dry_run:
        path = save_annotations_csv(project_dir, updated)
        log(f'Saved: {path}')
    else:
        log('Dry run — not writing annotations CSV')

    # Display summary by color
    display = list(updated.values())
    if args.status:
        display = [a for a in display if a.get('status') == args.status]
    if args.color:
        display = [a for a in display if a.get('color') == args.color]
    if args.scene:
        display = [a for a in display if a.get('scene_id') == args.scene]

    if display:
        log('')
        log(f'Annotations ({len(display)}):')
        for ann in display:
            scene = ann.get('scene_id', '?')
            color = ann.get('color', '?')
            label = ann.get('color_label', COLOR_LABELS.get(color, color))
            status = ann.get('status', '?')
            text = ann.get('text', '')[:60]
            note = ann.get('note', '')
            line = f'  [{status}] {scene} ({label}): "{text}"'
            if note:
                line += f' — {note[:40]}'
            log(line)

    # Count unaddressed by intent
    new_craft = sum(1 for a in updated.values()
                    if a.get('status') == 'new' and a.get('fix_location') == 'craft')
    new_structural = sum(1 for a in updated.values()
                         if a.get('status') == 'new' and a.get('fix_location') == 'structural')
    new_protection = sum(1 for a in updated.values()
                         if a.get('status') == 'new' and a.get('fix_location') == 'protection')
    new_research = sum(1 for a in updated.values()
                       if a.get('status') == 'new' and a.get('fix_location') == 'research')

    if new_craft or new_structural or new_protection or new_research:
        log('')
        log('Unaddressed:')
        if new_craft:
            log(f'  {new_craft} craft revision(s) (pink/yellow)')
        if new_structural:
            log(f'  {new_structural} structural revision(s) (orange)')
        if new_protection:
            log(f'  {new_protection} passage(s) to protect (green)')
        if new_research:
            log(f'  {new_research} research item(s) (blue)')
