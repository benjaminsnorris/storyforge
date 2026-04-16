"""storyforge evaluate -- Multi-agent evaluation panel.

Runs 6 core evaluator agents (plus custom evaluators from storyforge.yaml)
in parallel via batch API, each reading the manuscript and writing a report.
After all evaluators complete, runs synthesis + optional assessment pass.

Usage:
    storyforge evaluate                      # Full manuscript (scene files)
    storyforge evaluate --manuscript         # Full manuscript (assembled chapters)
    storyforge evaluate --chapter 5          # Single assembled chapter
    storyforge evaluate --act 2              # Scenes in act 2
    storyforge evaluate --scenes ID,ID       # Specific scenes
    storyforge evaluate --scene ID           # Single scene
    storyforge evaluate --from-seq 5         # Scenes from seq 5 onward
    storyforge evaluate --evaluator line-editor  # Single evaluator
    storyforge evaluate --final              # Final eval (beta reader lens)
    storyforge evaluate --direct             # Direct API instead of batch
    storyforge evaluate --dry-run            # Print prompts only
"""

import argparse
import json
import os
import re
import sys
import time
from datetime import datetime

from storyforge.common import (
    detect_project_root, log, set_log_file, read_yaml_field,
    select_model, get_plugin_dir, install_signal_handlers,
    get_coaching_level, build_shared_context,
)
from storyforge.costs import estimate_cost, log_operation, print_summary
from storyforge.scene_filter import build_scene_list, apply_scene_filter
from storyforge.git import (
    create_branch, ensure_branch_pushed, create_draft_pr,
    update_pr_task, commit_and_push,
)
from storyforge.api import (
    invoke_to_file, extract_text, extract_text_from_file,
    extract_usage, calculate_cost_from_usage,
    submit_batch, poll_batch, download_batch_results,
    get_api_key, invoke_api, build_batch_request,
)


# ============================================================================
# Constants
# ============================================================================

CORE_EVALUATORS = [
    'literary-agent',
    'developmental-editor',
    'line-editor',
    'genre-expert',
    'first-reader',
    'writing-coach',
]


# ============================================================================
# Argument parsing
# ============================================================================

def parse_args(argv):
    parser = argparse.ArgumentParser(
        prog='storyforge evaluate',
        description='Run a multi-agent evaluation panel on your manuscript.',
    )

    scope = parser.add_argument_group('scope')
    scope.add_argument('--manuscript', action='store_true',
                       help='Evaluate assembled chapters (from manuscript/chapters/)')
    scope.add_argument('--chapter', type=int, default=None,
                       help='Evaluate a single assembled chapter')
    scope.add_argument('--act', '--part', type=str, default=None,
                       help='Evaluate scenes in act/part N')
    scope.add_argument('--scenes', type=str, default=None,
                       help='Evaluate specific scenes (comma-separated or ID..ID range)')
    scope.add_argument('--scene', type=str, default=None,
                       help='Evaluate a single scene')
    scope.add_argument('--from-seq', type=str, default=None,
                       help='Evaluate from sequence number N onward (or N-M range)')

    opts = parser.add_argument_group('options')
    opts.add_argument('--evaluator', type=str, default=None,
                      help='Run a single evaluator (e.g., line-editor)')
    opts.add_argument('--final', action='store_true',
                      help='Final evaluation before beta readers')
    opts.add_argument('--interactive', '-i', action='store_true',
                      help='Supervise the synthesis step interactively')
    opts.add_argument('--direct', action='store_true',
                      help='Use direct API calls instead of batch (default: batch)')
    opts.add_argument('--dry-run', action='store_true',
                      help='Print prompts without invoking Claude')

    return parser.parse_args(argv)


# ============================================================================
# Resolve filter mode from args
# ============================================================================

def _resolve_filter(args):
    """Return (filter_mode, filter_value, range_start, range_end, filter_scenes, filter_from_seq)."""
    if args.manuscript:
        return 'manuscript', None, None, None, None, None
    if args.chapter is not None:
        return 'chapter', str(args.chapter), None, None, None, None
    if args.act:
        return 'act', args.act, None, None, None, None
    if args.scene:
        return 'single', None, args.scene, None, None, None
    if args.scenes:
        if '..' in args.scenes:
            parts = args.scenes.split('..')
            return 'range', None, parts[0], parts[1], None, None
        return 'scenes', None, None, None, args.scenes, None
    if args.from_seq:
        return 'from_seq', None, None, None, None, args.from_seq
    return 'all', None, None, None, None, None


# ============================================================================
# Custom evaluators from storyforge.yaml
# ============================================================================

def _load_custom_evaluators(project_dir):
    """Parse custom_evaluators from storyforge.yaml.

    Returns list of (name, persona_path) tuples.
    """
    yaml_path = os.path.join(project_dir, 'storyforge.yaml')
    if not os.path.isfile(yaml_path):
        return []

    with open(yaml_path) as f:
        content = f.read()

    names = []
    paths = []

    # Extract custom_evaluators section
    in_section = False
    current_name = None
    for line in content.splitlines():
        stripped = line.strip()
        if stripped == 'custom_evaluators:':
            in_section = True
            continue
        if in_section and not line[0:1].isspace() and stripped:
            break
        if in_section:
            m = re.match(r'\s*-\s*name:\s*["\']?([^"\']+)["\']?\s*$', line)
            if m:
                current_name = m.group(1).strip()
                names.append(current_name)
                continue
            m = re.match(r'\s*persona_file:\s*["\']?([^"\']+)["\']?\s*$', line)
            if m and current_name:
                paths.append(os.path.join(project_dir, m.group(1).strip()))
                current_name = None

    result = []
    for i, name in enumerate(names):
        if i < len(paths):
            result.append((name, paths[i]))
        else:
            log(f"WARNING: No persona_file found for custom evaluator '{name}', skipping")
    return result


# ============================================================================
# Voice guide resolution
# ============================================================================

def _resolve_voice_guide(project_dir):
    """Find and read voice guide content. Returns (path, content) or (None, '')."""
    custom_vg = read_yaml_field('artifacts.voice_guide.path', project_dir)
    if custom_vg:
        vg_path = os.path.join(project_dir, custom_vg)
        if os.path.isfile(vg_path):
            return vg_path, open(vg_path).read()

    for vg in ['references/voice-guide.md', 'reference/voice-guide.md',
               'reference/persistent-prompt.md']:
        vg_path = os.path.join(project_dir, vg)
        if os.path.isfile(vg_path):
            return vg_path, open(vg_path).read()

    return None, ''


