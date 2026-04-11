"""storyforge cleanup — Project structure cleanup and migration.

Fixes structural drift in Storyforge novel projects: updates gitignore,
creates missing directories, migrates storyforge.yaml, adds CSV columns,
removes junk files, deletes legacy artifacts, and reports integrity issues.

Usage:
    storyforge cleanup                  # Apply all fixes and commit
    storyforge cleanup --dry-run        # Report what would change
    storyforge cleanup --verbose        # Detailed output
    storyforge cleanup --scenes         # Also strip writing-agent artifacts
    storyforge cleanup --csv            # Run only the CSV integrity report
"""

import argparse
import glob
import os
import re
import shutil
import subprocess
import sys
import tempfile

from storyforge.common import detect_project_root, log, read_yaml_field
from storyforge.git import commit_and_push, ensure_on_branch
from storyforge.parsing import clean_scene_content, extract_single_scene


# ============================================================================
# Constants
# ============================================================================

GITIGNORE_REQUIRED = [
    'working/logs/',
    'working/scores/**/.batch-requests.jsonl',
    'working/evaluations/**/.status-*',
    'working/scores/**/.markers-*',
    '.DS_Store',
    'working/.autopilot',
    'working/.interactive',
]

EXPECTED_DIRS = [
    'manuscript/press-kit',
    'working/logs',
    'working/evaluations',
    'working/plans',
    'working/recommendations',
]

PIPELINE_EXPECTED = 'cycle|started|status|evaluation|scoring|plan|review|recommendations|summary'

EXPECTED_TOP_DIRS = set('scenes reference working manuscript storyforge .git'.split())
EXPECTED_TOP_FILES = set('storyforge.yaml CLAUDE.md .gitignore .DS_Store storyforge'.split())

# Expected CSV schemas — canonical column lists for all known CSV files.
# Keys are paths relative to project root.
EXPECTED_CSV_SCHEMAS: dict[str, list[str]] = {
    # Core scene data (reference/)
    'reference/scenes.csv': [
        'id', 'seq', 'title', 'part', 'pov', 'location',
        'timeline_day', 'time_of_day', 'duration', 'type', 'status',
        'word_count', 'target_words',
    ],
    'reference/scene-intent.csv': [
        'id', 'function', 'action_sequel', 'emotional_arc', 'value_at_stake',
        'value_shift', 'turning_point', 'characters', 'on_stage',
        'mice_threads',
    ],
    'reference/scene-briefs.csv': [
        'id', 'goal', 'conflict', 'outcome', 'crisis', 'decision',
        'knowledge_in', 'knowledge_out', 'key_actions', 'key_dialogue',
        'emotions', 'motifs', 'subtext', 'continuity_deps', 'has_overflow',
        'physical_state_in', 'physical_state_out',
    ],
    # Registry CSVs (reference/)
    'reference/characters.csv': ['id', 'name', 'aliases', 'role', 'death_scene'],
    'reference/locations.csv': ['id', 'name', 'aliases'],
    'reference/values.csv': ['id', 'name', 'aliases'],
    'reference/knowledge.csv': ['id', 'name', 'aliases', 'category', 'origin'],
    'reference/mice-threads.csv': ['id', 'name', 'type', 'aliases'],
    'reference/motif-taxonomy.csv': ['id', 'name', 'aliases', 'tier'],
    'reference/physical-states.csv': [
        'id', 'character', 'description', 'category', 'acquired',
        'resolves', 'action_gating',
    ],
    'reference/chapter-map.csv': [
        'chapter', 'title', 'heading', 'part', 'scenes',
    ],
    # Working CSVs
    'working/craft-weights.csv': [
        'section', 'principle', 'weight', 'author_weight', 'notes',
    ],
    'working/pipeline.csv': [
        'cycle', 'started', 'status', 'evaluation', 'scoring',
        'plan', 'review', 'recommendations', 'summary',
    ],
    'working/costs/ledger.csv': [
        'timestamp', 'operation', 'target', 'model', 'input_tokens',
        'output_tokens', 'cache_read', 'cache_create', 'cost_usd',
        'duration_s',
    ],
    'working/scores/score-history.csv': [
        'cycle', 'scene_id', 'principle', 'score',
    ],
}
EXPECTED_WORKING_DIRS = set(
    'logs evaluations plans scores costs reviews recommendations coaching enrich timeline backups scenes-setup'.split()
)
EXPECTED_WORKING_FILES = set(
    'pipeline.csv craft-weights.csv overrides.csv exemplars.csv dashboard.html cleanup-report.csv'.split()
)


# ============================================================================
# Gitignore
# ============================================================================

def update_gitignore(project_dir: str) -> None:
    """Ensure .gitignore contains all required entries."""
    gitignore = os.path.join(project_dir, '.gitignore')

    if not os.path.isfile(gitignore):
        with open(gitignore, 'w') as f:
            f.write('# Storyforge — Novel Project .gitignore\n\n# macOS\n.DS_Store\n\n')

    with open(gitignore) as f:
        content = f.read()

    new_content = content
    if not new_content.endswith('\n'):
        new_content += '\n'

    added = False

    if 'working/logs/' not in content:
        new_content += '\n# Logs (debugging output, value extracted at write time)\nworking/logs/\n'
        added = True

    if 'working/scores/**/.batch-requests.jsonl' not in content:
        new_content += '\n# Batch API payloads (keep only latest for debugging)\nworking/scores/**/.batch-requests.jsonl\n'
        added = True

    if 'working/evaluations/**/.status-*' not in content:
        new_content += '\n# Intermediate scoring/eval state\nworking/evaluations/**/.status-*\n'
        added = True

    if 'working/scores/**/.markers-*' not in content:
        new_content += 'working/scores/**/.markers-*\n'
        added = True

    if 'working/.interactive' not in content:
        if 'working/.autopilot' in new_content:
            new_content = new_content.replace('working/.autopilot\n',
                                              'working/.autopilot\nworking/.interactive\n')
        else:
            new_content += '\n# Temporary flag files (cleaned up by scripts)\nworking/.autopilot\nworking/.interactive\n'
        added = True

    if added:
        with open(gitignore, 'w') as f:
            f.write(new_content)


