"""Tests for storyforge.pages — GN per-page file parsing and validation."""

import os
import pytest


def test_page_id_prefix_extracts_s_prefix():
    from storyforge.pages import page_id_prefix_for_scene
    assert page_id_prefix_for_scene('s01-studio-finalization') == 's01'
    assert page_id_prefix_for_scene('s10-arrival') == 's10'


def test_page_id_prefix_falls_back_to_full_id():
    from storyforge.pages import page_id_prefix_for_scene
    assert page_id_prefix_for_scene('the-blank-page') == 'the-blank-page'
    assert page_id_prefix_for_scene('cartographer-speaks') == 'cartographer-speaks'


def test_page_id_prefix_no_dash_after_s_prefix():
    from storyforge.pages import page_id_prefix_for_scene
    # 'salt-flats' — 's' followed by non-digit; not the sN- pattern
    assert page_id_prefix_for_scene('salt-flats') == 'salt-flats'


def test_page_filename_for_combines_prefix_and_number():
    from storyforge.pages import page_filename_for
    assert page_filename_for('s01-studio-finalization', 1) == 's01-p1.md'
    assert page_filename_for('s01-studio-finalization', 12) == 's01-p12.md'
    assert page_filename_for('the-blank-page', 1) == 'the-blank-page-p1.md'


SAMPLE_FRONTMATTER = """\
---
page_id: s01-p1
scene_id: s01-studio-finalization
scene_title: Studio Finalization
page_within_scene: 1
total_pages_in_scene: 5
spread_position: opening recto (book's first page)
panel_count: 2
characters_present: [lucien-vey, mirelle-ash]
location: archive-studio
timeline: day 1, evening
canonical_blocks_embedded:
  - reference/canon/style-foundation.md
  - reference/canon/lighting-laws.md
prompt_iteration: 6
schema_version: 2
---

# Page s01-p1 — Studio Finalization, page 1 of 5

## Scene context

Some prose.
"""


def test_parse_frontmatter_required_fields(tmp_path):
    from storyforge.pages import parse_page_file
    path = tmp_path / 's01-p1.md'
    path.write_text(SAMPLE_FRONTMATTER)
    page = parse_page_file(str(path))
    assert page is not None
    assert page['page_id'] == 's01-p1'
    assert page['scene_id'] == 's01-studio-finalization'
    assert page['page_within_scene'] == 1
    assert page['total_pages_in_scene'] == 5
    assert page['panel_count'] == 2


def test_parse_frontmatter_inline_list(tmp_path):
    from storyforge.pages import parse_page_file
    path = tmp_path / 's01-p1.md'
    path.write_text(SAMPLE_FRONTMATTER)
    page = parse_page_file(str(path))
    assert page['characters_present'] == ['lucien-vey', 'mirelle-ash']


def test_parse_frontmatter_recommended_fields(tmp_path):
    from storyforge.pages import parse_page_file
    path = tmp_path / 's01-p1.md'
    path.write_text(SAMPLE_FRONTMATTER)
    page = parse_page_file(str(path))
    assert page['spread_position'] == "opening recto (book's first page)"
    assert page['location'] == 'archive-studio'
    assert page['timeline'] == 'day 1, evening'


def test_parse_frontmatter_extras_collected(tmp_path):
    """Unknown keys go into the 'extra' dict — forward-compatible with
    canonical-blocks and modular-prompt sibling issues."""
    from storyforge.pages import parse_page_file
    path = tmp_path / 's01-p1.md'
    path.write_text(SAMPLE_FRONTMATTER)
    page = parse_page_file(str(path))
    assert page['extra']['scene_title'] == 'Studio Finalization'
    assert page['extra']['prompt_iteration'] == '6'
    assert page['extra']['schema_version'] == '2'