# ============================================================================
# Build file list (scenes or chapters)
# ============================================================================

def _build_file_list(project_dir, filter_mode, filter_value, range_start,
                     range_end, filter_scenes, filter_from_seq):
    """Build file list and scope description.

    Returns (scene_files, scope_description, input_type) where scene_files
    are relative paths from project root.
    """
    scenes_dir = os.path.join(project_dir, 'scenes')
    chapters_dir = os.path.join(project_dir, 'manuscript', 'chapters')

    if filter_mode in ('manuscript', 'chapter'):
        # Check chapter map freshness for manuscript evaluation
        from storyforge.common import check_chapter_map_freshness
        is_fresh, missing, extra = check_chapter_map_freshness(project_dir)
        if not is_fresh:
            parts = []
            if missing:
                parts.append(f'scenes not in chapter map: {", ".join(missing[:5])}')
            if extra:
                parts.append(f'chapter map references removed scenes: {", ".join(extra[:5])}')
            log(f'ERROR: Chapter map is stale — {"; ".join(parts)}')
            log('Update the chapter map before evaluating the manuscript.')
            sys.exit(1)

        # Manuscript mode
        if not os.path.isdir(chapters_dir):
            log("ERROR: No assembled chapters found at manuscript/chapters/")
            log("Run 'storyforge assemble' first to generate chapter files.")
            sys.exit(1)

        chapter_files = sorted([
            f for f in os.listdir(chapters_dir)
            if f.startswith('chapter-') and f.endswith('.md')
        ])

        if not chapter_files:
            log(f"ERROR: No chapter files found in {chapters_dir}")
            sys.exit(1)

        if filter_mode == 'chapter':
            ch_name = f"chapter-{int(filter_value):02d}.md"
            if ch_name not in chapter_files:
                log(f"ERROR: Chapter file not found: manuscript/chapters/{ch_name}")
                sys.exit(1)
            return [f'manuscript/chapters/{ch_name}'], f'chapter {filter_value}', 'chapters'

        scene_files = [f'manuscript/chapters/{f}' for f in chapter_files]
        return scene_files, f'full manuscript ({len(chapter_files)} assembled chapters)', 'chapters'

    # Scene mode
    metadata_csv = os.path.join(project_dir, 'reference', 'scenes.csv')
    all_ids = build_scene_list(metadata_csv)

    if filter_mode == 'all':
        filtered = apply_scene_filter(metadata_csv, all_ids, 'all')
    elif filter_mode == 'single':
        filtered = apply_scene_filter(metadata_csv, all_ids, 'single', range_start)
    elif filter_mode == 'range':
        filtered = apply_scene_filter(metadata_csv, all_ids, 'range', range_start, range_end)
    elif filter_mode == 'scenes':
        filtered = apply_scene_filter(metadata_csv, all_ids, 'scenes', filter_scenes)
    elif filter_mode == 'act':
        filtered = apply_scene_filter(metadata_csv, all_ids, 'act', filter_value)
    elif filter_mode == 'from_seq':
        filtered = apply_scene_filter(metadata_csv, all_ids, 'from_seq', filter_from_seq)
    else:
        filtered = all_ids

    scene_files = []
    missing = []
    for sid in filtered:
        scene_file = os.path.join(scenes_dir, f'{sid}.md')
        if os.path.isfile(scene_file):
            scene_files.append(f'scenes/{sid}.md')
        else:
            missing.append(sid)

    if not scene_files:
        log('ERROR: No drafted scene files found for the selected scope.')
        if missing:
            log(f'Missing scenes: {" ".join(missing)}')
        sys.exit(1)

    if missing:
        log(f'WARNING: {len(missing)} scenes not yet drafted (skipping): {" ".join(missing)}')

    scope = f'full manuscript ({len(scene_files)} scenes)'
    if filter_mode == 'act':
        scope = f'Act {filter_value} ({len(scene_files)} scenes)'
    elif filter_mode == 'range':
        scope = f'scenes {range_start} through {range_end} ({len(scene_files)} scenes)'
    elif filter_mode == 'single':
        scope = f'scene {range_start}'
    elif filter_mode == 'from_seq':
        scope = f'seq {filter_from_seq} ({len(scene_files)} scenes)'
    elif filter_mode == 'scenes':
        scope = f'{len(scene_files)} selected scenes'

    return scene_files, scope, 'scenes'


# ============================================================================
# Prompt building
# ============================================================================

