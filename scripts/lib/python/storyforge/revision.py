"""Revision prompt building and scope resolution.

Replaces the prompt-building functions from revision-passes.sh — provides
reliable scope resolution, craft-section extraction, and prompt assembly
without bash string-handling fragility.
"""

import csv
import os
import re
import sys


# ============================================================================
# Scene file resolution
# ============================================================================

def resolve_scene_file(scene_dir: str, scene_id: str) -> str | None:
    """Find a scene file with fallbacks for legacy naming.

    Tries in order:
        1. Exact match: {scene_dir}/{scene_id}.md
        2. Legacy numeric: strip "scene-"/"Scene-" prefix and leading zeros
        3. Zero-padded: bare "25" -> "025" (3-digit)

    Args:
        scene_dir: Path to the scenes/ directory.
        scene_id: The scene identifier (slug or numeric).

    Returns:
        Absolute path to the scene file, or None if not found.
    """
    # Exact match
    exact = os.path.join(scene_dir, f'{scene_id}.md')
    if os.path.isfile(exact):
        return exact

    # Legacy numeric fallback: strip "scene-"/"Scene-" prefix and leading zeros
    stripped = scene_id
    for prefix in ('scene-', 'Scene-'):
        if stripped.startswith(prefix):
            stripped = stripped[len(prefix):]
            break
    stripped = stripped.lstrip('0') or '0'

    if stripped != scene_id:
        legacy = os.path.join(scene_dir, f'{stripped}.md')
        if os.path.isfile(legacy):
            print(f"[WARN] Scene '{scene_id}' resolved via legacy fallback to '{stripped}.md'. "
                  f"Consider running: ./storyforge migrate-scenes", file=sys.stderr)
            return legacy

    # Zero-padded numeric fallback: bare "25" -> "025"
    if scene_id.isdigit():
        padded = f'{int(scene_id):03d}'
        if padded != scene_id:
            padded_path = os.path.join(scene_dir, f'{padded}.md')
            if os.path.isfile(padded_path):
                return padded_path

    return None


# ============================================================================
# Scene CSV helpers
# ============================================================================

def _read_pipe_csv(csv_path: str) -> list[dict]:
    """Read a pipe-delimited CSV file into a list of dicts.

    Strips ``\\r`` so CRLF line endings and stray carriage returns embedded
    by awk-based CSV edits never propagate into field values.
    """
    with open(csv_path, newline='', encoding='utf-8') as f:
        raw = f.read().replace('\r\n', '\n').replace('\r', '')
    rows = []
    reader = csv.DictReader(raw.splitlines(), delimiter='|')
    for row in reader:
        rows.append({k: (v if v is not None else '') for k, v in row.items()})
    return rows


def _find_scenes_csv(project_dir: str) -> str:
    """Locate the scenes CSV."""
    path = os.path.join(project_dir, 'reference', 'scenes.csv')
    if os.path.isfile(path):
        return path
    raise FileNotFoundError('scenes.csv not found in reference/')


# ============================================================================
# Scope resolution
# ============================================================================

def resolve_scope(scope: str, project_dir: str) -> list[str]:
    """Parse a scope string and return a list of scene file paths.

    Scope formats:
        "full"                              — all scenes (excluding cut)
        "scene-level" / "targeted"          — treated as full (targets narrow in prompt)
        "act-N" / "part-N"                  — scenes in that act/part
        "slug-a,slug-b,slug-c"             — comma-separated scene IDs
        "1,5,12"                           — all-numeric → resolve as seq numbers
        "[30, 31]"                         — inline list syntax (normalized)

    Args:
        scope: The scope specification string.
        project_dir: Path to the novel project root.

    Returns:
        List of absolute scene file paths.

    Raises:
        FileNotFoundError: If metadata CSV is missing.
        ValueError: If no scene files match the scope.
    """
    csv_path = _find_scenes_csv(project_dir)
    scene_dir = os.path.join(project_dir, 'scenes')
    rows = _read_pipe_csv(csv_path)

    # Filter out cut scenes and sort by seq
    active_rows = [r for r in rows if (r.get('type') or '').strip() != 'cut']
    active_rows.sort(key=lambda r: int(r.get('seq', '0').strip() or '0'))

    # Normalize inline list syntax: [30, 31] -> 30,31
    if scope.startswith('[') and scope.endswith(']'):
        scope = scope[1:-1].replace(' ', '')

    # Normalize aliases
    if scope in ('full', 'scene-level', 'targeted'):
        target_ids = [r['id'].strip() for r in active_rows]

    elif re.match(r'^(act|part)-\d+$', scope):
        part_num = scope.split('-')[-1]
        target_ids = [
            r['id'].strip() for r in active_rows
            if r.get('part', '').strip() == part_num
        ]

    else:
        # Comma- or semicolon-separated list — detect if all numeric (seq numbers)
        normalized = scope.replace(';', ',')
        parts = [s.strip() for s in normalized.split(',') if s.strip()]
        all_numeric = all(p.isdigit() for p in parts if not p.startswith('NEW:'))

        if all_numeric and not any(p.startswith('NEW:') for p in parts):
            # Resolve seq numbers to scene IDs
            seq_to_id = {r.get('seq', '').strip(): r['id'].strip() for r in active_rows}
            target_ids = []
            for seq in parts:
                sid = seq_to_id.get(seq)
                if sid:
                    target_ids.append(sid)
                else:
                    print(f"WARNING: No scene found with seq number {seq}", file=sys.stderr)
        else:
            target_ids = parts

    # Separate NEW: prefixed targets (scenes to create) from existing scenes
    new_scene_ids = []
    existing_ids = []
    for sid in target_ids:
        if sid.startswith('NEW:'):
            new_scene_ids.append(sid[4:])  # strip prefix
        else:
            existing_ids.append(sid)

    # Resolve existing IDs to file paths
    matched = []
    for sid in existing_ids:
        path = resolve_scene_file(scene_dir, sid)
        if path:
            matched.append(path)
        else:
            print(f"WARNING: Scene file missing for id '{sid}': {scene_dir}/{sid}.md",
                  file=sys.stderr)

    # Add virtual paths for new scenes (marked with NEW: prefix for downstream)
    for sid in new_scene_ids:
        matched.append(os.path.join(scene_dir, f'NEW:{sid}.md'))

    if not matched:
        raise ValueError(f"No scene files matched scope '{scope}'")

    return matched


