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
    p.add_argument('--format', default='markdown',
                   help='Output format: markdown (default)')
    p.add_argument('--dry-run', action='store_true',
                   help='Show what would be done without writing files')
    return p.parse_args(argv)


# ---------------------------------------------------------------------------
# Chapter-map reading
# ---------------------------------------------------------------------------

def _read_chapter_map(path):
    """Return list of {chapter, title, heading, scenes:[id,...]} or None if missing."""
    if not os.path.isfile(path):
        return None
    chapters = []
    with open(path) as f:
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
            text = open(scene_path).read()
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
    return header + '\n'.join(body_parts)


# ---------------------------------------------------------------------------
# Visual reference extraction
# ---------------------------------------------------------------------------

def _extract_visual_references(project_dir, title):
    """Pull character Visual sections + world-bible visual notes.

    Extracts `## CharacterName` sections that contain a `### Visual` subsection
    from character-bible.md, and similarly from world-bible.md.
    """
    parts = [
        f'# {title} — Visual References\n',
        '_For the artist. Pin to your drawing table._\n',
    ]

    ref_dir = os.path.join(project_dir, 'reference')

    char_path = os.path.join(ref_dir, 'character-bible.md')
    if os.path.isfile(char_path):
        content = open(char_path).read()
        # Split on level-2 headers (## ...).  sections[0] is pre-first-header preamble.
        sections = re.split(r'^## ', content, flags=re.MULTILINE)
        char_sections = []
        for sec in sections[1:]:
            if re.search(r'^### [Vv]isual', sec, re.MULTILINE):
                char_sections.append('## ' + sec.rstrip())
        if char_sections:
            parts.append('\n## Characters\n')
            parts.extend(s + '\n' for s in char_sections)

    world_path = os.path.join(ref_dir, 'world-bible.md')
    if os.path.isfile(world_path):
        content = open(world_path).read()
        sections = re.split(r'^## ', content, flags=re.MULTILINE)
        world_sections = []
        for sec in sections[1:]:
            if re.search(r'^### [Vv]isual', sec, re.MULTILINE):
                world_sections.append('## ' + sec.rstrip())
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

    # Dry-run: report what would be done
    if args.dry_run:
        print('===== DRY RUN: script-package =====')
        print(f'Project: {title}')
        print(f'Chapters: {len(chapters)}')
        total_scenes = sum(len(c['scenes']) for c in chapters)
        print(f'Scenes: {total_scenes}')
        for chap in chapters:
            print(f'  Chapter {chap["chapter"]}: {chap["title"]}')
            for sid in chap['scenes']:
                scene_path = os.path.join(project_dir, 'scenes', f'{sid}.md')
                status = 'OK' if os.path.isfile(scene_path) else 'MISSING'
                print(f'    - {sid} [{status}]')
        print('Output: manuscript/{script.md,visual-references.md,chapter-map.md,handoff-readme.md}')
        print('===== END DRY RUN =====')
        return

    bundle_dir = os.path.join(project_dir, 'manuscript')
    os.makedirs(bundle_dir, exist_ok=True)

    log(f'Assembling artist bundle for: {title}')
    log(f'Chapters: {len(chapters)}')

    # script.md
    script_md = _assemble_script(project_dir, chapters, title)
    script_path = os.path.join(bundle_dir, 'script.md')
    with open(script_path, 'w') as f:
        f.write(script_md)
    log('  manuscript/script.md')

    # visual-references.md
    refs = _extract_visual_references(project_dir, title)
    refs_path = os.path.join(bundle_dir, 'visual-references.md')
    with open(refs_path, 'w') as f:
        f.write(refs)
    log('  manuscript/visual-references.md')

    # chapter-map.md
    cm = _render_chapter_map(chapters, title)
    cm_path = os.path.join(bundle_dir, 'chapter-map.md')
    with open(cm_path, 'w') as f:
        f.write(cm)
    log('  manuscript/chapter-map.md')

    # handoff-readme.md
    readme = HANDOFF_README.format(title=title)
    readme_path = os.path.join(bundle_dir, 'handoff-readme.md')
    with open(readme_path, 'w') as f:
        f.write(readme)
    log('  manuscript/handoff-readme.md')

    log('Script package complete.')


if __name__ == '__main__':
    main()