# ============================================================================
# Missing directories
# ============================================================================

def create_missing_dirs(project_dir: str) -> list[str]:
    """Create expected directories that are missing. Returns list of created dirs."""
    created = []
    for d in EXPECTED_DIRS:
        path = os.path.join(project_dir, d)
        if not os.path.isdir(path):
            os.makedirs(path, exist_ok=True)
            gitkeep = os.path.join(path, '.gitkeep')
            with open(gitkeep, 'w') as f:
                pass
            created.append(d)
    return created


# ============================================================================
# Junk file cleanup
# ============================================================================

def clean_junk_files(project_dir: str) -> None:
    """Remove transient files that should not be committed."""
    patterns = [
        (os.path.join(project_dir, 'working', 'evaluations'), '.status-*'),
        (os.path.join(project_dir, 'working', 'scores'), '.markers-*'),
    ]
    for base, pattern in patterns:
        if os.path.isdir(base):
            for root, _dirs, files in os.walk(base):
                for f in files:
                    if _matches_glob(f, pattern):
                        os.remove(os.path.join(root, f))

    # Remove non-latest batch request files
    scores_dir = os.path.join(project_dir, 'working', 'scores')
    if os.path.isdir(scores_dir):
        for root, _dirs, files in os.walk(scores_dir):
            if 'latest' in root:
                continue
            for f in files:
                if f == '.batch-requests.jsonl':
                    os.remove(os.path.join(root, f))

    # Remove log files
    logs_dir = os.path.join(project_dir, 'working', 'logs')
    if os.path.isdir(logs_dir):
        for f in os.listdir(logs_dir):
            fp = os.path.join(logs_dir, f)
            if os.path.isfile(fp):
                os.remove(fp)

    # Remove empty dirs
    for d in ('enrich', 'coaching', 'backups', 'scenes-setup'):
        target = os.path.join(project_dir, 'working', d)
        if os.path.isdir(target) and not os.listdir(target):
            os.rmdir(target)


def _matches_glob(filename: str, pattern: str) -> bool:
    """Simple glob match for filename patterns like '.status-*'."""
    import fnmatch
    return fnmatch.fnmatch(filename, pattern)


# ============================================================================
# Legacy files and reorganization
# ============================================================================

def delete_legacy_files(project_dir: str) -> None:
    for f in ('working/pipeline.yaml', 'working/assemble.py'):
        path = os.path.join(project_dir, f)
        if os.path.isfile(path):
            os.remove(path)


def reorganize_loose_files(project_dir: str) -> None:
    recs_dir = os.path.join(project_dir, 'working', 'recommendations')
    os.makedirs(recs_dir, exist_ok=True)
    pattern = os.path.join(project_dir, 'working', 'recommendations*.md')
    for f in glob.glob(pattern):
        if os.path.isfile(f):
            dest = os.path.join(recs_dir, os.path.basename(f))
            if not os.path.exists(dest):
                shutil.move(f, dest)


# ============================================================================
# Pipeline CSV migration
# ============================================================================

def migrate_pipeline_csv(project_dir: str) -> None:
    csv_path = os.path.join(project_dir, 'working', 'pipeline.csv')
    if not os.path.isfile(csv_path):
        return

    with open(csv_path) as f:
        lines = f.readlines()

    if not lines:
        return

    header = lines[0].strip()
    if header == PIPELINE_EXPECTED:
        return

    old_cols = header.split('|')
    exp_cols = PIPELINE_EXPECTED.split('|')
    old_pos = {col: i for i, col in enumerate(old_cols)}

    new_lines = [PIPELINE_EXPECTED + '\n']
    for line in lines[1:]:
        vals = line.strip().split('|')
        new_vals = []
        for col in exp_cols:
            if col in old_pos and old_pos[col] < len(vals):
                new_vals.append(vals[old_pos[col]])
            else:
                new_vals.append('')
        new_lines.append('|'.join(new_vals) + '\n')

    with open(csv_path, 'w') as f:
        f.writelines(new_lines)


# ============================================================================
# Pipeline review deduplication
# ============================================================================

def dedup_pipeline_reviews(project_dir: str) -> None:
    reviews_dir = os.path.join(project_dir, 'working', 'reviews')
    if not os.path.isdir(reviews_dir):
        return

    files = sorted(glob.glob(os.path.join(reviews_dir, 'pipeline-review-*.md')), reverse=True)
    prev_date = ''
    for f in files:
        basename = os.path.basename(f)
        m = re.match(r'pipeline-review-(\d+)-', basename)
        if not m:
            continue
        date = m.group(1)
        if date == prev_date:
            os.remove(f)
        else:
            prev_date = date


# ============================================================================
# storyforge.yaml migration
# ============================================================================

