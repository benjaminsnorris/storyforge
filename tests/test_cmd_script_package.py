"""Tests for cmd_script_package — GN artist handoff bundle."""

import os
import pytest


SAMPLE_SCRIPT_A = """\
# Scene: the-blank-page

**Target pages:** 2 | **Layout intent:** splash p1, 4-grid p2

---

## Page 1 — SPLASH

**Panel 1**
Comp.

- CAPTION: *Cap A.*

---

## Page 2 — 4-GRID

**Panel 1**
Comp.
"""

SAMPLE_SCRIPT_B = """\
# Scene: shadows-arrive

**Target pages:** 1 | **Layout intent:** 6-grid p1

---

## Page 1 — 6-GRID

**Panel 1**
Comp.

- CAPTION: *Cap B.*
"""


def _setup_drafted_scenes(project_dir_gn):
    """Write fake drafted scenes and update CSV statuses."""
    scenes_dir = os.path.join(project_dir_gn, 'scenes')
    os.makedirs(scenes_dir, exist_ok=True)
    with open(os.path.join(scenes_dir, 'the-blank-page.md'), 'w') as f:
        f.write(SAMPLE_SCRIPT_A)
    with open(os.path.join(scenes_dir, 'shadows-arrive.md'), 'w') as f:
        f.write(SAMPLE_SCRIPT_B)
    from storyforge.csv_cli import update_field
    scenes_csv = os.path.join(project_dir_gn, 'reference', 'scenes.csv')
    update_field(scenes_csv, 'the-blank-page', 'status', 'drafted')
    update_field(scenes_csv, 'shadows-arrive', 'status', 'drafted')


def _setup_chapter_map(project_dir_gn):
    """Write a minimal chapter-map.csv mapping scenes 1-2 into chapter 1."""
    map_path = os.path.join(project_dir_gn, 'reference', 'chapter-map.csv')
    with open(map_path, 'w') as f:
        f.write('chapter|title|heading|scenes\n')
        f.write('1|Opening|numbered-titled|the-blank-page;shadows-arrive\n')


def test_script_package_produces_bundle(project_dir_gn, monkeypatch):
    monkeypatch.chdir(project_dir_gn)
    _setup_drafted_scenes(project_dir_gn)
    _setup_chapter_map(project_dir_gn)
    from storyforge import cmd_script_package
    cmd_script_package.main([])

    bundle = os.path.join(project_dir_gn, 'manuscript')
    assert os.path.isfile(os.path.join(bundle, 'script.md'))
    assert os.path.isfile(os.path.join(bundle, 'visual-references.md'))
    assert os.path.isfile(os.path.join(bundle, 'chapter-map.md'))
    assert os.path.isfile(os.path.join(bundle, 'handoff-readme.md'))


def test_script_package_global_page_numbering(project_dir_gn, monkeypatch):
    """The assembled script renumbers pages globally across scenes."""
    monkeypatch.chdir(project_dir_gn)
    _setup_drafted_scenes(project_dir_gn)
    _setup_chapter_map(project_dir_gn)
    from storyforge import cmd_script_package
    cmd_script_package.main([])

    script_md = open(os.path.join(project_dir_gn, 'manuscript', 'script.md')).read()
    # Scene A has 2 pages, scene B has 1. Globally renumbered: A pages 1-2, B page 3.
    assert '## Page 1 —' in script_md
    assert '## Page 2 —' in script_md
    assert '## Page 3 —' in script_md


def test_script_package_visual_references_extracted(project_dir_gn, monkeypatch):
    monkeypatch.chdir(project_dir_gn)
    _setup_drafted_scenes(project_dir_gn)
    _setup_chapter_map(project_dir_gn)
    from storyforge import cmd_script_package
    cmd_script_package.main([])

    refs = open(os.path.join(project_dir_gn, 'manuscript', 'visual-references.md')).read()
    # Cartographer Visual section content from the fixture
    assert 'Cartographer' in refs
    assert 'spectacles' in refs.lower() or 'silhouette' in refs.lower()
    # World bible content
    assert 'study' in refs.lower() or 'lamplight' in refs.lower()