def _build_eval_prompt(evaluator, is_custom, api_mode, project_dir, plugin_dir,
                       scene_files, scope_description, input_type,
                       project_title, genre_display, logline,
                       voice_guide_content, final_eval, eval_timestamp,
                       custom_evaluators):
    """Build the evaluation prompt for a single evaluator."""
    # Resolve persona file
    if is_custom:
        persona_file = None
        for name, path in custom_evaluators:
            if name == evaluator:
                persona_file = path
                break
    else:
        persona_dir = os.path.join(plugin_dir, 'scripts', 'prompts', 'evaluators')
        persona_file = os.path.join(persona_dir, f'{evaluator}.md')

    if not persona_file or not os.path.isfile(persona_file):
        log(f'ERROR: Persona file not found for {evaluator}')
        return None

    persona = open(persona_file).read()

    # Replace {GENRE} placeholder
    if genre_display:
        persona = persona.replace('{GENRE}', genre_display)
    else:
        persona = persona.replace('{GENRE}', 'fiction')

    # Inject AI-tell word list for line-editor
    if evaluator == 'line-editor':
        from storyforge.prompts import load_ai_tell_words
        ai_words = load_ai_tell_words(plugin_dir)
        if ai_words:
            vocab_words = [w['word'] for w in ai_words
                          if w['severity'] == 'high']
            word_block = (
                'Specific AI-tell vocabulary to flag (these words almost never '
                'belong in fiction): ' + ', '.join(vocab_words)
            )
            persona = persona.replace('{AI_TELL_WORDS}', word_block)
        else:
            persona = persona.replace('{AI_TELL_WORDS}', '')
    else:
        persona = persona.replace('{AI_TELL_WORDS}', '')

    # Inline manuscript content for API mode
    manuscript_inline = ''
    if api_mode:
        for sf in scene_files:
            sf_path = os.path.join(project_dir, sf)
            if os.path.isfile(sf_path):
                manuscript_inline += f'\n===== {sf} =====\n\n'
                manuscript_inline += open(sf_path).read()
                manuscript_inline += f'\n\n===== END {sf} =====\n'

    # Final evaluation context
    final_block = ''
    if final_eval:
        final_block = (
            '===== EVALUATION CONTEXT =====\n\n'
            'This is a final evaluation. The author plans to send this manuscript to beta\n'
            'readers after this cycle. Evaluate with that lens:\n\n'
            '- Focus on issues that outside readers would notice, stumble on, or be confused by.\n'
            '- Minor craft refinements that wouldn\'t affect a reader\'s experience should be\n'
            '  noted briefly but should not dominate your report or be prioritized highly.\n'
            '- Assess whether this manuscript is ready for outside eyes.\n\n'
        )
        final_extras = {
            'first-reader': 'Your perspective is the closest proxy for these beta readers -- be explicit about where you\'d put the book down, where you\'d lose trust, and where you\'d text a friend to say they have to read this.',
            'developmental-editor': 'Focus on structural issues that would leave a reader feeling the story didn\'t hold together -- dropped threads, unearned turns, pacing dead zones.',
            'line-editor': 'Focus on prose issues that would pull a non-specialist reader out of the story -- confusing sentences, jarring tense shifts, dialogue that rings false.',
            'genre-expert': 'Focus on where genre readers\' expectations would be violated in ways that feel like mistakes rather than deliberate subversions.',
            'literary-agent': 'Assess this as if the author is about to share it with a small group before querying. What would you want fixed before anyone outside the author\'s circle sees it.',
            'writing-coach': 'This is the last evaluation before outside readers. Focus your guidance on what the author should protect during any final touch-ups.',
        }
        if evaluator in final_extras:
            final_block += final_extras[evaluator]

    # Scene list string
    scene_list_str = '\n'.join(f'   - {sf}' for sf in scene_files)

    # Build prompt
    parts = [
        f'You are evaluating the manuscript of "{project_title}."\n',
        '===== PROJECT CONTEXT =====\n',
        f'Title: {project_title}',
        f'Genre: {genre_display or "Not specified"}',
        f'Logline: {logline or "Not provided"}',
        f'Evaluation scope: {scope_description}\n',
        '===== YOUR ROLE =====\n',
        persona,
        '\n',
        final_block,
    ]

    if api_mode:
        parts.extend([
            '===== MANUSCRIPT =====\n',
            manuscript_inline,
            '\n===== INSTRUCTIONS =====\n',
            'The manuscript is provided above. Evaluate it following the structure defined in your role description.\n',
        ])
    else:
        if input_type == 'chapters':
            parts.append('===== INSTRUCTIONS =====\n')
            parts.append('1. Read the assembled chapter files that comprise the evaluation scope:')
        else:
            parts.append('===== INSTRUCTIONS =====\n')
            parts.append('1. Read the scene files that comprise the evaluation scope:')
        parts.append(scene_list_str)

    if not api_mode:
        parts.extend([
            f'\n2. Write your evaluation report following the structure defined in your role description above.\n',
            f'3. Save your report to: working/evaluations/eval-{eval_timestamp}/{evaluator}.md\n',
        ])

    if input_type == 'chapters':
        parts.append(
            'Be specific. Cite chapter numbers, character names, and quote brief passages when making points. '
            'Pay particular attention to:\n'
            '   - Chapter-level pacing\n   - Chapter transitions\n   - Chapter length variation\n'
            '   - Scene breaks within chapters\n   - Overall reading momentum\n'
        )
    else:
        parts.append(
            'Be specific. Cite scene IDs, character names, and quote brief passages when making points. '
            'Vague praise or criticism is unhelpful. The author wants to know exactly what works, what does not, and why.\n'
        )

    parts.append(
        'Be honest. The author is looking for professional-grade feedback, not encouragement. '
        'If something is broken, say so clearly. If something is excellent, say that too -- '
        'protecting strengths is as important as fixing weaknesses.\n'
    )

    if api_mode:
        parts.extend([
            '===== OUTPUT =====\n',
            'Output your complete evaluation report directly. Do not include any preamble or explanation -- just the evaluation report content.',
        ])
    else:
        parts.extend([
            '===== OUTPUT =====\n',
            f'Save your complete evaluation to: working/evaluations/eval-{eval_timestamp}/{evaluator}.md\n',
            '===== COMMIT AND PUSH =====\n',
            f'After saving your report, stage and commit:\n',
            f'  git add "working/evaluations/eval-{eval_timestamp}/{evaluator}.md"',
            f'  git commit -m "Evaluate: {evaluator} report ({scope_description})"',
            f'  git push\n',
            'This is required -- the author follows progress by pulling commits as you work.',
        ])

    return '\n'.join(parts)


