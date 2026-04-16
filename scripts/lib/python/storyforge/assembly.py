"""Chapter assembly and manuscript production.

Replaces the data-heavy functions from scripts/lib/assembly.sh — chapter map
parsing, scene extraction, front/back matter generation, epub metadata, and
full manuscript assembly.  Tool-detection and pandoc/weasyprint wrappers stay
in bash.
"""

import os
import re
import sys
from datetime import datetime

from .prompts import read_yaml_field, _read_csv_header_and_rows, read_csv_field


# ============================================================================
# YAML helpers (supplement read_yaml_field for nested / list structures)
# ============================================================================

def _read_yaml_lines(yaml_file: str) -> list[str]:
    """Read all lines from a YAML file, or return empty list."""
    if not os.path.isfile(yaml_file):
        return []
    with open(yaml_file) as f:
        return f.readlines()


def _read_production_field_from_lines(lines: list[str], field: str) -> str:
    """Read a direct child of the ``production:`` block."""
    in_prod = False
    for line in lines:
        if re.match(r'^production:', line):
            in_prod = True
            continue
        if in_prod:
            if line and not line[0].isspace() and line[0] != '#':
                break
            m = re.match(rf'^\s+{re.escape(field)}:\s*(.*)', line)
            if m:
                return _strip_yaml_quotes(m.group(1))
    return ''


def _read_production_nested_from_lines(lines: list[str],
                                       parent: str, child: str) -> str:
    """Read a grandchild of ``production:`` (e.g. ``copyright > year``)."""
    in_prod = False
    in_parent = False
    for line in lines:
        if re.match(r'^production:', line):
            in_prod = True
            continue
        if in_prod:
            if line and not line[0].isspace() and line[0] != '#':
                break
            # Detect the parent key (one indent level under production)
            if re.match(rf'^\s+{re.escape(parent)}:', line):
                in_parent = True
                continue
            if in_parent:
                # End of parent block: next sibling at same indent
                if re.match(r'^\s+\S', line) and not re.match(r'^\s+\s+\S', line):
                    in_parent = False
                    continue
                m = re.match(rf'^\s+{re.escape(child)}:\s*(.*)', line)
                if m:
                    return _strip_yaml_quotes(m.group(1))
    return ''


def _strip_yaml_quotes(raw: str) -> str:
    val = raw.strip()
    if len(val) >= 2 and val[0] in ('"', "'") and val[-1] == val[0]:
        val = val[1:-1]
    return val


def _count_yaml_list_items(lines: list[str], list_key: str,
                           item_marker: str) -> int:
    """Count items in a YAML list block identified by ``list_key:``."""
    in_block = False
    count = 0
    for line in lines:
        if re.match(rf'^{re.escape(list_key)}:', line):
            in_block = True
            continue
        if in_block:
            if line and not line[0].isspace() and line[0] != '#':
                break
            if re.match(rf'^\s+-\s+{re.escape(item_marker)}:', line):
                count += 1
    return count


def _read_yaml_list_item_field(lines: list[str], list_key: str,
                               item_marker: str, item_num: int,
                               field: str) -> str:
    """Read a field from the Nth item in a YAML list block.

    Items are counted by occurrences of ``- item_marker:`` lines.
    """
    in_block = False
    count = 0
    in_target = False
    for line in lines:
        if re.match(rf'^{re.escape(list_key)}:', line):
            in_block = True
            continue
        if in_block:
            if line and not line[0].isspace() and line[0] != '#':
                break
            if re.match(rf'^\s+-\s+{re.escape(item_marker)}:', line):
                count += 1
                in_target = (count == item_num)
                # The marker line might itself be the field we want
                if in_target and field == item_marker:
                    m = re.match(rf'^\s+-\s+{re.escape(field)}:\s*(.*)', line)
                    if m:
                        return _strip_yaml_quotes(m.group(1))
                continue
            if in_target:
                # Next list item or end of block
                if re.match(r'^\s+-\s+\S', line):
                    break
                m = re.match(rf'^\s+{re.escape(field)}:\s*(.*)', line)
                if m:
                    return _strip_yaml_quotes(m.group(1))
    return ''


# ============================================================================
# Chapter map parsing (reads reference/chapter-map.csv)
# ============================================================================

def _chapter_map_path(project_dir: str) -> str:
    return os.path.join(project_dir, 'reference', 'chapter-map.csv')


def _detect_key_column(header: list[str]) -> str:
    """Return 'seq' if the first column is 'seq', otherwise 'chapter'."""
    if header and header[0] == 'seq':
        return 'seq'
    return 'chapter'


def count_chapters(project_dir: str) -> int:
    """Return the total number of chapters in the chapter map."""
    csv_file = _chapter_map_path(project_dir)
    if not os.path.isfile(csv_file):
        return 0

    header, rows = _read_csv_header_and_rows(csv_file)
    if not header:
        return 0

    key_col = _detect_key_column(header)
    try:
        key_idx = header.index(key_col)
    except ValueError:
        return 0

    return sum(1 for row in rows if len(row) > key_idx and row[key_idx])


def read_chapter_field(chapter_num: int, project_dir: str,
                       field: str) -> str:
    """Read a field from a chapter row.

    Args:
        chapter_num: 1-indexed chapter number.
        project_dir: Root directory of the project.
        field: Column name to return.

    Returns:
        The cell value, or empty string if not found.
    """
    csv_file = _chapter_map_path(project_dir)
    if not os.path.isfile(csv_file):
        return ''

    header, rows = _read_csv_header_and_rows(csv_file)
    key_col = _detect_key_column(header)
    return read_csv_field(csv_file, str(chapter_num), field, key_col)


def get_chapter_scenes(chapter_num: int, project_dir: str) -> list[str]:
    """Return the list of scene IDs for a chapter, in reading order."""
    scenes_str = read_chapter_field(chapter_num, project_dir, 'scenes')
    if not scenes_str:
        return []

    return [s.strip() for s in scenes_str.split(';') if s.strip()]


