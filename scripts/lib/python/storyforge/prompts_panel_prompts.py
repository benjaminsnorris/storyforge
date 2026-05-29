"""Panel-prompts stage prompt builders.

Mirrors prompts_page_architecture.py for the 13-section panel-prompt
schema introduced by issue #253. render_strict_template emits the
13-section template per panel with canon blocks embedded into sections
1, 2, 5, 6, 10 and TODO scaffolding in sections 3, 4, 7, 8, 9, 11, 12,
13. render_coach_brief builds the markdown for a per-page coaching
brief (the handler writes it to working/coaching/); build_full_prompt
assembles the LLM prompt for full coaching mode.
"""

from typing import Final

from storyforge.pages import PageFile, PANEL_SECTION_TITLES


_TODO_BY_SECTION_INDEX: Final[dict[int, str]] = {
    3: 'TODO — register (dominant | transitional | rhythmic | climactic | '
       'orientation | atmospheric) and relative weight on the page.',
    4: 'TODO — camera, framing, angle.',
    7: 'TODO — character framing in this beat (what each character is doing).',
    8: 'TODO — what receives detail vs. what dissolves.',
    9: 'TODO — panel-specific lighting (lamp side, shadow falloff).',
    11: 'TODO — declarative, procedural action ("lowers the inkpot"), '
        'not narrative ("the room cooling around the act").',
    12: 'TODO — single brief sentence labeled "(low weight)".',
    13: 'TODO — exclusions and motif-specific reinforcements.',
}


def _section_body_strict(section_index: int, canon_blocks: dict[str, str],
                         panel_register: str) -> str:
    """Return the body for one section under strict mode.

    Sections 1, 2 embed the universal canon blocks.
    Section 3 cites the register from page architecture (or TODO if absent).
    Sections 5, 6, 10 embed canon when keys with those prefixes exist in
    canon_blocks; otherwise TODO. Sections 4, 7, 8, 9, 11, 12, 13 are
    TODO scaffolding.
    """
    if section_index == 1:
        block = canon_blocks.get('style-foundation', '').strip()
        return block if block else 'TODO — paste the style-foundation embeddable block here.'
    if section_index == 2:
        block = canon_blocks.get('lighting-laws', '').strip()
        return block if block else 'TODO — paste the lighting-laws embeddable block here.'
    if section_index == 3:
        if panel_register:
            return f'Register: {panel_register}. TODO — relative weight on the page.'
        return _TODO_BY_SECTION_INDEX[3]
    if section_index == 5:
        location_keys = [k for k in canon_blocks if k.startswith('locations/')]
        if location_keys:
            block = canon_blocks[location_keys[0]].strip()
            return f'{block}\n\nTODO — panel-specific positioning.'
        return 'TODO — embed the location canon block + panel-specific positioning.'
    if section_index == 6:
        character_keys = [k for k in canon_blocks if k.startswith('characters/')]
        if character_keys:
            blocks = '\n\n'.join(canon_blocks[k].strip() for k in character_keys)
            return blocks
        return 'TODO — embed character canon blocks for each on-frame character.'
    if section_index == 10:
        motif_keys = [k for k in canon_blocks if k.startswith('motifs/')]
        if motif_keys:
            blocks = '\n\n'.join(
                f'{canon_blocks[k].strip()} (low weight)' for k in motif_keys
            )
            return blocks
        return 'TODO — embed motif canon for any motif on-frame, labeled "(low weight)".'
    return _TODO_BY_SECTION_INDEX.get(section_index, 'TODO')


def render_strict_template(*, page_id: str, panel_count: int,
                           canon_blocks: dict[str, str],
                           panel_registers: dict[int, str]) -> str:
    """Deterministic strict-mode template for one page's panel prompts.

    Emits ### Panel N blocks (one per panel), each containing #### M.
    <Title> subsections in canonical 1..13 order. Sections 1, 2, 5, 6,
    10 embed canon blocks when present in canon_blocks; section 3 cites
    the register from panel_registers when present, otherwise TODO;
    sections 4, 7, 8, 9, 11, 12, 13 are TODO scaffolding.

    canon_blocks keys: 'style-foundation', 'lighting-laws',
    'locations/<id>', 'characters/<id>', 'motifs/<id>'. Missing keys
    cause the corresponding section to fall back to TODO.
    """
    bullets = max(panel_count, 1)
    parts: list[str] = ['## Image-generation prompts']
    for panel_index in range(1, bullets + 1):
        parts.append('')
        parts.append(f'### Panel {panel_index}')
        register = panel_registers.get(panel_index, '')
        for section_index in range(1, 14):
            title = PANEL_SECTION_TITLES[section_index - 1]
            body = _section_body_strict(section_index, canon_blocks, register)
            parts.append('')
            parts.append(f'#### {section_index}. {title}')
            parts.append('')
            parts.append(body)
    return '\n'.join(parts) + '\n'


