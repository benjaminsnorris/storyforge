"""storyforge revise -- Execute revision passes from a revision plan.

Reads working/plans/revision-plan.csv (or legacy .yaml) and executes each
pass in order. Supports --polish for craft-only, --naturalness for targeted
AI pattern removal (3 passes), and --structural for CSV-only revision.

Usage:
    storyforge revise                 # Start from first pending pass
    storyforge revise 3               # Start from pass number 3 (1-indexed)
    storyforge revise --polish        # Craft-only polish plan
    storyforge revise --polish --loop # Score → polish → re-score until stable
    storyforge revise --naturalness   # 3-pass AI pattern removal
    storyforge revise --structural    # CSV-only from structural proposals
    storyforge revise --dry-run       # Print prompts only
"""

import argparse
import csv
import json
import os
import re
import subprocess
import sys
import time

from storyforge.common import (
    detect_project_root, log, set_log_file, read_yaml_field,
    select_model, select_revision_model, get_coaching_level,
    install_signal_handlers, get_plugin_dir,
)
from storyforge.costs import estimate_cost, log_operation, print_summary
from storyforge.git import (
    create_branch, ensure_branch_pushed, create_draft_pr,
    update_pr_task, commit_and_push, _git, has_gh, current_branch,
)
from storyforge.api import (
    invoke_api, invoke_to_file, extract_text, extract_text_from_file,
    extract_usage, calculate_cost_from_usage, get_api_key,
    REVISION_TIMEOUT, max_output_tokens,
)
from storyforge.cli import apply_coaching_override


# ============================================================================
# Argument parsing
# ============================================================================

def parse_args(argv):
    parser = argparse.ArgumentParser(
        prog='storyforge revise',
        description='Execute revision passes from a revision plan.',
    )
    parser.add_argument('--dry-run', action='store_true',
                        help='Build and print prompts without invoking Claude')
    parser.add_argument('--interactive', '-i', action='store_true',
                        help='Supervise each pass interactively')
    parser.add_argument('--structural', action='store_true',
                        help='Auto-generate plan from structural proposals (CSV-only)')
    parser.add_argument('--naturalness', action='store_true',
                        help='Auto-generate 3-pass plan targeting AI prose patterns')
    parser.add_argument('--polish', action='store_true',
                        help='Auto-generate craft-only polish plan')
    parser.add_argument('--coaching', choices=['full', 'coach', 'strict'],
                        help='Override coaching level')
    parser.add_argument('--loop', action='store_true',
                        help='Autonomous convergence loop: score → polish → re-score until stable (requires --polish)')
    parser.add_argument('--max-loops', type=int, default=5,
                        help='Maximum iterations in --loop mode (default: 5)')
    parser.add_argument('--skip-initial-score', action='store_true',
                        help='Skip initial scoring in --polish --loop (use existing scores)')
    parser.add_argument('pass_num', nargs='?', type=int, default=0,
                        help='Start from this pass number (1-indexed; default: first pending)')
    return parser.parse_args(argv)


# ============================================================================
# CSV plan helpers
# ============================================================================

CSV_PLAN_FIELDS = ['pass', 'name', 'purpose', 'scope', 'targets', 'guidance',
                   'protection', 'findings', 'status', 'model_tier', 'fix_location']


def _read_csv_plan(plan_file):
    """Read the CSV revision plan. Returns list of row dicts."""
    if not os.path.isfile(plan_file):
        return []
    rows = []
    with open(plan_file) as f:
        reader = csv.DictReader(f, delimiter='|')
        for row in reader:
            rows.append({k: (v if v is not None else '') for k, v in row.items()})
    return rows


def _write_csv_plan(plan_file, rows):
    """Write the CSV revision plan (in-place update to an existing file)."""
    os.makedirs(os.path.dirname(plan_file), exist_ok=True)
    with open(plan_file, 'w') as f:
        f.write('|'.join(CSV_PLAN_FIELDS) + '\n')
        for row in rows:
            f.write('|'.join(row.get(field, '') for field in CSV_PLAN_FIELDS) + '\n')


def _next_plan_number(plans_dir):
    """Find the next revision plan number by scanning existing numbered files."""
    highest = 0
    if os.path.isdir(plans_dir):
        for name in os.listdir(plans_dir):
            if name.startswith('revision-plan-') and name.endswith('.csv'):
                try:
                    n = int(name[len('revision-plan-'):-len('.csv')])
                    highest = max(highest, n)
                except ValueError:
                    pass
    return highest + 1


def _create_versioned_plan(plan_file, rows):
    """Write a new versioned revision plan and update the symlink.

    plan_file is the canonical symlink path (working/plans/revision-plan.csv).
    Creates revision-plan-N.csv and points the symlink at it.
    """
    plans_dir = os.path.dirname(plan_file)
    os.makedirs(plans_dir, exist_ok=True)
    num = _next_plan_number(plans_dir)
    numbered_name = f'revision-plan-{num}.csv'
    numbered_file = os.path.join(plans_dir, numbered_name)
    _write_csv_plan(numbered_file, rows)

    # Update symlink (handle existing symlink, regular file, or nothing)
    if os.path.islink(plan_file):
        os.remove(plan_file)
    elif os.path.exists(plan_file):
        os.remove(plan_file)
    os.symlink(numbered_name, plan_file)
    return numbered_file


def _count_passes(rows):
    return len(rows)


def _read_pass_field(rows, pass_num, field):
    """Read a field from a pass (1-indexed)."""
    idx = pass_num - 1
    if 0 <= idx < len(rows):
        return rows[idx].get(field, '')
    return ''


def _update_pass_field(rows, pass_num, field, value, plan_file):
    """Update a field for a pass and write back."""
    idx = pass_num - 1
    if 0 <= idx < len(rows):
        rows[idx][field] = value
        _write_csv_plan(plan_file, rows)


# ============================================================================
# Auto-generated plans
# ============================================================================

def _generate_polish_plan(plan_file):
    """Generate a single-pass craft-only polish plan."""
    rows = [{
        'pass': '1',
        'name': 'prose-polish',
        'purpose': 'Voice consistency, prose naturalness, dialogue authenticity, AI pattern cleanup',
        'scope': 'full',
        'targets': '',
        'guidance': 'Follow the voice guide strictly. Focus on: em dash overuse, antithesis framing, tricolon, hedge-stacking, sentence rhythm variety. Enter late, leave early.',
        'protection': 'voice-quality',
        'findings': 'polish',
        'status': 'pending',
        'model_tier': 'opus',
        'fix_location': 'craft',
    }]
    numbered = _create_versioned_plan(plan_file, rows)
    log(f'Generated single-pass polish plan: {numbered}')
    return rows