def count_parts(project_dir: str) -> int:
    """Count the number of parts defined in storyforge.yaml."""
    yaml_file = os.path.join(project_dir, 'storyforge.yaml')
    lines = _read_yaml_lines(yaml_file)
    return _count_yaml_list_items(lines, 'parts', 'number')


def read_part_field(part_num: int, project_dir: str, field: str) -> str:
    """Read a field from a part entry in storyforge.yaml.

    Args:
        part_num: 1-indexed part number.
        project_dir: Root directory of the project.
        field: Field name (e.g. ``title``).

    Returns:
        The field value, or empty string.
    """
    yaml_file = os.path.join(project_dir, 'storyforge.yaml')
    lines = _read_yaml_lines(yaml_file)
    return _read_yaml_list_item_field(lines, 'parts', 'number',
                                      part_num, field)


def get_chapter_part_title(chapter_num: int, project_dir: str) -> str:
    """Return the part title for a given chapter, or empty string."""
    part_str = read_chapter_field(chapter_num, project_dir, 'part')
    if not part_str:
        return ''

    try:
        part_num = int(part_str)
    except ValueError:
        return ''

    return read_part_field(part_num, project_dir, 'title')


# ============================================================================
# Scene extraction
# ============================================================================

def extract_scene_prose(scene_file: str) -> str:
    """Strip YAML frontmatter from a scene file, returning only prose.

    If the file does not start with ``---``, the entire content is returned.
    Leading blank lines after frontmatter are stripped.
    """
    if not os.path.isfile(scene_file):
        return ''

    with open(scene_file) as f:
        content = f.read()

    if not content.startswith('---\n') and not content.startswith('---\r'):
        return content.lstrip('\n')

    # Strip frontmatter (between first and second --- lines)
    lines = content.split('\n')
    in_frontmatter = True
    result_lines = []
    for i, line in enumerate(lines):
        if i == 0:
            continue  # skip opening ---
        if in_frontmatter:
            if line.rstrip() == '---':
                in_frontmatter = False
                continue
        else:
            result_lines.append(line)

    # Strip leading blank lines
    text = '\n'.join(result_lines)
    return text.lstrip('\n')


# ============================================================================
# Chapter assembly
# ============================================================================

_BREAK_MARKERS = {
    'space': '---',
    'blank': '---',
    'ornamental': '***',
    'line': '---',
}


def assemble_chapter(chapter_num: int, project_dir: str,
                     break_style: str = 'space') -> str:
    """Assemble a single chapter from its scenes.

    Args:
        chapter_num: 1-indexed chapter number.
        project_dir: Root directory of the project.
        break_style: One of ``space``, ``blank``, ``ornamental``, ``line``,
            or ``custom:SYMBOL``.

    Returns:
        Assembled chapter markdown.
    """
    title = read_chapter_field(chapter_num, project_dir, 'title')
    heading_format = read_chapter_field(chapter_num, project_dir, 'heading')

    # Build heading
    heading = ''
    if heading_format == 'numbered':
        heading = f'# Chapter {chapter_num}'
    elif heading_format == 'titled':
        heading = f'# {title}'
    elif heading_format == 'none':
        heading = ''
    else:
        # Default: numbered-titled (also covers empty heading_format)
        heading = f'# Chapter {chapter_num}: {title}'

    # Build break marker
    if break_style.startswith('custom:'):
        break_marker = break_style[7:]
    else:
        break_marker = _BREAK_MARKERS.get(break_style, '---')

    scene_ids = get_chapter_scenes(chapter_num, project_dir)
    parts = []

    if heading:
        parts.append(heading)
        parts.append('')

    first = True
    for scene_id in scene_ids:
        scene_file = os.path.join(project_dir, 'scenes', f'{scene_id}.md')
        if not os.path.isfile(scene_file):
            continue

        if first:
            first = False
        else:
            parts.append('')
            parts.append(break_marker)
            parts.append('')

        # Scene boundary marker
        parts.append(f'<!-- scene:{scene_id} -->')
        parts.append('')
        parts.append(extract_scene_prose(scene_file))

    return '\n'.join(parts)


# ============================================================================
# Production config
# ============================================================================

def read_production_field(project_dir: str, field: str) -> str:
    """Read a field from the ``production:`` section of storyforge.yaml."""
    yaml_file = os.path.join(project_dir, 'storyforge.yaml')
    lines = _read_yaml_lines(yaml_file)
    return _read_production_field_from_lines(lines, field)


def read_production_nested(project_dir: str, parent: str,
                           child: str) -> str:
    """Read a nested field under ``production:`` (e.g. ``copyright > year``)."""
    yaml_file = os.path.join(project_dir, 'storyforge.yaml')
    lines = _read_yaml_lines(yaml_file)
    return _read_production_nested_from_lines(lines, parent, child)


# ============================================================================
# Front / back matter
# ============================================================================

def _yaml_field(project_dir: str, *dotted_keys: str) -> str:
    """Try multiple dotted YAML keys, return the first non-empty value."""
    yaml_file = os.path.join(project_dir, 'storyforge.yaml')
    for key in dotted_keys:
        val = read_yaml_field(yaml_file, key)
        if val:
            return val
    return ''


def generate_title_page(project_dir: str) -> str:
    """Generate a title page in markdown."""
    title = _yaml_field(project_dir, 'project.title', 'title') or 'Untitled'
    author = read_production_field(project_dir, 'author')

    lines = ['---', f'title: "{title}"']
    if author:
        lines.append(f'author: "{author}"')
    lines.extend(['---', '', f'# {title}', ''])
    if author:
        lines.extend([f'### {author}', ''])

    return '\n'.join(lines)


