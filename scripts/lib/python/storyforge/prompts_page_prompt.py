"""Page-prompt stage prompt builders (issue #260).

The `prompts` stage authors the `## Image-generation workflow` section of
a per-page file: a single whole-page image-generation prompt tuned for
GPT Image 2 (ChatGPT Images 2.0), following OpenAI's 5-section template
(Scene / Subject / Important details / Use case / Constraints) plus
concrete per-panel beats.

Five paradigm shifts from the v2 (per-panel) approach drive this module:
  1. Whole-page generation in one prompt — no blocking/composition pass.
  2. Reference images carry style + character likeness, not prose.
  3. OpenAI's 5-section template; structure over brevity (~250-400 words).
  4. The character anchor must be the IDENTICAL string in every panel.
  5. Positive framing replaces defensive negation (negated keywords leak).

Three coaching modes share the module. render_strict_template stamps a
TODO scaffold (no LLM). render_coach_brief writes a question-driven brief.
build_full_prompt assembles the LLM prompt. assemble_workflow_section
wraps an authored/generated page prompt with the approach note and the
labeled reference list into the final page-file section.
"""

from typing import Final

from storyforge.pages import PageFile, DEFAULT_PAGE_ASPECT


# The five OpenAI template section labels, in order. Used by the LLM
# output contract, the strict scaffold, and the response validator so
# they share one definition.
PAGE_PROMPT_SECTIONS: Final[tuple[str, ...]] = (
    'Scene', 'Subject', 'Important details', 'Use case', 'Constraints',
)

# Boilerplate approach note that heads the workflow section. Explains to
# the artist/author how to use the prompt + references.
APPROACH_NOTE: Final[str] = (
    '**Approach (GPT Image 2 / ChatGPT Images 2.0):** Whole-page generation '
    'in a single prompt. There is no per-panel blocking or composition pass — '
    'GPT Image 2 plans the layout and renders the composed page in one shot. '
    'Style and character consistency live in the **reference images**, not in '
    'the prompt prose. The prompt below uses OpenAI’s 5-section template '
    '(Scene / Subject / Important details / Use case / Constraints) with '
    'concrete, action-focused per-panel beats. If the model drifts on '
    'register (color, lighting, texture, edge treatment), iterate by adjusting '
    'the reference images rather than by adding more prose to the prompt.'
)

# Standard reference roles, in upload order, when the page frontmatter has
# no `references_required` list to render from.
_DEFAULT_REFERENCE_ROLES: Final[tuple[str, ...]] = (
    'character reference (protagonist character sheet)',
    'paper-tone reference (page background / canvas color)',
    'prior rendered page (anchors style + continuity)',
)


def orientation_clause(page_aspect: str = DEFAULT_PAGE_ASPECT) -> str:
    """Return the one-line orientation directive for a page aspect (#263).

    GPT Image 2 drifts to landscape without an explicit directive, so the
    portrait clause asserts the target aspect AND negates the wrong ones —
    the one place orientation negation proved necessary in lived iteration
    (benjaminsnorris/ashes PR #9), distinct from the content-negation the
    rest of the prompt avoids.
    """
    a = (page_aspect or DEFAULT_PAGE_ASPECT).strip().lower()
    if a == 'landscape':
        return 'Render in LANDSCAPE orientation — wider than tall (~3:2 aspect ratio).'
    if a == 'square':
        return 'Render in SQUARE orientation — 1:1 aspect ratio.'
    return ('Render in PORTRAIT orientation — taller than wide, ~2:3 aspect '
            'ratio. Do not render as landscape or square.')


def differentiation_clause(convergence: list[list[int]] | None) -> str:
    """Return the panel-differentiation directive for converging close-ups.

    `convergence` is the output of pages.detect_closeup_convergence — groups
    of panel indices that are close-ups of the same subject. Returns '' when
    there is nothing to differentiate. The wording embeds the differentiation
    cues pages.has_differentiation_language looks for, so a generated page
    won't trip the undifferentiated-close-ups warning.
    """
    if not convergence:
        return ''
    groups = '; '.join(
        'panels ' + ', '.join(str(i) for i in g) for g in convergence
    )
    return (
        f'Differentiate the framing of the same-subject close-ups ({groups}) '
        f'so they do not converge into one image: render one panel with the '
        f'subject in isolation, one as the act of interaction at the contact '
        f'point, and one at a different scale or angle.'
    )


