"""Scene setup utilities — parsing, splitting, renaming, CSV generation.

Replaces the data-heavy functions from ``scripts/storyforge-scenes-setup``
(1307 lines, 33 sed calls) with clean Python equivalents. The bash script
handles file operations, git, and Claude invocations; this module provides
the parsing and data-transformation layer.
"""

import json
import os
import re
import sys


# ============================================================================
# Slug generation
# ============================================================================

def generate_slug(title: str) -> str:
    """Convert a scene title to a filename-safe slug.

    Matches the bash ``slugify()`` function exactly:
    lowercase, spaces to hyphens, strip special chars, collapse hyphens,
    strip leading ``the-``, truncate to 50 chars.

    Args:
        title: Human-readable scene title.

    Returns:
        A slug suitable for use as a scene filename (without extension).
    """
    slug = title.lower()

    # Replace em-dashes, en-dashes with hyphens; remove ellipses
    slug = slug.replace('\u2014', '-').replace('\u2013', '-')
    slug = slug.replace('...', '')

    # Remove special chars: quotes, colons, parentheses, commas, periods,
    # semicolons, exclamation, question marks, backticks
    slug = re.sub(r'''["'`():;,.!?]''', '', slug)

    # Replace spaces, underscores, and slashes with hyphens
    slug = re.sub(r'[\s_/]', '-', slug)

    # Remove any remaining non-alphanumeric chars except hyphens
    slug = re.sub(r'[^a-z0-9-]', '', slug)

    # Collapse multiple hyphens
    slug = re.sub(r'-{2,}', '-', slug)

    # Strip leading/trailing hyphens
    slug = slug.strip('-')

    # Strip leading "the-"
    if slug.startswith('the-'):
        slug = slug[4:]

    # Truncate to 50 chars and strip any trailing hyphen after truncation
    slug = slug[:50].rstrip('-')

    return slug


def unique_slug(base_slug: str, used: set[str]) -> str:
    """Return a unique slug, appending ``-2``, ``-3``, etc. if needed.

    The *used* set is updated in-place with the returned slug.

    Args:
        base_slug: The desired slug.
        used: Set of slugs already in use.

    Returns:
        A slug guaranteed not to collide with *used*.
    """
    candidate = base_slug
    counter = 2
    while candidate in used:
        candidate = f'{base_slug}-{counter}'
        counter += 1
    used.add(candidate)
    return candidate


# ============================================================================
# Scene boundary response parsing
# ============================================================================

def parse_scene_boundaries(response: str) -> list[dict]:
    """Parse Claude's scene-boundary detection response.

    Expects lines of the form::

        SCENE: <line_number> | <suggested_title> | <brief_reason>

    The parser is forgiving of whitespace and minor formatting variations
    (e.g. missing reason, extra spaces around pipes).

    Args:
        response: The full text response from Claude.

    Returns:
        List of dicts with keys ``line_number`` (int), ``title`` (str),
        and ``description`` (str).  Sorted by line_number ascending.
    """
    scenes: list[dict] = []

    for line in response.splitlines():
        line = line.strip()
        if not line.upper().startswith('SCENE:'):
            continue

        # Strip the SCENE: prefix (case-insensitive)
        raw = re.sub(r'^SCENE:\s*', '', line, flags=re.IGNORECASE)
        parts = raw.split('|')

        line_num_str = parts[0].strip() if parts else ''
        # Accept only valid integers
        if not re.fullmatch(r'\d+', line_num_str):
            continue

        title = parts[1].strip() if len(parts) > 1 else ''
        description = '|'.join(parts[2:]).strip() if len(parts) > 2 else ''

        scenes.append({
            'line_number': int(line_num_str),
            'title': title,
            'description': description,
        })

    scenes.sort(key=lambda s: s['line_number'])
    return scenes


# ============================================================================
# CSV generation
# ============================================================================

_METADATA_HEADER = 'id|seq|title|pov|setting|part|type|timeline_day|time_of_day|status|word_count|target_words'
_INTENT_HEADER = 'id|function|emotional_arc|characters|threads|motifs|notes'


