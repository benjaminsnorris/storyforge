"""Page-architecture stage prompt builders.

Three coaching modes share this module so they can reuse helpers
(panel-hierarchy formatting, neighbor-page rendering, canon-block
loaders). render_strict_template emits a TODO scaffold with no LLM
call. render_coach_brief builds a question-driven brief for the
author (the handler writes it to working/coaching/). build_full_prompt
assembles the full LLM prompt with canon vocabulary + scene brief +
neighbor pages.

Issue #260: page architecture is now pure *authoring context* — the
panel hierarchy, eye-flow, and pacing intent that inform the artist and
the page prompt. The separate monochrome "page-blocking prompt" was
removed: GPT Image 2 plans layout and renders the whole page from a
single prompt, so there is no blocking pass to author.
"""

from storyforge.pages import PageFile


_STRICT_TEMPLATE_HEADER = """\
## Page architecture

### Intent
TODO — narrative purpose, emotional arc, visual rhythm, dominant motif.

### Panel hierarchy
"""

_STRICT_TEMPLATE_TAIL = """\

### Layout
TODO — grid/splash/irregular, row × column geometry, eye flow
(left-to-right, Z, F, vertical), and spread context (verso of N–N+1 |
recto of N–1–N | opening recto | closing verso). Note any page-turn beat.
"""


def _format_neighbor(label: str, page: PageFile | None) -> str:
    if not page:
        return f'- {label}: (none — this page is at the scene edge)'
    pid = page.get('page_id', '?')
    spread = page.get('spread_position', '?')
    return f'- {label}: {pid} (spread_position: {spread})'


def render_strict_template(*, page_id: str, panel_count: int) -> str:
    """Deterministic strict-mode template. No LLM call.

    Emits the `## Page architecture` section with TODO scaffolding. The
    panel hierarchy enumerates one bullet per panel (using panel_count
    from the page-file frontmatter). When panel_count is 0 (unknown) we
    still render one bullet so the author has a starting point.
    """
    bullets = max(panel_count, 1)
    hierarchy = '\n'.join(
        f'- Panel {i}: TODO register: TODO role'
        for i in range(1, bullets + 1)
    ) + '\n'
    return _STRICT_TEMPLATE_HEADER + hierarchy + _STRICT_TEMPLATE_TAIL


def render_coach_brief(*,
                       page_id: str,
                       scene_title: str,
                       panel_count: int,
                       scene_brief: dict[str, str],
                       prev_page: PageFile | None,
                       next_page: PageFile | None,
                       canon_blocks: dict[str, str]) -> str:
    """Coach-mode markdown brief written to working/coaching/.

    No file mutation of the page file. The brief asks the right
    questions and embeds the canon vocabulary inline so the author
    can decide without flipping files.
    """
    lines = [
        f'# Page architecture brief: {page_id}',
        '',
        f'**Scene:** {scene_title}  ',
        f'**Panels on this page:** {panel_count}',
        '',
        '## What you need to decide',
        '',
        '- Which panel is this page\'s emotional fulcrum (the dominant register)?',
        '- Which panels are transitional / rhythmic / atmospheric?',
        '- Is there a page-turn beat? What reveals on the turn?',
        '- What\'s the spread context (this page\'s relationship to its facing page)?',
        '- Dominant motif on this page (cite from motif canon)?',
        '- The page layout — grid/splash/irregular, geometry, and eye flow?',
        '',
        '## Canon vocabulary to use',
        '',
    ]
    for canon_id in ('panel-registers', 'page-rhythm-rules'):
        block = canon_blocks.get(canon_id, '').strip()
        if block:
            lines += [f'### {canon_id}', '', block, '']
    lines += ['## Brief inputs', '']
    for key in ('panel_breakdown', 'visual_keywords', 'page_turn_beats',
                'page_layout', 'caption_strategy'):
        val = scene_brief.get(key, '')
        lines.append(f'- **{key}:** {val or "(empty)"}')
    lines += ['', '## Sibling pages', '']
    lines.append(_format_neighbor('Previous page', prev_page))
    lines.append(_format_neighbor('Next page', next_page))
    lines += [
        '',
        '## Write your section into the page file at:',
        '',
        f'`pages/{page_id}.md` — insert the section between '
        '`## Scene context` and `## Panel script`.',
        '',
        'Section header:',
        '',
        '```',
        '## Page architecture',
        '',
        '### Intent',
        '...',
        '',
        '### Panel hierarchy',
        '- Panel 1 — <register>: <one-line role>',
        '...',
        '',
        '### Layout',
        '<grid/splash/irregular; row × column geometry; eye flow;',
        ' spread context; page-turn beat>',
        '```',
    ]
    return '\n'.join(lines) + '\n'


