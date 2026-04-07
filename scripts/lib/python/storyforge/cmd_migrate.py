"""storyforge migrate — Upgrade existing projects to normalized registry model.

One-time migration that:
  1. Renames scene_type -> action_sequel in scene-intent.csv
  2. Removes the threads column from scene-intent.csv
  3. Seeds new registry files (values.csv, knowledge.csv, mice-threads.csv)
  4. Normalizes all registry-backed fields to canonical IDs
  5. Runs schema validation to show remaining issues

Idempotent — safe to run multiple times.

Usage:
    storyforge migrate                  # Full migration + commit
    storyforge migrate --dry-run        # Show what would change
    storyforge migrate --no-commit      # Make changes but don't commit
"""

import argparse
import os
import re
import sys

from storyforge.common import detect_project_root, log, read_yaml_field
from storyforge.git import commit_and_push


# ============================================================================
# Helpers
# ============================================================================

def _read_csv(path: str) -> tuple[list[str], list[dict]]:
    """Read a pipe-delimited CSV. Returns (header_fields, rows_as_dicts)."""
    if not os.path.isfile(path):
        return [], []
    with open(path, encoding='utf-8') as f:
        lines = [l.rstrip('\n') for l in f if l.strip()]
    if not lines:
        return [], []
    header = lines[0].split('|')
    rows = [dict(zip(header, l.split('|'))) for l in lines[1:]]
    return header, rows


def _slugify(text: str) -> str:
    s = text.strip().lower()
    s = re.sub(r'[^a-z0-9\s-]', '', s)
    s = re.sub(r'[\s]+', '-', s)
    s = re.sub(r'-+', '-', s)
    return s.strip('-')


def _write_registry(path: str, header_str: str, rows: list[str]) -> None:
    with open(path, 'w', encoding='utf-8') as f:
        f.write(header_str + '\n')
        for row in rows:
            f.write(row + '\n')


# ============================================================================
# Step 1: Rename scene_type -> action_sequel
# ============================================================================

def step1_rename_scene_type(ref_dir: str, dry_run: bool) -> str:
    intent_path = os.path.join(ref_dir, 'scene-intent.csv')
    if not os.path.isfile(intent_path):
        return 'skip:no scene-intent.csv'

    with open(intent_path, encoding='utf-8') as f:
        lines = f.readlines()
    if not lines:
        return 'skip:empty file'

    header = lines[0]
    if 'scene_type' not in header:
        return 'skip:already renamed'

    lines[0] = header.replace('scene_type', 'action_sequel')
    count = len(lines) - 1

    if not dry_run:
        with open(intent_path, 'w', encoding='utf-8') as f:
            f.writelines(lines)

    return f'done:{count}'


# ============================================================================
# Step 2: Remove threads column
# ============================================================================

def step2_remove_threads(ref_dir: str, dry_run: bool) -> str:
    intent_path = os.path.join(ref_dir, 'scene-intent.csv')
    if not os.path.isfile(intent_path):
        return 'skip:no scene-intent.csv'

    with open(intent_path, encoding='utf-8') as f:
        lines = f.readlines()
    if not lines:
        return 'skip:empty file'

    header_fields = lines[0].rstrip('\n').split('|')
    if 'threads' not in header_fields:
        return 'skip:already removed'

    threads_idx = header_fields.index('threads')
    new_lines = []
    for line in lines:
        fields = line.rstrip('\n').split('|')
        if len(fields) > threads_idx:
            fields.pop(threads_idx)
        new_lines.append('|'.join(fields) + '\n')

    count = len(new_lines) - 1

    if not dry_run:
        with open(intent_path, 'w', encoding='utf-8') as f:
            f.writelines(new_lines)

    return f'done:{count}'


# ============================================================================
# Step 3: Seed registries
# ============================================================================

def step3_seed_registries(ref_dir: str, dry_run: bool) -> list[str]:
    """Seed values.csv, mice-threads.csv, knowledge.csv from scene data.
    Returns list of 'registry:action:detail' strings."""
    results = []

    # --- values.csv ---
    results.append(_seed_values(ref_dir, dry_run))

    # --- mice-threads.csv ---
    results.append(_seed_mice_threads(ref_dir, dry_run))

    # --- knowledge.csv ---
    results.append(_seed_knowledge(ref_dir, dry_run))

    return results


