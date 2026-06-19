"""Tests for prompts_page_prompt — the GPT Image 2 page-prompt builders
used by elaborate --stage prompts (issue #260)."""


def test_render_references_block_with_refs():
    from storyforge.prompts_page_prompt import render_references_block
    out = render_references_block([
        'reference/visual/char.png',
        'reference/visual/tone.png',
    ])
    assert '### References to upload' in out
    assert '**Image 1:** reference/visual/char.png' in out
    assert '**Image 2:** reference/visual/tone.png' in out


def test_render_references_block_empty_emits_todo_scaffold():
    from storyforge.prompts_page_prompt import render_references_block
    out = render_references_block([])
    assert 'TODO' in out
    # The three standard roles are listed
    assert 'character reference' in out
    assert 'paper-tone' in out
    assert 'prior rendered page' in out
    # Warns that references are essential, not optional
    assert 'essential' in out.lower()


def test_blockquote_preserves_blank_lines_without_trailing_space():
    """TG-7: a blank line becomes a bare '>' (no trailing space), and
    content lines are prefixed with '> '."""
    from storyforge.prompts_page_prompt import _blockquote
    assert _blockquote('a\n\nb') == '> a\n>\n> b'
    # No trailing-whitespace blockquote lines anywhere
    assert '> \n' not in _blockquote('a\n\nb') + '\n'


def test_assemble_workflow_section_blockquotes_prompt():
    from storyforge.prompts_page_prompt import assemble_workflow_section
    out = assemble_workflow_section(
        page_prompt_body='**Scene:** A studio.\n\n**Panels:**\n\n1. Wide.',
        references_required=['ref/char.png'],
    )
    assert out.startswith('## Image-generation workflow')
    assert 'Approach' in out
    assert '### References to upload' in out
    assert '### Page prompt' in out
    # The prompt body is rendered as a blockquote, blank lines preserved
    assert '> **Scene:** A studio.' in out
    assert '\n>\n' in out


def test_strict_template_has_five_sections_and_panels():
    from storyforge.prompts_page_prompt import render_strict_template
    out = render_strict_template(
        page_id='s01-p2', panel_count=3, scene_title='Studio',
        references_required=['ref/char.png'],
    )
    assert out.startswith('## Image-generation workflow')
    for label in ('**Scene:**', '**Subject:**', '**Important details:**',
                  '**Use case:**', '**Constraints:**', '**Panels:**'):
        assert label in out, label
    # One numbered beat per panel
    assert '> 1. ' in out
    assert '> 3. ' in out
    # Character anchor instruction present
    assert 'Character anchor' in out


def test_strict_template_is_deterministic():
    from storyforge.prompts_page_prompt import render_strict_template
    a = render_strict_template(page_id='s01-p2', panel_count=2,
                               scene_title='S', references_required=[])
    b = render_strict_template(page_id='s01-p2', panel_count=2,
                               scene_title='S', references_required=[])
    assert a == b


def test_coach_brief_includes_gpt_image_2_rules():
    from storyforge.prompts_page_prompt import render_coach_brief
    out = render_coach_brief(
        page_id='s01-p2', panel_count=3, scene_title='Studio',
        page_architecture='### Intent\nThe work begins.',
        panel_script='### Panel 1\nMid shot.',
        scene_brief={'panel_breakdown': 'p2: 6-panel', 'motifs': 'candle'},
        references_required=['ref/char.png'],
        canon_blocks={'style-foundation': 'Chiaroscuro palette.'},
    )
    # The five paradigm shifts are surfaced as guidance
    assert 'whole page' in out.lower()
    assert 'IDENTICAL' in out or 'identical' in out
    assert 'ositive framing' in out  # Positive framing
    assert 'reference images' in out.lower()
    # Inputs surfaced
    assert 'The work begins.' in out
    assert 'Mid shot.' in out
    assert 'Chiaroscuro palette.' in out
    assert 'pages/s01-p2.md' in out


