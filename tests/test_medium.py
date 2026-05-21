"""Tests for project.medium handling."""

import os

import pytest

from storyforge.common import get_medium


def test_get_medium_returns_novel_when_field_absent(project_dir):
    """A project without project.medium defaults to 'novel'."""
    yaml_path = os.path.join(project_dir, 'storyforge.yaml')
    with open(yaml_path) as f:
        content = f.read()
    assert 'medium:' not in content
    assert get_medium(project_dir) == 'novel'


def test_get_medium_returns_graphic_novel_when_set(project_dir):
    """A project with project.medium: graphic-novel returns that value."""
    yaml_path = os.path.join(project_dir, 'storyforge.yaml')
    with open(yaml_path) as f:
        content = f.read()
    # Insert under `project:` block
    content = content.replace(
        'project:\n',
        'project:\n  medium: graphic-novel\n',
        1,
    )
    with open(yaml_path, 'w') as f:
        f.write(content)
    assert get_medium(project_dir) == 'graphic-novel'


def test_get_medium_returns_novel_for_explicit_novel(project_dir):
    """A project with project.medium: novel returns 'novel'."""
    yaml_path = os.path.join(project_dir, 'storyforge.yaml')
    with open(yaml_path) as f:
        content = f.read()
    content = content.replace(
        'project:\n',
        'project:\n  medium: novel\n',
        1,
    )
    with open(yaml_path, 'w') as f:
        f.write(content)
    assert get_medium(project_dir) == 'novel'


def test_get_medium_returns_novel_for_unrecognized_value(project_dir):
    """An unrecognized medium value logs a warning and defaults to 'novel'."""
    yaml_path = os.path.join(project_dir, 'storyforge.yaml')
    with open(yaml_path) as f:
        content = f.read()
    content = content.replace('project:\n', 'project:\n  medium: screenplay\n', 1)
    with open(yaml_path, 'w') as f:
        f.write(content)
    assert get_medium(project_dir) == 'novel'


def test_gn_fixture_loads(fixture_dir_gn):
    """The graphic-novel fixture exists and is graphic-novel mode."""
    assert os.path.isfile(os.path.join(fixture_dir_gn, 'storyforge.yaml'))
    assert get_medium(fixture_dir_gn) == 'graphic-novel'


def test_gn_fixture_schema_passes(fixture_dir_gn):
    """The graphic-novel fixture passes schema validation."""
    from storyforge.schema import validate_schema
    ref_dir = os.path.join(fixture_dir_gn, 'reference')
    result = validate_schema(ref_dir, fixture_dir_gn)
    # The fixture should pass — failed count must be 0
    assert result['failed'] == 0, f"Fixture has schema failures: {result.get('errors')}"