def generate_copyright_page(project_dir: str) -> str:
    """Generate a copyright page in markdown."""
    title = _yaml_field(project_dir, 'project.title', 'title') or 'Untitled'
    author = read_production_field(project_dir, 'author')
    copyright_year = (read_production_nested(project_dir, 'copyright', 'year')
                      or str(datetime.now().year))
    isbn = read_production_nested(project_dir, 'copyright', 'isbn')
    license_text = (read_production_nested(project_dir, 'copyright', 'license')
                    or 'All rights reserved.')

    lines = ['# Copyright', '', f'*{title}*', '']
    if author:
        lines.append(f'Copyright \u00a9 {copyright_year} {author}')
    else:
        lines.append(f'Copyright \u00a9 {copyright_year}')
    lines.extend(['', license_text, ''])
    if isbn:
        lines.extend([f'ISBN: {isbn}', ''])

    return '\n'.join(lines)


def generate_toc(project_dir: str) -> str:
    """Generate a table of contents in markdown."""
    total = count_chapters(project_dir)
    if total == 0:
        return ''

    lines = ['# Contents', '']
    for i in range(1, total + 1):
        title = read_chapter_field(i, project_dir, 'title')
        heading_format = read_chapter_field(i, project_dir, 'heading')

        if heading_format == 'numbered':
            lines.append(f'- Chapter {i}')
        elif heading_format == 'titled':
            lines.append(f'- {title}')
        elif heading_format == 'none':
            lines.append(f'- Chapter {i}')
        else:
            lines.append(f'- Chapter {i}: {title}')

    lines.append('')
    return '\n'.join(lines)


def read_matter_file(project_dir: str, section: str, name: str) -> str:
    """Read front-matter or back-matter content.

    Checks the production config for a custom path first, then falls back
    to the default location (``manuscript/front-matter/`` or
    ``manuscript/back-matter/``).

    Args:
        project_dir: Root directory of the project.
        section: ``front_matter`` or ``back_matter``.
        name: Item name (e.g. ``dedication``, ``acknowledgments``).

    Returns:
        File content, or empty string if not found.
    """
    filepath = read_production_nested(project_dir, section, name)
    if filepath:
        full = os.path.join(project_dir, filepath)
        if os.path.isfile(full):
            with open(full) as f:
                return f.read()

    # Default locations
    if section == 'front_matter':
        default = os.path.join(project_dir, 'manuscript', 'front-matter',
                               f'{name}.md')
    elif section == 'back_matter':
        default = os.path.join(project_dir, 'manuscript', 'back-matter',
                               f'{name}.md')
    else:
        return ''

    if os.path.isfile(default):
        with open(default) as f:
            return f.read()

    return ''


# ============================================================================
# Epub metadata
# ============================================================================

def _unquote(s: str) -> str:
    """Strip surrounding quotes from a string."""
    if s and len(s) >= 2 and s[0] == s[-1] and s[0] in ('"', "'"):
        return s[1:-1]
    return s


def generate_epub_metadata(project_dir: str) -> str:
    """Generate pandoc metadata YAML for epub production."""
    title = _yaml_field(project_dir, 'project.title', 'title') or 'Untitled'
    author = read_production_field(project_dir, 'author') or 'Anonymous'
    language = read_production_field(project_dir, 'language') or 'en'
    genre = _yaml_field(project_dir, 'project.genre', 'genre')
    isbn = read_production_nested(project_dir, 'copyright', 'isbn')
    copyright_year = (read_production_nested(project_dir, 'copyright', 'year')
                      or str(datetime.now().year))
    cover_image = read_production_field(project_dir, 'cover_image')

    lines = [
        '---',
        f"title: '{_unquote(title)}'",
        f"author: '{_unquote(author)}'",
        f'lang: {language}',
        f'date: {copyright_year}',
    ]

    if genre:
        lines.append(f"subject: '{_unquote(genre)}'")
    if isbn:
        lines.append(f"identifier: '{_unquote(isbn)}'")
    if cover_image:
        full_path = os.path.join(project_dir, cover_image)
        if os.path.isfile(full_path):
            lines.append(f"cover-image: '{full_path}'")

    # Series metadata
    series_name = _yaml_field(project_dir, 'project.series_name')
    series_position = _yaml_field(project_dir, 'project.series_position')
    if series_name:
        lines.append(f"belongs-to-collection: '{_unquote(series_name)}'")
        if series_position:
            lines.append(f"group-position: '{_unquote(series_position)}'")

    lines.append(f"rights: 'Copyright \u00a9 {copyright_year} {_unquote(author)}'")
    lines.append('---')

    return '\n'.join(lines)


# ============================================================================
# Full manuscript assembly
# ============================================================================

def assemble_manuscript(project_dir: str, output_file: str) -> int:
    """Assemble the complete manuscript markdown file.

    Generates front matter, all chapters, and back matter.

    Args:
        project_dir: Root directory of the project.
        output_file: Path to write the assembled manuscript.

    Returns:
        Total word count of the assembled manuscript.
    """
    break_style = read_production_field(project_dir, 'scene_break') or 'blank'
    total = count_chapters(project_dir)

    if total == 0:
        print('ERROR: No chapters found in chapter-map.csv', file=sys.stderr)
        return 0

    parts = []

    # Front matter
    parts.append(generate_title_page(project_dir))
    parts.append(generate_copyright_page(project_dir))
    parts.append('')

    # Dedication
    dedication = read_matter_file(project_dir, 'front_matter', 'dedication')
    if dedication:
        parts.append('# Dedication')
        parts.append('')
        parts.append(dedication)
        parts.append('')

    # Epigraph
    epigraph = read_matter_file(project_dir, 'front_matter', 'epigraph')
    if epigraph:
        parts.append(epigraph)
        parts.append('')

    # Chapters
    for i in range(1, total + 1):
        parts.append(assemble_chapter(i, project_dir, break_style))
        parts.append('')

    # Back matter
    acknowledgments = read_matter_file(project_dir, 'back_matter',
                                       'acknowledgments')
    if acknowledgments:
        parts.append('# Acknowledgments')
        parts.append('')
        parts.append(acknowledgments)
        parts.append('')

    about_author = read_matter_file(project_dir, 'back_matter',
                                    'about-the-author')
    if about_author:
        parts.append('# About the Author')
        parts.append('')
        parts.append(about_author)
        parts.append('')

    also_by = read_matter_file(project_dir, 'back_matter', 'also-by')
    if also_by:
        parts.append('# Also By')
        parts.append('')
        parts.append(also_by)
        parts.append('')

    content = '\n'.join(parts)

    os.makedirs(os.path.dirname(output_file) or '.', exist_ok=True)
    with open(output_file, 'w') as f:
        f.write(content)

    return manuscript_word_count(output_file)