# ============================================================================
# Craft engine extraction
# ============================================================================

def _find_plugin_dir() -> str:
    """Locate the storyforge plugin directory.

    Walks up from this file's location to find the repo root (where
    .claude-plugin/plugin.json lives).
    """
    # This file is at scripts/lib/python/storyforge/revision.py
    # Plugin root is 4 levels up
    here = os.path.dirname(os.path.abspath(__file__))
    plugin_dir = os.path.normpath(os.path.join(here, '..', '..', '..', '..'))
    if os.path.isfile(os.path.join(plugin_dir, '.claude-plugin', 'plugin.json')):
        return plugin_dir
    # Fallback: check STORYFORGE_PLUGIN_DIR env
    env_dir = os.environ.get('STORYFORGE_PLUGIN_DIR', '')
    if env_dir and os.path.isdir(env_dir):
        return env_dir
    return plugin_dir


def extract_craft_sections(*section_nums: int) -> str:
    """Extract numbered sections from the craft engine markdown.

    Sections are delimited by ``## N. Title`` headers. Each requested
    section number is extracted in full (header through end of section).

    Args:
        section_nums: One or more section numbers to extract.

    Returns:
        The concatenated section text, separated by ``---`` dividers.
    """
    plugin_dir = _find_plugin_dir()
    craft_file = os.path.join(plugin_dir, 'references', 'craft-engine.md')

    if not os.path.isfile(craft_file):
        return ''

    with open(craft_file) as f:
        content = f.read()

    # Parse into sections keyed by number
    sections: dict[int, str] = {}
    section_pattern = re.compile(r'^## (\d+)\. ', re.MULTILINE)
    matches = list(section_pattern.finditer(content))

    for i, m in enumerate(matches):
        num = int(m.group(1))
        start = m.start()
        end = matches[i + 1].start() if i + 1 < len(matches) else len(content)
        sections[num] = content[start:end].rstrip()

    parts = []
    for num in section_nums:
        if num in sections:
            parts.append(sections[num])

    return '\n\n---\n\n'.join(parts)


# ============================================================================
# Scoring rubric + exemplar loading
# ============================================================================

# Map common principle target names to rubric headings.  Rubric headings use
# title case with full names; pass targets use snake_case shorthand.  This
# map bridges the two so we can look up a rubric section from a pass target.
_PRINCIPLE_HEADING_MAP = {
    'enter_late_leave_early': 'Enter Late, Leave Early',
    'every_scene_must_turn': 'Every Scene Must Turn',
    'scene_emotion_vs_character': 'Scene Emotion vs. Character Emotion',
    'psychic_distance_scene': 'Psychic Distance at Scene Level',
    'show_vs_tell_scenes': 'Show vs. Tell Scenes',
    'thread_management': 'Thread Management',
    'pacing_variety': 'Pacing Through Scene Variety',
    'economy_clarity': 'Economy and Clarity',
    'sentence_as_thought': 'Sentence as Unit of Thought',
    'writers_toolbox': "Writer's Toolbox",
    'precision_language': 'Precision in Language',
    'persuasive_structure': 'Persuasive Structure',
    'fictive_dream': 'The Fictive Dream',
    'scene_vs_summary': 'Scene vs. Summary, Showing vs. Telling',
    'sound_rhythm_pov': 'Sound, Rhythm, and Point of View',
    'permission_honesty': 'Permission and Emotional Honesty',
    'prose_naturalness': 'Prose Naturalness',
    'show_dont_tell': 'Show, Don\'t Tell',
    'avoid_adverbs': 'Avoid Adverbs',
    'avoid_passive': 'Avoid Passive Voice',
    'no_weather_dreams': 'Never Open with Weather or Dreams',
    'said_bookisms': 'Avoid Said-Bookisms',
    'kill_darlings': 'Kill Your Darlings',
    'want_need': 'Want vs. Need',
    'wound_lie': 'Wound and Lie',
    'voice_as_character': 'Voice as Character',
    'egri_premise': "Egri's Premise",
    'character_as_theme': 'Character as Theme',
    'flaws_as_strengths': 'Flaws as Strengths',
    'archetype_vs_cliche': 'Archetype vs. Cliché',
}


