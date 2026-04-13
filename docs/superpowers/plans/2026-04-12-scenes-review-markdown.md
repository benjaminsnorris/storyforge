# Scenes Review Markdown Export/Import Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Two storyforge commands (`scenes-export`, `scenes-import`) that merge all three scene CSVs into a single reviewable markdown file and round-trip edits back.

**Architecture:** Both commands are thin CLI wrappers around shared export/import logic. Export reads three CSVs, merges by scene ID, writes grouped key-value markdown. Import parses the markdown back, diffs against current CSVs, and calls `update_field` only for changed values.

**Tech Stack:** Python stdlib only. Uses existing `csv_cli`, `scene_filter`, and `cli` modules.

---

### Task 1: Export — core logic and tests

**Files:**
- Create: `scripts/lib/python/storyforge/cmd_scenes_export.py`
- Create: `tests/test_scenes_review.py`

The export module reads three CSVs and writes a markdown file. Each scene gets an `## id` heading with three `###` sections (Structural, Intent, Brief) containing `key: value` lines.

- [ ] **Step 1: Write the test file with export tests**

```python
# tests/test_scenes_review.py
"""Tests for scenes-export and scenes-import commands."""

import os

from storyforge.csv_cli import get_field


# ============================================================================
# Column definitions (must match cmd_scenes_export.py)
# ============================================================================

STRUCTURAL_FIELDS = [
    'seq', 'title', 'part', 'pov', 'location', 'timeline_day',
    'time_of_day', 'duration', 'type', 'status', 'word_count', 'target_words',
]
INTENT_FIELDS = [
    'function', 'action_sequel', 'emotional_arc', 'value_at_stake',
    'value_shift', 'turning_point', 'characters', 'on_stage', 'mice_threads',
]
BRIEF_FIELDS = [
    'goal', 'conflict', 'outcome', 'crisis', 'decision', 'knowledge_in',
    'knowledge_out', 'key_actions', 'key_dialogue', 'emotions', 'motifs',
    'subtext', 'continuity_deps', 'has_overflow', 'physical_state_in',
    'physical_state_out',
]


class TestExport:
    def test_export_creates_file(self, project_dir):
        from storyforge.cmd_scenes_export import export_scenes

        output = os.path.join(project_dir, 'working', 'scenes-review.md')
        export_scenes(project_dir, output)
        assert os.path.isfile(output)

    def test_export_has_scene_headings(self, project_dir):
        from storyforge.cmd_scenes_export import export_scenes

        output = os.path.join(project_dir, 'working', 'scenes-review.md')
        export_scenes(project_dir, output)
        content = open(output).read()
        assert '## act1-sc01' in content
        assert '## act1-sc02' in content

    def test_export_ordered_by_seq(self, project_dir):
        from storyforge.cmd_scenes_export import export_scenes

        output = os.path.join(project_dir, 'working', 'scenes-review.md')
        export_scenes(project_dir, output)
        content = open(output).read()
        pos1 = content.index('## act1-sc01')
        pos2 = content.index('## act1-sc02')
        assert pos1 < pos2

    def test_export_has_three_sections(self, project_dir):
        from storyforge.cmd_scenes_export import export_scenes

        output = os.path.join(project_dir, 'working', 'scenes-review.md')
        export_scenes(project_dir, output)
        content = open(output).read()
        assert '### Structural' in content
        assert '### Intent' in content
        assert '### Brief' in content

    def test_export_structural_fields(self, project_dir):
        from storyforge.cmd_scenes_export import export_scenes

        output = os.path.join(project_dir, 'working', 'scenes-review.md')
        export_scenes(project_dir, output)
        content = open(output).read()
        assert 'title: The Finest Cartographer' in content
        assert 'pov: Dorren Hayle' in content

    def test_export_intent_fields(self, project_dir):
        from storyforge.cmd_scenes_export import export_scenes

        output = os.path.join(project_dir, 'working', 'scenes-review.md')
        export_scenes(project_dir, output)
        content = open(output).read()
        assert 'action_sequel: action' in content
        assert 'value_at_stake: truth' in content

    def test_export_brief_fields(self, project_dir):
        from storyforge.cmd_scenes_export import export_scenes

        output = os.path.join(project_dir, 'working', 'scenes-review.md')
        export_scenes(project_dir, output)
        content = open(output).read()
        assert 'outcome: no-and' in content

    def test_export_with_act_filter(self, project_dir):
        from storyforge.cmd_scenes_export import export_scenes

        output = os.path.join(project_dir, 'working', 'scenes-review.md')
        export_scenes(project_dir, output, filter_mode='act', filter_value='1')
        content = open(output).read()
        # Both test scenes are in part 1
        assert '## act1-sc01' in content
        assert '## act1-sc02' in content

    def test_export_with_scenes_filter(self, project_dir):
        from storyforge.cmd_scenes_export import export_scenes

        output = os.path.join(project_dir, 'working', 'scenes-review.md')
        export_scenes(project_dir, output, filter_mode='scenes', filter_value='act1-sc01')
        content = open(output).read()
        assert '## act1-sc01' in content
        assert '## act1-sc02' not in content

    def test_export_empty_fields_present(self, project_dir):
        from storyforge.cmd_scenes_export import export_scenes

        output = os.path.join(project_dir, 'working', 'scenes-review.md')
        export_scenes(project_dir, output)
        content = open(output).read()
        # word_count is 0 in fixture, should still appear
        assert 'word_count: 0' in content
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd /Users/cadencedev/Developer/storyforge && python3 -m pytest tests/test_scenes_review.py -v`
Expected: ImportError — `cmd_scenes_export` does not exist yet.