def migrate_storyforge_yaml(project_dir: str) -> None:
    yaml_path = os.path.join(project_dir, 'storyforge.yaml')
    if not os.path.isfile(yaml_path):
        return

    with open(yaml_path) as f:
        content = f.read()

    modified = False

    # Move misplaced chapter_map to under artifacts
    if re.search(r'^chapter_map:', content, re.MULTILINE):
        # Extract values
        block_match = re.search(
            r'^chapter_map:\n((?:  .+\n)*)', content, re.MULTILINE
        )
        if block_match:
            block_text = block_match.group(1)
            cm_exists = ''
            cm_path = ''
            cm_updated = ''
            for line in block_text.splitlines():
                m = re.match(r'\s+exists:\s*(.*)', line)
                if m:
                    cm_exists = m.group(1).strip()
                m = re.match(r'\s+path:\s*(.*)', line)
                if m:
                    cm_path = m.group(1).strip()
                m = re.match(r'\s+updated:\s*(.*)', line)
                if m:
                    cm_updated = m.group(1).strip()

            # Remove top-level chapter_map block
            content = re.sub(r'^chapter_map:\n(?:  .+\n)*', '', content, flags=re.MULTILINE)
            # Remove consecutive blank lines
            content = re.sub(r'\n{3,}', '\n\n', content)

            # Insert under artifacts
            insert_block = (
                f'  chapter_map:\n'
                f'    exists: {cm_exists}\n'
                f'    path: {cm_path}\n'
                f'    updated: {cm_updated}\n'
            )
            content = re.sub(
                r'(^artifacts:\n)',
                r'\1' + insert_block,
                content,
                flags=re.MULTILINE,
            )
            modified = True

    # Add missing sections
    if not re.search(r'^scene_extensions:', content, re.MULTILINE):
        content += '\nscene_extensions: []\n'
        modified = True

    if not re.search(r'^evaluation:', content, re.MULTILINE):
        content += '\nevaluation:\n  custom_evaluators: []\n'
        modified = True

    if not re.search(r'^production:', content, re.MULTILINE) and not re.search(r'^# production:', content, re.MULTILINE):
        content += '\n# production:\n#   author: ""\n#   language: en\n#   scene_break: ornamental\n#   default_heading: numbered-titled\n'
        modified = True

    if not re.search(r'^parts:', content, re.MULTILINE) and not re.search(r'^# parts:', content, re.MULTILINE):
        content += '\n# parts:\n#   - number: 1\n#     title: "Part One"\n'
        modified = True

    # Add missing artifact entries for files on disk
    artifact_files = [
        ('characters', 'reference/characters.csv'),
        ('locations', 'reference/locations.csv'),
        ('threads', 'reference/threads.csv'),
        ('motif_taxonomy', 'reference/motif-taxonomy.csv'),
        ('scene_intent', 'reference/scene-intent.csv'),
        ('title_development', 'reference/title-development.md'),
    ]
    for aid, apath in artifact_files:
        if os.path.isfile(os.path.join(project_dir, apath)):
            if f'  {aid}:' not in content:
                insert = (
                    f'  {aid}:\n'
                    f'    exists: true\n'
                    f'    path: {apath}\n'
                    f'    updated:\n'
                )
                content = re.sub(
                    r'(^artifacts:\n)',
                    r'\1' + insert,
                    content,
                    flags=re.MULTILINE,
                )
                modified = True

    # Fix exists flags based on disk
    def _fix_exists(match):
        block = match.group(0)
        path_match = re.search(r'path:\s*(.+)', block)
        if not path_match:
            return block
        apath = path_match.group(1).strip().strip('"')
        disk_exists = os.path.exists(os.path.join(project_dir, apath))
        if disk_exists:
            block = re.sub(r'exists: false', 'exists: true', block)
        else:
            block = re.sub(r'exists: true', 'exists: false', block)
        return block

    content = re.sub(
        r'^  [a-z_]+:\n(?:    (?:exists|path|updated):.*\n)+',
        _fix_exists,
        content,
        flags=re.MULTILINE,
    )
    modified = True

    if modified:
        with open(yaml_path, 'w') as f:
            f.write(content)


# ============================================================================
# CSV Schema Report
# ============================================================================

def report_csv_schema(project_dir: str) -> list[str]:
    """Check all expected CSV files for existence and column completeness.

    Returns a list of issue strings (MISSING_CSV, MISSING_COLUMN, EXTRA_COLUMN).
    """
    issues = []

    for rel_path, expected_cols in EXPECTED_CSV_SCHEMAS.items():
        csv_path = os.path.join(project_dir, rel_path)

        if not os.path.isfile(csv_path):
            issues.append(f'MISSING_CSV:{rel_path}')
            continue

        with open(csv_path) as f:
            first_line = f.readline().strip()

        if not first_line:
            issues.append(f'EMPTY_CSV:{rel_path}')
            continue

        actual_cols = [c.strip() for c in first_line.split('|')]
        expected_set = set(expected_cols)
        actual_set = set(actual_cols)

        for col in expected_cols:
            if col not in actual_set:
                issues.append(f'MISSING_COLUMN:{rel_path}:{col}')

        for col in actual_cols:
            if col not in expected_set:
                issues.append(f'EXTRA_COLUMN:{rel_path}:{col}')

    return issues


# ============================================================================
# CSV Integrity Report
# ============================================================================