def test_parse_frontmatter_block_list(tmp_path):
    """Block-style lists (key:\\n  - item) parse into Python lists."""
    from storyforge.pages import parse_page_file
    path = tmp_path / 's01-p1.md'
    path.write_text(SAMPLE_FRONTMATTER)
    page = parse_page_file(str(path))
    assert 'canonical_blocks_embedded' in page['extra_lists']
    assert page['extra_lists']['canonical_blocks_embedded'] == [
        'reference/canon/style-foundation.md',
        'reference/canon/lighting-laws.md',
    ]


def test_parse_page_file_no_frontmatter_returns_none(tmp_path):
    from storyforge.pages import parse_page_file
    path = tmp_path / 'noframe.md'
    path.write_text('# Just a heading\n\nNo frontmatter.\n')
    assert parse_page_file(str(path)) is None


def test_parse_page_file_missing_file_returns_none(tmp_path):
    from storyforge.pages import parse_page_file
    assert parse_page_file(str(tmp_path / 'nope.md')) is None


def test_parse_frontmatter_handles_inline_comment(tmp_path):
    """Trailing # comments on list items are stripped (matches the
    ashes-PR-8 example: '  - path/to/x.md  # in page-blocking prompt only')."""
    from storyforge.pages import parse_page_file
    path = tmp_path / 's01-p1.md'
    path.write_text(
        "---\n"
        "page_id: s01-p1\n"
        "scene_id: s01\n"
        "page_within_scene: 1\n"
        "total_pages_in_scene: 1\n"
        "panel_count: 1\n"
        "canonical_blocks_embedded:\n"
        "  - reference/canon/a.md  # used in blocking prompt only\n"
        "  - reference/canon/b.md\n"
        "---\n\nbody\n"
    )
    page = parse_page_file(str(path))
    assert page['extra_lists']['canonical_blocks_embedded'] == [
        'reference/canon/a.md',
        'reference/canon/b.md',
    ]


def _write_page(path, page_id, scene_id, within, total, panels):
    path.write_text(
        f"---\n"
        f"page_id: {page_id}\n"
        f"scene_id: {scene_id}\n"
        f"page_within_scene: {within}\n"
        f"total_pages_in_scene: {total}\n"
        f"panel_count: {panels}\n"
        f"---\n\nbody\n"
    )


def test_list_page_files_returns_empty_when_no_pages_dir(tmp_path):
    from storyforge.pages import list_page_files
    assert list_page_files(str(tmp_path)) == []


def test_list_page_files_sorted_and_filters_non_md(tmp_path):
    from storyforge.pages import list_page_files
    pages = tmp_path / 'pages'
    pages.mkdir()
    (pages / 's01-p1.md').write_text('---\npage_id: s01-p1\n---\n')
    (pages / 's01-p2.md').write_text('---\npage_id: s01-p2\n---\n')
    (pages / 'readme.txt').write_text('skip me')
    (pages / '.hidden.md').write_text('skip me too')
    result = list_page_files(str(tmp_path))
    assert [os.path.basename(p) for p in result] == ['s01-p1.md', 's01-p2.md']


def test_pages_for_scene_groups_by_prefix(tmp_path):
    """pages_for_scene returns parsed page files for one scene, sorted by
    page_within_scene. Matches by the page_id_prefix_for_scene convention,
    NOT by scene_id field — the prefix is the on-disk filename rule."""
    from storyforge.pages import pages_for_scene
    pages = tmp_path / 'pages'
    pages.mkdir()
    _write_page(pages / 's01-p2.md', 's01-p2', 's01-studio-finalization', 2, 3, 4)
    _write_page(pages / 's01-p1.md', 's01-p1', 's01-studio-finalization', 1, 3, 2)
    _write_page(pages / 's01-p3.md', 's01-p3', 's01-studio-finalization', 3, 3, 6)
    _write_page(pages / 's02-p1.md', 's02-p1', 's02-other', 1, 1, 1)
    result = pages_for_scene(str(tmp_path), 's01-studio-finalization')
    assert [p['page_id'] for p in result] == ['s01-p1', 's01-p2', 's01-p3']


