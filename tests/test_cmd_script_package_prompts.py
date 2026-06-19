"""Tests for cmd_script_package's manuscript/page-prompts.md and
manuscript/reference-images.md outputs (issue #260)."""

import os


def _write_page(pages_dir, page_id, scene_id, within, total, body, *,
                references=None):
    fm_refs = ''
    if references:
        fm_refs = 'references_required:\n' + ''.join(
            f'  - {r}\n' for r in references)
    text = (
        "---\n"
        f"page_id: {page_id}\n"
        f"scene_id: {scene_id}\n"
        f"page_within_scene: {within}\n"
        f"total_pages_in_scene: {total}\n"
        f"panel_count: 2\n"
        + fm_refs +
        "---\n\n"
        f"{body}"
    )
    with open(os.path.join(pages_dir, f'{page_id}.md'), 'w') as f:
        f.write(text)


def _chapters():
    return [{'chapter': 1, 'title': 'One', 'heading': 'One',
             'scenes': ['s01-studio']}]


def _scenes_csv(tmp_path):
    ref_dir = tmp_path / 'reference'
    ref_dir.mkdir(exist_ok=True)
    (ref_dir / 'scenes.csv').write_text('id|seq|title\ns01-studio|1|Studio\n')


def test_assemble_page_prompts_concatenates_in_global_page_order(tmp_path):
    from storyforge.cmd_script_package import _assemble_page_prompts
    pages_dir = tmp_path / 'pages'
    pages_dir.mkdir()
    _write_page(str(pages_dir), 's01-p1', 's01-studio', 1, 2,
                '## Panel script\n\n**Panel 1.**\n\n'
                '## Image-generation workflow\n\nFIRST workflow.\n')
    _write_page(str(pages_dir), 's01-p2', 's01-studio', 2, 2,
                '## Panel script\n\n**Panel 1.**\n\n'
                '## Image-generation workflow\n\nSECOND workflow.\n')
    _scenes_csv(tmp_path)
    out = _assemble_page_prompts(str(tmp_path), _chapters())
    assert 'FIRST workflow' in out
    assert 'SECOND workflow' in out
    assert out.index('FIRST workflow') < out.index('SECOND workflow')
    assert 'Global page 1' in out
    assert 'Global page 2' in out
    assert 's01-p1' in out and 's01-p2' in out


def test_assemble_page_prompts_omits_pages_without_workflow(tmp_path):
    from storyforge.cmd_script_package import _assemble_page_prompts
    pages_dir = tmp_path / 'pages'
    pages_dir.mkdir()
    _write_page(str(pages_dir), 's01-p1', 's01-studio', 1, 2,
                '## Image-generation workflow\n\nONLY workflow.\n')
    _write_page(str(pages_dir), 's01-p2', 's01-studio', 2, 2,
                '## Panel script\n\n**Panel 1.**\n')  # no workflow
    _scenes_csv(tmp_path)
    out = _assemble_page_prompts(str(tmp_path), _chapters())
    assert 'ONLY workflow' in out
    assert 's01-p2' not in out


def test_assemble_page_prompts_empty_when_no_workflows(tmp_path):
    from storyforge.cmd_script_package import _assemble_page_prompts
    pages_dir = tmp_path / 'pages'
    pages_dir.mkdir()
    _write_page(str(pages_dir), 's01-p1', 's01-studio', 1, 1,
                '## Panel script\n\n**Panel 1.**\n')
    _scenes_csv(tmp_path)
    assert _assemble_page_prompts(str(tmp_path), _chapters()) == ''


def test_assemble_reference_manifest_dedupes_and_lists_per_page(tmp_path):
    from storyforge.cmd_script_package import _assemble_reference_manifest
    pages_dir = tmp_path / 'pages'
    pages_dir.mkdir()
    _write_page(str(pages_dir), 's01-p1', 's01-studio', 1, 2,
                '## Image-generation workflow\n\nx.\n',
                references=['ref/char.png', 'ref/tone.png'])
    _write_page(str(pages_dir), 's01-p2', 's01-studio', 2, 2,
                '## Image-generation workflow\n\nx.\n',
                references=['ref/char.png', 'ref/page1.png'])  # char.png repeats
    _scenes_csv(tmp_path)
    out = _assemble_reference_manifest(str(tmp_path), _chapters())
    # Deduped gather list at top
    assert '## All reference images (gather these once)' in out
    gather = out.split('## Global page')[0]
    assert gather.count('ref/char.png') == 1  # deduped
    assert 'ref/tone.png' in gather
    assert 'ref/page1.png' in gather
    # Per-page labeled lists
    assert '**Image 1:** ref/char.png' in out
    assert 'Global page 1' in out and 'Global page 2' in out


def test_assemble_reference_manifest_empty_when_no_references(tmp_path):
    from storyforge.cmd_script_package import _assemble_reference_manifest
    pages_dir = tmp_path / 'pages'
    pages_dir.mkdir()
    _write_page(str(pages_dir), 's01-p1', 's01-studio', 1, 1,
                '## Image-generation workflow\n\nx.\n')  # no references
    _scenes_csv(tmp_path)
    assert _assemble_reference_manifest(str(tmp_path), _chapters()) == ''