def manuscript_word_count(manuscript_file: str) -> int:
    """Count words in an assembled manuscript file."""
    if not os.path.isfile(manuscript_file):
        return 0

    with open(manuscript_file) as f:
        content = f.read()

    return len(content.split())


# ============================================================================
# CSS / styling
# ============================================================================

def get_genre_css(plugin_dir: str, genre: str) -> str:
    """Resolve the CSS file path for a genre preset.

    Args:
        plugin_dir: Path to the storyforge plugin directory.
        genre: Genre name (e.g. ``fantasy``, ``science fiction``).

    Returns:
        Absolute path to the CSS file (falls back to ``default.css``).
    """
    normalized = genre.lower().replace(' ', '-')
    css_file = os.path.join(plugin_dir, 'templates', 'production', 'css',
                            f'{normalized}.css')

    if os.path.isfile(css_file):
        return css_file

    return os.path.join(plugin_dir, 'templates', 'production', 'css',
                        'default.css')


# ============================================================================
# Format generation (epub, html, pdf)
# ============================================================================

def generate_cover_if_missing(project_dir: str, plugin_dir: str) -> None:
    """Generate a placeholder SVG cover if no cover image exists."""
    production_dir = os.path.join(project_dir, 'production')
    for ext in ('jpg', 'jpeg', 'png', 'webp', 'svg'):
        if os.path.isfile(os.path.join(production_dir, f'cover.{ext}')):
            return

    title = _yaml_field(project_dir, 'project.title', 'title') or 'Untitled'
    author = read_production_field(project_dir, 'author') or ''

    os.makedirs(production_dir, exist_ok=True)
    svg = (
        f'<svg xmlns="http://www.w3.org/2000/svg" width="1600" height="2400" '
        f'viewBox="0 0 1600 2400">\n'
        f'  <rect width="1600" height="2400" fill="#2c3e50"/>\n'
        f'  <text x="800" y="1000" text-anchor="middle" '
        f'font-family="Georgia, serif" font-size="80" fill="#ecf0f1">'
        f'{title}</text>\n'
        f'  <text x="800" y="1150" text-anchor="middle" '
        f'font-family="Georgia, serif" font-size="48" fill="#bdc3c7">'
        f'{author}</text>\n'
        f'</svg>\n'
    )
    with open(os.path.join(production_dir, 'cover.svg'), 'w') as f:
        f.write(svg)


def generate_epub(project_dir: str, manuscript_file: str,
                  epub_file: str, plugin_dir: str) -> None:
    """Generate an epub file from an assembled manuscript via pandoc."""
    import subprocess

    genre = _yaml_field(project_dir, 'project.genre', 'genre') or 'default'
    css_file = get_genre_css(plugin_dir, genre)

    # Write metadata YAML to a temp file
    metadata = generate_epub_metadata(project_dir)
    meta_file = os.path.join(project_dir, 'working', 'epub-metadata.yaml')
    os.makedirs(os.path.dirname(meta_file), exist_ok=True)
    with open(meta_file, 'w') as f:
        f.write(metadata)

    cmd = [
        'pandoc', manuscript_file,
        '-o', epub_file,
        '--metadata-file', meta_file,
        '--css', css_file,
        '--toc', '--toc-depth=1',
        '--epub-chapter-level=1',
    ]

    # Add cover image if available
    cover_image = read_production_field(project_dir, 'cover_image')
    if cover_image:
        full_path = os.path.join(project_dir, cover_image)
        if os.path.isfile(full_path):
            cmd.extend(['--epub-cover-image', full_path])

    subprocess.run(cmd, check=True)


def generate_html(project_dir: str, manuscript_file: str,
                  html_file: str, plugin_dir: str) -> None:
    """Generate a standalone HTML file from an assembled manuscript via pandoc."""
    import subprocess

    genre = _yaml_field(project_dir, 'project.genre', 'genre') or 'default'
    css_file = get_genre_css(plugin_dir, genre)
    title = _yaml_field(project_dir, 'project.title', 'title') or 'Untitled'

    cmd = [
        'pandoc', manuscript_file,
        '-o', html_file,
        '--standalone',
        '--css', css_file,
        '--toc', '--toc-depth=1',
        f'--metadata=title:{title}',
    ]
    subprocess.run(cmd, check=True)


def generate_pdf(project_dir: str, manuscript_file: str,
                 pdf_file: str, plugin_dir: str) -> None:
    """Generate a PDF from an assembled manuscript via pandoc + weasyprint."""
    import subprocess

    genre = _yaml_field(project_dir, 'project.genre', 'genre') or 'default'
    css_file = get_genre_css(plugin_dir, genre)
    title = _yaml_field(project_dir, 'project.title', 'title') or 'Untitled'

    # Try weasyprint first (better typography), fall back to default engine
    cmd = [
        'pandoc', manuscript_file,
        '-o', pdf_file,
        '--pdf-engine=weasyprint',
        '--css', css_file,
        f'--metadata=title:{title}',
    ]
    r = subprocess.run(cmd, capture_output=True)
    if r.returncode != 0:
        # Fall back to default pdf engine (pdflatex/xelatex)
        cmd = [
            'pandoc', manuscript_file,
            '-o', pdf_file,
            f'--metadata=title:{title}',
            '-V', 'geometry:margin=1in',
        ]
        subprocess.run(cmd, check=True)


# ============================================================================
# Web book generation
# ============================================================================

HEAD_SCRIPT = (
    "(function(){var t=localStorage.getItem('storyforge-theme');"
    "if(t)document.documentElement.dataset.theme=t;"
    "else if(window.matchMedia('(prefers-color-scheme:dark)').matches)"
    "document.documentElement.dataset.theme='dark'})();"
)


