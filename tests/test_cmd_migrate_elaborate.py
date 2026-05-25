"""Tests for the elaboration-v1 migration steps in cmd_migrate.

Covers:
  - step6_create_story_summary: bootstrap reference/story-summary.md
  - step7_extract_spine: move status=spine rows to spine.csv
  - step8_extract_architecture: move status=architecture rows to architecture.csv

Idempotency is the key invariant — running migrate twice should not
double-extract or overwrite author edits.
"""

import os
import shutil

from storyforge.cmd_migrate import (
    step6_create_story_summary,
    step7_extract_spine,
    step8_extract_architecture,
)


def _read_file(path):
    with open(path, encoding='utf-8') as f:
        return f.read()


# ---------------------------------------------------------------------------
# step6: story-summary.md bootstrap
# ---------------------------------------------------------------------------

def test_step6_creates_story_summary_when_absent(project_dir):
    """No story-summary.md → create it with the project's logline seeded."""
    path = os.path.join(project_dir, 'reference', 'story-summary.md')
    assert not os.path.isfile(path)

    result = step6_create_story_summary(project_dir, dry_run=False)
    assert result.startswith('create:')
    assert os.path.isfile(path)
    content = _read_file(path)
    # Sections present
    assert '## Logline' in content
    assert '## Synopsis' in content
    assert '## Act-shape' in content
    assert '## Theme' in content
    # Frontmatter present
    assert 'logline_updated:' in content


def test_step6_skips_when_file_exists(project_dir):
    """story-summary.md already present → leave it alone (idempotency)."""
    path = os.path.join(project_dir, 'reference', 'story-summary.md')
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, 'w') as f:
        f.write('# Custom content I wrote\n')

    result = step6_create_story_summary(project_dir, dry_run=False)
    assert result.startswith('skip:')
    assert 'Custom content I wrote' in _read_file(path)


def test_step6_dry_run_does_not_write(project_dir):
    path = os.path.join(project_dir, 'reference', 'story-summary.md')
    result = step6_create_story_summary(project_dir, dry_run=True)
    assert result.startswith('create:')
    assert not os.path.isfile(path)


def test_step6_leaves_logline_blank_when_yaml_has_none(tmp_path):
    """When storyforge.yaml has no project.logline, the bootstrapped
    story-summary.md leaves the Logline section blank (not a placeholder
    string). This is so score_logline correctly reports present: False
    instead of being fooled by a placeholder that the user clearly
    didn't author."""
    (tmp_path / 'storyforge.yaml').write_text('project:\n  title: test\n')
    step6_create_story_summary(str(tmp_path), dry_run=False)
    md = _read_file(os.path.join(str(tmp_path), 'reference', 'story-summary.md'))
    # The template has `## Logline\n\n{logline}\n\n## Synopsis` — the
    # logline-section body should be empty between those headers.
    assert '(write the logline here)' not in md
    # The Logline section header still exists but its body is empty
    assert '## Logline' in md
    # Verify the level-0 floor check correctly reports `present: False`
    from storyforge.scoring_levels import score_logline
    r = score_logline(str(tmp_path))
    present_check = next(c for c in r['checks'] if c['check'] == 'present')
    assert not present_check['passed'], (
        'level-0 floor check should report Logline section as not present '
        'when the yaml had no logline'
    )


def test_step6_seeds_logline_from_yaml(project_dir):
    """The project's storyforge.yaml:project.logline gets written into the
    Logline section of the bootstrapped file. Uses the fixture's pre-existing
    logline rather than injecting a new value."""
    step6_create_story_summary(project_dir, dry_run=False)
    md_content = _read_file(os.path.join(project_dir, 'reference', 'story-summary.md'))
    # The fixture's storyforge.yaml has this logline pre-set.
    assert 'A cartographer discovers her maps are erasing people from existence.' in md_content


# ---------------------------------------------------------------------------
# step7: spine extraction
# ---------------------------------------------------------------------------

def test_step7_extracts_spine_rows(project_dir):
    """status=spine rows in scenes.csv → spine.csv (with function from
    scene-intent.csv). The fixture has one row at status=spine."""
    ref_dir = os.path.join(project_dir, 'reference')
    scenes_csv = os.path.join(ref_dir, 'scenes.csv')
    spine_csv = os.path.join(ref_dir, 'spine.csv')

    # Confirm fixture starting state
    with open(scenes_csv) as f:
        before = f.read()
    assert 'act2-sc02' in before
    # act2-sc02 has status=spine per the fixture

    result = step7_extract_spine(ref_dir, dry_run=False)
    assert result.startswith('extract:')
    assert os.path.isfile(spine_csv)
    spine_content = _read_file(spine_csv)
    assert spine_content.startswith('id|seq|title|function|part\n')
    assert 'act2-sc02' in spine_content
    # And it was removed from scenes.csv
    with open(scenes_csv) as f:
        after = f.read()
    assert 'act2-sc02' not in after


