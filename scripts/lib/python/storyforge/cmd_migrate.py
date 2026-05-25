"""storyforge migrate — Upgrade existing projects to the current schema.

One-time migration that runs eight steps. Steps 1-5 normalize the
registry model; steps 6-8 carry projects forward to the elaboration-v1
three-tier structure (#229):

  1. Renames scene_type -> action_sequel in scene-intent.csv
  2. Removes the threads column from scene-intent.csv
  3. Seeds new registry files (values.csv, knowledge.csv, mice-threads.csv)
  4. Normalizes all registry-backed fields to canonical IDs
  5. Runs schema validation to show remaining issues
  6. Creates reference/story-summary.md (Logline / Synopsis / Act-shape /
     Theme), seeding the Logline from storyforge.yaml:project.logline
  7. Extracts status=spine rows from scenes.csv into reference/spine.csv
     (also drops matching scene-intent.csv rows and orphan scene-briefs.csv
     rows). Idempotent — picks up stranded rows added between runs.
  8. Extracts status=architecture rows from scenes.csv into
     reference/architecture.csv (same shape as step 7).

Steps 7 and 8 use multi-file atomic writes so a mid-write failure
doesn't leave the project in a half-migrated state.

Every step is idempotent — safe to run multiple times.

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
from storyforge.git import commit_and_push, ensure_on_branch


# ============================================================================
# Helpers
# ============================================================================

def _read_csv(path: str) -> tuple[list[str], list[dict]]:
    """Read a pipe-delimited CSV. Returns (header_fields, rows_as_dicts).

    Strips ``\\r`` so CRLF line endings and stray carriage returns embedded
    by awk-based CSV edits never propagate into field values.
    """
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
# Step 6: bootstrap reference/story-summary.md from project.logline
# ============================================================================

# Re-rendering the template via Python rather than file-copying keeps the
# command self-contained and avoids a templates path dependency.
STORY_SUMMARY_BOOTSTRAP = """\
<!--
This file holds the story at progressively finer levels of detail:

  - Logline (1 sentence)
  - Synopsis (1 paragraph)
  - Act-shape (3 paragraphs)
  - Theme (2-4 sentences)

Edit any section freely. `storyforge sync` keeps the structural tier
aligned. Per-section update timestamps in the frontmatter feed cascade
drift detection.

Internal use only. None of this is pitch material — be specific.
-->
---
logline_updated:
synopsis_updated:
act_shape_updated:
theme_updated:
---

# Story summary

## Logline

{logline}

## Synopsis

(write the synopsis here)

## Act-shape

### Act 1
(write Act 1 here)

### Act 2
(write Act 2 here)

### Act 3
(write Act 3 here)

## Theme

