"""storyforge assemble (graphic-novel mode) — Artist handoff bundle.

Produces manuscript/{script.md,visual-references.md,chapter-map.md,handoff-readme.md}.

Usage:
    storyforge assemble               # Default: markdown bundle
    storyforge assemble --dry-run     # Show what would be done
"""

import argparse
import os
import re
import sys

from storyforge.common import (
    detect_project_root, log, install_signal_handlers, get_medium,
    read_yaml_field,
)


# ---------------------------------------------------------------------------
# Argument parsing
# ---------------------------------------------------------------------------

def parse_args(argv):
    p = argparse.ArgumentParser(prog='storyforge assemble (gn)')
    p.add_argument('--dry-run', action='store_true',
                   help='Show what would be done without writing files')
    p.add_argument('--force', action='store_true',
                   help='Bundle even if some scenes are not yet drafted.')
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
        print('Output: manuscript/{script.md,visual-references.md,chapter-map.md,handoff-readme.md}')
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
        log("Run 'storyforge write-gn' to draft missing scenes, or use --force to bundle anyway.")
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

    log('Script package complete.')


if __name__ == '__main__':
    main()
