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
# Metadata CSV helpers
# ============================================================================

def _read_pipe_csv(csv_path: str) -> list[dict]:
    """Read a pipe-delimited CSV file into a list of dicts."""
    rows = []
    with open(csv_path) as f:
        reader = csv.DictReader(f, delimiter='|')
        for row in reader:
            rows.append(row)
    return rows


def _find_metadata_csv(project_dir: str) -> str:
    """Locate the scene metadata CSV, checking both canonical and legacy paths."""
    canonical = os.path.join(project_dir, 'reference', 'scene-metadata.csv')
    if os.path.isfile(canonical):
        return canonical
    legacy = os.path.join(project_dir, 'scenes', 'metadata.csv')
    if os.path.isfile(legacy):
        return legacy
    raise FileNotFoundError('scene-metadata.csv not found in reference/ or scenes/')


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
    csv_path = _find_metadata_csv(project_dir)
    scene_dir = os.path.join(project_dir, 'scenes')
    rows = _read_pipe_csv(csv_path)

    # Filter out cut scenes and sort by seq
    active_rows = [r for r in rows if r.get('type', '').strip() != 'cut']
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
        # Comma-separated list — detect if all numeric (seq numbers)
        parts = [s.strip() for s in scope.split(',') if s.strip()]
        all_numeric = all(p.isdigit() for p in parts)

        if all_numeric:
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

    # Resolve IDs to file paths
    matched = []
    for sid in target_ids:
        path = resolve_scene_file(scene_dir, sid)
        if path:
            matched.append(path)
        else:
            print(f"WARNING: Scene file missing for id '{sid}': {scene_dir}/{sid}.md",
                  file=sys.stderr)

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
            scene_id = row.get('id', row.get(list(row.keys())[0], '')).strip()
            if scene_id in target_ids:
                # Columns: id, principle, directive (or similar)
                cols = list(row.values())
                if len(cols) >= 3:
                    lines.append(f"- [{cols[0].strip()}] {cols[1].strip()}: {cols[2].strip()}")
    else:
        for row in rows:
            cols = list(row.values())
            if len(cols) >= 3:
                lines.append(f"- [{cols[0].strip()}] {cols[1].strip()}: {cols[2].strip()}")

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
    file_count = len(file_paths)

    # Build file list block and optionally inline content
    file_lines = []
    inline_scenes = []
    for fpath in file_paths:
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

    file_block = '\n'.join(file_lines)

    # Inline reference files for API mode
    inline_references = ''
    if api_mode:
        ref_files = [
            'reference/voice-guide.md',
            'reference/continuity-tracker.md',
            'reference/scene-metadata.csv',
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

    # --- Assemble the prompt ---
    parts = [
        f'# Revision Pass: {pass_name}\n',
        f'## Purpose\n\n{purpose}\n',
        f'## Scope\n\nThis pass covers {file_count} scene file(s):\n\n{file_block}',
        config_section,
        overrides_section,
        craft_section,
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
        'Only output scenes you actually changed. Skip scenes that need no edits for this pass.\n'
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
        '- `reference/continuity-tracker.md` — the living ledger of continuity facts, promises, '
        'and threads. Consult this before changing any plot-relevant detail.\n'
        '- `reference/scene-metadata.csv` — the master scene list for structural context.\n\n'
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
            '### Preserve Voice\n\n'
            'Every edit must be consistent with the voice guide provided in the reference context '
            'above. Do not flatten distinctive character voices. Do not introduce vocabulary, '
            'rhythms, or registers that violate the established style. When in doubt, preserve '
            'the original phrasing.\n\n'
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
            '### 4. Preserve Voice\n\n'
            'Every edit must be consistent with the voice guide. Do not flatten distinctive '
            'character voices. Do not introduce vocabulary, rhythms, or registers that violate '
            'the established style. When in doubt, preserve the original phrasing.\n\n'
            '### 5. Maintain Continuity\n\n'
            'If your edits change any plot-relevant detail — character knowledge, physical state, '
            'timeline position, object presence, setting detail — update the continuity tracker '
            'to reflect the change. Do not create contradictions with other scenes '
            '(including those outside this pass\'s scope).\n\n'
            f'### 6. Commit and Push\n\n'
            'After completing all edits for this pass, stage and commit your changes:\n\n'
            '```\n'
            'git add scenes/ reference/ 2>/dev/null\n'
            f'git commit -m "Revision: {pass_name}"\n'
            'git push\n'
            '```\n\n'
            'This is required — the author follows progress by pulling commits as you work.\n\n'
            '### 7. Post-Pass Summary\n\n'
            'After completing all edits, print a structured summary:\n'
            '- **Files modified:** List each file that was changed\n'
            '- **Changes made:** Brief description of the kinds of edits applied\n'
            '- **Target progress:** For each target in the pass configuration, '
            'report how close you came (e.g., "architecture metaphor: reduced from ~85 to ~32 instances")\n'
            '- **Protected passages:** Confirm all protected passages were left untouched\n'
            '- **Continuity updates:** Any changes to the continuity tracker\n'
            '- **Net word count change:** Approximate words added or removed '
            '(e.g., "+1,200" or "-800")\n'
            '- **Issues discovered:** Anything that may need a separate pass'
        )


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

    else:
        print(f'Unknown command: {command}', file=sys.stderr)
        sys.exit(1)


if __name__ == '__main__':
    main()