def _read_template(plugin_dir: str, filename: str) -> str:
    """Read a web-book template file."""
    path = os.path.join(plugin_dir, 'templates', 'production',
                        'web-book', filename)
    with open(path) as f:
        return f.read()


def _md_to_html(markdown_text: str) -> str:
    """Convert markdown to HTML using pandoc."""
    import subprocess
    r = subprocess.run(
        ['pandoc', '-f', 'markdown', '-t', 'html', '--no-highlight'],
        input=markdown_text, capture_output=True, text=True,
    )
    if r.returncode != 0:
        raise RuntimeError(f'pandoc failed: {r.stderr[:300]}')
    return r.stdout


def generate_web_book(project_dir: str, plugin_dir: str,
                      annotate: bool = False) -> str:
    """Generate a multi-page web book from chapter map.

    Creates:
        output/web/index.html       — landing page
        output/web/contents.html    — table of contents
        output/web/chapters/chapter-N.html — one per chapter
        output/web/chapters/part-N.html    — part interstitials (if parts)
        output/web/fonts/            — embedded fonts

    Args:
        project_dir: Root directory of the project.
        plugin_dir: Path to the storyforge plugin directory.
        annotate: Whether to include annotation overlay.

    Returns:
        Path to the generated web book directory.
    """
    import json
    import shutil

    title = _yaml_field(project_dir, 'project.title', 'title') or 'Untitled'
    author = read_production_field(project_dir, 'author') or ''
    lang = read_production_field(project_dir, 'language') or 'en'
    genre = _yaml_field(project_dir, 'project.genre', 'genre') or 'default'
    description = _yaml_field(project_dir, 'project.logline', 'logline') or ''
    title_slug = re.sub(r'[^a-z0-9-]', '', title.lower().replace(' ', '-'))
    total_chapters = count_chapters(project_dir)
    break_style = read_production_field(project_dir, 'scene_break') or 'blank'
    total_parts = count_parts(project_dir)

    if total_chapters == 0:
        print('ERROR: No chapters in chapter-map.csv', file=sys.stderr)
        return ''

    # Output directory
    web_dir = os.path.join(project_dir, 'output', 'web')
    chapters_dir = os.path.join(web_dir, 'chapters')
    os.makedirs(chapters_dir, exist_ok=True)

    # Load templates
    index_tpl = _read_template(plugin_dir, 'index.html')
    toc_tpl = _read_template(plugin_dir, 'toc.html')
    chapter_tpl = _read_template(plugin_dir, 'chapter.html')
    part_tpl = _read_template(plugin_dir, 'part.html')
    css = _read_template(plugin_dir, 'reading.css')
    js = _read_template(plugin_dir, 'reading.js')

    if annotate:
        css += '\n' + _read_template(plugin_dir, 'annotations.css')
        js += '\n' + _read_template(plugin_dir, 'annotations.js')

    # Copy fonts
    fonts_src = os.path.join(plugin_dir, 'templates', 'production',
                             'web-book', 'fonts')
    fonts_dst = os.path.join(web_dir, 'fonts')
    if os.path.isdir(fonts_src):
        if os.path.isdir(fonts_dst):
            shutil.rmtree(fonts_dst)
        shutil.copytree(fonts_src, fonts_dst)

    # Cover image
    cover_img = ''
    for ext in ('jpg', 'jpeg', 'png', 'webp', 'svg'):
        candidate = os.path.join(project_dir, 'production', f'cover.{ext}')
        if os.path.isfile(candidate):
            dst = os.path.join(web_dir, f'cover.{ext}')
            shutil.copy2(candidate, dst)
            cover_img = (f'<img src="cover.{ext}" alt="{title}" '
                         f'class="cover-image">')
            break

    # Build chapter map for resume feature and TOC
    chapter_map = {}
    toc_entries = []
    # Track which chapters start a new part
    chapter_parts = {}
    if total_parts > 0:
        for ch in range(1, total_chapters + 1):
            part_title = get_chapter_part_title(ch, project_dir)
            if part_title:
                chapter_parts[ch] = part_title

    # Navigation pages to generate (chapters + part interstitials)
    pages = []  # list of (slug, type, chapter_num_or_part_num)

    seen_parts = set()
    for ch in range(1, total_chapters + 1):
        if ch in chapter_parts and chapter_parts[ch] not in seen_parts:
            part_title = chapter_parts[ch]
            seen_parts.add(part_title)
            part_num = len(seen_parts)
            pages.append((f'part-{part_num}', 'part', part_num))
        pages.append((f'chapter-{ch}', 'chapter', ch))

    # Generate each page
    for idx, (slug, page_type, num) in enumerate(pages):
        prev_link = ''
        next_link = ''
        if idx > 0:
            prev_slug = pages[idx - 1][0]
            prev_link = (f'<a href="{prev_slug}.html" '
                         f'class="nav-link nav-prev">&larr; Previous</a>')
        if idx < len(pages) - 1:
            next_slug = pages[idx + 1][0]
            next_link = (f'<a href="{next_slug}.html" '
                         f'class="nav-link nav-next">Next &rarr;</a>')

        if page_type == 'part':
            part_title = read_part_field(num, project_dir, 'title') or f'Part {num}'
            html = part_tpl
            html = html.replace('{{PART_NUMBER}}', str(num))
            html = html.replace('{{PART_TITLE}}', part_title)
            html = html.replace('{{BOOK_TITLE}}', title)
            html = html.replace('{{AUTHOR}}', author)
            html = html.replace('{{LANG}}', lang)
            html = html.replace('{{CANONICAL}}', '')
            html = html.replace('{{TITLE_FONT_LINK}}', '')
            html = html.replace('{{HEAD_SCRIPT}}', HEAD_SCRIPT)
            html = html.replace('{{CSS}}', css)
            html = html.replace('{{JS}}', js)
            html = html.replace('{{PREV_LINK}}', prev_link)
            html = html.replace('{{NEXT_LINK}}', next_link)
            with open(os.path.join(chapters_dir, f'{slug}.html'), 'w') as f:
                f.write(html)
        else:
            ch_num = num
            ch_title = read_chapter_field(ch_num, project_dir, 'title')
            ch_slug = f'chapter-{ch_num}'
            chapter_map[ch_slug] = ch_title or f'Chapter {ch_num}'

            # Build heading
            heading_format = read_chapter_field(ch_num, project_dir, 'heading')
            if heading_format == 'numbered':
                display_title = f'Chapter {ch_num}'
            elif heading_format == 'titled':
                display_title = ch_title or f'Chapter {ch_num}'
            elif heading_format == 'none':
                display_title = ''
            else:
                display_title = f'Chapter {ch_num}: {ch_title}' if ch_title else f'Chapter {ch_num}'

            # Assemble chapter markdown and convert to HTML
            chapter_md = assemble_chapter(ch_num, project_dir, break_style)
            chapter_html = _md_to_html(chapter_md)

            # Part label if this chapter starts a new part
            part_label = ''
            if ch_num in chapter_parts:
                part_label = (f'<div class="chapter-part-label">'
                              f'{chapter_parts[ch_num]}</div>')

            # TOC entry
            toc_entries.append(
                f'    <a href="chapters/{ch_slug}.html" '
                f'class="toc-entry">{display_title or ch_title}</a>')

            html = chapter_tpl
            html = html.replace('{{CHAPTER_TITLE}}', display_title or ch_title or f'Chapter {ch_num}')
            html = html.replace('{{CHAPTER_SLUG}}', ch_slug)
            html = html.replace('{{CHAPTER_NUM}}', str(ch_num))
            html = html.replace('{{TOTAL_CHAPTERS}}', str(total_chapters))
            html = html.replace('{{CHAPTER_CONTENT}}', chapter_html)
            html = html.replace('{{PART_LABEL}}', part_label)
            html = html.replace('{{BOOK_TITLE}}', title)
            html = html.replace('{{AUTHOR}}', author)
            html = html.replace('{{LANG}}', lang)
            html = html.replace('{{CANONICAL}}', '')
            html = html.replace('{{TITLE_FONT_LINK}}', '')
            html = html.replace('{{HEAD_SCRIPT}}', HEAD_SCRIPT)
            html = html.replace('{{CSS}}', css)
            html = html.replace('{{JS}}', js)
            html = html.replace('{{PREV_LINK}}', prev_link)
            html = html.replace('{{NEXT_LINK}}', next_link)
            html = html.replace('{{TOC_ENTRIES}}', '\n'.join(toc_entries))
            with open(os.path.join(chapters_dir, f'{ch_slug}.html'), 'w') as f:
                f.write(html)

    # Generate TOC page
    toc_html = toc_tpl
    toc_html = toc_html.replace('{{BOOK_TITLE}}', title)
    toc_html = toc_html.replace('{{BOOK_SLUG}}', title_slug)
    toc_html = toc_html.replace('{{AUTHOR}}', author)
    toc_html = toc_html.replace('{{LANG}}', lang)
    toc_html = toc_html.replace('{{CANONICAL}}', '')
    toc_html = toc_html.replace('{{TITLE_FONT_LINK}}', '')
    toc_html = toc_html.replace('{{HEAD_SCRIPT}}', HEAD_SCRIPT)
    toc_html = toc_html.replace('{{CSS}}', css)
    toc_html = toc_html.replace('{{JS}}', js)
    toc_html = toc_html.replace('{{TOC_ENTRIES}}', '\n'.join(toc_entries))
    toc_html = toc_html.replace('{{BACK_MATTER_LINKS}}', '')
    with open(os.path.join(web_dir, 'contents.html'), 'w') as f:
        f.write(toc_html)

    # Generate index/landing page
    first_page = pages[0][0]
    logline_html = f'<p class="book-logline">{description}</p>' if description else ''
    series_name = _yaml_field(project_dir, 'project.series_name')
    series_html = (f'<p class="book-series">{series_name}</p>'
                   if series_name else '')
    copyright_year = (read_production_nested(project_dir, 'copyright', 'year')
                      or str(datetime.now().year))
    copyright_html = (f'<p class="book-copyright">&copy; {copyright_year} '
                      f'{author}</p>')

    index_html = index_tpl
    index_html = index_html.replace('{{BOOK_TITLE}}', title)
    index_html = index_html.replace('{{AUTHOR}}', author)
    index_html = index_html.replace('{{DESCRIPTION}}', description)
    index_html = index_html.replace('{{LANG}}', lang)
    index_html = index_html.replace('{{CANONICAL}}', '')
    index_html = index_html.replace('{{TITLE_FONT_LINK}}', '')
    index_html = index_html.replace('{{HEAD_SCRIPT}}', HEAD_SCRIPT)
    index_html = index_html.replace('{{CSS}}', css)
    index_html = index_html.replace('{{JS}}', js)
    index_html = index_html.replace('{{COVER_IMG}}', cover_img)
    index_html = index_html.replace('{{LOGLINE}}', logline_html)
    index_html = index_html.replace('{{SERIES}}', series_html)
    index_html = index_html.replace('{{COPYRIGHT}}', copyright_html)
    index_html = index_html.replace('{{FIRST_PAGE}}', f'{first_page}.html')
    index_html = index_html.replace('{{CHAPTER_MAP_JSON}}',
                                    json.dumps(chapter_map))
    with open(os.path.join(web_dir, 'index.html'), 'w') as f:
        f.write(index_html)

    return web_dir


