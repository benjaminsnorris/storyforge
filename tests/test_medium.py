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


def test_cmd_validate_passes_on_gn_fixture(project_dir_gn, monkeypatch):
    """Running `storyforge validate` on the GN fixture exits 0."""
    monkeypatch.chdir(project_dir_gn)
    from storyforge import cmd_validate
    with pytest.raises(SystemExit) as exc_info:
        cmd_validate.main(['--quiet'])
    assert exc_info.value.code == 0


def test_cmd_cleanup_csv_passes_on_gn_fixture(project_dir_gn, monkeypatch, capsys):
    """`storyforge cleanup --csv` does not flag GN-specific columns as unexpected."""
    monkeypatch.chdir(project_dir_gn)
    from storyforge import cmd_cleanup
    # cmd_cleanup.main returns normally (no sys.exit) on --csv
    cmd_cleanup.main(['--csv'])
    captured = capsys.readouterr()
    # GN-only columns must not be flagged as unexpected extras — they are valid
    # in graphic-novel mode and the cleanup report should know that.
    assert 'target_pages' not in captured.out or 'unexpected' not in captured.out
    assert 'panel_count' not in captured.out or 'unexpected' not in captured.out
    assert 'page_layout' not in captured.out or 'unexpected' not in captured.out
    # Also: GN fixture does not have characters/locations/etc. — they are optional
    # in GN mode, so should not appear as warnings.
    assert 'characters.csv does not exist' not in captured.out
    assert 'locations.csv does not exist' not in captured.out


def test_hone_gn_flags_missing_panel_breakdown(project_dir_gn, monkeypatch):
    """A graphic-novel brief missing panel_breakdown is flagged by hone."""
    from storyforge.csv_cli import update_field
    briefs = os.path.join(project_dir_gn, 'reference', 'scene-briefs.csv')
    update_field(briefs, 'the-blank-page', 'panel_breakdown', '')

    from storyforge.hone import diagnose_briefs
    findings = diagnose_briefs(project_dir_gn)
    flagged = [f for f in findings if f.get('scene_id') == 'the-blank-page'
               and f.get('field') == 'panel_breakdown']
    assert flagged, 'expected a panel_breakdown finding for the-blank-page'


def test_hone_gn_flags_missing_page_layout(project_dir_gn, monkeypatch):
    """A graphic-novel brief missing page_layout is flagged by hone."""
    from storyforge.csv_cli import update_field
    briefs = os.path.join(project_dir_gn, 'reference', 'scene-briefs.csv')
    update_field(briefs, 'shadows-arrive', 'page_layout', '')

    from storyforge.hone import diagnose_briefs
    findings = diagnose_briefs(project_dir_gn)
    flagged = [f for f in findings if f.get('scene_id') == 'shadows-arrive'
               and f.get('field') == 'page_layout']
    assert flagged, 'expected a page_layout finding for shadows-arrive'


def test_hone_novel_does_not_flag_panel_breakdown(project_dir, monkeypatch):
    """Novel-mode briefs are not checked for panel_breakdown."""
    from storyforge.hone import diagnose_briefs
    findings = diagnose_briefs(project_dir)
    panel_findings = [f for f in findings if f.get('field') == 'panel_breakdown']
    assert not panel_findings
