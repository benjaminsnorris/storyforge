"""Tests for graphic-novel schema columns and medium-aware validation."""

import os
import pytest

from storyforge.schema import COLUMN_SCHEMA, validate_schema


GN_SCENES_COLUMNS = ('target_pages', 'panel_count', 'page_count')
GN_BRIEFS_COLUMNS = (
    'page_layout', 'panel_breakdown', 'visual_keywords',
    'page_turn_beats', 'caption_strategy',
)


@pytest.mark.parametrize('column', GN_SCENES_COLUMNS)
def test_gn_scenes_columns_defined(column):
    assert column in COLUMN_SCHEMA, f'{column} missing from COLUMN_SCHEMA'
    assert COLUMN_SCHEMA[column]['file'] == 'scenes.csv'


@pytest.mark.parametrize('column', GN_BRIEFS_COLUMNS)
def test_gn_briefs_columns_defined(column):
    assert column in COLUMN_SCHEMA, f'{column} missing from COLUMN_SCHEMA'
    assert COLUMN_SCHEMA[column]['file'] == 'scene-briefs.csv'


def test_target_pages_is_integer():
    assert COLUMN_SCHEMA['target_pages']['type'] == 'integer'


def test_panel_count_is_integer():
    assert COLUMN_SCHEMA['panel_count']['type'] == 'integer'


def test_page_count_is_integer():
    assert COLUMN_SCHEMA['page_count']['type'] == 'integer'


def test_gn_brief_text_columns_are_free_text():
    for col in GN_BRIEFS_COLUMNS:
        assert COLUMN_SCHEMA[col]['type'] == 'free_text', (
            f'{col} should be free_text in v1 (extensible later)'
        )


import shutil


@pytest.fixture
def gn_project_dir(tmp_path, fixture_dir):
    """A novel fixture copied and flipped to graphic-novel mode.

    Intentionally distinct from ``project_dir_gn`` (which uses the dedicated
    GN fixture with target_pages populated). This fixture starts from the
    novel fixture's data — which has target_words but no target_pages — so
    that GN-mode validation will surface the missing-target_pages failure
    being asserted below.
    """
    dest = tmp_path / 'gn-project'
    shutil.copytree(fixture_dir, dest)
    yaml_path = dest / 'storyforge.yaml'
    content = yaml_path.read_text()
    yaml_path.write_text(
        content.replace('project:\n', 'project:\n  medium: graphic-novel\n', 1)
    )
    return str(dest)


def test_validate_schema_gn_flags_missing_target_pages(gn_project_dir):
    """In graphic-novel mode, a scene with no target_pages but a target_words
    value should be flagged."""
    ref_dir = os.path.join(gn_project_dir, 'reference')
    result = validate_schema(ref_dir, gn_project_dir)
    # At least one scene should fail because target_pages is missing
    failing_columns = {e['column'] for e in result.get('errors', [])}
    assert 'target_pages' in failing_columns


def test_validate_schema_novel_does_not_require_target_pages(fixture_dir):
    """In novel mode, target_pages absence is fine — target_words is what matters."""
    ref_dir = os.path.join(fixture_dir, 'reference')
    result = validate_schema(ref_dir, fixture_dir)
    failing_columns = {e['column'] for e in result.get('errors', [])}
    assert 'target_pages' not in failing_columns
