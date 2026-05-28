"""Panel-prompts stage prompt builders.

Mirrors prompts_page_architecture.py for the 13-section panel-prompt
schema introduced by issue #253. render_strict_template emits the
13-section template per panel with canon blocks embedded into sections
1, 2, 5, 6, 10 and TODO scaffolding in sections 3, 4, 7, 8, 9, 11, 12,
13. render_coach_brief writes a per-page brief; build_full_prompt
assembles the LLM prompt for full coaching mode.
"""

from storyforge.pages import PageFile, PANEL_SECTION_TITLES


_TODO_BY_SECTION_INDEX: dict[int, str] = {
    3: 'TODO — register (dominant | transitional | rhythmic | climactic | '
       'atmospheric) and relative weight on the page.',
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
    10 embed canon blocks when present in canon_blocks; sections 3, 4,
    7, 8, 9, 11, 12, 13 are TODO scaffolding. Section 3 cites the
    register from panel_registers when present.

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
                       scene_brief: dict, canon_blocks: dict[str, str]) -> str:
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
    lines += ['', '## Canon embeds (paste verbatim into sections 1, 2, 5, 6, 10)', '']
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
