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
