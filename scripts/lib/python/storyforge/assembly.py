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
        f'title: "{title}"',
        f'author: "{author}"',
        f'lang: {language}',
        f'date: {copyright_year}',
    ]

    if genre:
        lines.append(f'subject: "{genre}"')
    if isbn:
        lines.append(f'identifier: "{isbn}"')
    if cover_image:
        full_path = os.path.join(project_dir, cover_image)
        if os.path.isfile(full_path):
            lines.append(f'cover-image: "{full_path}"')

    # Series metadata
    series_name = _yaml_field(project_dir, 'project.series_name')
    series_position = _yaml_field(project_dir, 'project.series_position')
    if series_name:
        lines.append(f'belongs-to-collection: "{series_name}"')
        if series_position:
            lines.append(f'group-position: "{series_position}"')

    lines.append(f'rights: "Copyright \u00a9 {copyright_year} {author}"')
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

    else:
        print(f'Unknown command: {command}', file=sys.stderr)
        sys.exit(1)


if __name__ == '__main__':
    main()
