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


def test_readme_includes_page_prompts_inventory_when_emitted():
    """The page-prompts inventory line names both new bundle files."""
    from storyforge.cmd_script_package import _PAGE_PROMPTS_INVENTORY_LINE
    assert 'page-prompts.md' in _PAGE_PROMPTS_INVENTORY_LINE
    assert 'reference-images.md' in _PAGE_PROMPTS_INVENTORY_LINE
    assert 'GPT Image 2' in _PAGE_PROMPTS_INVENTORY_LINE