def generate_metadata_rows(scenes: list[dict],
                           part_num: int | None = None,
                           seq_start: int = 1) -> list[str]:
    """Generate pipe-delimited CSV rows for ``scene-metadata.csv``.

    Each row uses the header order:
    ``id|seq|title|pov|setting|part|type|timeline_day|time_of_day|status|word_count|target_words``

    The scene dicts must have at least ``title`` (str).  They may
    optionally include ``word_count`` (int) and ``slug`` (str).  If
    ``slug`` is absent it is derived from ``title`` via
    :func:`generate_slug`.

    Args:
        scenes: Scene dicts as returned by :func:`parse_scene_boundaries`
            (or any list of dicts with a ``title`` key).
        part_num: Optional part/act number to fill the ``part`` column.
        seq_start: Starting sequence number (default 1).

    Returns:
        List of pipe-delimited row strings (no header row included).
    """
    rows: list[str] = []
    used_slugs: set[str] = set()

    for i, scene in enumerate(scenes):
        title = scene.get('title', '')
        slug = scene.get('slug', '') or generate_slug(title)
        if not slug:
            slug = f'scene-{seq_start + i}'
        slug = unique_slug(slug, used_slugs)

        seq = seq_start + i
        part = str(part_num) if part_num is not None else ''
        word_count = str(scene.get('word_count', ''))

        row = f'{slug}|{seq}|{title}|||{part}|||||{word_count}|'
        rows.append(row)

    return rows


def generate_intent_rows(scenes: list[dict]) -> list[str]:
    """Generate pipe-delimited CSV rows for ``scene-intent.csv``.

    Each row uses the header order:
    ``id|function|emotional_arc|characters|threads|motifs|notes``

    Args:
        scenes: Scene dicts (must have at least ``title``; ``slug`` is
            optional and derived if absent).

    Returns:
        List of pipe-delimited row strings (no header row included).
    """
    rows: list[str] = []
    used_slugs: set[str] = set()

    for scene in scenes:
        title = scene.get('title', '')
        slug = scene.get('slug', '') or generate_slug(title)
        if not slug:
            slug = f'scene-unknown'
        slug = unique_slug(slug, used_slugs)

        row = f'{slug}||||||'
        rows.append(row)

    return rows


def metadata_header() -> str:
    """Return the canonical metadata CSV header line."""
    return _METADATA_HEADER


def intent_header() -> str:
    """Return the canonical intent CSV header line."""
    return _INTENT_HEADER


# ============================================================================
# Manuscript / chapter splitting
# ============================================================================

def split_by_scene_markers(text: str,
                           markers: list[dict]) -> dict[str, str]:
    """Split full text into scene content by boundary markers.

    Args:
        text: The full chapter or manuscript text.
        markers: List of dicts with ``line_number`` (int, 1-indexed) and
            ``title`` (str).  Must be sorted by ``line_number``.

    Returns:
        Ordered dict of ``scene_slug -> prose`` for each marker.
        Scene break decoration lines (``***``, ``---``, ``# # #``,
        ``* * *``) are stripped from the prose.
    """
    lines = text.splitlines(keepends=True)
    total = len(lines)
    result: dict[str, str] = {}
    used_slugs: set[str] = set()

    # Sort markers by line_number to be safe
    sorted_markers = sorted(markers, key=lambda m: m['line_number'])

    for i, marker in enumerate(sorted_markers):
        start = marker['line_number'] - 1  # 0-indexed
        if start < 0:
            start = 0
        if start >= total:
            start = total - 1

        if i + 1 < len(sorted_markers):
            end = sorted_markers[i + 1]['line_number'] - 1  # exclusive
        else:
            end = total

        segment_lines = lines[start:end]

        # Strip scene break markers
        cleaned = []
        for ln in segment_lines:
            stripped = ln.strip()
            if stripped in ('***', '---', '# # #', '* * *'):
                continue
            cleaned.append(ln)

        # Trim leading blank lines
        while cleaned and not cleaned[0].strip():
            cleaned.pop(0)

        prose = ''.join(cleaned).rstrip('\n') + '\n'

        title = marker.get('title', '') or f'scene-{i + 1}'
        slug = generate_slug(title)
        if not slug:
            slug = f'scene-{i + 1}'
        slug = unique_slug(slug, used_slugs)

        result[slug] = prose

    return result