def test_inventory_lines_are_split_per_file():
    """SF-1/CR-1: page-prompts.md and reference-images.md have independent
    inventory lines so the README documents only files actually written."""
    from storyforge.cmd_script_package import (
        _PAGE_PROMPTS_INVENTORY_LINE, _REFERENCE_IMAGES_INVENTORY_LINE,
    )
    assert 'page-prompts.md' in _PAGE_PROMPTS_INVENTORY_LINE
    assert 'reference-images.md' not in _PAGE_PROMPTS_INVENTORY_LINE
    assert 'GPT Image 2' in _PAGE_PROMPTS_INVENTORY_LINE
    assert 'reference-images.md' in _REFERENCE_IMAGES_INVENTORY_LINE
    assert 'page-prompts.md' not in _REFERENCE_IMAGES_INVENTORY_LINE


# ---------------------------------------------------------------------------
# main() wiring — SF-1 / SF-2 / CR-1 regressions
# ---------------------------------------------------------------------------

def _setup_project(tmp_path, page_bodies):
    """Build a minimal GN project. page_bodies maps page_id -> (frontmatter
    extra lines, body). Returns the project dir."""
    proj = tmp_path / 'proj'
    proj.mkdir()
    (proj / 'storyforge.yaml').write_text(
        'project:\n  medium: graphic-novel\n  title: Test\n'
    )
    ref = proj / 'reference'
    ref.mkdir()
    (ref / 'scenes.csv').write_text(
        'id|seq|title|status\ns01-studio|1|Studio|briefed\n'
    )
    (ref / 'chapter-map.csv').write_text(
        'chapter|title|heading|scenes\n1|One|numbered|s01-studio\n'
    )
    pages = proj / 'pages'
    pages.mkdir()
    for page_id, (fm_extra, body) in page_bodies.items():
        (pages / f'{page_id}.md').write_text(
            "---\n"
            f"page_id: {page_id}\n"
            "scene_id: s01-studio\n"
            "page_within_scene: 1\n"
            "total_pages_in_scene: 1\n"
            "panel_count: 1\n"
            + fm_extra +
            "---\n\n"
            + body
        )
    return str(proj)


def test_reference_manifest_written_even_without_workflow(tmp_path, monkeypatch):
    """SF-1: a page that declares references_required but has no
    `## Image-generation workflow` section yet must still get
    reference-images.md — and page-prompts.md must NOT be written."""
    proj = _setup_project(tmp_path, {
        's01-p1': (
            'references_required:\n  - ref/char.png\n  - ref/tone.png\n',
            '## Panel script\n\n**Panel 1.** Wide.\n',
        ),
    })
    monkeypatch.chdir(proj)
    import os
    from storyforge import cmd_script_package
    cmd_script_package.main([])
    manuscript = os.path.join(proj, 'manuscript')
    assert os.path.isfile(os.path.join(manuscript, 'reference-images.md'))
    assert 'ref/char.png' in open(os.path.join(manuscript, 'reference-images.md')).read()
    assert not os.path.isfile(os.path.join(manuscript, 'page-prompts.md'))
    # README documents reference-images.md but NOT page-prompts.md
    readme = open(os.path.join(manuscript, 'handoff-readme.md')).read()
    assert 'reference-images.md' in readme
    assert 'page-prompts.md' not in readme


def test_skip_notes_logged_when_page_files_present(tmp_path, monkeypatch, capsys):
    """SF-2: when pages exist but no workflow/no references, main() logs a
    NOTE for each skipped artifact instead of silently omitting it."""
    proj = _setup_project(tmp_path, {
        's01-p1': ('', '## Panel script\n\n**Panel 1.** Wide.\n'),
    })
    monkeypatch.chdir(proj)
    import os
    from storyforge import cmd_script_package
    cmd_script_package.main([])
    out = capsys.readouterr().out + capsys.readouterr().err
    assert 'skipping page-prompts.md' in out
    assert 'skipping reference-images.md' in out
    manuscript = os.path.join(proj, 'manuscript')
    assert not os.path.isfile(os.path.join(manuscript, 'page-prompts.md'))
    assert not os.path.isfile(os.path.join(manuscript, 'reference-images.md'))


def test_rendered_pages_inventory_and_count(tmp_path, monkeypatch, capsys):
    """#261: script-package reports an N/M rendered count and adds a
    manuscript/pages/ inventory line to the README when renders exist."""
    proj = _setup_project(tmp_path, {
        's01-p1': ('', '## Panel script\n\n**Panel 1.** Wide.\n'),
    })
    import os
    rdir = os.path.join(proj, 'manuscript', 'pages')
    os.makedirs(rdir)
    open(os.path.join(rdir, 's01-p1.png'), 'wb').write(b'\x89PNG')
    monkeypatch.chdir(proj)
    from storyforge import cmd_script_package
    cmd_script_package.main([])
    out = capsys.readouterr().out
    assert '1/1 pages rendered' in out
    readme = open(os.path.join(proj, 'manuscript', 'handoff-readme.md')).read()
    assert '`pages/`' in readme
    assert '1 of 1 pages are rendered' in readme