def report_csv_integrity(project_dir: str) -> list[str]:
    """Check CSV integrity. Returns list of issue strings."""
    issues = []
    meta_csv = os.path.join(project_dir, 'reference', 'scenes.csv')
    intent_csv = os.path.join(project_dir, 'reference', 'scene-intent.csv')
    chapter_csv = os.path.join(project_dir, 'reference', 'chapter-map.csv')
    chars_csv = os.path.join(project_dir, 'reference', 'characters.csv')
    scenes_dir = os.path.join(project_dir, 'scenes')

    def _read_ids(csv_path):
        if not os.path.isfile(csv_path):
            return set()
        with open(csv_path) as f:
            lines = f.readlines()
        return {line.split('|')[0].strip() for line in lines[1:] if line.strip()}

    # Scene files vs metadata
    if os.path.isfile(meta_csv) and os.path.isdir(scenes_dir):
        meta_ids = _read_ids(meta_csv)
        file_ids = set()
        for f in os.listdir(scenes_dir):
            if f.endswith('.md'):
                file_ids.add(f[:-3])
        for fid in sorted(file_ids - meta_ids):
            issues.append(f'ORPHAN_FILE:{fid}')
        for mid in sorted(meta_ids - file_ids):
            issues.append(f'ORPHAN_META:{mid}')

    # Metadata vs intent
    if os.path.isfile(meta_csv) and os.path.isfile(intent_csv):
        meta_ids = _read_ids(meta_csv)
        intent_ids = _read_ids(intent_csv)
        for mid in sorted(meta_ids - intent_ids):
            issues.append(f'MISSING_INTENT:{mid}')
        for iid in sorted(intent_ids - meta_ids):
            issues.append(f'EXTRA_INTENT:{iid}')

    # Chapter map references
    if os.path.isfile(chapter_csv) and os.path.isfile(meta_csv):
        meta_ids = _read_ids(meta_csv)
        with open(chapter_csv) as f:
            lines = f.readlines()
        for line in lines[1:]:
            parts = line.strip().split('|')
            if len(parts) > 4:
                for sid in parts[4].split(';'):
                    sid = sid.strip()
                    if sid and sid not in meta_ids:
                        issues.append(f'BAD_CHAPTER_REF:{sid}')

    # Sequence gaps
    if os.path.isfile(meta_csv):
        with open(meta_csv) as f:
            lines = f.readlines()
        seqs = []
        for line in lines[1:]:
            parts = line.strip().split('|')
            if len(parts) > 1 and parts[1].strip():
                seqs.append(parts[1].strip())
        needs_renumber = False
        prev = 0
        for s in sorted(seqs, key=lambda x: float(x) if re.match(r'^[\d.]+$', x) else 0):
            if '.' in s:
                needs_renumber = True
            elif s.isdigit():
                val = int(s)
                if val > prev + 1:
                    needs_renumber = True
                prev = val
        if needs_renumber:
            issues.append('SEQ_NEEDS_RENUMBER:gaps or non-integer seq values found')

    # Unknown characters
    if os.path.isfile(intent_csv) and os.path.isfile(chars_csv):
        with open(chars_csv) as f:
            clines = f.readlines()
        known = set()
        for line in clines[1:]:
            parts = line.strip().split('|')
            for i in (1, 2):
                if i < len(parts):
                    for name in parts[i].split(';'):
                        name = name.strip()
                        if name:
                            known.add(name)

        with open(intent_csv) as f:
            ilines = f.readlines()
        header = ilines[0].strip().split('|') if ilines else []
        char_idx = header.index('characters') if 'characters' in header else -1
        used = set()
        if char_idx >= 0:
            for line in ilines[1:]:
                parts = line.strip().split('|')
                if char_idx < len(parts):
                    for name in parts[char_idx].split(';'):
                        name = name.strip()
                        if name:
                            used.add(name)
        for name in sorted(used - known):
            issues.append(f'UNKNOWN_CHARACTER:{name}')

    return issues


# ============================================================================
# Unexpected Files Report
# ============================================================================

def report_unexpected_files(project_dir: str) -> list[str]:
    """Report unexpected files and directories. Returns list of issue strings."""
    issues = []

    # Top-level dirs
    for entry in sorted(os.listdir(project_dir)):
        path = os.path.join(project_dir, entry)
        if os.path.isdir(path) and entry not in EXPECTED_TOP_DIRS:
            issues.append(f'UNEXPECTED_DIR:{entry}')
        elif os.path.isfile(path) and entry not in EXPECTED_TOP_FILES:
            issues.append(f'UNEXPECTED_FILE:{entry}')

    # Working subdirs
    working = os.path.join(project_dir, 'working')
    if os.path.isdir(working):
        for entry in sorted(os.listdir(working)):
            path = os.path.join(working, entry)
            if os.path.isdir(path) and entry not in EXPECTED_WORKING_DIRS:
                issues.append(f'UNEXPECTED_DIR:working/{entry}')
            elif os.path.isfile(path) and entry not in EXPECTED_WORKING_FILES:
                issues.append(f'UNEXPECTED_FILE:working/{entry}')

    return issues


# ============================================================================
# Scene file cleanup
# ============================================================================

def clean_scene_files(project_dir: str, dry_run: bool = False,
                      verbose: bool = False) -> int:
    """Strip writing-agent artifacts from scene files.

    Removes scene markers (=== SCENE: id ===), leading H1/H2 title headers,
    and trailing Continuity Tracker Update blocks from all scene files.

    Returns the number of files that were (or would be) modified.
    """
    scenes_dir = os.path.join(project_dir, 'scenes')
    if not os.path.isdir(scenes_dir):
        return 0

    changed = 0
    for filename in sorted(os.listdir(scenes_dir)):
        if not filename.endswith('.md'):
            continue
        filepath = os.path.join(scenes_dir, filename)
        with open(filepath, encoding='utf-8') as f:
            original = f.read()

        cleaned = original
        # Strip === SCENE: id === / === END SCENE: id === markers
        extracted = extract_single_scene(cleaned)
        if extracted is not None:
            cleaned = extracted
        # Strip title headers and continuity tracker blocks
        cleaned = clean_scene_content(cleaned)

        if cleaned != original:
            changed += 1
            if verbose or dry_run:
                log(f'  {"Would clean" if dry_run else "Cleaned"}: {filename}')
            if not dry_run:
                with open(filepath, 'w', encoding='utf-8') as f:
                    f.write(cleaned)

    return changed