def _load_rubric_sections(principles: list[str]) -> str:
    """Load scoring rubric sections for the given principle names.

    Parses references/scoring-rubrics.md and extracts the full rubric
    (all 5 score levels with exemplars) for each requested principle.

    Returns the concatenated rubric text, ready to inject into a prompt.
    """
    from storyforge.common import get_plugin_dir

    rubric_path = os.path.join(get_plugin_dir(), 'references', 'scoring-rubrics.md')
    if not os.path.isfile(rubric_path):
        return ''

    with open(rubric_path) as f:
        content = f.read()

    # Build set of headings we're looking for
    target_headings = set()
    for p in principles:
        heading = _PRINCIPLE_HEADING_MAP.get(p)
        if heading:
            target_headings.add(heading)
        else:
            # Fall back to title-casing the snake_case name
            target_headings.add(p.replace('_', ' ').title())

    if not target_headings:
        return ''

    # Parse: split on ### headings, capture heading + body
    sections = re.split(r'^### ', content, flags=re.MULTILINE)
    results = []

    for section in sections:
        if not section.strip():
            continue
        # First line is the heading
        first_newline = section.find('\n')
        if first_newline == -1:
            continue
        heading = section[:first_newline].strip()

        if heading in target_headings:
            # Include the full section (heading + all score levels + exemplars)
            body = section[first_newline:].strip()
            results.append(f'### {heading}\n\n{body}')

    return '\n\n---\n\n'.join(results)


def _load_author_exemplars(project_dir: str, principles: list[str]) -> str:
    """Load author exemplar passages for the given principles.

    Reads working/exemplars.csv (if it exists) and returns exemplar
    excerpts for the targeted principles.  These are the author's own
    high-scoring passages, collected during prior scoring cycles.
    """
    exemplars_path = os.path.join(project_dir, 'working', 'exemplars.csv')
    if not os.path.isfile(exemplars_path):
        return ''

    target_set = set(principles)
    entries = []

    with open(exemplars_path, newline='', encoding='utf-8') as f:
        raw = f.read().replace('\r\n', '\n').replace('\r', '')
    reader = csv.DictReader(raw.splitlines(), delimiter='|')
    for row in reader:
        principle = (row.get('principle') or '').strip()
        if principle not in target_set:
            continue
        excerpt = (row.get('excerpt') or '').strip()
        scene_id = (row.get('scene_id') or '').strip()
        score = (row.get('score') or '').strip()
        if excerpt:
            entries.append(
                f'**{principle}** (score {score}, scene `{scene_id}`):\n'
                f'> {excerpt}'
            )

    return '\n\n'.join(entries)


def _extract_pass_principles(pass_config: str, purpose: str) -> list[str]:
    """Extract principle names targeted by this pass.

    Looks for principle names in the pass config targets, guidance, and
    purpose text.  Returns a list of snake_case principle identifiers.
    """
    text = f'{pass_config}\n{purpose}'.lower()
    found = []
    for key in _PRINCIPLE_HEADING_MAP:
        # Match the snake_case key or its space-separated form
        if key in text or key.replace('_', ' ') in text or key.replace('_', '-') in text:
            found.append(key)
    return found


def _select_craft_sections(pass_name: str, purpose: str) -> str:
    """Pick relevant craft engine sections based on the pass name and purpose."""
    key = f'{pass_name} {purpose}'.lower()

    if re.search(r'prose|voice|tighten|line.edit|sentence|rhythm|word.choice', key):
        nums = (3, 5)  # Prose Craft + Rules
    elif re.search(r'character|arc|deepen|motivation|relationship|dialogue', key):
        nums = (4, 5)  # Character Craft + Rules
    elif re.search(r'structure|pacing|reorder|scene.order|act.break|tempo', key):
        nums = (1, 2)  # Narrative Structure + Scene Craft
    elif re.search(r'continuity|timeline|consistency|fact.check', key):
        nums = ()       # No craft sections — continuity is factual
    else:
        nums = (2, 3, 5)  # Default: Scene Craft + Prose Craft + Rules

    if not nums:
        return ''
    return extract_craft_sections(*nums)


# ============================================================================
# Overrides injection
# ============================================================================

def _build_overrides_section(project_dir: str, pass_config: str) -> str:
    """Read scoring overrides and build the prompt section.

    If pass_config contains targets, filter overrides to those scene IDs.
    Otherwise include all overrides.
    """
    overrides_file = os.path.join(project_dir, 'working', 'scores', 'latest', 'overrides.csv')
    if not os.path.isfile(overrides_file):
        return ''

    rows = _read_pipe_csv(overrides_file)
    if not rows:
        return ''

    # Extract target scene IDs from pass_config
    target_ids: list[str] = []
    if pass_config:
        m = re.search(r'targets:\s*([^|]+)', pass_config)
        if m:
            raw = m.group(1).strip().strip('"')
            target_ids = [t.strip() for t in raw.split(';') if t.strip()]

    lines = []
    if target_ids:
        for row in rows:
            rid = row.get('id', '').strip()
            if rid in target_ids:
                principle = row.get('principle', '').strip()
                directive = row.get('directive', '').strip()
                if rid and principle and directive:
                    lines.append(f"- [{rid}] {principle}: {directive}")
    else:
        for row in rows:
            rid = row.get('id', '').strip()
            principle = row.get('principle', '').strip()
            directive = row.get('directive', '').strip()
            if rid and principle and directive:
                lines.append(f"- [{rid}] {principle}: {directive}")

    if not lines:
        return ''

    return (
        '\n## Scoring Overrides\n\n'
        'The following craft directives were approved during scoring. '
        'Apply them during this revision:\n\n'
        + '\n'.join(lines)
    )


# ============================================================================
# Prompt building
# ============================================================================

