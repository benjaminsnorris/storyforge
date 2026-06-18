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
from typing import NamedTuple

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

# Matches `## Page N —` at start of line. Group 2 is the number; groups
# 1 and 3 are the literal prefix/suffix preserved verbatim during renumber.
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

    For GN projects with per-page files (pages/<prefix>-pN.md), the panel
    script content is assembled from the page files' '## Panel script'
    sections, sorted by page_within_scene, and prepended with a synthetic
    `# Scene: {sid}` header so the bundle stays navigable (page files
    carry per-page headers, not scene-level ones). Scenes without page
    files fall back to the inline scene-file body — that path uses the
    file's existing header rather than synthesizing one. Returns the
    assembled markdown string.
    """
    from storyforge.script_format import count_panels
    from storyforge.pages import pages_for_scene, extract_panel_script

    global_page = 1
    total_panels = 0
    body_parts = []

    for chap in chapters:
        body_parts.append(f'\n# Chapter {chap["chapter"]} — {chap["title"]}\n')
        for sid in chap['scenes']:
            page_files = pages_for_scene(project_dir, sid)
            if page_files:
                # Synthetic `# Scene: {sid}` header — the inline-scene-file
                # path uses the file's existing header, but page files have
                # their own (per-page) headers and need a scene-level wrapper
                # so the artist bundle stays navigable.
                scene_text_parts = [f'\n# Scene: {sid}\n']
                pages_with_script = 0
                for page in page_files:
                    script_body = extract_panel_script(page['path'])
                    if script_body:
                        scene_text_parts.append('\n' + script_body + '\n')
                        pages_with_script += 1
                if pages_with_script == 0:
                    log(f'  WARNING: scene {sid}: {len(page_files)} page '
                        f'file(s) exist but none contain a `## Panel script` '
                        f'section; artist bundle will have an empty scene')
                elif pages_with_script < len(page_files):
                    log(f'  WARNING: scene {sid}: {pages_with_script}/'
                        f'{len(page_files)} page file(s) have a `## Panel '
                        f'script` section; remaining pages produce no output')
                text = ''.join(scene_text_parts)
            else:
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
# Blocking-prompt assembly
# ---------------------------------------------------------------------------

def _assemble_page_prompts(project_dir: str, chapters: list[dict]) -> str:
    """Concatenate per-page image-generation workflows in global page order.

    Iterates chapters → scenes → page files (sorted by page_within_scene),
    pulls the `## Image-generation workflow` section out of each (the
    whole-page GPT Image 2 prompt + reference list), and emits a per-page
    header carrying a global page number.

    Returns '' when no page in the bundle has a workflow section (so the
    caller can skip writing the file entirely).
    """
    from storyforge.pages import pages_for_scene, extract_image_workflow
    from storyforge.csv_cli import get_field

    scenes_csv = os.path.join(project_dir, 'reference', 'scenes.csv')
    sections: list[str] = []
    global_page = 0
    for chap in chapters:
        for sid in chap['scenes']:
            scene_title = get_field(scenes_csv, sid, 'title') or sid
            siblings = pages_for_scene(project_dir, sid)
            total = len(siblings)
            for i, page in enumerate(siblings, start=1):
                global_page += 1
                body = extract_image_workflow(page['path']).strip()
                if not body:
                    continue
                page_id = page.get('page_id', '?')
                sections.append(
                    f'# Global page {global_page} ({page_id}) — '
                    f'{scene_title}, page {i}/{total}\n\n{body}\n'
                )
    return '\n'.join(sections)


def _assemble_reference_manifest(project_dir: str, chapters: list[dict]) -> str:
    """Build the reference-image manifest for the artist bundle.

    Two parts: a deduped "gather these once" checklist of every distinct
    reference image across the book, then a per-page list of the
    `references_required` each page needs (in upload order). Returns ''
    when no page declares any references.
    """
    from storyforge.pages import pages_for_scene
    from storyforge.csv_cli import get_field

    scenes_csv = os.path.join(project_dir, 'reference', 'scenes.csv')
    per_page: list[str] = []
    all_refs: list[str] = []
    seen: set[str] = set()
    global_page = 0
    for chap in chapters:
        for sid in chap['scenes']:
            scene_title = get_field(scenes_csv, sid, 'title') or sid
            siblings = pages_for_scene(project_dir, sid)
            total = len(siblings)
            for i, page in enumerate(siblings, start=1):
                global_page += 1
                refs = page.get('references_required', []) or []
                if not refs:
                    continue
                page_id = page.get('page_id', '?')
                lines = [f'## Global page {global_page} ({page_id}) — '
                         f'{scene_title}, page {i}/{total}', '']
                for n, ref in enumerate(refs, start=1):
                    lines.append(f'- **Image {n}:** {ref}')
                    if ref not in seen:
                        seen.add(ref)
                        all_refs.append(ref)
                per_page.append('\n'.join(lines))
    if not per_page:
        return ''
    gather = ['## All reference images (gather these once)', '']
    gather += [f'- {r}' for r in all_refs]
    return '\n'.join(gather) + '\n\n' + '\n\n'.join(per_page) + '\n'


# Two separate inventory lines so the README documents only the files that
# were actually written (page-prompts.md and reference-images.md are emitted
# independently — see SF-1/CR-1 review findings).
_PAGE_PROMPTS_INVENTORY_LINE = (
    '\n- `page-prompts.md` — One whole-page image-generation prompt per '
    'book page, tuned for GPT Image 2 (ChatGPT Images 2.0). Each prompt '
    'follows OpenAI’s 5-section template (Scene / Subject / Important '
    'details / Use case / Constraints) with per-panel beats. Paste a page '
    'prompt into ChatGPT alongside that page’s reference images to render '
    'the whole page in one shot. Adjust the reference images, not the prose, '
    'to fix style/character drift.'
)

_REFERENCE_IMAGES_INVENTORY_LINE = (
    '\n- `reference-images.md` — The reference images each page needs, '
    'labeled by role (character / paper-tone / prior page), plus a deduped '
    'checklist to gather them once.'
)


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
# Canon bundling
# ---------------------------------------------------------------------------

def _copy_canon_into_bundle(project_dir: str, bundle_dir: str) -> int:
    """Mirror reference/canon/ into manuscript/canon/. Returns the number
    of canon .md files in the SOURCE tree (0 when canon/ is absent or
    contains no .md files).

    Uses `dirs_exist_ok=True` for idempotent merge-copy, then prunes any
    file or directory in the destination that no longer exists in the
    source. The two-step pattern beats rmtree+copytree because a partial
    failure during the copy phase leaves the bundle equal to or better
    than the prior state, not strictly worse. The return value comes from
    the source tree so the caller's readme decision is honest regardless
    of partial-copy outcomes.
    """
    import shutil

    src = os.path.join(project_dir, 'reference', 'canon')
    if not os.path.isdir(src):
        return 0
    source_count = 0
    for root, _dirs, files in os.walk(src):
        source_count += sum(1 for f in files if f.endswith('.md'))
    if source_count == 0:
        return 0
    dst = os.path.join(bundle_dir, 'canon')
    shutil.copytree(src, dst, dirs_exist_ok=True)
    _prune_orphans(src, dst)
    return source_count


def _prune_orphans(src: str, dst: str) -> None:
    """Delete files/dirs under dst that have no counterpart under src.

    Walks dst top-down. For each entry, computes the equivalent path in
    src; if the source path is missing, the entry is removed. Keeps the
    bundle as an exact mirror of the canon source even when authors
    rename or delete canon files between runs.
    """
    import shutil

    for root, dirs, files in os.walk(dst, topdown=False):
        rel = os.path.relpath(root, dst)
        src_root = src if rel == '.' else os.path.join(src, rel)
        for name in files:
            if not os.path.exists(os.path.join(src_root, name)):
                os.remove(os.path.join(root, name))
        for name in dirs:
            src_subdir = os.path.join(src_root, name)
            dst_subdir = os.path.join(root, name)
            if not os.path.isdir(src_subdir) and os.path.isdir(dst_subdir):
                shutil.rmtree(dst_subdir)


# ---------------------------------------------------------------------------
# Handoff README template
# ---------------------------------------------------------------------------

HANDOFF_README = """\
# Artist Handoff — {title}