def test_script_package_fails_when_no_chapter_map(project_dir_gn, monkeypatch):
    """Missing chapter-map.csv is a clear error."""
    monkeypatch.chdir(project_dir_gn)
    _setup_drafted_scenes(project_dir_gn)
    # Note: no chapter map
    from storyforge import cmd_script_package
    with pytest.raises(SystemExit) as exc_info:
        cmd_script_package.main([])
    assert exc_info.value.code != 0


def test_script_package_rejects_novel_projects(project_dir, monkeypatch):
    """Running cmd_script_package on a novel-mode project exits with an error."""
    monkeypatch.chdir(project_dir)
    from storyforge import cmd_script_package
    with pytest.raises(SystemExit) as exc_info:
        cmd_script_package.main([])
    assert exc_info.value.code != 0


def test_renumber_pages_preserves_page_turn_marker():
    """Global page renumbering must not strip the ⟵ PAGE-TURN REVEAL marker."""
    from storyforge.cmd_script_package import _renumber_pages
    text = '## Page 1 — SPLASH ⟵ PAGE-TURN REVEAL\n'
    result, _ = _renumber_pages(text, 5)
    assert result == '## Page 5 — SPLASH ⟵ PAGE-TURN REVEAL\n'


def test_script_package_handles_missing_scene_file(project_dir_gn, monkeypatch):
    """A chapter-map entry referencing a missing scene file produces a placeholder."""
    monkeypatch.chdir(project_dir_gn)
    _setup_drafted_scenes(project_dir_gn)
    # Chapter map references a scene that doesn't exist on disk
    map_path = os.path.join(project_dir_gn, 'reference', 'chapter-map.csv')
    with open(map_path, 'w') as f:
        f.write('chapter|title|heading|scenes\n')
        f.write('1|Opening|numbered-titled|the-blank-page;nonexistent-scene\n')
    # Also need 'nonexistent-scene' to appear in scenes.csv with status='drafted'
    # so the new draft-status check doesn't block it.
    scenes_csv = os.path.join(project_dir_gn, 'reference', 'scenes.csv')
    from storyforge.csv_cli import append_row
    # 16 columns matching the GN scenes.csv header (id|seq|title|part|pov|location|
    # timeline_day|time_of_day|duration|type|status|word_count|target_words|
    # target_pages|panel_count|page_count)
    append_row(scenes_csv, 'nonexistent-scene|99|Missing|1|cartographer|study|1|night|short|action|drafted||||')
    from storyforge import cmd_script_package
    cmd_script_package.main([])
    script_md = open(os.path.join(project_dir_gn, 'manuscript', 'script.md')).read()
    assert 'nonexistent-scene' in script_md
    assert 'not found' in script_md


def test_script_package_rejects_undrafted_scenes(project_dir_gn, monkeypatch):
    """Scenes with status != drafted cause a non-zero exit unless --force is passed."""
    monkeypatch.chdir(project_dir_gn)
    # Write scene files but leave CSV status as 'briefed' (fixture default)
    scenes_dir = os.path.join(project_dir_gn, 'scenes')
    os.makedirs(scenes_dir, exist_ok=True)
    with open(os.path.join(scenes_dir, 'the-blank-page.md'), 'w') as f:
        f.write(SAMPLE_SCRIPT_A)
    with open(os.path.join(scenes_dir, 'shadows-arrive.md'), 'w') as f:
        f.write(SAMPLE_SCRIPT_B)
    _setup_chapter_map(project_dir_gn)
    from storyforge import cmd_script_package
    with pytest.raises(SystemExit) as exc_info:
        cmd_script_package.main([])
    assert exc_info.value.code != 0


def test_script_package_force_bypasses_status_check(project_dir_gn, monkeypatch):
    """--force allows bundling even when scenes are not drafted."""
    monkeypatch.chdir(project_dir_gn)
    scenes_dir = os.path.join(project_dir_gn, 'scenes')
    os.makedirs(scenes_dir, exist_ok=True)
    with open(os.path.join(scenes_dir, 'the-blank-page.md'), 'w') as f:
        f.write(SAMPLE_SCRIPT_A)
    with open(os.path.join(scenes_dir, 'shadows-arrive.md'), 'w') as f:
        f.write(SAMPLE_SCRIPT_B)
    _setup_chapter_map(project_dir_gn)
    from storyforge import cmd_script_package
    cmd_script_package.main(['--force'])
    bundle = os.path.join(project_dir_gn, 'manuscript')
    assert os.path.isfile(os.path.join(bundle, 'script.md'))