# ============================================================================
# File rename planning
# ============================================================================

def generate_rename_plan(scenes_dir: str,
                         metadata_csv: str) -> list[tuple[str, str]]:
    """Compare scene filenames against metadata CSV and plan renames.

    Reads the metadata CSV to find the ``title`` for each scene ID, then
    generates a slug from that title.  If the slug differs from the
    current filename (the ``id`` column), a rename entry is produced.

    Handles numeric-to-slug conversion (e.g. ``001.md`` -> ``finest-cartographer.md``).

    Args:
        scenes_dir: Path to the ``scenes/`` directory.
        metadata_csv: Path to ``reference/scene-metadata.csv``.

    Returns:
        List of ``(old_path, new_path)`` tuples for files that need
        renaming.  Paths are absolute.
    """
    if not os.path.isfile(metadata_csv):
        return []

    # Read the CSV
    with open(metadata_csv) as f:
        csv_lines = [l.rstrip('\n') for l in f if l.strip()]

    if not csv_lines:
        return []

    header = csv_lines[0].split('|')
    try:
        id_idx = header.index('id')
        title_idx = header.index('title')
    except ValueError:
        return []

    # Build id -> title map from CSV
    id_title: dict[str, str] = {}
    for line in csv_lines[1:]:
        cols = line.split('|')
        if len(cols) > max(id_idx, title_idx):
            scene_id = cols[id_idx]
            title = cols[title_idx]
            if scene_id:
                id_title[scene_id] = title

    # Collect existing scene files
    if not os.path.isdir(scenes_dir):
        return []

    existing_files = sorted(
        f for f in os.listdir(scenes_dir) if f.endswith('.md')
    )

    renames: list[tuple[str, str]] = []
    used_slugs: set[str] = set()

    for filename in existing_files:
        old_id = filename[:-3]  # strip .md

        # Get title from CSV; fall back to extracting from file content
        title = id_title.get(old_id, '')
        if not title:
            # Try reading first heading from the file
            filepath = os.path.join(scenes_dir, filename)
            title = _title_from_file(filepath)

        new_slug = generate_slug(title) if title else generate_slug(old_id)
        if not new_slug:
            new_slug = old_id

        new_slug = unique_slug(new_slug, used_slugs)

        if old_id != new_slug:
            old_path = os.path.join(scenes_dir, f'{old_id}.md')
            new_path = os.path.join(scenes_dir, f'{new_slug}.md')
            renames.append((old_path, new_path))

    return renames


def _title_from_file(filepath: str) -> str:
    """Derive a title from the first heading or first non-empty line."""
    try:
        with open(filepath) as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                if line.startswith('#'):
                    return re.sub(r'^#+\s*', '', line)
                return line[:80]
    except OSError:
        pass
    return ''


# ============================================================================
# Scene boundary detection prompt
# ============================================================================

def build_boundary_prompt(chapter_text: str) -> str:
    """Build a prompt for Claude to detect scene boundaries in a chapter.

    Args:
        chapter_text: The full text of a chapter.

    Returns:
        The assembled prompt string.
    """
    return f"""You are identifying scene boundaries in a chapter of a novel.

A scene is a continuous unit of action in one time and place. A new scene begins when there is a significant shift in:
- Time (hours or days pass)
- Setting/location (characters move to a new place)
- Point of view (the perspective character changes)
- Narrative focus (a distinct new dramatic situation begins)

Minor transitions within the same time/place/focus are NOT scene breaks.

## Chapter Text

{chapter_text}

## Instructions

Identify where each scene begins. For each scene boundary (including the very start of the chapter), output one line:

SCENE: <line_number> | <suggested_title> | <brief_reason>

Where line_number is the line in the chapter text where this scene begins (1-indexed).
The first scene always starts at line 1.

Output ONLY SCENE: lines, nothing else."""


# ============================================================================
# CLI interface
# ============================================================================