This bundle contains everything you need to illustrate the graphic novel.

## Files

- `script.md` — The complete panel-by-panel script. Pages are globally numbered.
- `visual-references.md` — Character and location reference notes. Pin these up.
- `chapter-map.md` — How scenes group into chapters/issues.{canon_line}{prompts_line}

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

# Single source of truth for style-guide section names — every renderer
# (strict, coach, full-LLM-prompt) consumes this list so adding a section
# is one edit per render-mode, not five.
_STYLE_GUIDE_SECTIONS: tuple[str, ...] = (
    'Palette',
    'Line weight and inking',
    'Lettering and caption tone',
    'Panel-rhythm philosophy',
    'Reference-art inspirations',
)

# Per-section constraint text for the strict renderer.
_STRICT_GUIDANCE: dict[str, str] = {
    'Palette':
        'Cover: 4-8 hex codes for the primary palette; warm/cool/neutral '
        'balance; one or two callouts for accent colors used sparingly; '
        'palette shifts per act if intended.',
    'Line weight and inking':
        'Cover: line-weight intent (heavy / medium / variable); whether '
        'silhouettes lead; ink texture (clean digital / brush / scratchy); '
        'how line weight signals tone shifts.',
    'Lettering and caption tone':
        'Cover: caption voice (none / minimal / journal-voiceover / '
        'omniscient); font-family intent; whisper / thought / SFX '
        'treatments; balloon shape grammar.',
    'Panel-rhythm philosophy':
        'Cover: when to splash vs grid; preferred transitions '
        '(moment / action / subject / scene / aspect / non-sequitur); '
        'how page turns are reserved; tier or irregular usage guidance.',
    'Reference-art inspirations':
        'Cover: 3-6 specific reference artists or works; what to pull '
        'from each (composition? palette? line work?); deliberate '
        'distinctions from those references.',
}