def _seed_values(ref_dir: str, dry_run: bool) -> str:
    values_path = os.path.join(ref_dir, 'values.csv')
    if os.path.isfile(values_path):
        with open(values_path) as f:
            existing = [l.strip() for l in f if l.strip()]
        if len(existing) > 1:
            return f'values.csv:skip:already exists ({len(existing)-1} entries)'

    _, intent_rows = _read_csv(os.path.join(ref_dir, 'scene-intent.csv'))
    values = set()
    for r in intent_rows:
        v = r.get('value_at_stake', '').strip()
        if v:
            values.add(v)

    if values and not dry_run:
        rows = []
        for v in sorted(values):
            sid = _slugify(v)
            rows.append(f'{sid}|{v}|')
        _write_registry(values_path, 'id|name|aliases', rows)

    return f'values.csv:done:{len(values)}'


def _seed_mice_threads(ref_dir: str, dry_run: bool) -> str:
    mice_path = os.path.join(ref_dir, 'mice-threads.csv')
    if os.path.isfile(mice_path):
        with open(mice_path) as f:
            existing = [l.strip() for l in f if l.strip()]
        if len(existing) > 1:
            return f'mice-threads.csv:skip:already exists ({len(existing)-1} entries)'

    _, intent_rows = _read_csv(os.path.join(ref_dir, 'scene-intent.csv'))
    threads = {}  # name -> type
    for r in intent_rows:
        mice = r.get('mice_threads', '').strip()
        if not mice:
            continue
        for entry in mice.split(';'):
            entry = entry.strip()
            if len(entry) > 1 and entry[0] in ('+', '-') and ':' in entry[1:]:
                rest = entry[1:]
                type_part, _, name_part = rest.partition(':')
                type_part = type_part.strip().lower()
                name_part = name_part.strip()
                if name_part and name_part not in threads:
                    threads[name_part] = type_part

    if threads and not dry_run:
        rows = []
        for name in sorted(threads.keys()):
            t = threads[name]
            rows.append(f'{name}|{name}|{t}|')
        _write_registry(mice_path, 'id|name|type|aliases', rows)

    return f'mice-threads.csv:done:{len(threads)}'


def _seed_knowledge(ref_dir: str, dry_run: bool) -> str:
    knowledge_path = os.path.join(ref_dir, 'knowledge.csv')
    if os.path.isfile(knowledge_path):
        with open(knowledge_path) as f:
            existing = [l.strip() for l in f if l.strip()]
        if len(existing) > 1:
            return f'knowledge.csv:skip:already exists ({len(existing)-1} entries)'

    _, briefs_rows = _read_csv(os.path.join(ref_dir, 'scene-briefs.csv'))
    facts = set()
    for r in briefs_rows:
        for field in ('knowledge_in', 'knowledge_out'):
            v = r.get(field, '').strip()
            if v:
                for fact in v.split(';'):
                    fact = fact.strip()
                    if fact:
                        facts.add(fact)

    if facts and not dry_run:
        rows = []
        for fact in sorted(facts):
            sid = _slugify(fact)
            if not sid:
                continue
            rows.append(f'{sid}|{fact}|')
        _write_registry(knowledge_path, 'id|name|aliases', rows)

    return f'knowledge.csv:done:{len(facts)}'


# ============================================================================
# Step 4: Normalize all fields
# ============================================================================

def step4_normalize(ref_dir: str, project_dir: str) -> int:
    """Normalize registry-backed fields. Returns count of updated cells."""
    from storyforge.elaborate import _read_csv as elab_read_csv, _write_csv, _FILE_MAP
    from storyforge.enrich import load_registry_alias_maps, normalize_fields

    alias_maps = load_registry_alias_maps(project_dir)
    updated = 0

    for filename, columns in _FILE_MAP.items():
        path = os.path.join(ref_dir, filename)
        if not os.path.isfile(path):
            continue

        rows = elab_read_csv(path)
        changed = False

        for row in rows:
            original = dict(row)
            normalize_fields(row, alias_maps)
            if row != original:
                changed = True
                for k in row:
                    if row[k] != original.get(k, ''):
                        updated += 1

        if changed:
            _write_csv(path, rows, columns)

    return updated


# ============================================================================
# Step 5: Validate
# ============================================================================

