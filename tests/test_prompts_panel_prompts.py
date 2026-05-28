"""Tests for prompts_panel_prompts — strict / coach / full builders
for elaborate --stage panel-prompts (issue #253)."""


def test_strict_template_renders_all_13_sections_for_each_panel():
    from storyforge.prompts_panel_prompts import render_strict_template
    canon_blocks = {
        'style-foundation': 'foundation block',
        'lighting-laws': 'lighting block',
        'locations/archive': 'location block',
        'characters/lucien': 'lucien block',
        'motifs/inkpot': 'inkpot block (low weight)',
    }
    panel_registers = {1: 'dominant', 2: 'transitional'}
    out = render_strict_template(
        page_id='s01-p1', panel_count=2,
        canon_blocks=canon_blocks, panel_registers=panel_registers,
    )
    # Both panel headers present
    assert '### Panel 1' in out
    assert '### Panel 2' in out
    # All 13 section headers per panel — count by exact-position substring
    for n in range(1, 14):
        assert f'#### {n}. ' in out


def test_strict_template_embeds_canon_in_sections_1_2():
    """Sections 1 and 2 must contain canon embeds verbatim, not TODO."""
    from storyforge.prompts_panel_prompts import render_strict_template
    canon_blocks = {
        'style-foundation': 'STYLE_BLOCK_TEXT',
        'lighting-laws': 'LIGHTING_BLOCK_TEXT',
    }
    out = render_strict_template(
        page_id='s01-p1', panel_count=1,
        canon_blocks=canon_blocks, panel_registers={1: 'dominant'},
    )
    # Section 1 has the embed
    assert 'STYLE_BLOCK_TEXT' in out
    assert 'LIGHTING_BLOCK_TEXT' in out


def test_strict_template_cites_register_in_section_3():
    """Section 3 (Pacing role) cites the register from page architecture."""
    from storyforge.prompts_panel_prompts import render_strict_template
    out = render_strict_template(
        page_id='s01-p1', panel_count=2,
        canon_blocks={}, panel_registers={1: 'dominant', 2: 'transitional'},
    )
    # Section 3 in panel 1 mentions 'dominant'; section 3 in panel 2 mentions 'transitional'
    panel_1_start = out.index('### Panel 1')
    panel_2_start = out.index('### Panel 2')
    panel_1 = out[panel_1_start:panel_2_start]
    panel_2 = out[panel_2_start:]
    assert 'dominant' in panel_1.lower()
    assert 'transitional' in panel_2.lower()


def test_strict_template_uses_todo_in_panel_specific_sections():
    """Sections 3, 4, 7, 8, 9, 11, 12, 13 (panel-specific) are TODO scaffolding."""
    from storyforge.prompts_panel_prompts import render_strict_template
    out = render_strict_template(
        page_id='s01-p1', panel_count=1,
        canon_blocks={}, panel_registers={1: 'dominant'},
    )
    # Count how many TODO placeholders appear — at least one per panel-specific
    # section (3, 4, 7, 8, 9, 11, 12, 13 = 8 TODOs)
    assert out.lower().count('todo') >= 8


def test_strict_template_panel_count_zero_falls_back_to_one():
    """Edge case: page file has panel_count=0. Render at least one panel."""
    from storyforge.prompts_panel_prompts import render_strict_template
    out = render_strict_template(
        page_id='s01-p1', panel_count=0,
        canon_blocks={}, panel_registers={},
    )
    assert '### Panel 1' in out


def test_strict_template_is_deterministic():
    """Same inputs → same output."""
    from storyforge.prompts_panel_prompts import render_strict_template
    canon_blocks = {'style-foundation': 'foo'}
    panel_registers = {1: 'dominant'}
    a = render_strict_template(
        page_id='s01-p1', panel_count=2,
        canon_blocks=canon_blocks, panel_registers=panel_registers,
    )
    b = render_strict_template(
        page_id='s01-p1', panel_count=2,
        canon_blocks=canon_blocks, panel_registers=panel_registers,
    )
    assert a == b
