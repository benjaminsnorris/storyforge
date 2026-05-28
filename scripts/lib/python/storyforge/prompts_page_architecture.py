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
