"""storyforge migrate-medium — Convert a project between novel and graphic-novel mode.

Archives the current state, updates storyforge.yaml, transforms CSV files, and
clears scene files for re-drafting in the target medium.

Usage:
    storyforge migrate-medium --to novel           # convert to novel
    storyforge migrate-medium --to graphic-novel   # convert to graphic-novel
    storyforge migrate-medium --to X --dry-run     # show what would happen
    storyforge migrate-medium --to X --force       # skip confirmation
"""

import argparse
import os
import shutil
import sys
from datetime import datetime

from storyforge.common import detect_project_root, get_medium, log


# ============================================================================
# Helpers
# ============================================================================

def _read_csv(path: str) -> tuple[list[str], list[dict]]:
    """Read a pipe-delimited CSV. Returns (header_fields, rows_as_dicts)."""
    if not os.path.isfile(path):
        return [], []
    with open(path, newline='', encoding='utf-8') as f:
        raw = f.read().replace('\r\n', '\n').replace('\r', '')
    lines = [l for l in raw.splitlines() if l.strip()]
    if not lines:
        return [], []
    header = lines[0].split('|')
    rows = [dict(zip(header, l.split('|'))) for l in lines[1:]]
    return header, rows


def _write_csv(path: str, header: list[str], rows: list[dict]) -> None:
    """Write a pipe-delimited CSV."""
    with open(path, 'w', encoding='utf-8') as f:
        f.write('|'.join(header) + '\n')
        for row in rows:
            f.write('|'.join(row.get(col, '') for col in header) + '\n')


def _clear_columns(rows: list[dict], columns: list[str]) -> int:
    """Clear specific columns on all rows. Returns count of rows touched."""
    count = 0
    for row in rows:
        for col in columns:
            if col in row:
                row[col] = ''
                count += 1
    return len(rows)


def _set_column(rows: list[dict], column: str, value: str) -> int:
    """Set a column to a fixed value on all rows. Returns count of rows touched."""
    count = 0
    for row in rows:
        if column in row:
            row[column] = value
            count += 1
    return count


# ============================================================================
# Step 1: Validate direction
# ============================================================================

def step1_validate_direction(
    project_dir: str, target: str, force: bool
) -> tuple[str, str]:
    """Detect current medium, refuse if already at target (unless --force).

    Returns (from_medium, to_medium) on success.
    Exits 1 on refusal.
    """
    current = get_medium(project_dir)
    if current == target and not force:
        log(f'Error: project is already in {target!r} mode.')
        log('Nothing to do. Pass --force to create an archive anyway.')
        sys.exit(1)
    return current, target


# ============================================================================
# Step 2: Create archive directory
# ============================================================================

def step2_create_archive(
    project_dir: str, from_medium: str, to_medium: str, dry_run: bool
) -> str:
    """Create timestamped archive directory.

    Returns the archive path.
    """
    ts = datetime.now().strftime('%Y%m%d-%H%M%S')
    archive_name = f'{ts}-{from_medium}-to-{to_medium}'
    archive_dir = os.path.join(project_dir, 'working', 'migration', archive_name)
    if not dry_run:
        os.makedirs(archive_dir, exist_ok=True)
    log(f'  Archive dir: {archive_dir}')
    return archive_dir


# ============================================================================
# Step 3: Snapshot current state to archive
# ============================================================================

def step3_snapshot_state(
    project_dir: str, archive_dir: str, dry_run: bool
) -> list[str]:
    """Copy storyforge.yaml, key CSVs, and scenes/ to the archive.

    Returns list of copied paths.
    """
    ref_dir = os.path.join(project_dir, 'reference')
    snap = []

    files_to_copy = [
        os.path.join(project_dir, 'storyforge.yaml'),
        os.path.join(ref_dir, 'scenes.csv'),
        os.path.join(ref_dir, 'scene-briefs.csv'),
        os.path.join(ref_dir, 'voice-profile.csv'),
        os.path.join(ref_dir, 'chapter-map.csv'),
    ]

    for src in files_to_copy:
        if os.path.isfile(src):
            rel = os.path.relpath(src, project_dir)
            dest = os.path.join(archive_dir, rel)
            snap.append(rel)
            if not dry_run:
                os.makedirs(os.path.dirname(dest), exist_ok=True)
                shutil.copy2(src, dest)

    # Snapshot scenes/
    scenes_dir = os.path.join(project_dir, 'scenes')
    if os.path.isdir(scenes_dir):
        snap.append('scenes/')
        if not dry_run:
            dest_scenes = os.path.join(archive_dir, 'scenes')
            shutil.copytree(scenes_dir, dest_scenes, dirs_exist_ok=True)

    log(f'  Snapshot: {len(snap)} items archived')
    return snap