def step5_validate(ref_dir: str, project_dir: str) -> str:
    """Run schema validation. Returns formatted result string."""
    from storyforge.schema import validate_schema

    report = validate_schema(ref_dir, project_dir)
    passed = report['passed']
    failed = report['failed']
    skipped = report['skipped']

    lines = [f'{passed} passed, {failed} failed, {skipped} skipped']

    if report['errors']:
        by_file = {}
        for e in report['errors']:
            by_file.setdefault(e['file'], []).append(e)
        for fname, errs in sorted(by_file.items()):
            lines.append(f'  {fname}:')
            for e in errs:
                if e['constraint'] == 'enum':
                    allowed = ', '.join(e['allowed'])
                    lines.append(f'    {e["row"]} | {e["column"]}: "{e["value"]}" — not in ({allowed})')
                elif e['constraint'] == 'registry':
                    unresolved = ', '.join(e.get('unresolved', [e['value']]))
                    lines.append(f'    {e["row"]} | {e["column"]}: "{unresolved}" — not in {e["registry"]}')
                elif e['constraint'] == 'integer':
                    lines.append(f'    {e["row"]} | {e["column"]}: "{e["value"]}" — expected integer')
                elif e['constraint'] == 'boolean':
                    lines.append(f'    {e["row"]} | {e["column"]}: "{e["value"]}" — expected true/false')
                elif e['constraint'] == 'mice':
                    for p in e.get('problems', []):
                        lines.append(f'    {e["row"]} | {e["column"]}: "{p["entry"]}" — {p["reason"]}')
                elif e['constraint'] == 'scene_ids':
                    unresolved = ', '.join(e.get('unresolved', []))
                    lines.append(f'    {e["row"]} | {e["column"]}: "{unresolved}" — not in scenes.csv')

    return '\n'.join(lines)


# ============================================================================
# Argument parsing
# ============================================================================

def parse_args(argv):
    parser = argparse.ArgumentParser(
        prog='storyforge migrate',
        description='Upgrade existing projects to normalized registry model.',
    )
    parser.add_argument('--dry-run', action='store_true',
                        help='Show what would change without writing')
    parser.add_argument('--no-commit', action='store_true',
                        help='Make changes but don\'t git commit')
    return parser.parse_args(argv)


# ============================================================================
# Main
# ============================================================================

def main(argv=None):
    args = parse_args(argv or [])
    project_dir = detect_project_root()
    ref_dir = os.path.join(project_dir, 'reference')

    project_title = read_yaml_field('title', project_dir) or 'unknown'

    if not os.path.isfile(os.path.join(ref_dir, 'scenes.csv')):
        print(f'Error: No scenes.csv found in {ref_dir}.')
        sys.exit(1)

    log(f'Migration: {project_title}')
    log('')

    # Step 1: Rename scene_type -> action_sequel
    result = step1_rename_scene_type(ref_dir, args.dry_run)
    if result.startswith('skip:'):
        log(f'  [1/5] Rename scene_type -> action_sequel: skipped ({result[5:]})')
    else:
        count = result.split(':')[1]
        log(f'  [1/5] Rename scene_type -> action_sequel: done ({count} rows)')

    # Step 2: Remove threads column
    result = step2_remove_threads(ref_dir, args.dry_run)
    if result.startswith('skip:'):
        log(f'  [2/5] Remove threads column: skipped ({result[5:]})')
    else:
        count = result.split(':')[1]
        log(f'  [2/5] Remove threads column: done ({count} rows)')

    # Step 3: Seed registries
    log('  [3/5] Seed registries:')
    registry_results = step3_seed_registries(ref_dir, args.dry_run)
    for line in registry_results:
        registry = line.split(':')[0]
        action = line.split(':')[1]
        detail = ':'.join(line.split(':')[2:])
        if action == 'skip':
            log(f'    {registry}: skipped ({detail})')
        else:
            log(f'    {registry}: created ({detail} entries)')

    # Step 4: Normalize fields
    if args.dry_run:
        log('  [4/5] Normalize fields: skipped (dry run)')
    else:
        updated = step4_normalize(ref_dir, project_dir)
        log(f'  [4/5] Normalize fields: {updated} cells updated')

    # Step 5: Validate
    validate_output = step5_validate(ref_dir, project_dir)
    first_line = validate_output.split('\n')[0]
    log(f'  [5/5] Schema validation: {first_line}')
    rest_lines = validate_output.split('\n')[1:]
    for line in rest_lines:
        log(f'         {line}')

    # Commit
    if args.dry_run:
        log('')
        log('Dry run complete — no files were modified.')
    elif args.no_commit:
        log('')
        log('Changes written but not committed (--no-commit).')
    else:
        committed = commit_and_push(
            project_dir,
            'Migrate: upgrade to normalized registry model',
            ['reference/'],
        )
        log('')
        if committed:
            log('Changes committed.')
        else:
            log('No changes to commit.')