def test_step7_is_idempotent(project_dir):
    """Running twice doesn't double-extract or clobber."""
    ref_dir = os.path.join(project_dir, 'reference')
    step7_extract_spine(ref_dir, dry_run=False)
    first = _read_file(os.path.join(ref_dir, 'spine.csv'))

    result = step7_extract_spine(ref_dir, dry_run=False)
    assert result.startswith('skip:')
    second = _read_file(os.path.join(ref_dir, 'spine.csv'))
    assert first == second


def test_step7_skips_when_no_spine_rows(project_dir_gn):
    """A project with no status=spine rows → step7 is a no-op."""
    ref_dir = os.path.join(project_dir_gn, 'reference')
    result = step7_extract_spine(ref_dir, dry_run=False)
    assert result.startswith('skip:')


def test_step7_removes_extracted_id_from_scene_intent(project_dir):
    """The intent row for the moved scene must NOT remain in scene-intent.csv —
    its function column is now carried by spine.csv."""
    ref_dir = os.path.join(project_dir, 'reference')
    step7_extract_spine(ref_dir, dry_run=False)
    with open(os.path.join(ref_dir, 'scene-intent.csv')) as f:
        intent = f.read()
    assert 'act2-sc02|' not in intent


# ---------------------------------------------------------------------------
# step8: architecture extraction
# ---------------------------------------------------------------------------

def test_step8_extracts_architecture_rows(project_dir):
    """status=architecture rows in scenes.csv → architecture.csv with
    structural columns (action_sequel, value_at_stake, etc.) pulled from
    scene-intent.csv."""
    ref_dir = os.path.join(project_dir, 'reference')
    scenes_csv = os.path.join(ref_dir, 'scenes.csv')
    arch_csv = os.path.join(ref_dir, 'architecture.csv')

    # Confirm fixture starting state — act2-sc01 has status=architecture
    with open(scenes_csv) as f:
        assert 'act2-sc01' in f.read()

    result = step8_extract_architecture(ref_dir, dry_run=False)
    assert result.startswith('extract:')
    assert os.path.isfile(arch_csv)
    arch_content = _read_file(arch_csv)
    # Header has spine_event for downstream reference
    assert 'spine_event' in arch_content.splitlines()[0]
    assert 'act2-sc01' in arch_content
    # And removed from scenes.csv
    with open(scenes_csv) as f:
        assert 'act2-sc01' not in f.read()


def test_step8_leaves_spine_event_empty(project_dir):
    """Migration can't determine spine_event references automatically —
    author wires them up after migration."""
    ref_dir = os.path.join(project_dir, 'reference')
    step8_extract_architecture(ref_dir, dry_run=False)
    arch_content = _read_file(os.path.join(ref_dir, 'architecture.csv'))
    rows = arch_content.splitlines()[1:]
    for row in rows:
        cols = row.split('|')
        spine_event_idx = arch_content.splitlines()[0].split('|').index('spine_event')
        assert cols[spine_event_idx] == '', (
            f'spine_event should be empty after migration; got {cols[spine_event_idx]!r}'
        )


def test_step8_is_idempotent(project_dir):
    ref_dir = os.path.join(project_dir, 'reference')
    step8_extract_architecture(ref_dir, dry_run=False)
    first = _read_file(os.path.join(ref_dir, 'architecture.csv'))
    result = step8_extract_architecture(ref_dir, dry_run=False)
    assert result.startswith('skip:')
    assert _read_file(os.path.join(ref_dir, 'architecture.csv')) == first


def test_step8_preserves_briefed_and_mapped_rows(project_dir):
    """Rows with status >= mapped stay in scenes.csv after extraction."""
    ref_dir = os.path.join(project_dir, 'reference')
    step8_extract_architecture(ref_dir, dry_run=False)
    with open(os.path.join(ref_dir, 'scenes.csv')) as f:
        scenes = f.read()
    # Fixture has at least one briefed row and one mapped row
    assert 'briefed' in scenes
    assert 'mapped' in scenes


# ---------------------------------------------------------------------------
# Combined: full migration sequence on the fixture
# ---------------------------------------------------------------------------

def test_step7_drops_orphan_brief_for_moved_id(project_dir):
    """When a spine-status scene has a brief row (e.g., a previously
    drafted scene demoted back to spine), the brief is dropped on
    extraction — not left as an orphan."""
    ref_dir = os.path.join(project_dir, 'reference')
    # Insert a brief row for act2-sc02 (status=spine in the fixture)
    briefs_path = os.path.join(ref_dir, 'scene-briefs.csv')
    with open(briefs_path) as f:
        header_line = f.readline().rstrip('\n')
        existing = f.read()
    cols = header_line.split('|')
    orphan_row = '|'.join(['act2-sc02' if c == 'id' else '' for c in cols])
    with open(briefs_path, 'w') as f:
        f.write(header_line + '\n')
        f.write(existing.rstrip('\n') + '\n' if existing.strip() else '')
        f.write(orphan_row + '\n')

    result = step7_extract_spine(ref_dir, dry_run=False)
    assert 'orphan brief' in result

    with open(briefs_path) as f:
        after = f.read()
    assert 'act2-sc02' not in after, (
        'orphan brief for the moved spine scene should be dropped'
    )