# ============================================================================
# Step 4: Update storyforge.yaml
# ============================================================================

def step4_update_yaml(project_dir: str, target: str, dry_run: bool) -> None:
    """Update project.medium in storyforge.yaml to the target value."""
    yaml_path = os.path.join(project_dir, 'storyforge.yaml')
    with open(yaml_path, encoding='utf-8') as f:
        content = f.read()

    import re
    # Replace existing medium field if present
    if re.search(r'^\s+medium:\s*', content, re.MULTILINE):
        new_content = re.sub(
            r'^(\s+medium:\s*).*$',
            rf'\g<1>{target}',
            content,
            flags=re.MULTILINE,
        )
    else:
        # Insert medium: under the `project:` block
        new_content = re.sub(
            r'^(project:\n)',
            rf'\g<1>  medium: {target}\n',
            content,
            flags=re.MULTILINE,
        )

    if not dry_run:
        with open(yaml_path, 'w', encoding='utf-8') as f:
            f.write(new_content)
    log(f'  storyforge.yaml: medium set to {target!r}')


# ============================================================================
# Step 5: Transform scenes.csv
# ============================================================================

def step5_transform_scenes_csv(
    project_dir: str, from_medium: str, to_medium: str, dry_run: bool
) -> str:
    """Clear medium-specific columns and reset status to 'mapped'."""
    scenes_path = os.path.join(project_dir, 'reference', 'scenes.csv')
    header, rows = _read_csv(scenes_path)
    if not rows:
        return 'skip: no rows'

    if from_medium == 'novel' and to_medium == 'graphic-novel':
        _clear_columns(rows, ['target_words', 'word_count'])
        log('  scenes.csv: cleared target_words, word_count')
    elif from_medium == 'graphic-novel' and to_medium == 'novel':
        _clear_columns(rows, ['target_pages', 'panel_count', 'page_count'])
        log('  scenes.csv: cleared target_pages, panel_count, page_count')

    _set_column(rows, 'status', 'mapped')
    log(f'  scenes.csv: reset {len(rows)} scene(s) to status=mapped')

    if not dry_run:
        _write_csv(scenes_path, header, rows)
    return f'done:{len(rows)}'


# ============================================================================
# Step 6: Transform scene-briefs.csv (GN→novel only)
# ============================================================================

def step6_transform_briefs_csv(
    project_dir: str, from_medium: str, to_medium: str, dry_run: bool
) -> str:
    """Clear GN-specific brief columns when converting graphic-novel → novel."""
    if not (from_medium == 'graphic-novel' and to_medium == 'novel'):
        return 'skip: not applicable for this direction'

    briefs_path = os.path.join(project_dir, 'reference', 'scene-briefs.csv')
    header, rows = _read_csv(briefs_path)
    if not rows:
        return 'skip: no rows'

    gn_cols = ['page_layout', 'panel_breakdown', 'visual_keywords',
               'page_turn_beats', 'caption_strategy']
    _clear_columns(rows, gn_cols)
    log(f'  scene-briefs.csv: cleared GN columns ({", ".join(gn_cols)})')

    if not dry_run:
        _write_csv(briefs_path, header, rows)
    return f'done:{len(rows)}'


# ============================================================================
# Step 7: Archive and clear scenes directory
# ============================================================================

def step7_archive_and_clear_scenes_dir(
    project_dir: str, archive_dir: str, from_medium: str, to_medium: str,
    dry_run: bool
) -> int:
    """Move scene files to archive and clear scenes/ for re-drafting.

    Returns count of files moved.
    """
    scenes_dir = os.path.join(project_dir, 'scenes')
    if not os.path.isdir(scenes_dir):
        log('  scenes/: directory not found, skipping')
        return 0

    scene_files = [
        f for f in os.listdir(scenes_dir)
        if f.endswith('.md') and f != '.gitkeep'
    ]

    if not scene_files:
        log('  scenes/: no scene files to archive')
        return 0

    subdir_name = 'scenes-novel' if from_medium == 'novel' else 'scenes-gn'
    archive_scenes = os.path.join(archive_dir, subdir_name)

    if not dry_run:
        os.makedirs(archive_scenes, exist_ok=True)
        for fname in scene_files:
            src = os.path.join(scenes_dir, fname)
            shutil.move(src, os.path.join(archive_scenes, fname))
        # Ensure scenes/ dir stays tracked by git
        gitkeep = os.path.join(scenes_dir, '.gitkeep')
        if not os.path.exists(gitkeep):
            open(gitkeep, 'w').close()

    log(f'  scenes/: moved {len(scene_files)} file(s) to archive/{subdir_name}')
    return len(scene_files)


