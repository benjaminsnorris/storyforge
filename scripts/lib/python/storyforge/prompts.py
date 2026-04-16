"""Prompt building for scene drafting.

Replaces scripts/lib/prompt-builder.sh — assembles the complete drafting
prompt from project metadata, scene CSVs, craft weights, and reference
files. Produces prompts suitable for both ``claude -p`` (file-path
references) and the direct Anthropic API (inlined file contents).
"""

import os
import re
import sys


# ============================================================================
# YAML reading (no PyYAML — mirrors the grep/sed approach in common.sh)
# ============================================================================

def read_yaml_field(yaml_file: str, field: str) -> str:
    """Read a value from a YAML file using simple regex parsing.

    Supports flat keys (``title``) and one-level dotted keys
    (``project.title``). Strips surrounding quotes.

    Args:
        yaml_file: Path to the YAML file.
        field: Key name, optionally dotted (``parent.child``).

    Returns:
        The value as a string, or empty string if not found.
    """
    if not os.path.isfile(yaml_file):
        return ''

    with open(yaml_file) as f:
        lines = f.readlines()

    if '.' in field:
        parent, child = field.split('.', 1)
        in_parent = False
        for line in lines:
            if re.match(rf'^{re.escape(parent)}:', line):
                in_parent = True
                continue
            if in_parent:
                # End of parent block: next top-level key
                if line and not line[0].isspace() and line[0] != '#':
                    break
                m = re.match(rf'^\s+{re.escape(child)}:\s*(.*)', line)
                if m:
                    return _strip_yaml_value(m.group(1))
    else:
        for line in lines:
            m = re.match(rf'^{re.escape(field)}:\s*(.*)', line)
            if m:
                return _strip_yaml_value(m.group(1))

    return ''


def _strip_yaml_value(raw: str) -> str:
    """Strip surrounding quotes and trailing whitespace from a YAML value."""
    val = raw.strip()
    if len(val) >= 2 and val[0] in ('"', "'") and val[-1] == val[0]:
        val = val[1:-1]
    return val


# ============================================================================
# AI-tell word list
# ============================================================================

def load_ai_tell_words(plugin_dir: str) -> list[dict[str, str]]:
    """Load the AI-tell word list from references/ai-tell-words.csv.

    Args:
        plugin_dir: Path to the Storyforge plugin root.

    Returns:
        List of dicts with keys: word, category, severity, replacement_hint.
        Empty list if file not found.
    """
    path = os.path.join(plugin_dir, 'references', 'ai-tell-words.csv')
    if not os.path.isfile(path):
        return []

    with open(path, encoding='utf-8') as f:
        raw = f.read().replace('\r\n', '\n').replace('\r', '')

    lines = [l for l in raw.splitlines() if l.strip()]
    if len(lines) < 2:
        return []

    header = lines[0].split('|')
    result = []
    for line in lines[1:]:
        fields = line.split('|')
        entry = {header[i]: (fields[i] if i < len(fields) else '')
                 for i in range(len(header))}
        result.append(entry)
    return result


def build_ai_tell_constraint(words: list[dict[str, str]],
                              severity: str = 'high') -> str:
    """Build a constraint block listing words to avoid.

    Args:
        words: Output of load_ai_tell_words().
        severity: Minimum severity to include ('high' = high only,
                  'medium' = both high and medium).

    Returns:
        Formatted constraint text for prompt injection.
    """
    if not words:
        return ''

    include = {'high'}
    if severity == 'medium':
        include.add('medium')

    filtered = [w['word'] for w in words if w.get('severity') in include]
    if not filtered:
        return ''

    word_list = ', '.join(filtered)
    return (
        'VOCABULARY CONSTRAINT: Do not use these words or phrases — they signal '
        'AI-generated prose and must be avoided entirely:\n'
        f'{word_list}\n'
        'Replace with concrete, specific words grounded in the scene and character.'
    )


# ============================================================================
# Voice profile
# ============================================================================

def load_voice_profile(project_dir: str) -> tuple[dict[str, str], dict[str, dict[str, str]]]:
    """Load the voice profile from reference/voice-profile.csv.

    Args:
        project_dir: Path to the book project root.

    Returns:
        Tuple of (project_data, character_data).
        project_data: dict of field -> value for the _project row.
        character_data: dict of character_id -> {field: value}.
        Both empty dicts if file not found.
    """
    path = os.path.join(project_dir, 'reference', 'voice-profile.csv')
    if not os.path.isfile(path):
        return {}, {}

    with open(path, encoding='utf-8') as f:
        raw = f.read().replace('\r\n', '\n').replace('\r', '')

    lines = [l for l in raw.splitlines() if l.strip()]
    if len(lines) < 2:
        return {}, {}

    header = lines[0].split('|')
    project_data = {}
    character_data = {}

    for line in lines[1:]:
        fields = line.split('|')
        row = {header[i]: (fields[i] if i < len(fields) else '')
               for i in range(len(header))}

        char_id = row.get('character', '').strip()
        if char_id == '_project':
            project_data = {k: v for k, v in row.items() if k != 'character' and v.strip()}
        elif char_id:
            character_data[char_id] = {k: v for k, v in row.items()
                                        if k != 'character' and v.strip()}

    return project_data, character_data


def merge_banned_words(project_profile: dict[str, str],
                       ai_tell_words: list[dict[str, str]]) -> list[str]:
    """Merge project-level banned words with universal AI-tell high-severity words.

    Args:
        project_profile: Project-level voice profile data (from load_voice_profile).
        ai_tell_words: Output of load_ai_tell_words().

    Returns:
        Deduplicated sorted list of banned words.
    """
    banned = set()

    # Project-level banned words
    project_banned = project_profile.get('banned_words', '')
    if project_banned:
        for w in project_banned.split(';'):
            w = w.strip()
            if w:
                banned.add(w)

    # Universal high-severity AI-tell words
    for entry in ai_tell_words:
        if entry.get('severity') == 'high':
            banned.add(entry['word'])

    return sorted(banned)


# ============================================================================
# CSV helpers (pipe-delimited)
# ============================================================================

def _read_csv_header_and_rows(csv_file: str) -> tuple[list[str], list[list[str]]]:
    """Read a pipe-delimited CSV, returning (header_fields, data_rows).

    Strips ``\\r`` so CRLF line endings and stray carriage returns embedded
    by awk-based CSV edits never propagate into field values.
    """
    with open(csv_file, newline='', encoding='utf-8') as f:
        raw = f.read().replace('\r\n', '\n').replace('\r', '')
    lines = [l for l in raw.splitlines() if l.strip()]

    if not lines:
        return [], []

    header = lines[0].split('|')
    rows = [line.split('|') for line in lines[1:]]
    return header, rows


def read_csv_field(csv_file: str, row_id: str, field: str,
                   key_column: str = 'id') -> str:
    """Read a single cell from a pipe-delimited CSV.

    Args:
        csv_file: Path to the CSV file.
        row_id: Value to match in the key column.
        field: Column name to return.
        key_column: Column used to locate the row (default ``id``).

    Returns:
        The cell value, or empty string if not found.
    """
    if not os.path.isfile(csv_file):
        return ''

    header, rows = _read_csv_header_and_rows(csv_file)
    if not header:
        return ''

    try:
        key_idx = header.index(key_column)
        field_idx = header.index(field)
    except ValueError:
        return ''

    for row in rows:
        if len(row) > key_idx and row[key_idx] == row_id:
            return row[field_idx] if len(row) > field_idx else ''

    return ''


def _get_csv_row_dict(csv_file: str, row_id: str,
                      key_column: str = 'id') -> dict[str, str]:
    """Return a row as a dict, or empty dict if not found."""
    if not os.path.isfile(csv_file):
        return {}

    header, rows = _read_csv_header_and_rows(csv_file)
    if not header:
        return {}

    try:
        key_idx = header.index(key_column)
    except ValueError:
        return {}

    for row in rows:
        if len(row) > key_idx and row[key_idx] == row_id:
            return {header[i]: (row[i] if i < len(row) else '')
                    for i in range(len(header))}

    return {}