class StyleGuideCues(NamedTuple):
    """Snapshot of project state used to generate the artist style guide.

    Always-`str` invariant: every field is a (possibly empty) string,
    never None, so callers can use `or 'unset'` / `.strip()` without
    None-guards.
    """
    genre: str
    subgenre: str
    world_bible: str
    character_bible: str
    voice_guide: str
    scene_intent_excerpt: str


def _gather_style_cues(project_dir: str) -> StyleGuideCues:
    """Pull style cues from project state for the style-guide generator."""
    return StyleGuideCues(
        genre=read_yaml_field('project.genre', project_dir) or '',
        subgenre=read_yaml_field('project.subgenre', project_dir) or '',
        world_bible=_read_optional(
            os.path.join(project_dir, 'reference', 'world-bible.md'),
        ),
        character_bible=_read_optional(
            os.path.join(project_dir, 'reference', 'character-bible.md'),
        ),
        voice_guide=_read_optional(
            os.path.join(project_dir, 'reference', 'voice-guide.md'),
        ),
        scene_intent_excerpt=_read_optional(
            os.path.join(project_dir, 'reference', 'scene-intent.csv'),
            head_lines=8,
        ),
    )


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


def _render_strict_style_guide(title: str, cues: StyleGuideCues) -> str:
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
    for section in _STYLE_GUIDE_SECTIONS:
        out.append(f'## {section}')
        out.append('')
        out.append(_STRICT_GUIDANCE[section])
        out.append('')
    # Append a compact source-map so the author can grep cues from project state.
    out.append('## Source pointers')
    out.append('')
    if cues.genre or cues.subgenre:
        out.append(f'- Genre / subgenre: {cues.genre} / {cues.subgenre}')
    for value, path in (
        (cues.world_bible, 'reference/world-bible.md'),
        (cues.character_bible, 'reference/character-bible.md'),
        (cues.voice_guide, 'reference/voice-guide.md'),
    ):
        if value:
            out.append(f'- See: {path}')
    out.append('')
    return '\n'.join(out)