# ============================================================================
# Argument parsing
# ============================================================================

def parse_args(argv):
    parser = argparse.ArgumentParser(
        prog='storyforge cleanup',
        description='Clean up and migrate a Storyforge novel project.',
    )
    parser.add_argument('--dry-run', action='store_true',
                        help='Report what would change without modifying anything')
    parser.add_argument('--verbose', action='store_true',
                        help='Detailed output for each step')
    parser.add_argument('--scenes', action='store_true',
                        help='Strip writing-agent artifacts (title headers, '
                             'continuity blocks, scene markers) from scene files')
    parser.add_argument('--csv', action='store_true',
                        help='Run only the CSV integrity report (schema '
                             'validation, row checks, unexpected files)')
    return parser.parse_args(argv)


# ============================================================================
# Main
# ============================================================================

def _classify_issue(issue: str, rename_pairs: dict[str, list[tuple[str, str]]]) -> dict | None:
    """Convert a raw issue string into a structured finding dict.

    Returns None for issues that should be suppressed (e.g. the EXTRA_COLUMN
    side of a rename pair).

    Each dict has: type, file, detail, action, command (optional), severity.
    - severity: 'error' (breaks pipeline), 'warning' (should fix),
                'info' (informational only)
    """
    if issue.startswith('MISSING_CSV:'):
        path = issue.split(':', 1)[1]
        if path.startswith('working/'):
            return {
                'type': 'missing_csv', 'file': path,
                'detail': f'{path} does not exist',
                'action': 'Will be created automatically on first use',
                'severity': 'info',
            }
        return {
            'type': 'missing_csv', 'file': path,
            'detail': f'{path} does not exist',
            'action': f'Copy from templates/ or run storyforge elaborate',
            'command': f'cp templates/{path.removeprefix("reference/")} {path}',
            'severity': 'warning',
        }

    if issue.startswith('EMPTY_CSV:'):
        path = issue.split(':', 1)[1]
        return {
            'type': 'empty_csv', 'file': path,
            'detail': f'{path} is empty (no header row)',
            'action': 'Restore header from templates/',
            'severity': 'error',
        }

    if issue.startswith('MISSING_COLUMN:'):
        _, path, col = issue.split(':', 2)
        pairs = rename_pairs.get(path, [])
        for missing, extra in pairs:
            if col == missing:
                return {
                    'type': 'rename_column', 'file': path,
                    'detail': f'Column "{extra}" should be "{missing}"',
                    'action': f'Rename column "{extra}" to "{missing}" in header',
                    'rename_from': extra, 'rename_to': missing,
                    'severity': 'warning',
                }
        return {
            'type': 'missing_column', 'file': path, 'column': col,
            'detail': f'{path} is missing column "{col}"',
            'action': f'Add "{col}" to header and empty values to existing rows',
            'severity': 'warning',
        }

    if issue.startswith('EXTRA_COLUMN:'):
        _, path, col = issue.split(':', 2)
        pairs = rename_pairs.get(path, [])
        for missing, extra in pairs:
            if col == extra:
                return None  # Covered by the rename_column finding
        return {
            'type': 'extra_column', 'file': path, 'column': col,
            'detail': f'{path} has unexpected column "{col}"',
            'action': f'Verify if "{col}" should be removed or added to schema',
            'severity': 'info',
        }

    if issue.startswith('ORPHAN_FILE:'):
        sid = issue.split(':', 1)[1]
        return {
            'type': 'orphan_file', 'file': f'scenes/{sid}.md', 'scene_id': sid,
            'detail': f'scenes/{sid}.md has no metadata row',
            'action': 'Extract metadata or remove scene file',
            'command': f'storyforge extract --scenes {sid}',
            'severity': 'warning',
        }

    if issue.startswith('ORPHAN_META:'):
        sid = issue.split(':', 1)[1]
        return {
            'type': 'orphan_meta', 'file': 'reference/scenes.csv',
            'scene_id': sid,
            'detail': f'"{sid}" has metadata but no scene file',
            'action': f'Remove rows for "{sid}" from CSVs or create scenes/{sid}.md',
            'severity': 'warning',
        }

    if issue.startswith('MISSING_INTENT:'):
        sid = issue.split(':', 1)[1]
        return {
            'type': 'missing_intent', 'file': 'reference/scene-intent.csv',
            'scene_id': sid,
            'detail': f'"{sid}" is in scenes.csv but not scene-intent.csv',
            'action': 'Fill intent gaps',
            'command': 'storyforge hone --domain gaps',
            'severity': 'warning',
        }

    if issue.startswith('EXTRA_INTENT:'):
        sid = issue.split(':', 1)[1]
        return {
            'type': 'extra_intent', 'file': 'reference/scene-intent.csv',
            'scene_id': sid,
            'detail': f'"{sid}" is in scene-intent.csv but not scenes.csv',
            'action': f'Remove the row from scene-intent.csv or add "{sid}" to scenes.csv',
            'severity': 'warning',
        }

    if issue.startswith('BAD_CHAPTER_REF:'):
        sid = issue.split(':', 1)[1]
        return {
            'type': 'bad_chapter_ref', 'file': 'reference/chapter-map.csv',
            'scene_id': sid,
            'detail': f'chapter-map.csv references "{sid}" which doesn\'t exist',
            'action': 'Update the chapter map to remove or replace the reference',
            'severity': 'error',
        }

    if issue.startswith('SEQ_NEEDS_RENUMBER:'):
        return {
            'type': 'seq_needs_renumber', 'file': 'reference/scenes.csv',
            'detail': 'Sequence has gaps or non-integer values',
            'action': 'Renumber scene sequences',
            'command': 'storyforge scenes-setup --renumber',
            'severity': 'warning',
        }

    if issue.startswith('UNKNOWN_CHARACTER:'):
        name = issue.split(':', 1)[1]
        return {
            'type': 'unknown_character', 'file': 'reference/characters.csv',
            'character': name,
            'detail': f'"{name}" appears in scene-intent.csv but not characters.csv',
            'action': 'Normalize character registries',
            'command': 'storyforge hone --domain registries',
            'severity': 'warning',
        }

    if issue.startswith('UNEXPECTED_DIR:'):
        path = issue.split(':', 1)[1]
        return {
            'type': 'unexpected_dir', 'file': path,
            'detail': f'{path}/ is not expected',
            'action': 'Review manually; may be leftover from an old version',
            'severity': 'info',
        }

    if issue.startswith('UNEXPECTED_FILE:'):
        path = issue.split(':', 1)[1]
        return {
            'type': 'unexpected_file', 'file': path,
            'detail': f'{path} is not expected',
            'action': 'Review manually; may be leftover from an old version',
            'severity': 'info',
        }

    return {'type': 'unknown', 'detail': issue, 'action': issue, 'severity': 'info'}