def _generate_naturalness_plan(plan_file):
    """Generate 3-pass plan for AI prose pattern removal.

    Targets the patterns most frequently penalized in scoring rationales:
    tricolon/parallelism, em-dash/antithesis, and AI vocabulary/hedging.
    """
    rows = [
        {
            'pass': '1',
            'name': 'tricolon-parallelism',
            'purpose': 'Break compulsive three-item structures — triple-sensation chains, three-beat lists, three-clause parallel constructions',
            'scope': 'full',
            'targets': '',
            'guidance': (
                'Find every instance of three-item parallelism and vary the count or structure. '
                'PATTERNS TO FIX: '
                '(a) Three-adjective chains: "gold deepening to persimmon deepening to red" — vary to 2 or 4, or restructure. '
                '(b) Three-clause parallelism: "too short for the counter, too narrow for the bowls, too wide for the space" — collapse to 1-2 clauses or vary rhythm. '
                '(c) Triple-sensation stacking: "Color. Taste. Sight interpretation." repeated as a template — break the template, vary which senses appear and in what order. '
                '(d) Three-item lists in narration: "the noodle shop level, the market corridor, the junction" — sometimes 2 is enough. '
                'NOT EVERY THREE-ITEM LIST IS WRONG. Only fix the ones that feel mechanical or templated. '
                'Organic tricolon in dialogue or emphatic prose is fine. The test: could a reader predict the third item? If yes, fix it.'
            ),
            'protection': 'Do not change dialogue content, plot events, or character actions. Only modify prose rhythm and structure.',
            'findings': 'naturalness',
            'status': 'pending',
            'model_tier': 'opus',
            'fix_location': 'craft',
        },
        {
            'pass': '2',
            'name': 'em-dash-antithesis',
            'purpose': 'Reduce em-dash frequency and eliminate "Not X but Y" antithesis framing',
            'scope': 'full',
            'targets': '',
            'guidance': (
                'Two patterns to fix: '
                '(a) EM-DASH OVERUSE: Count em dashes in each scene. Target: max 3-4 per 1000 words. '
                'Replace with: periods (for parenthetical asides), commas (for appositives), '
                'colons (for elaboration), or restructure the sentence. Keep em dashes only for genuine interruptions or abrupt shifts. '
                '(b) ANTITHESIS FRAMING: Find "Not X. Y." / "Not X but Y" / "Not X — Y" constructions. '
                'BEFORE: "Not reflecting-the-sky black, just black." '
                'AFTER: Describe what it IS without first saying what it ISN\'T. Negation-then-correction is a Claude tic. '
                'Also fix: "Not literally X but..." and "Less X than Y" when used as the primary description.'
            ),
            'protection': 'Do not change dialogue, plot, or character actions. Preserve em dashes in dialogue for speech interruptions.',
            'findings': 'naturalness',
            'status': 'pending',
            'model_tier': 'opus',
            'fix_location': 'craft',
        },
        {
            'pass': '3',
            'name': 'ai-vocabulary-hedging',
            'purpose': 'Remove AI-tell vocabulary, hedging stacks, sweeping openers, and summary closers',
            'scope': 'full',
            'targets': '',
            'guidance': (
                'Four patterns to fix: '
                '(a) AI-TELL VOCABULARY: Remove or replace these words that signal AI-generated prose: '
                'nuanced, multifaceted, tapestry, palpable, pivotal, intricate, profound, myriad, '
                'juxtaposition, dichotomy, paradigm, visceral (when not literal). Replace with concrete, specific words. '
                '(b) HEDGING STACKS: "something like", "something between", "almost as if", "perhaps", '
                '"a kind of", "the particular" — remove or commit to the statement. '
                'BEFORE: "Something that tasted the way silence feels." AFTER: Name the taste. '
                '(c) SWEEPING OPENERS: Remove scene-opening sentences that set a thematic frame before anything happens. '
                '"The thing about memory is..." / "There are moments when..." — cut to the first concrete action or image. '
                '(d) SUMMARY CLOSERS: Remove paragraph-ending sentences that interpret what was just shown. '
                '"And that was the thing about X." / "It was, she realized, exactly what she needed." — let the scene end on action or image.'
            ),
            'protection': 'Do not change dialogue, plot events, or character interiority that reveals new information.',
            'findings': 'naturalness',
            'status': 'pending',
            'model_tier': 'opus',
            'fix_location': 'craft',
        },
    ]
    numbered = _create_versioned_plan(plan_file, rows)
    log(f'Generated 3-pass naturalness plan: {numbered}')
    return rows


def _generate_structural_plan(project_dir, plan_file):
    """Generate CSV-only plan from structural proposals."""
    proposals_file = os.path.join(project_dir, 'working', 'scores', 'structural-proposals.csv')
    if not os.path.isfile(proposals_file):
        log(f'ERROR: No structural proposals found at {proposals_file}')
        log('Run: storyforge-validate --structural')
        sys.exit(1)

    # Read proposals
    proposals = []
    with open(proposals_file) as f:
        reader = csv.DictReader(f, delimiter='|')
        for row in reader:
            row = {k: (v if v is not None else '') for k, v in row.items()}
            if row.get('status', '').strip() == 'pending':
                proposals.append(row)

    if not proposals:
        log(f'ERROR: No pending proposals in {proposals_file}')
        sys.exit(1)

    # Save pre-revision scores
    pre_scores = os.path.join(project_dir, 'working', 'scores', 'structural-latest.csv')
    if os.path.isfile(pre_scores):
        import shutil
        shutil.copy2(pre_scores, os.path.join(project_dir, 'working', 'scores', 'structural-pre-revision.csv'))

    log(f'Structural mode -- generating plan from {len(proposals)} proposals...')

    # Group by dimension
    from collections import OrderedDict
    groups = OrderedDict()
    for row in proposals:
        dim = row['dimension']
        if dim not in groups:
            groups[dim] = {'fix_location': row['fix_location'], 'targets': [], 'rationales': []}
        target = row.get('target', 'global').strip()
        if target and target != 'global':
            groups[dim]['targets'].append(target)
        groups[dim]['rationales'].append(row.get('rationale', row.get('change', '')))

    # Sort by fix_location priority
    priority = {'structural': 0, 'intent': 1, 'registry': 2, 'brief': 3}
    sorted_dims = sorted(groups.items(), key=lambda x: priority.get(x[1]['fix_location'], 9))

    rows = []
    for i, (dim, info) in enumerate(sorted_dims, 1):
        rows.append({
            'pass': str(i),
            'name': f'structural-{dim.replace("_", "-")}',
            'purpose': '; '.join(info['rationales']),
            'scope': 'full',
            'targets': ';'.join(info['targets']) if info['targets'] else '',
            'guidance': '',
            'protection': 'all-strengths',
            'findings': '',
            'status': 'pending',
            'model_tier': 'sonnet',
            'fix_location': info['fix_location'],
        })

    _create_versioned_plan(plan_file, rows)

    for i, (dim, info) in enumerate(sorted_dims, 1):
        log(f'  Pass {i}: {dim} (fix_location: {info["fix_location"]})')

    return rows


# ============================================================================
# Polish convergence loop
# ============================================================================

def _read_diagnosis(cycle_dir: str) -> list[dict]:
    """Read diagnosis.csv from a scoring cycle dir. Returns list of row dicts."""
    diag_file = os.path.join(cycle_dir, 'diagnosis.csv')
    if not os.path.isfile(diag_file):
        return []
    rows = []
    with open(diag_file) as f:
        reader = csv.DictReader(f, delimiter='|')
        for row in reader:
            rows.append({k: (v if v is not None else '') for k, v in row.items()})
    return rows


def _summarize_diagnosis(diag_rows: list[dict]) -> dict:
    """Summarize diagnosis into counts and key metrics."""
    high = [r for r in diag_rows if r.get('priority') == 'high' and r.get('scale') == 'scene']
    medium = [r for r in diag_rows if r.get('priority') == 'medium' and r.get('scale') == 'scene']
    scene_rows = [r for r in diag_rows if r.get('scale') == 'scene']

    avg_scores = []
    for r in scene_rows:
        try:
            avg_scores.append(float(r.get('avg_score', '0')))
        except ValueError:
            pass

    overall_avg = sum(avg_scores) / len(avg_scores) if avg_scores else 0.0

    return {
        'high_count': len(high),
        'medium_count': len(medium),
        'high_principles': [r['principle'] for r in high],
        'medium_principles': [r['principle'] for r in medium],
        'overall_avg': overall_avg,
        'scene_principle_count': len(scene_rows),
    }