def _render_coach_style_guide(title: str, cues: StyleGuideCues) -> str:
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
    genre = cues.genre.strip()
    subgenre = cues.subgenre.strip()
    genre_line = (f'{genre}' + (f' / {subgenre}' if subgenre else '')) or 'unset'

    coach_content: dict[str, list[str]] = {
        'Palette': [
            f'- Genre cue: {genre_line} — what palette signals this register?',
            '- Question: do you want a single palette across acts, or shifts?',
            '- Question: which color is reserved for the protagonist? for '
            'the antagonist? for emotional climaxes?',
        ],
        'Line weight and inking': [
            "- Cue: voice-guide.md (see file) for the project's tonal "
            'register.',
            '- Question: heavy / medium / variable — and where do you '
            'break the pattern intentionally?',
            '- Question: does line weight track POV or stakes?',
        ],
        'Lettering and caption tone': [
            '- Cue: scene-briefs.csv `caption_strategy` field (none / '
            'minimal / journal-voiceover / omniscient) — what mix appears '
            'across scenes?',
            '- Question: is caption font a primary character beat or '
            'background voice?',
            '- Question: how do you treat off-panel and thought balloons?',
        ],
        'Panel-rhythm philosophy': [
            '- Cue: scene-intent.csv `emotional_arc` patterns — what arc '
            'shapes recur, and what page rhythm matches them?',
            '- Question: when do you splash? when do you grid? when do '
            'you allow tier or irregular?',
            '- Question: are page turns reserved, and what beat earns them?',
        ],
        'Reference-art inspirations': [
            '- Cue: world-bible.md and character-bible.md for visual '
            'reference sections (if any).',
            '- Question: 3-6 specific artists or works — what does each '
            'one contribute to YOUR style, not theirs?',
            '- Question: where do you DELIBERATELY diverge from each '
            'reference?',
        ],
    }
    for section in _STYLE_GUIDE_SECTIONS:
        out.append(f'## {section}')
        out.append('')
        out.extend(coach_content[section])
        out.append('')
    return '\n'.join(out)


def _trim_for_prompt(text: str, lines: int) -> str:
    """Truncate `text` to the first N lines so the LLM prompt stays bounded."""
    if not text:
        return ''
    parts = text.splitlines()
    if len(parts) > lines:
        return '\n'.join(parts[:lines]) + '\n…'
    return text


def _build_full_style_guide_prompt(title: str, cues: StyleGuideCues) -> str:
    """Build the LLM prompt for full-mode style-guide synthesis.

    Section list is derived from _STYLE_GUIDE_SECTIONS so a change to
    that tuple propagates here automatically — no drift between the
    deterministic renderers and the LLM prompt.
    """
    section_block = '\n'.join(f'## {s}' for s in _STYLE_GUIDE_SECTIONS)
    return f"""You are drafting a style guide for the artist handing off a graphic
novel. The author has provided the following project context. Produce
a single markdown document with the standard sections.

# Project metadata

Title: {title}
Genre: {cues.genre or 'unset'}
Subgenre: {cues.subgenre or 'unset'}

# Voice guide (excerpt)

{_trim_for_prompt(cues.voice_guide, 80) or '(not present)'}

# World bible (excerpt)

{_trim_for_prompt(cues.world_bible, 100) or '(not present)'}

# Character bible (excerpt)

{_trim_for_prompt(cues.character_bible, 100) or '(not present)'}

# Scene-intent excerpt (CSV)

{cues.scene_intent_excerpt or '(empty)'}

# Task

Produce a markdown document with EXACTLY these top-level sections in
this order:

# {title} — Style guide

{section_block}

Each section: 3-6 sentences of specific, opinionated guidance grounded
in the project metadata above. Be concrete (hex codes if you can,
specific artist references, named transition types). Do NOT invent
content that contradicts the source material; when in doubt, surface
the choice rather than guess.

Return only the markdown document — no JSON, no preamble.
"""