def render_coach_brief(*, page_id: str, panel_count: int,
                       scene_title: str, page_architecture: str,
                       scene_brief: dict[str, str], canon_blocks: dict[str, str]) -> str:
    """Coach-mode markdown brief written to working/coaching/.

    Embeds canon vocabulary inline so the author can decide without
    flipping files. Lists the 13 sections with one or two prompting
    questions per section. Does NOT mutate the page file.
    """
    lines = [
        f'# Panel-prompts brief: {page_id}',
        '',
        f'**Scene:** {scene_title}  ',
        f'**Panels on this page:** {panel_count} panel{"s" if panel_count != 1 else ""}',
        '',
        '## Page architecture (from page-architecture stage)',
        '',
        page_architecture.strip() if page_architecture else '(none — run elaborate --stage page-architecture first)',
        '',
        '## Brief inputs',
        '',
    ]
    for key in ('panel_breakdown', 'visual_keywords', 'key_actions',
                'key_dialogue', 'motifs', 'emotions'):
        val = scene_brief.get(key, '')
        lines.append(f'- **{key}:** {val or "(empty)"}')
    lines += ['', '## Canon embeds (style-foundation -> §1, lighting-laws -> §2, '
              'sections 5, 6, 10; panel-registers is reference vocabulary for §3)', '']
    for canon_id in ('style-foundation', 'lighting-laws',
                     'panel-registers'):
        block = canon_blocks.get(canon_id, '').strip()
        if block:
            lines += [f'### {canon_id}', '', block, '']
    lines += [
        '## What to write per panel',
        '',
        'Write `### Panel N` blocks (one per panel) into the '
        '`## Image-generation prompts` section of:',
        '',
        f'`pages/{page_id}.md`',
        '',
        'Each panel must contain these 13 sections in order:',
        '',
    ]
    questions_by_section: dict[int, str] = {
        1: 'Paste the style-foundation embeddable block verbatim.',
        2: 'Paste the lighting-laws embeddable block verbatim.',
        3: 'Cite the register from page architecture (dominant / transitional / '
           'rhythmic / climactic / orientation / atmospheric). State this panel\'s '
           'relative weight on the page.',
        4: 'Camera distance, framing, angle. What\'s the shot grammar?',
        5: 'Paste the location embeddable block, then add panel-specific positioning '
           '(who\'s where in the frame).',
        6: 'Paste the character embeddable block for each on-frame character.',
        7: 'What is each character doing in THIS beat? What\'s the body language?',
        8: 'What receives detail (the inkpot, the hand)? What dissolves (background)?',
        9: 'Which side catches the light? Where do shadows fall?',
        10: 'If a motif is on-frame, paste its canon block. Label it "(low weight)".',
        11: 'Declarative procedural action ("lowers the inkpot"). NOT narrative '
            '("the room cooling around the act").',
        12: 'One brief sentence. Label "(low weight)". Emotional subtext only — '
            'no description of how it manifests visually.',
        13: 'What should the renderer NOT produce? Exclusions specific to this '
            'panel + motif reinforcements.',
    }
    for n in range(1, 14):
        title = PANEL_SECTION_TITLES[n - 1]
        lines.append(f'#### {n}. {title}')
        lines.append(f'  — {questions_by_section[n]}')
        lines.append('')
    return '\n'.join(lines) + '\n'


def _format_frontmatter_summary(fm: PageFile) -> str:
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


def _format_brief(brief: dict[str, str]) -> str:
    keys = ('panel_breakdown', 'visual_keywords', 'key_actions',
            'key_dialogue', 'motifs', 'emotions',
            'page_layout', 'page_turn_beats', 'caption_strategy',
            'goal', 'conflict', 'outcome')
    lines = []
    for k in keys:
        v = brief.get(k, '')
        if v:
            lines.append(f'- {k}: {v}')
    return '\n'.join(lines) if lines else '(empty)'


def _format_intent(intent: dict[str, str]) -> str:
    keys = ('function', 'emotional_arc', 'value_at_stake', 'value_shift',
            'turning_point', 'characters', 'on_stage')
    lines = []
    for k in keys:
        v = intent.get(k, '')
        if v:
            lines.append(f'- {k}: {v}')
    return '\n'.join(lines) if lines else '(empty)'