# ============================================================================
# Scene metadata and intent
# ============================================================================

def _resolve_scenes_csv(project_dir: str) -> str:
    """Find the scenes CSV (structural identity)."""
    path = os.path.join(project_dir, 'reference', 'scenes.csv')
    if os.path.isfile(path):
        return path
    return ''


def _resolve_intent_csv(project_dir: str) -> str:
    """Find the scene-intent CSV."""
    path = os.path.join(project_dir, 'reference', 'scene-intent.csv')
    if os.path.isfile(path):
        return path
    return ''


def _resolve_briefs_csv(project_dir: str) -> str:
    """Find the scene-briefs CSV (drafting contracts)."""
    path = os.path.join(project_dir, 'reference', 'scene-briefs.csv')
    if os.path.isfile(path):
        return path
    return ''


def get_scene_metadata(scene_id: str, project_dir: str) -> str:
    """Read metadata for a scene from reference/scenes.csv.

    Args:
        scene_id: The scene identifier.
        project_dir: Root directory of the project.

    Returns:
        Formatted ``key: value`` pairs (one per line), or empty string.
    """
    csv_file = _resolve_scenes_csv(project_dir)
    if not csv_file:
        return ''

    row = _get_csv_row_dict(csv_file, scene_id)
    if not row:
        return ''

    # Preserve header order
    header, _ = _read_csv_header_and_rows(csv_file)
    parts = []
    for field in header:
        parts.append(f'{field}: {row.get(field, "")}')

    return '\n'.join(parts)


def get_scene_intent(scene_id: str, project_dir: str) -> str:
    """Read intent data for a scene from reference/scene-intent.csv.

    Args:
        scene_id: The scene identifier.
        project_dir: Root directory of the project.

    Returns:
        Formatted ``key: value`` pairs (skipping id and empty values),
        or empty string.
    """
    csv_file = _resolve_intent_csv(project_dir)
    if not csv_file:
        return ''

    row = _get_csv_row_dict(csv_file, scene_id)
    if not row:
        return ''

    header, _ = _read_csv_header_and_rows(csv_file)
    parts = []
    for field in header:
        if field == 'id':
            continue
        val = row.get(field, '')
        if val:
            parts.append(f'{field}: {val}')

    return '\n'.join(parts)


def get_previous_scene(scene_id: str, project_dir: str) -> str:
    """Find the previous scene ID by sequence order.

    Args:
        scene_id: The current scene identifier.
        project_dir: Root directory of the project.

    Returns:
        The previous scene's ID, or empty string if first or not found.
    """
    csv_file = _resolve_scenes_csv(project_dir)
    if not csv_file:
        return ''

    header, rows = _read_csv_header_and_rows(csv_file)
    if not header:
        return ''

    try:
        seq_idx = header.index('seq')
    except ValueError:
        return ''

    id_idx = 0  # id is always first column

    # Build (id, seq) pairs and sort by seq numerically
    pairs = []
    for row in rows:
        if len(row) > max(id_idx, seq_idx):
            try:
                seq_val = int(row[seq_idx]) if row[seq_idx] else 0
            except ValueError:
                seq_val = 0
            pairs.append((row[id_idx], seq_val))

    pairs.sort(key=lambda p: p[1])

    prev = ''
    for rid, _ in pairs:
        if rid == scene_id:
            return prev
        prev = rid

    return ''


# ============================================================================
# Reference files
# ============================================================================

def list_reference_files(project_dir: str) -> list[str]:
    """List reference files (*.md, *.csv, *.yaml, *.yml, *.txt) in reference/.

    Args:
        project_dir: Root directory of the project.

    Returns:
        Sorted list of paths relative to project_dir.
    """
    ref_dir = os.path.join(project_dir, 'reference')
    if not os.path.isdir(ref_dir):
        return []

    extensions = {'.md', '.csv', '.yaml', '.yml', '.txt'}
    result = []
    for root, _dirs, files in os.walk(ref_dir):
        for fname in files:
            if os.path.splitext(fname)[1] in extensions:
                full = os.path.join(root, fname)
                rel = os.path.relpath(full, project_dir)
                result.append(rel)

    result.sort()
    return result


# ============================================================================
# Scene status
# ============================================================================

def get_scene_status(scene_id: str, project_dir: str) -> str:
    """Get the status of a scene from metadata CSV.

    Checks CSV status field first. If no CSV status, checks if the scene
    file exists with substantial content (>100 words) and returns 'drafted'.
    Falls back to 'pending'.

    Args:
        scene_id: The scene identifier.
        project_dir: Root directory of the project.

    Returns:
        Status string: 'pending', 'drafted', 'revised', 'cut', etc.
    """
    csv_file = _resolve_scenes_csv(project_dir)
    if csv_file:
        csv_status = read_csv_field(csv_file, scene_id, 'status')
        if csv_status:
            return csv_status

    # If no CSV status, check if file exists with content
    scene_file = os.path.join(project_dir, 'scenes', f'{scene_id}.md')
    if os.path.isfile(scene_file):
        try:
            with open(scene_file) as f:
                content = f.read()
            word_count = len(content.split())
            if word_count > 100:
                return 'drafted'
        except OSError:
            pass

    return 'pending'


# ============================================================================
# Craft weights / directives
# ============================================================================

def build_weighted_directive(project_dir: str) -> str:
    """Build a weighted summary of craft principles for prompt injection.

    Reads ``working/craft-weights.csv`` and groups principles by
    effective weight into high-priority (>=7) and medium (4-6) tiers.

    Args:
        project_dir: Root directory of the project.

    Returns:
        Formatted markdown text, or empty string if no weights file.
    """
    weights_file = os.path.join(project_dir, 'working', 'craft-weights.csv')
    if not os.path.isfile(weights_file):
        return ''

    header, rows = _read_csv_header_and_rows(weights_file)
    if not header:
        return ''

    # Locate columns by name
    col = {name: i for i, name in enumerate(header)}
    principle_idx = col.get('principle')
    weight_idx = col.get('weight')
    author_weight_idx = col.get('author_weight')

    if principle_idx is None or weight_idx is None:
        return ''

    high = []
    medium = []
    for row in rows:
        principle = row[principle_idx] if len(row) > principle_idx else ''
        weight_str = row[weight_idx] if len(row) > weight_idx else '0'
        aw_str = ''
        if author_weight_idx is not None and len(row) > author_weight_idx:
            aw_str = row[author_weight_idx]

        try:
            eff_w = int(aw_str) if aw_str else int(weight_str)
        except ValueError:
            eff_w = 0

        display = principle.replace('_', ' ')
        if eff_w >= 7:
            high.append((display, eff_w))
        elif eff_w >= 4:
            medium.append(display)

    parts = ['## Craft Priorities', '']

    if high:
        parts.append('Pay particular attention to these principles:')
        parts.append('')
        for name, w in high:
            parts.append(f'- **{name}** (priority: {w}/10)')
        parts.append('')

    parts.append('Also maintain awareness of: ')
    parts.append(', '.join(medium))
    parts.append('')
    parts.append('Follow all craft principles, but weight your attention '
                 'toward the priorities listed above.')
    parts.append('')
    parts.append('### Prohibition Priorities (always enforced)')
    parts.append('')
    parts.append('- **no antithesis framing** — zero "Not X. It\'s Y." per scene')
    parts.append('- **no tricolon default** — lists of three only when necessary')
    parts.append('- **no summary closers** — end on action, image, or dialogue')
    parts.append('- **no doubled emotions** — state once at the right pitch')
    parts.append('- **motif scarcity** — recurring thematic words max once per scene')

    return '\n'.join(parts)


# ============================================================================
# Craft engine section extraction
# ============================================================================

