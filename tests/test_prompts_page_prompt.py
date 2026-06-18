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
    # The prompt body is rendered as a blockquote
    assert '> **Scene:** A studio.' in out
    assert '>' in out  # blank lines preserved as bare '>'


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
