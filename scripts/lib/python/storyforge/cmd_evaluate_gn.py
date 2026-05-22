"""storyforge evaluate (graphic-novel mode) — 3-persona LLM evaluation panel.

Runs three evaluator personas (panel-composition, pacing, dialogue) against
drafted panel scripts and writes per-scene JSON findings files.

Usage (identical CLI surface to novel-mode evaluate):
    storyforge evaluate                        # all drafted scenes, all 3 personas
    storyforge evaluate scene-id               # one scene
    storyforge evaluate --scenes a,b,c
    storyforge evaluate --personas panel-composition,pacing  # filter
    storyforge evaluate --dry-run
"""

import argparse
import json
import os
import re
import sys
from datetime import datetime, timezone

from storyforge.common import (
    detect_project_root, log, set_log_file, select_model,
    install_signal_handlers, get_medium, get_plugin_dir,
)
from storyforge.csv_cli import get_field, get_row, list_ids
from storyforge.scene_filter import build_scene_list, apply_scene_filter
from storyforge.api import invoke_to_file, extract_text_from_file
from storyforge.costs import log_operation


# ---------------------------------------------------------------------------
# Arg parsing
# ---------------------------------------------------------------------------

def parse_args(argv):
    parser = argparse.ArgumentParser(
        prog='storyforge evaluate',
        description='Run 3-persona evaluation panel against GN panel scripts.',
    )
    parser.add_argument('positional', nargs='*', default=[],
                        help='Scene ID(s) to evaluate')
    parser.add_argument('--dry-run', action='store_true',
                        help='Show what would be evaluated without calling the API')
    parser.add_argument('--scenes', type=str, default=None,
                        help='Comma-separated scene IDs')
    parser.add_argument('--act', '--part', type=str, default=None,
                        help='Evaluate all scenes in act/part N')
    parser.add_argument('--from-seq', type=str, default=None,
                        help='Start from sequence number (N or N-M range)')
    parser.add_argument('--personas', type=str, default=None,
                        help='Comma-separated persona names to run '
                             '(default: all discovered)')
    return parser.parse_args(argv)


# ---------------------------------------------------------------------------
# CSV row helper (mirrors cmd_write_gn._row_to_dict)
# ---------------------------------------------------------------------------

def _row_to_dict(csv_path, row_id):
    """Read a CSV row by ID and return as a dict. Returns {} if not found."""
    if not os.path.isfile(csv_path):
        return {}
    with open(csv_path, newline='', encoding='utf-8') as f:
        raw = f.read().replace('\r\n', '\n').replace('\r', '')
    lines = raw.splitlines()
    if not lines:
        return {}
    headers = lines[0].split('|')
    for line in lines[1:]:
        fields = line.split('|')
        if fields and fields[0] == row_id:
            return dict(zip(headers, fields))
    return {}


# ---------------------------------------------------------------------------
# Persona discovery
# ---------------------------------------------------------------------------

def _discover_personas(plugin_dir):
    """List persona names from evaluators-gn/*.md.

    Returns list of (persona_name, prompt_file_path) tuples.
    Persona name is derived from the filename stem by stripping '-critic'.

    E.g. panel-composition-critic.md -> 'panel-composition'
    """
    evaluators_dir = os.path.join(plugin_dir, 'scripts', 'prompts', 'evaluators-gn')
    if not os.path.isdir(evaluators_dir):
        log(f'ERROR: evaluators-gn directory not found: {evaluators_dir}')
        return []

    personas = []
    for fname in sorted(os.listdir(evaluators_dir)):
        if not fname.endswith('.md'):
            continue
        stem = fname[:-3]  # strip .md
        # Strip trailing '-critic' suffix to get the persona name
        if stem.endswith('-critic'):
            persona_name = stem[:-7]  # strip '-critic'
        else:
            persona_name = stem
        prompt_path = os.path.join(evaluators_dir, fname)
        personas.append((persona_name, prompt_path))

    return personas


# ---------------------------------------------------------------------------
# Bibles and voice loading
# ---------------------------------------------------------------------------