def extract_craft_sections(plugin_dir: str, *section_nums: int) -> str:
    """Extract numbered sections from the craft engine markdown.

    Sections are delimited by ``## N.`` headers. Multiple sections are
    joined with ``---`` dividers.

    Args:
        plugin_dir: Path to the storyforge plugin directory.
        *section_nums: Section numbers to extract (e.g. 2, 3, 5).

    Returns:
        Extracted text, or empty string if the file is missing.
    """
    craft_file = os.path.join(plugin_dir, 'references', 'craft-engine.md')
    if not os.path.isfile(craft_file):
        return ''

    with open(craft_file) as f:
        content = f.read()

    sections = []
    for num in section_nums:
        pattern = rf'^(## {num}\. .+?)(?=^## \d+\. |\Z)'
        m = re.search(pattern, content, re.MULTILINE | re.DOTALL)
        if m:
            sections.append(m.group(1).rstrip())

    return '\n\n---\n\n'.join(sections)


# ============================================================================
# Scene overrides
# ============================================================================

def _get_scene_overrides(scene_id: str, project_dir: str) -> str:
    """Read scene-specific overrides from the latest evaluation cycle."""
    overrides_file = os.path.join(project_dir, 'working', 'scores', 'latest',
                                  'overrides.csv')
    if not os.path.isfile(overrides_file):
        return ''

    header, rows = _read_csv_header_and_rows(overrides_file)
    if not header:
        return ''

    # Build dicts so we access columns by name, not position
    col_map = {name.strip(): i for i, name in enumerate(header)}
    id_idx = col_map.get('id')
    directive_idx = col_map.get('directive')
    if id_idx is None or directive_idx is None:
        return ''

    lines = []
    for row in rows:
        if row and len(row) > max(id_idx, directive_idx) \
                and row[id_idx].strip() == scene_id:
            lines.append(f'- {row[directive_idx].strip()}')

    return '\n'.join(lines)


# ============================================================================
# Main prompt builder
# ============================================================================

def build_scene_prompt(scene_id: str, project_dir: str,
                       coaching_level: str = 'full',
                       api_mode: bool = False,
                       system_context: bool = False) -> str:
    """Assemble the complete drafting prompt for a single scene.

    Args:
        scene_id: The scene identifier (e.g. ``the-finest-cartographer``).
        project_dir: Root directory of the novel project.
        coaching_level: One of ``full``, ``coach``, ``strict``.
        api_mode: When True, inline reference file contents directly into
            the prompt. When False, emit file paths for ``claude -p``.
        system_context: When True, shared reference material (reference files,
            craft engine, AI-tell vocabulary, voice profile) is provided via
            the API ``system`` parameter and should NOT be inlined in the
            user prompt. Project-specific weighted directives, scene briefs,
            and per-scene overrides are still included.

    Returns:
        The assembled prompt string.
    """
    yaml_file = os.path.join(project_dir, 'storyforge.yaml')

    # --- Project config ---
    title = read_yaml_field(yaml_file, 'project.title')
    if not title:
        title = read_yaml_field(yaml_file, 'title')

    genre = read_yaml_field(yaml_file, 'project.genre')
    if not genre:
        genre = read_yaml_field(yaml_file, 'genre')

    # --- Scene metadata ---
    csv_file = _resolve_scenes_csv(project_dir)
    scene_metadata = get_scene_metadata(scene_id, project_dir)

    scene_title = ''
    target_words = ''
    if csv_file:
        scene_title = read_csv_field(csv_file, scene_id, 'title')
        target_words = read_csv_field(csv_file, scene_id, 'target_words')
        if not target_words:
            target_words = read_csv_field(csv_file, scene_id, 'word_count')

    # --- Scene intent ---
    scene_intent = get_scene_intent(scene_id, project_dir)

    # --- Previous scene ---
    prev_scene = get_previous_scene(scene_id, project_dir)

    # --- Voice guide ---
    voice_guide = read_yaml_field(yaml_file, 'reference.voice_guide')
    if not voice_guide:
        voice_guide = read_yaml_field(yaml_file, 'voice_guide')
    if not voice_guide:
        if os.path.isfile(os.path.join(project_dir, 'reference', 'voice-guide.md')):
            voice_guide = 'reference/voice-guide.md'
        elif os.path.isfile(os.path.join(project_dir, 'reference', 'persistent-prompt.md')):
            voice_guide = 'reference/persistent-prompt.md'

    # --- Reference files ---
    ref_files = list_reference_files(project_dir)

    ref_list = ''
    ref_inline = ''
    if not system_context:
        for rf in ref_files:
            ref_list += f'\n- {rf}'
            if api_mode:
                full_path = os.path.join(project_dir, rf)
                if os.path.isfile(full_path):
                    with open(full_path) as f:
                        content = f.read()
                    ref_inline += f'\n=== FILE: {rf} ===\n{content}\n=== END FILE ===\n'

    # --- Previous scene content (API mode) ---
    prev_scene_content = ''
    if api_mode and prev_scene:
        prev_file = os.path.join(project_dir, 'scenes', f'{prev_scene}.md')
        if os.path.isfile(prev_file):
            with open(prev_file) as f:
                prev_scene_content = f.read()

    # --- Plugin root (used for craft engine fallback and word list) ---
    # __file__ is scripts/lib/python/storyforge/prompts.py — 5 levels to repo root
    plugin_dir = os.path.dirname(os.path.dirname(os.path.dirname(
        os.path.dirname(os.path.dirname(os.path.abspath(__file__))))))

    # --- Craft principles ---
    craft_sections = build_weighted_directive(project_dir)
    if not craft_sections and not system_context:
        # Fallback: extract from craft engine (skipped when system_context
        # provides the craft engine via the API system parameter)
        craft_sections = extract_craft_sections(plugin_dir, 2, 3, 4, 5)

    overrides = _get_scene_overrides(scene_id, project_dir)
    if overrides:
        craft_sections += f'\n\n## Scene-Specific Notes\n{overrides}'

    # --- AI-tell vocabulary constraint ---
    # When system_context is True, the AI-tell word list and voice profile
    # are provided in the system parameter — skip inlining them here.
    ai_tell_words = [] if system_context else load_ai_tell_words(plugin_dir)
    ai_tell_block = build_ai_tell_constraint(ai_tell_words)

    # --- Voice profile ---
    if system_context:
        voice_profile_project, voice_profile_chars = {}, {}
    else:
        voice_profile_project, voice_profile_chars = load_voice_profile(project_dir)
    pov_char = ''
    if csv_file:
        pov_char = read_csv_field(csv_file, scene_id, 'pov')

    # Merge banned words: project profile + universal AI-tell list
    if voice_profile_project or ai_tell_words:
        merged_banned = merge_banned_words(voice_profile_project, ai_tell_words)
        if merged_banned:
            banned_str = ', '.join(merged_banned)
            ai_tell_block = (
                'VOCABULARY CONSTRAINT: Do not use these words or phrases — they '
                'are banned for this project:\n'
                f'{banned_str}\n'
                'Replace with concrete, specific words grounded in the scene and character.'
            )

    # Character-specific constraints
    char_voice_block = ''
    if pov_char:
        # Normalize POV name to slug form for matching (e.g. "Dorren Hayle" -> "dorren-hayle")
        pov_slug = pov_char.lower().replace(' ', '-')
        char_key = pov_char if pov_char in voice_profile_chars else (
            pov_slug if pov_slug in voice_profile_chars else '')
        if char_key:
            char_data = voice_profile_chars[char_key]
            parts = []
            if char_data.get('preferred_words'):
                parts.append(f'Favor these words (they define this character\'s voice): '
                            f'{char_data["preferred_words"].replace(";", ", ")}')
            if char_data.get('metaphor_families'):
                parts.append(f'Source metaphors from: '
                            f'{char_data["metaphor_families"].replace(";", ", ")}')
            if char_data.get('rhythm_preference'):
                parts.append(f'Sentence rhythm: '
                            f'{char_data["rhythm_preference"].replace(";", ", ")}')
            if char_data.get('dialogue_style'):
                parts.append(f'Dialogue style: '
                            f'{char_data["dialogue_style"].replace(";", ", ")}')
            if parts:
                char_voice_block = (
                    f'CHARACTER VOICE ({pov_char}):\n' + '\n'.join(f'- {p}' for p in parts)
                )

    # --- Title line ---
    title_part = f'"{title}"' if title else '"Untitled"'
    scene_label = f'scene {scene_id}'
    if scene_title:
        scene_label += f' ("{scene_title}")'
    genre_part = f', a {genre}' if genre else ''

    lines = []
    lines.append(f'You are drafting {scene_label} of {title_part}{genre_part}. '
                 'Follow these steps exactly and completely. Do not skip any step.')
    lines.append('')

    # ===== STEP 1: REFERENCE MATERIALS =====
    lines.append('===== STEP 1: REFERENCE MATERIALS =====')
    if system_context:
        lines.append('')
        lines.append('Reference materials (world bible, character bible, voice guide, '
                     'story architecture, craft engine, vocabulary constraints) have '
                     'been provided in the system context. Internalize them before writing.')
    elif api_mode:
        lines.append('')
        lines.append('The following reference materials contain the world bible, '
                     'character bible, story architecture, timeline, and all '
                     'other reference material for the project. Internalize them '
                     'before writing.')
        lines.append('')
        lines.append(ref_inline)
    else:
        lines.append('')
        lines.append('Read every one of these files. Do not skip any:')
        lines.append(ref_list)
        lines.append('')
        lines.append('These files contain the world bible, character bible, '
                     'story architecture, timeline, and all other reference '
                     'material for the project. Internalize them before writing.')

    if voice_guide and not system_context:
        lines.append('')
        lines.append('Pay special attention to the voice guide — this is the '
                     'voice and style guide. Follow it exactly.')

    if craft_sections:
        lines.append('')
        lines.append('===== CRAFT PRINCIPLES =====')
        lines.append('')
        lines.append('The following craft principles govern how you write this '
                     'scene. Internalize them — do not recite them, embody them '
                     'in the prose.')
        lines.append('')
        lines.append(craft_sections)

    if ai_tell_block:
        lines.append('')
        lines.append('===== VOCABULARY CONSTRAINTS =====')
        lines.append('')
        lines.append(ai_tell_block)

    if char_voice_block:
        lines.append('')
        lines.append('===== CHARACTER VOICE =====')
        lines.append('')
        lines.append(char_voice_block)

    if voice_profile_project.get('register'):
        lines.append('')
        lines.append(f'PROSE REGISTER: {voice_profile_project["register"].replace(";", ", ")}')

    # ===== STEP 2: PREVIOUS SCENE =====
    lines.append('')
    lines.append('===== STEP 2: PREVIOUS SCENE =====')
    if prev_scene:
        if api_mode and prev_scene_content:
            lines.append('')
            lines.append(f'Here is the previous scene ({prev_scene}) — '
                         'understand where the story left off, the emotional '
                         'state, scene transitions, and narrative momentum:')
            lines.append('')
            lines.append(prev_scene_content)
        else:
            lines.append('')
            lines.append(f'Read scenes/{prev_scene}.md to understand where '
                         'the story left off — the emotional state, scene '
                         'transitions, and narrative momentum.')
    else:
        lines.append('')
        lines.append('This is the first scene. There is no previous scene to '
                     'read. Begin the story.')

    # ===== STEP 3: SCENE METADATA =====
    lines.append('')
    lines.append('===== STEP 3: SCENE METADATA =====')
    lines.append('')
    lines.append('Here is the metadata for the scene you are drafting:')
    lines.append('')
    lines.append(scene_metadata)

    if scene_intent:
        lines.append('')
        lines.append('Scene intent:')
        lines.append(scene_intent)

    if target_words:
        lines.append('')
        lines.append(f'Target word count: {target_words} words '
                     '(stay within ~500 words of this target).')

    lines.append('')

    # ===== Coaching-level-specific steps =====
    if coaching_level == 'coach':
        lines.extend(_build_coach_steps(scene_id, scene_title, api_mode))
    elif coaching_level == 'strict':
        lines.extend(_build_strict_steps(scene_id, scene_title, api_mode))
    else:
        lines.extend(_build_full_steps(scene_id, scene_title, voice_guide,
                                       api_mode))

    return '\n'.join(lines)