- [ ] **Step 3: Write the export module**

```python
# scripts/lib/python/storyforge/cmd_scenes_export.py
"""storyforge scenes-export — Export scene data to a reviewable markdown file.

Merges scenes.csv, scene-intent.csv, and scene-briefs.csv into a single
markdown file with one ## heading per scene, ordered by sequence number.

Usage:
    storyforge scenes-export                      # Export all scenes
    storyforge scenes-export --act 2              # Export only Act 2
    storyforge scenes-export --scenes a,b,c       # Export specific scenes
    storyforge scenes-export --from-seq 10-20     # Export sequence range
    storyforge scenes-export --output /tmp/out.md # Custom output path
"""

import argparse
import os
import sys

from storyforge.cli import add_scene_filter_args, resolve_filter_args
from storyforge.common import detect_project_root, log
from storyforge.csv_cli import get_field
from storyforge.scene_filter import apply_scene_filter, build_scene_list


# ============================================================================
# Column definitions
# ============================================================================

STRUCTURAL_FIELDS = [
    'seq', 'title', 'part', 'pov', 'location', 'timeline_day',
    'time_of_day', 'duration', 'type', 'status', 'word_count', 'target_words',
]

INTENT_FIELDS = [
    'function', 'action_sequel', 'emotional_arc', 'value_at_stake',
    'value_shift', 'turning_point', 'characters', 'on_stage', 'mice_threads',
]

BRIEF_FIELDS = [
    'goal', 'conflict', 'outcome', 'crisis', 'decision', 'knowledge_in',
    'knowledge_out', 'key_actions', 'key_dialogue', 'emotions', 'motifs',
    'subtext', 'continuity_deps', 'has_overflow', 'physical_state_in',
    'physical_state_out',
]

SECTIONS = [
    ('Structural', 'reference/scenes.csv', STRUCTURAL_FIELDS),
    ('Intent', 'reference/scene-intent.csv', INTENT_FIELDS),
    ('Brief', 'reference/scene-briefs.csv', BRIEF_FIELDS),
]


# ============================================================================
# Export logic
# ============================================================================

def export_scenes(project_dir, output_path, filter_mode='all',
                  filter_value=None, filter_value2=None):
    """Export scene data from three CSVs to a single markdown file."""
    meta_csv = os.path.join(project_dir, 'reference', 'scenes.csv')
    all_ids = build_scene_list(meta_csv)
    scene_ids = apply_scene_filter(meta_csv, all_ids, filter_mode,
                                   filter_value, filter_value2)

    lines = []
    for i, sid in enumerate(scene_ids):
        if i > 0:
            lines.append('')
        lines.append(f'## {sid}')

        for section_name, csv_rel, fields in SECTIONS:
            csv_path = os.path.join(project_dir, csv_rel)
            lines.append('')
            lines.append(f'### {section_name}')
            for field in fields:
                value = get_field(csv_path, sid, field)
                lines.append(f'{field}: {value}')

    lines.append('')  # trailing newline

    os.makedirs(os.path.dirname(output_path), exist_ok=True)
    with open(output_path, 'w', encoding='utf-8') as f:
        f.write('\n'.join(lines))

    log(f'Exported {len(scene_ids)} scenes to {output_path}')


# ============================================================================
# Argument parsing
# ============================================================================

def parse_args(argv):
    parser = argparse.ArgumentParser(
        prog='storyforge scenes-export',
        description='Export scene data to a reviewable markdown file.',
    )
    add_scene_filter_args(parser)
    parser.add_argument('--output', '-o', type=str, default=None,
                        help='Output path (default: working/scenes-review.md)')
    return parser.parse_args(argv)


# ============================================================================
# Main
# ============================================================================

def main(argv=None):
    args = parse_args(argv or [])
    project_dir = detect_project_root()

    output = args.output or os.path.join(project_dir, 'working', 'scenes-review.md')
    mode, value, value2 = resolve_filter_args(args)
    export_scenes(project_dir, output, mode, value, value2)
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd /Users/cadencedev/Developer/storyforge && python3 -m pytest tests/test_scenes_review.py -v`
Expected: All 10 tests pass.