def _render_full_style_guide(project_dir: str, title: str, cues: StyleGuideCues,
                              dry_run: bool) -> tuple[str, str]:
    """full coaching: LLM-generated style guide. Returns (text, actual_mode)
    so callers can log truthfully when the LLM path falls back."""
    if dry_run:
        return _render_coach_style_guide(title, cues), 'full→coach (dry-run)'
    prompt = _build_full_style_guide_prompt(title, cues)
    model = select_model('creative')
    log_dir = os.path.join(project_dir, 'working', 'logs', 'script-package')
    os.makedirs(log_dir, exist_ok=True)
    log_file = os.path.join(log_dir, 'style-guide.json')
    try:
        invoke_to_file(prompt, model, log_file, max_tokens=4096)
    except Exception as e:
        log(f'WARNING: style-guide LLM call failed ({e}); falling back to '
            f'coach-mode template. No tokens were billed.')
        return _render_coach_style_guide(title, cues), 'full→coach (LLM error)'
    text = _extract_response_text(log_file)
    if not text or not text.strip().startswith('#'):
        log(f'WARNING: style-guide LLM response unparseable; falling back '
            f'to coach-mode template. (API call was billed; raw response '
            f'saved at {log_file}.)')
        _record_style_guide_cost(project_dir, log_file, model,
                                  target='style-guide:unparseable')
        return (_render_coach_style_guide(title, cues),
                'full→coach (LLM unparseable)')
    _record_style_guide_cost(project_dir, log_file, model)
    return text, 'full'


def _extract_response_text(log_file: str) -> str:
    """Read the text content from an api log file. Differentiates the
    distinct silent-failure modes so callers can act on them:
    - File missing / unreadable → WARNING, return ''
    - JSON decode failure → WARNING, return ''
    - Response has no content blocks → WARNING with stop_reason
    - No text block in content → WARNING with block types
    - Text block is empty / whitespace → WARNING
    """
    try:
        with open(log_file, encoding='utf-8') as f:
            resp = json.load(f)
    except (OSError, json.JSONDecodeError) as e:
        log(f'WARNING: could not read style-guide response file: {e}')
        return ''
    content = resp.get('content', [])
    if not content:
        stop = resp.get('stop_reason', '?')
        log(f'WARNING: response has no content blocks '
            f'(stop_reason={stop}, file={log_file})')
        return ''
    for block in content:
        if block.get('type') == 'text':
            text = block.get('text', '')
            if not text.strip():
                log(f'WARNING: response text block is empty '
                    f'(file={log_file})')
            return text
    log(f'WARNING: no text block in response '
        f'(types={[b.get("type") for b in content]}, file={log_file})')
    return ''


def _record_style_guide_cost(project_dir: str, log_file: str,
                              model: str, *,
                              target: str = 'style-guide') -> None:
    try:
        with open(log_file, encoding='utf-8') as f:
            resp = json.load(f)
    except (OSError, json.JSONDecodeError) as e:
        log(f'WARNING: cost ledger update failed reading {log_file}: {e}')
        return
    usage = extract_usage(resp)
    cost = calculate_cost_from_usage(usage, model)
    log_operation(
        project_dir, 'assemble-gn-style-guide', model,
        usage['input_tokens'], usage['output_tokens'], cost,
        target=target,
        cache_read=usage.get('cache_read', 0),
        cache_create=usage.get('cache_create', 0),
    )


