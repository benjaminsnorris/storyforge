"""storyforge assemble (graphic-novel mode) — Artist handoff bundle.

Produces manuscript/{script.md, visual-references.md, chapter-map.md,
handoff-readme.md, style-guide.md}.

Usage:
    storyforge assemble               # Default: markdown bundle
    storyforge assemble --dry-run     # Show what would be done
"""

import argparse
import json
import os
import re
import sys

from storyforge.api import (
    invoke_to_file, calculate_cost_from_usage, extract_usage,
)
from storyforge.common import (
    CoachingLevel, detect_project_root, get_coaching_level, log,
    install_signal_handlers, get_medium, read_yaml_field, select_model,
)
from storyforge.costs import log_operation


# ---------------------------------------------------------------------------
# Argument parsing
# ---------------------------------------------------------------------------

def parse_args(argv):
    p = argparse.ArgumentParser(prog='storyforge assemble (gn)')
    p.add_argument('--dry-run', action='store_true',
                   help='Show what would be done without writing files')
    p.add_argument('--force', action='store_true',
                   help='Bundle even if some scenes are not yet drafted.')
    p.add_argument('--coaching', type=str, default=None,
                   choices=['full', 'coach', 'strict'],
                   help='Override coaching level for the style-guide '
                        'generation (default: project setting).')
    return p.parse_args(argv)


# ---------------------------------------------------------------------------
# Chapter-map reading
# ---------------------------------------------------------------------------

def _read_chapter_map(path):
    """Return list of {chapter, title, heading, scenes:[id,...]} or None if missing."""
    if not os.path.isfile(path):
        return None
    chapters = []
    with open(path, encoding='utf-8') as f:
        header_line = next(f, None)
        if header_line is None:
            return chapters
        header = header_line.strip().split('|')
        for line in f:
            raw = line.rstrip('\n')
            if not raw.strip():
                continue
            fields = raw.split('|')
            row = dict(zip(header, fields))
            row['scenes'] = [s.strip() for s in row.get('scenes', '').split(';') if s.strip()]
            chapters.append(row)
    return chapters


# ---------------------------------------------------------------------------
# Page renumbering
# ---------------------------------------------------------------------------

# Matches `## Page N —` at start of line.  Group 1 = the number string.
# The trailing content (layout tag + optional page-turn marker) is left intact
# because the match uses the full prefix `## Page N — ` which is then replaced
# only at the `N` part.
PAGE_HEADER_RE = re.compile(r'^(## Page )(\d+)( — )', re.MULTILINE)


def _renumber_pages(scene_text, start):
    """Renumber `## Page N — ` headers starting from `start`.

    The layout tag and ⟵ PAGE-TURN REVEAL marker are preserved because they
    follow the `— ` separator which is outside the captured number group.

    Returns (renumbered_text, next_page_number).
    """
    counter = [start]

    def repl(m):
        new_num = counter[0]
        counter[0] += 1
        return f'{m.group(1)}{new_num}{m.group(3)}'

    new_text = PAGE_HEADER_RE.sub(repl, scene_text)
    return new_text, counter[0]


# ---------------------------------------------------------------------------
# Script assembly
# ---------------------------------------------------------------------------

def _assemble_script(project_dir, chapters, title):
    """Concatenate scenes in chapter order with global page numbering.

    Returns the assembled markdown string.
    """
    from storyforge.script_format import count_panels

    global_page = 1
    total_panels = 0
    body_parts = []

    for chap in chapters:
        body_parts.append(f'\n# Chapter {chap["chapter"]} — {chap["title"]}\n')
        for sid in chap['scenes']:
            scene_path = os.path.join(project_dir, 'scenes', f'{sid}.md')
            if not os.path.isfile(scene_path):
                log(f'  WARNING: scene file not found: scenes/{sid}.md')
                body_parts.append(f'\n*[scene {sid} not found]*\n')
                continue
            text = open(scene_path, encoding='utf-8').read()
            total_panels += count_panels(text)
            renumbered, global_page = _renumber_pages(text, global_page)
            body_parts.append(renumbered)
            body_parts.append('\n')

    total_pages = global_page - 1
    header = (
        f'# {title} — Artist Script\n\n'
        f'_Auto-generated. See handoff-readme.md for format conventions._\n\n'
        f'**Total pages:** {total_pages} | **Total panels:** {total_panels}\n'
    )
    return header + ''.join(body_parts)