def _generate_targeted_polish_plan(plan_file: str, diag_rows: list[dict]) -> list[dict]:
    """Generate a polish plan targeted at high/medium priority principles from diagnosis."""
    high = [r for r in diag_rows if r.get('priority') == 'high' and r.get('scale') == 'scene']
    medium = [r for r in diag_rows if r.get('priority') == 'medium' and r.get('scale') == 'scene']

    targets = high + medium
    if not targets:
        # Nothing specific to target — fall back to general polish
        return _generate_polish_plan(plan_file)

    # Build guidance from diagnosis findings
    guidance_parts = []
    for row in targets:
        principle = row['principle'].replace('_', ' ')
        avg = row.get('avg_score', '?')
        worst = row.get('worst_items', '')
        prio = row.get('priority', 'medium')
        part = f'{principle} (avg {avg}, {prio})'
        if worst:
            scenes = worst.split(';')[:3]
            part += f' — weakest in: {", ".join(scenes)}'
        guidance_parts.append(part)

    guidance = (
        'Diagnosis-driven polish. Priority principles to improve:\n'
        + '\n'.join(f'  - {g}' for g in guidance_parts)
        + '\nFollow the voice guide strictly. Preserve all plot, character, and continuity.'
    )

    worst_scenes = set()
    for row in targets:
        for sid in row.get('worst_items', '').split(';'):
            if sid.strip():
                worst_scenes.add(sid.strip())

    rows = [{
        'pass': '1',
        'name': 'targeted-polish',
        'purpose': f'Address {len(high)} high and {len(medium)} medium priority craft principles',
        'scope': 'full',
        'targets': ';'.join(sorted(worst_scenes)) if worst_scenes else '',
        'guidance': guidance,
        'protection': 'voice-quality',
        'findings': 'polish',
        'status': 'pending',
        'model_tier': 'opus',
        'fix_location': 'craft',
    }]
    _create_versioned_plan(plan_file, rows)
    return rows


def _run_lightweight_score(project_dir: str, scene_ids: list[str],
                           parallel: int = 6) -> tuple[str, list[dict]]:
    """Run scene-level scoring only (no branch/PR) and return (cycle_dir, diagnosis_rows).

    This is a lightweight path for the polish loop — scores scenes, generates
    diagnosis, but skips branch creation, PR, act/character/genre scoring.
    """
    from storyforge.scoring import (
        build_evaluation_criteria, build_weighted_text,
        init_craft_weights, generate_diagnosis, merge_score_files,
    )

    plugin_dir = get_plugin_dir()
    scores_base = os.path.join(project_dir, 'working', 'scores')
    log_dir = os.path.join(project_dir, 'working', 'logs')

    # Determine cycle
    highest = 0
    if os.path.isdir(scores_base):
        for name in os.listdir(scores_base):
            if name.startswith('cycle-'):
                try:
                    highest = max(highest, int(name.removeprefix('cycle-')))
                except ValueError:
                    pass
    cycle = highest + 1
    cycle_dir = os.path.join(scores_base, f'cycle-{cycle}')
    os.makedirs(cycle_dir, exist_ok=True)
    os.makedirs(log_dir, exist_ok=True)

    # Initialize weights
    init_craft_weights(project_dir, plugin_dir)
    weights_file = os.path.join(project_dir, 'working', 'craft-weights.csv')

    # Load scoring templates
    prompts_dir = os.path.join(plugin_dir, 'scripts', 'prompts', 'scoring')
    diagnostics_csv = os.path.join(plugin_dir, 'references', 'diagnostics.csv')
    guide_file = os.path.join(plugin_dir, 'references', 'principle-guide.md')
    eval_template_file = os.path.join(prompts_dir, 'scene-evaluation.md')

    with open(eval_template_file) as f:
        eval_template = f.read()

    evaluation_criteria = build_evaluation_criteria(diagnostics_csv, guide_file)
    weighted_text_str = build_weighted_text(weights_file, exclude_section='narrative')

    # Use sonnet for speed in loop scoring
    eval_model = select_model('evaluation')

    metadata_csv = os.path.join(project_dir, 'reference', 'scenes.csv')
    intent_csv = os.path.join(project_dir, 'reference', 'scene-intent.csv')
    scenes_dir = os.path.join(project_dir, 'scenes')

    log(f'  Scoring {len(scene_ids)} scenes (cycle {cycle}, model: {eval_model})...')

    # Import scoring internals
    from storyforge.cmd_score import _score_direct, _build_scene_prompt, _parse_scene_evaluation

    import time as _time
    scored, failed = _score_direct(
        scene_ids, eval_model, eval_template, evaluation_criteria,
        weighted_text_str, metadata_csv, intent_csv, scenes_dir,
        cycle_dir, log_dir, diagnostics_csv, plugin_dir,
        parallel, _time.time(),
    )

    log(f'  Scored: {scored}, failed: {failed}')

    # Generate diagnosis
    prev_dir = ''
    if highest > 0:
        prev_dir = os.path.join(scores_base, f'cycle-{highest}')

    generate_diagnosis(cycle_dir, prev_dir or '-', weights_file)

    # Update latest symlink
    latest_link = os.path.join(scores_base, 'latest')
    if os.path.islink(latest_link):
        os.remove(latest_link)
    os.symlink(f'cycle-{cycle}', latest_link)

    diag_rows = _read_diagnosis(cycle_dir)
    return cycle_dir, diag_rows


def _detect_upstream_scenes(project_dir: str, diag_rows: list[dict]) -> list[str]:
    """Identify scenes needing upstream fixes based on diagnosis root_cause.

    Returns sorted list of scene IDs where root_cause is 'brief' and score is low.
    Scene IDs are drawn from the worst_items field of matching diagnosis rows.
    """
    upstream = set()
    for row in diag_rows:
        if row.get('root_cause') != 'brief':
            continue
        worst = row.get('worst_items', '')
        if not worst:
            continue
        for sid in worst.split(';'):
            sid = sid.strip()
            if sid:
                upstream.add(sid)
    return sorted(upstream)


def _fix_upstream_briefs(project_dir: str, scene_ids: list[str]) -> int:
    """Rewrite conflict/goal/crisis/decision for scenes with upstream issues.

    Uses API to generate briefs with genuine dramatic opposition.
    Returns number of fields rewritten.
    """
    from storyforge.elaborate import _read_csv_as_map, _write_csv, _FILE_MAP, _read_csv

    ref_dir = os.path.join(project_dir, 'reference')
    briefs_path = os.path.join(ref_dir, 'scene-briefs.csv')
    scenes_path = os.path.join(ref_dir, 'scenes.csv')
    intent_path = os.path.join(ref_dir, 'scene-intent.csv')

    briefs_map = _read_csv_as_map(briefs_path)
    scenes_map = _read_csv_as_map(scenes_path)
    intent_map = _read_csv_as_map(intent_path)

    total_rewrites = 0

    for scene_id in scene_ids:
        brief = briefs_map.get(scene_id, {})
        scene = scenes_map.get(scene_id, {})
        intent = intent_map.get(scene_id, {})

        title = scene.get('title', scene_id)
        pov = scene.get('pov', '')
        outcome = brief.get('outcome', '')
        value_at_stake = intent.get('value_at_stake', '')
        emotional_arc = intent.get('emotional_arc', '')
        current_goal = brief.get('goal', '')
        current_conflict = brief.get('conflict', '')
        current_crisis = brief.get('crisis', '')
        current_decision = brief.get('decision', '')

        prompt = f"""You are a story editor rewriting scene briefs to introduce genuine dramatic opposition.

Scene: {title}
POV: {pov}
Outcome: {outcome}
Value at stake: {value_at_stake}
Emotional arc: {emotional_arc}

Current brief:
GOAL: {current_goal}
CONFLICT: {current_conflict}
CRISIS: {current_crisis}
DECISION: {current_decision}

The current brief lacks genuine opposition — the conflict is abstract or the goal/crisis/decision don't create real dramatic tension.

Rewrite all four fields to introduce genuine opposition while:
- Preserving the existing emotional arc and value at stake
- Making the conflict a concrete, specific obstacle with a clear opposing force
- Making the goal something the POV character actively wants and must fight for
- Making the crisis a specific moment where the worst happens or the hardest choice appears
- Making the decision a concrete choice with real cost on both sides

Respond ONLY with the four fields in this exact format (no preamble, no explanation):
GOAL: [rewritten goal]
CONFLICT: [rewritten conflict]
CRISIS: [rewritten crisis]
DECISION: [rewritten decision]"""

        model = select_model('creative')
        log(f'  Fixing upstream brief: {scene_id}')
        response = invoke_api(prompt, model, max_tokens=1024)

        if not response:
            log(f'  WARNING: No response for {scene_id} upstream fix — skipping')
            continue

        # Parse response lines
        fields = {}
        for line in response.splitlines():
            for key in ('GOAL', 'CONFLICT', 'CRISIS', 'DECISION'):
                prefix = f'{key}: '
                if line.startswith(prefix):
                    fields[key.lower()] = line[len(prefix):].strip()

        if not fields:
            log(f'  WARNING: Could not parse upstream fix response for {scene_id}')
            continue

        updated = False
        for field_name, new_value in fields.items():
            if new_value:
                briefs_map.setdefault(scene_id, {'id': scene_id})
                briefs_map[scene_id][field_name] = new_value
                total_rewrites += 1
                updated = True

        if updated:
            log(f'  Updated {len(fields)} fields for {scene_id}')

    # Write back updated briefs
    if total_rewrites > 0:
        all_briefs = list(briefs_map.values())
        _write_csv(briefs_path, all_briefs, _FILE_MAP['scene-briefs.csv'])

    return total_rewrites


