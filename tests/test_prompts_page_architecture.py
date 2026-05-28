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