# ---------------------------------------------------------------------------
# Visual reference extraction
# ---------------------------------------------------------------------------

def _extract_visual_subsection(section_text, char_header):
    """Extract only the ### Visual subsection from a ## Character section.

    Returns a string with the character header followed by the Visual
    subsection content only (stops at the next ### or ## heading or EOF).
    """
    # Find the start of the ### Visual block
    visual_match = re.search(r'^### [Vv]isual', section_text, re.MULTILINE)
    if not visual_match:
        return None
    # Extract from the ### Visual heading to the next ### or ## heading
    after_visual = section_text[visual_match.start():]
    next_heading = re.search(r'^(?:###|##) ', after_visual[4:], re.MULTILINE)
    if next_heading:
        visual_block = after_visual[:next_heading.start() + 4].rstrip()
    else:
        visual_block = after_visual.rstrip()
    return f'## {char_header}\n\n{visual_block}'


def _extract_visual_references(project_dir, title):
    """Pull character Visual subsections + world-bible visual notes.

    Extracts only the `### Visual` subsection (plus the character header for
    context) from each `## CharacterName` block in character-bible.md, and
    similarly from world-bible.md. Non-visual subsections (### Personality,
    ### Backstory, etc.) are excluded.
    """
    parts = [
        f'# {title} — Visual References\n',
        '_For the artist. Pin to your drawing table._\n',
    ]

    ref_dir = os.path.join(project_dir, 'reference')

    char_path = os.path.join(ref_dir, 'character-bible.md')
    if os.path.isfile(char_path):
        content = open(char_path, encoding='utf-8').read()
        # Split on level-2 headers (## ...).  sections[0] is pre-first-header preamble.
        sections = re.split(r'^## ', content, flags=re.MULTILINE)
        char_sections = []
        for sec in sections[1:]:
            char_header = sec.split('\n', 1)[0].strip()
            extracted = _extract_visual_subsection(sec, char_header)
            if extracted is not None:
                char_sections.append(extracted)
        if char_sections:
            parts.append('\n## Characters\n')
            parts.extend(s + '\n' for s in char_sections)

    world_path = os.path.join(ref_dir, 'world-bible.md')
    if os.path.isfile(world_path):
        content = open(world_path, encoding='utf-8').read()
        sections = re.split(r'^## ', content, flags=re.MULTILINE)
        world_sections = []
        for sec in sections[1:]:
            loc_header = sec.split('\n', 1)[0].strip()
            extracted = _extract_visual_subsection(sec, loc_header)
            if extracted is not None:
                world_sections.append(extracted)
        if world_sections:
            parts.append('\n## Settings\n')
            parts.extend(s + '\n' for s in world_sections)

    return '\n'.join(parts)


# ---------------------------------------------------------------------------
# Chapter-map rendering
# ---------------------------------------------------------------------------

def _render_chapter_map(chapters, title):
    """Render the chapter map as readable markdown."""
    out = [f'# {title} — Chapter Map\n']
    for chap in chapters:
        out.append(f'\n## Chapter {chap["chapter"]} — {chap["title"]}\n')
        scene_list = ', '.join(chap['scenes']) if chap['scenes'] else '(none)'
        out.append(f'Scenes: {scene_list}\n')
    return '\n'.join(out)


# ---------------------------------------------------------------------------
# Handoff README template
# ---------------------------------------------------------------------------

HANDOFF_README = """\
# Artist Handoff — {title}

This bundle contains everything you need to illustrate the graphic novel.

## Files

- `script.md` — The complete panel-by-panel script. Pages are globally numbered.
- `visual-references.md` — Character and location reference notes. Pin these up.
- `chapter-map.md` — How scenes group into chapters/issues.

## Script format

Each scene begins with `# Scene: {{scene-id}}`.

Each page begins with `## Page N — LAYOUT` where LAYOUT is one of:
- `SPLASH` — full-page single panel
- `6-PANEL GRID`, `9-PANEL GRID`, etc. — grid layouts
- `DOUBLE-SPREAD` — two-page spread
- `TIER` — horizontal strip
- `IRREGULAR` — non-grid layout (artist's discretion)

Each panel block starts with `**Panel N**` and may include a size hint in parens.

Panel composition is described in 1-3 sentences of prose. Interpret freely
for art direction; layout and panel count are authorial.

## Dialogue prefix vocabulary

- `CAPTION:` — Narration or omniscient caption box
- `{{CHARACTER NAME}}:` — Spoken word balloon
- `SFX:` — Sound effect (lettered as part of the art)
- `WHISPER:` — Whispered dialogue (smaller, italic balloon)
- `THOUGHT:` — Thought bubble
- `OFF-PANEL:` — Speaker not visible in the panel

## Page-turn beats

Any page header ending with ` ⟵ PAGE-TURN REVEAL` marks a beat that should
land as a recto-to-verso reveal. Try to ensure the prior page is on the
left (verso), so the reader physically turns the page into the moment.

## Questions

Reach out to the author with any questions about the script.
"""


