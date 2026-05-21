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