def build_full_prompt(*, page_id: str, panel_count: int,
                      scene_title: str,
                      page_frontmatter: PageFile,
                      page_architecture: str,
                      scene_brief: dict[str, str],
                      scene_intent: dict[str, str],
                      canon_blocks: dict[str, str]) -> str:
    """Full-mode LLM prompt for one page's panel prompts.

    The handler collects canon_blocks (style-foundation, lighting-laws,
    panel-registers, per-location, per-character, per-motif) and the
    page architecture body. This builder is pure — no I/O.

    Output contract: the LLM emits ### Panel 1 .. ### Panel N markdown,
    each containing #### M. <Title> subsections in canonical 1..13 order.
    Sections 1, 2, 5, 6, 10 contain the canon embeds verbatim; sections
    3, 4, 7, 8, 9, 11, 12, 13 are panel-specific prose. Sections 10 and
    12 must end with the literal text "(low weight)" — the Constraints
    block in the prompt enforces this. Without it, diffusion models render
    symbolic / emotional prose as visual intensity.
    """
    parts: list[str] = []
    parts.append(
        f'You are writing the 13-section image-generation prompts for '
        f'{panel_count} panel(s) on one page of a graphic novel.'
    )
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
    parts.append('## Page architecture (panel hierarchy + registers)')
    parts.append('')
    parts.append(page_architecture.strip() if page_architecture else '(none)')
    parts.append('')
    parts.append('## Scene brief')
    parts.append('')
    parts.append(_format_brief(scene_brief))
    parts.append('')
    parts.append('## Scene intent')
    parts.append('')
    parts.append(_format_intent(scene_intent))
    parts.append('')
    parts.append('## Canon (embed verbatim into the noted sections)')
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
        'Produce exactly the markdown below — `### Panel 1` through '
        f'`### Panel {panel_count}`, each with all 13 sections in '
        'canonical order — and no other text before or after:'
    )
    parts.append('')
    parts.append('```')
    parts.append('### Panel 1')
    parts.append('')
    for section_index in range(1, 14):
        title = PANEL_SECTION_TITLES[section_index - 1]
        parts.append(f'#### {section_index}. {title}')
        parts.append('')
        if section_index in (1, 2):
            canon_id = ('style-foundation' if section_index == 1
                        else 'lighting-laws')
            parts.append(f'<verbatim {canon_id} embed from above>')
        elif section_index == 3:
            parts.append('Register: <one of dominant | transitional | rhythmic | '
                         'climactic | orientation | atmospheric — cite from '
                         'page architecture above>. Relative weight: <how this '
                         'panel ranks within the page>.')
        elif section_index == 4:
            parts.append('<camera distance, framing, angle>')
        elif section_index == 5:
            parts.append('<verbatim location-canon embed from above>')
            parts.append('')
            parts.append('Panel-specific: <who is where in the frame>')
        elif section_index == 6:
            parts.append('<verbatim character-canon embed(s) for each on-frame character>')
        elif section_index == 7:
            parts.append('<each character\'s framing in this beat — what they are doing>')
        elif section_index == 8:
            parts.append('<what gets detail vs. what dissolves>')
        elif section_index == 9:
            parts.append('<panel-specific lighting — which side catches the lamp, '
                         'where shadows fall>')
        elif section_index == 10:
            parts.append('<verbatim motif-canon embed if motif on-frame, '
                         'plus the literal text "(low weight)" at the end>')
        elif section_index == 11:
            parts.append('<declarative procedural action — "lowers the inkpot", '
                         'NOT "the room cooling around the act">')
        elif section_index == 12:
            parts.append('<single brief sentence labeled "(low weight)">')
        elif section_index == 13:
            parts.append('<panel-specific exclusions + motif-specific reinforcements>')
        parts.append('')
    parts.append('### Panel 2')
    parts.append('<same 13-section structure>')
    parts.append('')
    parts.append(f'(... up through ### Panel {panel_count})')
    parts.append('```')
    parts.append('')
    parts.append('Constraints (all panels MUST satisfy):')
    parts.append('- Sections 1, 2, 5, 6, 10 contain the canon embeds verbatim. '
                 'Do not paraphrase. Do not abbreviate.')
    parts.append('- Section 3 cites a register from the page architecture above '
                 'by name. Every panel cites exactly one register.')
    parts.append('- Sections 11 (Action) is declarative and procedural. No '
                 'narrative description. No metaphor.')
    parts.append('- Sections 10 and 12 contain the literal text "(low weight)" '
                 'at the end of their bodies. This is critical — without it, '
                 'diffusion models render symbolic / emotional prose as visual '
                 'intensity.')
    return '\n'.join(parts) + '\n'
