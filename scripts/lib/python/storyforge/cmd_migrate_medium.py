"""storyforge migrate-medium — Convert a project between novel and graphic-novel mode.

Archives the current state, updates storyforge.yaml, transforms CSV files, and
clears scene files for re-drafting in the target medium.

Usage:
    storyforge migrate-medium --to novel           # convert to novel
    storyforge migrate-medium --to graphic-novel   # convert to graphic-novel
    storyforge migrate-medium --to X --dry-run     # show what would happen
    storyforge migrate-medium --to X --force       # bypass the "already in target medium" guard
"""

import argparse
import os
import shutil
import sys
from datetime import datetime

from storyforge.common import detect_project_root, get_medium, get_plugin_dir, log
from storyforge.git import commit_and_push, ensure_on_branch


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
    return count


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
    # Include microseconds so two --force runs in the same second don't collide.
    ts = datetime.now().strftime('%Y%m%d-%H%M%S-%f')
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

    # Note: scenes/ is NOT copied here — step 7 moves scene files to archive/scenes/,
    # which IS the pre-migration snapshot of the scenes. Copying here would duplicate them.

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
        # Insert medium: under the `project:` block.
        # Match `project:` followed by anything up to and including the newline,
        # so projects with `project: # main config` style yaml still get the field
        # inserted under the project block.
        pattern = re.compile(r'^(project:[^\n]*\n)', re.MULTILINE)
        new_content = pattern.sub(
            rf'\g<1>  medium: {target}\n',
            content,
        )

    if not dry_run:
        with open(yaml_path, 'w', encoding='utf-8') as f:
            f.write(new_content)
        # Post-write verification: confirm medium was actually written correctly
        actual = get_medium(project_dir)
        if actual != target:
            log(
                f'ERROR: storyforge.yaml was written but get_medium() returned {actual!r} '
                f'(expected {target!r}). '
                f'The YAML file may have a non-standard format. '
                f'Please set `project.medium: {target}` manually under the `project:` key.'
            )
            sys.exit(1)
    log(f'  storyforge.yaml: medium set to {target!r}')


# ============================================================================
# Step 5: Transform scenes.csv
# ============================================================================


# Full merged header that includes all columns from both mediums.
# After migration the CSV always uses this header; irrelevant columns stay empty.
# This lets the author immediately edit target_pages (N→GN) or target_words (GN→N)
# without adding columns manually.
_SCENES_FULL_HEADER = [
    'id', 'seq', 'title', 'part', 'pov', 'location',
    'timeline_day', 'time_of_day', 'duration', 'type', 'status',
    'word_count', 'target_words',      # novel columns
    'target_pages', 'panel_count', 'page_count',  # GN columns
]

_BRIEFS_FULL_HEADER = [
    'id', 'goal', 'conflict', 'outcome', 'crisis', 'decision',
    'knowledge_in', 'knowledge_out', 'key_actions', 'key_dialogue',
    'emotions', 'motifs', 'subtext', 'continuity_deps', 'has_overflow',
    'physical_state_in', 'physical_state_out',  # novel columns
    'page_layout', 'panel_breakdown', 'visual_keywords',  # GN columns
    'page_turn_beats', 'caption_strategy',                # GN columns
]


def step5_transform_scenes_csv(
    project_dir: str, from_medium: str, to_medium: str, dry_run: bool
) -> str:
    """Clear medium-specific columns, reset status to 'mapped', and widen header.

    After migration the CSV uses _SCENES_FULL_HEADER so the author can
    immediately populate target medium columns without adding them manually.
    """
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

    # Reset status to 'mapped' EXCEPT for terminal editorial states.
    # Normalize the value (strip whitespace, lowercase) before comparing so
    # ' cut ' or 'CUT' don't slip through. (cut/merged are deliberate authorial
    # decisions and must survive migration.)
    TERMINAL_STATUSES = {'cut', 'merged'}
    reset_count = 0
    for row in rows:
        status = (row.get('status') or '').strip().lower()
        if status not in TERMINAL_STATUSES:
            row['status'] = 'mapped'
            reset_count += 1
    skipped = len(rows) - reset_count
    log(f'  scenes.csv: reset {reset_count} scene(s) to status=mapped'
        + (f' (skipped {skipped} terminal: cut/merged)' if skipped else ''))

    if not dry_run:
        # Always write the full header so target-medium columns are present.
        _write_csv(scenes_path, _SCENES_FULL_HEADER, rows)
    return f'done:{len(rows)}'


# ============================================================================
# Step 6: Transform scene-briefs.csv (GN→novel only)
# ============================================================================