# ---------------------------------------------------------------------------
# Style guide generation
# ---------------------------------------------------------------------------

_STYLE_GUIDE_SECTIONS = [
    'Palette',
    'Line weight and inking',
    'Lettering and caption tone',
    'Panel-rhythm philosophy',
    'Reference-art inspirations',
]


def _gather_style_cues(project_dir: str) -> dict:
    """Pull style cues from project state for the style-guide generator.

    Returns a dict with whatever could be located; absent files are
    represented as empty strings so callers can render cleanly without
    extra existence checks.
    """
    out = {
        'genre': read_yaml_field('project.genre', project_dir) or '',
        'subgenre': read_yaml_field('project.subgenre', project_dir) or '',
        'world_bible': _read_optional(
            os.path.join(project_dir, 'reference', 'world-bible.md'),
        ),
        'character_bible': _read_optional(
            os.path.join(project_dir, 'reference', 'character-bible.md'),
        ),
        'voice_guide': _read_optional(
            os.path.join(project_dir, 'reference', 'voice-guide.md'),
        ),
        'scene_intent_excerpt': _read_optional(
            os.path.join(project_dir, 'reference', 'scene-intent.csv'),
            head_lines=8,
        ),
    }
    return out


def _read_optional(path: str, head_lines: int | None = None) -> str:
    """Read a file if it exists; return '' otherwise. Optionally truncate
    to the first N lines so LLM prompts stay bounded."""
    if not os.path.isfile(path):
        return ''
    try:
        with open(path, encoding='utf-8') as f:
            text = f.read()
    except (OSError, UnicodeDecodeError):
        return ''
    if head_lines:
        lines = text.splitlines()
        if len(lines) > head_lines:
            text = '\n'.join(lines[:head_lines]) + '\n…'
    return text


def _render_strict_style_guide(title: str, cues: dict) -> str:
    """strict coaching: blank section template + constraint list.

    No prose, no LLM. The author fills each section themselves. Sections
    list the fields each section should cover so the author has a
    checklist while drafting.
    """
    out: list[str] = [
        f'# {title} — Style guide',
        '',
        '<!-- Constraint template generated in `coaching=strict` mode. '
        'The author drafts every section; this file lists what each must '
        'cover. Source material referenced from world-bible.md, '
        'character-bible.md, voice-guide.md, and scene-intent.csv. -->',
        '',
    ]
    out.extend([
        '## Palette',
        '',
        'Cover: 4-8 hex codes for the primary palette; warm/cool/neutral '
        'balance; one or two callouts for accent colors used sparingly; '
        'palette shifts per act if intended.',
        '',
        '## Line weight and inking',
        '',
        'Cover: line-weight intent (heavy / medium / variable); whether '
        'silhouettes lead; ink texture (clean digital / brush / scratchy); '
        'how line weight signals tone shifts.',
        '',
        '## Lettering and caption tone',
        '',
        'Cover: caption voice (none / minimal / journal-voiceover / '
        'omniscient); font-family intent; whisper / thought / SFX '
        'treatments; balloon shape grammar.',
        '',
        '## Panel-rhythm philosophy',
        '',
        'Cover: when to splash vs grid; preferred transitions '
        '(moment / action / subject / scene / aspect / non-sequitur); '
        'how page turns are reserved; tier or irregular usage guidance.',
        '',
        '## Reference-art inspirations',
        '',
        'Cover: 3-6 specific reference artists or works; what to pull from '
        'each (composition? palette? line work?); deliberate distinctions '
        'from those references.',
        '',
    ])
    # Append a compact source-map so the author can grep cues from project state.
    out.append('## Source pointers')
    out.append('')
    if cues['genre'] or cues['subgenre']:
        out.append(f'- Genre / subgenre: {cues["genre"]} / {cues["subgenre"]}')
    for key, path in (
        ('world_bible', 'reference/world-bible.md'),
        ('character_bible', 'reference/character-bible.md'),
        ('voice_guide', 'reference/voice-guide.md'),
    ):
        if cues[key]:
            out.append(f'- See: {path}')
    out.append('')
    return '\n'.join(out)