# ============================================================================
# Step 8: Add visual notes to bibles (novel → graphic-novel only)
# ============================================================================

_BIBLE_VISUAL_NOTE = """
---

> **Graphic Novel Migration Note**
> Add a `### Visual` subsection for each character below. Include:
> - Silhouette and body language cues
> - Signature visual elements (costume, props, marks)
> - Costume continuity notes (what stays the same across scenes)
> - Any distinctive features the artist must maintain
>
> See `reference/character-bible.md` in the GN fixture for an example.
"""

_WORLD_VISUAL_NOTE = """
---

> **Graphic Novel Migration Note**
> Add a `### Visual` subsection for each location below. Include:
> - Visual keywords (textures, colours, lighting mood)
> - Camera/perspective conventions for this space
> - Continuity anchors (always-present elements)
>
> See `reference/world-bible.md` in the GN fixture for an example.
"""


def step8_add_bible_visual_notes(
    project_dir: str, dry_run: bool
) -> list[str]:
    """Append visual-note stubs to character-bible.md and world-bible.md.

    Only modifies files that exist and don't already contain '### Visual'.
    Returns list of modified file paths.
    """
    ref_dir = os.path.join(project_dir, 'reference')
    modified = []

    bibles = [
        (os.path.join(ref_dir, 'character-bible.md'), _BIBLE_VISUAL_NOTE),
        (os.path.join(ref_dir, 'world-bible.md'), _WORLD_VISUAL_NOTE),
    ]

    for path, note in bibles:
        if not os.path.isfile(path):
            continue
        with open(path, encoding='utf-8') as f:
            content = f.read()
        if '### Visual' in content:
            log(f'  {os.path.basename(path)}: already has ### Visual sections, skipping')
            continue
        if not dry_run:
            with open(path, 'a', encoding='utf-8') as f:
                f.write(note)
        modified.append(path)
        log(f'  {os.path.basename(path)}: appended visual migration note')

    return modified


# ============================================================================
# Step 9: Print summary
# ============================================================================

def step9_print_summary(
    from_medium: str, to_medium: str, archive_dir: str,
    scene_count: int, dry_run: bool
) -> None:
    """Print a human-readable migration summary with next steps."""
    if dry_run:
        print()
        print('=== DRY RUN — no files were modified ===')
        print()
        print(f'Would migrate: {from_medium} → {to_medium}')
        print(f'Would archive to: {archive_dir}')
        print(f'Would clear {scene_count} scene file(s) from scenes/')
        return

    print()
    print('=== Migration complete ===')
    print()
    print(f'Converted: {from_medium} → {to_medium}')
    print(f'Archive:   {archive_dir}')
    print()
    print('What changed:')
    print('  - storyforge.yaml: project.medium updated')
    print('  - scenes.csv: status reset to "mapped" for all scenes')

    if from_medium == 'novel' and to_medium == 'graphic-novel':
        print('  - scenes.csv: target_words and word_count cleared')
        print(f'  - scenes/: {scene_count} prose file(s) moved to archive/scenes-novel')
        print('  - character-bible.md, world-bible.md: visual notes appended (if no ### Visual sections existed)')
    elif from_medium == 'graphic-novel' and to_medium == 'novel':
        print('  - scenes.csv: target_pages, panel_count, page_count cleared')
        print('  - scene-briefs.csv: GN columns cleared (page_layout, panel_breakdown, visual_keywords, page_turn_beats, caption_strategy)')
        print(f'  - scenes/: {scene_count} script file(s) moved to archive/scenes-gn')

    print()
    print('What was preserved:')
    print('  - reference/scene-intent.csv (medium-agnostic)')
    print('  - reference/voice-profile.csv (voice carries between mediums)')
    print('  - reference/story-architecture.md (if present)')
    print('  - All other reference files')
    print()
    print('Reversibility:')
    print('  Every change is committed — use git to revert if needed.')
    print('  The full archive is preserved at:')
    print(f'    {archive_dir}')
    print()

    if from_medium == 'novel' and to_medium == 'graphic-novel':
        print('Next steps:')
        print('  1. Add ### Visual subsections to reference/character-bible.md per character')
        print('  2. Add ### Visual subsections to reference/world-bible.md per location')
        print('  3. Set target_pages for each scene in reference/scenes.csv')
        print('  4. Run: ./storyforge elaborate --stage briefs')
        print('     (fills page_layout, panel_breakdown, visual_keywords, page_turn_beats, caption_strategy)')
        print('  5. Run: ./storyforge write  (to draft panel scripts scene by scene)')
    elif from_medium == 'graphic-novel' and to_medium == 'novel':
        print('Next steps:')
        print('  1. Set target_words per scene in reference/scenes.csv')
        print('     (or run ./storyforge elaborate --stage map to repopulate)')
        print('  2. Run: ./storyforge write  (to draft prose scenes)')


