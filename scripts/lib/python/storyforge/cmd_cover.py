"""storyforge cover — Generate a typographic book cover from title and genre.

Creates a beautiful SVG cover with generative patterns seeded from the
book's title, styled by genre. Converts to PNG for epub embedding.

Usage:
    storyforge cover                  # Generate PNG cover
    storyforge cover --svg-only       # Generate SVG only (for preview)
    storyforge cover --output path    # Custom output path
    storyforge cover --dry-run        # Print config without generating
"""

import argparse
import hashlib
import math
import os
import shutil
import subprocess
import sys

from storyforge.common import detect_project_root, log, read_yaml_field
from storyforge.cover import (
    get_color_scheme, _compute_title_size, _max_chars_for_size,
    wrap_title_for_svg, _escape_xml, _read_project_metadata,
    _generate_standalone_svg,
)


def parse_args(argv):
    parser = argparse.ArgumentParser(
        prog='storyforge cover',
        description='Generate a typographic book cover from project title and genre.',
    )
    parser.add_argument('--dry-run', action='store_true',
                        help='Print config without generating')
    parser.add_argument('--svg-only', action='store_true',
                        help='Output SVG without PNG conversion')
    parser.add_argument('--output', type=str, default='',
                        help='Override output path (default: manuscript/assets/cover.png)')
    return parser.parse_args(argv)


