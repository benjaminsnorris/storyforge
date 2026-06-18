"""Tests for the rendered-page helpers in pages.py (issue #261)."""

import os


def _write_page(pages_dir, page_id):
    with open(os.path.join(pages_dir, f'{page_id}.md'), 'w') as f:
        f.write(
            f"---\npage_id: {page_id}\nscene_id: s01\npage_within_scene: 1\n"
            f"total_pages_in_scene: 1\npanel_count: 1\n---\n\nbody\n"
        )


def _setup(tmp_path, page_ids, rendered):
    proj = tmp_path / 'proj'
    pages = proj / 'pages'
    pages.mkdir(parents=True)
    rdir = proj / 'manuscript' / 'pages'
    rdir.mkdir(parents=True)
    for pid in page_ids:
        _write_page(str(pages), pid)
    for png in rendered:
        (rdir / png).write_bytes(b'\x89PNG')
    return str(proj)


def test_rendered_page_path_is_under_manuscript_pages(tmp_path):
    from storyforge.pages import rendered_page_path
    p = rendered_page_path(str(tmp_path), 's01-p2')
    assert p.endswith(os.path.join('manuscript', 'pages', 's01-p2.png'))


def test_list_rendered_pages_empty_when_dir_absent(tmp_path):
    from storyforge.pages import list_rendered_pages
    assert list_rendered_pages(str(tmp_path)) == []


def test_list_rendered_pages_filters_and_sorts(tmp_path):
    from storyforge.pages import list_rendered_pages
    proj = _setup(tmp_path, [], ['s01-p2.png', 's01-p1.png'])
    # a non-png and a hidden file are ignored
    rdir = os.path.join(proj, 'manuscript', 'pages')
    open(os.path.join(rdir, 'notes.txt'), 'w').write('x')
    open(os.path.join(rdir, '.DS_Store'), 'w').write('x')
    result = [os.path.basename(p) for p in list_rendered_pages(proj)]
    assert result == ['s01-p1.png', 's01-p2.png']


def test_render_report_splits_rendered_unrendered_orphans(tmp_path):
    from storyforge.pages import page_render_report
    proj = _setup(tmp_path, ['s01-p1', 's01-p2'],
                  ['s01-p1.png', 's09-p9.png'])
    r = page_render_report(proj)
    assert r['rendered'] == ['s01-p1']
    assert r['unrendered'] == ['s01-p2']
    assert r['orphans'] == ['s09-p9.png']


def test_render_report_all_empty_when_no_pages_or_renders(tmp_path):
    from storyforge.pages import page_render_report
    proj = _setup(tmp_path, [], [])
    r = page_render_report(proj)
    assert r == {'rendered': [], 'unrendered': [], 'orphans': []}


def test_render_report_no_manuscript_dir(tmp_path):
    """All page files unrendered, no orphans, when manuscript/pages/ absent."""
    from storyforge.pages import page_render_report
    proj = tmp_path / 'proj'
    (proj / 'pages').mkdir(parents=True)
    _write_page(str(proj / 'pages'), 's01-p1')
    r = page_render_report(str(proj))
    assert r['rendered'] == []
    assert r['unrendered'] == ['s01-p1']
    assert r['orphans'] == []