def build_revision_prompt(
    pass_name: str,
    purpose: str,
    scope: str,
    project_dir: str,
    pass_config: str = '',
    coaching_level: str = 'full',
    api_mode: bool = False,
) -> str:
    """Assemble the full revision prompt.

    When api_mode is True, inlines all scene content and reference files
    between marker tags and instructs Claude to output revised scenes with
    the same markers. When False, lists file paths for claude -p to read
    and includes git commit instructions.

    Args:
        pass_name: Short name for the revision pass (e.g., "prose-tightening").
        purpose: Human-readable purpose statement.
        scope: Scope specification (see resolve_scope).
        project_dir: Path to the novel project root.
        pass_config: Optional YAML block with pass configuration.
        coaching_level: One of "full", "coach", "strict".
        api_mode: If True, inline file content for API use.

    Returns:
        The assembled prompt as a string.
    """
    # Resolve scene files
    file_paths = resolve_scope(scope, project_dir)

    # Separate existing scenes from NEW: scenes to create
    existing_paths = []
    new_scene_ids = []
    for fpath in file_paths:
        basename = os.path.basename(fpath)
        if basename.startswith('NEW:'):
            new_scene_ids.append(os.path.splitext(basename[4:])[0])
        else:
            existing_paths.append(fpath)

    # Build file list block and optionally inline content
    file_lines = []
    inline_scenes = []
    for fpath in existing_paths:
        rel = os.path.relpath(fpath, project_dir)
        file_lines.append(f'- {rel}')
        if api_mode and os.path.isfile(fpath):
            scene_id = os.path.splitext(os.path.basename(fpath))[0]
            with open(fpath) as f:
                content = f.read()
            inline_scenes.append(
                f'\n=== SCENE: {scene_id} ===\n'
                f'{content}'
                f'\n=== END SCENE: {scene_id} ==='
            )

    # Add new scene creation targets to file list
    for sid in new_scene_ids:
        file_lines.append(f'- scenes/{sid}.md (NEW — to be created)')

    file_block = '\n'.join(file_lines)
    file_count = len(existing_paths) + len(new_scene_ids)

    # Intent-beat protection: load intent for in-scope scenes
    intent_section = ''
    intent_path = os.path.join(project_dir, 'reference', 'scene-intent.csv')
    briefs_path = os.path.join(project_dir, 'reference', 'scene-briefs.csv')
    if os.path.isfile(intent_path) or os.path.isfile(briefs_path):
        intent_lines = [
            '\n## Intent-Beat Protection\n',
            '**CRITICAL:** Before cutting or rewriting the final 30% of any scene, verify that '
            'all intent beats survive. Each scene has structural beats specified below that MUST '
            'be present in the revised scene. If a pattern rule (e.g., "cut summary closers") '
            'conflicts with an intent beat, preserve the intent beat and find another way to '
            'address the pattern.\n',
        ]
        # Get scene IDs from existing paths
        scope_ids = [os.path.splitext(os.path.basename(p))[0] for p in existing_paths]

        # Load intent and briefs data
        from storyforge.csv_cli import get_field
        for sid in scope_ids:
            beat_parts = []
            if os.path.isfile(briefs_path):
                for field in ('key_actions', 'key_dialogue', 'outcome'):
                    val = get_field(briefs_path, sid, field).strip()
                    if val:
                        beat_parts.append(f'  - **{field}:** {val}')
            if os.path.isfile(intent_path):
                tp = get_field(intent_path, sid, 'turning_point').strip()
                if tp:
                    beat_parts.append(f'  - **turning_point:** {tp}')
            if beat_parts:
                intent_lines.append(f'\n**{sid}:**')
                intent_lines.extend(beat_parts)

        if len(intent_lines) > 2:  # More than just header
            intent_section = '\n'.join(intent_lines)

    # New scene creation instructions
    new_scenes_section = ''
    if new_scene_ids:
        new_list = '\n'.join(f'- `scenes/{sid}.md`' for sid in new_scene_ids)
        new_scenes_section = (
            '\n## New Scenes to Create\n\n'
            'The following scenes do not yet exist. **Create** them as new files '
            '(do not look for existing content to revise):\n\n'
            f'{new_list}\n\n'
            'Write each scene following the voice guide, scene intent, and any '
            'guidance in the pass configuration. Each scene should be pure prose '
            'markdown with no YAML frontmatter.\n'
        )

    # Inline reference files for API mode
    inline_references = ''
    if api_mode:
        ref_files = [
            'reference/voice-guide.md',
            'reference/scenes.csv',
        ]
        ref_parts = []
        for ref in ref_files:
            ref_path = os.path.join(project_dir, ref)
            if os.path.isfile(ref_path):
                with open(ref_path) as f:
                    ref_content = f.read()
                ref_parts.append(
                    f'\n=== FILE: {ref} ===\n'
                    f'{ref_content}'
                    f'\n=== END FILE ==='
                )
        inline_references = '\n'.join(ref_parts) if ref_parts else 'No reference files found.'

    # Pass configuration section
    config_section = ''
    if pass_config:
        config_section = (
            '\n## Pass Configuration\n\n'
            "The full configuration for this revision pass from the author's revision plan.\n"
            'Follow all targets, guidance, and protection lists precisely:\n\n'
            f'```yaml\n{pass_config}\n```\n\n'
            '**Protection list:** Any items marked "do not touch" must be preserved exactly as-is. '
            'Do not edit protected passages.\n\n'
            '**Targets:** If specific reduction percentages or instance counts are given, '
            'aim for those numbers. Track your progress.'
        )

    # Scoring overrides
    overrides_section = _build_overrides_section(project_dir, pass_config)

    # Craft sections
    craft_text = _select_craft_sections(pass_name, purpose)
    craft_section = ''
    if craft_text:
        craft_section = (
            '\n## Craft Principles for This Pass\n\n'
            'The following craft principles are relevant to this revision pass. '
            'Let them guide your edits — do not reproduce them in the output, '
            'but let them inform every editorial decision.\n\n'
            + craft_text
        )

    # Scoring rubrics for targeted principles — shows what each score level
    # looks like with literary exemplars, so the reviser knows what to aim for
    targeted_principles = _extract_pass_principles(pass_config, purpose)
    rubric_section = ''
    if targeted_principles:
        rubric_text = _load_rubric_sections(targeted_principles)
        if rubric_text:
            rubric_section = (
                '\n## Scoring Rubrics for Targeted Principles\n\n'
                'These rubrics define what each score level looks like for the '
                'principles this pass is targeting. Use them to understand what '
                '"good" means — aim for level 4-5 qualities, eliminate level 1-2 '
                'patterns. The literary exemplars show the standard.\n\n'
                + rubric_text
            )

    # Author exemplars — the author's own high-scoring passages from this
    # manuscript, showing what the target quality looks like in their voice
    exemplar_section = ''
    if targeted_principles:
        exemplar_text = _load_author_exemplars(project_dir, targeted_principles)
        if exemplar_text:
            exemplar_section = (
                '\n## Author Exemplars\n\n'
                'These are passages from THIS manuscript that scored highly on '
                'the targeted principles. They show what the target quality looks '
                'like in this author\'s voice. Use them as a reference point — '
                'revised prose should feel like it belongs alongside these passages.\n\n'
                + exemplar_text
            )

    # --- Assemble the prompt ---
    parts = [
        f'# Revision Pass: {pass_name}\n',
        f'## Purpose\n\n{purpose}\n',
        f'## Scope\n\nThis pass covers {file_count} scene file(s):\n\n{file_block}',
        config_section,
        intent_section,
        new_scenes_section,
        overrides_section,
        craft_section,
        rubric_section,
        exemplar_section,
    ]

    # Mode-specific instructions
    if api_mode:
        parts.append(
            f'\n## Reference Context\n\n{inline_references}\n'
            f'\n## Scene Content\n\n'
            'Below are the full contents of every in-scope scene file. '
            'Read them all before making changes.\n'
            + '\n'.join(inline_scenes)
        )
        parts.append('\n## Instructions\n\n'
                      'You are performing a revision pass on a novel manuscript. '
                      'Apply the revision purpose stated above to the scene files provided.')
        parts.append(_api_output_format_block())
    else:
        parts.append(_claudep_read_instructions())

    # Coaching-level-specific instructions
    parts.append(_coaching_instructions(
        coaching_level, pass_name, purpose, api_mode
    ))

    return '\n'.join(p for p in parts if p)