def _blockquote(text: str) -> str:
    """Prefix every line of *text* with markdown blockquote markers."""
    out = []
    for line in text.rstrip('\n').splitlines():
        out.append('>' if not line.strip() else f'> {line}')
    return '\n'.join(out)


def render_references_block(references_required: list[str]) -> str:
    """Render the '### References to upload' block.

    When the page frontmatter lists `references_required`, each entry is
    rendered as a numbered, role-labeled bullet. When the list is empty,
    a TODO scaffold with the three standard roles is emitted so the author
    knows reference-anchored generation is expected.
    """
    lines = ['### References to upload (label each by role)', '']
    if references_required:
        for i, ref in enumerate(references_required, start=1):
            lines.append(f'- **Image {i}:** {ref}')
    else:
        for i, role in enumerate(_DEFAULT_REFERENCE_ROLES, start=1):
            lines.append(f'- **Image {i}:** TODO — {role}')
        lines.append('')
        lines.append(
            '_No `references_required` in the page frontmatter. GPT Image 2 '
            'drifts on character likeness past ~6-8 panels; reference images '
            'are essential, not optional, at this page size._'
        )
    return '\n'.join(lines)


def assemble_workflow_section(*, page_prompt_body: str,
                              references_required: list[str]) -> str:
    """Assemble the full `## Image-generation workflow` section.

    Combines the approach note, the labeled reference list, and the page
    prompt (rendered as a blockquote under a '### Page prompt' heading).
    `page_prompt_body` is the 5-section template body — authored (strict),
    or LLM-generated (full) — WITHOUT blockquote markers.
    """
    refs = render_references_block(references_required)
    quoted = _blockquote(page_prompt_body.strip())
    return (
        '## Image-generation workflow\n\n'
        f'{APPROACH_NOTE}\n\n'
        f'{refs}\n\n'
        '### Page prompt (paste into ChatGPT alongside the references)\n\n'
        f'{quoted}\n'
    )


def _strict_prompt_body(*, page_id: str, panel_count: int,
                        page_aspect: str = DEFAULT_PAGE_ASPECT,
                        convergence: list[list[int]] | None = None) -> str:
    """TODO scaffold for the 5-section page-prompt body (no LLM)."""
    page_label = page_id.split('-p')[-1] if '-p' in page_id else page_id
    panels = max(panel_count, 1)
    orient = orientation_clause(page_aspect)
    differ = differentiation_clause(convergence)
    lines = [
        f'**Page {page_label} — graphic novel page ({panels} '
        f'panel{"s" if panels != 1 else ""}).**',
        '',
        '**Scene:** TODO — where this happens, time of day, environment, '
        'key set elements.',
        '',
        '**Subject:** TODO — main focus. **Character anchor (use this exact '
        'string in every panel showing them):** "TODO — one identical '
        'description per recurring character." See attached character '
        'reference image.',
        '',
        '**Important details:** TODO — composition, palette, lighting, '
        'materials, mood. Match the style of the attached reference page(s). '
        'Use positive specification (state what IS present), not negation.',
        '',
        f'**Use case:** A single graphic novel page laid out as {panels} '
        f'panel(s) in a TODO grid, read left-to-right, top-to-bottom. '
        f'{orient} Continuous with the attached reference page(s).',
        '',
        '**Panels:**',
        '',
    ]
    for i in range(1, panels + 1):
        lines.append(f'{i}. TODO — concrete, action-focused beat (1-2 '
                     'sentences). Repeat the character anchor for any '
                     'character shown.')
    constraints = (
        '**Constraints:** TODO — keep the layout exactly; keep each '
        'character identical to the reference across every panel; positive '
        'constraints only (e.g. "eyes left as raw unpainted canvas", not '
        f'"no glow"). {orient}'
    )
    if differ:
        constraints += f' {differ}'
    lines += ['', constraints]
    return '\n'.join(lines)


