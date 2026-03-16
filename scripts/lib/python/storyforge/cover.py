"""SVG cover generation and template substitution.

Replaces the SVG template variable substitution from cover-api.sh with
clean Python string handling instead of 16 sed calls. Handles text
wrapping, color schemes, and full cover generation from project metadata.
"""

import hashlib
import os
import re
import sys

from storyforge.prompts import read_yaml_field


# ============================================================================
# Color Schemes
# ============================================================================

# Genre color schemes: bg, bg2, accent, accent2, text, text_dim
COLOR_SCHEMES = {
    'fantasy': {
        'bg': '#1a1a2e', 'bg2': '#16213e',
        'accent': '#d4a73a', 'accent2': '#b8860b',
        'text': '#f5f0e8', 'text_dim': 'rgba(245,240,232,0.5)',
    },
    'epic-fantasy': None,  # alias
    'urban-fantasy': None,
    'dark-fantasy': None,
    'science-fiction': {
        'bg': '#0d1117', 'bg2': '#161b22',
        'accent': '#58a6ff', 'accent2': '#1f6feb',
        'text': '#e6edf3', 'text_dim': 'rgba(230,237,243,0.5)',
    },
    'sci-fi': None,  # alias
    'cyberpunk': None,
    'space-opera': None,
    'thriller': {
        'bg': '#111111', 'bg2': '#1a1a1a',
        'accent': '#dc2626', 'accent2': '#991b1b',
        'text': '#f5f5f5', 'text_dim': 'rgba(245,245,245,0.5)',
    },
    'suspense': None,
    'mystery': None,
    'crime': None,
    'romance': {
        'bg': '#2d1b2e', 'bg2': '#1f1520',
        'accent': '#e8a87c', 'accent2': '#c4856c',
        'text': '#fdf6ee', 'text_dim': 'rgba(253,246,238,0.5)',
    },
    'contemporary-romance': None,
    'historical-romance': None,
    'literary-fiction': {
        'bg': '#f5f0e8', 'bg2': '#ede5d8',
        'accent': '#374151', 'accent2': '#6b7280',
        'text': '#1a1a1a', 'text_dim': 'rgba(26,26,26,0.4)',
    },
    'literary': None,
    'upmarket': None,
}

# Aliases map to their parent genre
_GENRE_ALIASES = {
    'epic-fantasy': 'fantasy',
    'urban-fantasy': 'fantasy',
    'dark-fantasy': 'fantasy',
    'sci-fi': 'science-fiction',
    'cyberpunk': 'science-fiction',
    'space-opera': 'science-fiction',
    'suspense': 'thriller',
    'mystery': 'thriller',
    'crime': 'thriller',
    'contemporary-romance': 'romance',
    'historical-romance': 'romance',
    'literary': 'literary-fiction',
    'upmarket': 'literary-fiction',
}

DEFAULT_SCHEME = {
    'bg': '#1e293b', 'bg2': '#0f172a',
    'accent': '#94a3b8', 'accent2': '#64748b',
    'text': '#f1f5f9', 'text_dim': 'rgba(241,245,249,0.5)',
}

# Named palette overrides
PALETTE_OVERRIDES = {
    'warm': {
        'bg': '#2d1b12', 'bg2': '#1a1008',
        'accent': '#d4a73a', 'accent2': '#b8860b',
        'text': '#fdf6ee', 'text_dim': 'rgba(253,246,238,0.5)',
    },
    'cool': {
        'bg': '#0c1222', 'bg2': '#060b16',
        'accent': '#60a5fa', 'accent2': '#3b82f6',
        'text': '#e2e8f0', 'text_dim': 'rgba(226,232,240,0.5)',
    },
    'dark': {
        'bg': '#0a0a0a', 'bg2': '#141414',
        'accent': '#a3a3a3', 'accent2': '#737373',
        'text': '#fafafa', 'text_dim': 'rgba(250,250,250,0.4)',
    },
    'light': {
        'bg': '#fafaf9', 'bg2': '#f5f5f4',
        'accent': '#57534e', 'accent2': '#78716c',
        'text': '#1c1917', 'text_dim': 'rgba(28,25,23,0.4)',
    },
}