def main():
    """CLI entry point.

    Usage::

        python3 -m storyforge.scenes parse-boundaries <response_file>
        python3 -m storyforge.scenes generate-slug <title>
        python3 -m storyforge.scenes split-text <text_file> <markers_json> <output_dir>
        python3 -m storyforge.scenes rename-plan <scenes_dir> <metadata_csv>
        python3 -m storyforge.scenes metadata-rows <boundaries_json> [--part N] [--seq-start N]
        python3 -m storyforge.scenes intent-rows <boundaries_json>
    """
    if len(sys.argv) < 2:
        print('Usage: python3 -m storyforge.scenes <command> [args]',
              file=sys.stderr)
        sys.exit(1)

    command = sys.argv[1]

    if command == 'parse-boundaries':
        if len(sys.argv) < 3:
            print('Usage: parse-boundaries <response_file>',
                  file=sys.stderr)
            sys.exit(1)
        response_file = sys.argv[2]
        with open(response_file) as f:
            response = f.read()
        scenes = parse_scene_boundaries(response)
        print(json.dumps(scenes, indent=2))

    elif command == 'generate-slug':
        if len(sys.argv) < 3:
            print('Usage: generate-slug <title>', file=sys.stderr)
            sys.exit(1)
        title = ' '.join(sys.argv[2:])
        print(generate_slug(title))

    elif command == 'split-text':
        if len(sys.argv) < 5:
            print('Usage: split-text <text_file> <markers_json> <output_dir>',
                  file=sys.stderr)
            sys.exit(1)
        text_file = sys.argv[2]
        markers_file = sys.argv[3]
        output_dir = sys.argv[4]

        with open(text_file) as f:
            text = f.read()
        with open(markers_file) as f:
            markers = json.load(f)

        result = split_by_scene_markers(text, markers)

        os.makedirs(output_dir, exist_ok=True)
        for slug, prose in result.items():
            out_path = os.path.join(output_dir, f'{slug}.md')
            with open(out_path, 'w') as f:
                f.write(prose)
            print(f'{slug}.md ({len(prose.split())} words)')

    elif command == 'rename-plan':
        if len(sys.argv) < 4:
            print('Usage: rename-plan <scenes_dir> <metadata_csv>',
                  file=sys.stderr)
            sys.exit(1)
        scenes_dir = sys.argv[2]
        metadata_csv = sys.argv[3]
        plan = generate_rename_plan(scenes_dir, metadata_csv)
        for old_path, new_path in plan:
            old_name = os.path.basename(old_path)
            new_name = os.path.basename(new_path)
            print(f'{old_name} -> {new_name}')

    elif command == 'metadata-rows':
        if len(sys.argv) < 3:
            print('Usage: metadata-rows <boundaries_json> [--part N] [--seq-start N]',
                  file=sys.stderr)
            sys.exit(1)
        with open(sys.argv[2]) as f:
            scenes = json.load(f)

        part_num = None
        seq_start = 1
        i = 3
        while i < len(sys.argv):
            if sys.argv[i] == '--part' and i + 1 < len(sys.argv):
                part_num = int(sys.argv[i + 1])
                i += 2
            elif sys.argv[i] == '--seq-start' and i + 1 < len(sys.argv):
                seq_start = int(sys.argv[i + 1])
                i += 2
            else:
                i += 1

        rows = generate_metadata_rows(scenes, part_num=part_num,
                                       seq_start=seq_start)
        for row in rows:
            print(row)

    elif command == 'intent-rows':
        if len(sys.argv) < 3:
            print('Usage: intent-rows <boundaries_json>', file=sys.stderr)
            sys.exit(1)
        with open(sys.argv[2]) as f:
            scenes = json.load(f)
        rows = generate_intent_rows(scenes)
        for row in rows:
            print(row)

    elif command == 'build-boundary-prompt':
        # Build scene boundary detection prompt from chapter text
        # Usage: build-boundary-prompt <chapter_file>
        if len(sys.argv) < 3:
            print('Usage: build-boundary-prompt <chapter_file>',
                  file=sys.stderr)
            sys.exit(1)
        with open(sys.argv[2]) as f:
            chapter_text = f.read()
        print(build_boundary_prompt(chapter_text))

    else:
        print(f'Unknown command: {command}', file=sys.stderr)
        sys.exit(1)


if __name__ == '__main__':
    main()