def render_strict_template(*, page_id: str, panel_count: int,
                           scene_title: str,
                           references_required: list[str],
                           page_aspect: str = DEFAULT_PAGE_ASPECT,
                           convergence: list[list[int]] | None = None) -> str:
    """Deterministic strict-mode `## Image-generation workflow` section.

    No LLM call. Emits the approach note, reference list, and a 5-section
    page-prompt TODO scaffold the author fills in, with the orientation
    directive (page_aspect, default portrait) baked into the Use case and
    Constraints and a panel-differentiation directive when `convergence`
    flags same-subject close-ups. (`scene_title` is accepted for call-site
    symmetry with the coach/full builders; the strict scaffold is
    title-agnostic.)
    """
    body = _strict_prompt_body(
        page_id=page_id, panel_count=panel_count,
        page_aspect=page_aspect, convergence=convergence,
    )
    return assemble_workflow_section(
        page_prompt_body=body, references_required=references_required,
    )


def render_coach_brief(*, page_id: str, panel_count: int,
                       scene_title: str, page_architecture: str,
                       panel_script: str, scene_brief: dict[str, str],
                       references_required: list[str],
                       canon_blocks: dict[str, str],
                       page_aspect: str = DEFAULT_PAGE_ASPECT,
                       convergence: list[list[int]] | None = None) -> str:
    """Coach-mode markdown brief written to working/coaching/.

    Surfaces the inputs (page architecture, panel script, brief, canon
    vocabulary) and the GPT Image 2 prompting rules — including the
    orientation directive and any panel-differentiation directive — so the
    author can write the page prompt themselves. Does NOT mutate the page file.
    """
    differ = differentiation_clause(convergence)
    lines = [
        f'# Page-prompt brief: {page_id}',
        '',
        f'**Scene:** {scene_title}  ',
        f'**Panels on this page:** {panel_count}',
        '',
        '## How GPT Image 2 wants the prompt',
        '',
        '- One prompt renders the **whole page**. No blocking/composition pass.',
        '- **Reference images carry style + character likeness** — keep prose '
        'short (~250-400 words total). Adjust references, not prose, to fix '
        'drift.',
        '- Use OpenAI’s 5-section template: **Scene / Subject / Important '
        'details / Use case / Constraints**, then per-panel beats.',
        '- The **character anchor must be the IDENTICAL string** in every '
        'panel showing that character — not paraphrased.',
        '- **Positive framing only.** Negated keywords ("no glow") leak into '
        'the image; specify what IS present instead.',
        f'- **Orientation:** put this in BOTH the Use case and Constraints — '
        f'{orientation_clause(page_aspect)}',
    ]
    if differ:
        lines.append(f'- **Panel differentiation:** {differ}')
    lines += [
        '',
        '## References to upload',
        '',
        render_references_block(references_required),
        '',
        '## Page architecture (authoring context)',
        '',
        page_architecture.strip() if page_architecture
        else '(none — run elaborate --stage page-architecture first)',
        '',
        '## Panel script (beats to distill into per-panel prompt lines)',
        '',
        panel_script.strip() if panel_script else '(none — draft the page first)',
        '',
        '## Brief inputs',
        '',
    ]
    for key in ('panel_breakdown', 'visual_keywords', 'key_actions',
                'caption_strategy', 'motifs'):
        val = scene_brief.get(key, '')
        lines.append(f'- **{key}:** {val or "(empty)"}')
    lines += ['', '## Canon (informs the prompt; do NOT paste verbatim)', '']
    for canon_id in ('style-foundation', 'lighting-laws'):
        block = canon_blocks.get(canon_id, '').strip()
        if block:
            lines += [f'### {canon_id}', '', block, '']
    lines += [
        '## Write the section into the page file at:',
        '',
        f'`pages/{page_id}.md` — a `## Image-generation workflow` section '
        'with the approach note, the reference list, and a `### Page prompt` '
        'blockquote in the 5-section template.',
    ]
    return '\n'.join(lines) + '\n'