# ============================================================================
# Coaching-level step builders
# ============================================================================

def _build_coach_steps(scene_id: str, scene_title: str,
                       api_mode: bool) -> list[str]:
    """Build the COACH mode prompt steps."""
    lines = []
    lines.append('===== PRODUCE SCENE BRIEF =====')
    lines.append('')
    lines.append('You are in COACH mode. Do NOT write prose. '
                 'Do NOT create the scene file.')
    lines.append('')
    lines.append('Instead, produce a detailed scene brief covering:')
    lines.append('- Voice considerations: which voice rules apply, '
                 'POV-specific patterns to deploy, emotional register')
    lines.append('- Continuity constraints: locked details that must be '
                 'honored, character states entering the scene, MICE threads')
    lines.append('- Emotional arc targets: where the scene starts emotionally, '
                 'where it must arrive, the turn')
    lines.append('- Craft guidance: pacing recommendations, dialogue density, '
                 'sensory priorities, scene structure advice')
    lines.append('- Specific suggestions the author can use when writing this '
                 'scene themselves')

    if api_mode:
        lines.append('')
        lines.append('Output your scene brief directly as markdown.')
    else:
        title_suffix = f': {scene_title}' if scene_title else ''
        lines.append('')
        lines.append('')
        lines.append(f'Save to: working/coaching/brief-{scene_id}.md')
        lines.append('')
        lines.append('Then commit:')
        lines.append('  mkdir -p working/coaching')
        lines.append(f'  git add "working/coaching/brief-{scene_id}.md"')
        lines.append(f'  git commit -m "Coach: scene brief for '
                     f'{scene_id}{title_suffix}"')
        lines.append('  git push')

    lines.append('')
    lines.append('===== IMPORTANT NOTES =====')
    lines.append('- Do NOT write the scene. Your job is to prepare the author '
                 'to write it.')
    lines.append('- Be specific. "Use sensory detail" is not useful. '
                 '"Ground the opening in the smell of wet stone and the sound '
                 'of dripping water — Kael notices environmental details '
                 'before people" is useful.')
    lines.append('- Reference the voice guide, continuity tracker, and craft '
                 'principles concretely.')
    return lines


def _build_strict_steps(scene_id: str, scene_title: str,
                        api_mode: bool) -> list[str]:
    """Build the STRICT mode prompt steps."""
    lines = []
    lines.append('===== PRODUCE CONSTRAINT LIST =====')
    lines.append('')
    lines.append('You are in STRICT mode. Do NOT write prose.')
    lines.append('')
    lines.append('Produce a constraint list covering:')
    lines.append('- Voice rules: which voice guide rules apply to this scene '
                 'and POV character')
    lines.append('- Continuity requirements: locked details, character states, '
                 'thread obligations')
    lines.append('- Structural obligations: what must turn in this scene, what '
                 'the scene must set up for later scenes')
    lines.append('- Metadata: target word count, scene type, emotional arc '
                 'endpoints')

    if api_mode:
        lines.append('')
        lines.append('Output your constraint list directly as markdown.')
    else:
        title_suffix = f': {scene_title}' if scene_title else ''
        lines.append('')
        lines.append('')
        lines.append('**Create the scene file** — an empty file (metadata is '
                     'tracked in CSV, not frontmatter):')
        lines.append(f'Save to: scenes/{scene_id}.md')
        lines.append('')
        lines.append(f'**Save constraints to:** working/coaching/'
                     f'constraints-{scene_id}.md')
        lines.append('')
        lines.append('Then commit:')
        lines.append('  mkdir -p working/coaching')
        lines.append(f'  git add "scenes/{scene_id}.md"')
        lines.append(f'  git add "working/coaching/constraints-{scene_id}.md"')
        lines.append(f'  git commit -m "Strict: constraints for '
                     f'{scene_id}{title_suffix}"')
        lines.append('  git push')

    lines.append('')
    lines.append('===== IMPORTANT NOTES =====')
    lines.append('- Do NOT write prose. List facts and requirements only.')
    lines.append('- Do NOT provide editorial suggestions or craft guidance.')
    return lines


