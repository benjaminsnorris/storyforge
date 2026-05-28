"""Tests for cmd_script_package's manuscript/page-blocking-prompts.md
output (issue #252)."""

import os
import textwrap


def _write_page(pages_dir, page_id, scene_id, within, total, body):
    text = (
        "---\n"
        f"page_id: {page_id}\n"
        f"scene_id: {scene_id}\n"
        f"page_within_scene: {within}\n"
        f"total_pages_in_scene: {total}\n"
        f"panel_count: 2\n"
        "---\n\n"
        f"{body}"
    )
    with open(os.path.join(pages_dir, f'{page_id}.md'), 'w') as f:
        f.write(text)


def test_assemble_blocking_prompts_concatenates_in_global_page_order(tmp_path):
    from storyforge.cmd_script_package import _assemble_blocking_prompts
    pages_dir = tmp_path / 'pages'
    pages_dir.mkdir()
    _write_page(str(pages_dir), 's01-p1', 's01-studio', 1, 2,
                '## Page-blocking prompt\n\nFIRST blocking.\n\n'
                '## Panel script\n\n**Panel 1.**\n')
    _write_page(str(pages_dir), 's01-p2', 's01-studio', 2, 2,
                '## Page-blocking prompt\n\nSECOND blocking.\n\n'
                '## Panel script\n\n**Panel 1.**\n')
    chapters = [{
        'chapter': 1, 'title': 'One', 'heading': 'One',
        'scenes': ['s01-studio'],
    }]
    ref_dir = tmp_path / 'reference'
    ref_dir.mkdir()
    (ref_dir / 'scenes.csv').write_text(
        'id|seq|title\ns01-studio|1|Studio\n'
    )
    out = _assemble_blocking_prompts(str(tmp_path), chapters)
    # Both prompts present in global page order
    assert 'FIRST blocking' in out
    assert 'SECOND blocking' in out
    assert out.index('FIRST blocking') < out.index('SECOND blocking')
    # Global page numbering (page 1, page 2)
    assert 'Global page 1' in out
    assert 'Global page 2' in out
    # Page ids in headers
    assert 's01-p1' in out
    assert 's01-p2' in out


def test_assemble_blocking_prompts_omits_pages_without_blocking_section(tmp_path):
    from storyforge.cmd_script_package import _assemble_blocking_prompts
    pages_dir = tmp_path / 'pages'
    pages_dir.mkdir()
    _write_page(str(pages_dir), 's01-p1', 's01-studio', 1, 2,
                '## Page-blocking prompt\n\nONLY blocking.\n\n## Panel script\n\n**Panel 1.**\n')
    _write_page(str(pages_dir), 's01-p2', 's01-studio', 2, 2,
                '## Panel script\n\n**Panel 1.**\n')  # no blocking prompt
    chapters = [{
        'chapter': 1, 'title': 'One', 'heading': 'One',
        'scenes': ['s01-studio'],
    }]
    ref_dir = tmp_path / 'reference'
    ref_dir.mkdir()
    (ref_dir / 'scenes.csv').write_text(
        'id|seq|title\ns01-studio|1|Studio\n'
    )
    out = _assemble_blocking_prompts(str(tmp_path), chapters)
    assert 'ONLY blocking' in out
    # The page without a blocking prompt does NOT appear as a header
    assert 's01-p2' not in out


def test_assemble_blocking_prompts_returns_empty_when_no_prompts(tmp_path):
    from storyforge.cmd_script_package import _assemble_blocking_prompts
    pages_dir = tmp_path / 'pages'
    pages_dir.mkdir()
    _write_page(str(pages_dir), 's01-p1', 's01-studio', 1, 1,
                '## Panel script\n\n**Panel 1.**\n')
    chapters = [{
        'chapter': 1, 'title': 'One', 'heading': 'One',
        'scenes': ['s01-studio'],
    }]
    ref_dir = tmp_path / 'reference'
    ref_dir.mkdir()
    (ref_dir / 'scenes.csv').write_text(
        'id|seq|title\ns01-studio|1|Studio\n'
    )
    out = _assemble_blocking_prompts(str(tmp_path), chapters)
    assert out == ''


def test_handoff_readme_includes_generation_order_when_file_emitted():
    from storyforge.cmd_script_package import HANDOFF_README
    # The template must be parameterizable on a 'blocking_line' field that
    # the main function fills in conditionally.
    rendered = HANDOFF_README.format(
        title='Test', canon_line='',
        blocking_line='\n- `page-blocking-prompts.md` — render these first.',
    )
    assert 'page-blocking-prompts.md' in rendered