- [ ] **Step 5: Commit**

```bash
git add scripts/lib/python/storyforge/cmd_scenes_export.py tests/test_scenes_review.py
git commit -m "Add scenes-export command with tests"
git push
```

---

### Task 2: Import — core logic and tests

**Files:**
- Create: `scripts/lib/python/storyforge/cmd_scenes_import.py`
- Modify: `tests/test_scenes_review.py`

The import module parses a markdown file back into per-scene field dictionaries, diffs against current CSV values, and updates only changed fields.

- [ ] **Step 1: Add import tests to the test file**

Append to `tests/test_scenes_review.py`:

```python
class TestParse:
    """Test the markdown parser independently."""

    def test_parse_single_scene(self):
        from storyforge.cmd_scenes_import import parse_markdown

        md = (
            '## test-scene\n'
            '\n'
            '### Structural\n'
            'seq: 5\n'
            'title: Test Scene\n'
            '\n'
            '### Intent\n'
            'function: Introduce conflict\n'
            '\n'
            '### Brief\n'
            'goal: Establish stakes\n'
        )
        scenes = parse_markdown(md)
        assert 'test-scene' in scenes
        assert scenes['test-scene']['Structural']['seq'] == '5'
        assert scenes['test-scene']['Structural']['title'] == 'Test Scene'
        assert scenes['test-scene']['Intent']['function'] == 'Introduce conflict'
        assert scenes['test-scene']['Brief']['goal'] == 'Establish stakes'

    def test_parse_multiple_scenes(self):
        from storyforge.cmd_scenes_import import parse_markdown

        md = (
            '## scene-a\n'
            '\n'
            '### Structural\n'
            'seq: 1\n'
            '\n'
            '## scene-b\n'
            '\n'
            '### Structural\n'
            'seq: 2\n'
        )
        scenes = parse_markdown(md)
        assert len(scenes) == 2
        assert scenes['scene-a']['Structural']['seq'] == '1'
        assert scenes['scene-b']['Structural']['seq'] == '2'

    def test_parse_empty_field(self):
        from storyforge.cmd_scenes_import import parse_markdown

        md = (
            '## test-scene\n'
            '\n'
            '### Structural\n'
            'seq: 1\n'
            'title: \n'
        )
        scenes = parse_markdown(md)
        assert scenes['test-scene']['Structural']['title'] == ''

    def test_parse_colon_in_value(self):
        from storyforge.cmd_scenes_import import parse_markdown

        md = (
            '## test-scene\n'
            '\n'
            '### Brief\n'
            'key_dialogue: She said: "Run!"\n'
        )
        scenes = parse_markdown(md)
        assert scenes['test-scene']['Brief']['key_dialogue'] == 'She said: "Run!"'

    def test_parse_continuation_line(self):
        from storyforge.cmd_scenes_import import parse_markdown

        md = (
            '## test-scene\n'
            '\n'
            '### Brief\n'
            'goal: Establish the world and introduce\n'
            '  the main character\n'
        )
        scenes = parse_markdown(md)
        assert scenes['test-scene']['Brief']['goal'] == 'Establish the world and introduce the main character'


class TestImport:
    def test_import_no_changes(self, project_dir):
        """Export then immediately import — nothing should change."""
        from storyforge.cmd_scenes_export import export_scenes
        from storyforge.cmd_scenes_import import import_scenes

        output = os.path.join(project_dir, 'working', 'scenes-review.md')
        export_scenes(project_dir, output)
        changes = import_scenes(project_dir, output, dry_run=True)
        assert changes == []

    def test_import_detects_change(self, project_dir):
        from storyforge.cmd_scenes_export import export_scenes
        from storyforge.cmd_scenes_import import import_scenes

        output = os.path.join(project_dir, 'working', 'scenes-review.md')
        export_scenes(project_dir, output)

        # Edit the markdown
        content = open(output).read()
        content = content.replace(
            'title: The Finest Cartographer',
            'title: The Last Cartographer',
        )
        with open(output, 'w') as f:
            f.write(content)

        changes = import_scenes(project_dir, output, dry_run=True)
        assert len(changes) == 1
        assert changes[0] == ('act1-sc01', 'reference/scenes.csv', 'title',
                              'The Finest Cartographer', 'The Last Cartographer')

    def test_import_writes_change(self, project_dir):
        from storyforge.cmd_scenes_export import export_scenes
        from storyforge.cmd_scenes_import import import_scenes

        output = os.path.join(project_dir, 'working', 'scenes-review.md')
        export_scenes(project_dir, output)

        content = open(output).read()
        content = content.replace(
            'title: The Finest Cartographer',
            'title: The Last Cartographer',
        )
        with open(output, 'w') as f:
            f.write(content)

        changes = import_scenes(project_dir, output, dry_run=False)
        assert len(changes) == 1

        # Verify the CSV was actually updated
        csv_path = os.path.join(project_dir, 'reference', 'scenes.csv')
        assert get_field(csv_path, 'act1-sc01', 'title') == 'The Last Cartographer'

    def test_import_multiple_changes(self, project_dir):
        from storyforge.cmd_scenes_export import export_scenes
        from storyforge.cmd_scenes_import import import_scenes

        output = os.path.join(project_dir, 'working', 'scenes-review.md')
        export_scenes(project_dir, output)

        content = open(output).read()
        content = content.replace('pov: Dorren Hayle', 'pov: Elara Voss')
        with open(output, 'w') as f:
            f.write(content)

        changes = import_scenes(project_dir, output, dry_run=False)
        # Both scenes have pov: Dorren Hayle, so both should change
        assert len(changes) == 2

        csv_path = os.path.join(project_dir, 'reference', 'scenes.csv')
        assert get_field(csv_path, 'act1-sc01', 'pov') == 'Elara Voss'
        assert get_field(csv_path, 'act1-sc02', 'pov') == 'Elara Voss'

    def test_import_unknown_scene_skipped(self, project_dir):
        from storyforge.cmd_scenes_import import import_scenes

        md_path = os.path.join(project_dir, 'working', 'scenes-review.md')
        os.makedirs(os.path.dirname(md_path), exist_ok=True)
        with open(md_path, 'w') as f:
            f.write('## nonexistent-scene\n\n### Structural\nseq: 99\n')

        changes = import_scenes(project_dir, md_path, dry_run=False)
        assert changes == []
```

