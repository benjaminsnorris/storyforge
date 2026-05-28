"""Page-architecture stage prompt builders.

Three coaching modes share this module so they can reuse helpers
(panel-hierarchy formatting, neighbor-page rendering, canon-block
loaders). render_strict_template emits a TODO scaffold with no LLM
call. render_coach_brief writes a question-driven brief for the
author. build_full_prompt assembles the full LLM prompt with canon
embeds + scene brief + neighbor pages.
"""


_STRICT_TEMPLATE_HEADER = """\
## Page architecture

### Intent
TODO — narrative purpose, emotional arc, visual rhythm, dominant motif.

### Panel hierarchy
"""

_STRICT_TEMPLATE_TAIL = """\

### Book-level placement
- Spread context: TODO (verso of N–N+1 | recto of N–1–N | opening recto | closing verso)
- Page-turn beat: TODO (yes/no — what reveals on the turn)

## Page-blocking prompt

TODO — monochrome storyboard thumbnail. Must:
- Cite panel registers by name (dominant | transitional | rhythmic |
  climactic | atmospheric — see reference/canon/panel-registers.md)
- Specify panel geometry (grid? splash? irregular? tier count?)
- Specify eye flow (left-to-right, Z, F, vertical)
- Be pure compositional blocking — no surface texture, no faces,
  no fine line work
"""


def _format_neighbor(label: str, page: dict | None) -> str:
    if not page:
        return f'- {label}: (none — this page is at the scene edge)'
    pid = page.get('page_id', '?')
    spread = page.get('spread_position', '?')
    return f'- {label}: {pid} (spread_position: {spread})'


def render_strict_template(*, page_id: str, panel_count: int) -> str:
    """Deterministic strict-mode template. No LLM call.

    Emits both new body sections with TODO scaffolding. The panel
    hierarchy enumerates one bullet per panel (using panel_count from
    the page-file frontmatter). When panel_count is 0 (unknown) we
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
                       scene_brief: dict,
                       prev_page: dict | None,
                       next_page: dict | None,
                       canon_blocks: dict) -> str:
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
        '## Write your sections into the page file at:',
        '',
        f'`pages/{page_id}.md` — insert both sections between '
        '`## Scene context` and `## Panel script`.',
        '',
        'Section headers:',
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
        '### Book-level placement',
        '- Spread context: ...',
        '- Page-turn beat: ...',
        '',
        '## Page-blocking prompt',
        '',
        '<monochrome storyboard thumbnail; cite registers by name;',
        ' specify geometry, eye flow; no surface texture, no faces>',
        '```',
    ]
    return '\n'.join(lines) + '\n'