def get_color_scheme(genre: str, palette: str = '') -> dict:
    """Return a color scheme dict for a genre.

    Args:
        genre: Genre name (e.g., 'fantasy', 'science-fiction').
               Case-insensitive, spaces converted to hyphens.
        palette: Optional palette override ('warm', 'cool', 'dark', 'light').

    Returns:
        Dict with keys: bg, bg2, accent, accent2, text, text_dim.
    """
    key = genre.lower().strip().replace(' ', '-')

    # Resolve aliases
    if key in _GENRE_ALIASES:
        key = _GENRE_ALIASES[key]

    scheme = COLOR_SCHEMES.get(key) or DEFAULT_SCHEME

    # Apply palette override if specified
    if palette and palette.lower() in PALETTE_OVERRIDES:
        scheme = PALETTE_OVERRIDES[palette.lower()]

    return dict(scheme)


# ============================================================================
# Text Wrapping
# ============================================================================

def wrap_title_for_svg(title: str, max_chars_per_line: int = 20) -> list[str]:
    """Split a long title into lines at word boundaries.

    Args:
        title: The title text.
        max_chars_per_line: Maximum characters per line.

    Returns:
        List of line strings.
    """
    words = title.split()
    if not words:
        return [title]

    lines = []
    current_line = ''

    for word in words:
        if not current_line:
            current_line = word
        elif len(current_line) + 1 + len(word) <= max_chars_per_line:
            current_line += ' ' + word
        else:
            lines.append(current_line)
            current_line = word

    if current_line:
        lines.append(current_line)

    return lines


def generate_title_tspans(title: str, x: int, y: int,
                          line_height: int = 45,
                          max_chars: int = 20) -> str:
    """Generate SVG tspan elements for a wrapped title.

    Produces a ``<tspan>`` element per line, with proper x/dy attributes
    for SVG text positioning. The first tspan uses an absolute ``y``;
    subsequent tspans use ``dy`` for relative positioning.

    Args:
        title: The title text.
        x: The x coordinate (text-anchor center point).
        y: The y coordinate of the first line.
        line_height: Vertical distance between lines in SVG units.
        max_chars: Maximum characters per line before wrapping.

    Returns:
        String of SVG tspan elements, one per line.
    """
    lines = wrap_title_for_svg(title, max_chars)
    parts = []

    for i, line in enumerate(lines):
        escaped = _escape_xml(line)
        if i == 0:
            parts.append(
                f'<tspan x="{x}" y="{y}">{escaped}</tspan>'
            )
        else:
            parts.append(
                f'<tspan x="{x}" dy="{line_height}">{escaped}</tspan>'
            )

    return '\n'.join(parts)


def _escape_xml(text: str) -> str:
    """Escape text for safe inclusion in XML/SVG."""
    return (text
            .replace('&', '&amp;')
            .replace('<', '&lt;')
            .replace('>', '&gt;')
            .replace('"', '&quot;')
            .replace("'", '&apos;'))


# ============================================================================
# SVG Template Substitution
# ============================================================================

def render_svg_template(template_path: str, variables: dict) -> str:
    """Read an SVG template and substitute ``{{VARIABLE}}`` placeholders.

    Replaces every occurrence of ``{{KEY}}`` in the template with the
    corresponding value from *variables*. Keys are matched case-insensitively.
    Unmatched placeholders are left unchanged.

    Args:
        template_path: Path to the SVG template file.
        variables: Dict mapping variable names to replacement values.
                   Values are XML-escaped automatically.

    Returns:
        The rendered SVG as a string.
    """
    with open(template_path, 'r') as f:
        svg = f.read()

    # Build a case-insensitive lookup
    lookup = {k.upper(): _escape_xml(str(v)) for k, v in variables.items()}

    def _replace(match):
        key = match.group(1).upper()
        return lookup.get(key, match.group(0))

    return re.sub(r'\{\{(\w+)\}\}', _replace, svg)


# ============================================================================
# Project Metadata Helpers
# ============================================================================