def _build_synthesis_prompt(project_dir, eval_dir, eval_timestamp, scope_description,
                            project_title, genre_display, logline, input_type,
                            succeeded, final_eval, api_mode):
    """Build the synthesis prompt."""
    readiness_section = ''
    if final_eval:
        readiness_section = (
            '\n## Beta Reader Readiness\n\n'
            'Assess whether this manuscript is ready for beta readers. Use one of:\n'
            '**Ready with high confidence**, **Ready with reservations**, or **Not ready**.\n'
            'Explain your reasoning in 2-3 paragraphs grounded in evaluator reports.\n'
        )

    if api_mode:
        # Inline reports
        inline_reports = ''
        for name in succeeded:
            report_path = os.path.join(eval_dir, f'{name}.md')
            if os.path.isfile(report_path):
                inline_reports += f'\n===== REPORT: {name} =====\n\n'
                inline_reports += open(report_path).read()
                inline_reports += f'\n\n===== END REPORT: {name} =====\n'

        location_type = 'chapter-number-or-range' if input_type == 'chapters' else 'scene-id'

        return f'''You are reconciling the evaluation reports from a multi-agent review panel for "{project_title}."

Your job is to synthesize what the panel said -- consensus, disagreements, and priorities. Do not filter or reinterpret findings based on the author's intentions. Report what the evaluators experienced.

===== PROJECT CONTEXT =====

Title: {project_title}
Genre: {genre_display or 'Not specified'}
Logline: {logline or 'Not provided'}
Evaluation scope: {scope_description}

===== EVALUATION REPORTS =====

{inline_reports}

===== INSTRUCTIONS =====

Produce TWO sections in your response, clearly delimited:

--- BEGIN synthesis.md ---

A prose synthesis report with these sections:

## Consensus Findings
Issues or strengths identified by 3+ evaluators. These are high-confidence findings.

## Contested Points
Areas where evaluators disagree. Present both sides fairly.

## Prioritized Action Items
A numbered list of the most impactful changes, ordered by priority.

## Strengths to Protect
Elements that evaluators praised and that must be preserved.

## Overall Assessment
A brief (2-3 paragraph) synthesis of where the manuscript stands.

--- END synthesis.md ---

--- BEGIN findings.yaml ---

A structured YAML file containing all findings. Use this format:

```yaml
metadata:
  title: "{project_title}"
  genre: "{genre_display or 'Not specified'}"
  scope: "{scope_description}"
  evaluators_succeeded:
    - evaluator-name
  timestamp: "{eval_timestamp}"

findings:
  - id: F001
    category: structure|character|pacing|prose|worldbuilding|theme|market|genre|continuity
    severity: critical|major|minor|suggestion
    summary: "One-line description"
    detail: "Full explanation with context"
    affected_locations:
      - {location_type}
    flagged_by:
      - evaluator-name
    recommendation: "Specific, actionable suggestion"
    fix_location: brief|intent|structural|craft

strengths:
  - id: S001
    category: structure|character|pacing|prose|worldbuilding|theme|voice|craft
    summary: "One-line description"
    detail: "Why this works"
    examples:
      - {location_type}
    flagged_by:
      - evaluator-name
```

IMPORTANT: The findings.yaml must be valid YAML. Use quoted strings for values with colons or special characters.

--- END findings.yaml ---
{readiness_section}'''
    else:
        # Interactive mode -- file-reading instructions
        report_list = '\n'.join(
            f'   - working/evaluations/eval-{eval_timestamp}/{name}.md'
            for name in succeeded
        )
        return f'''You are reconciling the evaluation reports from a multi-agent review panel for "{project_title}."

===== PROJECT CONTEXT =====

Title: {project_title}
Genre: {genre_display or 'Not specified'}
Evaluation scope: {scope_description}

===== INSTRUCTIONS =====

1. Read ALL of the following evaluation reports:
{report_list}
2. Produce TWO output files:

Save synthesis to: working/evaluations/eval-{eval_timestamp}/synthesis.md
Save findings to: working/evaluations/eval-{eval_timestamp}/findings.yaml

After saving both files, stage and commit:
  git add "working/evaluations/eval-{eval_timestamp}/"
  git commit -m "Evaluate: synthesis ({scope_description})"
  git push
{readiness_section}'''


def _build_assessment_prompt(project_dir, eval_dir, eval_timestamp, scope_description,
                             project_title, genre_display, final_eval, api_mode):
    """Build the assessment prompt if reference files exist.

    Returns (prompt, ref_count) or (None, 0) if no reference files.
    """
    ref_files = []
    for ref in ['reference/key-decisions.md',
                'reference/voice-guide.md', 'references/voice-guide.md',
                'reference/story-architecture.md', 'references/story-architecture.md']:
        if os.path.isfile(os.path.join(project_dir, ref)):
            ref_files.append(ref)

    if not ref_files:
        return None, 0

    # Build sections based on which files exist
    sections = []
    for ref in ref_files:
        if 'voice-guide' in ref:
            sections.append('## Voice Guide Alignment\nDid the prose deliver the voice described in the voice guide?')
        elif 'story-architecture' in ref:
            sections.append('## Story Architecture Alignment\nDid the structural intentions land?')
        elif 'key-decisions' in ref:
            sections.append('## Key Decisions Audit\nWhich deliberate choices read as intentional to the panel?')

    sections.append('## Revised Priorities\nWhich findings are most important given the author\'s intentions?')
    sections_text = '\n\n'.join(sections)

    readiness = ''
    if final_eval:
        readiness = '\n## Beta Reader Readiness\nAssess readiness for outside readers.\n'

    if api_mode:
        synth_content = ''
        synth_path = os.path.join(eval_dir, 'synthesis.md')
        if os.path.isfile(synth_path):
            synth_content = open(synth_path).read()

        ref_inline = ''
        for ref in ref_files:
            ref_path = os.path.join(project_dir, ref)
            ref_inline += f'\n===== REFERENCE: {ref} =====\n\n'
            ref_inline += open(ref_path).read()
            ref_inline += f'\n\n===== END REFERENCE: {ref} =====\n'

        prompt = f'''You are assessing the manuscript's execution against the author's stated intentions for "{project_title}."

===== PROJECT CONTEXT =====

Title: {project_title}
Genre: {genre_display or 'Not specified'}
Evaluation scope: {scope_description}

===== RECONCILIATION =====

{synth_content}

===== AUTHOR'S REFERENCE FILES =====

{ref_inline}

===== INSTRUCTIONS =====

Produce an assessment report with these sections:

{sections_text}

{readiness}

===== OUTPUT =====

Output your complete assessment report directly.'''
    else:
        ref_file_list = '\n'.join(f'   - {r}' for r in ref_files)
        prompt = f'''You are assessing the manuscript's execution against the author's stated intentions for "{project_title}."

===== INSTRUCTIONS =====

1. Read the reconciliation report:
   - working/evaluations/eval-{eval_timestamp}/synthesis.md
2. Read the author's reference files:
{ref_file_list}
3. Produce an assessment report:

{sections_text}

{readiness}

4. Save to: working/evaluations/eval-{eval_timestamp}/assessment.md

After saving, commit and push.'''

    return prompt, len(ref_files)


# ============================================================================
# Cost estimation helpers
# ============================================================================