# ============================================================================
# CLI interface
# ============================================================================

def main():
    """CLI entry point.

    Usage::

        python3 -m storyforge.assembly assemble <project_dir> <output_file>
        python3 -m storyforge.assembly chapter <chapter_num> <project_dir> [--break-style space]
        python3 -m storyforge.assembly extract-prose <scene_file>
        python3 -m storyforge.assembly word-count <manuscript_file>
        python3 -m storyforge.assembly metadata <project_dir>
        python3 -m storyforge.assembly toc <project_dir>
        python3 -m storyforge.assembly genre-css <plugin_dir> <genre>
    """
    if len(sys.argv) < 2:
        print('Usage: python3 -m storyforge.assembly <command> [args]',
              file=sys.stderr)
        sys.exit(1)

    command = sys.argv[1]

    if command == 'assemble':
        if len(sys.argv) < 4:
            print('Usage: assemble <project_dir> <output_file>',
                  file=sys.stderr)
            sys.exit(1)
        wc = assemble_manuscript(sys.argv[2], sys.argv[3])
        print(wc)

    elif command == 'chapter':
        if len(sys.argv) < 4:
            print('Usage: chapter <chapter_num> <project_dir> '
                  '[--break-style space]', file=sys.stderr)
            sys.exit(1)
        chapter_num = int(sys.argv[2])
        project_dir = sys.argv[3]
        break_style = 'space'
        i = 4
        while i < len(sys.argv):
            if sys.argv[i] == '--break-style' and i + 1 < len(sys.argv):
                break_style = sys.argv[i + 1]
                i += 2
            else:
                print(f'Unknown flag: {sys.argv[i]}', file=sys.stderr)
                sys.exit(1)
        print(assemble_chapter(chapter_num, project_dir, break_style))

    elif command == 'extract-prose':
        if len(sys.argv) < 3:
            print('Usage: extract-prose <scene_file>', file=sys.stderr)
            sys.exit(1)
        print(extract_scene_prose(sys.argv[2]))

    elif command == 'word-count':
        if len(sys.argv) < 3:
            print('Usage: word-count <manuscript_file>', file=sys.stderr)
            sys.exit(1)
        print(manuscript_word_count(sys.argv[2]))

    elif command == 'metadata':
        if len(sys.argv) < 3:
            print('Usage: metadata <project_dir>', file=sys.stderr)
            sys.exit(1)
        print(generate_epub_metadata(sys.argv[2]))

    elif command == 'toc':
        if len(sys.argv) < 3:
            print('Usage: toc <project_dir>', file=sys.stderr)
            sys.exit(1)
        result = generate_toc(sys.argv[2])
        if result:
            print(result)
        else:
            print('ERROR: No chapters found', file=sys.stderr)
            sys.exit(1)

    elif command == 'genre-css':
        if len(sys.argv) < 4:
            print('Usage: genre-css <plugin_dir> <genre>', file=sys.stderr)
            sys.exit(1)
        print(get_genre_css(sys.argv[2], sys.argv[3]))

    elif command == 'count-chapters':
        if len(sys.argv) < 3:
            print('Usage: count-chapters <project_dir>', file=sys.stderr)
            sys.exit(1)
        print(count_chapters(sys.argv[2]))

    elif command == 'read-chapter-field':
        if len(sys.argv) < 5:
            print('Usage: read-chapter-field <chapter_num> <project_dir> <field>',
                  file=sys.stderr)
            sys.exit(1)
        print(read_chapter_field(int(sys.argv[2]), sys.argv[3], sys.argv[4]))

    elif command == 'chapter-scenes':
        if len(sys.argv) < 4:
            print('Usage: chapter-scenes <chapter_num> <project_dir>',
                  file=sys.stderr)
            sys.exit(1)
        for scene_id in get_chapter_scenes(int(sys.argv[2]), sys.argv[3]):
            print(scene_id)

    else:
        print(f'Unknown command: {command}', file=sys.stderr)
        sys.exit(1)