def main(argv=None):
    args = parse_args(argv or [])

    project_dir = detect_project_root()
    log(f'Project root: {project_dir}')

    # --- Read project metadata ---
    meta = _read_project_metadata(project_dir)
    title = meta['title']
    author = meta['author']
    genre = meta['genre']
    genre_lc = genre.lower().replace(' ', '-')
    series_name = meta['series_name']
    series_pos = meta['series_position']
    subtitle = meta['subtitle']
    palette = meta['palette']

    # --- Set output paths ---
    assets_dir = os.path.join(project_dir, 'manuscript', 'assets')
    if args.output:
        output_path = args.output
        if not os.path.isabs(output_path):
            output_path = os.path.join(project_dir, output_path)
        svg_file = os.path.splitext(output_path)[0] + '.svg'
        png_file = output_path
    elif args.svg_only:
        svg_file = os.path.join(assets_dir, 'cover.svg')
        png_file = ''
    else:
        svg_file = os.path.join(assets_dir, 'cover.svg')
        png_file = os.path.join(assets_dir, 'cover.png')

    # --- Dry run ---
    if args.dry_run:
        log('=== Cover Generation (dry run) ===')
        log(f'  Title:    {title}')
        log(f'  Author:   {author or "[not set]"}')
        log(f'  Genre:    {genre} ({genre_lc})')
        log(f'  Subtitle: {subtitle or "[none]"}')
        log(f'  Palette:  {palette or "[genre default]"}')
        if series_name:
            log(f'  Series:   {series_name} #{series_pos}')
        log(f'  SVG:      {svg_file}')
        if not args.svg_only:
            log(f'  PNG:      {png_file}')
        sys.exit(0)

    # --- PRNG from title hash ---
    title_hash = hashlib.md5(title.encode()).hexdigest()

    def seed_from_hash(offset):
        """Extract a 0-255 value from 2 hex chars at offset."""
        return int(title_hash[offset:offset + 2], 16)

    def prng(offset, min_val, max_val):
        """Pseudo-random int in [min_val, max_val] from hash position."""
        val = seed_from_hash(offset % len(title_hash))
        return min_val + (val % (max_val - min_val + 1))

    def prng100(offset, min_val, max_val):
        """Pseudo-random value scaled 0-255 into [min_val, max_val]."""
        val = seed_from_hash(offset % len(title_hash))
        return min_val + (val * (max_val - min_val) // 255)

    # --- Get color scheme ---
    scheme = get_color_scheme(genre, palette)
    bg_color = scheme['bg']
    bg_color2 = scheme['bg2']
    accent = scheme['accent']
    accent2 = scheme['accent2']
    text_color = scheme['text']
    text_dim = scheme['text_dim']

    # --- Pattern generators ---
    def draw_fantasy_pattern():
        cx, cy = 800, 1200
        elements = []
        for i in range(6):
            r = 200 + i * 120 + prng(i * 2, -40, 40)
            sw = prng(i * 2 + 10, 1, 3)
            opacity = prng100(i * 2 + 12, 15, 40)
            dash = prng(i * 2 + 14, 8, 40)
            gap = prng(i * 2 + 16, 4, 20)
            elements.append(
                f'<circle cx="{cx}" cy="{cy}" r="{r}" fill="none" '
                f'stroke="{accent}" stroke-width="{sw}" opacity="0.{opacity}" '
                f'stroke-dasharray="{dash} {gap}"/>'
            )
        num_lines = prng(20, 6, 16)
        for i in range(num_lines):
            angle = i * 360 // num_lines + prng(22 + i, -8, 8)
            r1 = prng(24 + i, 100, 300)
            r2 = prng(26 + i, 500, 900)
            rad = math.radians(angle)
            x1 = int(cx + r1 * math.cos(rad))
            y1 = int(cy + r1 * math.sin(rad))
            x2 = int(cx + r2 * math.cos(rad))
            y2 = int(cy + r2 * math.sin(rad))
            opacity = prng100(28 + i, 10, 30)
            elements.append(
                f'<line x1="{x1}" y1="{y1}" x2="{x2}" y2="{y2}" '
                f'stroke="{accent}" stroke-width="1" opacity="0.{opacity}"/>'
            )
        d_size = prng(30, 40, 80)
        d_opacity = prng100(1, 15, 35)
        elements.append(
            f'<polygon points="800,{200 - d_size} {800 + d_size},200 '
            f'800,{200 + d_size} {800 - d_size},200" fill="none" '
            f'stroke="{accent}" stroke-width="1.5" opacity="0.{d_opacity}"/>'
        )
        return '\n'.join(elements)

    def draw_scifi_pattern():
        elements = []
        grid_size = prng(0, 4, 7)
        spacing = 1600 // (grid_size + 1)
        for i in range(1, grid_size + 1):
            for j in range(1, grid_size + 4):
                x = i * spacing + prng((i * 7 + j) % 30, -20, 20)
                y = j * spacing + prng((i * 3 + j * 5) % 30, -20, 20)
                r = prng((i + j) % 30, 2, 6)
                opacity = prng100((i * j) % 30, 10, 35)
                elements.append(
                    f'<circle cx="{x}" cy="{y}" r="{r}" fill="{accent}" '
                    f'opacity="0.{opacity}"/>'
                )
        num_lines = prng(4, 8, 16)
        for i in range(num_lines):
            x1 = prng(i * 2, 100, 1500)
            y1 = prng(i * 2 + 1, 100, 2300)
            length = prng(i * 2 + 6, 100, 600)
            vertical = prng(i * 2 + 8, 0, 1)
            if vertical:
                x2, y2 = x1, y1 + length
            else:
                x2, y2 = x1 + length, y1
            opacity = prng100(i * 2 + 10, 8, 25)
            elements.append(
                f'<line x1="{x1}" y1="{y1}" x2="{x2}" y2="{y2}" '
                f'stroke="{accent}" stroke-width="1" opacity="0.{opacity}"/>'
            )
            elements.append(
                f'<circle cx="{x1}" cy="{y1}" r="3" fill="{accent}" opacity="0.{opacity}"/>'
            )
            elements.append(
                f'<circle cx="{x2}" cy="{y2}" r="3" fill="{accent}" opacity="0.{opacity}"/>'
            )
        for hex_y in [400, 800, 1200, 1600, 2000]:
            hex_x = prng(hex_y % 28, 200, 1400)
            hex_r = prng((hex_y + 2) % 28, 60, 140)
            opacity = prng100((hex_y + 4) % 28, 5, 20)
            h87 = hex_r * 87 // 100
            pts = (f'{hex_x + hex_r},{hex_y} {hex_x + hex_r // 2},{hex_y + h87} '
                   f'{hex_x - hex_r // 2},{hex_y + h87} {hex_x - hex_r},{hex_y} '
                   f'{hex_x - hex_r // 2},{hex_y - h87} {hex_x + hex_r // 2},{hex_y - h87}')
            elements.append(
                f'<polygon points="{pts}" fill="none" '
                f'stroke="{accent}" stroke-width="1" opacity="0.{opacity}"/>'
            )
        return '\n'.join(elements)

    def draw_thriller_pattern():
        elements = []
        num_lines = prng(0, 10, 20)
        for i in range(num_lines):
            x1 = prng(i * 2, 0, 1600)
            y1 = prng(i * 2 + 1, 0, 2400)
            ln = prng(i * 2 + 6, 200, 800)
            angle = prng(i * 2 + 8, 20, 70)
            x2 = x1 + ln
            y2 = y1 + ln * angle // 45
            sw = prng(i * 2 + 10, 1, 4)
            opacity = prng100(i * 2 + 12, 8, 30)
            elements.append(
                f'<line x1="{x1}" y1="{y1}" x2="{x2}" y2="{y2}" '
                f'stroke="{accent}" stroke-width="{sw}" opacity="0.{opacity}"/>'
            )
        num_rects = prng(14, 4, 8)
        for i in range(num_rects):
            x = prng(i * 3, 50, 1400)
            y = prng(i * 3 + 1, 50, 2200)
            w = prng(i * 3 + 2, 40, 200)
            h = prng(i * 3 + 4, 40, 200)
            opacity = prng100(i * 3 + 6, 5, 20)
            rotation = prng(i * 3 + 8, -15, 15)
            elements.append(
                f'<rect x="{x}" y="{y}" width="{w}" height="{h}" '
                f'fill="none" stroke="{accent}" stroke-width="1" opacity="0.{opacity}" '
                f'transform="rotate({rotation} {x + w // 2} {y + h // 2})"/>'
            )
        return '\n'.join(elements)

    def draw_romance_pattern():
        elements = []
        num_curves = prng(0, 5, 10)
        for i in range(num_curves):
            x1 = prng(i * 4, 0, 1600)
            y1 = prng(i * 4 + 1, 0, 2400)
            cx1 = prng(i * 4 + 2, 0, 1600)
            cy1 = prng(i * 4 + 3, 0, 2400)
            cx2 = prng((i * 4 + 4) % 30, 0, 1600)
            cy2 = prng((i * 4 + 5) % 30, 0, 2400)
            x2 = prng((i * 4 + 6) % 30, 0, 1600)
            y2 = prng((i * 4 + 7) % 30, 0, 2400)
            sw = prng((i * 4 + 8) % 30, 1, 3)
            opacity = prng100((i * 4 + 9) % 30, 10, 30)
            elements.append(
                f'<path d="M{x1},{y1} C{cx1},{cy1} {cx2},{cy2} {x2},{y2}" '
                f'fill="none" stroke="{accent}" stroke-width="{sw}" opacity="0.{opacity}"/>'
            )
        num_circles = prng(10, 6, 12)
        for i in range(num_circles):
            cx = prng((i * 2 + 12) % 30, 200, 1400)
            cy = prng((i * 2 + 13) % 30, 300, 2100)
            r = prng((i * 2 + 14) % 30, 80, 300)
            opacity = prng100((i * 2 + 16) % 30, 3, 15)
            elements.append(
                f'<circle cx="{cx}" cy="{cy}" r="{r}" fill="none" '
                f'stroke="{accent}" stroke-width="1" opacity="0.{opacity}"/>'
            )
        return '\n'.join(elements)

    def draw_literary_pattern():
        elements = []
        num_lines = prng(0, 3, 6)
        for i in range(num_lines):
            x1 = prng(i * 3, 200, 1400)
            y1 = prng(i * 3 + 1, 400, 2000)
            x2 = prng(i * 3 + 2, 200, 1400)
            y2 = y1 + prng(i * 3 + 4, 100, 400)
            opacity = prng100(i * 3 + 6, 8, 20)
            elements.append(
                f'<line x1="{x1}" y1="{y1}" x2="{x2}" y2="{y2}" '
                f'stroke="{accent}" stroke-width="0.5" opacity="0.{opacity}"/>'
            )
        num_dots = prng(8, 20, 50)
        for i in range(num_dots):
            x = prng(i % 30, 100, 1500)
            y = prng((i + 15) % 30, 100, 2300)
            r = prng((i + 7) % 30, 1, 3)
            opacity = prng100((i + 3) % 30, 5, 15)
            elements.append(
                f'<circle cx="{x}" cy="{y}" r="{r}" fill="{accent}" '
                f'opacity="0.{opacity}"/>'
            )
        return '\n'.join(elements)

    def draw_default_pattern():
        elements = []
        num_shapes = prng(0, 8, 14)
        for i in range(num_shapes):
            shape_type = prng(i * 3, 0, 2)
            x = prng(i * 3 + 1, 100, 1500)
            y = prng(i * 3 + 2, 100, 2300)
            size = prng((i * 3 + 4) % 30, 40, 200)
            opacity = prng100((i * 3 + 6) % 30, 8, 25)
            if shape_type == 0:
                elements.append(
                    f'<circle cx="{x}" cy="{y}" r="{size}" fill="none" '
                    f'stroke="{accent}" stroke-width="1" opacity="0.{opacity}"/>'
                )
            elif shape_type == 1:
                elements.append(
                    f'<rect x="{x - size // 2}" y="{y - size // 2}" '
                    f'width="{size}" height="{size}" fill="none" '
                    f'stroke="{accent}" stroke-width="1" opacity="0.{opacity}"/>'
                )
            else:
                x2 = x + prng((i * 3 + 8) % 30, -300, 300)
                y2 = y + prng((i * 3 + 10) % 30, -300, 300)
                elements.append(
                    f'<line x1="{x}" y1="{y}" x2="{x2}" y2="{y2}" '
                    f'stroke="{accent}" stroke-width="1" opacity="0.{opacity}"/>'
                )
        return '\n'.join(elements)

    # --- Select pattern by genre ---
    pattern_map = {
        'fantasy': draw_fantasy_pattern,
        'epic-fantasy': draw_fantasy_pattern,
        'urban-fantasy': draw_fantasy_pattern,
        'dark-fantasy': draw_fantasy_pattern,
        'science-fiction': draw_scifi_pattern,
        'sci-fi': draw_scifi_pattern,
        'cyberpunk': draw_scifi_pattern,
        'space-opera': draw_scifi_pattern,
        'thriller': draw_thriller_pattern,
        'suspense': draw_thriller_pattern,
        'mystery': draw_thriller_pattern,
        'crime': draw_thriller_pattern,
        'romance': draw_romance_pattern,
        'contemporary-romance': draw_romance_pattern,
        'historical-romance': draw_romance_pattern,
        'literary-fiction': draw_literary_pattern,
        'literary': draw_literary_pattern,
        'upmarket': draw_literary_pattern,
    }
    draw_fn = pattern_map.get(genre_lc, draw_default_pattern)
    pattern = draw_fn()

    # --- Text sizing ---
    title_size = _compute_title_size(title)
    max_chars = _max_chars_for_size(title_size)
    title_lines = wrap_title_for_svg(title, max_chars)

    title_block_height = len(title_lines) * (title_size + 20)
    title_y = 600 - title_block_height // 2

    # Build title SVG
    title_parts = []
    for i, line in enumerate(title_lines):
        line_y = title_y + i * (title_size + 20)
        escaped = _escape_xml(line)
        title_parts.append(
            f'  <text x="800" y="{line_y}" text-anchor="middle" '
            f'font-family="Georgia, \'Palatino Linotype\', \'Book Antiqua\', serif" '
            f'font-size="{title_size}" font-weight="bold" '
            f'fill="{text_color}" letter-spacing="2">{escaped}</text>'
        )
    title_svg = '\n'.join(title_parts)

    # Subtitle
    subtitle_svg = ''
    if subtitle:
        sub_y = title_y + title_block_height + 40
        escaped = _escape_xml(subtitle)
        subtitle_svg = (
            f'  <text x="800" y="{sub_y}" text-anchor="middle" '
            f'font-family="Georgia, \'Palatino Linotype\', serif" '
            f'font-size="32" font-weight="normal" font-style="italic" '
            f'fill="{text_dim}">{escaped}</text>'
        )

    # Decorative rule
    rule_y = title_y + title_block_height + 100
    rule_svg = (
        f'  <line x1="650" y1="{rule_y}" x2="950" y2="{rule_y}" '
        f'stroke="{accent}" stroke-width="1" opacity="0.4"/>'
    )

    # Author
    author_svg = ''
    if author:
        escaped = _escape_xml(author)
        author_svg = (
            f'  <text x="800" y="2100" text-anchor="middle" '
            f'font-family="Georgia, \'Palatino Linotype\', serif" '
            f'font-size="40" font-weight="normal" '
            f'fill="{text_color}" letter-spacing="6">{escaped}</text>'
        )

    # Series badge
    series_svg = ''
    if series_name:
        series_text = series_name
        if series_pos:
            series_text += f' \u00b7 Book {series_pos}'
        escaped = _escape_xml(series_text)
        series_svg = (
            f'  <text x="800" y="2200" text-anchor="middle" '
            f'font-family="\'Courier New\', monospace" '
            f'font-size="22" font-weight="normal" '
            f'fill="{text_dim}" letter-spacing="4">{escaped}</text>'
        )

    # --- Assemble SVG ---
    svg = f'''<svg xmlns="http://www.w3.org/2000/svg" width="1600" height="2400" viewBox="0 0 1600 2400">
  <!-- Background -->
  <defs>
    <linearGradient id="bg-grad" x1="0" y1="0" x2="0" y2="1">
      <stop offset="0%" stop-color="{bg_color}"/>
      <stop offset="100%" stop-color="{bg_color2}"/>
    </linearGradient>
  </defs>
  <rect width="1600" height="2400" fill="url(#bg-grad)"/>

  <!-- Generated pattern -->
  <g class="pattern">
{pattern}
  </g>

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

    # --- Write SVG ---
    os.makedirs(os.path.dirname(svg_file) or '.', exist_ok=True)

    log('Generating cover...')
    log(f'  Title:  {title}')
    log(f'  Genre:  {genre} -> {genre_lc} palette')
    if author:
        log(f'  Author: {author}')

    with open(svg_file, 'w') as f:
        f.write(svg)
    log(f'SVG saved: {svg_file}')

    if args.svg_only:
        log('Done (SVG only). Open in browser to preview.')
        sys.exit(0)

    # --- Convert to PNG ---
    png_converted = False

    if shutil.which('rsvg-convert'):
        log('Converting to PNG via rsvg-convert...')
        subprocess.run(
            ['rsvg-convert', '-w', '1600', '-h', '2400', '-o', png_file, svg_file],
            check=True,
        )
        png_converted = True
    elif shutil.which('sips'):
        log('Converting to PNG via sips...')
        subprocess.run(
            ['sips', '-s', 'format', 'png', svg_file, '--out', png_file],
            capture_output=True,
        )
        png_converted = True

    if png_converted and os.path.isfile(png_file):
        file_size = os.path.getsize(png_file)
        log(f'PNG saved: {png_file} ({file_size // 1024}KB)')
    else:
        log('WARNING: PNG conversion not available. Install librsvg (brew install librsvg) for best results.')
        log(f'SVG cover is at: {svg_file}')
        png_file = svg_file

    log('Cover generation complete.')