def _build_full_steps(scene_id: str, scene_title: str,
                      voice_guide: str, api_mode: bool) -> list[str]:
    """Build the FULL mode prompt steps."""
    lines = []

    if api_mode:
        lines.append('===== DRAFT THE SCENE =====')
        lines.append('')
        lines.append('Write the complete scene following these rules:')
        lines.append('')
        lines.append('VOICE AND STYLE:')
        lines.append('- Follow the voice guide exactly')
        lines.append("- Maintain the POV character's distinct voice throughout")
        lines.append('- Let the style rules govern every sentence — word '
                     'choice, rhythm, metaphor, dialogue density')
        lines.append('')
        lines.append('PROSE NATURALNESS:')
        lines.append('- Em dashes are rare — use at most one per scene. '
                     'Default to commas, parentheses, or sentence breaks.')
        lines.append('- No antithesis framing. Do not structure observations '
                     'as contrasting pairs where the first element is negated '
                     'and the second affirmed. Let contrast emerge from content, '
                     'not rhetorical formula.')
        lines.append('- Do not default to tricolon or parallel structure. '
                     'If two items make the point, stop at two.')
        lines.append('- Vary sentence and paragraph length. Symmetry reads '
                     'as artificial.')
        lines.append('- Use contractions in interiority and dialogue.')
        lines.append('- No metaphor restatement. When you write an image or '
                     'metaphor, stop. Do not follow it with a clause that '
                     'explains what the image means. "The silence hung between '
                     'them like fog" is complete — do not add "thick, obscuring, '
                     'making it impossible to see." Trust the reader.')
        lines.append('- No interpretive tagging. When a character performs a '
                     'gesture or action, do not follow it with narrator commentary '
                     'explaining the significance. "She set the cup down carefully" '
                     'needs no "It was a gesture of control" or "as though '
                     'anchoring herself." The action is the meaning.')
        lines.append('- Vary scene endings. Do not default to: [small physical '
                     'action] then [thematic observation] then [short declarative '
                     'sentence]. This three-beat cadence is a template. End on '
                     'action, dialogue, image, or mid-motion instead.')
        lines.append('- Start scenes in the middle of something. End on image, '
                     'action, or dialogue — not summary.')
        lines.append('')
        lines.append('CONTINUITY:')
        lines.append('- Do not contradict ANY locked details in the continuity '
                     'tracker (provided in reference materials above)')
        lines.append('- Respect all current character states (physical, '
                     'emotional, relational)')
        lines.append('- Advance MICE threads as appropriate per the scene '
                     'outline')
        lines.append("- Maintain consistency with the previous scene's ending")
        lines.append('')
        lines.append('Write ONLY the scene prose. Do not include any YAML '
                     'frontmatter or metadata.')
        lines.append('')
        lines.append('===== OUTPUT FORMAT =====')
        lines.append('')
        lines.append('Output the complete scene using this exact format:')
        lines.append('')
        lines.append(f'=== SCENE: {scene_id} ===')
        lines.append('[Your complete scene prose here]')
        lines.append(f'=== END SCENE: {scene_id} ===')
        lines.append('')
        lines.append('**CRITICAL:** Output the COMPLETE scene. Do not '
                     'truncate, summarize, or use placeholders.')
        lines.append('')
        lines.append('===== IMPORTANT NOTES =====')
        lines.append('- Focus entirely on writing the best possible scene.')
        lines.append('- Let the craft principles, voice guide, and continuity '
                     'tracker guide every sentence.')
    else:
        title_suffix = f': {scene_title}' if scene_title else ''
        vg_ref = f' ({voice_guide})' if voice_guide else ''

        lines.append('===== STEP 4: DRAFT THE SCENE =====')
        lines.append('')
        lines.append('Write the complete scene following these rules:')
        lines.append('')
        lines.append('VOICE AND STYLE:')
        lines.append(f'- Follow the voice guide{vg_ref} exactly')
        lines.append("- Maintain the POV character's distinct voice throughout")
        lines.append('- Let the style rules govern every sentence — word '
                     'choice, rhythm, metaphor, dialogue density')
        lines.append('')
        lines.append('PROSE NATURALNESS:')
        lines.append('- Em dashes are rare — use at most one per scene. '
                     'Default to commas, parentheses, or sentence breaks.')
        lines.append('- No antithesis framing. Do not structure observations '
                     'as contrasting pairs where the first element is negated '
                     'and the second affirmed. Let contrast emerge from content, '
                     'not rhetorical formula.')
        lines.append('- Do not default to tricolon or parallel structure. '
                     'If two items make the point, stop at two.')
        lines.append('- Vary sentence and paragraph length. Symmetry reads '
                     'as artificial.')
        lines.append('- Use contractions in interiority and dialogue.')
        lines.append('- No metaphor restatement. When you write an image or '
                     'metaphor, stop. Do not follow it with a clause that '
                     'explains what the image means. "The silence hung between '
                     'them like fog" is complete — do not add "thick, obscuring, '
                     'making it impossible to see." Trust the reader.')
        lines.append('- No interpretive tagging. When a character performs a '
                     'gesture or action, do not follow it with narrator commentary '
                     'explaining the significance. "She set the cup down carefully" '
                     'needs no "It was a gesture of control" or "as though '
                     'anchoring herself." The action is the meaning.')
        lines.append('- Vary scene endings. Do not default to: [small physical '
                     'action] then [thematic observation] then [short declarative '
                     'sentence]. This three-beat cadence is a template. End on '
                     'action, dialogue, image, or mid-motion instead.')
        lines.append('- Start scenes in the middle of something. End on image, '
                     'action, or dialogue — not summary.')
        lines.append('')
        lines.append('CONTINUITY:')
        lines.append('- Do not contradict ANY locked details in the continuity '
                     'tracker')
        lines.append('- Respect all current character states (physical, '
                     'emotional, relational)')
        lines.append('- Advance MICE threads as appropriate per the scene '
                     'outline')
        lines.append("- Maintain consistency with the previous scene's ending")
        lines.append('')
        lines.append(f'Save the scene to: scenes/{scene_id}.md')
        lines.append('')
        lines.append('Write ONLY the scene prose. Do not include any YAML '
                     'frontmatter or metadata.')
        lines.append('')
        lines.append('===== STEP 5: QUALITY REVIEW =====')
        lines.append('')
        lines.append('Launch an Agent to review the draft. The agent should:')
        lines.append(f'1. Read scenes/{scene_id}.md')
        lines.append('2. Read the scene metadata from '
                     'reference/scenes.csv and reference/scene-intent.csv')
        lines.append('3. Check for:')
        lines.append('   - MICE threads that should advance but don\'t '
                     '(or advance incorrectly)')
        lines.append('   - POV voice consistency')
        lines.append('   - Word count vs. target')
        lines.append('   - Continuity breaks with the previous scene '
                     '(character locations, emotional states, time progression)')
        lines.append('4. Report any issues found')
        lines.append('')
        lines.append('===== STEP 6: REVISE IF NEEDED =====')
        lines.append('')
        lines.append('If the quality review found significant continuity '
                     'errors or voice breaks, '
                     'fix them in the scene file now. Minor style notes can be '
                     'logged but do not require immediate fixes.')
        lines.append('')
        lines.append('===== STEP 7: GIT COMMIT =====')
        lines.append('')
        lines.append('Stage and commit using the Bash tool:')
        lines.append('')
        lines.append(f'  git add "scenes/{scene_id}.md"')
        lines.append('  git add reference/ 2>/dev/null || true')
        lines.append(f'  git commit -m "Draft scene '
                     f'{scene_id}{title_suffix}"')
        lines.append('  git push')
        lines.append('')
        lines.append('===== IMPORTANT NOTES =====')
        lines.append("- Complete ALL eight steps. The next scene's drafting "
                     'depends on accurate continuity state.')
        lines.append('- If you encounter an issue with the draft, fix it '
                     'before updating continuity files.')
        lines.append('- The continuity updates are as important as the scene '
                     'itself — future scenes rely on them.')

    return lines