def _format_frontmatter_summary(fm: PageFile) -> str:
    keys = ('page_id', 'scene_id', 'page_within_scene',
            'total_pages_in_scene', 'panel_count', 'spread_position',
            'characters_present', 'location', 'timeline', 'target_model')
    lines = []
    for k in keys:
        v = fm.get(k)
        if v is None or v == '':
            continue
        if isinstance(v, list):
            v = ', '.join(v)
        lines.append(f'- {k}: {v}')
    return '\n'.join(lines) if lines else '(empty)'


def _format_brief(brief: dict[str, str]) -> str:
    keys = ('panel_breakdown', 'visual_keywords', 'key_actions',
            'key_dialogue', 'motifs', 'caption_strategy',
            'page_layout', 'goal', 'conflict', 'outcome')
    lines = []
    for k in keys:
        v = brief.get(k, '')
        if v:
            lines.append(f'- {k}: {v}')
    return '\n'.join(lines) if lines else '(empty)'


def build_full_prompt(*, page_id: str, panel_count: int,
                      scene_title: str,
                      page_frontmatter: PageFile,
                      page_architecture: str,
                      panel_script: str,
                      scene_brief: dict[str, str],
                      references_required: list[str],
                      canon_blocks: dict[str, str],
                      page_aspect: str = DEFAULT_PAGE_ASPECT,
                      convergence: list[list[int]] | None = None) -> str:
    """Full-mode LLM prompt that authors the page-prompt body.

    The handler collects the page architecture, panel script, brief, the
    references list, and canon blocks (as distillation source — NOT to
    embed). This builder is pure — no I/O.

    Output contract: the LLM emits ONLY the 5-section page-prompt body
    (Scene / Subject / Important details / Use case / Constraints + a
    numbered Panels list), in markdown, WITHOUT blockquote markers and
    without the surrounding workflow scaffolding. The handler wraps it
    with the approach note and reference list. The orientation directive
    (page_aspect, default portrait) goes in BOTH Use case and Constraints,
    and same-subject close-ups flagged by `convergence` get differentiated
    framing (issue #263).
    """
    orient = orientation_clause(page_aspect)
    differ = differentiation_clause(convergence)
    page_label = page_id.split('-p')[-1] if '-p' in page_id else page_id
    refs = ('\n'.join(f'- Image {i}: {r}'
                      for i, r in enumerate(references_required, start=1))
            if references_required else '(none listed — assume a character '
            'reference, a paper-tone reference, and the prior rendered page)')

    parts: list[str] = []
    parts.append(
        'You are writing a single whole-page image-generation prompt for one '
        'page of a graphic novel, tuned for GPT Image 2 (ChatGPT Images 2.0).'
    )
    parts.append('')
    parts.append('## How GPT Image 2 works (obey these — they are validated)')
    parts.append('')
    parts.append('- ONE prompt renders the whole page. Do NOT describe a '
                 'blocking thumbnail or a composition pass.')
    parts.append('- Reference images carry style, palette, edge treatment, '
                 'and character likeness. Keep the prompt SHORT '
                 '(~250-400 words total). Long stylistic prose competes for '
                 'attention budget and degrades the result.')
    parts.append('- The character anchor must be the IDENTICAL string in '
                 'every panel that shows that character — not paraphrased. '
                 'Define it once in Subject, then reuse the exact words in '
                 'each panel beat that needs it.')
    parts.append('- Use POSITIVE framing. Never write "no X" / "without X" — '
                 'GPT Image 2 often renders the negated keyword anyway. State '
                 'what IS present instead (e.g. "eyes left as raw unpainted '
                 'canvas", not "no glowing eyes").')
    parts.append('- Reference the attached images by role ("see attached '
                 'character reference", "match the attached page style").')
    parts.append(f'- Orientation: GPT Image 2 drifts to landscape unless told '
                 f'otherwise. Put this directive in BOTH the Use case and the '
                 f'Constraints, verbatim: "{orient}"')
    if differ:
        parts.append('- Same-subject close-ups converge into one image unless '
                     'differentiated. ' + differ)
    parts.append('')
    parts.append('## Page identity')
    parts.append('')
    parts.append(f'- page_id: {page_id}')
    parts.append(f'- scene: {scene_title}')
    parts.append(f'- panel_count: {panel_count}')
    parts.append('')
    parts.append('## Page frontmatter')
    parts.append('')
    parts.append(_format_frontmatter_summary(page_frontmatter))
    parts.append('')
    parts.append('## References that will be uploaded with this prompt')
    parts.append('')
    parts.append(refs)
    parts.append('')
    parts.append('## Page architecture (panel hierarchy + layout)')
    parts.append('')
    parts.append(page_architecture.strip() if page_architecture else '(none)')
    parts.append('')
    parts.append('## Panel script (the per-panel beats to distill)')
    parts.append('')
    parts.append(panel_script.strip() if panel_script else '(none)')
    parts.append('')
    parts.append('## Scene brief')
    parts.append('')
    parts.append(_format_brief(scene_brief))
    parts.append('')
    parts.append('## Canon (distill into short prompt lines — do NOT paste '
                 'verbatim)')
    parts.append('')
    for canon_id, block in canon_blocks.items():
        if not block or not block.strip():
            continue
        parts.append(f'### {canon_id}')
        parts.append('')
        parts.append(block.strip())
        parts.append('')
    parts.append('## Output contract')
    parts.append('')
    parts.append(
        'Produce ONLY the page-prompt body below — no blockquote markers, no '
        'surrounding headings, no commentary before or after. Use the exact '
        'bold section labels shown:'
    )
    parts.append('')
    parts.append('```')
    parts.append(f'**Page {page_label} — graphic novel page ({panel_count} '
                 'panels).**')
    parts.append('')
    parts.append('**Scene:** <where this happens, time of day, environment, '
                 'key set elements>')
    parts.append('')
    parts.append('**Subject:** <main focus>. **Character anchor (use this '
                 'exact description in every panel showing them):** "<one '
                 'identical description per recurring character>." See '
                 'attached character reference image.')
    parts.append('')
    parts.append('**Important details:** <composition, palette, lighting, '
                 'materials, mood — distilled from the style/lighting canon '
                 'and matched to the attached reference page(s); positive '
                 'specification only>')
    parts.append('')
    parts.append(f'**Use case:** A single graphic novel page laid out as '
                 f'{panel_count} panels in a <grid geometry>, read '
                 f'left-to-right, top-to-bottom. {orient} Continuous with the '
                 'attached reference page(s).')
    parts.append('')
    parts.append('**Panels:**')
    parts.append('')
    parts.append('1. <concrete, action-focused beat, 1-2 sentences; repeat '
                 'the character anchor for any character shown>')
    parts.append(f'(... one numbered beat per panel, through panel '
                 f'{panel_count})')
    parts.append('')
    parts.append(f'**Constraints:** <keep the layout exactly; keep each '
                 f'character identical to the reference across every panel; '
                 f'positive constraints only>. {orient}'
                 + (f' {differ}' if differ else ''))
    parts.append('```')
    parts.append('')
    parts.append('Hard requirements:')
    parts.append(f'- Include all five labels (**Scene:**, **Subject:**, '
                 '**Important details:**, **Use case:**, **Constraints:**) '
                 'and a **Panels:** list.')
    parts.append(f'- The Panels list has exactly {panel_count} numbered '
                 'beats.')
    parts.append(f'- The orientation directive appears in BOTH Use case and '
                 f'Constraints: "{orient}"')
    if differ:
        parts.append('- Differentiate the flagged same-subject close-ups so '
                     'they do not converge.')
    parts.append('- Total length ~250-400 words. Shorter is better than '
                 'padded.')
    parts.append('- Use positive specification for content; the only allowed '
                 'negation is the orientation directive above.')
    return '\n'.join(parts) + '\n'