def _read_project_metadata(project_dir: str) -> dict:
    """Read cover-relevant metadata from storyforge.yaml.

    Args:
        project_dir: Path to the project root.

    Returns:
        Dict with keys: title, author, genre, subtitle, palette,
        series_name, series_position.
    """
    yaml_file = os.path.join(project_dir, 'storyforge.yaml')

    def _field(dotted_key: str, fallback_key: str = '') -> str:
        val = read_yaml_field(yaml_file, dotted_key)
        if not val and fallback_key:
            val = read_yaml_field(yaml_file, fallback_key)
        return val

    title = _field('project.title', 'title') or 'Untitled'
    author = _field('production.author') or _field('project.author', 'author')
    genre = _field('project.genre', 'genre') or 'default'
    subtitle = _field('production.cover.subtitle')
    palette = _field('production.cover.palette')
    series_name = _field('project.series_name')
    series_position = _field('project.series_position')

    return {
        'title': title,
        'author': author,
        'genre': genre,
        'subtitle': subtitle,
        'palette': palette,
        'series_name': series_name,
        'series_position': series_position,
    }


def _compute_title_size(title: str) -> int:
    """Compute title font size based on character count."""
    length = len(title)
    if length <= 8:
        return 140
    elif length <= 15:
        return 120
    elif length <= 25:
        return 96
    elif length <= 40:
        return 72
    return 56


def _max_chars_for_size(font_size: int) -> int:
    """Return max characters per line for a given font size."""
    if font_size >= 120:
        return 12
    elif font_size >= 96:
        return 16
    elif font_size >= 72:
        return 22
    return 30


# ============================================================================
# Cover Generation
# ============================================================================

def generate_svg_cover(project_dir: str, template_path: str,
                       output_path: str) -> str:
    """Generate an SVG cover from project metadata and a template.

    Reads title, author, genre, subtitle, and other metadata from the
    project's storyforge.yaml. Selects a color scheme based on genre,
    computes title wrapping, and renders the SVG template with all
    variables substituted.

    Template variables available:
        ``{{TITLE}}``, ``{{AUTHOR}}``, ``{{SUBTITLE}}``, ``{{GENRE}}``,
        ``{{BG}}``, ``{{BG2}}``, ``{{ACCENT}}``, ``{{ACCENT2}}``,
        ``{{TEXT}}``, ``{{TEXT_DIM}}``, ``{{TITLE_TSPANS}}``,
        ``{{TITLE_SIZE}}``, ``{{SERIES}}``, ``{{SERIES_NAME}}``,
        ``{{SERIES_POSITION}}``.

    If no template file exists, generates a complete standalone SVG
    matching the style of the original bash cover generator.

    Args:
        project_dir: Path to the project root.
        template_path: Path to the SVG template file.
        output_path: Path to write the rendered SVG.

    Returns:
        The output path.
    """
    meta = _read_project_metadata(project_dir)
    scheme = get_color_scheme(meta['genre'], meta['palette'])

    title_size = _compute_title_size(meta['title'])
    max_chars = _max_chars_for_size(title_size)
    title_lines = wrap_title_for_svg(meta['title'], max_chars)

    # Title Y position: centered in upper third of 2400px canvas
    title_block_height = len(title_lines) * (title_size + 20)
    title_y = 600 - title_block_height // 2

    title_tspans = generate_title_tspans(
        meta['title'], x=800, y=title_y,
        line_height=title_size + 20, max_chars=max_chars
    )

    # Series text
    series_text = ''
    if meta['series_name']:
        series_text = meta['series_name']
        if meta['series_position']:
            series_text += f" \u00b7 Book {meta['series_position']}"

    variables = {
        'TITLE': meta['title'],
        'AUTHOR': meta['author'],
        'SUBTITLE': meta['subtitle'],
        'GENRE': meta['genre'],
        'BG': scheme['bg'],
        'BG2': scheme['bg2'],
        'ACCENT': scheme['accent'],
        'ACCENT2': scheme['accent2'],
        'TEXT': scheme['text'],
        'TEXT_DIM': scheme['text_dim'],
        'TITLE_SIZE': str(title_size),
        'TITLE_TSPANS': title_tspans,
        'SERIES': series_text,
        'SERIES_NAME': meta['series_name'],
        'SERIES_POSITION': meta['series_position'],
    }

    if os.path.isfile(template_path):
        svg = render_svg_template(template_path, variables)
    else:
        svg = _generate_standalone_svg(meta, scheme, title_size,
                                       title_lines, title_y)

    os.makedirs(os.path.dirname(output_path) or '.', exist_ok=True)
    with open(output_path, 'w') as f:
        f.write(svg)

    return output_path


