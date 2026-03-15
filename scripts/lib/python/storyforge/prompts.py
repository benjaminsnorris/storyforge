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
# CSV helpers (pipe-delimited)
# ============================================================================

def _read_csv_header_and_rows(csv_file: str) -> tuple[list[str], list[list[str]]]:
    """Read a pipe-delimited CSV, returning (header_fields, data_rows)."""
    with open(csv_file) as f:
        lines = [l.rstrip('\n') for l in f if l.strip()]

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

def _resolve_metadata_csv(project_dir: str) -> str:
    """Find the scene-metadata CSV, checking the fallback location."""
    primary = os.path.join(project_dir, 'reference', 'scene-metadata.csv')
    if os.path.isfile(primary):
        return primary
    fallback = os.path.join(project_dir, 'scenes', 'metadata.csv')
    if os.path.isfile(fallback):
        return fallback
    return ''


def _resolve_intent_csv(project_dir: str) -> str:
    """Find the scene-intent CSV, checking the fallback location."""
    primary = os.path.join(project_dir, 'reference', 'scene-intent.csv')
    if os.path.isfile(primary):
        return primary
    fallback = os.path.join(project_dir, 'scenes', 'intent.csv')
    if os.path.isfile(fallback):
        return fallback
    return ''


def get_scene_metadata(scene_id: str, project_dir: str) -> str:
    """Read metadata for a scene from reference/scene-metadata.csv.

    Args:
        scene_id: The scene identifier.
        project_dir: Root directory of the project.

    Returns:
        Formatted ``key: value`` pairs (one per line), or empty string.
    """
    csv_file = _resolve_metadata_csv(project_dir)
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
    csv_file = _resolve_metadata_csv(project_dir)
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
                seq_val = float(row[seq_idx]) if row[seq_idx] else 0
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

    lines = []
    for row in rows:
        if row and row[0] == scene_id and len(row) > 2:
            lines.append(f'- {row[2]}')

    return '\n'.join(lines)


# ============================================================================
# Main prompt builder
# ============================================================================

def build_scene_prompt(scene_id: str, project_dir: str,
                       coaching_level: str = 'full',
                       api_mode: bool = False) -> str:
    """Assemble the complete drafting prompt for a single scene.

    Args:
        scene_id: The scene identifier (e.g. ``the-finest-cartographer``).
        project_dir: Root directory of the novel project.
        coaching_level: One of ``full``, ``coach``, ``strict``.
        api_mode: When True, inline reference file contents directly into
            the prompt. When False, emit file paths for ``claude -p``.

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
    csv_file = _resolve_metadata_csv(project_dir)
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

    # --- Craft principles ---
    craft_sections = build_weighted_directive(project_dir)
    if not craft_sections:
        # Fallback: extract from craft engine
        # __file__ is scripts/lib/python/storyforge/prompts.py — 5 levels to repo root
        plugin_dir = os.path.dirname(os.path.dirname(os.path.dirname(
            os.path.dirname(os.path.dirname(os.path.abspath(__file__))))))
        craft_sections = extract_craft_sections(plugin_dir, 2, 3, 4, 5)

    overrides = _get_scene_overrides(scene_id, project_dir)
    if overrides:
        craft_sections += f'\n\n## Scene-Specific Notes\n{overrides}'

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
    if api_mode:
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

    if voice_guide:
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
                 'honored, character states entering the scene, active threads')
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
        lines.append('CONTINUITY:')
        lines.append('- Do not contradict ANY locked details in the continuity '
                     'tracker (provided in reference materials above)')
        lines.append('- Respect all current character states (physical, '
                     'emotional, relational)')
        lines.append('- Advance active threads as appropriate per the scene '
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
        lines.append('CONTINUITY:')
        lines.append('- Do not contradict ANY locked details in the continuity '
                     'tracker')
        lines.append('- Respect all current character states (physical, '
                     'emotional, relational)')
        lines.append('- Advance active threads as appropriate per the scene '
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
        lines.append('2. Read the continuity tracker '
                     '(reference/continuity-tracker.md if it exists)')
        lines.append('3. Read the scene metadata from '
                     'reference/scene-metadata.csv')
        lines.append('4. Check for:')
        lines.append('   - Contradictions with locked details')
        lines.append('   - Active threads that should advance but don\'t '
                     '(or advance incorrectly)')
        lines.append('   - POV voice consistency')
        lines.append('   - Word count vs. target')
        lines.append('   - Continuity breaks with the previous scene '
                     '(character locations, emotional states, time progression)')
        lines.append('5. Report any issues found')
        lines.append('')
        lines.append('===== STEP 6: REVISE IF NEEDED =====')
        lines.append('')
        lines.append('If the quality review found significant continuity '
                     'errors, contradicted locked details, or voice breaks, '
                     'fix them in the scene file now. Minor style notes can be '
                     'logged but do not require immediate fixes.')
        lines.append('')
        lines.append('===== STEP 7: UPDATE CONTINUITY =====')
        lines.append('')
        lines.append('If a continuity tracker exists '
                     '(reference/continuity-tracker.md), update it:')
        lines.append('- Add a summary for this scene (2-3 sentences)')
        lines.append("- Update character states to reflect this scene's events")
        lines.append('- Add any new locked details established in this scene')
        lines.append('- Update active threads: advance existing ones, add new '
                     'ones opened, move fully resolved ones to a resolved '
                     'section')
        lines.append('- Update any motif tracking')
        lines.append('')
        lines.append('===== STEP 8: GIT COMMIT =====')
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

    else:
        print(f'Unknown command: {command}', file=sys.stderr)
        sys.exit(1)


if __name__ == '__main__':
    main()