def _render_coach_style_guide(title: str, cues: dict) -> str:
    """coach coaching: sections + 'cues from project state' bullet list
    under each, asking questions to focus the author's drafting. No LLM.
    """
    out: list[str] = [
        f'# {title} — Style guide',
        '',
        '<!-- Coaching brief generated in `coaching=coach` mode. Each '
        'section lists cues pulled from project state and questions for '
        'the author to weigh; the author writes the final guide. -->',
        '',
    ]
    genre = (cues['genre'] or '').strip()
    subgenre = (cues['subgenre'] or '').strip()
    genre_line = (f'{genre}' + (f' / {subgenre}' if subgenre else '')) or 'unset'

    out.extend([
        '## Palette',
        '',
        f'- Genre cue: {genre_line} — what palette signals this register?',
        '- Question: do you want a single palette across acts, or shifts?',
        '- Question: which color is reserved for the protagonist? for the '
        'antagonist? for emotional climaxes?',
        '',
    ])

    out.extend([
        '## Line weight and inking',
        '',
        '- Cue: voice-guide.md (see file) for the project\'s tonal register.',
        '- Question: heavy / medium / variable — and where do you break the '
        'pattern intentionally?',
        '- Question: does line weight track POV or stakes?',
        '',
    ])

    out.extend([
        '## Lettering and caption tone',
        '',
        '- Cue: scene-briefs.csv `caption_strategy` field (none / minimal / '
        'journal-voiceover / omniscient) — what mix appears across scenes?',
        '- Question: is caption font a primary character beat or background '
        'voice?',
        '- Question: how do you treat off-panel and thought balloons?',
        '',
    ])

    out.extend([
        '## Panel-rhythm philosophy',
        '',
        '- Cue: scene-intent.csv `emotional_arc` patterns — what arc shapes '
        'recur, and what page rhythm matches them?',
        '- Question: when do you splash? when do you grid? when do you '
        'allow tier or irregular?',
        '- Question: are page turns reserved (per Plan 1 layout vocabulary), '
        'and what beat earns them?',
        '',
    ])

    out.extend([
        '## Reference-art inspirations',
        '',
        '- Cue: world-bible.md and character-bible.md for visual reference '
        'sections (if any).',
        '- Question: 3-6 specific artists or works — what does each one '
        'contribute to YOUR style, not theirs?',
        '- Question: where do you DELIBERATELY diverge from each reference?',
        '',
    ])
    return '\n'.join(out)


_FULL_STYLE_GUIDE_PROMPT = """\
You are drafting a style guide for the artist handing off a graphic
novel. The author has provided the following project context. Produce
a single markdown document with the standard sections.

# Project metadata

Title: {title}
Genre: {genre}
Subgenre: {subgenre}

# Voice guide (excerpt)

{voice_guide}

# World bible (excerpt)

{world_bible}

# Character bible (excerpt)

{character_bible}

# Scene-intent excerpt (CSV)

{scene_intent_excerpt}

# Task

Produce a markdown document with EXACTLY these top-level sections in
this order:

# {title} — Style guide

## Palette
## Line weight and inking
## Lettering and caption tone
## Panel-rhythm philosophy
## Reference-art inspirations

Each section: 3-6 sentences of specific, opinionated guidance grounded
in the project metadata above. Be concrete (hex codes if you can,
specific artist references, named transition types). Do NOT invent
content that contradicts the source material; when in doubt, surface
the choice rather than guess.

Return only the markdown document — no JSON, no preamble.
"""