# ============================================================================
# Prompt section builders (private)
# ============================================================================

def _api_output_format_block() -> str:
    return (
        '\n### Output Format\n\n'
        'For EACH scene you modify, output the complete revised scene using this exact format:\n\n'
        '```\n'
        '=== SCENE: scene-id ===\n'
        '[complete revised scene prose — the ENTIRE file content, not just changed parts]\n'
        '=== END SCENE: scene-id ===\n'
        '```\n\n'
        '**CRITICAL:** Output the COMPLETE file content for every modified scene. '
        'Do not use ellipsis, "[rest unchanged]", or partial content. '
        'If you change even one word in a scene, output the entire scene.\n\n'
        'Only output scenes you actually changed — skip scenes that need no edits for this pass. '
        'Always output newly created scenes using the same marker format.\n'
    )


def _claudep_read_instructions() -> str:
    return (
        '\n## Instructions\n\n'
        'You are performing a revision pass on a novel manuscript. Follow these rules precisely:\n\n'
        '### 1. Read Reference Context First\n\n'
        'Before making any changes, read these reference files to understand the project\'s '
        'voice and continuity state:\n\n'
        '- `reference/voice-guide.md` — the established voice rules, prose style, and '
        'per-character dialogue fingerprints. Every edit you make must be consistent with this guide.\n'
        '- `reference/scenes.csv` — the master scene list for structural context.\n'
        '- `reference/scene-intent.csv` — narrative dynamics, MICE threads, and character presence.\n'
        '- `reference/knowledge.csv` — canonical knowledge facts for continuity checking.\n\n'
        '### 2. Read All In-Scope Scene Files\n\n'
        'Read every scene file listed above in full before making changes. '
        'Understand the narrative arc across these scenes before editing any individual scene.\n'
    )


def _coaching_instructions(coaching_level: str, pass_name: str, purpose: str,
                           api_mode: bool) -> str:
    """Build coaching-level-specific instruction sections."""
    if coaching_level == 'coach':
        return _coach_instructions(pass_name, purpose, api_mode)
    elif coaching_level == 'strict':
        return _strict_instructions(pass_name, purpose, api_mode)
    else:
        return _full_instructions(pass_name, purpose, api_mode)