def _redraft_scenes(project_dir: str, scene_ids: list[str]) -> int:
    """Re-draft scenes after brief rewrites using brief-aware drafting.

    Only re-drafts scenes that already have a scene file.
    Returns number of scenes re-drafted.
    """
    from storyforge.prompts import build_scene_prompt
    from storyforge.common import get_coaching_level

    scenes_dir = os.path.join(project_dir, 'scenes')
    coaching_level = get_coaching_level(project_dir)
    model = select_model('creative')
    count = 0

    for scene_id in scene_ids:
        scene_file = os.path.join(scenes_dir, f'{scene_id}.md')
        if not os.path.isfile(scene_file):
            log(f'  Skipping re-draft of {scene_id} (not yet drafted)')
            continue

        log(f'  Re-drafting scene: {scene_id}')
        try:
            prompt = build_scene_prompt(scene_id, project_dir,
                                        coaching_level=coaching_level, api_mode=True)
        except Exception as e:
            log(f'  WARNING: Could not build prompt for {scene_id}: {e} — skipping')
            continue

        response = invoke_api(prompt, model, max_tokens=16384)
        if not response:
            log(f'  WARNING: No response for {scene_id} re-draft — skipping')
            continue

        with open(scene_file, 'w', encoding='utf-8') as f:
            f.write(response)

        count += 1
        log(f'  Re-drafted {scene_id}')

    return count


def _run_polish_loop(project_dir: str, max_loops: int,
                     coaching_override: str | None, *,
                     skip_initial_score: bool = False) -> None:
    """Score → polish → re-score convergence loop."""
    from storyforge.common import get_coaching_level, read_yaml_field
    from storyforge.git import create_branch, ensure_branch_pushed, commit_and_push
    from storyforge.scene_filter import build_scene_list

    if coaching_override:
        os.environ['STORYFORGE_COACHING'] = coaching_override

    title = read_yaml_field('project.title', project_dir) or '(untitled)'
    metadata_csv = os.path.join(project_dir, 'reference', 'scenes.csv')
    scenes_dir = os.path.join(project_dir, 'scenes')

    # Build scene list (only drafted scenes)
    all_ids = build_scene_list(metadata_csv)
    scene_ids = [sid for sid in all_ids
                 if os.path.isfile(os.path.join(scenes_dir, f'{sid}.md'))]

    if not scene_ids:
        log('ERROR: No drafted scenes found.')
        sys.exit(1)

    # Create branch once for the whole loop
    create_branch('revise', project_dir)
    ensure_branch_pushed(project_dir)

    log('============================================')
    log(f'Storyforge Polish Loop — {title}')
    log(f'Scenes: {len(scene_ids)}')
    log(f'Max iterations: {max_loops}')
    log('============================================')

    csv_plan_file = os.path.join(project_dir, 'working', 'plans', 'revision-plan.csv')
    prev_avg = 0.0
    baseline_summary = None

    for iteration in range(1, max_loops + 1):
        log(f'\n=== Iteration {iteration}/{max_loops}: Score ===')

        if iteration == 1 and skip_initial_score:
            # Load existing scores instead of running a new scoring cycle
            latest_dir = os.path.join(project_dir, 'working', 'scores', 'latest')
            if not os.path.isdir(latest_dir):
                log('ERROR: --skip-initial-score but no existing scores in working/scores/latest')
                sys.exit(1)
            diag_rows = _read_diagnosis(latest_dir)
            if not diag_rows:
                log('WARNING: No diagnosis found in existing scores — generating empty baseline')
            log('  Skipped initial scoring (--skip-initial-score) — using existing scores')
            summary = _summarize_diagnosis(diag_rows)
        else:
            cycle_dir, diag_rows = _run_lightweight_score(project_dir, scene_ids)
            summary = _summarize_diagnosis(diag_rows)

        if iteration == 1:
            baseline_summary = summary

        log(f'  Overall avg: {summary["overall_avg"]:.2f}')
        log(f'  High priority: {summary["high_count"]} principles')
        log(f'  Medium priority: {summary["medium_count"]} principles')
        if summary['high_principles']:
            log(f'    High: {", ".join(p.replace("_", " ") for p in summary["high_principles"])}')

        # Convergence check: no actionable issues
        if summary['high_count'] == 0 and summary['medium_count'] == 0:
            log('  No high or medium priority issues — converged')
            break

        # Convergence check: scores stopped improving
        if iteration > 1 and summary['overall_avg'] <= prev_avg:
            log(f'  Overall avg did not improve ({summary["overall_avg"]:.2f} <= {prev_avg:.2f}) — converged')
            break

        prev_avg = summary['overall_avg']

        # Check for upstream causes before craft polish
        upstream_scenes = _detect_upstream_scenes(project_dir, diag_rows)
        if upstream_scenes:
            log(f'  Upstream issues in {len(upstream_scenes)} scenes — fixing briefs first')
            _fix_upstream_briefs(project_dir, upstream_scenes)
            _redraft_scenes(project_dir, upstream_scenes)
            commit_and_push(project_dir,
                            f'Polish: upstream brief fixes for {len(upstream_scenes)} scenes',
                            ['reference/', 'scenes/', 'working/'])

        # Generate targeted plan from diagnosis
        log(f'\n=== Iteration {iteration}/{max_loops}: Polish ===')
        plan_rows = _generate_targeted_polish_plan(csv_plan_file, diag_rows)

        # Execute the single polish pass
        # Reset status to pending
        plan_rows[0]['status'] = 'pending'
        _write_csv_plan(csv_plan_file, plan_rows)

        # Run the pass through the standard execution path
        _execute_single_pass(project_dir, csv_plan_file, plan_rows, iteration)

    else:
        log(f'\n  Reached max iterations ({max_loops})')

    # Final score for summary
    log(f'\n=== Final Score ===')
    _, final_diag = _run_lightweight_score(project_dir, scene_ids)
    final_summary = _summarize_diagnosis(final_diag)

    log('\n============================================')
    log('Polish loop complete')
    if baseline_summary:
        log(f'  Before: avg {baseline_summary["overall_avg"]:.2f}, '
            f'{baseline_summary["high_count"]} high / {baseline_summary["medium_count"]} medium priority')
    log(f'  After:  avg {final_summary["overall_avg"]:.2f}, '
        f'{final_summary["high_count"]} high / {final_summary["medium_count"]} medium priority')
    if baseline_summary and baseline_summary['overall_avg'] > 0:
        delta = final_summary['overall_avg'] - baseline_summary['overall_avg']
        log(f'  Improvement: {delta:+.2f} avg score')
    log('============================================')

    commit_and_push(project_dir, 'Polish: loop complete', ['working/'])


def _extract_scene_rationales(project_dir: str, scene_ids: list,
                              principles: list = None) -> dict:
    """Extract scoring rationales for specific scenes from the latest scoring cycle.

    Args:
        project_dir: Project root.
        scene_ids: Scenes to extract rationales for.
        principles: Principles to include (default: all *_rationale columns).

    Returns:
        {scene_id: {principle: rationale_text}}
    """
    from storyforge.elaborate import _read_csv_as_map

    latest_dir = os.path.join(project_dir, 'working', 'scores', 'latest')
    scores_file = os.path.join(latest_dir, 'scene-scores.csv')
    if not os.path.isfile(scores_file):
        return {}

    scores_map = _read_csv_as_map(scores_file)
    result = {}

    for sid in scene_ids:
        row = scores_map.get(sid)
        if not row:
            continue
        rationales = {}
        for col, val in row.items():
            if not col or not col.endswith('_rationale') or not val:
                continue
            principle = col[:-len('_rationale')]
            if principles and principle not in principles:
                continue
            rationales[principle] = val
        if rationales:
            result[sid] = rationales

    return result