def generate_publish_manifest(project_dir: str, cover_path: str | None = None,
                              include_dashboard: bool = False,
                              include_cover: bool = False) -> str:
    """Generate a JSON publish manifest from scene files and chapter map.

    Converts each scene's markdown to HTML, groups by chapter from
    chapter-map.csv, and writes working/publish-manifest.json.

    The manifest is compatible with the Bookshelf PUT /api/books/<slug>
    endpoint and optionally includes dashboard_html and cover_base64.

    Args:
        project_dir: Root directory of the project.
        cover_path: Optional path to cover image (absolute or relative to
            project_dir). When include_cover is True and cover_path is None,
            auto-detects from production/cover.* or manuscript/assets/cover.*.
        include_dashboard: If True, read working/dashboard.html and embed it.
        include_cover: If True, base64-encode the cover image and embed it.

    Returns:
        Path to the generated manifest file.

    Raises:
        ValueError: If the chapter map is stale.
    """
    import base64
    import json
    from storyforge.common import (check_chapter_map_freshness,
                                   read_yaml_field as _common_read_yaml_field)

    # Check freshness
    is_fresh, missing, extra = check_chapter_map_freshness(project_dir)
    if not is_fresh:
        parts = []
        if missing:
            parts.append(f'scenes not in chapter map: {", ".join(missing)}')
        if extra:
            parts.append(f'chapter map references removed scenes: {", ".join(extra)}')
        raise ValueError(f'Chapter map is stale — {"; ".join(parts)}')

    title = _common_read_yaml_field('project.title', project_dir) or 'Untitled'
    author = _common_read_yaml_field('project.author', project_dir) or 'Unknown'
    slug = re.sub(r'[^a-z0-9]+', '-', title.lower()).strip('-')

    scenes_dir = os.path.join(project_dir, 'scenes')
    total_chapters = count_chapters(project_dir)

    chapters = []
    for ch_num in range(1, total_chapters + 1):
        ch_title = read_chapter_field(ch_num, project_dir, 'title')
        scene_ids = get_chapter_scenes(ch_num, project_dir)

        scenes = []
        for sort_idx, scene_id in enumerate(scene_ids, 1):
            scene_file = os.path.join(scenes_dir, f'{scene_id}.md')
            if not os.path.isfile(scene_file):
                continue

            with open(scene_file) as f:
                md = f.read()

            # Strip YAML frontmatter if present
            if md.startswith('---'):
                end = md.find('---', 3)
                if end != -1:
                    md = md[end + 3:].strip()

            html = _md_to_html(md)
            word_count = len(md.split())

            scenes.append({
                'slug': scene_id,
                'content_html': html.strip(),
                'word_count': word_count,
                'sort_order': sort_idx,
            })

        chapters.append({
            'number': ch_num,
            'title': ch_title,
            'scenes': scenes,
        })

    # Read optional metadata from storyforge.yaml
    genre = _common_read_yaml_field('project.genre', project_dir) or ''
    language = _common_read_yaml_field('project.language', project_dir) or 'en'
    metadata = {}
    if genre:
        metadata['genre'] = genre
    if language:
        metadata['language'] = language

    manifest = {
        'title': title,
        'author': author,
        'slug': slug,
        'metadata': metadata,
        'chapters': chapters,
    }

    # Embed dashboard HTML if requested
    if include_dashboard:
        dashboard_path = os.path.join(project_dir, 'working', 'dashboard.html')
        if os.path.isfile(dashboard_path):
            with open(dashboard_path) as f:
                manifest['dashboard_html'] = f.read()

    # Always include structured dashboard data for server-side rendering
    from storyforge.visualize import load_dashboard_data
    manifest['dashboard_data'] = load_dashboard_data(project_dir)

    # Embed cover as base64 if requested
    if include_cover:
        resolved = _resolve_cover_path(project_dir, cover_path)
        if resolved and os.path.isfile(resolved):
            optimized = _optimize_cover_image(resolved, project_dir)
            with open(optimized, 'rb') as f:
                manifest['cover_base64'] = base64.b64encode(f.read()).decode('ascii')
            manifest['cover_extension'] = os.path.splitext(optimized)[1]

    output_path = os.path.join(project_dir, 'working', 'publish-manifest.json')
    os.makedirs(os.path.dirname(output_path), exist_ok=True)
    with open(output_path, 'w') as f:
        json.dump(manifest, f, indent=2, ensure_ascii=False)

    return output_path