def _coach_instructions(pass_name: str, purpose: str, api_mode: bool) -> str:
    parts = [
        '\n### Produce Editorial Notes\n\n'
        'You are in COACH mode. Do NOT edit scene files. Do NOT change any prose.\n\n'
        'For each in-scope scene file, produce editorial notes for the revision purpose:\n\n'
        f'> {purpose}\n\n'
        'If a pass configuration was provided above, analyze each scene against its targets, '
        'guidance, and protection lists. Document what you find — what needs to change, why, '
        'and how the author might approach it.\n\n'
        'Your notes should include:\n'
        '- Specific passages that need attention (quote them)\n'
        '- What is wrong or could be improved and why\n'
        '- Concrete suggestions for how to revise (but do not make the edits)\n'
        '- Voice preservation warnings — places where revision could damage the voice\n'
        '- Continuity implications of potential changes'
    ]

    if api_mode:
        parts.append('\n\nOutput your editorial notes directly as markdown.')
    else:
        parts.append(
            f'\n\nSave to: `working/coaching/{pass_name}-notes.md`\n\n'
            'Then commit and push:\n'
            '```\n'
            'mkdir -p working/coaching\n'
            f'git add working/coaching/{pass_name}-notes.md\n'
            f'git commit -m "Coach: editorial notes for {pass_name}"\n'
            'git push\n'
            '```'
        )

    parts.append(
        '\n\n### Post-Pass Summary\n\n'
        'Print a structured summary:\n'
        '- **Scenes analyzed:** List each scene file reviewed\n'
        '- **Key findings:** Most important editorial observations\n'
        '- **Target assessment:** For each target in the pass configuration, '
        'report current state and what needs to change\n'
        '- **Priority edits:** Which changes would have the most impact, in order\n'
        '- **Voice risks:** Where the revision is most likely to damage voice if not careful\n'
        '- **Intent-beat verification:** Confirm all intent beats from the protection list are present in revised scenes\n'
        '- **Issues discovered:** Anything that may need a separate pass'
    )

    return ''.join(parts)


def _strict_instructions(pass_name: str, purpose: str, api_mode: bool) -> str:
    parts = [
        '\n### Produce Revision Checklist\n\n'
        'You are in STRICT mode. Do NOT edit scene files. '
        'Do NOT provide editorial suggestions or craft guidance.\n\n'
        'For each in-scope scene file, produce a checklist of which revision targets apply where:\n\n'
        f'> {purpose}\n\n'
        'If a pass configuration was provided above, check each scene against its targets. '
        'Report facts only — which targets apply to which scenes, with line references.\n\n'
        'Your checklist should include:\n'
        '- Which targets from the pass configuration apply to which scenes\n'
        '- Specific locations (with quotes) where targets are relevant\n'
        '- Current counts or measurements for quantitative targets\n'
        '- Protection list verification — confirm protected passages are identified'
    ]

    if api_mode:
        parts.append('\n\nOutput your checklist directly as markdown.')
    else:
        parts.append(
            f'\n\nSave to: `working/coaching/{pass_name}-checklist.md`\n\n'
            'Then commit and push:\n'
            '```\n'
            'mkdir -p working/coaching\n'
            f'git add working/coaching/{pass_name}-checklist.md\n'
            f'git commit -m "Strict: revision checklist for {pass_name}"\n'
            'git push\n'
            '```'
        )

    parts.append(
        '\n\n### Post-Pass Summary\n\n'
        'Print a structured summary:\n'
        '- **Scenes analyzed:** List each scene file reviewed\n'
        '- **Target counts:** For each target, the current measurement per scene\n'
        '- **Applicable locations:** How many locations per scene per target\n'
        '- **Protected passages:** Confirmed locations of all protected passages'
    )

    return ''.join(parts)


