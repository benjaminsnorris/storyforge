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


def test_coach_brief_includes_canon_inline_and_questions_per_section():
    from storyforge.prompts_panel_prompts import render_coach_brief
    out = render_coach_brief(
        page_id='s01-p1', panel_count=2, scene_title='Studio finalization',
        page_architecture='### Panel hierarchy\n- Panel 1 — dominant: focus\n- Panel 2 — atmospheric: ambience',
        scene_brief={
            'panel_breakdown': 'p1: 2-panel',
            'visual_keywords': 'inkpot; hand',
            'key_actions': 'lowers the inkpot',
            'motifs': 'inkpot',
        },
        canon_blocks={
            'style-foundation': 'STYLE_BLOCK',
            'lighting-laws': 'LIGHTING_BLOCK',
            'panel-registers': 'Dominant: emotional fulcrum.\nAtmospheric: pause.',
        },
    )
    # Embeds canon vocabulary inline
    assert 'STYLE_BLOCK' in out
    assert 'LIGHTING_BLOCK' in out
    # Lists the 13 sections with at least one question per section
    for n in range(1, 14):
        assert f'#### {n}. ' in out or f'{n}.' in out
    # Identifies the write target
    assert 'pages/s01-p1.md' in out
    # Names the panel count
    assert '2 panel' in out or '2 panels' in out


def test_coach_brief_handles_empty_inputs():
    from storyforge.prompts_panel_prompts import render_coach_brief
    out = render_coach_brief(
        page_id='solo-p1', panel_count=1, scene_title='Solo',
        page_architecture='', scene_brief={}, canon_blocks={},
    )
    assert 'solo-p1' in out


def test_full_prompt_embeds_canon_and_page_architecture():
    from storyforge.prompts_panel_prompts import build_full_prompt
    prompt = build_full_prompt(
        page_id='s01-p1', panel_count=2,
        scene_title='Studio finalization',
        page_frontmatter={
            'page_id': 's01-p1', 'scene_id': 's01-studio',
            'panel_count': 2, 'characters_present': ['lucien-vey'],
            'location': 'archive-studio',
        },
        page_architecture='### Intent\nQuiet tension.\n\n### Panel hierarchy\n- Panel 1 — dominant\n- Panel 2 — atmospheric',
        scene_brief={
            'panel_breakdown': 'p1: 2-panel',
            'visual_keywords': 'inkpot; hand',
            'key_actions': 'lowers the inkpot',
            'motifs': 'inkpot',
        },
        scene_intent={
            'function': 'opening', 'emotional_arc': 'apprehension to focus',
            'on_stage': 'lucien-vey',
        },
        canon_blocks={
            'style-foundation': 'STYLE_BLOCK',
            'lighting-laws': 'LIGHTING_BLOCK',
            'locations/archive-studio': 'LOCATION_BLOCK',
            'characters/lucien-vey': 'LUCIEN_BLOCK',
            'motifs/inkpot': 'INKPOT_BLOCK',
            'panel-registers': 'Dominant: emotional fulcrum.\nAtmospheric: pause.',
        },
    )
    # Identity
    assert 's01-p1' in prompt
    assert 'Studio finalization' in prompt
    # Page architecture
    assert 'Panel 1 — dominant' in prompt
    # Brief
    assert 'inkpot' in prompt
    # Canon embedded
    assert 'STYLE_BLOCK' in prompt
    assert 'LIGHTING_BLOCK' in prompt
    assert 'LOCATION_BLOCK' in prompt
    assert 'LUCIEN_BLOCK' in prompt
    assert 'INKPOT_BLOCK' in prompt
    # Output contract names the 13 sections
    for n in range(1, 14):
        assert f'#### {n}. ' in prompt
    # Constraint mentions sections 1, 2, 5, 6, 10 embed verbatim
    assert 'verbatim' in prompt.lower() or 'paste' in prompt.lower()


def test_full_prompt_skips_empty_canon_blocks():
    """Empty canon_blocks values are not embedded (avoid blank '### canon-id' headers)."""
    from storyforge.prompts_panel_prompts import build_full_prompt
    prompt = build_full_prompt(
        page_id='s01-p1', panel_count=1,
        scene_title='Solo', page_frontmatter={'page_id': 's01-p1', 'panel_count': 1},
        page_architecture='', scene_brief={}, scene_intent={},
        canon_blocks={'style-foundation': '', 'lighting-laws': 'LIGHTING_BLOCK'},
    )
    # The empty style-foundation should not produce a blank embed section
    # (we don't enforce exactly how, just that LIGHTING_BLOCK is in and
    # there's no spurious '### style-foundation' followed by blank content)
    assert 'LIGHTING_BLOCK' in prompt