def step6_transform_briefs_csv(
    project_dir: str, from_medium: str, to_medium: str, dry_run: bool
) -> str:
    """Clear GN-specific brief columns and widen header to full schema.

    On N→GN: adds the five GN columns (empty) so the author can populate them.
    On GN→novel: clears the GN columns and keeps the full header for symmetry.
    """
    briefs_path = os.path.join(project_dir, 'reference', 'scene-briefs.csv')
    header, rows = _read_csv(briefs_path)
    if not rows:
        return 'skip: no rows'

    gn_cols = ['page_layout', 'panel_breakdown', 'visual_keywords',
               'page_turn_beats', 'caption_strategy']

    if from_medium == 'graphic-novel' and to_medium == 'novel':
        _clear_columns(rows, gn_cols)
        log(f'  scene-briefs.csv: cleared GN columns ({", ".join(gn_cols)})')
    elif from_medium == 'novel' and to_medium == 'graphic-novel':
        # GN columns don't exist yet — nothing to clear, but we still widen the header.
        log('  scene-briefs.csv: widening to full schema (added GN columns, empty)')
    else:
        return 'skip: not applicable for this direction'

    if not dry_run:
        # Always write the full header so both novel and GN columns are present.
        _write_csv(briefs_path, _BRIEFS_FULL_HEADER, rows)
    return f'done:{len(rows)}'


# ============================================================================
# Step 7: Archive and clear scenes directory
# ============================================================================

def _load_scene_ids(project_dir: str) -> set[str] | None:
    """Return the set of scene IDs from reference/scenes.csv, or None if unavailable."""
    scenes_csv = os.path.join(project_dir, 'reference', 'scenes.csv')
    _, rows = _read_csv(scenes_csv)
    if not rows:
        return None
    ids = {r.get('id', '').strip() for r in rows if r.get('id', '').strip()}
    return ids if ids else None


def step7_archive_and_clear_scenes_dir(
    project_dir: str, archive_dir: str, from_medium: str, to_medium: str,
    dry_run: bool
) -> int:
    """Move scene files to archive and clear scenes/ for re-drafting.

    Only moves files that match a known scene ID from reference/scenes.csv.
    README.md, NOTES.md, and other author notes in scenes/ are left in place.
    Falls back to moving all .md files (with a warning) if scenes.csv is absent.

    Returns count of files moved.
    """
    scenes_dir = os.path.join(project_dir, 'scenes')
    if not os.path.isdir(scenes_dir):
        log('  scenes/: directory not found, skipping')
        return 0

    all_md = [f for f in os.listdir(scenes_dir)
              if f.endswith('.md') and f != '.gitkeep']

    if not all_md:
        log('  scenes/: no scene files to archive')
        return 0

    # Restrict to filenames that correspond to known scene IDs.
    # This prevents README.md, NOTES.md, and other author notes from being archived.
    known_ids = _load_scene_ids(project_dir)
    if known_ids is not None:
        scene_files = [f for f in all_md if f[:-3] in known_ids]  # strip ".md"
        non_scene = set(all_md) - set(scene_files)
        if non_scene:
            log(f'  scenes/: leaving {len(non_scene)} non-scene file(s) in place: '
                + ', '.join(sorted(non_scene)))
    else:
        # scenes.csv missing or empty — fall back to original behavior with warning.
        log('  scenes/: WARNING: reference/scenes.csv not found or empty; '
            'archiving ALL .md files (including any README/NOTES)')
        scene_files = all_md

    if not scene_files:
        log('  scenes/: no scene files matched known IDs')
        return 0

    archive_scenes = os.path.join(archive_dir, 'scenes')

    if not dry_run:
        os.makedirs(archive_scenes, exist_ok=True)
        for fname in scene_files:
            src = os.path.join(scenes_dir, fname)
            shutil.move(src, os.path.join(archive_scenes, fname))
        # Ensure scenes/ dir stays tracked by git
        gitkeep = os.path.join(scenes_dir, '.gitkeep')
        if not os.path.exists(gitkeep):
            open(gitkeep, 'w').close()

    log(f'  scenes/: moved {len(scene_files)} file(s) to archive/scenes')
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

    Always appends to existing files (even when some ### Visual sections already
    exist) so partial migrations don't leave characters without migration cues.
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
        # Always append the migration note, even when SOME ### Visual sections
        # already exist. A partial migration (e.g. one character already has a
        # Visual section) would otherwise leave every other character without
        # the prompt. The note is additive and harmless to delete; a skip would
        # silently leave characters without migration cues.
        if not dry_run:
            with open(path, 'a', encoding='utf-8') as f:
                f.write(note)
        modified.append(path)
        log(f'  {os.path.basename(path)}: appended visual migration note')

    return modified


# ============================================================================
# Step 8b: Scaffold canon tree (novel → graphic-novel only)
# ============================================================================