def _estimate_avg_words(project_dir, scene_files):
    """Estimate average word count from metadata or scene files."""
    metadata_csv = os.path.join(project_dir, 'reference', 'scenes.csv')

    if os.path.isfile(metadata_csv):
        from storyforge.csv_cli import get_column
        wc_col = get_column(metadata_csv, 'word_count')
        total = sum(int(w) for w in wc_col if w and w != '0')
        count = sum(1 for w in wc_col if w and w != '0')
        if count > 0:
            return total // count

    # Fall back to file word counts
    total = 0
    count = 0
    for sf in scene_files:
        sf_path = os.path.join(project_dir, sf)
        if os.path.isfile(sf_path):
            wc = len(open(sf_path).read().split())
            total += wc
            count += 1

    return total // count if count > 0 else 3000


# ============================================================================
# Log usage from API response
# ============================================================================

def _log_usage(project_dir, log_file_or_response, operation, target, model,
               duration_s=0, batch=False):
    """Log usage from an API response file or dict.

    If batch=True, applies the Anthropic Batch API 50% discount to cost.
    """
    if isinstance(log_file_or_response, dict):
        usage = extract_usage(log_file_or_response)
    elif os.path.isfile(log_file_or_response):
        try:
            with open(log_file_or_response) as f:
                usage = extract_usage(json.load(f))
        except (json.JSONDecodeError, FileNotFoundError):
            return
    else:
        return

    cost = calculate_cost_from_usage(usage, model, batch=batch)
    log_operation(
        project_dir, operation, model,
        usage['input_tokens'], usage['output_tokens'], cost,
        duration_s=duration_s, target=target,
        cache_read=usage.get('cache_read', 0),
        cache_create=usage.get('cache_create', 0),
    )


# ============================================================================
# Pipeline manifest helpers
# ============================================================================

def _ensure_pipeline_manifest(project_dir):
    """Ensure pipeline.csv exists."""
    manifest = os.path.join(project_dir, 'working', 'pipeline.csv')
    if not os.path.isfile(manifest):
        os.makedirs(os.path.dirname(manifest), exist_ok=True)
        with open(manifest, 'w') as f:
            f.write('cycle|status|evaluation|plan|revision|timestamp\n')


def _start_cycle(project_dir, eval_timestamp):
    """Start a new pipeline cycle. Returns cycle ID."""
    manifest = os.path.join(project_dir, 'working', 'pipeline.csv')
    _ensure_pipeline_manifest(project_dir)

    # Count existing cycles
    with open(manifest) as f:
        lines = f.readlines()
    cycle_id = str(len(lines))  # 1-indexed (header is line 0)

    ts = datetime.now().strftime('%Y-%m-%dT%H:%M:%S')
    with open(manifest, 'a') as f:
        f.write(f'{cycle_id}|evaluating|eval-{eval_timestamp}|||{ts}\n')

    return cycle_id


def _update_cycle(project_dir, cycle_id, field, value):
    """Update a field in the pipeline manifest."""
    manifest = os.path.join(project_dir, 'working', 'pipeline.csv')
    if not os.path.isfile(manifest):
        return

    with open(manifest) as f:
        lines = f.readlines()

    header = lines[0].strip().split('|')
    if field not in header:
        return

    field_idx = header.index(field)

    for i in range(1, len(lines)):
        parts = lines[i].strip().split('|')
        if parts and parts[0] == cycle_id:
            while len(parts) <= field_idx:
                parts.append('')
            parts[field_idx] = value
            lines[i] = '|'.join(parts) + '\n'
            break

    with open(manifest, 'w') as f:
        f.writelines(lines)


def _write_word_count_snapshot(eval_dir: str, project_dir: str) -> None:
    """Write word count snapshot for staleness detection."""
    scenes_csv = os.path.join(project_dir, 'reference', 'scenes.csv')
    if not os.path.isfile(scenes_csv):
        return

    from storyforge.csv_cli import get_column, list_ids
    ids = list_ids(scenes_csv)
    wc_col = get_column(scenes_csv, 'word_count')

    snapshot_path = os.path.join(eval_dir, 'word-counts.csv')
    with open(snapshot_path, 'w') as f:
        f.write('id|word_count\n')
        for scene_id, wc in zip(ids, wc_col):
            if wc and wc != '0':
                f.write(f'{scene_id}|{wc}\n')


# ============================================================================
# Main
# ============================================================================