def _full_instructions(pass_name: str, purpose: str, api_mode: bool) -> str:
    if api_mode:
        return (
            '\n### Apply the Revision\n\n'
            'For each in-scope scene, apply the revision purpose stated above:\n\n'
            f'> {purpose}\n\n'
            'If a pass configuration was provided above, follow its targets, guidance, '
            'and protection lists precisely. These represent the author\'s intent — '
            'execute on them, do not second-guess them.\n\n'
            '### Preserve Voice and Discriminate Cuts\n\n'
            'Every edit must be consistent with the voice guide provided in the reference context '
            'above. The voice guide defines each POV character\'s sentence patterns, metaphor '
            'domains, and emotional registers. Before cutting or rewriting any passage, identify '
            'which character\'s voice is active and what the voice guide says about that voice.\n\n'
            '**What "kill darlings" means — and what it does not:**\n\n'
            'CUT these (they serve the writer, not the story):\n'
            '- Restated metaphors: a second sentence that says the same thing in different imagery\n'
            '- Interpretive tags after shown emotion: "She felt the weight of it" when the weight '
            'was already dramatized through action or physical sensation\n'
            '- Throat-clearing: "And then," "After a moment," "She realized that," '
            '"It was clear that," "began to"\n'
            '- Ornamental elaboration that delays the scene without advancing character or theme\n'
            '- Passages where cutting loses no meaning — the surrounding prose already conveys it\n\n'
            'DO NOT CUT these (they serve the story):\n'
            '- The sentence that delivers the scene\'s value shift or thematic thesis\n'
            '- Character-specific diction that the voice guide identifies as that character\'s '
            'pattern (e.g., engineering metaphors for an engineer, food metaphors for a cook, '
            'polysyndetic chains in a voice that builds through accumulation)\n'
            '- Physical sensation markers that externalize internal state — these are showing, '
            'not telling\n'
            '- Closing images that are the scene\'s earned payoff (a concrete image is not a '
            '"summary closer" — only cut closers that restate the scene\'s meaning abstractly)\n'
            '- Lyrical extensions at emotional peaks when the voice guide says this voice earns '
            'lyricism through contrast with its default spare register\n\n'
            '**Test before cutting:** If a sentence is doing voice work (matching a pattern the '
            'voice guide explicitly calls for) AND advancing the scene\'s emotional or thematic '
            'arc, it is not a darling. Improve it if the phrasing is weak, but do not delete it.\n\n'
            '### Prose Naturalness\n\n'
            'Em dashes are rare — use at most one per scene. Default to commas, parentheses, or '
            'sentence breaks. No antithesis framing — do not structure observations as contrasting '
            'pairs where the first element is negated and the second affirmed. Let contrast emerge '
            'from content, not rhetorical formula. Do not default to tricolon or parallel structure. '
            'Vary sentence and paragraph length. Use contractions in interiority and dialogue. '
            'Do not introduce these patterns during revision even if the original prose was free '
            'of them.\n\n'
            '### Maintain Continuity\n\n'
            'Do not create contradictions with other scenes. Consult the continuity tracker in '
            'the reference context above before changing any plot-relevant detail.\n\n'
            '### Output Your Revisions\n\n'
            'For EACH scene you modify, output the complete revised scene using this exact format:\n\n'
            '```\n'
            '=== SCENE: scene-id ===\n'
            '[complete revised scene prose — the ENTIRE file content, not just changed parts]\n'
            '=== END SCENE: scene-id ===\n'
            '```\n\n'
            '**CRITICAL:** Output the COMPLETE file content for every modified scene. '
            'Do not use ellipsis, "[rest unchanged]", or partial content. '
            'If you change even one word in a scene, output the entire scene.\n\n'
            'Only output scenes you actually changed. Skip scenes that need no edits for this pass.\n\n'
            '### Post-Pass Summary\n\n'
            'After all revised scenes, print a structured summary:\n'
            '- **Files modified:** List each scene that was changed\n'
            '- **Changes made:** Brief description of the kinds of edits applied\n'
            '- **Target progress:** For each target in the pass configuration, '
            'report how close you came\n'
            '- **Protected passages:** Confirm all protected passages were left untouched\n'
            '- **Intent-beat verification:** Confirm all intent beats from the protection list are present in revised scenes\n'
            '- **Net word count change:** Approximate words added or removed\n'
            '- **Issues discovered:** Anything that may need a separate pass'
        )
    else:
        return (
            '\n### 3. Apply the Revision\n\n'
            'For each in-scope scene file, apply the revision purpose stated above:\n\n'
            f'> {purpose}\n\n'
            'If a pass configuration was provided above, follow its targets, guidance, '
            'and protection lists precisely. These represent the author\'s intent — '
            'execute on them, do not second-guess them.\n\n'
            'Work through each file methodically. Make edits directly to the scene files.\n\n'
            '### 4. Preserve Voice and Discriminate Cuts\n\n'
            'Every edit must be consistent with the voice guide. The voice guide defines each '
            'POV character\'s sentence patterns, metaphor domains, and emotional registers. '
            'Before cutting or rewriting any passage, identify which character\'s voice is active '
            'and what the voice guide says about that voice.\n\n'
            '**What "kill darlings" means — and what it does not:**\n\n'
            'CUT these (they serve the writer, not the story):\n'
            '- Restated metaphors: a second sentence that says the same thing in different imagery\n'
            '- Interpretive tags after shown emotion: "She felt the weight of it" when the weight '
            'was already dramatized through action or physical sensation\n'
            '- Throat-clearing: "And then," "After a moment," "She realized that," '
            '"It was clear that," "began to"\n'
            '- Ornamental elaboration that delays the scene without advancing character or theme\n'
            '- Passages where cutting loses no meaning — the surrounding prose already conveys it\n\n'
            'DO NOT CUT these (they serve the story):\n'
            '- The sentence that delivers the scene\'s value shift or thematic thesis\n'
            '- Character-specific diction that the voice guide identifies as that character\'s '
            'pattern (e.g., engineering metaphors for an engineer, food metaphors for a cook, '
            'polysyndetic chains in a voice that builds through accumulation)\n'
            '- Physical sensation markers that externalize internal state — these are showing, '
            'not telling\n'
            '- Closing images that are the scene\'s earned payoff (a concrete image is not a '
            '"summary closer" — only cut closers that restate the scene\'s meaning abstractly)\n'
            '- Lyrical extensions at emotional peaks when the voice guide says this voice earns '
            'lyricism through contrast with its default spare register\n\n'
            '**Test before cutting:** If a sentence is doing voice work (matching a pattern the '
            'voice guide explicitly calls for) AND advancing the scene\'s emotional or thematic '
            'arc, it is not a darling. Improve it if the phrasing is weak, but do not delete it.\n\n'
            '### 5. Prose Naturalness\n\n'
            'Em dashes are rare — use at most one per scene. Default to commas, parentheses, or '
            'sentence breaks. No antithesis framing — do not structure observations as contrasting '
            'pairs where the first element is negated and the second affirmed. Let contrast emerge '
            'from content, not rhetorical formula. Do not default to tricolon or parallel structure. '
            'Vary sentence and paragraph length. Use contractions in interiority and dialogue. '
            'Do not introduce these patterns during revision even if the original prose was free '
            'of them.\n\n'
            '### 6. Maintain Continuity\n\n'
            'If your edits change any plot-relevant detail — character knowledge, physical state, '
            'timeline position, object presence, setting detail — update the continuity tracker '
            'to reflect the change. Do not create contradictions with other scenes '
            '(including those outside this pass\'s scope).\n\n'
            f'### 7. Commit and Push\n\n'
            'After completing all edits for this pass, stage and commit your changes:\n\n'
            '```\n'
            'git add scenes/ reference/ 2>/dev/null\n'
            f'git commit -m "Revision: {pass_name}"\n'
            'git push\n'
            '```\n\n'
            'This is required — the author follows progress by pulling commits as you work.\n\n'
            '### 8. Post-Pass Summary\n\n'
            'After completing all edits, print a structured summary:\n'
            '- **Files modified:** List each file that was changed\n'
            '- **Changes made:** Brief description of the kinds of edits applied\n'
            '- **Target progress:** For each target in the pass configuration, '
            'report how close you came (e.g., "architecture metaphor: reduced from ~85 to ~32 instances")\n'
            '- **Protected passages:** Confirm all protected passages were left untouched\n'
            '- **Intent-beat verification:** Confirm all intent beats from the protection list are present in revised scenes\n'
            '- **Continuity updates:** Any changes to the continuity tracker\n'
            '- **Net word count change:** Approximate words added or removed '
            '(e.g., "+1,200" or "-800")\n'
            '- **Issues discovered:** Anything that may need a separate pass'
        )


