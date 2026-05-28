"""Tests for prompts_page_architecture — strict / coach / full builders
used by elaborate --stage page-architecture."""

import textwrap


def test_strict_template_renders_panel_hierarchy_for_each_panel():
    from storyforge.prompts_page_architecture import render_strict_template
    out = render_strict_template(page_id='s01-p1', panel_count=3)
    # Both new sections present
    assert '## Page architecture' in out
    assert '## Page-blocking prompt' in out
    # Panel hierarchy enumerates each panel (panel_count=3 → 3 bullets)
    assert out.count('TODO register: TODO role') == 3
    # Required intent / placement / blocking constraints documented
    assert '### Intent' in out
    assert '### Book-level placement' in out
    assert 'panel-registers.md' in out
    assert 'monochrome' in out.lower()


def test_strict_template_panel_count_one():
    from storyforge.prompts_page_architecture import render_strict_template
    out = render_strict_template(page_id='s01-p1', panel_count=1)
    assert out.count('TODO register: TODO role') == 1


def test_strict_template_panel_count_zero_falls_back_to_one_placeholder():
    """Edge case: page file has panel_count=0 (unknown). Render at least
    one placeholder so the author has something to fill in."""
    from storyforge.prompts_page_architecture import render_strict_template
    out = render_strict_template(page_id='s01-p1', panel_count=0)
    assert out.count('TODO register: TODO role') >= 1


def test_strict_template_is_deterministic():
    """Same inputs → same output (no timestamps, no random IDs)."""
    from storyforge.prompts_page_architecture import render_strict_template
    a = render_strict_template(page_id='s01-p1', panel_count=2)
    b = render_strict_template(page_id='s01-p1', panel_count=2)
    assert a == b


def test_coach_brief_includes_decision_prompts():
    from storyforge.prompts_page_architecture import render_coach_brief
    out = render_coach_brief(
        page_id='s01-p1',
        scene_title='Studio finalization',
        panel_count=3,
        scene_brief={
            'panel_breakdown': 'p1: 3-panel tier',
            'visual_keywords': 'inkpot; trembling hand',
            'page_turn_beats': '',
        },
        prev_page=None,
        next_page={'page_id': 's01-p2', 'spread_position': 'verso'},
        canon_blocks={
            'panel-registers': 'Dominant: emotional fulcrum.\nTransitional: rhythmic bridge.',
            'page-rhythm-rules': 'One dominant per page maximum.',
        },
    )
    # Asks the author the right questions
    assert 'Which panel' in out and 'dominant' in out
    # Includes canon vocabulary inline so author doesn't need to flip files
    assert 'emotional fulcrum' in out
    assert 'One dominant per page' in out
    # References sibling page for spread context
    assert 's01-p2' in out
    # Points at where to write
    assert 'pages/s01-p1.md' in out


def test_coach_brief_handles_missing_neighbor_pages():
    from storyforge.prompts_page_architecture import render_coach_brief
    out = render_coach_brief(
        page_id='s01-p1', scene_title='Open', panel_count=1,
        scene_brief={}, prev_page=None, next_page=None, canon_blocks={},
    )
    # Doesn't crash; mentions absence
    assert 's01-p1' in out


def test_full_prompt_embeds_canon_and_brief():
    from storyforge.prompts_page_architecture import build_full_prompt
    prompt = build_full_prompt(
        page_id='s01-p1',
        page_frontmatter={
            'page_id': 's01-p1', 'scene_id': 's01-studio',
            'page_within_scene': 1, 'total_pages_in_scene': 3,
            'panel_count': 2, 'spread_position': 'opening recto',
            'characters_present': ['lucien-vey'], 'location': 'archive',
            'timeline': 'day 1, evening',
        },
        scene_title='Studio finalization',
        scene_brief={
            'panel_breakdown': 'p1: 2-panel; p2: 3-panel; p3: splash',
            'visual_keywords': 'inkpot; trembling hand',
            'page_turn_beats': 'p3 reveal',
            'page_layout': '3-page scene; splash on p3',
            'caption_strategy': 'minimal',
        },
        scene_intent={
            'function': 'opening', 'emotional_arc': 'apprehension to focus',
            'value_at_stake': 'control', 'value_shift': 'positive',
        },
        prev_page=None,
        next_page={'page_id': 's01-p2', 'spread_position': 'verso'},
        canon_blocks={
            'panel-registers': 'Dominant: emotional fulcrum.',
            'page-rhythm-rules': 'One dominant per page maximum.',
            'style-foundation': 'Chiaroscuro; muted palette.',
            'lighting-laws': 'Single source; no supernatural luminosity.',
        },
    )
    # Page identity
    assert 's01-p1' in prompt
    assert 'Studio finalization' in prompt
    # Brief context
    assert '2-panel; p2: 3-panel' in prompt or 'panel_breakdown' in prompt
    assert 'inkpot' in prompt
    # Intent context
    assert 'apprehension to focus' in prompt
    # Canon embedded inline
    assert 'emotional fulcrum' in prompt
    assert 'One dominant per page' in prompt
    assert 'Chiaroscuro' in prompt
    # Neighbor for spread context
    assert 's01-p2' in prompt
    # Output contract: both section headers requested
    assert '## Page architecture' in prompt
    assert '## Page-blocking prompt' in prompt
    # Constraint: blocking prompt must cite registers + be monochrome
    assert 'monochrome' in prompt.lower()
    assert 'cite' in prompt.lower() and 'register' in prompt.lower()


def test_full_prompt_when_no_neighbor_pages():
    from storyforge.prompts_page_architecture import build_full_prompt
    prompt = build_full_prompt(
        page_id='solo-p1',
        page_frontmatter={'page_id': 'solo-p1', 'panel_count': 1},
        scene_title='Solo', scene_brief={}, scene_intent={},
        prev_page=None, next_page=None,
        canon_blocks={'panel-registers': 'Dominant: emotional fulcrum.'},
    )
    # Doesn't crash; mentions absence of neighbors so the LLM knows
    assert 'solo-p1' in prompt