def test_step8_drops_orphan_brief_for_moved_id(project_dir):
    """Same as above for architecture-status moves."""
    ref_dir = os.path.join(project_dir, 'reference')
    briefs_path = os.path.join(ref_dir, 'scene-briefs.csv')
    with open(briefs_path) as f:
        header_line = f.readline().rstrip('\n')
        existing = f.read()
    cols = header_line.split('|')
    orphan_row = '|'.join(['act2-sc01' if c == 'id' else '' for c in cols])
    with open(briefs_path, 'w') as f:
        f.write(header_line + '\n')
        f.write(existing.rstrip('\n') + '\n' if existing.strip() else '')
        f.write(orphan_row + '\n')

    result = step8_extract_architecture(ref_dir, dry_run=False)
    assert 'orphan brief' in result

    with open(briefs_path) as f:
        after = f.read()
    assert 'act2-sc01' not in after


def test_step7_picks_up_stranded_spine_rows_added_between_runs(project_dir):
    """If the author adds a NEW status=spine row to scenes.csv after the
    first migration, a second migrate run should pick it up rather than
    silently skipping because spine.csv already has data."""
    ref_dir = os.path.join(project_dir, 'reference')
    # First run extracts act2-sc02 → spine.csv
    step7_extract_spine(ref_dir, dry_run=False)
    first_spine = _read_file(os.path.join(ref_dir, 'spine.csv'))
    assert 'act2-sc02' in first_spine

    # Author adds a new status=spine row to scenes.csv
    scenes_path = os.path.join(ref_dir, 'scenes.csv')
    with open(scenes_path) as f:
        scenes_header = f.readline().rstrip('\n').split('|')
    new_row = {c: '' for c in scenes_header}
    new_row.update({
        'id': 'late-add-1', 'seq': '99', 'title': 'A new spine event',
        'part': '1', 'pov': 'Dorren Hayle', 'status': 'spine',
    })
    with open(scenes_path, 'a', encoding='utf-8') as f:
        f.write('|'.join(new_row[c] for c in scenes_header) + '\n')

    # Second run: should pick up the stranded row
    result = step7_extract_spine(ref_dir, dry_run=False)
    assert result.startswith('extract:'), (
        f'expected stranded row to be picked up; got {result!r}'
    )

    second_spine = _read_file(os.path.join(ref_dir, 'spine.csv'))
    assert 'late-add-1' in second_spine, (
        'late-added spine row should now be in spine.csv'
    )
    assert 'act2-sc02' in second_spine, (
        'previously-migrated row should still be in spine.csv'
    )


def test_step7_skip_when_truly_idempotent(project_dir):
    """When spine.csv has data AND scenes.csv has no stranded spine rows,
    step 7 reports `skip:already migrated`."""
    ref_dir = os.path.join(project_dir, 'reference')
    step7_extract_spine(ref_dir, dry_run=False)
    result = step7_extract_spine(ref_dir, dry_run=False)
    assert result == 'skip:already migrated'


def test_step8_picks_up_stranded_architecture_rows(project_dir):
    """Symmetric to test_step7_picks_up_stranded_spine_rows."""
    ref_dir = os.path.join(project_dir, 'reference')
    step8_extract_architecture(ref_dir, dry_run=False)

    scenes_path = os.path.join(ref_dir, 'scenes.csv')
    with open(scenes_path) as f:
        scenes_header = f.readline().rstrip('\n').split('|')
    new_row = {c: '' for c in scenes_header}
    new_row.update({
        'id': 'late-arch-1', 'seq': '99', 'title': 'Late arch beat',
        'part': '2', 'pov': 'Dorren Hayle', 'status': 'architecture',
    })
    with open(scenes_path, 'a', encoding='utf-8') as f:
        f.write('|'.join(new_row[c] for c in scenes_header) + '\n')

    result = step8_extract_architecture(ref_dir, dry_run=False)
    assert result.startswith('extract:')
    arch_content = _read_file(os.path.join(ref_dir, 'architecture.csv'))
    assert 'late-arch-1' in arch_content
    assert 'act2-sc01' in arch_content  # earlier run's row still present


def test_full_v1_sequence_on_fixture(project_dir):
    """Run all three steps in order; final state should have spine.csv,
    architecture.csv, story-summary.md, and a reduced scenes.csv."""
    ref_dir = os.path.join(project_dir, 'reference')

    step6_create_story_summary(project_dir, dry_run=False)
    step7_extract_spine(ref_dir, dry_run=False)
    step8_extract_architecture(ref_dir, dry_run=False)

    assert os.path.isfile(os.path.join(ref_dir, 'story-summary.md'))
    assert os.path.isfile(os.path.join(ref_dir, 'spine.csv'))
    assert os.path.isfile(os.path.join(ref_dir, 'architecture.csv'))

    # Re-running the sequence is a no-op
    assert step6_create_story_summary(project_dir, dry_run=False).startswith('skip:')
    assert step7_extract_spine(ref_dir, dry_run=False).startswith('skip:')
    assert step8_extract_architecture(ref_dir, dry_run=False).startswith('skip:')