def _detect_rename_pairs(issues: list[str]) -> dict[str, list[tuple[str, str]]]:
    """Detect MISSING_COLUMN + EXTRA_COLUMN on the same file as rename candidates.

    Returns {path: [(missing_col, extra_col), ...]} for files where the count
    of missing and extra columns match (suggesting renames rather than
    additions/deletions).
    """
    from collections import defaultdict
    missing: dict[str, list[str]] = defaultdict(list)
    extra: dict[str, list[str]] = defaultdict(list)

    for issue in issues:
        if issue.startswith('MISSING_COLUMN:'):
            _, path, col = issue.split(':', 2)
            missing[path].append(col)
        elif issue.startswith('EXTRA_COLUMN:'):
            _, path, col = issue.split(':', 2)
            extra[path].append(col)

    pairs: dict[str, list[tuple[str, str]]] = {}
    for path in missing:
        if path in extra and len(missing[path]) == len(extra[path]):
            pairs[path] = list(zip(missing[path], extra[path]))
    return pairs


def _check_scene_artifacts(project_dir: str) -> list[dict]:
    """Check scene files for writing-agent artifacts without modifying them.

    Returns a list of finding dicts for scenes that need cleaning.
    """
    scenes_dir = os.path.join(project_dir, 'scenes')
    if not os.path.isdir(scenes_dir):
        return []

    findings: list[dict] = []
    dirty_count = 0
    for filename in sorted(os.listdir(scenes_dir)):
        if not filename.endswith('.md'):
            continue
        filepath = os.path.join(scenes_dir, filename)
        with open(filepath, encoding='utf-8') as f:
            original = f.read()

        cleaned = original
        extracted = extract_single_scene(cleaned)
        if extracted is not None:
            cleaned = extracted
        cleaned = clean_scene_content(cleaned)

        if cleaned != original:
            dirty_count += 1

    if dirty_count > 0:
        findings.append({
            'type': 'scene_artifacts', 'file': 'scenes/',
            'category': 'scenes',
            'detail': f'{dirty_count} scene file(s) contain writing-agent artifacts '
                      f'(title headers, continuity blocks, or scene markers)',
            'action': 'Strip artifacts from scene files',
            'command': 'storyforge cleanup --scenes',
            'severity': 'warning',
        })
    return findings


def _check_crlf(project_dir: str) -> list[dict]:
    """Check CSV files for CRLF line endings."""
    findings: list[dict] = []
    dirty_files: list[str] = []
    for rel_path in EXPECTED_CSV_SCHEMAS:
        csv_path = os.path.join(project_dir, rel_path)
        if not os.path.isfile(csv_path):
            continue
        with open(csv_path, 'rb') as f:
            if b'\r\n' in f.read():
                dirty_files.append(rel_path)

    if dirty_files:
        findings.append({
            'type': 'crlf_line_endings', 'file': '; '.join(dirty_files),
            'category': 'structure',
            'detail': f'{len(dirty_files)} CSV file(s) have CRLF line endings: '
                      f'{", ".join(dirty_files[:5])}'
                      f'{"..." if len(dirty_files) > 5 else ""}',
            'action': 'Normalize line endings to LF',
            'command': "find reference working -name '*.csv' -exec sed -i '' $'s/\\r$//' {} +",
            'severity': 'warning',
        })
    return findings