def _generate_standalone_svg(meta: dict, scheme: dict, title_size: int,
                             title_lines: list[str], title_y: int) -> str:
    """Generate a complete SVG cover without a template.

    Produces an SVG matching the style of the original bash cover
    generator, with gradient background, title, author, subtitle,
    decorative rule, and series badge.
    """
    title_block_height = len(title_lines) * (title_size + 20)

    # Title text elements
    title_parts = []
    for i, line in enumerate(title_lines):
        line_y = title_y + i * (title_size + 20)
        escaped = _escape_xml(line)
        title_parts.append(
            f'  <text x="800" y="{line_y}" text-anchor="middle" '
            f'font-family="Georgia, \'Palatino Linotype\', \'Book Antiqua\', serif" '
            f'font-size="{title_size}" font-weight="bold" '
            f'fill="{scheme["text"]}" letter-spacing="2">{escaped}</text>'
        )
    title_svg = '\n'.join(title_parts)

    # Subtitle
    subtitle_svg = ''
    if meta['subtitle']:
        sub_y = title_y + title_block_height + 40
        escaped = _escape_xml(meta['subtitle'])
        subtitle_svg = (
            f'  <text x="800" y="{sub_y}" text-anchor="middle" '
            f'font-family="Georgia, \'Palatino Linotype\', serif" '
            f'font-size="32" font-weight="normal" font-style="italic" '
            f'fill="{scheme["text_dim"]}">{escaped}</text>'
        )

    # Decorative rule
    rule_y = title_y + title_block_height + 100
    rule_svg = (
        f'  <line x1="650" y1="{rule_y}" x2="950" y2="{rule_y}" '
        f'stroke="{scheme["accent"]}" stroke-width="1" opacity="0.4"/>'
    )

    # Author
    author_svg = ''
    if meta['author']:
        escaped = _escape_xml(meta['author'])
        author_svg = (
            f'  <text x="800" y="2100" text-anchor="middle" '
            f'font-family="Georgia, \'Palatino Linotype\', serif" '
            f'font-size="40" font-weight="normal" '
            f'fill="{scheme["text"]}" letter-spacing="6">{escaped}</text>'
        )

    # Series badge
    series_svg = ''
    if meta['series_name']:
        series_text = meta['series_name']
        if meta['series_position']:
            series_text += f' \u00b7 Book {meta["series_position"]}'
        escaped = _escape_xml(series_text)
        series_svg = (
            f'  <text x="800" y="2200" text-anchor="middle" '
            f"font-family=\"'Courier New', monospace\" "
            f'font-size="22" font-weight="normal" '
            f'fill="{scheme["text_dim"]}" letter-spacing="4">{escaped}</text>'
        )

    return f'''<svg xmlns="http://www.w3.org/2000/svg" width="1600" height="2400" viewBox="0 0 1600 2400">
  <!-- Background -->
  <defs>
    <linearGradient id="bg-grad" x1="0" y1="0" x2="0" y2="1">
      <stop offset="0%" stop-color="{scheme['bg']}"/>
      <stop offset="100%" stop-color="{scheme['bg2']}"/>
    </linearGradient>
  </defs>
  <rect width="1600" height="2400" fill="url(#bg-grad)"/>

  <!-- Title -->
{title_svg}

  <!-- Subtitle -->
{subtitle_svg}

  <!-- Rule -->
{rule_svg}

  <!-- Author -->
{author_svg}

  <!-- Series -->
{series_svg}
</svg>'''


# ============================================================================
# CLI Interface
# ============================================================================