def _build_visual_refs(project_dir):
    """Read character-bible.md and world-bible.md for visual reference."""
    ref_dir = os.path.join(project_dir, 'reference')
    chars_path = os.path.join(ref_dir, 'character-bible.md')
    world_path = os.path.join(ref_dir, 'world-bible.md')
    char_text = open(chars_path, encoding='utf-8').read() if os.path.isfile(chars_path) else ''
    world_text = open(world_path, encoding='utf-8').read() if os.path.isfile(world_path) else ''
    return char_text, world_text


def _build_voice_text(project_dir):
    """Read voice-profile.csv as raw text for the prompt."""
    voice_path = os.path.join(project_dir, 'reference', 'voice-profile.csv')
    if os.path.isfile(voice_path):
        return open(voice_path, encoding='utf-8').read()
    return ''


# ---------------------------------------------------------------------------
# Prompt building
# ---------------------------------------------------------------------------

def _build_evaluation_prompt(scene_id, scene_row, intent_row, brief_row,
                              script_text, char_text, world_text, voice_text):
    """Build the user prompt for a single (scene, persona) evaluation call."""
    parts = []

    # Scene metadata block
    parts.append('## Scene Metadata')
    parts.append(f'- **scene_id:** {scene_id}')
    parts.append(f'- **title:** {scene_row.get("title", "")}')
    parts.append(f'- **target_pages:** {scene_row.get("target_pages", "")}')
    parts.append(f'- **pov:** {scene_row.get("pov", "")}')
    parts.append(f'- **location:** {scene_row.get("location", "")}')
    parts.append(f'- **type:** {scene_row.get("type", "")}')
    parts.append('')

    # Intent
    if intent_row:
        parts.append('## Scene Intent')
        for k, v in intent_row.items():
            if k != 'id' and v:
                parts.append(f'- **{k}:** {v}')
        parts.append('')

    # Brief (the scene contract — persona uses this to evaluate fidelity)
    if brief_row:
        parts.append('## Scene Brief')
        for k, v in brief_row.items():
            if k != 'id' and v:
                parts.append(f'- **{k}:** {v}')
        parts.append('')

    # Visual references
    if char_text:
        parts.append('## Character Bible')
        parts.append(char_text.strip())
        parts.append('')

    if world_text:
        parts.append('## World Bible')
        parts.append(world_text.strip())
        parts.append('')

    if voice_text:
        parts.append('## Voice Profile')
        parts.append(voice_text.strip())
        parts.append('')

    # The script itself
    parts.append('## Panel Script')
    parts.append(script_text.strip())
    parts.append('')

    parts.append(
        'Evaluate the script above according to your persona\'s focus areas. '
        'Return a JSON object with a single top-level key `findings` '
        '(an array of finding objects as specified in your persona description). '
        'Set `scene_id` on every finding to: ' + json.dumps(scene_id)
    )

    return '\n'.join(parts)


# ---------------------------------------------------------------------------
# JSON findings parsing
# ---------------------------------------------------------------------------

def _parse_findings(response_text, persona_name, scene_id):
    """Extract the findings array from a persona's API response.

    Tries:
      1. Direct json.loads
      2. Fenced block extraction (```json ... ``` or ``` ... ```)
      3. Log warning and return [] on failure
    """
    if not response_text:
        log(f'  WARNING [{persona_name}]: empty response for {scene_id}')
        return []

    # Attempt 1: direct parse
    try:
        data = json.loads(response_text)
        findings = data.get('findings', [])
        # Ensure scene_id is stamped on each finding
        for f in findings:
            f.setdefault('scene_id', scene_id)
        return findings
    except (json.JSONDecodeError, AttributeError):
        pass

    # Attempt 2: extract from fenced code block (```json ... ``` or ``` ... ```)
    # The block may contain nested JSON objects, so we take everything inside the fences.
    fenced = re.search(r'```(?:json)?\s*\n(.*?)\n```', response_text, re.DOTALL)
    if fenced:
        try:
            data = json.loads(fenced.group(1).strip())
            findings = data.get('findings', [])
            for f in findings:
                f.setdefault('scene_id', scene_id)
            return findings
        except (json.JSONDecodeError, AttributeError):
            pass

    log(f'  WARNING [{persona_name}]: could not parse JSON findings for {scene_id} '
        f'— skipping this persona\'s contribution')
    return []


# ---------------------------------------------------------------------------
# Scene resolution
# ---------------------------------------------------------------------------

