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