# ============================================================================
# Change verification
# ============================================================================

def verify_revision_changes(head_before: str, project_dir: str) -> bool:
    """Check if a revision pass produced changes.

    Checks for new commits since head_before, uncommitted changes
    (staged or unstaged), and untracked files in scenes/ or reference/.

    Args:
        head_before: Git commit hash recorded before the pass started.
        project_dir: Path to the project root.

    Returns:
        True if changes exist, False if the pass produced no changes.
    """
    import subprocess

    def _git(*args: str) -> str:
        try:
            result = subprocess.run(
                ['git', '-C', project_dir] + list(args),
                capture_output=True, text=True, timeout=10,
            )
            return result.stdout.strip()
        except (subprocess.TimeoutExpired, FileNotFoundError):
            return ''

    def _git_rc(*args: str) -> int:
        try:
            result = subprocess.run(
                ['git', '-C', project_dir] + list(args),
                capture_output=True, text=True, timeout=10,
            )
            return result.returncode
        except (subprocess.TimeoutExpired, FileNotFoundError):
            return 1

    # Check for new commits
    head_now = _git('rev-parse', 'HEAD')
    if head_now and head_now != head_before:
        return True

    # Check for uncommitted changes (staged or unstaged)
    if _git_rc('diff', '--quiet') != 0:
        return True
    if _git_rc('diff', '--cached', '--quiet') != 0:
        return True

    # Check for untracked files in scenes/ or reference/
    untracked = _git('ls-files', '--others', '--exclude-standard',
                      '--', 'scenes/', 'reference/')
    if untracked:
        return True

    return False


# ============================================================================
# CLI interface
# ============================================================================

def main():
    """CLI entry point. Usage:

    python3 -m storyforge.revision build-prompt <pass_name> <purpose> <scope> <project_dir> [options]
    python3 -m storyforge.revision resolve-scope <scope> <project_dir>

    Options for build-prompt:
        --config <yaml_block>           Pass configuration YAML
        --coaching full|coach|strict    Coaching level (default: full)
        --api-mode                      Inline files for API use
    """
    if len(sys.argv) < 2:
        print('Usage: python3 -m storyforge.revision <command> [args]', file=sys.stderr)
        sys.exit(1)

    command = sys.argv[1]

    if command == 'resolve-scope':
        if len(sys.argv) < 4:
            print('Usage: resolve-scope <scope> <project_dir>', file=sys.stderr)
            sys.exit(1)
        scope = sys.argv[2]
        project_dir = sys.argv[3]
        try:
            paths = resolve_scope(scope, project_dir)
            for p in paths:
                print(p)
        except (FileNotFoundError, ValueError) as e:
            print(f'ERROR: {e}', file=sys.stderr)
            sys.exit(1)

    elif command == 'build-prompt':
        if len(sys.argv) < 6:
            print('Usage: build-prompt <pass_name> <purpose> <scope> <project_dir> [options]',
                  file=sys.stderr)
            sys.exit(1)

        pass_name = sys.argv[2]
        purpose = sys.argv[3]
        scope = sys.argv[4]
        project_dir = sys.argv[5]

        # Parse optional flags
        pass_config = ''
        coaching_level = 'full'
        api_mode = False
        i = 6
        while i < len(sys.argv):
            if sys.argv[i] == '--config' and i + 1 < len(sys.argv):
                pass_config = sys.argv[i + 1]
                i += 2
            elif sys.argv[i] == '--coaching' and i + 1 < len(sys.argv):
                coaching_level = sys.argv[i + 1]
                i += 2
            elif sys.argv[i] == '--api-mode':
                api_mode = True
                i += 1
            else:
                print(f'Unknown option: {sys.argv[i]}', file=sys.stderr)
                sys.exit(1)

        try:
            prompt = build_revision_prompt(
                pass_name, purpose, scope, project_dir,
                pass_config=pass_config,
                coaching_level=coaching_level,
                api_mode=api_mode,
            )
            print(prompt)
        except (FileNotFoundError, ValueError) as e:
            print(f'ERROR: {e}', file=sys.stderr)
            sys.exit(1)

    elif command == 'verify-changes':
        # Usage: verify-changes <head_before> <project_dir>
        if len(sys.argv) < 4:
            print('Usage: verify-changes <head_before> <project_dir>',
                  file=sys.stderr)
            sys.exit(1)
        head_before = sys.argv[2]
        project_dir = sys.argv[3]
        has_changes = verify_revision_changes(head_before, project_dir)
        if has_changes:
            print('changes')
            sys.exit(0)
        else:
            print('no-changes')
            sys.exit(1)

    else:
        print(f'Unknown command: {command}', file=sys.stderr)
        sys.exit(1)


if __name__ == '__main__':
    main()