def _resolve_target_scenes(args, metadata_csv):
    """Resolve which scenes to evaluate, in priority order:
      1. Positional args
      2. --scenes flag
      3. --act / --from-seq
      4. All scenes in metadata
    """
    all_ids = build_scene_list(metadata_csv)

    if args.positional:
        mode = 'scenes'
        value = ','.join(args.positional)
    elif args.scenes:
        mode = 'scenes'
        value = args.scenes
    elif args.act:
        mode = 'act'
        value = args.act
    elif hasattr(args, 'from_seq') and args.from_seq:
        mode = 'from_seq'
        value = args.from_seq
    else:
        mode = 'all'
        value = None

    return apply_scene_filter(metadata_csv, all_ids, mode, value)


# ---------------------------------------------------------------------------
# Per-scene evaluation
# ---------------------------------------------------------------------------

def _evaluate_scene(scene_id, project_dir, metadata_csv, personas, model,
                    dry_run=False):
    """Run all personas against one scene. Returns output dict or None on failure."""
    scene_path = os.path.join(project_dir, 'scenes', f'{scene_id}.md')
    if not os.path.isfile(scene_path):
        log(f'  SKIP {scene_id}: scene file not found')
        return None

    with open(scene_path, encoding='utf-8') as f:
        script_text = f.read()

    ref_dir = os.path.join(project_dir, 'reference')
    scene_row = _row_to_dict(os.path.join(ref_dir, 'scenes.csv'), scene_id)
    intent_row = _row_to_dict(os.path.join(ref_dir, 'scene-intent.csv'), scene_id)
    brief_row = _row_to_dict(os.path.join(ref_dir, 'scene-briefs.csv'), scene_id)

    char_text, world_text = _build_visual_refs(project_dir)
    voice_text = _build_voice_text(project_dir)

    user_prompt = _build_evaluation_prompt(
        scene_id, scene_row, intent_row, brief_row,
        script_text, char_text, world_text, voice_text,
    )

    log_base_dir = os.path.join(project_dir, 'working', 'logs', 'evaluate-gn')
    os.makedirs(log_base_dir, exist_ok=True)

    all_findings = []
    personas_run = []

    for persona_name, prompt_path in personas:
        # Read persona system prompt
        with open(prompt_path, encoding='utf-8') as f:
            system_prompt_text = f.read()

        # The API system parameter is a list of content blocks
        system_blocks = [{'type': 'text', 'text': system_prompt_text}]

        if dry_run:
            log(f'  DRY RUN: would call {persona_name} persona for {scene_id}')
            continue

        log_file = os.path.join(log_base_dir, f'{scene_id}-{persona_name}.json')

        try:
            invoke_to_file(
                user_prompt, model, log_file, max_tokens=4096,
                system=system_blocks,
            )
        except Exception as e:
            log(f'  WARNING [{persona_name}]: API call failed for {scene_id}: {e}')
            continue

        response_text = extract_text_from_file(log_file)
        findings = _parse_findings(response_text, persona_name, scene_id)

        # Tag each finding with the persona that produced it
        for finding in findings:
            finding['persona'] = persona_name

        all_findings.extend(findings)
        personas_run.append(persona_name)

        # Cost tracking
        try:
            with open(log_file, encoding='utf-8') as f:
                resp = json.load(f)
            from storyforge.api import extract_usage, calculate_cost_from_usage
            usage = extract_usage(resp)
            cost = calculate_cost_from_usage(usage, model)
            log_operation(
                project_dir, 'evaluate-gn', model,
                usage['input_tokens'], usage['output_tokens'], cost,
                target=scene_id,
                cache_read=usage.get('cache_read', 0),
                cache_create=usage.get('cache_create', 0),
            )
        except Exception:
            pass

    if dry_run:
        return None

    return {
        'scene_id': scene_id,
        'evaluated_at': datetime.now(timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ'),
        'personas_run': personas_run,
        'findings': all_findings,
    }


# ---------------------------------------------------------------------------
# Summary printing
# ---------------------------------------------------------------------------

def _print_summary(results):
    """Print per-scene summary grouped by severity."""
    print('')
    for r in results:
        sid = r['scene_id']
        findings = r['findings']
        if not findings:
            print(f'  {sid}: 0 findings')
            continue
        by_sev = {}
        for f in findings:
            sev = f.get('severity', 'unknown')
            by_sev[sev] = by_sev.get(sev, 0) + 1
        sev_str = ', '.join(
            f'{count} {sev}' for sev, count in sorted(by_sev.items())
        )
        print(f'  {sid}: {len(findings)} finding(s) ({sev_str})')
    print('')


# ---------------------------------------------------------------------------
# main
# ---------------------------------------------------------------------------

def main(argv=None):
    args = parse_args(argv if argv is not None else sys.argv[1:])

    install_signal_handlers()

    project_dir = detect_project_root()

    # GN guard
    medium = get_medium(project_dir)
    if medium != 'graphic-novel':
        log(f'ERROR: This command is only for graphic-novel projects '
            f'(project.medium = "{medium}").')
        log('For novel projects, use the standard `storyforge evaluate` command.')
        sys.exit(1)

    log(f'Project root: {project_dir}')
    log('Medium: graphic-novel — using GN evaluation panel')

    plugin_dir = get_plugin_dir()

    # Set up logging
    log_dir = os.path.join(project_dir, 'working', 'logs')
    os.makedirs(log_dir, exist_ok=True)
    set_log_file(os.path.join(log_dir, 'evaluate-gn-log.txt'))

    # Discover personas
    all_personas = _discover_personas(plugin_dir)
    if not all_personas:
        log('ERROR: No evaluator persona files found in evaluators-gn/.')
        sys.exit(1)

    # Apply --personas filter
    if args.personas:
        requested = [p.strip() for p in args.personas.split(',') if p.strip()]
        known_names = {name for name, _ in all_personas}
        unknown = [p for p in requested if p not in known_names]
        if unknown:
            log(f'ERROR: Unknown persona(s): {", ".join(unknown)}')
            log(f'Available personas: {", ".join(sorted(known_names))}')
            sys.exit(1)
        personas = [(name, path) for name, path in all_personas if name in requested]
    else:
        personas = all_personas

    log(f'Personas: {", ".join(name for name, _ in personas)}')

    # Resolve target scenes
    metadata_csv = os.path.join(project_dir, 'reference', 'scenes.csv')

    candidate_ids = _resolve_target_scenes(args, metadata_csv)

    # Filter to only drafted scenes
    scenes_dir = os.path.join(project_dir, 'scenes')
    scene_ids = []
    for sid in candidate_ids:
        status = get_field(metadata_csv, sid, 'status') or ''
        if status != 'drafted':
            log(f'  SKIP {sid}: status is "{status}" (not drafted)')
            continue
        if not os.path.isfile(os.path.join(scenes_dir, f'{sid}.md')):
            log(f'  SKIP {sid}: scene file not found')
            continue
        scene_ids.append(sid)

    if not scene_ids:
        log('ERROR: No drafted scenes found for the selected scope.')
        sys.exit(1)

    log(f'Scenes to evaluate: {len(scene_ids)}')

    # Dry-run: print plan and exit
    if args.dry_run:
        log('DRY RUN — no API calls will be made')
        for sid in scene_ids:
            title = get_field(metadata_csv, sid, 'title') or sid
            log(f'  - {sid} ({title})')
        log(f'Personas: {", ".join(name for name, _ in personas)}')
        return

    # Prepare output directory
    output_dir = os.path.join(project_dir, 'working', 'evaluations', 'latest')
    os.makedirs(output_dir, exist_ok=True)

    model = select_model('analytical')
    log(f'Model: {model}')

    # Evaluate each scene
    results = []
    for sid in scene_ids:
        log(f'  Evaluating {sid}...')
        result = _evaluate_scene(
            sid, project_dir, metadata_csv, personas, model,
            dry_run=False,
        )
        if result is None:
            continue

        # Write per-scene JSON
        json_path = os.path.join(output_dir, f'{sid}.json')
        with open(json_path, 'w', encoding='utf-8') as f:
            json.dump(result, f, indent=2)

        results.append(result)
        log(f'  {sid}: {len(result["findings"])} finding(s) '
            f'from {len(result["personas_run"])} persona(s)')

    if not results:
        log('ERROR: No scenes were successfully evaluated.')
        sys.exit(1)

    # Print summary
    _print_summary(results)

    log(f'Evaluation complete. Results in {output_dir}')


if __name__ == '__main__':
    main()