def test_orphan_render_warned_by_script_package(tmp_path, monkeypatch, capsys):
    """#261: an orphan PNG (no matching page file) triggers a WARNING."""
    proj = _setup_project(tmp_path, {
        's01-p1': ('', '## Panel script\n\n**Panel 1.** Wide.\n'),
    })
    import os
    rdir = os.path.join(proj, 'manuscript', 'pages')
    os.makedirs(rdir)
    open(os.path.join(rdir, 's09-p9.png'), 'wb').write(b'\x89PNG')
    monkeypatch.chdir(proj)
    from storyforge import cmd_script_package
    cmd_script_package.main([])
    out = capsys.readouterr().out
    assert 'orphan render' in out
    assert 's09-p9.png' in out


def test_orphan_warned_even_when_pages_dir_absent(tmp_path, monkeypatch, capsys):
    """SF-1: orphan renders must surface even when there is no pages/ dir
    (so the bundle and cleanup don't disagree on identical state). The scene
    is mapped via a scene file, not page files."""
    import os
    proj = tmp_path / 'proj'
    proj.mkdir()
    (proj / 'storyforge.yaml').write_text(
        'project:\n  medium: graphic-novel\n  title: Test\n'
    )
    ref = proj / 'reference'
    ref.mkdir()
    (ref / 'scenes.csv').write_text(
        'id|seq|title|status\ns01-studio|1|Studio|drafted\n'
    )
    (ref / 'chapter-map.csv').write_text(
        'chapter|title|heading|scenes\n1|One|numbered|s01-studio\n'
    )
    scenes = proj / 'scenes'
    scenes.mkdir()
    (scenes / 's01-studio.md').write_text(
        '## Page 1 — SPLASH\n\n**Panel 1**\nInline.\n'
    )
    # Orphan render, NO pages/ directory at all
    rdir = proj / 'manuscript' / 'pages'
    rdir.mkdir(parents=True)
    (rdir / 's09-p9.png').write_bytes(b'\x89PNG')
    monkeypatch.chdir(str(proj))
    from storyforge import cmd_script_package
    cmd_script_package.main([])
    out = capsys.readouterr().out
    assert 'orphan render' in out
    assert 's09-p9.png' in out


def test_partial_render_count_uses_both_format_slots(tmp_path, monkeypatch, capsys):
    """TG-2: with 2 pages and 1 render, the count is '1 of 2' / '1/2' — the
    only case that distinguishes the n and total format slots."""
    import os
    proj = _setup_project(tmp_path, {
        's01-p1': ('', '## Panel script\n\n**Panel 1.** Wide.\n'),
        's01-p2': ('', '## Panel script\n\n**Panel 1.** Wide.\n'),
    })
    # scenes.csv / chapter-map from _setup_project map only s01-studio; both
    # pages belong to it (page_id_prefix s01). Render only p1.
    rdir = os.path.join(proj, 'manuscript', 'pages')
    os.makedirs(rdir)
    open(os.path.join(rdir, 's01-p1.png'), 'wb').write(b'\x89PNG')
    monkeypatch.chdir(proj)
    from storyforge import cmd_script_package
    cmd_script_package.main([])
    out = capsys.readouterr().out
    assert '1/2 pages rendered' in out
    readme = open(os.path.join(proj, 'manuscript', 'handoff-readme.md')).read()
    assert '1 of 2 pages are rendered' in readme


def test_no_renders_notes_progress(tmp_path, monkeypatch, capsys):
    """#261: with page files but zero renders, a 0/M NOTE is logged and no
    pages inventory line appears in the README."""
    proj = _setup_project(tmp_path, {
        's01-p1': ('', '## Panel script\n\n**Panel 1.** Wide.\n'),
    })
    monkeypatch.chdir(proj)
    import os
    from storyforge import cmd_script_package
    cmd_script_package.main([])
    out = capsys.readouterr().out
    assert '0/1 pages rendered' in out
    readme = open(os.path.join(proj, 'manuscript', 'handoff-readme.md')).read()
    assert '`pages/`' not in readme


def test_both_files_and_inventory_when_workflow_and_refs_present(tmp_path, monkeypatch):
    """Happy path: workflow + references present → both files written and
    the README names both."""
    proj = _setup_project(tmp_path, {
        's01-p1': (
            'references_required:\n  - ref/char.png\n',
            '## Panel script\n\n**Panel 1.** Wide.\n\n'
            '## Image-generation workflow\n\n**Approach:** whole page.\n',
        ),
    })
    monkeypatch.chdir(proj)
    import os
    from storyforge import cmd_script_package
    cmd_script_package.main([])
    manuscript = os.path.join(proj, 'manuscript')
    assert os.path.isfile(os.path.join(manuscript, 'page-prompts.md'))
    assert os.path.isfile(os.path.join(manuscript, 'reference-images.md'))
    readme = open(os.path.join(manuscript, 'handoff-readme.md')).read()
    assert 'page-prompts.md' in readme
    assert 'reference-images.md' in readme