def test_build_full_prompt_encodes_rules_and_contract():
    from storyforge.prompts_page_prompt import build_full_prompt
    prompt = build_full_prompt(
        page_id='s01-p2', panel_count=6, scene_title='Studio',
        page_frontmatter={'page_id': 's01-p2', 'panel_count': 6,
                          'location': 'archive', 'target_model': 'gpt-image-2'},
        page_architecture='### Intent\nThe work begins.',
        panel_script='### Panel 1\nMid shot of Lucien.',
        scene_brief={'panel_breakdown': 'p2: 6-panel', 'visual_keywords': 'candle'},
        references_required=['ref/char.png', 'ref/tone.png'],
        canon_blocks={'style-foundation': 'Chiaroscuro; muted palette.',
                     'lighting-laws': 'Single warm source.'},
    )
    # Identity + inputs
    assert 's01-p2' in prompt
    assert 'Studio' in prompt
    assert 'The work begins.' in prompt
    assert 'Mid shot of Lucien.' in prompt
    # References listed
    assert 'ref/char.png' in prompt
    # Canon present as distillation source (not embed)
    assert 'Chiaroscuro' in prompt
    assert 'do NOT paste verbatim' in prompt or 'distill' in prompt.lower()
    # The five rules encoded
    assert 'IDENTICAL' in prompt
    assert 'POSITIVE' in prompt or 'positive' in prompt.lower()
    assert '250-400 words' in prompt
    # Output contract: the five labels + Panels + panel count
    for label in ('**Scene:**', '**Subject:**', '**Important details:**',
                  '**Use case:**', '**Constraints:**', '**Panels:**'):
        assert label in prompt, label
    assert 'exactly 6' in prompt or '6 numbered' in prompt


def test_build_full_prompt_handles_empty_inputs():
    """TG-8: the handler legitimately calls build_full_prompt with empty
    references (the NOTE-don't-block path) and may have empty arch/script.
    The empty-input fallbacks are on a live code path."""
    from storyforge.prompts_page_prompt import build_full_prompt
    prompt = build_full_prompt(
        page_id='s01-p1', panel_count=2, scene_title='Studio',
        page_frontmatter={'page_id': 's01-p1', 'panel_count': 2},
        page_architecture='', panel_script='',
        scene_brief={}, references_required=[], canon_blocks={},
    )
    # Empty references → the "assume a character reference…" fallback
    assert 'assume a character reference' in prompt
    # Empty architecture / panel script render as (none)
    assert '(none)' in prompt
    # Empty brief renders as (empty)
    assert '(empty)' in prompt


# ---------------------------------------------------------------------------
# Portrait orientation + panel differentiation (issue #263)
# ---------------------------------------------------------------------------

def test_orientation_clause_per_aspect():
    from storyforge.prompts_page_prompt import orientation_clause
    assert orientation_clause().startswith('Render in PORTRAIT')
    assert 'do not render as landscape or square' in orientation_clause().lower()
    assert orientation_clause('landscape').startswith('Render in LANDSCAPE')
    assert orientation_clause('square').startswith('Render in SQUARE')


def test_differentiation_clause_empty_and_populated():
    from storyforge.prompts_page_prompt import differentiation_clause
    assert differentiation_clause(None) == ''
    assert differentiation_clause([]) == ''
    c = differentiation_clause([[3, 6]])
    assert 'panels 3, 6' in c
    assert 'isolation' in c and 'contact point' in c


def test_strict_template_emits_portrait_in_use_case_and_constraints():
    from storyforge.prompts_page_prompt import render_strict_template
    out = render_strict_template(page_id='s01-p2', panel_count=3,
                                 scene_title='S', references_required=[])
    assert out.count('PORTRAIT orientation') == 2


def test_strict_template_aspect_optout():
    from storyforge.prompts_page_prompt import render_strict_template
    for aspect, word in (('landscape', 'LANDSCAPE'), ('square', 'SQUARE')):
        out = render_strict_template(page_id='s01-p2', panel_count=2,
                                     scene_title='S', references_required=[],
                                     page_aspect=aspect)
        assert word in out
        assert 'PORTRAIT' not in out


def test_strict_template_differentiation_when_convergence():
    from storyforge.prompts_page_prompt import render_strict_template
    from storyforge.pages import has_differentiation_language
    out = render_strict_template(page_id='s01-p2', panel_count=6,
                                 scene_title='S', references_required=[],
                                 convergence=[[3, 6]])
    assert has_differentiation_language(out)
    assert 'panels 3, 6' in out


def test_full_prompt_requires_orientation_in_both_sections():
    from storyforge.prompts_page_prompt import build_full_prompt
    prompt = build_full_prompt(
        page_id='s01-p2', panel_count=6, scene_title='S',
        page_frontmatter={'page_id': 's01-p2'}, page_architecture='a',
        panel_script='s', scene_brief={}, references_required=['r'],
        canon_blocks={}, convergence=[[3, 6]],
    )
    assert 'BOTH the Use case' in prompt
    from storyforge.pages import has_differentiation_language
    assert has_differentiation_language(prompt)
    # orientation directive present in the rules + both template slots
    assert prompt.count('PORTRAIT orientation') >= 3