def build_cleanup_report(project_dir: str) -> dict:
    """Build a full structured cleanup report covering all checks.

    Returns a dict with:
        findings: list of finding dicts (type, file, detail, action, severity, category, ...)
        action_items: list of actionable finding dicts (severity != 'info')
        summary: dict with counts by severity and category
    """
    all_findings: list[dict] = []

    # --- Structure checks ---
    # Missing directories
    for d in EXPECTED_DIRS:
        if not os.path.isdir(os.path.join(project_dir, d)):
            all_findings.append({
                'type': 'missing_dir', 'file': d,
                'category': 'structure',
                'detail': f'{d}/ does not exist',
                'action': f'Created by storyforge cleanup',
                'severity': 'info',
            })

    # storyforge.yaml
    yaml_path = os.path.join(project_dir, 'storyforge.yaml')
    if not os.path.isfile(yaml_path):
        all_findings.append({
            'type': 'missing_yaml', 'file': 'storyforge.yaml',
            'category': 'structure',
            'detail': 'storyforge.yaml not found',
            'action': 'Initialize with storyforge init or create manually',
            'command': 'storyforge init',
            'severity': 'error',
        })

    # CRLF check
    all_findings.extend(_check_crlf(project_dir))

    # --- Scene artifacts ---
    all_findings.extend(_check_scene_artifacts(project_dir))

    # --- CSV schema ---
    schema_issues = report_csv_schema(project_dir)
    rename_pairs = _detect_rename_pairs(schema_issues)
    for issue in schema_issues:
        finding = _classify_issue(issue, rename_pairs)
        if finding:
            finding['category'] = 'schema'
            all_findings.append(finding)

    # --- CSV row integrity ---
    for issue in report_csv_integrity(project_dir):
        finding = _classify_issue(issue, {})
        if finding:
            finding['category'] = 'integrity'
            all_findings.append(finding)

    # --- Unexpected files ---
    for issue in report_unexpected_files(project_dir):
        finding = _classify_issue(issue, {})
        if finding:
            finding['category'] = 'unexpected'
            all_findings.append(finding)

    # Set default status on all findings
    for f in all_findings:
        if 'status' not in f:
            f['status'] = 'pending' if f['severity'] != 'info' else ''

    action_items = [f for f in all_findings if f['severity'] != 'info']

    return {
        'findings': all_findings,
        'action_items': action_items,
        'summary': {
            'total': len(all_findings),
            'errors': sum(1 for f in all_findings if f['severity'] == 'error'),
            'warnings': sum(1 for f in all_findings if f['severity'] == 'warning'),
            'info': sum(1 for f in all_findings if f['severity'] == 'info'),
        },
    }


def _print_report(report: dict) -> None:
    """Print a human-readable report to stdout via log()."""
    findings = report['findings']
    action_items = report['action_items']
    summary = report['summary']

    # Group by category for display
    categories = [
        ('structure', 'Project Structure'),
        ('scenes', 'Scene Files'),
        ('schema', 'CSV Schema'),
        ('integrity', 'CSV Integrity'),
        ('unexpected', 'Unexpected Files'),
    ]
    for category, heading in categories:
        group = [f for f in findings if f.get('category') == category]
        if not group:
            continue
        log(f'=== {heading} ===')
        for f in group:
            severity_tag = f'[{f["severity"].upper()}]'
            log(f'  {severity_tag} {f["detail"]}')
            log(f'         → {f["action"]}')
            if 'command' in f:
                log(f'           $ {f["command"]}')
        log('')

    # Action items summary
    if action_items:
        log(f'=== Action Items ({len(action_items)}) ===')
        for i, item in enumerate(action_items, 1):
            if 'command' in item:
                log(f'  {i}. {item["action"]}  →  {item["command"]}')
            else:
                log(f'  {i}. {item["detail"]}: {item["action"]}')
    else:
        log('=== No action items — project is clean ===')

    log('')
    log(f'Summary: {summary["errors"]} error(s), '
        f'{summary["warnings"]} warning(s), {summary["info"]} info')


REPORT_COLUMNS = ['category', 'type', 'severity', 'file', 'detail', 'action', 'command', 'status']


def _write_report(report: dict, project_dir: str) -> str:
    """Write the report as pipe-delimited CSV to working/cleanup-report.csv.

    Returns the path to the written file.
    """
    working_dir = os.path.join(project_dir, 'working')
    os.makedirs(working_dir, exist_ok=True)
    report_path = os.path.join(working_dir, 'cleanup-report.csv')
    with open(report_path, 'w') as f:
        f.write('|'.join(REPORT_COLUMNS) + '\n')
        for finding in report['findings']:
            row = [finding.get(col, '') for col in REPORT_COLUMNS]
            f.write('|'.join(row) + '\n')
    return report_path


def _run_and_write_report(project_dir: str) -> None:
    """Build the full cleanup report, print it, and write JSON."""
    report = build_cleanup_report(project_dir)
    _print_report(report)
    report_path = _write_report(report, project_dir)
    log(f'Report written to {report_path}')