# ============================================================================
# Prose prohibition block — front-loaded to exploit primacy bias
# ============================================================================

_PROHIBITION_BLOCK = """## CRITICAL PROSE RULES — Read These First

These rules override everything else in this prompt. Violations are the single most common failure mode.

### Absolute Prohibitions

1. **NO antithesis framing.** Never write "Not X. It's Y." or "It wasn't X — it was Y." or "This isn't about X. It's about Y." If you need contrast, let it emerge from content, not rhetorical formula. ZERO instances per scene.

2. **NO tricolon by default.** Do not list three things when two or one will do. Three-part structures must feel necessary, not habitual. Before writing any list of three, ask: would two items make the point? If yes, stop at two.

3. **NO scene-ending summary or philosophical pivot.** Do not end scenes with a sentence that restates the scene's theme, meaning, or emotional content. End on action, image, or dialogue. The scene already said what it means.

4. **NO doubled emotional statements.** Do not describe an emotion, then describe it again with greater intensity in the same paragraph. State it once, at the right pitch. "She went still" does not need "— a stillness born of..." One statement. Move on.

5. **NO silence annotation.** Do not describe a silence and then explain what kind of silence it was. Show what happens in the silence instead.

6. **NO hedging stacks.** Do not pile "perhaps," "almost as if," "a kind of," "something like." Commit to the observation.

7. **NO performative noticing.** Never write "He noticed that..." or "She became aware that..." Just render what they perceive.

### Motif Discipline

Recurring thematic language (signature phrases, recurring images, thematic keywords) may appear AT MOST ONCE per scene, and only if it earns its place. These words gain power through scarcity.

Functional vocabulary — names of instruments, equipment, locations, and procedures — is exempt from the motif cap. Use them as the action requires, but vary phrasing where natural.

### Scene Endings

End every scene with ONE of these and nothing else:
- A physical action (someone moves, picks something up, turns away)
- A line of dialogue (the last word spoken)
- A concrete image (what the POV character sees, not what they think about it)

Do NOT end with: a reflection on what just happened, a thematic restatement, a landscape-as-metaphor sentence, or a philosophical observation. The scene is over. Stop.

### Technical Detail Is Not Ornamentation

Technical and procedural detail — how instruments work, how schemes are executed, how professional skills are applied — is load-bearing content, not decoration. Preserve it. Cut lyrical excess, not specificity."""


def _get_pov_restraint_level(pov: str, ref_dir: str) -> str:
    """Determine prose restraint level based on POV character's role.

    Returns 'maximum', 'medium', or 'permitted' to guide interior elaboration.
    """
    chars_path = os.path.join(ref_dir, 'characters.csv')
    if not os.path.isfile(chars_path):
        return 'maximum'

    from .elaborate import _read_csv_as_map
    chars = _read_csv_as_map(chars_path)

    # Try exact match, then normalize
    role = ''
    if pov in chars:
        role = chars[pov].get('role', '').strip().lower()
    else:
        # Try matching by name
        pov_lower = pov.lower()
        for cid, cdata in chars.items():
            name = cdata.get('name', '').lower()
            if name == pov_lower or pov_lower in name:
                role = cdata.get('role', '').strip().lower()
                break

    if role == 'antagonist':
        return 'permitted'
    elif role in ('supporting', 'minor'):
        return 'medium'
    else:  # protagonist or unknown
        return 'maximum'


def _build_pov_restraint_block(pov: str, ref_dir: str) -> str:
    """Build POV-aware restraint guidance."""
    level = _get_pov_restraint_level(pov, ref_dir)

    if level == 'permitted':
        return """### POV Restraint Level: PERMITTED (Antagonist/Architect)

This POV character's mind IS the scene — their systematic thinking, classifications, and self-justification are characterization. Interior elaboration is permitted at length. The absolute prohibitions (no antithesis, no tricolon defaults, no doubled emotions) still apply, but this scene can sustain longer interior passages because the character's obsessive control is the point."""

    elif level == 'medium':
        return """### POV Restraint Level: MEDIUM (Supporting/Outsider)

This POV character's interiority is grounded in the physical world. Reflective passages are permitted when rooted in specific sensory memory, not abstract philosophy. Keep interior elaboration moderate — show more through action and observation than through named emotions."""

    else:  # maximum
        return """### POV Restraint Level: MAXIMUM (Protagonist)

This POV character withholds. Their interiority is sparse, physical, professional. Emotions are shown through action and observation, rarely named. Do not editorialize their feelings. Let the reader infer from what the character does and what they notice."""


def _load_prose_exemplars(project_dir: str, pov: str = '') -> str:
    """Load prose exemplar text, preferring per-POV files.

    Loading order:
    1. reference/exemplars/{pov-slug}.md (per-POV, if pov is provided)
    2. reference/prose-exemplars.md (flat file fallback)

    Returns formatted prompt block, or empty string if no exemplars found.
    """
    content = ''

    # Try per-POV file first
    if pov:
        pov_slug = pov.lower().replace(' ', '-')
        pov_path = os.path.join(project_dir, 'reference', 'exemplars', f'{pov_slug}.md')
        if os.path.isfile(pov_path):
            with open(pov_path, encoding='utf-8') as f:
                content = f.read().strip()

    # Fall back to flat file
    if not content:
        flat_path = os.path.join(project_dir, 'reference', 'prose-exemplars.md')
        if os.path.isfile(flat_path):
            with open(flat_path, encoding='utf-8') as f:
                content = f.read().strip()

    if not content:
        return ''

    # Extract rhythm signature if possible
    rhythm_block = ''
    try:
        from .exemplars import compute_rhythm_signature, format_rhythm_for_prompt
        sig = compute_rhythm_signature(content)
        if sig:
            rhythm_block = '\n\n' + format_rhythm_for_prompt(sig)
    except (ImportError, Exception):
        pass

    return (
        "## Voice Calibration — Write Like This\n\n"
        "These passages represent the manuscript's target voice. "
        "Study their rhythm, restraint, and specificity. "
        "Notice what they do NOT do: they don't summarize, don't explain emotions, "
        "don't end with philosophical reflections.\n\n"
        + content
        + rhythm_block
    )


# ============================================================================
# Brief-aware prompt builder (elaboration pipeline)
# ============================================================================