def _build_revision_config(plan_row: dict, extra: dict | None = None) -> str:
    """Build a YAML config string from plan row fields for passing to revision.py.

    Only includes non-empty values for the known config fields: guidance,
    protection, findings, targets.  Additional optional data (e.g. rationale
    from Task 9) can be supplied via *extra*.

    Args:
        plan_row: A single plan CSV row dict.
        extra: Optional dict of additional key→value pairs to append.

    Returns:
        A YAML string, or empty string if no config fields are present.
    """
    config_fields = ['guidance', 'protection', 'findings', 'targets']
    lines = []
    for field in config_fields:
        value = plan_row.get(field, '')
        if value:
            # Indent multi-line values as a YAML block scalar
            if '\n' in value:
                indented = value.replace('\n', '\n  ')
                lines.append(f'{field}: |-\n  {indented}')
            else:
                lines.append(f'{field}: {value}')
    if extra:
        for key, value in extra.items():
            if value:
                if '\n' in str(value):
                    indented = str(value).replace('\n', '\n  ')
                    lines.append(f'{key}: |-\n  {indented}')
                else:
                    lines.append(f'{key}: {value}')
    return '\n'.join(lines)


def _execute_single_pass(project_dir: str, csv_plan_file: str,
                         plan_rows: list[dict], iteration: int) -> None:
    """Execute a single revision pass from a plan. Subset of main pass loop."""
    from storyforge.common import select_revision_model, get_coaching_level
    from storyforge.git import commit_and_push
    from storyforge.api import invoke_to_file, extract_text

    pass_name = plan_rows[0].get('name', 'polish')
    pass_purpose = plan_rows[0].get('purpose', '')
    pass_scope = plan_rows[0].get('scope', 'full')
    guidance = plan_rows[0].get('guidance', '')
    fix_location = plan_rows[0].get('fix_location', 'craft')

    log(f'  Pass: {pass_name}')
    log(f'  Purpose: {pass_purpose[:120]}...' if len(pass_purpose) > 120 else f'  Purpose: {pass_purpose}')

    # Mark in_progress
    _update_pass_field(plan_rows, 1, 'status', 'in_progress', csv_plan_file)

    # Build prompt via the revision module (subprocess)
    plugin_dir = get_plugin_dir()
    revision_module = os.path.join(plugin_dir, 'scripts', 'lib', 'python', 'storyforge', 'revision.py')

    import subprocess
    # Extract per-scene rationales for targeted revision
    rationales = None
    targets_field = plan_rows[0].get('targets', '')
    if targets_field:
        target_ids = [s.strip() for s in targets_field.split(';') if s.strip()]
        rationales = _extract_scene_rationales(project_dir, target_ids)
    elif plan_rows[0].get('findings') == 'naturalness':
        # For naturalness passes, get rationales for all scenes
        from storyforge.scene_filter import build_scene_list
        metadata_csv = os.path.join(project_dir, 'reference', 'scenes.csv')
        all_ids = build_scene_list(metadata_csv)
        rationales = _extract_scene_rationales(project_dir, all_ids,
                                                principles=['prose_naturalness'])

    # Build config with rationales as extra data
    extra = {}
    if rationales:
        scene_findings = []
        for sid, rats in rationales.items():
            for principle, text in rats.items():
                # Truncate long rationales to keep prompt manageable
                scene_findings.append(f'Scene {sid} ({principle}): {text[:500]}')
        if scene_findings:
            extra['per_scene_findings'] = '\n'.join(scene_findings)

    config_yaml = _build_revision_config(plan_rows[0], extra=extra)
    cmd = [
        sys.executable, revision_module, 'build-prompt',
        pass_name, pass_purpose, pass_scope, project_dir,
        '--api-mode',
    ]
    if config_yaml:
        cmd.extend(['--config', config_yaml])

    log(f'  Building revision prompt...')
    result = subprocess.run(cmd, capture_output=True, text=True)
    if result.returncode != 0:
        log(f'  ERROR building prompt: {result.stderr[:500]}')
        return

    prompt = result.stdout

    # Select model and invoke API
    pass_model = select_revision_model(pass_name, pass_purpose)
    log_dir = os.path.join(project_dir, 'working', 'logs')
    step_log = os.path.join(log_dir, f'loop-{iteration}-{pass_name}.json')

    log(f'  Invoking API (model: {pass_model})...')
    try:
        invoke_to_file(prompt, pass_model, step_log,
                       max_tokens=max_output_tokens(pass_model),
                       label=f'polish loop {iteration} ({pass_name})',
                       timeout=REVISION_TIMEOUT)
    except Exception as e:
        log(f'  API call failed: {e}')
        return

    # Extract scenes from response
    log(f'  Extracting revised scenes...')
    parsing_module = os.path.join(plugin_dir, 'scripts', 'lib', 'python', 'storyforge', 'parsing.py')
    subprocess.run(
        [sys.executable, parsing_module, 'extract-scenes',
         '--project-dir', project_dir, '--log-file', step_log],
        capture_output=True, text=True,
    )

    # Update word counts
    _update_word_counts_from_dir(project_dir)

    # Mark completed
    _update_pass_field(plan_rows, 1, 'status', 'completed', csv_plan_file)

    # Commit
    import time as _time
    elapsed = 0  # We don't track per-pass time in loop mode
    commit_and_push(
        project_dir,
        f'Polish: loop iteration {iteration} — {pass_name}',
        ['scenes/', 'reference/', 'working/'],
    )


def _update_word_counts_from_dir(project_dir: str) -> None:
    """Update word counts in scenes.csv from scene files."""
    from storyforge.elaborate import _read_csv, _write_csv, _FILE_MAP
    metadata_csv = os.path.join(project_dir, 'reference', 'scenes.csv')
    scenes_dir = os.path.join(project_dir, 'scenes')

    rows = _read_csv(metadata_csv)
    for row in rows:
        scene_file = os.path.join(scenes_dir, f'{row["id"]}.md')
        if os.path.isfile(scene_file):
            with open(scene_file) as f:
                wc = len(f.read().split())
            row['word_count'] = str(wc)

    _write_csv(metadata_csv, rows, _FILE_MAP['scenes.csv'])


# ============================================================================
# Usage logging helper
# ============================================================================

def _log_usage(project_dir, log_file, operation, target, model, duration_s=0):
    """Log API usage from a response file."""
    if not os.path.isfile(log_file):
        return
    try:
        with open(log_file) as f:
            response = json.load(f)
        usage = extract_usage(response)
        cost = calculate_cost_from_usage(usage, model)
        log_operation(
            project_dir, operation, model,
            usage['input_tokens'], usage['output_tokens'], cost,
            duration_s=duration_s, target=target,
            cache_read=usage.get('cache_read', 0),
            cache_create=usage.get('cache_create', 0),
        )
    except (json.JSONDecodeError, FileNotFoundError, KeyError):
        pass


# ============================================================================
# Word count estimation
# ============================================================================

def _estimate_avg_words(project_dir):
    """Estimate average scene word count."""
    metadata_csv = os.path.join(project_dir, 'reference', 'scenes.csv')
    if os.path.isfile(metadata_csv):
        from storyforge.csv_cli import get_column
        wc_col = get_column(metadata_csv, 'word_count')
        total = sum(int(w) for w in wc_col if w and w != '0')
        count = sum(1 for w in wc_col if w and w != '0')
        if count > 0:
            return total // count, count

    # Fall back to scene files
    scenes_dir = os.path.join(project_dir, 'scenes')
    total = 0
    count = 0
    if os.path.isdir(scenes_dir):
        for f in os.listdir(scenes_dir):
            if f.endswith('.md'):
                wc = len(open(os.path.join(scenes_dir, f)).read().split())
                total += wc
                count += 1

    if count > 0:
        return total // count, count
    return 3000, 1