def _render_full_style_guide(project_dir: str, title: str, cues: dict,
                              dry_run: bool) -> str:
    """full coaching: LLM-generated style guide. Falls back to the coach
    template if the LLM call fails or in dry-run mode."""
    if dry_run:
        return _render_coach_style_guide(title, cues)
    # Truncate long bibles so the prompt stays bounded.
    def _trim(text: str, lines: int) -> str:
        if not text:
            return '(not present)'
        parts = text.splitlines()
        if len(parts) > lines:
            return '\n'.join(parts[:lines]) + '\n…'
        return text

    prompt = _FULL_STYLE_GUIDE_PROMPT.format(
        title=title,
        genre=cues['genre'] or 'unset',
        subgenre=cues['subgenre'] or 'unset',
        voice_guide=_trim(cues['voice_guide'], 80),
        world_bible=_trim(cues['world_bible'], 100),
        character_bible=_trim(cues['character_bible'], 100),
        scene_intent_excerpt=cues['scene_intent_excerpt'] or '(empty)',
    )
    model = select_model('creative')
    log_dir = os.path.join(project_dir, 'working', 'logs', 'script-package')
    os.makedirs(log_dir, exist_ok=True)
    log_file = os.path.join(log_dir, 'style-guide.json')
    try:
        invoke_to_file(prompt, model, log_file, max_tokens=4096)
    except Exception as e:
        log(f'WARNING: style-guide LLM call failed ({e}); falling back to '
            f'coach-mode template.')
        return _render_coach_style_guide(title, cues)
    text = _extract_response_text(log_file)
    if not text or not text.strip().startswith('#'):
        log(f'WARNING: style-guide LLM response unparseable; falling back to '
            f'coach-mode template.')
        return _render_coach_style_guide(title, cues)
    _record_style_guide_cost(project_dir, log_file, model)
    return text


def _extract_response_text(log_file: str) -> str:
    try:
        with open(log_file, encoding='utf-8') as f:
            resp = json.load(f)
        for block in resp.get('content', []):
            if block.get('type') == 'text':
                return block.get('text', '')
    except (OSError, json.JSONDecodeError) as e:
        log(f'WARNING: could not read style-guide response file: {e}')
    return ''


def _record_style_guide_cost(project_dir: str, log_file: str,
                              model: str) -> None:
    try:
        with open(log_file, encoding='utf-8') as f:
            resp = json.load(f)
        usage = extract_usage(resp)
        cost = calculate_cost_from_usage(usage, model)
        log_operation(
            project_dir, 'assemble-gn-style-guide', model,
            usage['input_tokens'], usage['output_tokens'], cost,
            target='style-guide',
            cache_read=usage.get('cache_read', 0),
            cache_create=usage.get('cache_create', 0),
        )
    except (OSError, json.JSONDecodeError, KeyError) as e:
        log(f'WARNING: cost ledger update failed: {e}')