def build_scene_prompt_from_briefs(
    scene_id: str,
    project_dir: str,
    plugin_dir: str,
    coaching_level: str = 'full',
    dep_scenes: list[str] | None = None,
    system_context: bool = False,
) -> str:
    """Build a drafting prompt from the three-file scene CSV model.

    Unlike build_scene_prompt which reads scenes.csv + scene-intent.csv,
    this reads scenes.csv + scene-intent.csv + scene-briefs.csv and includes
    the full brief as the drafting contract. The full manuscript is NOT included —
    only dependency scene briefs for context.

    Args:
        scene_id: The scene to draft.
        project_dir: Path to the book project.
        plugin_dir: Path to the Storyforge plugin root.
        coaching_level: full/coach/strict.
        dep_scenes: Scene IDs this scene depends on (from continuity_deps).
                    Their brief rows are included for context.
        system_context: When True, shared reference material (voice guide,
            character bible, AI-tell vocabulary, voice profile) is provided
            via the API ``system`` parameter and should NOT be inlined.
    """
    from .elaborate import get_scene, get_scenes

    yaml_path = os.path.join(project_dir, 'storyforge.yaml')
    title = read_yaml_field(yaml_path, 'project.title') or 'Untitled'
    genre = read_yaml_field(yaml_path, 'project.genre') or ''

    ref_dir = os.path.join(project_dir, 'reference')
    scene = get_scene(scene_id, ref_dir)
    if not scene:
        return f"ERROR: Scene {scene_id} not found in scenes.csv"

    # Build scene data block (exclude subtext — it gets special framing below)
    scene_block = '\n'.join(f"**{k}:** {v}" for k, v in scene.items()
                            if v and k not in ('id', 'subtext'))

    # Subtext gets its own section so the drafter treats it as a constraint
    subtext_value = scene.get('subtext', '').strip()
    if subtext_value:
        scene_block += (
            f'\n\n**SUBTEXT (show, never tell):** {subtext_value}\n'
            'This is what is happening beneath the surface. The reader should '
            'feel it through action, dialogue, and detail — never through '
            'narrator explanation.'
        )

    # Build dependency context
    dep_block = ''
    if dep_scenes:
        dep_parts = []
        for dep_id in dep_scenes:
            dep = get_scene(dep_id, ref_dir)
            if dep:
                dep_summary = (
                    f"**{dep_id}** — {dep.get('function', '')}\n"
                    f"  outcome: {dep.get('outcome', '')}\n"
                    f"  knowledge_out: {dep.get('knowledge_out', '')}\n"
                    f"  physical_state_out: {dep.get('physical_state_out', '')}\n"
                    f"  emotional_arc: {dep.get('emotional_arc', '')}"
                )
                dep_parts.append(dep_summary)
        if dep_parts:
            dep_block = "## Dependency Scenes\n\nThese scenes happen before this one. Their outcomes and knowledge states are your starting context.\n\n" + '\n\n'.join(dep_parts)

    # Voice guide (skipped when system_context provides it)
    voice_guide = ''
    if not system_context:
        voice_path = os.path.join(ref_dir, 'voice-guide.md')
        if os.path.isfile(voice_path):
            with open(voice_path) as f:
                voice_guide = f"## Voice Guide\n\n{f.read().strip()}"

    # Character bible entries for on-stage characters (skipped when system_context)
    char_block = ''
    if not system_context:
        char_path = os.path.join(ref_dir, 'character-bible.md')
        if os.path.isfile(char_path):
            on_stage = scene.get('on_stage', '')
            if on_stage:
                char_block = f"## Character Bible (on-stage: {on_stage})\n\n"
                with open(char_path) as f:
                    char_block += f.read().strip()

    # Physical state context
    state_block = ''
    state_in = scene.get('physical_state_in', '').strip()
    if state_in:
        state_ids = [s.strip() for s in state_in.split(';') if s.strip()]
        # Try to load registry for descriptions
        states_registry = {}
        states_path = os.path.join(ref_dir, 'physical-states.csv')
        if os.path.isfile(states_path):
            from .elaborate import _read_csv_as_map
            states_registry = _read_csv_as_map(states_path)

        state_lines = []
        for sid in state_ids:
            entry = states_registry.get(sid, {})
            char = entry.get('character', '')
            desc = entry.get('description', sid)
            gating = entry.get('action_gating', 'false').lower() == 'true'
            line = f"- **{char}**: {desc}" if char else f"- {desc}"
            if gating:
                line += " *(action-gating)*"
            state_lines.append(line)

        state_block = (
            "## Active Physical States\n\n"
            "Characters entering this scene carry these states:\n\n"
            + '\n'.join(state_lines)
        )

    # Craft principles
    craft = build_weighted_directive(project_dir)
    craft_block = f"## Craft Principles\n\n{craft}" if craft else ''

    # --- AI-tell vocabulary constraint ---
    # When system_context is True, AI-tell words and voice profile are in the
    # system parameter — skip inlining them here.
    ai_tell_words = [] if system_context else load_ai_tell_words(plugin_dir)
    ai_tell_block = build_ai_tell_constraint(ai_tell_words)

    # --- Voice profile ---
    if system_context:
        voice_profile_project, voice_profile_chars = {}, {}
    else:
        voice_profile_project, voice_profile_chars = load_voice_profile(project_dir)
    pov_char = scene.get('pov', '')

    # Merge banned words: project profile + universal AI-tell list
    if voice_profile_project or ai_tell_words:
        merged_banned = merge_banned_words(voice_profile_project, ai_tell_words)
        if merged_banned:
            banned_str = ', '.join(merged_banned)
            ai_tell_block = (
                'VOCABULARY CONSTRAINT: Do not use these words or phrases — they '
                'are banned for this project:\n'
                f'{banned_str}\n'
                'Replace with concrete, specific words grounded in the scene and character.'
            )

    # Character-specific voice constraints
    char_voice_block = ''
    if pov_char:
        pov_slug = pov_char.lower().replace(' ', '-')
        char_key = pov_char if pov_char in voice_profile_chars else (
            pov_slug if pov_slug in voice_profile_chars else '')
        if char_key:
            char_data = voice_profile_chars[char_key]
            parts = []
            if char_data.get('preferred_words'):
                parts.append(f'Favor these words (they define this character\'s voice): '
                            f'{char_data["preferred_words"].replace(";", ", ")}')
            if char_data.get('metaphor_families'):
                parts.append(f'Source metaphors from: '
                            f'{char_data["metaphor_families"].replace(";", ", ")}')
            if char_data.get('rhythm_preference'):
                parts.append(f'Sentence rhythm: '
                            f'{char_data["rhythm_preference"].replace(";", ", ")}')
            if char_data.get('dialogue_style'):
                parts.append(f'Dialogue style: '
                            f'{char_data["dialogue_style"].replace(";", ", ")}')
            if parts:
                char_voice_block = (
                    f'CHARACTER VOICE ({pov_char}):\n' + '\n'.join(f'- {p}' for p in parts)
                )

    vocab_block = ''
    if ai_tell_block:
        vocab_block = f"## Vocabulary Constraints\n\n{ai_tell_block}"

    char_voice_section = ''
    if char_voice_block:
        char_voice_section = f"## Character Voice\n\n{char_voice_block}"

    register_line = ''
    if voice_profile_project.get('register'):
        register_line = f"PROSE REGISTER: {voice_profile_project['register'].replace(';', ', ')}"

    # Target word count
    target_words = scene.get('target_words', '') or scene.get('word_count', '')
    word_target_line = ''
    if target_words and str(target_words).strip() and int(str(target_words).strip() or 0) > 0:
        word_target_line = f"\n**Target length: ~{target_words} words.** Prefer economy — achieve through implication what would take twice the words in exposition. Do not pad to reach the target; stop when the scene is complete."

    # Key dialogue checklist
    key_dialogue = scene.get('key_dialogue', '').strip()
    dialogue_checklist = ''
    if key_dialogue:
        lines = [d.strip() for d in key_dialogue.split(';') if d.strip()]
        if lines:
            items = '\n'.join(f'  - [ ] {line}' for line in lines)
            dialogue_checklist = f"\n\n**Key dialogue checklist — every line below MUST appear in the scene (verbatim or close paraphrase). Do not end the scene until all are delivered:**\n{items}"

    # Coaching-specific instructions
    if coaching_level == 'full':
        task_block = f"""## Task

Write the complete prose for scene **{scene_id}** ("{scene.get('title', '')}").
{word_target_line}

The brief is your contract. Deliver:
- The value shift specified ({scene.get('value_shift', '')})
- The outcome specified ({scene.get('outcome', '')})
- The emotional arc from {scene.get('emotional_arc', '')}
- The POV character must know {scene.get('knowledge_out', '')} by scene end
{dialogue_checklist}

**Prose rules:**
- Em dashes rare (max one per scene)
- Vary sentence and paragraph length — follow thought patterns, not templates
- Contractions in interiority and dialogue
- Enter late, leave early
- Match the voice guide exactly

**Scene ending — choose ONE, then stop:**
- A physical action
- A line of dialogue
- A concrete image
Do NOT follow it with a reflection, a thematic echo, or a landscape-as-metaphor sentence.

**Guardrails:**
- Do NOT invent character relationships, history, or backstory not present in the brief, knowledge chain, or character bible
- Do NOT add characters not listed in on_stage
- Do NOT resolve threads not listed in mice_threads for this scene
- Acknowledge all action-gating physical states — characters cannot use injured limbs, don't have lost equipment

Output the scene prose only. No metadata, no frontmatter, no commentary."""

    elif coaching_level == 'coach':
        task_block = f"""## Task

Produce an expanded writing guide for scene **{scene_id}** ("{scene.get('title', '')}").

Include:
- Voice notes specific to this scene and POV character
- Craft reminders relevant to the scene type ({scene.get('action_sequel', '')})
- How to land the value shift ({scene.get('value_shift', '')})
- Suggested approach for the crisis/decision moment
- Line-level suggestions for key dialogue
- Pacing guidance given the emotional arc

Do NOT write the prose. The author writes from your guide."""

    else:  # strict
        task_block = f"""## Task

Format the brief data for scene **{scene_id}** ("{scene.get('title', '')}") as a clean reference for the author.

Include all structural data, knowledge states, and continuity constraints.
Do NOT add creative interpretation or suggestions."""

    # Prose prohibition block (front-loaded for primacy)
    prohibition_block = _PROHIBITION_BLOCK if coaching_level == 'full' else ''

    # POV-aware restraint level
    pov = scene.get('pov', '')
    pov_restraint = _build_pov_restraint_block(pov, ref_dir) if coaching_level == 'full' else ''

    # Prose exemplars (optional, per-POV preferred)
    exemplar_block = _load_prose_exemplars(project_dir, pov) if coaching_level == 'full' else ''

    return f"""You are drafting a scene for "{title}" ({genre}).

{prohibition_block}

{pov_restraint}

{exemplar_block}

## Scene Brief: {scene_id}

{scene_block}

{dep_block}

{state_block}

{voice_guide}

{char_block}

{craft_block}

{vocab_block}

{char_voice_section}

{register_line}

{task_block}
"""