def main():
    """CLI entry point.

    Usage:
        python3 -m storyforge.cover render <template> <output> --title "T" --author "A" [--subtitle "S"] [--genre "G"]
        python3 -m storyforge.cover generate <project_dir> <template> <output>
        python3 -m storyforge.cover wrap-title "A Very Long Book Title"
        python3 -m storyforge.cover color-scheme <genre> [--palette <name>]
    """
    if len(sys.argv) < 2:
        print('Usage: python3 -m storyforge.cover <command> [args]', file=sys.stderr)
        sys.exit(1)

    command = sys.argv[1]

    if command == 'render':
        _cli_render(sys.argv[2:])

    elif command == 'generate':
        if len(sys.argv) < 5:
            print('Usage: python3 -m storyforge.cover generate <project_dir> <template> <output>',
                  file=sys.stderr)
            sys.exit(1)
        project_dir, template_path, output_path = sys.argv[2:5]
        result = generate_svg_cover(project_dir, template_path, output_path)
        print(result)

    elif command == 'wrap-title':
        if len(sys.argv) < 3:
            print('Usage: python3 -m storyforge.cover wrap-title "Title" [max_chars]',
                  file=sys.stderr)
            sys.exit(1)
        title = sys.argv[2]
        max_chars = int(sys.argv[3]) if len(sys.argv) > 3 else 20
        lines = wrap_title_for_svg(title, max_chars)
        for line in lines:
            print(line)

    elif command == 'color-scheme':
        if len(sys.argv) < 3:
            print('Usage: python3 -m storyforge.cover color-scheme <genre> [--palette <name>]',
                  file=sys.stderr)
            sys.exit(1)
        genre = sys.argv[2]
        palette = ''
        if '--palette' in sys.argv:
            idx = sys.argv.index('--palette')
            if idx + 1 < len(sys.argv):
                palette = sys.argv[idx + 1]
        scheme = get_color_scheme(genre, palette)
        for key, value in scheme.items():
            print(f'{key}={value}')

    else:
        print(f'Unknown command: {command}', file=sys.stderr)
        sys.exit(1)


def _cli_render(args: list[str]):
    """Parse args and run the render command."""
    if len(args) < 2:
        print('Usage: python3 -m storyforge.cover render <template> <output> --title "T" --author "A" [--subtitle "S"] [--genre "G"]',
              file=sys.stderr)
        sys.exit(1)

    template_path = args[0]
    output_path = args[1]

    # Parse named arguments
    variables = {}
    flag_map = {
        '--title': 'TITLE',
        '--author': 'AUTHOR',
        '--subtitle': 'SUBTITLE',
        '--genre': 'GENRE',
        '--palette': '_palette',
    }

    i = 2
    while i < len(args):
        if args[i] in flag_map and i + 1 < len(args):
            variables[flag_map[args[i]]] = args[i + 1]
            i += 2
        else:
            print(f'Unknown argument: {args[i]}', file=sys.stderr)
            sys.exit(1)

    # Add color scheme variables
    genre = variables.get('GENRE', 'default')
    palette = variables.pop('_palette', '')
    scheme = get_color_scheme(genre, palette)
    variables.update({
        'BG': scheme['bg'],
        'BG2': scheme['bg2'],
        'ACCENT': scheme['accent'],
        'ACCENT2': scheme['accent2'],
        'TEXT': scheme['text'],
        'TEXT_DIM': scheme['text_dim'],
    })

    # Add title tspans if title provided
    title = variables.get('TITLE', '')
    if title:
        title_size = _compute_title_size(title)
        max_chars = _max_chars_for_size(title_size)
        title_lines = wrap_title_for_svg(title, max_chars)
        title_block_height = len(title_lines) * (title_size + 20)
        title_y = 600 - title_block_height // 2
        variables['TITLE_SIZE'] = str(title_size)
        variables['TITLE_TSPANS'] = generate_title_tspans(
            title, x=800, y=title_y,
            line_height=title_size + 20, max_chars=max_chars
        )

    svg = render_svg_template(template_path, variables)

    os.makedirs(os.path.dirname(output_path) or '.', exist_ok=True)
    with open(output_path, 'w') as f:
        f.write(svg)

    print(output_path)


if __name__ == '__main__':
    main()