- [ ] **Step 2: Run tests to verify new tests fail**

Run: `cd /Users/cadencedev/Developer/storyforge && python3 -m pytest tests/test_scenes_review.py::TestParse -v`
Expected: ImportError — `cmd_scenes_import` does not exist yet.

- [ ] **Step 3: Write the import module**

```python
# scripts/lib/python/storyforge/cmd_scenes_import.py
"""storyforge scenes-import — Import edited markdown back into scene CSVs.

Parses a markdown file produced by scenes-export, diffs against the current
CSV values, and updates only fields that changed.

Usage:
    storyforge scenes-import                      # Import from default path
    storyforge scenes-import --dry-run            # Show changes without writing
    storyforge scenes-import --input /tmp/out.md  # Custom input path
"""

import argparse
import os
import re
import sys

from storyforge.common import detect_project_root, log
from storyforge.csv_cli import get_field, list_ids, update_field


# ============================================================================
# Column definitions (must match cmd_scenes_export.py)
# ============================================================================

STRUCTURAL_FIELDS = [
    'seq', 'title', 'part', 'pov', 'location', 'timeline_day',
    'time_of_day', 'duration', 'type', 'status', 'word_count', 'target_words',
]

INTENT_FIELDS = [
    'function', 'action_sequel', 'emotional_arc', 'value_at_stake',
    'value_shift', 'turning_point', 'characters', 'on_stage', 'mice_threads',
]

BRIEF_FIELDS = [
    'goal', 'conflict', 'outcome', 'crisis', 'decision', 'knowledge_in',
    'knowledge_out', 'key_actions', 'key_dialogue', 'emotions', 'motifs',
    'subtext', 'continuity_deps', 'has_overflow', 'physical_state_in',
    'physical_state_out',
]

# Section name → (csv relative path, known field names)
SECTION_MAP = {
    'Structural': ('reference/scenes.csv', set(STRUCTURAL_FIELDS)),
    'Intent': ('reference/scene-intent.csv', set(INTENT_FIELDS)),
    'Brief': ('reference/scene-briefs.csv', set(BRIEF_FIELDS)),
}


# ============================================================================
# Markdown parser
# ============================================================================

def parse_markdown(text):
    """Parse scenes-review markdown into a nested dict.

    Returns: {scene_id: {section_name: {field: value}}}
    """
    scenes = {}
    current_scene = None
    current_section = None
    last_field = None

    for line in text.splitlines():
        # Scene heading
        if line.startswith('## '):
            current_scene = line[3:].strip()
            scenes[current_scene] = {}
            current_section = None
            last_field = None
            continue

        # Section heading
        if line.startswith('### '):
            section_name = line[4:].strip()
            if current_scene and section_name in SECTION_MAP:
                current_section = section_name
                scenes[current_scene][current_section] = {}
                last_field = None
            continue

        # Blank line
        if not line.strip():
            continue

        # Field line or continuation
        if current_scene and current_section:
            known_fields = SECTION_MAP[current_section][1]
            # Try to match "field_name: value"
            match = re.match(r'^([a-z_]+):\s?(.*)', line)
            if match and match.group(1) in known_fields:
                field_name = match.group(1)
                value = match.group(2)
                scenes[current_scene][current_section][field_name] = value
                last_field = field_name
            elif last_field is not None:
                # Continuation line — append to previous field
                prev = scenes[current_scene][current_section][last_field]
                scenes[current_scene][current_section][last_field] = \
                    prev + ' ' + line.strip()

    return scenes


# ============================================================================
# Import logic
# ============================================================================

def import_scenes(project_dir, input_path, dry_run=False):
    """Import edited markdown back into CSVs. Returns list of changes.

    Each change is a tuple: (scene_id, csv_rel, field, old_value, new_value)
    """
    with open(input_path, encoding='utf-8') as f:
        text = f.read()

    parsed = parse_markdown(text)
    changes = []

    # Build lookup of valid scene IDs per CSV
    csv_ids = {}
    for section_name, (csv_rel, _fields) in SECTION_MAP.items():
        csv_path = os.path.join(project_dir, csv_rel)
        csv_ids[csv_rel] = set(list_ids(csv_path))

    for scene_id, sections in parsed.items():
        for section_name, fields in sections.items():
            csv_rel, _known = SECTION_MAP[section_name]
            csv_path = os.path.join(project_dir, csv_rel)

            if scene_id not in csv_ids.get(csv_rel, set()):
                log(f'WARNING: Scene {scene_id} not found in {csv_rel}, skipping')
                continue

            for field_name, new_value in fields.items():
                old_value = get_field(csv_path, scene_id, field_name)
                if new_value != old_value:
                    changes.append((scene_id, csv_rel, field_name,
                                    old_value, new_value))
                    if not dry_run:
                        update_field(csv_path, scene_id, field_name, new_value)

    return changes


# ============================================================================
# Argument parsing
# ============================================================================

def parse_args(argv):
    parser = argparse.ArgumentParser(
        prog='storyforge scenes-import',
        description='Import edited markdown back into scene CSVs.',
    )
    parser.add_argument('--input', '-i', type=str, default=None,
                        help='Input path (default: working/scenes-review.md)')
    parser.add_argument('--dry-run', action='store_true',
                        help='Show changes without writing')
    return parser.parse_args(argv)


# ============================================================================
# Main
# ============================================================================

def main(argv=None):
    args = parse_args(argv or [])
    project_dir = detect_project_root()

    input_path = args.input or os.path.join(project_dir, 'working',
                                            'scenes-review.md')
    if not os.path.isfile(input_path):
        log(f'ERROR: Input file not found: {input_path}')
        log("Run 'storyforge scenes-export' first.")
        raise SystemExit(1)

    changes = import_scenes(project_dir, input_path, dry_run=args.dry_run)

    if not changes:
        log('No changes detected.')
    else:
        for scene_id, csv_rel, field, old_val, new_val in changes:
            old_display = old_val if old_val else '(empty)'
            new_display = new_val if new_val else '(empty)'
            log(f'  {scene_id}: {field} "{old_display}" -> "{new_display}"')

        action = 'Would update' if args.dry_run else 'Updated'
        log(f'{action} {len(changes)} field(s).')
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd /Users/cadencedev/Developer/storyforge && python3 -m pytest tests/test_scenes_review.py -v`
Expected: All 20 tests pass (10 export + 5 parse + 5 import).