# ============================================================================
# Scene registration for new scenes created during revision
# ============================================================================

def _register_new_scenes(project_dir, targets, pass_name):
    """Register new scenes (NEW: prefix in targets) in metadata CSVs."""
    meta_csv = os.path.join(project_dir, 'reference', 'scenes.csv')
    intent_csv = os.path.join(project_dir, 'reference', 'scene-intent.csv')

    new_ids = []
    for t in targets.split(';'):
        t = t.strip()
        if t.startswith('NEW:'):
            new_ids.append(t[4:])

    if not new_ids:
        return

    # Find max seq
    max_seq = 0
    if os.path.isfile(meta_csv):
        with open(meta_csv) as f:
            for line in f:
                parts = line.strip().split('|')
                if len(parts) >= 2:
                    try:
                        seq = int(parts[1])
                        if seq > max_seq:
                            max_seq = seq
                    except ValueError:
                        pass

    registered = 0
    for sid in new_ids:
        scene_file = os.path.join(project_dir, 'scenes', f'{sid}.md')
        if not os.path.isfile(scene_file):
            continue

        # Check if already registered
        if os.path.isfile(meta_csv):
            with open(meta_csv) as f:
                if any(line.startswith(f'{sid}|') for line in f):
                    continue

        max_seq += 1
        wc = len(open(scene_file).read().split())

        # Generate title from slug
        title = ' '.join(w.capitalize() for w in sid.split('-'))

        if os.path.isfile(meta_csv):
            from storyforge.csv_cli import append_row
            append_row(meta_csv, f'{sid}|{max_seq}|{title}|||||||drafted|{wc}|')
            log(f'  Registered new scene in metadata: {sid} (seq {max_seq})')

        if os.path.isfile(intent_csv):
            from storyforge.csv_cli import append_row
            append_row(intent_csv, f'{sid}|Created by revision pass: {pass_name}|||||')
            log(f'  Registered new scene in intent: {sid}')

        registered += 1

    if registered > 0:
        log(f'  Registered {registered} new scene(s) in metadata and intent CSVs')


# ============================================================================
# Main
# ============================================================================