_COVER_MAX_DIMENSION = 1600
_COVER_MAX_BYTES = 500_000  # 500 KB — skip optimization if already small


def _optimize_cover_image(cover_path: str, project_dir: str) -> str:
    """Optimize a cover image for publishing.

    Converts PNG to JPEG and resizes if either dimension exceeds
    _COVER_MAX_DIMENSION.  Uses macOS ``sips`` (available on Darwin).
    Returns path to the optimized file in working/, or the original
    path if optimization is unnecessary or unavailable.
    """
    import platform
    import shutil
    import subprocess

    file_size = os.path.getsize(cover_path)
    ext = os.path.splitext(cover_path)[1].lower()

    # Skip if already small enough
    if file_size <= _COVER_MAX_BYTES and ext in ('.jpg', '.jpeg'):
        return cover_path

    # sips is macOS-only
    if platform.system() != 'Darwin':
        from storyforge.common import log
        if file_size > _COVER_MAX_BYTES:
            log(f'WARNING: Cover image is {file_size:,} bytes — '
                f'optimization requires macOS sips')
        return cover_path

    from storyforge.common import log
    working_dir = os.path.join(project_dir, 'working')
    os.makedirs(working_dir, exist_ok=True)

    # Convert PNG/WebP to JPEG for smaller size
    if ext in ('.png', '.webp'):
        optimized = os.path.join(working_dir, 'cover-optimized.jpg')
        shutil.copy2(cover_path, optimized)
        try:
            subprocess.run(
                ['sips', '-s', 'format', 'jpeg',
                 '-s', 'formatOptions', '85',
                 optimized, '--out', optimized],
                capture_output=True, check=True,
            )
            log(f'Cover: converted {ext} to JPEG '
                f'({file_size:,} → {os.path.getsize(optimized):,} bytes)')
        except (subprocess.CalledProcessError, FileNotFoundError):
            log(f'WARNING: sips conversion failed, using original')
            return cover_path
    else:
        optimized = os.path.join(working_dir, f'cover-optimized{ext}')
        shutil.copy2(cover_path, optimized)

    # Resize if dimensions are too large
    try:
        result = subprocess.run(
            ['sips', '-g', 'pixelWidth', '-g', 'pixelHeight', optimized],
            capture_output=True, text=True, check=True,
        )
        width = height = 0
        for line in result.stdout.splitlines():
            if 'pixelWidth' in line:
                width = int(line.split(':')[-1].strip())
            elif 'pixelHeight' in line:
                height = int(line.split(':')[-1].strip())

        if max(width, height) > _COVER_MAX_DIMENSION:
            subprocess.run(
                ['sips', '--resampleHeightWidthMax', str(_COVER_MAX_DIMENSION),
                 optimized],
                capture_output=True, check=True,
            )
            new_size = os.path.getsize(optimized)
            log(f'Cover: resized from {width}x{height} to max {_COVER_MAX_DIMENSION}px '
                f'({new_size:,} bytes)')
    except (subprocess.CalledProcessError, FileNotFoundError, ValueError):
        pass  # resize failed — use whatever we have

    return optimized


def _resolve_cover_path(project_dir: str, cover_path: str | None) -> str | None:
    """Resolve a cover image path, auto-detecting if not provided.

    Priority: explicit cover_path > production.cover_image YAML field >
    auto-detect from production/ then manuscript/assets/ (jpg first).
    """
    if cover_path:
        if os.path.isabs(cover_path):
            return cover_path
        return os.path.join(project_dir, cover_path)

    # Check production.cover_image YAML field
    try:
        cover_image = read_production_field(project_dir, 'cover_image')
    except Exception:
        cover_image = ''
    if cover_image:
        full = os.path.join(project_dir, cover_image)
        if os.path.isfile(full):
            return full
        from storyforge.common import log
        log(f'WARNING: production.cover_image set to {cover_image!r} but file not found, falling back to auto-detect')

    # Auto-detect from standard locations (jpg preferred for publishing)
    for directory in ('production', 'manuscript/assets'):
        for ext in ('jpg', 'jpeg', 'png', 'webp', 'svg'):
            candidate = os.path.join(project_dir, directory, f'cover.{ext}')
            if os.path.isfile(candidate):
                return candidate
    return None


if __name__ == '__main__':
    main()
