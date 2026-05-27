"""Tests for cmd_extract_gn --from-pages — sync metadata from page files."""

import os
import textwrap

import pytest


def _seed_gn_project(project_dir: str) -> None:
    """Minimal GN project with one scene row and two page files."""
    with open(os.path.join(project_dir, 'storyforge.yaml'), 'w') as f:
        f.write('project:\n  title: Test\n  medium: graphic-novel\n  '
                'coaching_level: full\n')

    ref = os.path.join(project_dir, 'reference')
    os.makedirs(ref, exist_ok=True)
    with open(os.path.join(ref, 'scenes.csv'), 'w') as f:
        f.write('id|title|status|panel_count|page_count\n')
        f.write('s01-studio|Studio|briefed||\n')

    pages = os.path.join(project_dir, 'pages')
    os.makedirs(pages, exist_ok=True)
    with open(os.path.join(pages, 's01-p1.md'), 'w') as f:
        f.write(textwrap.dedent("""\
            ---
            page_id: s01-p1
            scene_id: s01-studio
            page_within_scene: 1
            total_pages_in_scene: 2
            panel_count: 2
            characters_present: [lucien-vey]
            ---

            ## Panel script
            body
            """))
    with open(os.path.join(pages, 's01-p2.md'), 'w') as f:
        f.write(textwrap.dedent("""\
            ---
            page_id: s01-p2
            scene_id: s01-studio
            page_within_scene: 2
            total_pages_in_scene: 2
            panel_count: 4
            characters_present: [lucien-vey, mirelle-ash]
            ---

            ## Panel script
            body
            """))


def test_from_pages_updates_panel_count_and_page_count(tmp_path, monkeypatch):
    _seed_gn_project(str(tmp_path))
    monkeypatch.chdir(str(tmp_path))
    from storyforge.cmd_extract_gn import main
    main(['--from-pages'])

    from storyforge.csv_cli import get_field
    scenes_csv = str(tmp_path / 'reference' / 'scenes.csv')
    assert get_field(scenes_csv, 's01-studio', 'panel_count') == '6'
    assert get_field(scenes_csv, 's01-studio', 'page_count') == '2'


def test_from_pages_dry_run_does_not_write(tmp_path, monkeypatch):
    _seed_gn_project(str(tmp_path))
    monkeypatch.chdir(str(tmp_path))
    from storyforge.cmd_extract_gn import main
    main(['--from-pages', '--dry-run'])

    from storyforge.csv_cli import get_field
    scenes_csv = str(tmp_path / 'reference' / 'scenes.csv')
    assert get_field(scenes_csv, 's01-studio', 'panel_count') == ''


def test_from_pages_no_pages_dir_errors(tmp_path, monkeypatch):
    with open(tmp_path / 'storyforge.yaml', 'w') as f:
        f.write('project:\n  title: Test\n  medium: graphic-novel\n')
    monkeypatch.chdir(str(tmp_path))
    from storyforge.cmd_extract_gn import main
    with pytest.raises(SystemExit):
        main(['--from-pages'])