def test_validate_page_file_clean_passes(tmp_path):
    """A page file with all required fields and correct filename/page_id
    match returns no findings."""
    from storyforge.pages import validate_page_file
    path = tmp_path / 's01-p1.md'
    _write_page(path, 's01-p1', 's01-studio-finalization', 1, 5, 2)
    assert validate_page_file(str(path)) == []


def test_validate_missing_required_field(tmp_path):
    """A missing required field surfaces a 'missing_field' finding."""
    from storyforge.pages import validate_page_file
    path = tmp_path / 's01-p1.md'
    path.write_text(
        "---\n"
        "page_id: s01-p1\n"
        "scene_id: s01-studio-finalization\n"
        "total_pages_in_scene: 5\n"
        "panel_count: 2\n"
        "---\n\nbody\n"
    )
    findings = validate_page_file(str(path))
    assert any(f['kind'] == 'missing_field'
               and f['field'] == 'page_within_scene' for f in findings)


def test_validate_filename_mismatch(tmp_path):
    """Filename stem must equal page_id."""
    from storyforge.pages import validate_page_file
    path = tmp_path / 's01-p7.md'
    _write_page(path, 's01-p1', 's01', 1, 5, 2)
    findings = validate_page_file(str(path))
    assert any(f['kind'] == 'filename_page_id_mismatch' for f in findings)


def test_validate_page_within_scene_out_of_range(tmp_path):
    """page_within_scene must be in [1, total_pages_in_scene]."""
    from storyforge.pages import validate_page_file
    path = tmp_path / 's01-p9.md'
    _write_page(path, 's01-p9', 's01', 9, 5, 2)
    findings = validate_page_file(str(path))
    assert any(f['kind'] == 'page_within_scene_out_of_range' for f in findings)


def test_validate_no_frontmatter(tmp_path):
    """A file without frontmatter surfaces 'no_frontmatter'."""
    from storyforge.pages import validate_page_file
    path = tmp_path / 's01-p1.md'
    path.write_text('# No frontmatter here\n')
    findings = validate_page_file(str(path))
    assert findings == [{'kind': 'no_frontmatter', 'path': str(path)}]


def test_extract_panel_script_body(tmp_path):
    """Extract the '## Panel script' section text only."""
    from storyforge.pages import extract_panel_script
    text = (
        "---\npage_id: s01-p1\n---\n\n"
        "# Page heading\n\n"
        "## Scene context\n\nSome context.\n\n"
        "## Page architecture\n\n### Intent\nThings.\n\n"
        "## Panel script\n\n"
        "**Panel 1.** Wide. A studio.\n\n*No dialogue.*\n\n"
        "**Panel 2.** Close. A hand.\n\n"
        "## Image-generation workflow\n\nshould not appear\n"
    )
    path = tmp_path / 's01-p1.md'
    path.write_text(text)
    result = extract_panel_script(str(path))
    assert '**Panel 1.**' in result
    assert '**Panel 2.**' in result
    assert 'A studio' in result
    assert 'should not appear' not in result
    assert 'Scene context' not in result


def test_extract_panel_script_missing_section_returns_empty(tmp_path):
    from storyforge.pages import extract_panel_script
    path = tmp_path / 's01-p1.md'
    path.write_text('---\npage_id: s01-p1\n---\n\n# Heading\n\nno script section\n')
    assert extract_panel_script(str(path)) == ''


def test_extract_panel_script_keeps_page_headers(tmp_path):
    """`## Page N — LAYOUT` is part of the script format; the extractor
    must not treat those as section boundaries (regression — script-package
    needs the page headers preserved so global renumbering can find them)."""
    from storyforge.pages import extract_panel_script
    path = tmp_path / 's01-p1.md'
    path.write_text(
        "---\npage_id: s01-p1\n---\n\n"
        "## Panel script\n\n"
        "## Page 1 — SPLASH\n\n**Panel 1**\nWide.\n\n"
        "## Image-generation workflow\n\nstops here\n"
    )
    result = extract_panel_script(str(path))
    assert '## Page 1 — SPLASH' in result
    assert 'Wide.' in result
    assert 'stops here' not in result