def main(argv=None):
    args = parse_args(argv or [])
    project_dir = detect_project_root()
    log(f'Project root: {project_dir}')

    # --csv: run only the report and exit (no modifications)
    if args.csv:
        _run_and_write_report(project_dir)
        log('')
        log('Check complete.')
        return

    def vlog(msg):
        if args.verbose:
            log(msg)

    if args.dry_run:
        log('=== DRY RUN — no changes will be made ===')
    else:
        ensure_on_branch('cleanup', project_dir)

    # Step 1: Gitignore
    log('Checking .gitignore...')
    if args.dry_run:
        tmp_dir = tempfile.mkdtemp()
        src = os.path.join(project_dir, '.gitignore')
        dst = os.path.join(tmp_dir, '.gitignore')
        if os.path.isfile(src):
            shutil.copy2(src, dst)
        else:
            with open(dst, 'w') as f:
                pass
        update_gitignore(tmp_dir)
        import filecmp
        if not os.path.isfile(src) or not filecmp.cmp(src, dst):
            log('  Would update .gitignore with missing entries')
        shutil.rmtree(tmp_dir)
    else:
        update_gitignore(project_dir)
        git_dir = os.path.join(project_dir, '.git')
        if shutil.which('git') and os.path.isdir(git_dir):
            r = subprocess.run(
                ['git', '-C', project_dir, 'ls-files', '-i', '--exclude-standard'],
                capture_output=True, text=True,
            )
            tracked = r.stdout.strip()
            if tracked:
                count = len(tracked.splitlines())
                log(f'  Untracking {count} newly-gitignored files')
                for f in tracked.splitlines():
                    subprocess.run(
                        ['git', '-C', project_dir, 'rm', '--cached', '-q', f],
                        capture_output=True,
                    )

    # Step 2: Missing directories
    log('Checking directories...')
    if args.dry_run:
        for d in EXPECTED_DIRS:
            if not os.path.isdir(os.path.join(project_dir, d)):
                log(f'  Would create {d}/')
    else:
        created = create_missing_dirs(project_dir)
        for d in created:
            vlog(f'  Created {d}/')

    # Step 3: storyforge.yaml migration
    log('Checking storyforge.yaml...')
    if args.dry_run:
        tmp_dir = tempfile.mkdtemp()
        yaml_src = os.path.join(project_dir, 'storyforge.yaml')
        if os.path.isfile(yaml_src):
            shutil.copy2(yaml_src, os.path.join(tmp_dir, 'storyforge.yaml'))
            ref_src = os.path.join(project_dir, 'reference')
            ref_dst = os.path.join(tmp_dir, 'reference')
            if os.path.isdir(ref_src):
                shutil.copytree(ref_src, ref_dst)
            migrate_storyforge_yaml(tmp_dir)
            import filecmp
            if not filecmp.cmp(yaml_src, os.path.join(tmp_dir, 'storyforge.yaml')):
                log('  Would migrate storyforge.yaml (missing sections, artifact flags)')
        shutil.rmtree(tmp_dir)
    else:
        migrate_storyforge_yaml(project_dir)

    # Step 4: Pipeline CSV
    log('Checking pipeline.csv...')
    if args.dry_run:
        csv_path = os.path.join(project_dir, 'working', 'pipeline.csv')
        if os.path.isfile(csv_path):
            with open(csv_path) as f:
                header = f.readline().strip()
            if header != PIPELINE_EXPECTED:
                log('  Would add missing columns to pipeline.csv')
    else:
        migrate_pipeline_csv(project_dir)

    # Step 5: Junk files
    log('Cleaning junk files...')
    if args.dry_run:
        for base, pattern in [
            ('working/evaluations', '.status-*'),
            ('working/scores', '.markers-*'),
        ]:
            base_path = os.path.join(project_dir, base)
            if os.path.isdir(base_path):
                count = 0
                for root, _dirs, files in os.walk(base_path):
                    count += sum(1 for f in files if _matches_glob(f, pattern))
                if count > 0:
                    log(f'  Would remove {count} {pattern} files')

        scores_dir = os.path.join(project_dir, 'working', 'scores')
        if os.path.isdir(scores_dir):
            count = 0
            for root, _dirs, files in os.walk(scores_dir):
                if 'latest' not in root:
                    count += sum(1 for f in files if f == '.batch-requests.jsonl')
            if count > 0:
                log(f'  Would remove {count} .batch-requests.jsonl files')

        logs_dir = os.path.join(project_dir, 'working', 'logs')
        if os.path.isdir(logs_dir):
            count = sum(1 for f in os.listdir(logs_dir) if os.path.isfile(os.path.join(logs_dir, f)))
            if count > 0:
                log(f'  Would remove {count} log files')
    else:
        clean_junk_files(project_dir)

    # Step 6: Legacy files
    log('Checking legacy files...')
    if args.dry_run:
        for f in ('working/pipeline.yaml', 'working/assemble.py'):
            if os.path.isfile(os.path.join(project_dir, f)):
                log(f'  Would delete {f}')
    else:
        delete_legacy_files(project_dir)

    # Step 7: Reorganize loose files
    log('Reorganizing loose files...')
    if args.dry_run:
        pattern = os.path.join(project_dir, 'working', 'recommendations*.md')
        count = len(glob.glob(pattern))
        if count > 0:
            log(f'  Would move {count} recommendation files to working/recommendations/')
    else:
        reorganize_loose_files(project_dir)

    # Step 8: Pipeline review dedup
    log('Deduplicating pipeline reviews...')
    if args.dry_run:
        log('  Would deduplicate pipeline reviews (keep latest per day)')
    else:
        dedup_pipeline_reviews(project_dir)

    # Step 9: Scene file cleanup (only with --scenes)
    if args.scenes:
        log('Cleaning scene files...')
        cleaned = clean_scene_files(project_dir, dry_run=args.dry_run,
                                    verbose=args.verbose)
        if cleaned:
            log(f'  {"Would clean" if args.dry_run else "Cleaned"} {cleaned} scene file(s)')
        else:
            log('  All scene files are clean.')

    # Steps 10-12: Full report
    log('')
    _run_and_write_report(project_dir)

    # Step 13: Commit (unless dry-run)
    if not args.dry_run:
        git_dir = os.path.join(project_dir, '.git')
        if shutil.which('git') and os.path.isdir(git_dir):
            r = subprocess.run(
                ['git', '-C', project_dir, 'status', '--porcelain'],
                capture_output=True, text=True,
            )
            if r.stdout.strip():
                log('')
                log('Committing changes...')
                committed = commit_and_push(
                    project_dir,
                    'Cleanup: project structure and working files',
                )
                if not committed:
                    log('WARNING: git commit or push may have failed')
            else:
                log('No changes to commit.')

    log('')
    log('Cleanup complete.')