# ============================================================================
# Argument parsing
# ============================================================================

def parse_args(argv):
    parser = argparse.ArgumentParser(
        prog='storyforge migrate-medium',
        description='Convert a project between novel and graphic-novel mode.',
    )
    parser.add_argument(
        '--to', required=True,
        choices=['novel', 'graphic-novel'],
        metavar='{novel|graphic-novel}',
        dest='target',
        help='Target medium to convert to',
    )
    parser.add_argument(
        '--dry-run', action='store_true',
        help='Show what would happen without modifying any files',
    )
    parser.add_argument(
        '--force', action='store_true',
        help='Skip confirmation; also bypass "already in target medium" guard',
    )
    parser.add_argument(
        '--no-commit', action='store_true',
        help='Apply changes but skip git commit',
    )
    return parser.parse_args(argv)


# ============================================================================
# Main
# ============================================================================

def main(argv=None):
    args = parse_args(argv or [])
    project_dir = detect_project_root()

    log(f'migrate-medium: project={project_dir}')
    log(f'  target={args.target}  dry-run={args.dry_run}  force={args.force}')
    log('')

    # Step 1: Validate
    from_medium, to_medium = step1_validate_direction(
        project_dir, args.target, args.force
    )
    log(f'  [1/9] Direction: {from_medium} → {to_medium}')

    # Step 2: Create archive directory
    archive_dir = step2_create_archive(
        project_dir, from_medium, to_medium, args.dry_run
    )
    log(f'  [2/9] Archive directory created')

    # Step 3: Snapshot state
    snap = step3_snapshot_state(project_dir, archive_dir, args.dry_run)
    log(f'  [3/9] State snapshot: {len(snap)} item(s)')

    # Step 4: Update storyforge.yaml
    step4_update_yaml(project_dir, to_medium, args.dry_run)
    log(f'  [4/9] storyforge.yaml updated')

    # Step 5: Transform scenes.csv
    result = step5_transform_scenes_csv(
        project_dir, from_medium, to_medium, args.dry_run
    )
    log(f'  [5/9] scenes.csv: {result}')

    # Step 6: Transform scene-briefs.csv
    result = step6_transform_briefs_csv(
        project_dir, from_medium, to_medium, args.dry_run
    )
    log(f'  [6/9] scene-briefs.csv: {result}')

    # Step 7: Archive and clear scenes dir
    scene_count = step7_archive_and_clear_scenes_dir(
        project_dir, archive_dir, from_medium, to_medium, args.dry_run
    )
    log(f'  [7/9] scenes/: {scene_count} file(s) archived')

    # Step 8: Bible visual notes (novel → GN only)
    if from_medium == 'novel' and to_medium == 'graphic-novel':
        modified = step8_add_bible_visual_notes(project_dir, args.dry_run)
        log(f'  [8/9] Bible visual notes: {len(modified)} file(s) updated')
    else:
        log('  [8/9] Bible visual notes: skipped (GN→novel direction)')

    # Step 9: Summary
    step9_print_summary(
        from_medium, to_medium, archive_dir, scene_count, args.dry_run
    )
    log('  [9/9] Summary printed')

    # Commit
    if not args.dry_run and not args.no_commit:
        from storyforge.git import commit_and_push
        committed = commit_and_push(
            project_dir,
            f'Migrate medium: {from_medium} → {to_medium}',
            [
                'storyforge.yaml',
                'reference/',
                'scenes/',
                'working/migration/',
                'working/',
            ],
        )
        if committed:
            log('Changes committed and pushed.')
        else:
            log('No changes to commit (or git not available).')