def _assemble_style_guide(project_dir: str, title: str,
                           coaching: CoachingLevel, dry_run: bool) -> str:
    """Generate the style-guide markdown for the artist handoff bundle.

    Coaching levels:
      - strict: blank template + constraint list (no LLM).
      - coach:  template + cues pulled from project state + author
                questions per section (no LLM creative content).
      - full:   LLM-synthesized guide from project context. Falls back
                to the coach template on LLM failure / API-key missing.
    """
    cues = _gather_style_cues(project_dir)
    if coaching == 'strict':
        return _render_strict_style_guide(title, cues)
    if coaching == 'coach':
        return _render_coach_style_guide(title, cues)
    # full coaching: LLM only if API key + not dry-run; else fall through
    # to coach template (matches the rest of the bundle, which is also
    # deterministic — the LLM is an enhancement, not a requirement).
    if dry_run:
        return _render_coach_style_guide(title, cues)
    if not os.environ.get('ANTHROPIC_API_KEY'):
        log('NOTE: ANTHROPIC_API_KEY not set; style-guide will fall back '
            'to the coach-mode template (deterministic). Set the key for '
            'an LLM-synthesized guide.')
        return _render_coach_style_guide(title, cues)
    return _render_full_style_guide(project_dir, title, cues, dry_run)


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main(argv=None):
    args = parse_args(argv if argv is not None else sys.argv[1:])
    install_signal_handlers()

    project_dir = detect_project_root()

    # Validate medium
    if get_medium(project_dir) != 'graphic-novel':
        log('ERROR: cmd_script_package invoked on a non-graphic-novel project.')
        log('Use `storyforge assemble` for novel projects.')
        sys.exit(1)

    # Require chapter map
    chapter_map_path = os.path.join(project_dir, 'reference', 'chapter-map.csv')
    chapters = _read_chapter_map(chapter_map_path)
    if not chapters:
        log('ERROR: reference/chapter-map.csv is missing or empty.')
        log('Create a chapter map before assembling the artist bundle.')
        log('Each row: chapter|title|heading|scenes (semicolon-separated scene IDs)')
        sys.exit(1)

    title = read_yaml_field('project.title', project_dir) or 'Untitled'

    # Dry-run: report what would be done (runs before the drafted check so
    # authors can preview the bundle plan even if some scenes are not yet drafted)
    if args.dry_run:
        from storyforge.csv_cli import get_field as _gf
        _scenes_csv = os.path.join(project_dir, 'reference', 'scenes.csv')
        print('===== DRY RUN: script-package =====')
        print(f'Project: {title}')
        print(f'Chapters: {len(chapters)}')
        total_scenes = sum(len(c['scenes']) for c in chapters)
        print(f'Scenes: {total_scenes}')
        for chap in chapters:
            print(f'  Chapter {chap["chapter"]}: {chap["title"]}')
            for sid in chap['scenes']:
                scene_path = os.path.join(project_dir, 'scenes', f'{sid}.md')
                _status = _gf(_scenes_csv, sid, 'status') or 'unknown'
                file_ok = 'OK' if os.path.isfile(scene_path) else 'MISSING'
                print(f'    - {sid} [{file_ok}] status={_status}')
        print('Output: manuscript/{script.md,visual-references.md,chapter-map.md,handoff-readme.md,style-guide.md}')
        print('===== END DRY RUN =====')
        return

    # Validate that every mapped scene has status=drafted
    from storyforge.csv_cli import get_field
    scenes_csv = os.path.join(project_dir, 'reference', 'scenes.csv')
    not_drafted = []
    for chap in chapters:
        for sid in chap['scenes']:
            status = get_field(scenes_csv, sid, 'status') or ''
            if status != 'drafted':
                not_drafted.append(f'{sid} (status={status or "unknown"})')
    if not_drafted and not args.force:
        log('WARNING: the following scenes are not drafted:')
        for item in not_drafted:
            log(f'  - {item}')
        log("Run 'storyforge write' to draft missing scenes, or use --force to bundle anyway.")
        sys.exit(1)

    bundle_dir = os.path.join(project_dir, 'manuscript')
    os.makedirs(bundle_dir, exist_ok=True)

    log(f'Assembling artist bundle for: {title}')
    log(f'Chapters: {len(chapters)}')

    # script.md
    script_md = _assemble_script(project_dir, chapters, title)
    script_path = os.path.join(bundle_dir, 'script.md')
    with open(script_path, 'w', encoding='utf-8') as f:
        f.write(script_md)
    log('  manuscript/script.md')

    # visual-references.md
    refs = _extract_visual_references(project_dir, title)
    refs_path = os.path.join(bundle_dir, 'visual-references.md')
    with open(refs_path, 'w', encoding='utf-8') as f:
        f.write(refs)
    log('  manuscript/visual-references.md')

    # chapter-map.md
    cm = _render_chapter_map(chapters, title)
    cm_path = os.path.join(bundle_dir, 'chapter-map.md')
    with open(cm_path, 'w', encoding='utf-8') as f:
        f.write(cm)
    log('  manuscript/chapter-map.md')

    # handoff-readme.md
    readme = HANDOFF_README.format(title=title)
    readme_path = os.path.join(bundle_dir, 'handoff-readme.md')
    with open(readme_path, 'w', encoding='utf-8') as f:
        f.write(readme)
    log('  manuscript/handoff-readme.md')

    # style-guide.md (coaching-aware)
    coaching = args.coaching or get_coaching_level(project_dir)
    style_guide = _assemble_style_guide(project_dir, title, coaching,
                                         dry_run=False)
    style_path = os.path.join(bundle_dir, 'style-guide.md')
    with open(style_path, 'w', encoding='utf-8') as f:
        f.write(style_guide)
    log(f'  manuscript/style-guide.md (coaching={coaching})')

    log('Script package complete.')


if __name__ == '__main__':
    main()