def _assemble_style_guide(project_dir: str, title: str,
                           coaching: CoachingLevel,
                           dry_run: bool) -> tuple[str, str]:
    """Generate the style-guide markdown for the artist handoff bundle.

    Returns (text, actual_mode) where actual_mode is the rendering path
    that was used — so the caller can log truthfully even when the
    requested coaching level was full but fell back to coach.

    Coaching levels:
      - strict: blank template + constraint list (no LLM).
      - coach:  template + cues pulled from project state + author
                questions per section (no LLM creative content).
      - full:   LLM-synthesized guide from project context. Falls back
                to the coach template on LLM failure / API-key missing.
    """
    cues = _gather_style_cues(project_dir)
    if coaching == 'strict':
        return _render_strict_style_guide(title, cues), 'strict'
    if coaching == 'coach':
        return _render_coach_style_guide(title, cues), 'coach'
    if dry_run:
        return _render_coach_style_guide(title, cues), 'full→coach (dry-run)'
    if not os.environ.get('ANTHROPIC_API_KEY'):
        log('NOTE: ANTHROPIC_API_KEY not set; style-guide will fall back '
            'to the coach-mode template (deterministic). Set the key for '
            'an LLM-synthesized guide.')
        return _render_coach_style_guide(title, cues), 'full→coach (no API key)'
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

    # Validate that every mapped scene has status=drafted (or has page files —
    # a scene with at least one pages/<prefix>-pN.md is treated as drafted
    # even when scenes.csv still shows briefed, since per-page work is the
    # source of truth for those scenes).
    from storyforge.csv_cli import get_field
    from storyforge.pages import pages_for_scene
    scenes_csv = os.path.join(project_dir, 'reference', 'scenes.csv')
    not_drafted = []
    for chap in chapters:
        for sid in chap['scenes']:
            if pages_for_scene(project_dir, sid):
                continue
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

    # canon/ — copy reference/canon/ alongside the script so artists have
    # the source-of-truth visual blocks in one place. Canon informs the page
    # prompts and the reference images but is no longer embedded inline
    # (issue #260); this directory is the editable source artists work from.
    canon_copied = _copy_canon_into_bundle(project_dir, bundle_dir)
    canon_line = (
        '\n- `canon/` — Source-of-truth visual canon (style foundation, '
        'lighting laws, panel registers, page rhythm, plus per-character/'
        'per-location/per-motif blocks). Canon *informs* the page prompts and '
        'reference images; it is no longer pasted inline. This directory is '
        'the editable source.'
    ) if canon_copied else ''
    if canon_copied:
        log(f'  manuscript/canon/ ({canon_copied} files)')

    # page-prompts.md and reference-images.md (issue #260) are emitted
    # INDEPENDENTLY: a page may declare references_required before the
    # prompts stage authors its workflow section, so the manifest must not
    # be gated on the page prompts existing (SF-1). Each file's README
    # inventory line is added only when that file is actually written (CR-1).
    # Skip-NOTEs fire only when per-page work is underway (pages/ populated)
    # so prose-only GN bundles stay quiet (SF-2).
    from storyforge.pages import list_page_files
    has_page_files = bool(list_page_files(project_dir))
    prompts_line = ''

    page_prompts_md = _assemble_page_prompts(project_dir, chapters)
    if page_prompts_md:
        header = (
            f'# {title} — Page Prompts (GPT Image 2)\n\n'
            '_One whole-page prompt per book page. Paste each into ChatGPT '
            'alongside that page’s reference images (see reference-images.md)._\n\n'
        )
        with open(os.path.join(bundle_dir, 'page-prompts.md'), 'w',
                  encoding='utf-8') as f:
            f.write(header + page_prompts_md)
        log('  manuscript/page-prompts.md')
        prompts_line += _PAGE_PROMPTS_INVENTORY_LINE
    elif has_page_files:
        log('  NOTE: no page has an "## Image-generation workflow" section '
            'yet — skipping page-prompts.md (run `storyforge elaborate '
            '--stage prompts`)')

    manifest_md = _assemble_reference_manifest(project_dir, chapters)
    if manifest_md:
        m_header = (
            f'# {title} — Reference Images\n\n'
            '_Upload the listed images alongside each page prompt, labeled '
            'by role. Reference images carry style + character likeness in '
            'GPT Image 2 — keep the prompt prose short and iterate on these '
            'instead._\n\n'
        )
        with open(os.path.join(bundle_dir, 'reference-images.md'), 'w',
                  encoding='utf-8') as f:
            f.write(m_header + manifest_md)
        log('  manuscript/reference-images.md')
        prompts_line += _REFERENCE_IMAGES_INVENTORY_LINE
    elif has_page_files:
        log('  NOTE: no page declares `references_required` in its '
            'frontmatter — skipping reference-images.md')

    # handoff-readme.md
    readme = HANDOFF_README.format(
        title=title, canon_line=canon_line, prompts_line=prompts_line,
    )
    readme_path = os.path.join(bundle_dir, 'handoff-readme.md')
    with open(readme_path, 'w', encoding='utf-8') as f:
        f.write(readme)
    log('  manuscript/handoff-readme.md')

    # style-guide.md (coaching-aware)
    coaching = args.coaching or get_coaching_level(project_dir)
    style_guide, actual_mode = _assemble_style_guide(
        project_dir, title, coaching, dry_run=False,
    )
    style_path = os.path.join(bundle_dir, 'style-guide.md')
    with open(style_path, 'w', encoding='utf-8') as f:
        f.write(style_guide)
    log(f'  manuscript/style-guide.md ({actual_mode})')

    log('Script package complete.')


if __name__ == '__main__':
    main()