def main(argv=None):
    args = parse_args(argv or [])
    install_signal_handlers()

    project_dir = detect_project_root()
    plugin_dir = get_plugin_dir()

    log_dir = os.path.join(project_dir, 'working', 'logs')
    os.makedirs(log_dir, exist_ok=True)
    set_log_file(os.path.join(log_dir, 'evaluation-log.txt'))

    log(f'Project root: {project_dir}')

    # Determine eval mode
    if args.interactive:
        eval_mode = 'interactive'
    elif args.direct:
        eval_mode = 'direct'
    else:
        eval_mode = 'batch'

    # Check API key early
    if not args.dry_run and eval_mode != 'interactive':
        try:
            get_api_key()
        except RuntimeError:
            log('ERROR: ANTHROPIC_API_KEY is required for batch and direct modes.')
            log('  Set it with: export ANTHROPIC_API_KEY=your-key')
            log('  Or use --interactive to run with claude -p instead.')
            sys.exit(1)

    # Resolve filter
    filter_mode, filter_value, range_start, range_end, filter_scenes, filter_from_seq = \
        _resolve_filter(args)

    # Read project metadata
    project_title = read_yaml_field('project.title', project_dir) or \
                    read_yaml_field('title', project_dir) or 'Unknown'
    project_genre = read_yaml_field('project.genre', project_dir) or \
                    read_yaml_field('genre', project_dir) or ''
    project_subgenre = read_yaml_field('project.subgenre', project_dir) or ''
    project_logline = read_yaml_field('project.logline', project_dir) or \
                      read_yaml_field('logline', project_dir) or ''

    genre_display = project_genre
    if project_subgenre:
        genre_display = f'{project_genre} ({project_subgenre})'

    # Voice guide
    vg_path, voice_guide_content = _resolve_voice_guide(project_dir)
    if vg_path:
        log(f'Voice guide: {vg_path}')
    else:
        log('WARNING: No voice guide found.')

    # Build file list
    scene_files, scope_description, input_type = _build_file_list(
        project_dir, filter_mode, filter_value, range_start,
        range_end, filter_scenes, filter_from_seq,
    )

    # Custom evaluators
    custom_evaluators = _load_custom_evaluators(project_dir)

    # Build evaluator list
    core_evals = list(CORE_EVALUATORS)

    # Single evaluator filtering
    if args.evaluator:
        all_names = core_evals + [name for name, _ in custom_evaluators]
        if args.evaluator not in all_names:
            print(f'ERROR: Unknown evaluator \'{args.evaluator}\'', file=sys.stderr)
            print(f'Available evaluators: {" ".join(all_names)}', file=sys.stderr)
            sys.exit(1)
        core_evals = [e for e in core_evals if e == args.evaluator]
        custom_evaluators = [(n, p) for n, p in custom_evaluators if n == args.evaluator]
        log(f'Single evaluator mode: {args.evaluator}')

    all_evaluator_count = len(core_evals) + len(custom_evaluators)

    # Timestamp for this evaluation
    eval_timestamp = datetime.now().strftime('%Y%m%d-%H%M%S')
    eval_dir = os.path.join(project_dir, 'working', 'evaluations', f'eval-{eval_timestamp}')

    # Determine if prompts need inline file content
    use_api_prompts = eval_mode in ('batch', 'direct')

    # Build all prompts
    eval_names = []
    eval_models = []
    eval_prompts = []
    eval_is_custom = []

    for evaluator in core_evals:
        model = select_model('evaluation')
        prompt = _build_eval_prompt(
            evaluator, False, use_api_prompts, project_dir, plugin_dir,
            scene_files, scope_description, input_type,
            project_title, genre_display, project_logline,
            voice_guide_content, args.final, eval_timestamp,
            custom_evaluators,
        )
        eval_names.append(evaluator)
        eval_models.append(model)
        eval_prompts.append(prompt)
        eval_is_custom.append(False)

    for name, path in custom_evaluators:
        model = select_model('evaluation')
        prompt = _build_eval_prompt(
            name, True, use_api_prompts, project_dir, plugin_dir,
            scene_files, scope_description, input_type,
            project_title, genre_display, project_logline,
            voice_guide_content, args.final, eval_timestamp,
            custom_evaluators,
        )
        eval_names.append(name)
        eval_models.append(model)
        eval_prompts.append(prompt)
        eval_is_custom.append(True)

    # ---- DRY RUN ----
    if args.dry_run:
        print(f'# Mode: {eval_mode} (api_prompts: {use_api_prompts})')
        print()
        for i, name in enumerate(eval_names):
            custom_label = ' (custom)' if eval_is_custom[i] else ''
            print(f'===== DRY RUN: {name}{custom_label} =====')
            print(eval_prompts[i])
            print(f'===== END DRY RUN: {name} =====')
            print()
        print(f'===== DRY RUN: synthesis (Pass 1 -- reconciliation) =====')
        print(f'# Reconciliation prompt would read reports from: working/evaluations/eval-{eval_timestamp}/')
        print(f'# Evaluators: {" ".join(eval_names)}')
        print(f'===== END DRY RUN: synthesis =====')
        print()
        print(f'===== DRY RUN: assessment (Pass 2 -- execution vs. intent) =====')
        print(f'# Assessment reads: synthesis.md + reference files')
        if args.final:
            print(f'# --final: includes Beta Reader Readiness section')
        print(f'# Skipped if no reference files exist')
        print(f'===== END DRY RUN: assessment =====')
        return

    # ---- START REAL EXECUTION ----
    session_start = datetime.now().strftime('%Y-%m-%dT%H:%M:%S')
    _wall_start = time.time()

    # Pipeline manifest
    cycle_id = '0'
    if not args.evaluator:
        _ensure_pipeline_manifest(project_dir)
        cycle_id = _start_cycle(project_dir, eval_timestamp)

    os.makedirs(eval_dir, exist_ok=True)

    # Branch + PR setup (skip for single evaluator)
    eval_task_labels = []
    if not args.evaluator:
        create_branch('evaluate', project_dir)
        ensure_branch_pushed(project_dir)

        pr_lines = [
            '## Evaluation Panel\n',
            f'**Project:** {project_title}',
            f'**Scope:** {scope_description}',
            f'**Evaluators:** {all_evaluator_count}\n',
            '### Tasks',
        ]

        for i, name in enumerate(eval_names):
            custom_label = ' (custom)' if eval_is_custom[i] else ''
            label = f'Evaluator: {name}{custom_label}'
            eval_task_labels.append(label)
            pr_lines.append(f'- [ ] {label}')
        pr_lines.append('- [ ] Synthesis')
        pr_lines.append('- [ ] Assessment')

        create_draft_pr(
            f'Evaluate: {project_title} ({scope_description})',
            '\n'.join(pr_lines),
            project_dir, 'evaluation',
        )

    log('============================================')
    log('Starting Storyforge evaluation panel')
    log(f'Project: {project_title}')
    log(f'Genre: {genre_display or "Not specified"}')
    log(f'Scope: {scope_description}')
    log(f'Core evaluators: {" ".join(core_evals)}')
    if custom_evaluators:
        log(f'Custom evaluators: {" ".join(n for n, _ in custom_evaluators)}')
    log(f'Output directory: {eval_dir}')
    log('============================================')

    # Cost forecast
    eval_model_forecast = select_model('evaluation')
    synth_model_forecast = select_model('synthesis')
    avg_words = _estimate_avg_words(project_dir, scene_files)

    evaluator_cost = estimate_cost('evaluate', len(scene_files), avg_words, eval_model_forecast)
    synth_cost = estimate_cost('evaluate', 1, avg_words * len(scene_files), synth_model_forecast)

    if eval_mode == 'batch':
        total_forecast = evaluator_cost * all_evaluator_count * 0.75 + synth_cost
        cost_mode_label = 'batch, ~25% discount'
    else:
        total_forecast = evaluator_cost * all_evaluator_count + synth_cost
        cost_mode_label = eval_mode

    log(f'Cost forecast: ~${total_forecast:.2f} ({all_evaluator_count} evaluators @ ~${evaluator_cost:.2f} + synthesis ~${synth_cost:.2f}, mode: {cost_mode_label})')

    # ---- LAUNCH EVALUATORS ----
    succeeded = []
    failed = []

    # Build shared context for prompt caching (batch + direct modes)
    system = build_shared_context(project_dir, model=eval_models[0] if eval_models else '')

    if eval_mode == 'batch':

        # Build JSONL batch
        log(f'Building batch request for {len(eval_names)} evaluators...')
        batch_file = os.path.join(log_dir, f'eval-batch-{eval_timestamp}.jsonl')
        with open(batch_file, 'w') as f:
            for i, name in enumerate(eval_names):
                request = build_batch_request(name, eval_prompts[i], eval_models[i], 8192,
                                              system=system)
                f.write(json.dumps(request) + '\n')
                log(f'  Added to batch: {name} (model: {eval_models[i]})')

        log(f'Submitting batch ({len(eval_names)} requests)...')
        batch_id = submit_batch(batch_file)
        log(f'Batch submitted: {batch_id}')

        log('Polling batch for completion...')
        results_url = poll_batch(batch_id, log_fn=log)
        log('Batch complete. Downloading results...')

        download_batch_results(results_url, eval_dir, log_dir)

        # Process results
        for i, name in enumerate(eval_names):
            status_file = os.path.join(eval_dir, f'.status-{name}')
            eval_json = os.path.join(log_dir, f'{name}.json')
            eval_txt = os.path.join(log_dir, f'{name}.txt')

            if os.path.isfile(eval_json):
                _log_usage(project_dir, eval_json, 'evaluate', name, eval_models[i],
                           batch=True)

            if os.path.isfile(status_file) and open(status_file).read().strip() == 'ok':
                if os.path.isfile(eval_txt):
                    os.makedirs(eval_dir, exist_ok=True)
                    with open(os.path.join(eval_dir, f'{name}.md'), 'w') as f:
                        f.write(open(eval_txt).read())

                report_path = os.path.join(eval_dir, f'{name}.md')
                if os.path.isfile(report_path):
                    wc = len(open(report_path).read().split())
                    log(f'SUCCESS: {name} ({wc} words)')
                    succeeded.append(name)
                    if i < len(eval_task_labels):
                        update_pr_task(eval_task_labels[i], project_dir)
                else:
                    log(f'FAILED: {name} (no output file created)')
                    failed.append(name)
            else:
                log(f'FAILED: {name} (batch request failed)')
                failed.append(name)

        # Clean up
        os.remove(batch_file)

    elif eval_mode == 'direct':
        # Direct API -- parallel via ThreadPoolExecutor
        from concurrent.futures import ThreadPoolExecutor, as_completed

        def _run_evaluator(idx):
            name = eval_names[idx]
            model = eval_models[idx]
            prompt = eval_prompts[idx]
            eval_log = os.path.join(log_dir, f'eval-{name}.log')

            try:
                response = invoke_to_file(prompt, model, eval_log, max_tokens=8192,
                                          system=system)
                text = extract_text(response)
                if text:
                    os.makedirs(eval_dir, exist_ok=True)
                    with open(os.path.join(eval_dir, f'{name}.md'), 'w') as f:
                        f.write(text)
                    return 'ok', name, model, eval_log
                return 'fail', name, model, eval_log
            except Exception as e:
                log(f'FAILED: {name} -- {e}')
                return 'fail', name, model, eval_log

        log(f'Launching {len(eval_names)} evaluators (direct API)...')
        with ThreadPoolExecutor(max_workers=len(eval_names)) as pool:
            futures = {pool.submit(_run_evaluator, i): i for i in range(len(eval_names))}
            for future in as_completed(futures):
                idx = futures[future]
                status, name, model, eval_log = future.result()
                _log_usage(project_dir, eval_log, 'evaluate', name, model)

                if status == 'ok':
                    report_path = os.path.join(eval_dir, f'{name}.md')
                    if os.path.isfile(report_path):
                        wc = len(open(report_path).read().split())
                        log(f'SUCCESS: {name} ({wc} words)')
                        succeeded.append(name)
                        if idx < len(eval_task_labels):
                            update_pr_task(eval_task_labels[idx], project_dir)
                    else:
                        log(f'FAILED: {name} (no output file)')
                        failed.append(name)
                else:
                    log(f'FAILED: {name}')
                    failed.append(name)

    else:
        # Interactive mode -- use claude CLI
        import subprocess

        pids = []
        for i, name in enumerate(eval_names):
            model = eval_models[i]
            prompt = eval_prompts[i]
            eval_log = os.path.join(log_dir, f'eval-{name}.log')

            custom_label = ' (custom)' if eval_is_custom[i] else ''
            log(f'Launching evaluator{custom_label}: {name} (model: {model})')

            with open(eval_log, 'w') as log_f:
                proc = subprocess.Popen(
                    ['claude', '-p', prompt,
                     '--model', model,
                     '--dangerously-skip-permissions',
                     '--output-format', 'stream-json',
                     '--verbose'],
                    stdout=log_f, stderr=subprocess.STDOUT,
                )
                pids.append((proc, name, model, eval_log))

        log(f'All {len(pids)} evaluators launched. Waiting for completion...')

        for proc, name, model, eval_log in pids:
            proc.wait()
            report_path = os.path.join(eval_dir, f'{name}.md')
            if proc.returncode == 0 and os.path.isfile(report_path):
                wc = len(open(report_path).read().split())
                log(f'SUCCESS: {name} ({wc} words)')
                succeeded.append(name)
            else:
                log(f'FAILED: {name} (exit code {proc.returncode})')
                failed.append(name)

    log(f'Evaluator results: {len(succeeded)} succeeded, {len(failed)} failed')
    if failed:
        log(f'Failed evaluators: {" ".join(failed)}')

    # ---- SYNTHESIS ----
    if args.evaluator:
        log('Single evaluator mode -- skipping synthesis and assessment')
    elif len(succeeded) < 3:
        log(f'ERROR: Too few evaluators succeeded ({len(succeeded)}/{all_evaluator_count}). Skipping synthesis.')
        sys.exit(1)

    if not args.evaluator and len(succeeded) >= 3:
        log('Running synthesis session...')
        synth_start = time.time()
        synth_model = select_model('synthesis')
        synth_log = os.path.join(log_dir, 'eval-synthesis.log')

        api_mode = eval_mode != 'interactive'
        synth_prompt = _build_synthesis_prompt(
            project_dir, eval_dir, eval_timestamp, scope_description,
            project_title, genre_display, project_logline, input_type,
            succeeded, args.final, api_mode,
        )

        if api_mode:
            log(f'Running synthesis via direct API (model: {synth_model})...')
            response = invoke_to_file(synth_prompt, synth_model, synth_log, max_tokens=8192,
                                      system=system)
            synth_response = extract_text(response)

            if synth_response:
                # Parse delimited sections
                import re as _re
                synth_md_match = _re.search(
                    r'--- BEGIN synthesis\.md ---\n(.*?)--- END synthesis\.md ---',
                    synth_response, _re.DOTALL,
                )
                synth_md = synth_md_match.group(1).strip() if synth_md_match else synth_response
                with open(os.path.join(eval_dir, 'synthesis.md'), 'w') as f:
                    f.write(synth_md)

                findings_match = _re.search(
                    r'--- BEGIN findings\.yaml ---\n(.*?)--- END findings\.yaml ---',
                    synth_response, _re.DOTALL,
                )
                if findings_match:
                    findings_yaml = findings_match.group(1).strip()
                    findings_yaml = _re.sub(r'^```yaml\s*\n', '', findings_yaml)
                    findings_yaml = _re.sub(r'\n```\s*$', '', findings_yaml)
                    with open(os.path.join(eval_dir, 'findings.yaml'), 'w') as f:
                        f.write(findings_yaml)
        else:
            # Interactive synthesis
            subprocess.run(
                ['claude', synth_prompt,
                 '--model', synth_model,
                 '--dangerously-skip-permissions'],
                cwd=project_dir,
            )

        synth_duration = int(time.time() - synth_start)
        _log_usage(project_dir, synth_log, 'synthesize', 'synthesis', synth_model, synth_duration)

        synth_path = os.path.join(eval_dir, 'synthesis.md')
        if not os.path.isfile(synth_path):
            log('ERROR: synthesis.md not created')
            sys.exit(1)

        synth_words = len(open(synth_path).read().split())
        log(f'SUCCESS: Synthesis complete ({synth_words} words, {synth_duration // 60}m{synth_duration % 60}s)')

        _update_cycle(project_dir, cycle_id, 'status', 'planning')
        update_pr_task('Synthesis', project_dir)

        findings_path = os.path.join(eval_dir, 'findings.yaml')
        if os.path.isfile(findings_path):
            content = open(findings_path).read()
            finding_count = content.count('- id: F')
            strength_count = content.count('- id: S')
            log(f'Findings: {finding_count} issues, {strength_count} strengths cataloged')

        # ---- ASSESSMENT ----
        assess_prompt, ref_count = _build_assessment_prompt(
            project_dir, eval_dir, eval_timestamp, scope_description,
            project_title, genre_display, args.final, api_mode,
        )

        if assess_prompt:
            log(f'Running assessment pass ({ref_count} reference files)...')
            assess_start = time.time()
            assess_model = select_model('synthesis')
            assess_log = os.path.join(log_dir, 'eval-assessment.log')

            if api_mode:
                log(f'Running assessment via direct API (model: {assess_model})...')
                response = invoke_to_file(assess_prompt, assess_model, assess_log, max_tokens=8192,
                                          system=system)
                assess_response = extract_text(response)
                if assess_response:
                    with open(os.path.join(eval_dir, 'assessment.md'), 'w') as f:
                        f.write(assess_response)
            else:
                subprocess.run(
                    ['claude', assess_prompt,
                     '--model', assess_model,
                     '--dangerously-skip-permissions'],
                    cwd=project_dir,
                )

            assess_duration = int(time.time() - assess_start)
            _log_usage(project_dir, assess_log, 'assess', 'assessment', assess_model, assess_duration)

            assess_path = os.path.join(eval_dir, 'assessment.md')
            if os.path.isfile(assess_path):
                assess_words = len(open(assess_path).read().split())
                log(f'SUCCESS: Assessment complete ({assess_words} words, {assess_duration // 60}m{assess_duration % 60}s)')
            else:
                log('WARNING: assessment.md not created')

            update_pr_task('Assessment', project_dir)
        else:
            log('No reference files found -- skipping assessment pass')

    # ---- GIT COMMIT ----
    log('Committing evaluation files...')
    commit_and_push(
        project_dir,
        f'Evaluation: {scope_description} ({len(succeeded)}/{all_evaluator_count} evaluators)',
        [
            f'working/evaluations/eval-{eval_timestamp}/',
            'working/logs/',
            'working/costs/',
            'working/pipeline.csv',
        ],
    )

    # ---- SESSION SUMMARY ----
    session_duration = int(time.time() - _wall_start)
    session_mins = session_duration // 60
    session_secs = session_duration % 60

    log('============================================')
    log('Evaluation panel complete!')
    log(f'  Project: {project_title}')
    log(f'  Scope: {scope_description}')
    log(f'  Reports: {eval_dir}/')
    if args.evaluator:
        log(f'  Evaluator: {args.evaluator}')
    else:
        log(f'  Succeeded: {len(succeeded)}/{all_evaluator_count} evaluators + synthesis')
    if os.path.isfile(os.path.join(eval_dir, 'assessment.md')):
        log('  Assessment: yes (execution vs. intent)')
    if failed:
        log(f'  Failed: {" ".join(failed)}')
    log(f'  Time: {session_mins}m{session_secs}s')
    log('============================================')
    log('')
    log('Next steps:')
    log(f'  Read the synthesis:  cat {eval_dir}/synthesis.md')
    if os.path.isfile(os.path.join(eval_dir, 'assessment.md')):
        log(f'  Read the assessment: cat {eval_dir}/assessment.md')
    if os.path.isfile(os.path.join(eval_dir, 'findings.yaml')):
        log(f'  Browse findings:    cat {eval_dir}/findings.yaml')
    log(f'  Read individual:    ls {eval_dir}/')

    # Write word count snapshot for staleness detection
    _write_word_count_snapshot(eval_dir, project_dir)

    # Cost summary
    print_summary(project_dir, 'evaluate', session_start=session_start)
    print_summary(project_dir, 'synthesize', session_start=session_start)
    print_summary(project_dir, 'assess', session_start=session_start)

    # Mark cycle complete
    if cycle_id != '0':
        _update_cycle(project_dir, cycle_id, 'status', 'complete')

    # Exit with failure if any evaluator failed
    if failed:
        sys.exit(1)