# ============================================================================
# CLI interface for calling from bash
# ============================================================================

def main():
    """CLI entry point. Usage:

    python3 -m storyforge.prompts build-scene <scene_id> <project_dir> [--coaching full|coach|strict] [--api-mode]
    python3 -m storyforge.prompts get-metadata <scene_id> <project_dir>
    python3 -m storyforge.prompts get-intent <scene_id> <project_dir>
    python3 -m storyforge.prompts get-previous <scene_id> <project_dir>
    python3 -m storyforge.prompts list-refs <project_dir>
    python3 -m storyforge.prompts read-field <csv_file> <row_id> <field> [key_column]
    python3 -m storyforge.prompts weighted-directive <project_dir>
    """
    if len(sys.argv) < 2:
        print('Usage: python3 -m storyforge.prompts <command> [args]',
              file=sys.stderr)
        sys.exit(1)

    command = sys.argv[1]

    if command == 'build-scene':
        if len(sys.argv) < 4:
            print('Usage: build-scene <scene_id> <project_dir> '
                  '[--coaching full|coach|strict] [--api-mode]',
                  file=sys.stderr)
            sys.exit(1)

        scene_id = sys.argv[2]
        project_dir = sys.argv[3]
        coaching = 'full'
        api_mode = False

        # Parse optional flags
        i = 4
        while i < len(sys.argv):
            if sys.argv[i] == '--coaching' and i + 1 < len(sys.argv):
                coaching = sys.argv[i + 1]
                i += 2
            elif sys.argv[i] == '--api-mode':
                api_mode = True
                i += 1
            else:
                print(f'Unknown flag: {sys.argv[i]}', file=sys.stderr)
                sys.exit(1)

        prompt = build_scene_prompt(scene_id, project_dir, coaching, api_mode)
        print(prompt)

    elif command == 'build-from-briefs':
        if len(sys.argv) < 4:
            print('Usage: build-from-briefs <scene_id> <project_dir> '
                  '[--plugin-dir DIR] [--coaching full|coach|strict] '
                  '[--deps id1;id2;...]',
                  file=sys.stderr)
            sys.exit(1)

        scene_id = sys.argv[2]
        project_dir = sys.argv[3]
        plugin_dir = project_dir  # default fallback
        coaching = 'full'
        dep_scenes = None

        i = 4
        while i < len(sys.argv):
            if sys.argv[i] == '--coaching' and i + 1 < len(sys.argv):
                coaching = sys.argv[i + 1]
                i += 2
            elif sys.argv[i] == '--plugin-dir' and i + 1 < len(sys.argv):
                plugin_dir = sys.argv[i + 1]
                i += 2
            elif sys.argv[i] == '--deps' and i + 1 < len(sys.argv):
                dep_scenes = [d.strip() for d in sys.argv[i + 1].split(';') if d.strip()]
                i += 2
            else:
                i += 1

        prompt = build_scene_prompt_from_briefs(
            scene_id, project_dir, plugin_dir, coaching, dep_scenes)
        print(prompt)

    elif command == 'build-waves':
        if len(sys.argv) < 3:
            print('Usage: build-waves <project_dir>', file=sys.stderr)
            sys.exit(1)
        from .elaborate import compute_drafting_waves
        import json
        waves = compute_drafting_waves(os.path.join(sys.argv[2], 'reference'))
        print(json.dumps(waves))

    elif command == 'get-metadata':
        if len(sys.argv) < 4:
            print('Usage: get-metadata <scene_id> <project_dir>',
                  file=sys.stderr)
            sys.exit(1)
        print(get_scene_metadata(sys.argv[2], sys.argv[3]))

    elif command == 'get-intent':
        if len(sys.argv) < 4:
            print('Usage: get-intent <scene_id> <project_dir>',
                  file=sys.stderr)
            sys.exit(1)
        print(get_scene_intent(sys.argv[2], sys.argv[3]))

    elif command == 'get-previous':
        if len(sys.argv) < 4:
            print('Usage: get-previous <scene_id> <project_dir>',
                  file=sys.stderr)
            sys.exit(1)
        print(get_previous_scene(sys.argv[2], sys.argv[3]))

    elif command == 'list-refs':
        if len(sys.argv) < 3:
            print('Usage: list-refs <project_dir>', file=sys.stderr)
            sys.exit(1)
        for ref in list_reference_files(sys.argv[2]):
            print(ref)

    elif command == 'read-field':
        if len(sys.argv) < 5:
            print('Usage: read-field <csv_file> <row_id> <field> [key_column]',
                  file=sys.stderr)
            sys.exit(1)
        csv_file = sys.argv[2]
        row_id = sys.argv[3]
        field = sys.argv[4]
        key_col = sys.argv[5] if len(sys.argv) > 5 else 'id'
        print(read_csv_field(csv_file, row_id, field, key_col))

    elif command == 'weighted-directive':
        if len(sys.argv) < 3:
            print('Usage: weighted-directive <project_dir>', file=sys.stderr)
            sys.exit(1)
        result = build_weighted_directive(sys.argv[2])
        if result:
            print(result)

    elif command == 'scene-status':
        if len(sys.argv) < 4:
            print('Usage: scene-status <scene_id> <project_dir>',
                  file=sys.stderr)
            sys.exit(1)
        print(get_scene_status(sys.argv[2], sys.argv[3]))

    else:
        print(f'Unknown command: {command}', file=sys.stderr)
        sys.exit(1)


if __name__ == '__main__':
    main()
