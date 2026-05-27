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


def test_from_pages_errors_when_target_columns_missing(tmp_path, monkeypatch, capsys):
    """Regression for CR-1/SF-5: csv_cli.update_field silently no-ops on a
    missing column. _run_from_pages must fail loudly if panel_count or
    page_count is not in scenes.csv, so projects that haven't run cleanup
    don't get a false-success message while writing nothing."""
    with open(tmp_path / 'storyforge.yaml', 'w') as f:
        f.write('project:\n  title: Test\n  medium: graphic-novel\n')
    ref = tmp_path / 'reference'
    ref.mkdir()
    # scenes.csv WITHOUT panel_count/page_count columns
    (ref / 'scenes.csv').write_text('id|title|status\ns01-studio|S|briefed\n')
    pages = tmp_path / 'pages'
    pages.mkdir()
    (pages / 's01-p1.md').write_text(
        '---\npage_id: s01-p1\nscene_id: s01-studio\n'
        'page_within_scene: 1\ntotal_pages_in_scene: 1\npanel_count: 2\n---\n'
    )
    monkeypatch.chdir(str(tmp_path))
    from storyforge.cmd_extract_gn import main
    with pytest.raises(SystemExit):
        main(['--from-pages'])
    out = capsys.readouterr().out
    assert 'panel_count' in out
    assert 'page_count' in out


def test_from_pages_warns_when_panel_count_missing(tmp_path, monkeypatch, capsys):
    """SF-4: a page without panel_count is silently treated as 0; the
    aggregator should surface this so authors notice partial sums."""
    _seed_gn_project(str(tmp_path))
    # Add a page with no panel_count
    pages = tmp_path / 'pages'
    (pages / 's01-p3.md').write_text(
        '---\npage_id: s01-p3\nscene_id: s01-studio\n'
        'page_within_scene: 3\ntotal_pages_in_scene: 3\n---\n\nbody\n'
    )
    # Update total_pages_in_scene in the other files
    monkeypatch.chdir(str(tmp_path))
    from storyforge.cmd_extract_gn import main
    main(['--from-pages'])
    out = capsys.readouterr().out
    assert 'lack a valid integer panel_count' in out
    assert 's01-p3.md' in out


def test_from_pages_warns_when_scene_id_missing(tmp_path, monkeypatch, capsys):
    """T-6: page with no scene_id field surfaces a WARNING and is skipped."""
    with open(tmp_path / 'storyforge.yaml', 'w') as f:
        f.write('project:\n  title: Test\n  medium: graphic-novel\n')
    ref = tmp_path / 'reference'
    ref.mkdir()
    (ref / 'scenes.csv').write_text(
        'id|title|status|panel_count|page_count\n'
        's01-studio|S|briefed||\n'
    )
    pages = tmp_path / 'pages'
    pages.mkdir()
    (pages / 's01-p1.md').write_text(
        '---\npage_id: s01-p1\n'  # no scene_id
        'page_within_scene: 1\ntotal_pages_in_scene: 1\npanel_count: 2\n---\n'
    )
    monkeypatch.chdir(str(tmp_path))
    from storyforge.cmd_extract_gn import main
    main(['--from-pages'])
    out = capsys.readouterr().out
    assert 'has no scene_id' in out


def test_from_pages_warns_when_scene_id_unknown(tmp_path, monkeypatch, capsys):
    """T-6: page references a scene_id not in scenes.csv → WARNING + skip."""
    with open(tmp_path / 'storyforge.yaml', 'w') as f:
        f.write('project:\n  title: Test\n  medium: graphic-novel\n')
    ref = tmp_path / 'reference'
    ref.mkdir()
    (ref / 'scenes.csv').write_text(
        'id|title|status|panel_count|page_count\n'
        's01-studio|S|briefed||\n'
    )
    pages = tmp_path / 'pages'
    pages.mkdir()
    (pages / 's99-p1.md').write_text(
        '---\npage_id: s99-p1\nscene_id: s99-ghost\n'
        'page_within_scene: 1\ntotal_pages_in_scene: 1\npanel_count: 2\n---\n'
    )
    monkeypatch.chdir(str(tmp_path))
    from storyforge.cmd_extract_gn import main
    main(['--from-pages'])
    out = capsys.readouterr().out
    assert 's99-ghost' in out
    assert 'not in' in out and 'scenes.csv' in out