(write the central question or claim here)
"""


def step6_create_story_summary(project_dir: str, dry_run: bool) -> str:
    """Create reference/story-summary.md if absent.

    Seeds the Logline section from `storyforge.yaml:project.logline` when
    present. If the yaml has no logline, the Logline section is written
    blank (NOT with a placeholder string) — a placeholder would slip past
    the level-0 floor check's "present" assertion. Other sections also
    use placeholders only because the templates need *some* prompt text;
    those slots aren't gated by a `present` check the same way.

    Skips if the file already exists (idempotent).
    """
    path = os.path.join(project_dir, 'reference', 'story-summary.md')
    if os.path.isfile(path):
        return 'skip:already exists'

    logline = (
        read_yaml_field('project.logline', project_dir)
        or read_yaml_field('logline', project_dir)
        or ''  # leave blank so score_logline correctly reports `present: False`
    )
    content = STORY_SUMMARY_BOOTSTRAP.format(logline=logline)

    if dry_run:
        return f'create:{len(content)} bytes'

    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, 'w', encoding='utf-8') as f:
        f.write(content)
    return f'create:{len(content)} bytes (logline {"seeded" if logline else "blank"})'


# ============================================================================
# Step 7: extract status=spine rows from scenes.csv into spine.csv
# ============================================================================

# Column lists are the single source of truth in elaborate._FILE_MAP.
# Importing rather than redefining prevents schema drift between the
# migration writer and the rest of the codebase that reads the file.
from storyforge.elaborate import _SPINE_COLS, _ARCHITECTURE_COLS


def step7_extract_spine(ref_dir: str, dry_run: bool) -> str:
    """Move status=spine rows from scenes.csv into reference/spine.csv.

    For each moved row, the matching scene-intent.csv row is also removed
    (its `function` column is now carried by spine.csv) and any matching
    scene-briefs.csv row (an orphan briefly possible if a project was
    drafted then demoted) is dropped.

    Side effects:
      - Writes reference/spine.csv (creates or overwrites the header-only
        template).
      - Rewrites reference/scenes.csv without the moved rows.
      - Rewrites reference/scene-intent.csv without the moved IDs.
      - Rewrites reference/scene-briefs.csv to drop any orphans for the
        moved IDs.

    Idempotency:
      - If spine.csv has data rows AND scenes.csv contains no remaining
        status=spine rows, skip with 'skip:already migrated'.
      - If spine.csv has data rows AND scenes.csv still has status=spine
        rows, those are STRANDED — process them (so an author who adds a
        new spine row between migrations gets it picked up).

    Atomicity: all four file writes go through a write-temp / atomic-
    rename helper so a mid-write failure leaves all files in their
    pre-migration state (or fully migrated). No partial-state outcomes.
    """
    spine_path = os.path.join(ref_dir, 'spine.csv')
    scenes_path = os.path.join(ref_dir, 'scenes.csv')
    intent_path = os.path.join(ref_dir, 'scene-intent.csv')
    briefs_path = os.path.join(ref_dir, 'scene-briefs.csv')

    if not os.path.isfile(scenes_path):
        return 'skip:no scenes.csv'

    # Upgrade old-schema spine.csv (e.g., pre-summary header) before any
    # append, so stranded rows don't get written with a column-arity
    # mismatch against the existing header.
    if not dry_run:
        _upgrade_csv_header_if_drifted(spine_path, _SPINE_COLS)

    scenes_header, scenes_rows = _read_csv(scenes_path)
    intent_header, intent_rows = _read_csv(intent_path)
    briefs_header, briefs_rows = _read_csv(briefs_path)
    intent_by_id = {r.get('id', ''): r for r in intent_rows}

    spine_rows_out: list[dict] = []
    keep_scene_rows: list[dict] = []
    moved_ids: set[str] = set()
    for row in scenes_rows:
        if row.get('status', '').strip() == 'spine':
            intent = intent_by_id.get(row.get('id', ''), {})
            spine_rows_out.append({
                'id': row.get('id', ''),
                'seq': row.get('seq', ''),
                'title': row.get('title', ''),
                'function': intent.get('function', ''),
                'part': row.get('part', ''),
            })
            moved_ids.add(row.get('id', ''))
        else:
            keep_scene_rows.append(row)

    # Idempotency: if spine.csv already has data AND no stranded rows
    # remain in scenes.csv, we have nothing to do.
    spine_has_data = False
    if os.path.isfile(spine_path):
        with open(spine_path, encoding='utf-8') as f:
            existing = [l for l in f.read().splitlines() if l.strip()]
        spine_has_data = len(existing) > 1

    if not moved_ids:
        if spine_has_data:
            return 'skip:already migrated'
        return 'skip:no status=spine rows in scenes.csv'

    if dry_run:
        return f'extract:{len(spine_rows_out)} rows'

    keep_intent_rows = [r for r in intent_rows if r.get('id', '') not in moved_ids]
    keep_briefs_rows = [r for r in briefs_rows if r.get('id', '') not in moved_ids]
    briefs_dropped = len(briefs_rows) - len(keep_briefs_rows)

    # If spine.csv already has rows (we're processing stranded entries),
    # append rather than overwrite — preserves prior spine entries.
    existing_spine_lines: list[str] = []
    if spine_has_data:
        with open(spine_path, encoding='utf-8') as f:
            existing_spine_lines = [l for l in f.read().splitlines() if l.strip()]

    _atomic_multi_write([
        (spine_path, _format_csv_lines(_SPINE_COLS, spine_rows_out,
                                       existing_lines=existing_spine_lines)),
        (scenes_path, _format_csv_lines(scenes_header, keep_scene_rows)),
        (intent_path, _format_csv_lines(intent_header, keep_intent_rows))
            if intent_header else None,
        (briefs_path, _format_csv_lines(briefs_header, keep_briefs_rows))
            if briefs_header and briefs_dropped else None,
    ])

    summary = f'extract:{len(spine_rows_out)} rows'
    if briefs_dropped:
        summary += f' (+ dropped {briefs_dropped} orphan brief(s))'
    return summary


# ============================================================================
# Step 8: extract status=architecture rows from scenes.csv into architecture.csv
# ============================================================================

def step8_extract_architecture(ref_dir: str, dry_run: bool) -> str:
    """Move status=architecture rows from scenes.csv (+ matching scene-intent
    columns) into reference/architecture.csv. `spine_event` is left empty —
    the author wires it up after migration.

    Side effects + idempotency + atomicity: same shape as step 7. Reads
    scenes.csv, scene-intent.csv, scene-briefs.csv; writes architecture.csv
    and rewrites the manuscript-tier files atomically.
    """
    arch_path = os.path.join(ref_dir, 'architecture.csv')
    scenes_path = os.path.join(ref_dir, 'scenes.csv')
    intent_path = os.path.join(ref_dir, 'scene-intent.csv')
    briefs_path = os.path.join(ref_dir, 'scene-briefs.csv')

    if not os.path.isfile(scenes_path):
        return 'skip:no scenes.csv'

    # Upgrade old-schema architecture.csv before any append.
    if not dry_run:
        _upgrade_csv_header_if_drifted(arch_path, _ARCHITECTURE_COLS)

    scenes_header, scenes_rows = _read_csv(scenes_path)
    intent_header, intent_rows = _read_csv(intent_path)
    briefs_header, briefs_rows = _read_csv(briefs_path)
    intent_by_id = {r.get('id', ''): r for r in intent_rows}

    arch_rows_out: list[dict] = []
    keep_scene_rows: list[dict] = []
    moved_ids: set[str] = set()
    for row in scenes_rows:
        if row.get('status', '').strip() == 'architecture':
            intent = intent_by_id.get(row.get('id', ''), {})
            arch_rows_out.append({
                'id': row.get('id', ''),
                'seq': row.get('seq', ''),
                'title': row.get('title', ''),
                'part': row.get('part', ''),
                'pov': row.get('pov', ''),
                'spine_event': '',
                'action_sequel': intent.get('action_sequel', ''),
                'emotional_arc': intent.get('emotional_arc', ''),
                'value_at_stake': intent.get('value_at_stake', ''),
                'value_shift': intent.get('value_shift', ''),
                'turning_point': intent.get('turning_point', ''),
            })
            moved_ids.add(row.get('id', ''))
        else:
            keep_scene_rows.append(row)

    arch_has_data = False
    if os.path.isfile(arch_path):
        with open(arch_path, encoding='utf-8') as f:
            existing = [l for l in f.read().splitlines() if l.strip()]
        arch_has_data = len(existing) > 1

    if not moved_ids:
        if arch_has_data:
            return 'skip:already migrated'
        return 'skip:no status=architecture rows in scenes.csv'

    if dry_run:
        return f'extract:{len(arch_rows_out)} rows'

    keep_intent_rows = [r for r in intent_rows if r.get('id', '') not in moved_ids]
    keep_briefs_rows = [r for r in briefs_rows if r.get('id', '') not in moved_ids]
    briefs_dropped = len(briefs_rows) - len(keep_briefs_rows)

    existing_arch_lines: list[str] = []
    if arch_has_data:
        with open(arch_path, encoding='utf-8') as f:
            existing_arch_lines = [l for l in f.read().splitlines() if l.strip()]

    _atomic_multi_write([
        (arch_path, _format_csv_lines(_ARCHITECTURE_COLS, arch_rows_out,
                                      existing_lines=existing_arch_lines)),
        (scenes_path, _format_csv_lines(scenes_header, keep_scene_rows)),
        (intent_path, _format_csv_lines(intent_header, keep_intent_rows))
            if intent_header else None,
        (briefs_path, _format_csv_lines(briefs_header, keep_briefs_rows))
            if briefs_header and briefs_dropped else None,
    ])

    summary = f'extract:{len(arch_rows_out)} rows'
    if briefs_dropped:
        summary += f' (+ dropped {briefs_dropped} orphan brief(s))'
    return summary


# ============================================================================
# Write helpers — atomicity for the multi-file migration steps
# ============================================================================

def _upgrade_csv_header_if_drifted(path: str, target_cols: list[str]) -> bool:
    """If the CSV at `path` has a header that's a strict subset of
    `target_cols` (older schema), rewrite the file with the new header and
    pad existing rows with empty cells for the added columns.

    Returns True if an upgrade was performed; False if the header already
    matches or the file is absent. Raises ValueError if the existing
    header has columns NOT in target_cols (would lose data).
    """
    if not os.path.isfile(path):
        return False
    with open(path, encoding='utf-8') as f:
        lines = [l for l in f.read().splitlines() if l.strip()]
    if not lines:
        return False
    existing_header = lines[0].split('|')
    if existing_header == target_cols:
        return False
    extra = [c for c in existing_header if c not in target_cols]
    if extra:
        raise ValueError(
            f'{path}: header has columns not in target schema {extra!r}; '
            f'refusing to upgrade (would lose data)'
        )
    # Pad each existing row with empty cells for the new columns.
    new_lines = ['|'.join(target_cols)]
    for line in lines[1:]:
        cells = line.split('|')
        row = dict(zip(existing_header, cells))
        new_lines.append('|'.join(row.get(c, '') for c in target_cols))
    with open(path, 'w', encoding='utf-8') as f:
        f.write('\n'.join(new_lines) + '\n')
    return True


def _format_csv_lines(header: list[str], rows: list[dict],
                      existing_lines: list[str] | None = None) -> str:
    """Render header + rows as a single pipe-delimited CSV string.

    If `existing_lines` is given, the existing header is checked against
    `header`. If they match, existing rows are kept and new rows appended.
    If `header` adds columns not in the existing header (schema upgrade),
    the existing rows are padded with empty cells for the new columns and
    the file is rewritten with the new header. If `existing_lines` has
    columns NOT in `header`, raises ValueError (would lose data).
    """
    if not existing_lines:
        parts = ['|'.join(header)]
        for row in rows:
            parts.append('|'.join(row.get(c, '') for c in header))
        return '\n'.join(parts) + '\n'

    existing_header = existing_lines[0].split('|')
    extra_in_existing = [c for c in existing_header if c not in header]
    if extra_in_existing:
        raise ValueError(
            f'existing CSV has columns not in target schema '
            f'{extra_in_existing!r}; refusing to migrate (would lose data)'
        )

    if existing_header == header:
        # Headers match — keep the existing block verbatim.
        parts = list(existing_lines)
    else:
        # Schema upgrade: rewrite header, pad existing rows with empty
        # cells for any added columns.
        parts = ['|'.join(header)]
        for line in existing_lines[1:]:
            cells = line.split('|')
            row = dict(zip(existing_header, cells))
            parts.append('|'.join(row.get(c, '') for c in header))
    for row in rows:
        parts.append('|'.join(row.get(c, '') for c in header))
    return '\n'.join(parts) + '\n'


def _atomic_multi_write(writes: list[tuple[str, str] | None]) -> None:
    """Write multiple files atomically as a group.

    Each entry is (path, content) — or None (skip). Strategy:
      1. Write all content to sibling temp files (`<path>.migrate-tmp`).
      2. Once every write has succeeded, os.replace each into place.

    If step 1 fails for any file, no live data has been touched and the
    partial temp files are cleaned up. If step 2 fails partway, files
    written so far are renamed but the rest aren't — that's not strictly
    atomic across files, but on local filesystems os.replace itself is
    atomic per-file and the rename pass is fast enough that this window
    is small. Worth a follow-up if/when migration runs on slow storage.
    """
    writes = [w for w in writes if w is not None]
    tmp_paths: list[tuple[str, str]] = []  # (tmp_path, final_path)
    try:
        for final_path, content in writes:
            tmp_path = final_path + '.migrate-tmp'
            os.makedirs(os.path.dirname(final_path) or '.', exist_ok=True)
            with open(tmp_path, 'w', encoding='utf-8') as f:
                f.write(content)
            tmp_paths.append((tmp_path, final_path))
    except OSError:
        # Step 1 failed: clean up temps so we leave no debris.
        for tmp_path, _ in tmp_paths:
            try:
                os.remove(tmp_path)
            except OSError:
                pass
        raise

    # Step 2: rename pass. os.replace is atomic per-file on POSIX/Windows.
    for tmp_path, final_path in tmp_paths:
        os.replace(tmp_path, final_path)


def _rewrite_csv(path: str, header: list[str], rows: list[dict]) -> None:
    """Rewrite a pipe-delimited CSV with the given header + rows.

    Cells default to '' when a row is missing a header column. Preserves
    header order even when rows have a different shape.

    Kept for backward compatibility with earlier callers; new step 7/8
    code paths go through _format_csv_lines + _atomic_multi_write for
    multi-file atomicity.
    """
    with open(path, 'w', encoding='utf-8') as f:
        f.write('|'.join(header) + '\n')
        for row in rows:
            f.write('|'.join(row.get(c, '') for c in header) + '\n')


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

    if not args.dry_run and not args.no_commit:
        ensure_on_branch('migrate', project_dir)

    log(f'Migration: {project_title}')
    log('')

    # Step 1: Rename scene_type -> action_sequel
    result = step1_rename_scene_type(ref_dir, args.dry_run)
    if result.startswith('skip:'):
        log(f'  [1/8] Rename scene_type -> action_sequel: skipped ({result[5:]})')
    else:
        count = result.split(':')[1]
        log(f'  [1/8] Rename scene_type -> action_sequel: done ({count} rows)')

    # Step 2: Remove threads column
    result = step2_remove_threads(ref_dir, args.dry_run)
    if result.startswith('skip:'):
        log(f'  [2/8] Remove threads column: skipped ({result[5:]})')
    else:
        count = result.split(':')[1]
        log(f'  [2/8] Remove threads column: done ({count} rows)')

    # Step 3: Seed registries
    log('  [3/8] Seed registries:')
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
        log('  [4/8] Normalize fields: skipped (dry run)')
    else:
        updated = step4_normalize(ref_dir, project_dir)
        log(f'  [4/8] Normalize fields: {updated} cells updated')

    # Step 5: Validate
    validate_output = step5_validate(ref_dir, project_dir)
    first_line = validate_output.split('\n')[0]
    log(f'  [5/8] Schema validation: {first_line}')
    rest_lines = validate_output.split('\n')[1:]
    for line in rest_lines:
        log(f'         {line}')

    # Step 6: Bootstrap story-summary.md (elaboration v1)
    result = step6_create_story_summary(project_dir, args.dry_run)
    if result.startswith('skip:'):
        log(f'  [6/8] Create story-summary.md: skipped ({result[5:]})')
    else:
        log(f'  [6/8] Create story-summary.md: {result.split(":")[1]}')

    # Step 7: Extract spine.csv from status=spine rows
    result = step7_extract_spine(ref_dir, args.dry_run)
    if result.startswith('skip:'):
        log(f'  [7/8] Extract spine.csv: skipped ({result[5:]})')
    else:
        log(f'  [7/8] Extract spine.csv: {result.split(":")[1]}')

    # Step 8: Extract architecture.csv from status=architecture rows
    result = step8_extract_architecture(ref_dir, args.dry_run)
    if result.startswith('skip:'):
        log(f'  [8/8] Extract architecture.csv: skipped ({result[5:]})')
    else:
        log(f'  [8/8] Extract architecture.csv: {result.split(":")[1]}')

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
