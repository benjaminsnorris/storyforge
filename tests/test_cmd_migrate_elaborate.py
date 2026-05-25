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