def step8b_scaffold_canon_tree(
    project_dir: str, dry_run: bool
) -> list[str]:
    """Copy templates/reference/canon/ and visual-style.md into the project.

    Idempotent: if reference/canon/ already exists, no files are copied
    or overwritten — the author may have started canon work between
    migration runs and we should leave it alone. Same rule for
    visual-style.md, which authors often hand-edit with cross-references
    and project-wide iteration notes.

    Returns list of project-relative paths that were created.
    """
    created: list[str] = []
    plugin_dir = get_plugin_dir()
    src_canon = os.path.join(plugin_dir, 'templates', 'reference', 'canon')
    src_visual = os.path.join(
        plugin_dir, 'templates', 'reference', 'visual-style.md',
    )
    dst_canon = os.path.join(project_dir, 'reference', 'canon')
    dst_visual = os.path.join(project_dir, 'reference', 'visual-style.md')

    if not os.path.isdir(dst_canon):
        if os.path.isdir(src_canon):
            if not dry_run:
                shutil.copytree(src_canon, dst_canon)
            created.append('reference/canon/')
            log('  reference/canon/: scaffolded from templates')
        else:
            log(f'  WARNING: plugin templates not found at {src_canon}; '
                'canon tree not scaffolded — manual setup required')

    if not os.path.isfile(dst_visual):
        if os.path.isfile(src_visual):
            if not dry_run:
                os.makedirs(os.path.dirname(dst_visual), exist_ok=True)
                shutil.copy2(src_visual, dst_visual)
            created.append('reference/visual-style.md')
            log('  reference/visual-style.md: scaffolded from template')
        else:
            log(f'  WARNING: plugin template not found at {src_visual}; '
                'visual-style.md not scaffolded — manual setup required')

    return created


# ============================================================================
# Step 9: Print summary
# ============================================================================

def step9_print_summary(
    from_medium: str, to_medium: str, archive_dir: str,
    scene_count: int, dry_run: bool, no_commit: bool = False
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
    print('  - scenes.csv: status reset to "mapped" for non-terminal scenes (cut/merged preserved)')

    if from_medium == 'novel' and to_medium == 'graphic-novel':
        print('  - scenes.csv: target_words and word_count cleared')
        print(f'  - scenes/: {scene_count} prose file(s) moved to archive/scenes')
        print('  - character-bible.md, world-bible.md: visual migration notes appended')
        print('  - reference/canon/ and reference/visual-style.md: scaffolded')
    elif from_medium == 'graphic-novel' and to_medium == 'novel':
        print('  - scenes.csv: target_pages, panel_count, page_count cleared')
        print('  - scene-briefs.csv: GN columns cleared (page_layout, panel_breakdown, visual_keywords, page_turn_beats, caption_strategy)')
        print(f'  - scenes/: {scene_count} script file(s) moved to archive/scenes')

    print()
    print('What was preserved:')
    print('  - reference/scene-intent.csv (medium-agnostic)')
    print('  - reference/voice-profile.csv (voice carries between mediums)')
    print('  - reference/story-architecture.md (if present)')
    print('  - All other reference files')
    print()
    print('Reversibility:')
    if no_commit:
        print('  Changes are NOT committed (--no-commit). The archive in `working/migration/` is your')
        print('  fallback if you need to recover. Run `git add -A && git commit` when ready.')
    else:
        print('  Every change is committed. Use `git revert` to undo the migration commit if needed.')
    print('  The full archive is preserved at:')
    print(f'    {archive_dir}')
    print()

    if from_medium == 'novel' and to_medium == 'graphic-novel':
        print('Next steps:')
        print('  1. Add ### Visual subsections to reference/character-bible.md per character')
        print('  2. Add ### Visual subsections to reference/world-bible.md per location')
        print('  3. Fill in reference/canon/ — style-foundation, lighting-laws, etc.')
        print('     plus a canon/characters/<slug>.md per on-page character')
        print('  4. Set target_pages for each scene in reference/scenes.csv')
        print('  5. Run: ./storyforge elaborate --stage briefs')
        print('     (fills page_layout, panel_breakdown, visual_keywords, page_turn_beats, caption_strategy)')
        print('  6. Run: ./storyforge write  (to draft panel scripts scene by scene)')
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
        help='Bypass the "already in target medium" guard. Useful if you previously aborted a migration and want to retry.',
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

    # Per CLAUDE.md: if on main, create a feature branch first so the migration
    # is never committed directly to main.
    if not args.dry_run and not args.no_commit:
        ensure_on_branch('migrate-medium', project_dir)

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
        created = step8b_scaffold_canon_tree(project_dir, args.dry_run)
        log(f'  [8b/9] Canon tree: {len(created)} item(s) scaffolded')
    else:
        log('  [8/9] Bible visual notes: skipped (GN→novel direction)')

    # Step 9: Summary
    step9_print_summary(
        from_medium, to_medium, archive_dir, scene_count, args.dry_run,
        no_commit=args.no_commit,
    )
    log('  [9/9] Summary printed')

    # Commit
    if not args.dry_run and not args.no_commit:
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