- [ ] **Step 5: Commit**

```bash
git add scripts/lib/python/storyforge/cmd_scenes_import.py tests/test_scenes_review.py
git commit -m "Add scenes-import command with tests"
git push
```

---

### Task 3: Register commands and verify end-to-end

**Files:**
- Modify: `scripts/lib/python/storyforge/__main__.py`

- [ ] **Step 1: Add both commands to the dispatcher**

In `scripts/lib/python/storyforge/__main__.py`, add these two entries to the `COMMANDS` dict (after the `'scenes-setup'` line):

```python
    'scenes-export': 'storyforge.cmd_scenes_export',
    'scenes-import': 'storyforge.cmd_scenes_import',
```

- [ ] **Step 2: Run the full test suite**

Run: `cd /Users/cadencedev/Developer/storyforge && python3 -m pytest tests/test_scenes_review.py -v`
Expected: All tests pass.

- [ ] **Step 3: Verify CLI help works**

Run: `cd /Users/cadencedev/Developer/storyforge && ./storyforge scenes-export -h`
Expected: Shows usage with `--scenes`, `--act`, `--from-seq`, `--output` flags.

Run: `cd /Users/cadencedev/Developer/storyforge && ./storyforge scenes-import -h`
Expected: Shows usage with `--input`, `--dry-run` flags.

- [ ] **Step 4: Commit**

```bash
git add scripts/lib/python/storyforge/__main__.py
git commit -m "Register scenes-export and scenes-import commands"
git push
```

---

### Task 4: Version bump

**Files:**
- Modify: `.claude-plugin/plugin.json`

- [ ] **Step 1: Bump the patch version**

Read `.claude-plugin/plugin.json`, increment the patch version by 1.

- [ ] **Step 2: Commit**

```bash
git add .claude-plugin/plugin.json
git commit -m "Bump version to X.Y.Z"
git push
```