def _format_frontmatter_summary(fm: dict) -> str:
    keys = ('page_id', 'scene_id', 'page_within_scene',
            'total_pages_in_scene', 'panel_count', 'spread_position',
            'characters_present', 'location', 'timeline')
    lines = []
    for k in keys:
        v = fm.get(k)
        if v is None or v == '':
            continue
        if isinstance(v, list):
            v = ', '.join(v)
        lines.append(f'- {k}: {v}')
    return '\n'.join(lines) if lines else '(empty)'


def _format_brief(brief: dict) -> str:
    keys = ('page_layout', 'panel_breakdown', 'visual_keywords',
            'page_turn_beats', 'caption_strategy', 'goal', 'conflict',
            'outcome', 'emotions', 'motifs')
    lines = []
    for k in keys:
        v = brief.get(k, '')
        if v:
            lines.append(f'- {k}: {v}')
    return '\n'.join(lines) if lines else '(empty)'


def _format_intent(intent: dict) -> str:
    keys = ('function', 'emotional_arc', 'value_at_stake', 'value_shift',
            'turning_point', 'characters', 'on_stage')
    lines = []
    for k in keys:
        v = intent.get(k, '')
        if v:
            lines.append(f'- {k}: {v}')
    return '\n'.join(lines) if lines else '(empty)'


def build_full_prompt(*,
                      page_id: str,
                      page_frontmatter: PageFile,
                      scene_title: str,
                      scene_brief: dict[str, str],
                      scene_intent: dict[str, str],
                      prev_page: PageFile | None,
                      next_page: PageFile | None,
                      canon_blocks: dict[str, str]) -> str:
    """Full-mode LLM prompt for one page.

    The handler is responsible for collecting canon_blocks (panel-registers,
    page-rhythm-rules, style-foundation, lighting-laws) and the neighbor
    pages. This builder just assembles the prompt deterministically — no I/O.

    Output contract for the LLM: a single markdown block containing exactly
    one top-level section — `## Page architecture` — with three subsections
    (Intent, Panel hierarchy, Layout) and nothing else. The handler parses
    that block, asserts the header is present, and splices it into the page
    file.
    """
    parts: list[str] = []
    parts.append(
        'You are writing the page architecture — the authoring context that '
        'captures panel hierarchy, eye flow, and pacing intent — for one '
        'page of a graphic novel.'
    )
    parts.append('')
    parts.append('## Page identity')
    parts.append('')
    parts.append(f'- page_id: {page_id}')
    parts.append(f'- scene: {scene_title}')
    parts.append('')
    parts.append('## Page frontmatter')
    parts.append('')
    parts.append(_format_frontmatter_summary(page_frontmatter))
    parts.append('')
    parts.append('## Scene brief')
    parts.append('')
    parts.append(_format_brief(scene_brief))
    parts.append('')
    parts.append('## Scene intent')
    parts.append('')
    parts.append(_format_intent(scene_intent))
    parts.append('')
    parts.append('## Sibling pages (for spread context)')
    parts.append('')
    parts.append(_format_neighbor('Previous page', prev_page))
    parts.append(_format_neighbor('Next page', next_page))
    parts.append('')
    parts.append('## Canon vocabulary (cite registers by name)')
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
        'Produce exactly one markdown section, with no other text before '
        'or after:'
    )
    parts.append('')
    parts.append('```')
    parts.append('## Page architecture')
    parts.append('')
    parts.append('### Intent')
    parts.append('<narrative purpose, emotional arc, visual rhythm, dominant motif>')
    parts.append('')
    parts.append('### Panel hierarchy')
    parts.append('- Panel 1 — <register>: <one-line role>')
    parts.append('- Panel 2 — <register>: <one-line role>')
    parts.append('  (one bullet per panel; every panel cites a register '
                 'from panel-registers above)')
    parts.append('')
    parts.append('### Layout')
    parts.append('<grid/splash/irregular; row × column geometry; eye flow '
                 '(left-to-right, Z, F, vertical); spread context (verso of '
                 'N–N+1 | recto of N–1–N | opening recto | closing verso); '
                 'and any page-turn beat>')
    parts.append('```')
    parts.append('')
    parts.append('Constraints:')
    parts.append('- Every panel in the hierarchy cites a register by name '
                 'from panel-registers above.')
    parts.append('- This is authoring context, not a render prompt: describe '
                 'composition and pacing intent, not lighting or surface '
                 'detail (those live in the image-generation prompt).')
    return '\n'.join(parts) + '\n'