def main(argv=None):
    args = parse_args(argv or [])
    install_signal_handlers()

    project_dir = detect_project_root()

    log_dir = os.path.join(project_dir, 'working', 'logs')
    os.makedirs(log_dir, exist_ok=True)
    set_log_file(os.path.join(log_dir, 'revision-log.txt'))

    python_lib = os.path.join(os.path.dirname(os.path.dirname(__file__)))

    # Resolve plan file
    csv_plan_file = os.path.join(project_dir, 'working', 'plans', 'revision-plan.csv')
    yaml_plan_file = os.path.join(project_dir, 'working', 'plans', 'revision-plan.yaml')

    # Check mutually exclusive modes
    mode_count = sum([args.structural, args.polish, args.naturalness])
    if mode_count > 1:
        print('ERROR: --structural, --polish, and --naturalness are mutually exclusive.', file=sys.stderr)
        sys.exit(1)

    # Validate --loop
    if args.loop:
        if not args.polish:
            print('ERROR: --loop requires --polish', file=sys.stderr)
            sys.exit(1)
        if args.dry_run:
            print('ERROR: --loop and --dry-run are incompatible', file=sys.stderr)
            sys.exit(1)
        if args.interactive:
            print('ERROR: --loop and --interactive are incompatible', file=sys.stderr)
            sys.exit(1)

    # Validate --skip-initial-score
    if args.skip_initial_score and not args.loop:
        print('ERROR: --skip-initial-score requires --loop', file=sys.stderr)
        sys.exit(1)

    # Loop mode — takes over execution entirely
    if args.loop:
        _run_polish_loop(project_dir, args.max_loops, args.coaching,
                         skip_initial_score=args.skip_initial_score)
        return

    # Auto-generate plans
    if args.polish:
        log('Polish mode -- generating craft-only revision plan...')
        plan_rows = _generate_polish_plan(csv_plan_file)
    elif args.naturalness:
        log('Naturalness mode -- generating 3-pass plan for AI pattern removal...')
        # Check for upstream causes first (load latest diagnosis if available)
        _naturalness_diag_rows = []
        _latest_diag = os.path.join(project_dir, 'working', 'scores', 'latest', 'diagnosis.csv')
        if os.path.isfile(_latest_diag):
            _naturalness_diag_rows = _read_diagnosis(os.path.dirname(_latest_diag))
        upstream_scenes = _detect_upstream_scenes(project_dir, _naturalness_diag_rows) if _naturalness_diag_rows else []
        if upstream_scenes:
            log(f'Upstream issues in {len(upstream_scenes)} scenes — fixing briefs')
            _fix_upstream_briefs(project_dir, upstream_scenes)
            _redraft_scenes(project_dir, upstream_scenes)
            commit_and_push(project_dir, 'Naturalness: upstream brief fixes',
                            ['reference/', 'scenes/', 'working/'])
        plan_rows = _generate_naturalness_plan(csv_plan_file)
    elif args.structural:
        plan_rows = _generate_structural_plan(project_dir, csv_plan_file)
    elif os.path.isfile(csv_plan_file):
        log(f'Using CSV revision plan: {csv_plan_file}')
        plan_rows = _read_csv_plan(csv_plan_file)
    elif os.path.isfile(yaml_plan_file):
        log('DEPRECATION: Using YAML revision plan. Migrate to working/plans/revision-plan.csv.')
        # For YAML fallback, we just read it via the original bash approach.
        # The Python migration handles CSV-first plans.
        log('ERROR: YAML plan support not available in Python migration. Convert to CSV.')
        sys.exit(1)
    else:
        log(f'ERROR: Revision plan not found at {csv_plan_file}')
        log("Run the storyforge-plan-revision skill first to create a revision plan.")
        sys.exit(1)

    total_passes = _count_passes(plan_rows)
    if total_passes == 0:
        log('ERROR: No passes found in revision plan')
        sys.exit(1)

    # Coaching level
    if args.coaching:
        apply_coaching_override(args)
    effective_coaching = get_coaching_level(project_dir)

    # API key check
    if not args.dry_run and not args.interactive:
        try:
            get_api_key()
        except RuntimeError:
            log('ERROR: ANTHROPIC_API_KEY not set. Required for direct API mode.')
            log('  Set it with: export ANTHROPIC_API_KEY=your-key')
            log('  Or use --interactive to run via claude -p instead.')
            sys.exit(1)

    os.makedirs(os.path.join(project_dir, 'working', 'coaching'), exist_ok=True)

    # Determine start point
    start_pass = args.pass_num
    if start_pass == 0:
        for i in range(1, total_passes + 1):
            status = _read_pass_field(plan_rows, i, 'status')
            if status == 'planned':
                log(f"WARNING: Pass {i} has status 'planned' -- normalizing to 'pending'")
                _update_pass_field(plan_rows, i, 'status', 'pending', csv_plan_file)
                status = 'pending'
            if status in ('pending', 'in_progress'):
                start_pass = i
                break
        if start_pass == 0:
            log('All passes are already completed. Nothing to do.')
            return

    if start_pass < 1 or start_pass > total_passes:
        log(f'ERROR: Pass number {start_pass} is out of range (1-{total_passes})')
        sys.exit(1)

    # Project title
    project_title = read_yaml_field('project.title', project_dir) or '(untitled project)'

    # Pipeline manifest
    manifest = os.path.join(project_dir, 'working', 'pipeline.csv')
    cycle_id = '0'
    if os.path.isfile(manifest):
        with open(manifest) as f:
            lines = f.readlines()
        if len(lines) > 1:
            cycle_id = lines[-1].strip().split('|')[0]

    # Branch + PR setup
    if not args.dry_run:
        create_branch('revise', project_dir)
        ensure_branch_pushed(project_dir)

        task_lines = ['### Progress']
        for i in range(1, total_passes + 1):
            pname = _read_pass_field(plan_rows, i, 'name')
            task_lines.append(f'- [ ] Pass: {pname}')
        task_lines.append('- [ ] Review')

        pr_body = (
            f'## Revision\n\n'
            f'**Project:** {project_title}\n'
            f'**Passes:** {total_passes}\n\n'
            + '\n'.join(task_lines)
        )

        create_draft_pr(f'Revise: {project_title}', pr_body, project_dir, 'revision')

    if not args.dry_run and cycle_id != '0':
        # Update pipeline cycle
        if os.path.isfile(manifest):
            with open(manifest) as f:
                lines = f.readlines()
            header = lines[0].strip().split('|')
            if 'status' in header:
                idx = header.index('status')
                for i in range(1, len(lines)):
                    parts = lines[i].strip().split('|')
                    if parts[0] == cycle_id:
                        while len(parts) <= idx:
                            parts.append('')
                        parts[idx] = 'revising'
                        lines[i] = '|'.join(parts) + '\n'
                with open(manifest, 'w') as f:
                    f.writelines(lines)

    log('============================================')
    log(f'Storyforge Revision -- {project_title}')
    log(f'Plan: {csv_plan_file}')
    log(f'Cycle: {cycle_id}')
    log(f'Coaching level: {effective_coaching}')
    log(f'Starting from pass: {start_pass} of {total_passes}')
    log('============================================')

    # Cost forecast
    if not args.dry_run:
        pending = sum(
            1 for i in range(start_pass, total_passes + 1)
            if _read_pass_field(plan_rows, i, 'status') != 'completed'
        )
        avg_words, scene_count = _estimate_avg_words(project_dir)
        revise_model = select_revision_model('prose', 'prose revision')
        per_pass = estimate_cost('revise', scene_count, avg_words, revise_model)
        total_forecast = per_pass * pending
        log(f'Cost forecast: ~${total_forecast:.2f} ({pending} passes @ ~${per_pass:.2f})')

    # ---- MAIN PASS LOOP ----
    for pass_num in range(start_pass, total_passes + 1):
        pass_name = _read_pass_field(plan_rows, pass_num, 'name')
        pass_scope = _read_pass_field(plan_rows, pass_num, 'scope')
        pass_purpose = _read_pass_field(plan_rows, pass_num, 'purpose')
        pass_status = _read_pass_field(plan_rows, pass_num, 'status')

        if pass_status == 'planned':
            _update_pass_field(plan_rows, pass_num, 'status', 'pending', csv_plan_file)
            pass_status = 'pending'

        if pass_status == 'completed':
            log(f'Pass {pass_num}/{total_passes}: {pass_name} -- already completed, skipping.')
            continue

        log(f'--- Pass {pass_num}/{total_passes}: {pass_name} ---')
        log(f'  Purpose: {pass_purpose}')
        log(f'  Scope: {pass_scope}')

        # Build CSV config block for prompt
        targets = _read_pass_field(plan_rows, pass_num, 'targets')
        guidance = _read_pass_field(plan_rows, pass_num, 'guidance')
        protection = _read_pass_field(plan_rows, pass_num, 'protection')
        findings = _read_pass_field(plan_rows, pass_num, 'findings')
        fix_location = _read_pass_field(plan_rows, pass_num, 'fix_location')

        # Resolve effective scope
        effective_scope = pass_scope
        if pass_scope in ('scene-level', 'targeted') and targets:
            effective_scope = targets.replace(';', ',')
        elif pass_scope in ('scene-level', 'targeted'):
            effective_scope = 'full'

        # Build config block for prompt builder
        pass_block = f'- name: {pass_name}\n    purpose: {pass_purpose}\n    scope: {pass_scope}'
        if targets:
            pass_block += f'\n    targets: {targets}'
        if guidance:
            pass_block += f'\n    guidance: {guidance}'
        if protection:
            pass_block += f'\n    protection: {protection}'
        if findings:
            pass_block += f'\n    findings: {findings}'

        # Determine API mode flags
        api_flag = ''
        if not args.dry_run and not args.interactive and os.environ.get('ANTHROPIC_API_KEY'):
            api_flag = '--api-mode'

        # Build prompt
        log('  Building revision prompt...')
        if fix_location in ('brief', 'intent', 'structural', 'registry'):
            # Upstream revision prompt -- built inline via Python
            from storyforge.elaborate import get_scenes
            ref_dir = os.path.join(project_dir, 'reference')
            scenes = get_scenes(ref_dir)

            target_ids = [t.strip() for t in targets.split(';') if t.strip()] if targets else [s['id'] for s in scenes]
            scene_data = [s for s in scenes if s['id'] in target_ids]

            data_block = []
            for s in scene_data:
                data_block.append(f"Scene: {s.get('id', '')} (seq {s.get('seq', '')}, POV: {s.get('pov', '')})")
                for k, v in s.items():
                    if k not in ('id', 'seq', 'pov') and v:
                        data_block.append(f'  {k}: {str(v)[:120]}')
                data_block.append('')

            file_map = {
                'brief': 'scene-briefs.csv',
                'intent': 'scene-intent.csv',
                'structural': 'scenes.csv',
            }
            csv_type_map = {
                'brief': 'briefs-csv',
                'intent': 'intent-csv',
                'structural': 'scenes-csv',
            }

            prompt = f'''You are performing an upstream revision on scene data for a novel.

## Pass: {pass_name}
## Purpose: {pass_purpose}
## Fix Location: {fix_location}

## Guidance
{guidance or 'No specific guidance provided.'}

## Protection
{protection or 'No protection constraints.'}

## Current Scene Data

{chr(10).join(data_block)}

## Instructions

Revise the {file_map.get(fix_location, 'scenes.csv')} data to address the purpose above.

Output your changes as pipe-delimited CSV rows in a fenced block:

```{csv_type_map.get(fix_location, 'scenes-csv')}
(header row)
(one row per scene that needs changes)
```

Rules:
- Only modify scenes listed in the targets
- Preserve all values you are not changing
- Output the full row for each modified scene
'''
        else:
            # Standard prose revision -- use revision module
            try:
                result = subprocess.run(
                    [sys.executable, '-m', 'storyforge.revision', 'build-prompt',
                     pass_name, pass_purpose, effective_scope or pass_scope, project_dir,
                     '--config', pass_block, '--coaching', effective_coaching]
                    + ([api_flag] if api_flag else []),
                    capture_output=True, text=True, check=True,
                    env={**os.environ, 'PYTHONPATH': python_lib},
                )
                prompt = result.stdout
            except subprocess.CalledProcessError as e:
                log(f'ERROR: Failed to build prompt for pass \'{pass_name}\'')
                log(f'  {e.stderr}')
                sys.exit(1)

        # Dry-run: print and continue
        if args.dry_run:
            print(f'===== DRY RUN: {pass_name} (pass {pass_num}/{total_passes}) =====')
            print(prompt)
            print(f'===== END DRY RUN: {pass_name} =====')
            print()
            continue

        # Mark as in_progress
        _update_pass_field(plan_rows, pass_num, 'status', 'in_progress', csv_plan_file)

        # Record git HEAD before invocation
        head_before = _git(project_dir, 'rev-parse', 'HEAD', check=False).stdout.strip()

        step_log = os.path.join(log_dir, f'revision-pass-{pass_num}-{pass_name}.log')
        start_time = time.time()

        # Select model
        pass_model = select_revision_model(pass_name, pass_purpose)

        if args.interactive:
            # Interactive mode
            subprocess.run(
                ['claude', prompt,
                 '--model', pass_model,
                 '--dangerously-skip-permissions'],
                cwd=project_dir,
            )
            exit_code = 0
        else:
            # Direct API mode
            log(f'  Invoking API for revision (model: {pass_model})...')
            try:
                response = invoke_to_file(prompt, pass_model, step_log,
                                         max_tokens=max_output_tokens(pass_model),
                                         label=f'pass {pass_num}/{total_passes} ({pass_name})',
                                         timeout=REVISION_TIMEOUT)
                exit_code = 0
            except Exception as e:
                log(f'  API call failed: {e}')
                exit_code = 1

            # Check for truncation
            if exit_code == 0:
                stop = response.get('stop_reason', 'end_turn')
                if stop == 'max_tokens':
                    log(f'  WARNING: Pass "{pass_name}" was truncated (hit max_tokens). '
                        f'The last scene in the output will be discarded to prevent data loss.')

            # Process response
            if exit_code == 0:
                if fix_location in ('brief', 'intent', 'structural', 'registry'):
                    # Upstream revision -- apply CSV updates
                    log(f'  Upstream revision (fix_location: {fix_location}) -- applying CSV updates...')
                    try:
                        from storyforge.prompts_elaborate import parse_stage_response, csv_block_to_rows
                        from storyforge.elaborate import _read_csv_as_map, _write_csv, _FILE_MAP

                        response_text = extract_text(response)

                        blocks = parse_stage_response(response_text)
                        updated_files = []
                        affected_scenes = set()

                        csv_file_map = {
                            'scenes-csv': ('scenes.csv', _FILE_MAP['scenes.csv']),
                            'scenes-csv-update': ('scenes.csv', _FILE_MAP['scenes.csv']),
                            'intent-csv': ('scene-intent.csv', _FILE_MAP['scene-intent.csv']),
                            'briefs-csv': ('scene-briefs.csv', _FILE_MAP['scene-briefs.csv']),
                        }

                        ref_dir = os.path.join(project_dir, 'reference')
                        for label, content in blocks.items():
                            if label not in csv_file_map:
                                continue
                            rows = csv_block_to_rows(content)
                            if not rows:
                                continue

                            fname, cols = csv_file_map[label]
                            path = os.path.join(ref_dir, fname)
                            existing = _read_csv_as_map(path)

                            for row in rows:
                                sid = row.get('id', '')
                                if not sid:
                                    continue
                                affected_scenes.add(sid)
                                if sid in existing:
                                    existing[sid].update({k: v for k, v in row.items() if v and k != 'id'})
                                else:
                                    new = {c: '' for c in cols}
                                    new.update(row)
                                    existing[sid] = new

                            if label.startswith('scenes-csv'):
                                ordered = sorted(existing.values(), key=lambda r: int(r.get('seq', 0)))
                            else:
                                ordered = sorted(existing.values(), key=lambda r: r.get('id', ''))
                            _write_csv(path, ordered, cols)
                            updated_files.append(fname)

                        log(f'  Updated: {", ".join(updated_files) if updated_files else "no CSV blocks found"}')
                        log(f'  Affected scenes: {", ".join(sorted(affected_scenes)) if affected_scenes else "none"}')
                    except Exception as e:
                        log(f'  WARNING: Failed to apply upstream changes: {e}')
                else:
                    # Standard prose revision -- extract scenes from response
                    try:
                        result = subprocess.run(
                            [sys.executable, '-m', 'storyforge.parsing', 'extract-scenes',
                             step_log, os.path.join(project_dir, 'scenes')],
                            capture_output=True, text=True,
                            env={**os.environ, 'PYTHONPATH': python_lib},
                        )
                        if result.stdout.strip():
                            for line in result.stdout.strip().splitlines():
                                log(f'  {line}')
                        else:
                            log('  API response received (analytical pass, no scene markers)')
                    except Exception:
                        log('  API response received (could not parse scene content)')

                    # Register new scenes
                    if targets:
                        _register_new_scenes(project_dir, targets, pass_name)

        end_time = time.time()
        duration = int(end_time - start_time)
        minutes = duration // 60
        secs = duration % 60

        # Log usage
        _log_usage(project_dir, step_log, 'revise', pass_name, pass_model, duration)

        if exit_code != 0:
            log(f'ERROR: API call failed for pass \'{pass_name}\' after {minutes}m{secs}s')
            log(f'See full output: {step_log}')
            log(f'Fix the issue and re-run: storyforge revise {pass_num}')
            sys.exit(1)

        # Update word counts
        metadata_csv = os.path.join(project_dir, 'reference', 'scenes.csv')
        if os.path.isfile(metadata_csv) and effective_coaching == 'full':
            from storyforge.csv_cli import list_ids, update_field
            for scene_id in list_ids(metadata_csv):
                scene_file = os.path.join(project_dir, 'scenes', f'{scene_id}.md')
                if os.path.isfile(scene_file):
                    new_wc = str(len(open(scene_file).read().split()))
                    update_field(metadata_csv, scene_id, 'word_count', new_wc)

        # Git commit if Claude didn't
        head_after = _git(project_dir, 'rev-parse', 'HEAD', check=False).stdout.strip()
        if head_before == head_after:
            log('  No commit from Claude. Creating manual commit...')
            if effective_coaching in ('coach', 'strict'):
                commit_and_push(
                    project_dir,
                    f'{effective_coaching.capitalize()}: {pass_name}',
                    ['working/coaching/', 'working/logs/', 'working/costs/', 'working/pipeline.csv'],
                )
            else:
                commit_and_push(project_dir, f'Revision: {pass_name}', ['.'])

        # Push
        _git(project_dir, 'push', check=False)

        # Mark completed
        _update_pass_field(plan_rows, pass_num, 'status', 'completed', csv_plan_file)

        commit_short = _git(project_dir, 'rev-parse', '--short', 'HEAD', check=False).stdout.strip()
        log(f'SUCCESS: Pass {pass_num}/{total_passes} ({pass_name}) -- {minutes}m{secs}s, commit {commit_short}')
        update_pr_task(f'Pass: {pass_name}', project_dir)

        # Pause between passes (headless only)
        if pass_num < total_passes and not args.interactive:
            next_status = _read_pass_field(plan_rows, pass_num + 1, 'status')
            if next_status != 'completed':
                log('Pausing 10s before next pass...')
                time.sleep(10)

    # ---- SESSION SUMMARY ----
    completed = sum(
        1 for i in range(1, total_passes + 1)
        if _read_pass_field(plan_rows, i, 'status') == 'completed'
    )

    log('')
    log('============================================')
    log(f'Revision session complete. {completed}/{total_passes} passes finished.')

    # Structural mode: re-validate
    if args.structural and not args.dry_run:
        log('Re-running structural validation...')
        try:
            from storyforge.structural import (
                structural_score, save_structural_scores,
                load_scores_as_dict, print_score_delta,
            )
            ref_dir = os.path.join(project_dir, 'reference')
            report = structural_score(ref_dir)
            save_structural_scores(report, project_dir)

            pre_path = os.path.join(project_dir, 'working', 'scores', 'structural-pre-revision.csv')
            post_path = os.path.join(project_dir, 'working', 'scores', 'structural-latest.csv')
            pre = load_scores_as_dict(pre_path)
            post = load_scores_as_dict(post_path)

            print('\n=== Structural Score Delta ===')
            print(print_score_delta(pre, post))
            print(f'\nOverall: {report.get("overall", 0):.2f}')

            # Mark proposals as completed
            proposals_file = os.path.join(project_dir, 'working', 'scores', 'structural-proposals.csv')
            if os.path.isfile(proposals_file):
                content = open(proposals_file).read()
                content = content.replace('|pending', '|completed')
                with open(proposals_file, 'w') as f:
                    f.write(content)
                log('Marked all proposals as completed')
        except Exception as e:
            log(f'WARNING: Structural re-validation failed: {e}')

    # Cost summary
    if not args.dry_run:
        print_summary(project_dir, 'revise')

    if completed == total_passes:
        log('All revision passes are done!')
        os.makedirs(os.path.join(project_dir, 'working', 'reviews'), exist_ok=True)
        commit_and_push(
            project_dir,
            'Revision complete: advance phase to review',
            ['storyforge.yaml', 'working/pipeline.csv'],
        )
        log('')
        log('Next step: run /storyforge:revise to review results, or /storyforge:score to measure improvement')

    log('============================================')
