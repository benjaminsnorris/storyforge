"""storyforge score — Principled craft scoring for Storyforge projects.

Evaluates manuscript scenes against the craft engine's scoring rubrics,
producing per-scene, per-act, and novel-level scores in CSV format.

Three scoring modes:
  (default)     Batch API, Opus — best value and judgment
  --direct      Direct API, Sonnet — real-time results for interactive use
  --direct --deep  Direct API, Opus — real-time Opus when you need results now

Usage:
    storyforge score                        # All scenes, batch Opus
    storyforge score --direct --scenes ID   # Sonnet, one scene, real-time
    storyforge score --direct --deep --act 2
    storyforge score --dry-run              # Show what would be scored
    storyforge score --no-apply             # Report proposals, never apply them (evals)
    storyforge score --complete-cycle       # Fill in the newest incomplete cycle's gaps
"""

import argparse
import hashlib
import json
from dataclasses import dataclass
import os
import re
import subprocess
import sys
import time

from storyforge.common import (
    detect_project_root, log, set_log_file, read_yaml_field, select_model,
    model_for_tier, get_coaching_level, get_current_cycle,
    install_signal_handlers, get_plugin_dir, build_shared_context,
    is_unfilled_template,
)
from storyforge.git import (
    create_branch, ensure_branch_pushed, create_draft_pr, commit_and_push,
    update_pr_task, has_gh,
)
from storyforge.cli import add_scene_filter_args, resolve_filter_args, apply_coaching_override
from storyforge.illustrations import read_scene_prose
from storyforge.api import (
    invoke_to_file, extract_text, extract_text_from_file, extract_usage,
    calculate_cost_from_usage, submit_batch, poll_batch, download_batch_results,
    stop_problem, is_truncated,
    build_batch_request,
)
from storyforge.costs import (
    estimate_cost, check_threshold, exit_if_bad_threshold, log_operation, print_summary,
)
from storyforge.scene_filter import build_scene_list, apply_scene_filter
from storyforge.csv_cli import get_field, get_column, update_field


def parse_args(argv):
    parser = argparse.ArgumentParser(
        prog='storyforge score',
        description='Score manuscript scenes against 25 craft principles.',
    )
    parser.add_argument('--dry-run', action='store_true',
                        help='Show what would be scored without invoking Claude')
    parser.add_argument('--interactive', '-i', action='store_true',
                        help='Enable interactive mode')
    parser.add_argument('--direct', action='store_true',
                        help='Direct API with Sonnet — real-time results')
    parser.add_argument('--deep', action='store_true',
                        help='Use Opus for direct API (requires --direct)')
    parser.add_argument('--scenes', type=str, default=None,
                        help='Comma-separated scene IDs')
    parser.add_argument('--act', type=str, default=None,
                        help='Score scenes in act N')
    parser.add_argument('--from-seq', type=str, default=None,
                        help='Start from sequence number (N or N-M range)')
    parser.add_argument('--principles', type=str, default=None,
                        help='Comma-separated craft principles to score '
                             '(e.g. prose_repetition,prose_naturalness)')
    parser.add_argument('--deterministic', action='store_true',
                        help='Score only deterministic principles (no API calls)')
    parser.add_argument('--readability', action='store_true',
                        help='Print each scene\'s reading level (Flesch-Kincaid grade) '
                             'and the pooled figure for the scenes in scope (the book\'s '
                             'with no filter), against project.reading_level when set. '
                             'No API calls, no cycle, nothing written. Every scoring '
                             'cycle (full or --deterministic) also writes it, to '
                             'readability.csv. Prose projects only.')
    parser.add_argument('--register', action='store_true',
                        help='Print the register check for the scenes in scope (the '
                             'book\'s with no filter): a source translation\'s archaic '
                             'words, grammar and idiom carried into the prose, and runs '
                             'of dialogue copied from the source scene a scene adapts '
                             '(#615). Skips what the voice guide\'s "Register exemptions" '
                             'allow. No API calls, no cycle, nothing written. Prose '
                             'projects only.')
    parser.add_argument('--parallel', type=int,
                        default=int(os.environ.get('STORYFORGE_SCORE_PARALLEL', '6')),
                        help='Parallel workers for direct mode (default: 6)')
    parser.add_argument('--no-apply', action='store_true',
                        help='Write the diagnosis and proposals but never apply '
                             'them, whatever the coaching level (calibration and '
                             'eval runs on a book that should not change)')
    parser.add_argument('--diagnosis-only', action='store_true',
                        help='Generate diagnosis and proposals from existing scores '
                             '(skip scoring, run improvement cycle only)')
    # Elaboration entry points: deterministic floor checks + comparison.
    parser.add_argument('--level', type=int, default=None,
                        choices=range(0, 7), metavar='N',
                        help='Run floor checks for elaboration level N (0-6). '
                             'Levels: 0=logline, 1=synopsis, 2=act-shape, '
                             '3=spine, 4=architecture, 5=scene-map, 6=briefs.')
    parser.add_argument('--all-levels', action='store_true',
                        help='Run floor checks for every elaboration level (0-6).')
    parser.add_argument('--compare', nargs='+', metavar='CANDIDATE',
                        help='Compare 2-4 candidate artifacts at the same level '
                             '(used with --level for prose-tier levels). Each '
                             'candidate is a file path or a literal text string.')
    parser.add_argument('--drift', action='store_true',
                        help='Read-only drift report: which levels are out of '
                             'sync vs. git HEAD, registries, or each other.')
    # LLM-driven elaboration scoring entry points.
    parser.add_argument('--boundary', type=str, default=None, metavar='N->M',
                        help='Run the LLM faithfulness diff at one level '
                             'boundary (e.g. 5->6). Optional --scope filters '
                             'to one scene/anchor/event.')
    parser.add_argument('--all-boundaries', action='store_true',
                        help='Run the LLM faithfulness diff at every boundary '
                             '(0->1 through 6->7).')
    parser.add_argument('--scope', type=str, default=None,
                        help='Restrict --boundary or --bible-consistency to '
                             'one scope id (scene/anchor/event).')
    parser.add_argument('--semantic', action='store_true',
                        help='Modifier on --compare: populate the LLM ceiling '
                             'axes (specificity, irony, hook word, etc.) '
                             'instead of leaving them as em-dash placeholders.')
    parser.add_argument('--bible-consistency', action='store_true',
                        help='LLM-check each drafted scene against the project '
                             'bibles (character/world/voice). On-demand only.')
    parser.add_argument('--source-fidelity', choices=('briefs', 'prose'), default=None,
                        help='Adaptations only (a source: block): check the briefs '
                             '(before any prose) or the prose against the source '
                             'scenes they adapt, and nothing else. A full scoring '
                             'run (without --principles/--deterministic) already '
                             'checks the prose.')
    parser.add_argument('--complete-cycle', nargs='?', const='newest', default=None,
                        metavar='CYCLE',
                        help='Re-score only the parts an incomplete cycle\'s incomplete.txt '
                             'lists (source fidelity scenes, acts, novel-level character or '
                             'genre, narrative) into that same cycle; with every part filled, '
                             'the file is cleared, the diagnosis rebuilt, and the cycle '
                             'becomes latest (unless a newer cycle is). CYCLE is N or '
                             'cycle-N (default: the newest incomplete cycle). Refuses when '
                             'what those parts read changed since the cycle was scored '
                             '(prose, briefs for brief parts, and the reference files act '
                             'and novel-level scoring read). Scene scores and brief fidelity '
                             'are not filled: re-score the cycle for those.')
    parser.add_argument('--text-fidelity', action='store_true',
                        help='Check the upper tiers (logline, synopsis, act-shape, theme, '
                             'spine, architecture) against the book\'s prose: split into '
                             'claims, each judged against the scenes it cites. Report only. '
                             'Needs prose.')
    parser.add_argument('--story-power', action='store_true',
                        help='Run the story-power scorecard (8 craft axes) on '
                             'logline + synopsis + theme + spine + architecture. '
                             'Coaching-aware: full LLM-scores, coach writes a '
                             'review brief, strict produces a self-scoring '
                             'checklist with no LLM call.')
    return parser.parse_args(argv)


# Principles that can be scored without any API calls.
DETERMINISTIC_PRINCIPLES = frozenset([
    'prose_repetition',
    'avoid_passive',
    'avoid_adverbs',
    'no_weather_dreams',
    'sentence_as_thought',
    'economy_clarity',
])


def _load_known_principles(plugin_dir: str) -> set[str]:
    """Load all known principle names from default-craft-weights.csv."""
    weights_path = os.path.join(plugin_dir, 'references', 'default-craft-weights.csv')
    if not os.path.isfile(weights_path):
        return set()
    principles = set()
    with open(weights_path) as f:
        header = f.readline().strip().split('|')
        p_idx = header.index('principle') if 'principle' in header else 1
        for line in f:
            fields = line.strip().split('|')
            if len(fields) > p_idx and fields[p_idx]:
                principles.add(fields[p_idx])
    return principles


def _parse_principles(raw: str, plugin_dir: str) -> list[str]:
    """Parse and validate the --principles flag value.

    Returns a list of validated principle names.
    Exits with an error message if any principle name is unrecognised.
    """
    requested = [p.strip() for p in raw.split(',') if p.strip()]
    known = _load_known_principles(plugin_dir)
    if not known:
        return requested  # graceful fallback when weights file missing
    unknown = [p for p in requested if p not in known]
    if unknown:
        log(f'ERROR: Unknown principle(s): {", ".join(unknown)}')
        log(f'Known principles: {", ".join(sorted(known))}')
        sys.exit(1)
    return requested


def _validate_flag_combinations(args) -> None:
    """Reject incoherent elaboration-entry-point combinations with a clear error.

    Each entry point is mutually exclusive — silent precedence rules make
    expensive flags (like --bible-consistency) easy to misfire.
    """
    triggers = []
    if args.bible_consistency:
        triggers.append('--bible-consistency')
    if args.boundary:
        triggers.append('--boundary')
    if args.all_boundaries:
        triggers.append('--all-boundaries')
    if args.compare:
        triggers.append('--compare')
    if args.drift:
        triggers.append('--drift')
    if args.all_levels:
        triggers.append('--all-levels')
    if args.level is not None and not args.compare:
        triggers.append('--level')
    if args.story_power:
        triggers.append('--story-power')
    if args.text_fidelity:
        triggers.append('--text-fidelity')
    if len(triggers) > 1:
        log(f'ERROR: these flags cannot be combined: {", ".join(triggers)}. '
            'Pick one entry point and re-run.')
        sys.exit(1)

    # --scope only applies to --boundary and --bible-consistency.
    if args.scope and not (args.boundary or args.bible_consistency):
        log('ERROR: --scope only applies to --boundary or --bible-consistency. '
            'For --all-boundaries, drop --scope and run all boundaries; for '
            'prose-tier comparison and the story-power scorecard, --scope is '
            'not meaningful (these operate on whole-project artifacts).')
        sys.exit(1)


def _check_llm_preconditions(operation: str, dry_run: bool) -> None:
    """Verify ANTHROPIC_API_KEY is set before an LLM dispatch.

    Skipped in dry-run mode (no API call will happen). Calls sys.exit(1)
    with a clear message when the key is missing; this catches the case
    before invoke_to_file raises a less-actionable network error.
    """
    if dry_run:
        return
    if not os.environ.get('ANTHROPIC_API_KEY'):
        log(f'ERROR: ANTHROPIC_API_KEY is not set. {operation} requires '
            'an API key. Set it and re-run, or use --dry-run to preview '
            'without calling the LLM.')
        sys.exit(1)


def _run_text_fidelity(project_dir: str, dry_run: bool) -> None:
    """`score --text-fidelity`: the upper tiers against the book's prose
    (`scoring_text_fidelity`). Report only; nothing is committed."""
    from storyforge import scoring_text_fidelity as tf
    from storyforge.common import read_yaml_field
    model = select_model('synthesis')
    tiers = tf.read_tiers(project_dir)
    if tiers.empty():
        log('ERROR: no upper tiers to check: story-summary.md is the template, and '
            'spine.csv and architecture.csv are empty (extract --phase 5 writes them)')
        sys.exit(1)
    scenes = tf._scenes(project_dir)
    if not any(tf._prose(project_dir, r['id']) for r in scenes):
        log('ERROR: no scene has prose to check the tiers against')
        sys.exit(1)
    first = tf.forecast_claims(tiers, scenes, model)
    log(f'Text fidelity: claims pass ~${first:.2f} ({model}); the check pass is '
        f'forecast once the claims are known')
    if dry_run:
        for docs in (tiers.summary_docs(), tiers.story_architecture):
            if docs:
                print(tf.build_claims_prompt(docs, scenes)[:3000])
        return
    if not check_threshold(first):
        log('Cost threshold check declined. Aborting.')
        sys.exit(1)
    _check_llm_preconditions('--text-fidelity', dry_run=False)

    spent = []

    def on_usage(path, label):
        import json
        from storyforge.costs import log_operation
        with open(path) as f:
            usage = extract_usage(json.load(f))
        cost = calculate_cost_from_usage(usage, model)
        spent.append(cost)
        log_operation(project_dir, f'score-{label}', model, usage['input_tokens'],
                      usage['output_tokens'], cost, target='book',
                      cache_read=usage.get('cache_read', 0),
                      cache_create=usage.get('cache_create', 0))

    out = tf.output_dir(project_dir)
    try:
        result = tf.run(project_dir, model, log_dir=os.path.join(out, 'logs'),
                        approve=check_threshold, on_usage=on_usage)
    except tf.FidelityError as e:
        log(f'ERROR: {e}')
        sys.exit(1)
    result.cost = sum(spent)
    tf.write(result, out, read_yaml_field('project.title', project_dir) or '')
    table = tf.counts(result.claims)
    bad = sum(r['contradicted'] + r['overreach'] for r in table.values())
    log(f'Text fidelity: {len(result.claims)} claims, {bad} contradicted or overreaching, '
        f'${result.cost:.2f} → {out}/report.md')


def _run_elaboration_scoring(args) -> None:
    """Dispatch elaboration-scoring entry points; short-circuits scene-prose scoring."""
    from datetime import datetime
    from storyforge.scoring_levels import (
        score_level, score_all_levels, LEVEL_NAMES,
    )
    from storyforge.scoring_consistency import (
        score_consistency_at_level, score_consistency_all_levels,
    )
    from storyforge.scoring_comparison import compare_candidates, render_report
    from storyforge.common import get_medium

    project_dir = detect_project_root()
    from storyforge.series import require_canon
    require_canon(project_dir)  # a bad series canon stops here, before a branch or spend
    medium = get_medium(project_dir) or 'novel'

    _validate_flag_combinations(args)

    # --text-fidelity: the upper tiers against the prose.
    if args.text_fidelity:
        _run_text_fidelity(project_dir, args.dry_run)
        return

    # --story-power: 8-axis pitch-tier craft scorecard.
    if args.story_power:
        from storyforge.scoring_story_power import score_story_power
        from storyforge.common import get_coaching_level
        coaching = get_coaching_level(project_dir)
        result = score_story_power(project_dir, coaching, dry_run=args.dry_run)
        if result['output_dir']:
            log(f'Story-power scorecard ({result["mode"]}): '
                f'composite={result["composite"]} → {result["output_dir"]}')
        return

    # --bible-consistency: LLM check vs character/world/voice bibles.
    if args.bible_consistency:
        from storyforge.scoring_bible import score_bible_consistency
        if args.scope:
            scene_path = os.path.join(project_dir, 'scenes', f'{args.scope}.md')
            if not os.path.isfile(scene_path):
                log(f'ERROR: --scope {args.scope!r} does not match any drafted '
                    f'scene (looked for {scene_path}).')
                sys.exit(1)
        _check_llm_preconditions('--bible-consistency', dry_run=args.dry_run)
        findings = score_bible_consistency(
            project_dir, scope=args.scope, dry_run=args.dry_run,
        )
        _print_bible_findings(findings)
        return

    # --boundary / --all-boundaries: LLM faithfulness diff.
    if args.boundary or args.all_boundaries:
        from storyforge.scoring_boundary import (
            score_boundary, score_all_boundaries, BOUNDARY_IDS,
        )
        if args.boundary and args.boundary not in BOUNDARY_IDS:
            log(f'ERROR: --boundary must be one of {", ".join(BOUNDARY_IDS)}; '
                f'got {args.boundary!r}.')
            sys.exit(1)
        op = '--all-boundaries' if args.all_boundaries else f'--boundary {args.boundary}'
        _check_llm_preconditions(op, dry_run=args.dry_run)
        if args.all_boundaries:
            diffs = score_all_boundaries(project_dir, dry_run=args.dry_run)
        else:
            diffs = score_boundary(
                project_dir, args.boundary,
                scope=args.scope, dry_run=args.dry_run,
            )
        _print_boundary_diffs(diffs)
        return

    # --compare: deterministic floor axes + --semantic ceiling axes (LLM).
    if args.compare:
        if args.level is None:
            log('ERROR: --compare requires --level to know what kind of '
                'candidates these are (0=logline, 1=synopsis, 2=act-shape).')
            sys.exit(1)
        if args.level not in (0, 1, 2):
            log('ERROR: --compare is only supported at the prose tier '
                '(levels 0-2).')
            sys.exit(1)
        if args.semantic:
            _check_llm_preconditions('--compare --semantic', dry_run=args.dry_run)
        candidates_text = [_read_candidate(c) for c in args.compare]
        try:
            result = compare_candidates(
                LEVEL_NAMES[args.level], candidates_text,
                semantic=args.semantic, project_dir=project_dir,
                dry_run=args.dry_run,
            )
        except ValueError as e:
            log(f'ERROR: {e}')
            sys.exit(1)
        md = render_report(result)
        # Write to a working/ report and also echo to stdout.
        out_dir = os.path.join(project_dir, 'working')
        os.makedirs(out_dir, exist_ok=True)
        ts = datetime.now().strftime('%Y%m%d-%H%M%S')
        out_path = os.path.join(
            out_dir, f'comparison-{LEVEL_NAMES[args.level]}-{ts}.md',
        )
        with open(out_path, 'w', encoding='utf-8') as f:
            f.write(md)
        log(f'Comparison report: {out_path}')
        print(md)
        return

    # --drift: read-only report. Combines coverage + consistency.
    if args.drift:
        _print_drift_report(project_dir, medium)
        return

    # --level N or --all-levels: floor + consistency + coverage per level.
    if args.all_levels:
        levels = list(range(0, 7))
    else:
        levels = [args.level]

    from storyforge.scoring_coverage import score_coverage_at_level
    for level in levels:
        floor = score_level(project_dir, level, medium=medium)
        _print_level_result(floor)
        if level in (3, 4, 5, 6):
            consistency = score_consistency_at_level(project_dir, level)
            _print_level_result(consistency)
        if level in (2, 3, 4):
            coverage = score_coverage_at_level(project_dir, level)
            _print_level_result(coverage)


def _print_boundary_diffs(diffs: list[dict]) -> None:
    """Render boundary-diff results to stdout."""
    if not diffs:
        print('\nNo boundary diffs produced — every checked scope already '
              'has a recorded verdict, or content is incomplete.\n')
        return
    for d in diffs:
        marker = '⌗' if d.get('persisted') else '⚠'
        print(f'\n[{marker} {d["boundary"]} / {d["scope"]}]')
        if d.get('upstream_summary'):
            print(f'  upstream: {d["upstream_summary"]}')
        if d.get('downstream_summary'):
            print(f'  downstream: {d["downstream_summary"]}')
        if d.get('alignment'):
            print(f'  alignment: {d["alignment"]}')
        if d.get('proposed_verdict'):
            tag = ' (persisted)' if d.get('persisted') else ' (proposed; not persisted)'
            print(f'  verdict: {d["proposed_verdict"]}{tag}')
        if d.get('rationale'):
            print(f'  rationale: {d["rationale"]}')


def _print_bible_findings(findings: list[dict]) -> None:
    """Render bible-consistency findings to stdout."""
    if not findings:
        print('\nNo bible-consistency findings (or no bibles / drafts to check).\n')
        return
    # Group by scope for legible output.
    by_scope: dict[str, list[dict]] = {}
    for f in findings:
        by_scope.setdefault(f['scope'], []).append(f)
    for scope in sorted(by_scope):
        scope_findings = by_scope[scope]
        accepted_count = sum(1 for f in scope_findings if f.get('accepted'))
        active_count = len(scope_findings) - accepted_count
        summary = f'{active_count} finding(s)'
        if accepted_count:
            summary += f' (+ {accepted_count} accepted)'
        print(f'\n[bible / {scope}] {summary}')
        for f in scope_findings:
            tag = ' (accepted)' if f.get('accepted') else ''
            print(f'  [{f["severity"]}] {f["bible"]}{tag}')
            print(f'    bible: {f["claim"]}')
            print(f'    scene: {f["scene_says"]}')
            print(f'    fix:   {f["fix_location"]} (finding_id={f["finding_id"]})')


def _read_candidate(arg: str) -> str:
    """If `arg` is a path that exists, read it; otherwise treat as literal text."""
    if os.path.isfile(arg):
        with open(arg, encoding='utf-8') as f:
            return f.read()
    return arg


def _print_level_result(result: dict) -> None:
    """Render a level-rubric result dict to stdout as a compact table.

    Failed checks the author has marked as accepted in
    working/scoring-overrides.csv surface with an `(accepted)` marker so
    the author can still see them but the headline counts make it clear
    they're not blocking quality.
    """
    name = result.get('name', 'unknown')
    level = result.get('level', '?')
    passed = result.get('passed', 0)
    failed = result.get('failed', 0)
    accepted = result.get('accepted', 0)
    real_failed = failed - accepted
    summary = f'{passed} passed, {real_failed} failed'
    if accepted:
        summary += f' (+ {accepted} accepted)'
    print(f'\n[level {level}] {name}: {summary}')
    for c in result.get('checks', []):
        if c.get('accepted'):
            marker = '~'  # accepted-failure marker — visible but not blocking
            tag = ' (accepted)'
        elif c['passed']:
            marker = '✓'
            tag = ''
        else:
            marker = '✗'
            tag = ''
        detail = f' — {c["detail"]}' if c.get('detail') else ''
        print(f'  {marker} {c["check"]}{tag}{detail}')


def _print_drift_report(project_dir: str, medium: str) -> None:
    """Compose a read-only drift report from floor + consistency + coverage."""
    from storyforge.scoring_levels import score_all_levels
    from storyforge.scoring_consistency import score_consistency_all_levels
    from storyforge.scoring_coverage import score_coverage_all_levels

    print(f'\n# Drift report (deterministic floor + consistency + coverage)')
    print(f'\nProject root: {project_dir}')
    print(f'Medium: {medium}')

    print('\n## Floor checks per level\n')
    for result in score_all_levels(project_dir, medium=medium):
        _print_level_result(result)

    print('\n## Registry consistency per level\n')
    for result in score_consistency_all_levels(project_dir):
        _print_level_result(result)

    print('\n## Cross-tier coverage per level\n')
    for result in score_coverage_all_levels(project_dir):
        _print_level_result(result)


# What this cycle could not score (scenes, fidelity, acts, novel-level):
# named at the end, and the run exits 1.
_incomplete: list[str] = []


def main(argv=None):
    args = parse_args(argv if argv is not None else sys.argv[1:])

    install_signal_handlers()
    exit_if_bad_threshold()   # before anything is spent
    _incomplete.clear()

    # --complete-cycle first, so it refuses every flag it would drop
    if args.complete_cycle is not None:
        _run_complete_cycle(args)
        return

    # Elaboration entry points short-circuit the prose-scoring flow.
    # (--semantic is a modifier on --compare, not a standalone trigger.)
    if (args.level is not None or args.all_levels or args.compare or args.drift
            or args.boundary or args.all_boundaries or args.bible_consistency
            or args.story_power or args.text_fidelity):
        _run_elaboration_scoring(args)
        return
    if args.source_fidelity:
        _run_source_fidelity_only(args)
        return
    if args.readability:
        _run_readability_only(args)
        return
    if args.register:
        _run_register_only(args)
        return

    from datetime import datetime
    session_start = datetime.now().strftime('%Y-%m-%dT%H:%M:%S')

    # Resolve score mode
    if args.direct and args.deep:
        score_mode = 'direct-deep'
    elif args.direct:
        score_mode = 'direct'
    else:
        score_mode = 'batch'

    project_dir = detect_project_root()
    from storyforge.series import require_canon
    require_canon(project_dir)  # a bad series canon stops here, before a branch or spend
    from storyforge.ledger import exit_if_not_migrated
    exit_if_not_migrated(project_dir)  # the registries live in the ledger
    log(f'Project root: {project_dir}')
    reading_target = _reading_target_or_exit(project_dir)  # before anything is spent

    title = (read_yaml_field('project.title', project_dir)
             or read_yaml_field('title', project_dir) or 'Unknown')

    # Branch + PR
    if not args.dry_run:
        create_branch('score', project_dir)
        ensure_branch_pushed(project_dir)

    plugin_dir = get_plugin_dir()
    scripts_dir = os.path.join(plugin_dir, 'scripts')
    prompts_dir = os.path.join(scripts_dir, 'prompts', 'scoring')

    # Parse --principles / --deterministic filter
    targeted_principles = None
    deterministic_only = False
    if args.deterministic and args.principles:
        log('WARNING: --deterministic and --principles both set; '
            'using --deterministic (ignoring --principles)')
    if args.deterministic:
        targeted_principles = sorted(DETERMINISTIC_PRINCIPLES)
        deterministic_only = True
    elif args.principles:
        targeted_principles = _parse_principles(args.principles, plugin_dir)
        deterministic_only = all(p in DETERMINISTIC_PRINCIPLES for p in targeted_principles)
    if targeted_principles:
        log(f'Targeted principles: {", ".join(targeted_principles)}')
        if deterministic_only:
            log('All requested principles are deterministic — skipping LLM pipeline')

    # Model selection
    sonnet_model = select_model('evaluation')
    opus_model = model_for_tier('opus')

    if score_mode == 'batch':
        eval_model = opus_model
    elif score_mode == 'direct':
        eval_model = sonnet_model
    else:
        eval_model = opus_model

    log(f'Mode: {score_mode}, Model: {eval_model}')

    # An adaptation (#477): read the block before anything is spent
    from storyforge import source as source_mod
    try:
        source_cfg = source_mod.read_config(project_dir)
        if source_cfg is not None:
            source_mod.require_imported(project_dir, source_cfg)
    except source_mod.SourceError as e:
        log(f'ERROR: {e}')
        sys.exit(1)

    # Build shared context once for all API calls (prompt caching)
    system = build_shared_context(project_dir, model=eval_model)

    # Initialize craft weights
    from storyforge.scoring import init_craft_weights
    init_craft_weights(project_dir, plugin_dir)
    weights_file = os.path.join(project_dir, 'working', 'craft-weights.csv')

    # Build scene list
    metadata_csv = os.path.join(project_dir, 'reference', 'scenes.csv')
    intent_csv = os.path.join(project_dir, 'reference', 'scene-intent.csv')
    briefs_csv = os.path.join(project_dir, 'reference', 'scene-briefs.csv')
    has_briefs = os.path.isfile(briefs_csv)
    scenes_dir = os.path.join(project_dir, 'scenes')

    all_ids = build_scene_list(metadata_csv)

    # Filter scenes
    filter_mode, filter_value, _ = _resolve_filter(args)
    filtered_ids = apply_scene_filter(metadata_csv, all_ids, filter_mode, filter_value)

    # Keep only drafted scenes
    scene_ids = []
    missing = []
    for sid in filtered_ids:
        if os.path.isfile(os.path.join(scenes_dir, f'{sid}.md')):
            scene_ids.append(sid)
        else:
            missing.append(sid)

    if not scene_ids:
        log('ERROR: No drafted scene files found for the selected scope.')
        if missing:
            log(f'Missing scenes: {" ".join(missing)}')
        sys.exit(1)

    if missing:
        log(f'WARNING: {len(missing)} scenes not yet drafted (skipping): {" ".join(missing)}')

    scene_count = len(scene_ids)
    log(f'Scoring {scene_count} scenes in {score_mode} mode')

    # Determine cycle number
    cycle = _determine_cycle(project_dir)
    cycle_dir = os.path.join(project_dir, 'working', 'scores', f'cycle-{cycle}')
    log_dir = os.path.join(project_dir, 'working', 'logs')
    os.makedirs(cycle_dir, exist_ok=True)
    os.makedirs(log_dir, exist_ok=True)

    log(f'Cycle: {cycle} -> {cycle_dir}')

    # =========================================================================
    # Deterministic-only fast path
    # =========================================================================
    # When --principles requests only deterministic principles (e.g.
    # prose_repetition), skip the entire LLM pipeline: no API key needed, no
    # cost, no batch requests, no PR.  Just run the deterministic scorers,
    # write results, generate diagnosis, commit and exit.

    if deterministic_only:
        if args.dry_run:
            _print_dry_run_deterministic(
                targeted_principles, scene_count, cycle, scene_ids,
                metadata_csv, cycle_dir,
            )
            return
        _write_readability(scene_ids, project_dir, cycle_dir, reading_target)
        _run_deterministic_only(
            targeted_principles, scene_ids, project_dir, cycle, cycle_dir,
            plugin_dir, weights_file, title,
        )
        return

    # =========================================================================
    # Diagnosis-only fast path
    # =========================================================================
    # When --diagnosis-only is set, skip all scoring and run just the
    # improvement cycle (diagnosis + proposals) from existing scores.

    if args.diagnosis_only:
        # Use latest cycle dir if it has scores, otherwise use current
        latest_link = os.path.join(project_dir, 'working', 'scores', 'latest')
        if os.path.islink(latest_link):
            diag_cycle_dir = os.path.realpath(latest_link)
        else:
            diag_cycle_dir = cycle_dir

        scores_file = os.path.join(diag_cycle_dir, 'scene-scores.csv')
        if not os.path.isfile(scores_file):
            log(f'ERROR: No scene-scores.csv found in {diag_cycle_dir}')
            log('Run a full scoring cycle first, then use --diagnosis-only.')
            sys.exit(1)

        log(f'Running diagnosis only from {diag_cycle_dir}')
        try:
            diag_cycle = int(os.path.basename(diag_cycle_dir).replace('cycle-', ''))
        except ValueError:
            log(f'ERROR: Could not determine cycle number from {diag_cycle_dir}')
            sys.exit(1)
        _run_improvement_cycle(
            diag_cycle, diag_cycle_dir, project_dir, weights_file, plugin_dir,
            intent_csv, title, no_apply=args.no_apply,
        )
        _generate_report_and_comment(
            diag_cycle, diag_cycle_dir, project_dir, score_mode, scene_count,
        )
        commit_and_push(project_dir, f'Score: diagnosis-only cycle {diag_cycle}',
                        ['working/'])
        return

    # Cost forecast
    avg_words = _avg_word_count(metadata_csv, scene_ids, scenes_dir)
    scene_cost = estimate_cost('score', scene_count, avg_words, eval_model)
    if score_mode == 'batch':
        scene_cost *= 0.5
        log(f'Cost forecast: ~${scene_cost:.2f} ({scene_count} Opus calls via Batch API, 50% off)')
    else:
        log(f'Cost forecast: ~${scene_cost:.2f} ({scene_count} {eval_model} calls via Direct API)')

    if not args.dry_run:
        if not check_threshold(scene_cost):
            log('Cost threshold check declined. Aborting.')
            sys.exit(1)

    # API key check
    if not args.dry_run and not os.environ.get('ANTHROPIC_API_KEY'):
        log('ERROR: ANTHROPIC_API_KEY not set.')
        sys.exit(1)

    # Draft PR
    if not args.dry_run:
        pr_body = f"""## Principled Scoring

**Project:** {title}
**Mode:** {score_mode}
**Scenes:** {scene_count}
**Estimated cost:** ~${scene_cost:.2f}

### Tasks
- [ ] Scene-level scoring ({scene_count} scenes)
- [ ] Act-level scoring
- [ ] Novel-level scoring
- [ ] Diagnosis and proposals
- [ ] Improvement cycle
- [ ] Review"""
        create_draft_pr(
            f'Score: {title} ({score_mode}, {scene_count} scenes)',
            pr_body, project_dir, 'scoring',
        )

    # Dry-run summary
    if args.dry_run:
        _print_dry_run(score_mode, scene_count, args.parallel, cycle,
                       eval_model, scene_cost, scene_ids, metadata_csv,
                       cycle_dir, targeted_principles)
        return

    # What prose and inputs this cycle scores, so --complete-cycle can tell
    # if they changed
    _write_prose_hashes(scene_ids, project_dir, cycle_dir)

    # Load evaluation template and criteria
    diagnostics_csv = os.path.join(plugin_dir, 'references', 'diagnostics.csv')
    guide_file = os.path.join(plugin_dir, 'references', 'principle-guide.md')
    eval_template_file = os.path.join(prompts_dir, 'scene-evaluation.md')

    for f, label in [(diagnostics_csv, 'Diagnostics CSV'),
                     (eval_template_file, 'Scene evaluation template')]:
        if not os.path.isfile(f):
            log(f'ERROR: {label} not found: {f}')
            sys.exit(1)

    with open(eval_template_file) as f:
        eval_template = f.read()

    from storyforge.scoring import build_evaluation_criteria, build_weighted_text
    # Filter to only the requested LLM-scored principles (excluding
    # deterministic ones which are handled separately).
    llm_principles = None
    if targeted_principles:
        llm_principles = [p for p in targeted_principles
                          if p not in DETERMINISTIC_PRINCIPLES]
    evaluation_criteria = build_evaluation_criteria(
        diagnostics_csv, guide_file, principles=llm_principles)
    weighted_text_str = build_weighted_text(
        weights_file, exclude_section='narrative', principles=llm_principles)

    log(f'Evaluation model: {eval_model} (mode: {score_mode})')

    # =========================================================================
    # Scene-Level Scoring
    # =========================================================================

    log('')
    log('============================================')
    log('Scene-Level Scoring')
    log('============================================')

    score_start = time.time()
    scored = 0
    failed: list[str] = []

    if score_mode == 'batch':
        scored, failed = _score_batch(
            scene_ids, eval_model, eval_template, evaluation_criteria,
            weighted_text_str, metadata_csv, intent_csv, scenes_dir,
            cycle_dir, log_dir, diagnostics_csv, plugin_dir,
            project_dir, system=system,
        )
    else:
        scored, failed = _score_direct(
            scene_ids, eval_model, eval_template, evaluation_criteria,
            weighted_text_str, metadata_csv, intent_csv, scenes_dir,
            cycle_dir, log_dir, diagnostics_csv, plugin_dir,
            args.parallel, score_start, project_dir, system=system,
        )

    log('')
    log(f'Scene scoring complete: {scored} scenes scored, {len(failed)} failures')
    if failed:
        log(f'WARNING: this cycle has no scene scores for {", ".join(failed)} '
            f'(refused, cut off or failed); re-score them before relying on it')
        _incomplete.append(_item_scene_scores(failed))
    update_pr_task(f'Scene-level scoring ({scene_count} scenes)', project_dir)

    # =========================================================================
    # Brief fidelity scoring (skip when targeting specific principles)
    # =========================================================================

    if has_briefs and not targeted_principles:
        _run_fidelity_scoring(
            filtered_ids, project_dir, scenes_dir, log_dir, cycle_dir,
            briefs_csv, score_mode, sonnet_model, plugin_dir, system=system,
        )

    # Source fidelity (#477): an adaptation's prose against its source
    if not targeted_principles and source_cfg is not None:
        _run_source_fidelity(scene_ids, 'prose', project_dir, plugin_dir, cycle_dir,
                             log_dir, sonnet_model, system, args.parallel)

    # =========================================================================
    # Act-level scoring (skip when targeting specific principles)
    # =========================================================================

    if not targeted_principles:
        log('Running act-level scoring...')
        _run_act_scoring(
            scene_ids, metadata_csv, scenes_dir, cycle_dir, log_dir,
            prompts_dir, weights_file, sonnet_model, plugin_dir, args.dry_run,
            project_dir, system=system,
        )
        update_pr_task('Act-level scoring', project_dir)

    # =========================================================================
    # Novel-level scoring (skip when targeting specific principles)
    # =========================================================================

    if not targeted_principles:
        log('Running novel-level scoring...')
        _run_novel_scoring(
            scene_count, metadata_csv, intent_csv, project_dir, cycle_dir,
            log_dir, prompts_dir, weights_file, sonnet_model, plugin_dir,
            args.dry_run, system=system,
        )
        update_pr_task('Novel-level scoring', project_dir)

    # =========================================================================
    # Narrative framework scoring (skip when targeting specific principles)
    # =========================================================================

    if not targeted_principles:
        log('')
        log('============================================')
        log('Narrative Framework Scoring')
        log('============================================')

        _run_narrative_scoring(
            title, metadata_csv, project_dir, cycle_dir, log_dir, prompts_dir,
            weights_file, args.dry_run, system=system,
        )

    # latest stays on the last complete cycle: an incomplete one is still
    # saved and committed, but readers of latest shouldn't see its gaps
    from storyforge.project import mark_cycle_incomplete
    mark_cycle_incomplete(cycle_dir, _incomplete)
    if _incomplete:
        _log_latest_kept(project_dir, cycle)
    else:
        _update_latest_link(project_dir, cycle)

    # Cost summary
    print('')
    print_summary(project_dir, 'score', session_start=session_start)

    # Append to score history for cross-cycle tracking
    from storyforge.history import append_cycle
    history_count = append_cycle(cycle_dir, cycle, project_dir)
    if history_count:
        log(f'Score history: appended {history_count} entries (cycle {cycle})')

    # =========================================================================
    # Deterministic scoring (no API calls)
    # =========================================================================

    # Run each deterministic scorer when: no --principles filter, or the
    # principle is in the requested set.
    for det_principle in sorted(DETERMINISTIC_PRINCIPLES):
        should_run = (not targeted_principles
                      or det_principle in targeted_principles)
        if not should_run:
            continue
        if det_principle == 'prose_repetition':
            _score_repetition(scene_ids, project_dir, cycle_dir)
        elif det_principle == 'avoid_passive':
            _score_passive(scene_ids, project_dir, cycle_dir)
        elif det_principle == 'avoid_adverbs':
            _score_adverbs(scene_ids, project_dir, cycle_dir)
        elif det_principle == 'no_weather_dreams':
            _score_weather(scene_ids, project_dir, cycle_dir)
        elif det_principle == 'sentence_as_thought':
            _score_rhythm(scene_ids, project_dir, cycle_dir)
        elif det_principle == 'economy_clarity':
            _score_economy(scene_ids, project_dir, cycle_dir)
    _write_readability(scene_ids, project_dir, cycle_dir, reading_target)

    # =========================================================================
    # Improvement cycle
    # =========================================================================

    if failed:
        # Tuning craft weights from the scenes that happened to score would
        # move them for the whole book on a partial picture
        log(f'Skipping the improvement cycle: {len(failed)} scene(s) have no scores this cycle')
    else:
        _run_improvement_cycle(
            cycle, cycle_dir, project_dir, weights_file, plugin_dir,
            intent_csv, title, no_apply=args.no_apply,
        )
    _record_weights_hash(project_dir, cycle_dir)
    update_pr_task('Diagnosis and proposals', project_dir)
    update_pr_task('Improvement cycle', project_dir)

    # =========================================================================
    # Report, commit, and finish
    # =========================================================================

    _generate_report_and_comment(
        cycle, cycle_dir, project_dir, score_mode, scene_count,
    )
    update_pr_task('Review', project_dir)

    # Final commit
    log('Committing scoring results...')
    commit_and_push(project_dir,
                    f'Score: cycle {cycle}, {scene_count} scenes ({score_mode} mode)'
                    + (' (incomplete)' if _incomplete else ''),
                    ['working/scores/', 'working/craft-weights.csv', 'working/costs/',
                     'working/logs/', 'working/tuning.csv', 'working/overrides.csv',
                     'working/exemplars.csv'])

    log('============================================')
    log(f'Scoring cycle {cycle} complete')
    log(f'Results: {cycle_dir}')
    log('============================================')
    if _incomplete:
        log(f'ERROR: cycle {cycle} is incomplete; re-score these before relying on it:')
        for item in _incomplete:
            log(f'  {item}')
        sys.exit(1)


# ============================================================================
# Internal helpers
# ============================================================================

def _update_latest_link(project_dir, cycle):
    """Point working/scores/latest at cycle-{cycle}."""
    latest_link = os.path.join(project_dir, 'working', 'scores', 'latest')
    target = f'cycle-{cycle}'
    if os.path.islink(latest_link):
        os.remove(latest_link)
    os.symlink(target, latest_link)
    log(f'Updated latest symlink -> {target}')


def _log_latest_kept(project_dir, cycle):
    """Say which cycle latest stays on when cycle-{cycle} is incomplete."""
    latest_link = os.path.join(project_dir, 'working', 'scores', 'latest')
    if os.path.islink(latest_link):
        kept = os.readlink(latest_link)
        if kept == f'cycle-{cycle}':
            # A re-score within the same pipeline cycle writes into the
            # directory latest already names
            log(f'WARNING: latest is {kept}, which this run re-scored only '
                f'in part; the parts named below were not re-scored')
        else:
            log(f'latest stays on {kept}: cycle-{cycle} has unscored parts')
    else:
        log(f'latest not created: cycle-{cycle} has unscored parts')


def _reading_target_or_exit(project_dir):
    """project.reading_level as a `readability.ReadingTarget`, or None when
    unset; a value that isn't a grade or range is an ERROR, exit 1."""
    from storyforge.readability import read_target
    try:
        return read_target(project_dir)
    except ValueError as e:
        log(f'ERROR: {e} in storyforge.yaml')
        sys.exit(1)


def _write_readability(scene_ids, project_dir, cycle_dir, target):
    """The cycle's reading level: readability.csv (a row per scene and an
    ALL row pooling them) and the summary in the log, with a WARNING naming
    any scene it couldn't measure. A measure, not a principle: it never
    enters scene-scores.csv."""
    from storyforge import readability
    measured = readability.measure_scenes(scene_ids, project_dir)
    path = os.path.join(cycle_dir, 'readability.csv')
    readability.write_csv(path, measured.rows, target)
    for line in readability.summary_lines(measured, target):
        log(line)
    log(f'Reading level: {path}')


#: what `--readability` can't be combined with: each would be dropped
_READABILITY_EXCLUSIVE = ('source_fidelity', 'register', 'deterministic', 'principles',
                          'direct',
                          'deep', 'diagnosis_only', 'no_apply', 'interactive',
                          'complete_cycle')


#: what `--register` can't be combined with: each would be dropped
_REGISTER_EXCLUSIVE = ('source_fidelity', 'readability', 'deterministic', 'principles',
                       'direct', 'deep', 'diagnosis_only', 'no_apply', 'interactive',
                       'complete_cycle')


def _run_register_only(args):
    """`score --register`: print the register check's findings for the
    scenes in scope (--scenes/--act/--from-seq). No API call, no cycle,
    nothing written. Findings exit 0 (they are for the author to judge); a
    scene that can't be read is an ERROR, exit 1, after the report."""
    from storyforge import register
    clash = [f'--{name.replace("_", "-")}' for name in _REGISTER_EXCLUSIVE
             if getattr(args, name, None)]
    if clash:
        log(f'ERROR: --register prints the register check only; '
            f'it can\'t be combined with {", ".join(clash)}')
        sys.exit(1)
    project_dir = detect_project_root()
    metadata_csv = os.path.join(project_dir, 'reference', 'scenes.csv')
    filter_mode, filter_value, _ = _resolve_filter(args)
    ids = apply_scene_filter(metadata_csv, build_scene_list(metadata_csv),
                             filter_mode, filter_value)
    if not ids:
        log('ERROR: No scene in scope.')
        sys.exit(1)
    checked = register.check_scenes(ids, project_dir)
    for line in register.report_lines(checked):
        print(line)
    if any(why.startswith("can't be read") for why in checked.unchecked.values()):
        log('ERROR: scene file(s) above can\'t be read; fix them and run again.')
        sys.exit(1)


def _run_readability_only(args):
    """`score --readability`: print the reading level of the scenes in
    scope (--scenes/--act/--from-seq) and their pooled figure (the book's
    with no filter). No API call, no cycle, nothing written. A scene that
    can't be read is an ERROR, exit 1, after the table."""
    from storyforge import readability
    clash = [f'--{name.replace("_", "-")}' for name in _READABILITY_EXCLUSIVE
             if getattr(args, name, None)]
    if clash:
        log(f'ERROR: --readability prints the reading level only; '
            f'it can\'t be combined with {", ".join(clash)}')
        sys.exit(1)
    project_dir = detect_project_root()
    target = _reading_target_or_exit(project_dir)
    metadata_csv = os.path.join(project_dir, 'reference', 'scenes.csv')
    filter_mode, filter_value, _ = _resolve_filter(args)
    ids = apply_scene_filter(metadata_csv, build_scene_list(metadata_csv),
                             filter_mode, filter_value)
    measured = readability.measure_scenes(ids, project_dir)
    if measured.rows:
        width = max(len(r.scene_id) for r in measured.rows)
        print(f'{"scene":<{width}}  words  w/sent  grade  narration  target')
        for r in measured.rows:
            print(f'{r.scene_id:<{width}}  {r.whole.words:>5}  '
                  f'{r.whole.words_per_sentence:>6.1f}  {r.whole.grade:>5.1f}  '
                  f'{readability._fmt(r.narration.grade):>9}  '
                  f'{readability.verdict(r.whole.grade, target)}')
        print()
    for line in readability.summary_lines(measured, target):
        print(line)
    if any(why.startswith("can't be read") for why in measured.unmeasured.values()):
        log('ERROR: scene file(s) above can\'t be read; fix them and run again.')
        sys.exit(1)
    if not measured.rows:
        log('ERROR: No scene in scope has prose to measure.')
        sys.exit(1)


def _score_repetition(scene_ids, project_dir, cycle_dir):
    """Run deterministic repetition scoring. Returns path to scores CSV."""
    from storyforge.repetition import scan_manuscript, score_scene_repetition

    log('Running repetition scan...')
    rep_findings = scan_manuscript(project_dir, scene_ids=scene_ids)
    rep_high = sum(1 for f in rep_findings if f['severity'] == 'high')
    log(f'Repetition scan: {len(rep_findings)} findings ({rep_high} high-severity)')

    # Persist findings for revision guidance
    findings_path = os.path.join(cycle_dir, 'repetition-findings.csv')
    with open(findings_path, 'w', encoding='utf-8') as f:
        f.write('phrase|category|severity|count|scene_ids\n')
        for finding in rep_findings:
            phrase = finding['phrase'].replace('|', ',').replace('\n', ' ')
            category = finding['category']
            severity = finding['severity']
            count = finding['count']
            sids = ';'.join(finding['scene_ids'])
            f.write(f'{phrase}|{category}|{severity}|{count}|{sids}\n')
    log(f'Repetition findings: {findings_path} ({len(rep_findings)} entries)')

    rep_scores_path = os.path.join(cycle_dir, 'repetition-latest.csv')
    with open(rep_scores_path, 'w', encoding='utf-8') as f:
        f.write('id|prose_repetition\n')
        for sid in scene_ids:
            markers = score_scene_repetition(sid, rep_findings)
            active = sum(markers[k] for k in ('pr-1', 'pr-2', 'pr-3', 'pr-4'))
            prose_rep_score = max(1, 5 - active)
            f.write(f'{sid}|{prose_rep_score}\n')

    log(f'Repetition scores: {rep_scores_path}')
    return rep_scores_path


def _load_scene_texts(scene_ids, project_dir):
    """Load scene prose texts from disk. Returns dict of scene_id -> text."""
    scenes_dir = os.path.join(project_dir, 'scenes')
    texts = {}
    for sid in scene_ids:
        path = os.path.join(scenes_dir, f'{sid}.md')
        if os.path.isfile(path):
            texts[sid] = read_scene_prose(path)
    return texts


def _score_single_principle(scene_ids, project_dir, cycle_dir,
                            principle, scorer_fn):
    """Generic scorer for single-scene deterministic principles.

    scorer_fn(text) -> {'score': int, 'markers': dict, 'details': str}
    Returns path to the scores CSV. Also appends findings to scene-findings.csv.
    """
    scene_texts = _load_scene_texts(scene_ids, project_dir)

    log(f'Running {principle} scorer...')
    scores_path = os.path.join(cycle_dir, f'{principle}-latest.csv')
    findings_path = os.path.join(cycle_dir, 'scene-findings.csv')

    write_header = not os.path.isfile(findings_path)

    findings_rows = []
    with open(scores_path, 'w', encoding='utf-8') as f:
        f.write(f'id|{principle}\n')
        for sid in scene_ids:
            text = scene_texts.get(sid, '')
            result = scorer_fn(text)
            f.write(f'{sid}|{result["score"]}\n')

            # Collect findings for scenes with issues (score < 5)
            if result['score'] < 5 and result.get('details'):
                findings_rows.append({
                    'scene_id': sid,
                    'principle': principle,
                    'finding': next((k for k, v in result.get('markers', {}).items() if v), principle),
                    'detail': result['details'],
                })

    # Append findings to shared file
    if findings_rows:
        with open(findings_path, 'a', encoding='utf-8') as f:
            if write_header:
                f.write('scene_id|principle|finding|detail\n')
            for row in findings_rows:
                detail = row['detail'].replace('|', ',').replace('\n', ' ')
                f.write(f'{row["scene_id"]}|{row["principle"]}|{row["finding"]}|{detail}\n')

    log(f'{principle} scores: {scores_path}')
    return scores_path


def _score_passive(scene_ids, project_dir, cycle_dir):
    """Run deterministic passive voice scoring."""
    from storyforge.scoring_passive import score_avoid_passive
    return _score_single_principle(
        scene_ids, project_dir, cycle_dir, 'avoid_passive', score_avoid_passive)


def _score_adverbs(scene_ids, project_dir, cycle_dir):
    """Run deterministic adverb scoring."""
    from storyforge.scoring_adverbs import score_avoid_adverbs
    return _score_single_principle(
        scene_ids, project_dir, cycle_dir, 'avoid_adverbs', score_avoid_adverbs)


def _score_weather(scene_ids, project_dir, cycle_dir):
    """Run deterministic weather/dream opening scoring."""
    from storyforge.scoring_weather import score_no_weather_dreams
    return _score_single_principle(
        scene_ids, project_dir, cycle_dir, 'no_weather_dreams',
        score_no_weather_dreams)


def _score_rhythm(scene_ids, project_dir, cycle_dir):
    """Run deterministic sentence rhythm scoring."""
    from storyforge.scoring_rhythm import score_sentence_as_thought
    return _score_single_principle(
        scene_ids, project_dir, cycle_dir, 'sentence_as_thought',
        score_sentence_as_thought)


def _score_economy(scene_ids, project_dir, cycle_dir):
    """Run deterministic economy/clarity scoring."""
    from storyforge.scoring_economy import score_economy_clarity
    # Pre-load AI-tell words once for all scenes
    from storyforge.prose_analysis import load_ai_tell_words
    ai_words = load_ai_tell_words(get_plugin_dir())

    def scorer(text):
        return score_economy_clarity(text, ai_tell_words=ai_words)

    return _score_single_principle(
        scene_ids, project_dir, cycle_dir, 'economy_clarity', scorer)


# Dispatch table for deterministic scorers
_DETERMINISTIC_SCORERS = {
    'prose_repetition': '_score_repetition',  # special case — uses manuscript scan
    'avoid_passive': '_score_passive',
    'avoid_adverbs': '_score_adverbs',
    'no_weather_dreams': '_score_weather',
    'sentence_as_thought': '_score_rhythm',
    'economy_clarity': '_score_economy',
}


def _resolve_filter(args):
    if args.scenes:
        return ('scenes', args.scenes, None)
    if args.act:
        return ('act', args.act, None)
    if hasattr(args, 'from_seq') and args.from_seq:
        return ('from_seq', args.from_seq, None)
    return ('all', None, None)


def _run_deterministic_only(principles, scene_ids, project_dir, cycle,
                            cycle_dir, plugin_dir, weights_file, title):
    """Fast path for scoring only deterministic principles (no API calls)."""
    log('')
    log('============================================')
    log('Deterministic Scoring (no API calls)')
    log('============================================')

    from storyforge.scoring import merge_score_files
    scores_path = os.path.join(cycle_dir, 'scene-scores.csv')

    for principle in principles:
        if principle == 'prose_repetition':
            path = _score_repetition(scene_ids, project_dir, cycle_dir)
        elif principle == 'avoid_passive':
            path = _score_passive(scene_ids, project_dir, cycle_dir)
        elif principle == 'avoid_adverbs':
            path = _score_adverbs(scene_ids, project_dir, cycle_dir)
        elif principle == 'no_weather_dreams':
            path = _score_weather(scene_ids, project_dir, cycle_dir)
        elif principle == 'sentence_as_thought':
            path = _score_rhythm(scene_ids, project_dir, cycle_dir)
        elif principle == 'economy_clarity':
            path = _score_economy(scene_ids, project_dir, cycle_dir)
        else:
            log(f'WARNING: No deterministic scorer for {principle}')
            continue
        merge_score_files(scores_path, path)

    _update_latest_link(project_dir, cycle)

    # Append to score history
    from storyforge.history import append_cycle
    history_count = append_cycle(cycle_dir, cycle, project_dir)
    if history_count:
        log(f'Score history: appended {history_count} entries (cycle {cycle})')

    # Diagnosis (only for scored principles)
    from storyforge.scoring import generate_diagnosis
    prev_cycle = cycle - 1
    prev_dir = os.path.join(project_dir, 'working', 'scores',
                            f'cycle-{prev_cycle}')
    if not os.path.isdir(prev_dir):
        prev_dir = '-'
    generate_diagnosis(cycle_dir, prev_dir, weights_file)

    # Commit results
    commit_and_push(project_dir,
                    f'Score: {", ".join(principles)} cycle {cycle}, '
                    f'{len(scene_ids)} scenes (deterministic)',
                    ['working/scores/', 'working/costs/', 'working/logs/'])

    log('')
    log('============================================')
    log(f'Deterministic scoring complete — cycle {cycle}')
    log(f'Results: {cycle_dir}')
    log('============================================')


def _print_dry_run_deterministic(principles, scene_count, cycle, scene_ids,
                                 metadata_csv, cycle_dir):
    """Print dry-run summary for deterministic-only scoring."""
    log('============================================')
    log('DRY RUN — Deterministic Scoring (no API calls)')
    log('============================================')
    log(f'Principles: {", ".join(principles)}')
    log(f'Scenes:     {scene_count}')
    log(f'Cycle:      {cycle}')
    log(f'Cost:       $0.00 (deterministic)')
    log('')
    log('Scenes to score:')
    for sid in scene_ids:
        title = get_field(metadata_csv, sid, 'title') or 'untitled'
        log(f'  - {sid} ({title})')
    log('')
    log(f'Output directory: {cycle_dir}')
    log('============================================')


def _determine_cycle(project_dir: str) -> int:
    """Determine the scoring cycle number."""
    cycle = get_current_cycle(project_dir)
    if cycle == 0:
        cycle = 1

    scores_dir = os.path.join(project_dir, 'working', 'scores')
    if cycle == 1 and os.path.isdir(scores_dir):
        highest = 0
        for name in os.listdir(scores_dir):
            if name.startswith('cycle-'):
                try:
                    n = int(name.removeprefix('cycle-'))
                    highest = max(highest, n)
                except ValueError:
                    pass
        if highest > 0:
            cycle = highest + 1

    return cycle


def _avg_word_count(metadata_csv: str, scene_ids: list, scenes_dir: str) -> int:
    """Calculate average word count from metadata or scene files."""
    values = get_column(metadata_csv, 'word_count')
    nums = [int(v) for v in values if v and v != '0'
            and v.isdigit()]
    if nums:
        return sum(nums) // len(nums)

    # Fallback: measure from scene files
    total = 0
    count = 0
    for sid in scene_ids:
        sf = os.path.join(scenes_dir, f'{sid}.md')
        if os.path.isfile(sf):
            total += len(read_scene_prose(sf).split())
            count += 1
    return (total // count) if count > 0 else 3000


def _build_scene_prompt(scene_id: str, eval_template: str,
                        evaluation_criteria: str, weighted_text_str: str,
                        metadata_csv: str, intent_csv: str,
                        scenes_dir: str) -> str:
    """Build the evaluation prompt for a single scene."""
    scene_file = os.path.join(scenes_dir, f'{scene_id}.md')
    scene_text = ''
    if os.path.isfile(scene_file):
        scene_text = read_scene_prose(scene_file)

    scene_title = get_field(metadata_csv, scene_id, 'title') or 'Unknown'
    scene_pov = get_field(metadata_csv, scene_id, 'pov') or 'Unknown'
    scene_function = ''
    scene_emotional_arc = ''
    if os.path.isfile(intent_csv):
        scene_function = get_field(intent_csv, scene_id, 'function') or 'Not specified'
        scene_emotional_arc = get_field(intent_csv, scene_id, 'emotional_arc') or 'Not specified'

    # Number lines
    numbered = '\n'.join(f'{i+1}: {line}' for i, line in enumerate(scene_text.splitlines()))

    # Count principles from the evaluation criteria (each gets a ### heading)
    principle_count = evaluation_criteria.count('\n### ')
    if not principle_count:
        principle_count = 25  # fallback for the default full set

    prompt = eval_template
    prompt = prompt.replace('{{SCENE_TITLE}}', scene_title)
    prompt = prompt.replace('{{SCENE_POV}}', scene_pov)
    prompt = prompt.replace('{{SCENE_FUNCTION}}', scene_function or 'Not specified')
    prompt = prompt.replace('{{SCENE_EMOTIONAL_ARC}}', scene_emotional_arc or 'Not specified')
    prompt = prompt.replace('{{EVALUATION_CRITERIA}}', evaluation_criteria)
    prompt = prompt.replace('{{WEIGHTED_PRINCIPLES}}', weighted_text_str)
    prompt = prompt.replace('{{PRINCIPLE_COUNT}}', str(principle_count))
    prompt = prompt.replace('{{SCENE_TEXT}}', numbered)
    return prompt


def _parse_scene_evaluation(text_content: str, output_scores: str,
                            output_rationale: str, scene_id: str,
                            diagnostics_csv: str) -> bool:
    """Parse scene evaluation text into score/rationale CSVs."""
    from storyforge.scoring import parse_scene_evaluation
    try:
        scores_csv, rationale_csv = parse_scene_evaluation(
            text_content, scene_id, diagnostics_csv)
        if scores_csv:
            with open(output_scores, 'w') as f:
                f.write(scores_csv)
        if rationale_csv:
            with open(output_rationale, 'w') as f:
                f.write(rationale_csv)
        return bool(scores_csv)
    except Exception as e:
        log(f'WARNING: Parse failed for {scene_id}: {e}')
        return False


def _log_api_usage(log_file: str, operation: str, target: str, model: str,
                   project_dir: str, batch: bool = False) -> None:
    """Log API usage/cost from a JSON response file.

    If batch=True, applies the Anthropic Batch API 50% discount to cost.
    """
    try:
        with open(log_file) as f:
            response = json.load(f)
        usage = extract_usage(response)
        cost = calculate_cost_from_usage(usage, model, batch=batch)
        log_operation(
            project_dir, operation, model,
            usage['input_tokens'], usage['output_tokens'], cost,
            target=target,
            cache_read=usage.get('cache_read', 0),
            cache_create=usage.get('cache_create', 0),
        )
    except Exception as e:
        log(f'WARNING: Failed to log usage for {operation}/{target} '
            f'(model={model}): {e}')


# ============================================================================
# Scoring modes
# ============================================================================

def _score_batch(scene_ids, eval_model, eval_template, evaluation_criteria,
                 weighted_text_str, metadata_csv, intent_csv, scenes_dir,
                 cycle_dir, log_dir, diagnostics_csv, plugin_dir,
                 project_dir, system=None):
    """Batch mode scoring. Returns (scored count, failed scene ids)."""
    log('')
    log(f'Building batch request for {len(scene_ids)} scenes...')

    batch_file = os.path.join(cycle_dir, '.batch-requests.jsonl')
    _safe_remove(batch_file)

    for sid in scene_ids:
        prompt = _build_scene_prompt(sid, eval_template, evaluation_criteria,
                                     weighted_text_str, metadata_csv, intent_csv,
                                     scenes_dir)
        request = build_batch_request(sid, prompt, eval_model, 4096, system=system)
        with open(batch_file, 'a') as f:
            f.write(json.dumps(request) + '\n')

    log(f'Submitting batch ({os.path.getsize(batch_file)} bytes)...')
    batch_id = submit_batch(batch_file)
    log(f'Batch submitted: {batch_id}')
    log('Polling for results...')
    results_url = poll_batch(batch_id, log_fn=log)
    log('Results downloaded. Parsing...')
    download_batch_results(results_url, cycle_dir, log_dir)

    scored = 0
    failed: list[str] = []
    from storyforge.scoring import merge_score_files

    for sid in scene_ids:
        scene_title = get_field(metadata_csv, sid, 'title') or sid
        status_file = os.path.join(cycle_dir, f'.status-{sid}')
        text_file = os.path.join(log_dir, f'{sid}.txt')
        json_file = os.path.join(log_dir, f'{sid}.json')

        status_ok = (os.path.isfile(status_file) and
                     open(status_file).read().strip() == 'ok' and
                     os.path.isfile(text_file))

        # Log usage whenever there is a reply, used or not: it was paid for
        # (batch=True for 50% discount pricing)
        if os.path.isfile(json_file):
            _log_api_usage(json_file, 'score', sid, eval_model,
                           project_dir, batch=True)

        if status_ok:
            text_content = open(text_file).read()
            tmp_scores = os.path.join(cycle_dir, f'.tmp-scores-{sid}.csv')
            tmp_rationale = os.path.join(cycle_dir, f'.tmp-rationale-{sid}.csv')

            if _parse_scene_evaluation(text_content, tmp_scores, tmp_rationale,
                                       sid, diagnostics_csv):
                merge_score_files(os.path.join(cycle_dir, 'scene-scores.csv'), tmp_scores)
                merge_score_files(os.path.join(cycle_dir, 'scene-rationale.csv'), tmp_rationale)
                scored += 1
                log(f'  {scene_title} scored ({scored}/{len(scene_ids)})')
            else:
                failed.append(sid)
                log(f'  WARNING: Failed to parse {sid}')
            _safe_remove(tmp_scores)
            _safe_remove(tmp_rationale)
        else:
            failed.append(sid)
            log(f'  WARNING: Failed {sid}')
        _safe_remove(status_file)

    _safe_remove(batch_file)
    return scored, failed


def _score_direct(scene_ids, eval_model, eval_template, evaluation_criteria,
                  weighted_text_str, metadata_csv, intent_csv, scenes_dir,
                  cycle_dir, log_dir, diagnostics_csv, plugin_dir,
                  parallel, score_start, project_dir, system=None):
    """Direct mode scoring with parallel workers. Returns (scored count,
    failed scene ids)."""
    from storyforge.runner import run_batched
    from storyforge.scoring import merge_score_files

    log(f'Parallel workers: {parallel}')

    scored = 0
    failed: list[str] = []

    def score_one(sid):
        prompt = _build_scene_prompt(sid, eval_template, evaluation_criteria,
                                     weighted_text_str, metadata_csv, intent_csv,
                                     scenes_dir)
        log_file = os.path.join(log_dir, f'score-{sid}.json')

        try:
            response = invoke_to_file(prompt, eval_model, log_file, 4096,
                                      system=system)
            _log_api_usage(log_file, 'score', sid, eval_model, project_dir)
            if is_truncated(response):  # a refusal raises in invoke_to_file
                log(f'    [{sid}] FAILED: {stop_problem(response)}')
                return {'ok': False}

            text = extract_text(response)
            tmp_scores = os.path.join(cycle_dir, f'.tmp-scores-{sid}.csv')
            tmp_rationale = os.path.join(cycle_dir, f'.tmp-rationale-{sid}.csv')

            ok = _parse_scene_evaluation(text, tmp_scores, tmp_rationale,
                                         sid, diagnostics_csv)
            return {'ok': ok, 'scores': tmp_scores, 'rationale': tmp_rationale}
        except Exception as e:
            log(f'    [{sid}] FAILED (API error): {e}')
            return {'ok': False}

    def merge_one(sid, result):
        nonlocal scored
        scene_title = get_field(metadata_csv, sid, 'title') or sid

        if isinstance(result, Exception) or not result.get('ok'):
            failed.append(sid)
            log(f'  WARNING: Failed to score {sid}')
            return

        merge_score_files(os.path.join(cycle_dir, 'scene-scores.csv'),
                          result['scores'])
        merge_score_files(os.path.join(cycle_dir, 'scene-rationale.csv'),
                          result['rationale'])
        scored += 1
        log(f'  {scene_title} scored ({scored}/{len(scene_ids)})')
        _safe_remove(result.get('scores', ''))
        _safe_remove(result.get('rationale', ''))

    run_batched(scene_ids, score_one, merge_fn=merge_one,
                batch_size=parallel, label='scene')

    return scored, failed


# ============================================================================
# Higher-level scoring phases
# ============================================================================

def _run_fidelity_scoring(filtered_ids, project_dir, scenes_dir, log_dir,
                          cycle_dir, briefs_csv, score_mode, sonnet_model,
                          plugin_dir, system=None):
    """Run brief fidelity scoring."""
    # Count scenes with brief data
    brief_count = 0
    with open(briefs_csv) as f:
        header = None
        goal_idx = 1  # fallback
        for i, line in enumerate(f):
            if i == 0:
                header = line.strip().split('|')
                if 'goal' in header:
                    goal_idx = header.index('goal')
                continue
            fields = line.strip().split('|')
            if len(fields) > goal_idx and fields[goal_idx].strip():
                brief_count += 1

    if brief_count == 0:
        log('No scenes with brief data — skipping fidelity scoring')
        return

    log(f'Running brief fidelity scoring ({brief_count} scenes with briefs)...')

    from storyforge.scoring import (
        build_fidelity_prompt, parse_fidelity_response,
        write_fidelity_csv, generate_fidelity_diagnosis,
    )

    # Only this run's replies are read below: an earlier run's file for a
    # scene whose call fails now would otherwise be scored as this cycle's.
    for sid in filtered_ids:
        for ext in ('txt', 'json'):
            stale = os.path.join(log_dir, f'fidelity-{sid}.{ext}')
            if os.path.isfile(stale):
                os.remove(stale)

    requested: list[str] = []
    if score_mode == 'batch':
        fidelity_batch = os.path.join(log_dir, f'fidelity-batch-{os.getpid()}.jsonl')
        _safe_remove(fidelity_batch)

        for sid in filtered_ids:
            if not os.path.isfile(os.path.join(scenes_dir, f'{sid}.md')):
                continue
            prompt = build_fidelity_prompt(sid, project_dir, plugin_dir)
            if not prompt:
                continue
            requested.append(sid)
            request = build_batch_request(
                f'fidelity-{sid}', prompt, sonnet_model, 2048, system=system)
            with open(fidelity_batch, 'a') as f:
                f.write(json.dumps(request) + '\n')

        if os.path.isfile(fidelity_batch):
            line_count = sum(1 for _ in open(fidelity_batch))
            if line_count > 0:
                log(f'  Submitting fidelity batch ({line_count} scenes)...')
                batch_id = submit_batch(fidelity_batch)
                results_url = poll_batch(batch_id, log_fn=log)
                fidelity_output = os.path.join(log_dir, 'fidelity-output')
                os.makedirs(fidelity_output, exist_ok=True)
                download_batch_results(results_url, fidelity_output, log_dir)
            _safe_remove(fidelity_batch)
    else:
        for sid in filtered_ids:
            if not os.path.isfile(os.path.join(scenes_dir, f'{sid}.md')):
                continue
            prompt = build_fidelity_prompt(sid, project_dir, plugin_dir)
            if not prompt:
                continue
            fidelity_log = os.path.join(log_dir, f'fidelity-{sid}.json')
            requested.append(sid)
            try:
                invoke_to_file(prompt, sonnet_model, fidelity_log, 2048,
                               system=system)
                _log_api_usage(fidelity_log, 'score-fidelity', sid,
                               sonnet_model, project_dir)
            except Exception:
                log(f'  WARNING: Fidelity scoring failed for {sid}')

    # Log batch fidelity costs
    if score_mode == 'batch':
        for sid in filtered_ids:
            json_file = os.path.join(log_dir, f'fidelity-{sid}.json')
            if os.path.isfile(json_file):
                _log_api_usage(json_file, 'score-fidelity', sid,
                               sonnet_model, project_dir, batch=True)

    # Process results
    results = []
    scored_ids: set[str] = set()
    for sid in filtered_ids:
        for path in [os.path.join(log_dir, f'fidelity-{sid}.txt'),
                     os.path.join(log_dir, f'fidelity-{sid}.json')]:
            if not os.path.isfile(path):
                continue
            text = open(path).read()
            try:
                data = json.loads(text)
            except json.JSONDecodeError:
                data = None
            if isinstance(data, dict):
                # A refused or cut-off reply holds no complete scores. (The
                # batch download already named it and wrote no .txt.)
                problem = stop_problem(data)
                if problem:
                    log(f'  WARNING: Fidelity scoring of {sid} not used: {problem}')
                    break
                text = ''.join(item.get('text', '')
                               for item in data.get('content', [])
                               if item.get('type') == 'text')
            if text:
                result = parse_fidelity_response(text, sid)
                if result.get('scores'):
                    results.append(result)
                    scored_ids.add(sid)
                break
    unscored = [sid for sid in requested if sid not in scored_ids]
    if unscored:
        log(f'  WARNING: no fidelity scores for {", ".join(unscored)}')
        _incomplete.append(_item_fidelity(unscored))

    if results:
        write_fidelity_csv(results, cycle_dir)
        diagnosis = generate_fidelity_diagnosis(results)
        avg_overall = sum(r['overall'] for r in results) / len(results)
        log(f'  Fidelity: {len(results)} scenes scored, avg {avg_overall:.1f}/5')
        high_priority = [d for d in diagnosis if d.get('priority') == 'high']
        if high_priority:
            log('  High-priority fidelity gaps:')
            for d in high_priority:
                log(f'    {d["element"]}: avg {d["avg_score"]}/5 '
                    f'({d["weak_count"]}/{d["total_scenes"]} weak)')
    else:
        log('  No fidelity results to process')


def _run_source_fidelity(scene_ids, target, project_dir, plugin_dir, cycle_dir, log_dir,
                         model, system, parallel, required=False, keep_items=None) -> bool:
    """Run source fidelity on the scenes; a scene it couldn't score is named
    and counted in `_incomplete`. With `required` (--complete-cycle: these
    scenes were listed as missing), a scene with nothing to check now is
    listed too, with a WARNING. When the run can't start, `keep_items` (the
    incomplete.txt lines being filled) go back as they were, else a `not
    run` item. Returns True when every check that ran gave a result."""
    from storyforge import source as source_mod, source_fidelity
    log(f'Running source fidelity on {"briefs" if target == "brief" else "prose"}...')
    try:
        results, skipped, failed = source_fidelity.run(
            project_dir, scene_ids, target, plugin_dir=plugin_dir, out_dir=cycle_dir,
            log_dir=log_dir, model=model, system=system, parallel=parallel)
    except Exception as e:
        # Anything, not only SourceError: in a full run the craft scores are
        # already paid for, and the cycle still has to be marked and committed
        log(f'  WARNING: source fidelity not run: {type(e).__name__}: {e}')
        _incomplete.extend(keep_items if keep_items else [_item_source_not_run(target, e)])
        return False
    source_fidelity.report(results, skipped, failed, target)
    unfilled = list(failed)
    if required and skipped:
        log(f'  WARNING: listed as missing but nothing to check now, so still listed: '
            + '; '.join(f'{sid} ({why})' for sid, why in skipped.items()))
        unfilled += list(skipped)
    if unfilled:
        # the target named, so --complete-cycle can re-check these
        _incomplete.append(_item_source(target, unfilled))
    return not unfilled


def _run_source_fidelity_only(args) -> None:
    """`score --source-fidelity briefs|prose`: source fidelity alone, into
    this cycle's directory (merged with what is there)."""
    from storyforge import source as source_mod
    from storyforge.ledger import exit_if_not_migrated

    project_dir = detect_project_root()
    from storyforge.series import require_canon
    require_canon(project_dir)  # a bad series canon stops here, before a branch or spend
    exit_if_not_migrated(project_dir)
    try:
        cfg = source_mod.read_config(project_dir)
    except source_mod.SourceError as e:
        log(f'ERROR: {e}')
        sys.exit(1)
    if cfg is None:
        log('ERROR: --source-fidelity needs a `source:` block in storyforge.yaml '
            '(this project adapts nothing)')
        sys.exit(1)
    target = 'brief' if args.source_fidelity == 'briefs' else 'prose'
    metadata_csv = os.path.join(project_dir, 'reference', 'scenes.csv')
    filter_mode, filter_value, _ = _resolve_filter(args)
    scene_ids = apply_scene_filter(metadata_csv, build_scene_list(metadata_csv),
                                   filter_mode, filter_value)
    plugin_dir = get_plugin_dir()
    model = select_model('evaluation')

    from storyforge import source_fidelity
    try:
        rows = source_mod.read_source_map(project_dir)
        if rows is None:
            raise source_mod.SourceError(f'there is no reference/{source_mod.SOURCE_MAP} '
                                         f'yet (elaborate --stage map writes it)')
        rules = source_mod.read_rules(project_dir, cfg)
    except source_mod.SourceError as e:
        log(f'ERROR: {e}')
        sys.exit(1)
    by_scene = source_mod.map_rows_by_scene(rows)
    try:
        source_mod.require_imported(project_dir, cfg)
        spans = source_mod.spans(project_dir, cfg)
    except source_mod.SourceError as e:
        log(f'ERROR: {e}')
        sys.exit(1)
    cat = source_mod.catalogue(project_dir, cfg)
    plans = [source_fidelity.plan_scene(project_dir, sid, target, plugin_dir, cfg,
                                        by_scene, rules, cat=cat, spans=spans)
             for sid in scene_ids]
    todo = [p for p in plans if not p.skip]
    words = (sum(len(p.prompt.split()) for p in todo) // len(todo)) if todo else 0
    cost = estimate_cost('fidelity', len(todo), words, model)
    log(f'Source fidelity ({args.source_fidelity}): {len(todo)} of {len(scene_ids)} '
        f'scenes to check, ~${cost:.2f} ({model})')
    for p in plans:
        if p.skip:
            log(f'  {"ERROR" if p.broken else "not checked"}: {p.scene_id} ({p.skip})')
    if args.dry_run:
        for p in todo:
            for note in p.notes:
                log(f'  WARNING: {note}')
        return
    if not todo:
        log('ERROR: nothing to check' + ('' if scene_ids else ' (no scene matched the filter)'))
        sys.exit(1)
    if not check_threshold(cost):
        log('Cost threshold check declined. Aborting.')
        sys.exit(1)
    _check_llm_preconditions('--source-fidelity', dry_run=False)

    create_branch('score', project_dir)
    ensure_branch_pushed(project_dir)
    # Into the latest scored cycle when there is one; a new cycle holding
    # only these files is marked incomplete so it never reads as the latest
    # craft scores (project.latest_scores)
    latest = os.path.join(project_dir, 'working', 'scores', 'latest')
    new_cycle = not os.path.islink(latest)
    if new_cycle:
        cycle_dir = os.path.join(project_dir, 'working', 'scores',
                                 f'cycle-{_determine_cycle(project_dir)}')
    else:
        cycle_dir = os.path.realpath(latest)
    os.makedirs(cycle_dir, exist_ok=True)
    log_dir = os.path.join(project_dir, 'working', 'logs')
    system = build_shared_context(project_dir, model=model)
    _incomplete.clear()
    ok = _run_source_fidelity(scene_ids, target, project_dir, plugin_dir, cycle_dir,
                              log_dir, model, system, args.parallel)
    if new_cycle:
        from storyforge.project import mark_cycle_incomplete
        mark_cycle_incomplete(cycle_dir, [ITEM_SOURCE_ONLY] + _incomplete)
    rel = os.path.relpath(cycle_dir, project_dir)
    commit_and_push(project_dir, f'Score: source fidelity ({args.source_fidelity}), '
                                 f'{os.path.basename(cycle_dir)}', ['working/'])
    log(f'Results: {rel}/{source_fidelity.SCORES_FILE}')
    if not ok:
        for item in _incomplete:
            log(f'  incomplete: {item}')
        sys.exit(1)


# ============================================================================
# --complete-cycle: fill in an incomplete cycle's gaps (#618)
# ============================================================================

#: Each scored scene's prose hash (`source_fidelity.target_hash` of its prose,
#: as source fidelity records it), written by every LLM scoring cycle (not
#: --deterministic) and merged by id when a later run scores into the cycle
PROSE_HASHES_FILE = 'prose-hashes.csv'
PROSE_HASHES_HEADER = ['id', 'prose_hash']

#: The other inputs act, novel-level and narrative scoring read, hashed at
#: score time (craft weights after the improvement cycle, since the filled
#: parts read the weights the cycle left): {name: candidate paths, first found}
INPUT_HASHES_FILE = 'input-hashes.csv'
INPUT_HASHES_HEADER = ['input', 'hash']
SCORED_INPUTS = {
    'scenes.csv': ('reference/scenes.csv',),
    'scene-intent.csv': ('reference/scene-intent.csv',),
    'character-bible.md': ('reference/character-bible.md', 'references/character-bible.md'),
    'story-architecture.md': ('reference/story-architecture.md',
                              'references/story-architecture.md'),
    'chapter-map.csv': ('reference/chapter-map.csv',),
    'craft-weights.csv': ('working/craft-weights.csv',),
}
#: An input hash that changed between two runs into the same cycle
MIXED = 'changed-within-cycle'

#: What `--complete-cycle` can't be combined with: each would be dropped.
#: (Checked by identity with None and False: `--level 0` is a level.)
_COMPLETE_EXCLUSIVE = ('source_fidelity', 'readability', 'register', 'deterministic',
                       'principles',
                       'diagnosis_only', 'scenes', 'act', 'from_seq', 'direct', 'deep',
                       'interactive', 'no_apply', 'level', 'all_levels', 'compare', 'drift',
                       'boundary', 'all_boundaries', 'scope', 'semantic', 'bible_consistency',
                       'story_power', 'text_fidelity')

_NOVEL_SECTION_NAMES = ('character', 'genre')


# --- incomplete.txt items: one formatter each, read back by _completion_parts

def _item_scene_scores(ids):
    return f'scene scores: {", ".join(ids)}'


ITEM_SOURCE_ONLY = 'scene scores: not run (score --source-fidelity only)'


def _item_fidelity(ids):
    return f'fidelity: {", ".join(ids)}'


def _item_source(target, ids):
    return f'source fidelity ({target}): {", ".join(ids)}'


def _item_source_not_run(target, error):
    first = (str(error).strip().splitlines() or [type(error).__name__])[0]
    return f'source fidelity ({target}) not run: {first}'


def _item_act(label, unreadable=False):
    return f'act {label}' + (': unreadable reply' if unreadable else '')


def _item_novel(section=None):
    return ('novel-level scoring' if section is None
            else f'novel-level {section} scores: unreadable reply')


def _item_narrative(unreadable=False):
    return 'narrative scoring' + (': unreadable reply' if unreadable else '')


def _item_no_template(part):
    return f'{part}: no template'


def _hash_text(text):
    return hashlib.sha256(text.encode('utf-8')).hexdigest()[:16]


def _read_hash_file(path, header):
    """{key: hash} from a cycle's hash file, or None when there is none.
    Raises SourceError for one that can't be read, has another header or a
    row that isn't two cells: a check read from it would be wrong."""
    from storyforge.source import SourceError
    if not os.path.isfile(path):
        return None
    try:
        with open(path, encoding='utf-8') as f:
            lines = [l for l in f.read().splitlines() if l.strip()]
    except (OSError, UnicodeDecodeError) as e:
        raise SourceError(f'{path} could not be read ({e})') from e
    if not lines or lines[0].split('|') != header:
        raise SourceError(f'{path}: the header must be {"|".join(header)}')
    out = {}
    for n, line in enumerate(lines[1:], 2):
        cells = line.split('|')
        if len(cells) != 2 or not cells[0]:
            raise SourceError(f'{path} line {n}: wrong number of cells')
        out[cells[0]] = cells[1]
    return out


def read_prose_hashes(cycle_dir):
    """A cycle's {scene id: prose hash} ('' for no prose), or None when it
    records none. Raises SourceError as `_read_hash_file` does."""
    return _read_hash_file(os.path.join(cycle_dir, PROSE_HASHES_FILE), PROSE_HASHES_HEADER)


def read_input_hashes(cycle_dir):
    """A cycle's {input: hash} (`SCORED_INPUTS`), or None when it records
    none. Raises SourceError as `_read_hash_file` does."""
    return _read_hash_file(os.path.join(cycle_dir, INPUT_HASHES_FILE), INPUT_HASHES_HEADER)


def _write_hash_file(path, header, rows):
    with open(path, 'w', encoding='utf-8', newline='') as f:
        f.write('\n'.join(['|'.join(header)] + [f'{k}|{v}' for k, v in rows.items()]) + '\n')


def _current_prose_hash(project_dir, sid, tables=None):
    from storyforge.source_fidelity import target_text, target_hash
    text = target_text(project_dir, sid, 'prose', tables)
    return target_hash(text) if text else ''


def _current_input_hashes(project_dir):
    out = {}
    for name, candidates in SCORED_INPUTS.items():
        path = next((os.path.join(project_dir, c) for c in candidates
                     if os.path.isfile(os.path.join(project_dir, c))), None)
        if path is None:
            out[name] = ''
            continue
        with open(path, encoding='utf-8', errors='replace') as f:
            out[name] = _hash_text(f.read())
    return out


def _write_prose_hashes(scene_ids, project_dir, cycle_dir):
    """Record what this run scores: each scene's prose hash, merged by id
    into the cycle's prose-hashes.csv (a run over some scenes keeps the
    others' rows), and the other inputs' hashes in input-hashes.csv, an
    input that differs from an earlier run into the cycle marked `MIXED`.
    A hash file that can't be read is replaced, with a WARNING."""
    from storyforge.source import SourceError
    try:
        prose = read_prose_hashes(cycle_dir) or {}
    except SourceError as e:
        log(f'WARNING: {e}; rewriting it from this run\'s scenes only')
        prose = {}
    for sid in scene_ids:
        prose[sid] = _current_prose_hash(project_dir, sid)
    _write_hash_file(os.path.join(cycle_dir, PROSE_HASHES_FILE), PROSE_HASHES_HEADER, prose)
    try:
        before = read_input_hashes(cycle_dir)
    except SourceError as e:
        log(f'WARNING: {e}; rewriting it')
        before = None
    now = _current_input_hashes(project_dir)
    if before is not None:
        now = {k: (v if before.get(k, v) == v else MIXED) for k, v in now.items()}
    _write_hash_file(os.path.join(cycle_dir, INPUT_HASHES_FILE), INPUT_HASHES_HEADER, now)


def _record_weights_hash(project_dir, cycle_dir):
    """After the improvement cycle: the craft weights the cycle left."""
    from storyforge.source import SourceError
    try:
        rows = read_input_hashes(cycle_dir)
    except SourceError:
        return   # _write_prose_hashes said so; the check will refuse
    if rows is not None and rows.get('craft-weights.csv') != MIXED:
        rows['craft-weights.csv'] = _current_input_hashes(project_dir)['craft-weights.csv']
        _write_hash_file(os.path.join(cycle_dir, INPUT_HASHES_FILE), INPUT_HASHES_HEADER,
                         rows)


_PART_KINDS = ('source', 'act', 'novel', 'narrative')


@dataclass(frozen=True)
class _Part:
    """One incomplete.txt item `--complete-cycle` can fill."""
    kind: str           # one of _PART_KINDS
    item: str           # the incomplete.txt line
    target: str = ''    # source: 'prose' or 'brief'
    ids: tuple = ()     # source: scene ids; act: its label; novel: sections

    def __post_init__(self):
        ok = {
            'source': self.target in ('prose', 'brief') and bool(self.ids),
            'act': not self.target and len(self.ids) == 1 and bool(self.ids[0]),
            'novel': (not self.target and bool(self.ids)
                      and set(self.ids) <= set(_NOVEL_SECTION_NAMES)),
            'narrative': not self.target and not self.ids,
        }.get(self.kind, False)
        if not ok or not self.item:
            raise ValueError(f'_Part({self.kind!r}, {self.item!r}, {self.target!r}, '
                             f'{self.ids!r})')


def _completion_parts(items, known_ids, source_only):
    """Split a cycle's incomplete.txt items (written by the `_item_*`
    formatters) into the parts `--complete-cycle` fills and [(item, why it
    can't)]. `known_ids` are the project's scene ids; `source_only` says the
    cycle came from `score --source-fidelity`."""
    parts, cannot = [], []
    for item in items:
        m = re.match(r'^source fidelity(?: \((prose|brief)\))? not run: ', item)
        if m:
            cannot.append((item, 'source fidelity did not run at all; run score '
                                 f'--source-fidelity {"briefs" if m.group(1) == "brief" else "prose"}'))
            continue
        m = re.match(r'^source fidelity(?: \((prose|brief)\))?: (.+)$', item)
        if m:
            ids = tuple(i.strip() for i in m.group(2).split(','))
            if not all(i in known_ids for i in ids):
                # an older cycle's "source fidelity: <error>"
                cannot.append((item, 'source fidelity did not run; run score '
                                     '--source-fidelity'))
            elif m.group(1) is None and source_only:
                # written before the target was recorded: briefs or prose?
                cannot.append((item, "it doesn't say whether briefs or prose; run score "
                                     '--source-fidelity'))
            else:
                # without a target, a full cycle's: those check the prose
                parts.append(_Part('source', item, m.group(1) or 'prose', ids))
            continue
        m = re.match(r'^act (\S+?)(?:: unreadable reply)?$', item)
        if m:
            parts.append(_Part('act', item, ids=(m.group(1),)))
            continue
        m = re.match(r'^novel-level (character|genre) scores: unreadable reply$', item)
        if m:
            parts.append(_Part('novel', item, ids=(m.group(1),)))
            continue
        if item == _item_novel():
            parts.append(_Part('novel', item, ids=_NOVEL_SECTION_NAMES))
            continue
        if item in (_item_narrative(), _item_narrative(unreadable=True)):
            parts.append(_Part('narrative', item))
            continue
        if item == ITEM_SOURCE_ONLY:
            why = 'the cycle holds source fidelity only'
        elif item.startswith('scene scores:'):
            why = ('scene scores feed the diagnosis, proposals and score history; '
                   're-score the cycle')
        elif item.startswith('fidelity:'):
            why = 'brief fidelity is written whole; re-score the cycle'
        elif item.endswith(': no template'):
            why = 'its prompt template is missing'
        else:
            why = 'not a part --complete-cycle fills; re-score the cycle'
        cannot.append((item, why))
    return parts, cannot


def _cycle_number(name):
    m = re.match(r'^(?:cycle-)?(\d+)$', name or '')
    return int(m.group(1)) if m else None


def _find_incomplete_cycle(scores_dir, wanted):
    """(number, dir) of the cycle `--complete-cycle` names: `newest` is the
    highest-numbered cycle with an incomplete.txt (exit 1 when there is
    none); N or cycle-N must exist (exit 1 when it doesn't), and may be
    complete: the caller says there is nothing to fill."""
    from storyforge.project import INCOMPLETE_MARKER
    if wanted == 'newest':
        names = os.listdir(scores_dir) if os.path.isdir(scores_dir) else []
        found = sorted((_cycle_number(name), os.path.join(scores_dir, name))
                       for name in names if name.startswith('cycle-')
                       and _cycle_number(name) is not None
                       and os.path.isfile(os.path.join(scores_dir, name, INCOMPLETE_MARKER)))
        if not found:
            log('ERROR: no score cycle is incomplete (none has an incomplete.txt)')
            sys.exit(1)
        return found[-1]
    n = _cycle_number(wanted)
    path = os.path.join(scores_dir, f'cycle-{n}')
    if n is None or not os.path.isdir(path):
        log(f'ERROR: --complete-cycle {wanted}: no such cycle (give N or cycle-N)')
        sys.exit(1)
    return n, path


def _prose_check(project_dir, cycle_dir, cycle, brief_too):
    """(what changed since the cycle scored it, a line saying what was
    checked). Scenes: the cycle's prose-hashes.csv when it has one, plus the
    hashes its source-fidelity results record (prose, and briefs when
    `brief_too`); without prose-hashes.csv the line says what that leaves
    unchecked. Raises SourceError for a hash or source-fidelity file that
    can't be read."""
    from storyforge import source_fidelity as sf
    tables = sf._project_tables(project_dir)

    def now(sid, target):
        text = sf.target_text(project_dir, sid, target, tables)
        return sf.target_hash(text) if text else ''

    prose = read_prose_hashes(cycle_dir)
    changed = [sid for sid, h in (prose or {}).items() if now(sid, 'prose') != h]
    checked = {(sid, 'prose') for sid in (prose or {})}
    sf_rows = [r for r in sf.read_scores(cycle_dir)
               if (r['target'] == 'prose' or (brief_too and r['target'] == 'brief'))
               and (r['id'], r['target']) not in checked]
    for r in sf_rows:
        if now(r['id'], r['target']) != r['target_hash']:
            changed.append(r['id'] if r['target'] == 'prose' else f'{r["id"]} (brief)')
    what = 'Prose and briefs' if brief_too else 'Prose'
    if prose is not None:
        line = (f'{what} unchanged since cycle-{cycle} was scored ({len(checked)} scenes'
                + (f', {sum(r["target"] == "brief" for r in sf_rows)} briefs' if brief_too
                   else '') + ' checked)')
    elif sf_rows:
        line = (f'NOTE: cycle-{cycle} records no prose hashes (it was scored before they '
                f'were kept): checked the {len(sf_rows)} results its source-fidelity file '
                f'hashes; a change to any other scene since is not detected')
    else:
        line = (f'NOTE: cycle-{cycle} records no prose hashes (it was scored before they '
                f'were kept): whether the prose changed since is not checked')
    return sorted(set(changed)), line


def _input_check(project_dir, cycle_dir):
    """The scored inputs (`SCORED_INPUTS`) that changed since the cycle
    recorded them, or None when it records none. Raises SourceError for a
    file that can't be read."""
    recorded = read_input_hashes(cycle_dir)
    if recorded is None:
        return None
    now = _current_input_hashes(project_dir)
    return sorted(k for k in SCORED_INPUTS
                  if recorded.get(k) == MIXED or recorded.get(k, '') != now[k])


def _rebuild_diagnosis(cycle, cycle_dir, project_dir, weights_file):
    """The cycle's diagnosis from its scores as they are now; proposals are
    not made or applied (the cycle's run did that)."""
    from storyforge.scoring import generate_diagnosis
    prev_dir = os.path.join(project_dir, 'working', 'scores', f'cycle-{cycle - 1}')
    generate_diagnosis(cycle_dir, prev_dir if os.path.isdir(prev_dir) else '-',
                       weights_file)
    log(f'Diagnosis rebuilt from cycle-{cycle}\'s filled-in scores (no proposals applied)')


def _move_latest(project_dir, scores_dir, cycle):
    """Point latest at the completed cycle unless a newer cycle is latest.
    Returns False (with an ERROR) when latest can't be read: it is left as
    it is."""
    latest = os.path.join(scores_dir, 'latest')
    if os.path.lexists(latest) and not os.path.islink(latest):
        log(f'ERROR: {latest} is not a symlink; latest left as it is')
        return False
    if os.path.islink(latest):
        current = _cycle_number(os.path.basename(os.readlink(latest).rstrip('/')))
        if current is None:
            log(f'ERROR: latest points at {os.readlink(latest)}, not a cycle; left as it is')
            return False
        if current > cycle:
            log(f'cycle-{cycle} is complete; latest stays on the newer cycle-{current}')
            return True
    _update_latest_link(project_dir, cycle)
    log(f'cycle-{cycle} is complete')
    return True


def _run_complete_cycle(args):
    """`score --complete-cycle [CYCLE]`: re-score only the parts the
    cycle's incomplete.txt lists, into that cycle. Refuses (exit 1, nothing
    spent) when what those parts read changed since the cycle was scored:
    scenes' prose (and briefs, for brief source-fidelity parts), and for
    act, novel-level and narrative parts the other inputs (`SCORED_INPUTS`;
    a cycle that records none can't have those filled). With every part
    filled the file is cleared, act/novel/narrative scores rebuild the
    diagnosis (no proposals applied), and the cycle becomes latest unless a
    newer cycle already is. A part it can't fill, or that fails again,
    stays listed and the run exits 1."""
    from storyforge.project import INCOMPLETE_MARKER, mark_cycle_incomplete
    from storyforge.ledger import exit_if_not_migrated
    from storyforge import source as source_mod, source_fidelity
    clash = [f'--{name.replace("_", "-")}' for name in _COMPLETE_EXCLUSIVE
             if getattr(args, name, None) is not None
             and getattr(args, name) is not False]
    if clash:
        log(f"ERROR: --complete-cycle fills in what a cycle is missing; it can't be "
            f'combined with {", ".join(clash)}')
        sys.exit(1)
    project_dir = detect_project_root()
    from storyforge.series import require_canon
    require_canon(project_dir)  # a bad series canon stops here, before a branch or spend
    exit_if_not_migrated(project_dir)
    scores_dir = os.path.join(project_dir, 'working', 'scores')
    cycle, cycle_dir = _find_incomplete_cycle(scores_dir, args.complete_cycle)
    marker = os.path.join(cycle_dir, INCOMPLETE_MARKER)
    if not os.path.isfile(marker):
        log(f'cycle-{cycle} has no incomplete.txt: nothing to fill in')
        return
    with open(marker, encoding='utf-8') as f:
        items = [l.strip() for l in f.read().splitlines() if l.strip()]

    metadata_csv = os.path.join(project_dir, 'reference', 'scenes.csv')
    intent_csv = os.path.join(project_dir, 'reference', 'scene-intent.csv')
    scenes_dir = os.path.join(project_dir, 'scenes')
    known = [i for i in get_column(metadata_csv, 'id') if i]
    parts, cannot = _completion_parts(items, set(known), ITEM_SOURCE_ONLY in items)

    try:
        prose_hashes = read_prose_hashes(cycle_dir)
        inputs_changed = _input_check(project_dir, cycle_dir)
    except source_mod.SourceError as e:
        log(f'ERROR: {e}')
        sys.exit(1)
    # The cycle's scenes: what it hashed, in reading order
    order = build_scene_list(metadata_csv, min_words=0)
    cycle_ids = [i for i in order if i in (prose_hashes or {})]
    acts_scored = {get_field(metadata_csv, i, 'act') for i in cycle_ids}
    for part in [p for p in parts if p.kind != 'source']:
        if prose_hashes is None or inputs_changed is None:
            why = ('the cycle records no hashes of the prose and inputs it scored (it '
                   'predates them), so a part filled now could score other text; '
                   're-score the cycle')
        elif not cycle_ids or (part.kind == 'act' and part.ids[0] not in acts_scored):
            why = 'the cycle records no scored scenes for it; re-score the cycle'
        else:
            continue
        parts.remove(part)
        cannot.append((part.item, why))

    brief_too = any(p.kind == 'source' and p.target == 'brief' for p in parts)
    try:
        changed, checked = _prose_check(project_dir, cycle_dir, cycle, brief_too)
    except source_mod.SourceError as e:
        log(f'ERROR: {e}')
        sys.exit(1)
    if any(p.kind != 'source' for p in parts) and inputs_changed:
        changed += inputs_changed
    if changed:
        log(f"ERROR: cycle-{cycle} can't be filled in: {', '.join(changed)} changed since "
            f'it was scored, so the parts filled in would score other text than the rest. '
            f'Re-score instead (storyforge score).')
        sys.exit(1)
    log(checked)

    log(f'Filling in cycle-{cycle}:')
    for p in parts:
        log(f'  {p.item}')
    for item, why in cannot:
        log(f"  can't fill: {item} ({why})")
    if not parts:
        log(f"ERROR: nothing in cycle-{cycle}'s incomplete.txt is a part --complete-cycle "
            f'fills')
        sys.exit(1)

    plugin_dir = get_plugin_dir()
    prompts_dir = os.path.join(plugin_dir, 'scripts', 'prompts', 'scoring')
    weights_file = os.path.join(project_dir, 'working', 'craft-weights.csv')
    log_dir = os.path.join(project_dir, 'working', 'logs')
    model = select_model('evaluation')
    source_parts = [p for p in parts if p.kind == 'source']
    cost = 0.0
    if source_parts:
        try:
            cfg = source_mod.read_config(project_dir)
            if cfg is None:
                raise source_mod.SourceError('storyforge.yaml has no `source:` block')
            source_mod.require_imported(project_dir, cfg)
            rows = source_mod.read_source_map(project_dir)
            if rows is None:
                raise source_mod.SourceError(f'there is no reference/{source_mod.SOURCE_MAP} '
                                             f'yet (elaborate --stage map writes it)')
            rules = source_mod.read_rules(project_dir, cfg)
            spans = source_mod.spans(project_dir, cfg)
        except source_mod.SourceError as e:
            log(f'ERROR: {e}')
            sys.exit(1)
        by_scene = source_mod.map_rows_by_scene(rows)
        cat = source_mod.catalogue(project_dir, cfg)
        reading = source_fidelity.reading_order(project_dir)
        plans = [source_fidelity.plan_scene(project_dir, sid, p.target, plugin_dir, cfg,
                                            by_scene, rules, cat=cat, spans=spans,
                                            order=reading)
                 for p in source_parts for sid in p.ids]
        todo = [pl for pl in plans if not pl.skip]
        for pl in plans:
            if pl.skip:
                log(f'  WARNING: {pl.scene_id} has nothing to check now ({pl.skip}); '
                    f'it stays listed')
        words = (sum(len(pl.prompt.split()) for pl in todo) // len(todo)) if todo else 0
        cost += estimate_cost('fidelity', len(todo), words, model)
    for label in sorted({p.ids[0] for p in parts if p.kind == 'act'}):
        words = sum(len(read_scene_prose(os.path.join(scenes_dir, f'{i}.md')).split())
                    for i in cycle_ids if get_field(metadata_csv, i, 'act') == label
                    and os.path.isfile(os.path.join(scenes_dir, f'{i}.md')))
        cost += estimate_cost('score', 1, words, model)
    whole = sum(1 for kind in ('novel', 'narrative') if any(p.kind == kind for p in parts))
    if whole:
        cost += estimate_cost('score', whole,
                              _avg_word_count(metadata_csv, cycle_ids, scenes_dir), model)
    log(f'Cost forecast: ~${cost:.2f} ({model}; a floor: the shared context sent with '
        f'each call is not counted)')
    if args.dry_run:
        return
    if not check_threshold(cost):
        log('Cost threshold check declined. Aborting.')
        sys.exit(1)
    _check_llm_preconditions('--complete-cycle', dry_run=False)

    create_branch('score', project_dir)
    ensure_branch_pushed(project_dir)
    system = build_shared_context(project_dir, model=model)
    _incomplete.clear()
    for target in ('prose', 'brief'):
        mine = [p for p in source_parts if p.target == target]
        if mine:
            _run_source_fidelity([sid for p in mine for sid in p.ids], target, project_dir,
                                 plugin_dir, cycle_dir, log_dir, model, system, args.parallel,
                                 required=True, keep_items=[p.item for p in mine])
    acts = {p.ids[0] for p in parts if p.kind == 'act'}
    if acts:
        _run_act_scoring(cycle_ids, metadata_csv, scenes_dir, cycle_dir, log_dir, prompts_dir,
                         weights_file, model, plugin_dir, False, project_dir, system=system,
                         only_acts=acts)
    sections = tuple(dict.fromkeys(s for p in parts if p.kind == 'novel' for s in p.ids))
    if sections:
        _run_novel_scoring(len(cycle_ids), metadata_csv, intent_csv, project_dir, cycle_dir,
                           log_dir, prompts_dir, weights_file, model, plugin_dir, False,
                           system=system, sections=sections)
    if any(p.kind == 'narrative' for p in parts):
        title = (read_yaml_field('project.title', project_dir)
                 or read_yaml_field('title', project_dir) or 'Unknown')
        _run_narrative_scoring(title, metadata_csv, project_dir, cycle_dir, log_dir,
                               prompts_dir, weights_file, False, system=system)

    remaining = [item for item, _ in cannot] + list(dict.fromkeys(_incomplete))
    mark_cycle_incomplete(cycle_dir, remaining)
    latest_ok = True
    if not remaining:
        if any(p.kind != 'source' for p in parts):
            _rebuild_diagnosis(cycle, cycle_dir, project_dir, weights_file)
            stale = [n for n in ('proposals.csv', 'report.html')
                     if os.path.isfile(os.path.join(cycle_dir, n))]
            if stale:
                log(f"NOTE: cycle-{cycle}'s {' and '.join(stale)} are from its first run, "
                    f'before these scores; `storyforge score --diagnosis-only` remakes '
                    f'them from the latest cycle')
        latest_ok = _move_latest(project_dir, scores_dir, cycle)
    commit_and_push(project_dir, f'Score: complete cycle {cycle}'
                    + (' (still incomplete)' if remaining else ''),
                    ['working/scores/', 'working/costs/', 'working/logs/'])
    if remaining:
        log(f'ERROR: cycle-{cycle} is still incomplete:')
        for item in remaining:
            log(f'  {item}')
    if remaining or not latest_ok:
        sys.exit(1)


def _run_act_scoring(scene_ids, metadata_csv, scenes_dir, cycle_dir, log_dir,
                     prompts_dir, weights_file, sonnet_model, plugin_dir,
                     dry_run, project_dir, system=None, only_acts=None):
    """Run act-level scoring: every act of `scene_ids`, or only the
    labels in `only_acts` (--complete-cycle), where an act that isn't
    scored, for want of scenes or a label scenes.csv no longer has, stays
    listed in `_incomplete` with a WARNING."""
    act_template_file = os.path.join(prompts_dir, 'act-level.md')
    if not os.path.isfile(act_template_file):
        log('WARNING: Act-level template not found, skipping')
        _incomplete.append(_item_no_template('act-level scoring'))
        return

    with open(act_template_file) as f:
        act_template = f.read()

    # Discover unique acts
    act_values = get_column(metadata_csv, 'act')
    acts = list(dict.fromkeys(v for v in act_values if v))  # unique, ordered
    if only_acts is not None:
        acts = [a for a in acts if a in only_acts]

    from storyforge.scoring import (
        extract_rubric_section, build_weighted_text, parse_score_output, merge_score_files,
    )

    for label in sorted((only_acts or set()) - set(acts)):
        log(f'  WARNING: act {label} is listed as missing but no scene is in it now; '
            f'it stays listed')
        _incomplete.append(_item_act(label))

    for act_label in acts:
        act_scenes_text = ''
        act_scene_count = 0
        act_id = f'act-{act_label}'

        for sid in scene_ids:
            scene_act = get_field(metadata_csv, sid, 'act')
            if scene_act != act_label:
                continue
            scene_file = os.path.join(scenes_dir, f'{sid}.md')
            if not os.path.isfile(scene_file):
                continue
            scene_title = get_field(metadata_csv, sid, 'title') or sid
            act_scenes_text += (f'\n\n--- Scene: {scene_title} ({sid}) '
                                f'---\n\n{read_scene_prose(scene_file)}')
            act_scene_count += 1

        if act_scene_count == 0:
            log(f'  Skipping act {act_label}: no scored scenes')
            if only_acts is not None:
                log(f'  WARNING: act {act_label} is listed as missing but has no scored '
                    f'scenes; it stays listed')
                _incomplete.append(_item_act(act_label))
            continue

        narrative_rubric = extract_rubric_section('Narrative Frameworks', plugin_dir)
        character_rubric = extract_rubric_section('Character Craft', plugin_dir)
        wt = build_weighted_text(weights_file)

        prompt = act_template
        prompt = prompt.replace('{{NARRATIVE_FRAMEWORKS_RUBRIC}}', narrative_rubric)
        prompt = prompt.replace('{{CHARACTER_CRAFT_ACT_RUBRIC}}', character_rubric)
        prompt = prompt.replace('{{ACT_LABEL}}', act_label)
        prompt = prompt.replace('{{SCENE_COUNT}}', str(act_scene_count))
        prompt = prompt.replace('{{ACT_SCENES_TEXT}}', act_scenes_text)
        prompt = prompt.replace('{{WEIGHTED_PRINCIPLES}}', wt)
        prompt = prompt.replace('{{ACT_ID}}', act_id)

        log(f'  Scoring act {act_label} ({act_scene_count} scenes)...')

        if dry_run:
            continue

        log_file = os.path.join(log_dir, f'score-{act_id}.json')

        try:
            response = invoke_to_file(prompt, sonnet_model, log_file, 4096,
                                      system=system)
            text = extract_text(response)
            _log_api_usage(log_file, 'score', act_id, sonnet_model, project_dir)

            tmp_scores = os.path.join(cycle_dir, f'.tmp-act-scores-{act_label}.csv')
            tmp_rationale = os.path.join(cycle_dir, f'.tmp-act-rationale-{act_label}.csv')

            scores_csv, rationale_csv = parse_score_output(text)
            if scores_csv:
                with open(tmp_scores, 'w') as f:
                    f.write(scores_csv)
                merge_score_files(os.path.join(cycle_dir, 'act-scores.csv'), tmp_scores)
                _safe_remove(tmp_scores)
            if rationale_csv:
                with open(tmp_rationale, 'w') as f:
                    f.write(rationale_csv)
                merge_score_files(os.path.join(cycle_dir, 'act-rationale.csv'), tmp_rationale)
                _safe_remove(tmp_rationale)
            if scores_csv:
                log(f'  Act {act_label} scored')
            else:
                log(f'  WARNING: no scores could be read from act {act_label}\'s reply')
                _incomplete.append(_item_act(act_label, unreadable=True))
        except Exception as e:
            log(f'  WARNING: Failed to score act {act_label}: {e}')
            _incomplete.append(_item_act(act_label))


#: The novel-level reply's sections: (file prefix, block marker prefix)
_NOVEL_SECTIONS = (('character', 'CHARACTER'), ('genre', 'GENRE'))

#: Appended to the novel-level prompt to re-ask for the sections that
#: couldn't be read (#618)
_NOVEL_RETRY_NOTE = '''

## Your earlier reply could not be used in full

Your earlier reply had no {blocks} block that could be read. Reply with only {these}, in the Output Format above: each block name on a line of its own ending in a colon (no markdown, no code fences), then its header row, then its rows, pipe-delimited.
'''


def _run_novel_scoring(scene_count, metadata_csv, intent_csv, project_dir,
                       cycle_dir, log_dir, prompts_dir, weights_file,
                       sonnet_model, plugin_dir, dry_run, system=None,
                       sections=('character', 'genre')):
    """Run novel-level character + genre scoring, writing only `sections`
    (a re-score filling in an incomplete cycle writes only what is
    missing). A section whose scores can't be read from the reply is asked
    for again once, saying which; a second failure leaves it incomplete."""
    novel_template_file = os.path.join(prompts_dir, 'novel-level.md')
    if not os.path.isfile(novel_template_file):
        log('WARNING: Novel-level template not found, skipping')
        _incomplete.append(_item_no_template('novel-level scoring'))
        return

    with open(novel_template_file) as f:
        novel_template = f.read()

    manuscript_summary = f'Scene count: {scene_count}'

    # Character list from intent.csv
    if os.path.isfile(intent_csv):
        chars = get_column(intent_csv, 'characters')
        all_chars = set()
        for c in chars:
            for name in c.split(';'):
                name = name.strip()
                if name:
                    all_chars.add(name)
        if all_chars:
            char_list = sorted(all_chars)[:20]
            manuscript_summary += '\n\nCharacters mentioned across scenes:\n'
            manuscript_summary += '\n'.join(f'- {c}' for c in char_list)

    # Character bible and story architecture
    character_bible = _read_reference(project_dir, ['reference/character-bible.md',
                                                     'references/character-bible.md'])
    story_architecture = _read_reference(project_dir, ['reference/story-architecture.md',
                                                        'references/story-architecture.md'])

    from storyforge.scoring import extract_rubric_section, build_weighted_text, parse_score_output

    char_rubric = extract_rubric_section('Character Craft', plugin_dir)
    genre_rubric = extract_rubric_section('Tropes and Genre', plugin_dir)
    wt = build_weighted_text(weights_file)

    prompt = novel_template
    prompt = prompt.replace('{{CHARACTER_CRAFT_NOVEL_RUBRIC}}', char_rubric)
    prompt = prompt.replace('{{GENRE_RUBRIC}}', genre_rubric)
    prompt = prompt.replace('{{MANUSCRIPT_SUMMARY}}', manuscript_summary)
    prompt = prompt.replace('{{CHARACTER_BIBLE}}', character_bible or 'No character bible found.')
    prompt = prompt.replace('{{STORY_ARCHITECTURE}}', story_architecture or 'No story architecture found.')
    prompt = prompt.replace('{{WEIGHTED_PRINCIPLES}}', wt)

    if dry_run:
        return

    log('  Scoring novel-level character + genre...')
    log_file = os.path.join(log_dir, 'score-novel-level.json')
    for stale in ('score-novel-level-retry.json', 'score-novel-level-retry.log'):
        _safe_remove(os.path.join(log_dir, stale))   # an earlier run's re-ask

    try:
        response = invoke_to_file(prompt, sonnet_model, log_file, 4096,
                                  system=system)
        text = extract_text(response)
        _log_api_usage(log_file, 'score', 'novel-level', sonnet_model, project_dir)

        # Write text for parse_output
        text_log = os.path.join(log_dir, 'score-novel-level.log')
        with open(text_log, 'w') as f:
            f.write(text)

        def parse(reply):
            return {section: parse_score_output(reply, score_marker=f'{marker}_SCORES',
                                                rationale_marker=f'{marker}_RATIONALE')
                    for section, marker in _NOVEL_SECTIONS if section in sections}

        parsed = parse(text)
        unread = [sec for sec, (scores_csv, _) in parsed.items() if not scores_csv]
        retried = False
        if unread:
            # One re-ask for the sections that couldn't be read
            markers = [m for sec, m in _NOVEL_SECTIONS if sec in unread]
            blocks = ' or '.join(f'{m}_SCORES:' for m in markers)
            these = ', '.join(f'{m}_SCORES: and {m}_RATIONALE:' for m in markers)
            log(f'  The novel-level reply had no readable {blocks} block; asking again once')
            retry_log = os.path.join(log_dir, 'score-novel-level-retry.json')
            try:
                retry = invoke_to_file(
                    prompt + _NOVEL_RETRY_NOTE.format(blocks=blocks, these=these),
                    sonnet_model, retry_log, 4096, system=system)
                _log_api_usage(retry_log, 'score', 'novel-level', sonnet_model, project_dir)
                retry_text = extract_text(retry)
                retried = True
                with open(os.path.join(log_dir, 'score-novel-level-retry.log'), 'w') as f:
                    f.write(retry_text)
                again = parse(retry_text)
                for sec in unread:
                    if again[sec][0]:
                        parsed[sec] = again[sec]
            except Exception as e:
                log(f'  WARNING: the novel-level re-ask failed: {e}')

        for section, (scores_csv, rationale_csv) in parsed.items():
            rationale_file = os.path.join(cycle_dir, f'{section}-rationale.csv')
            if scores_csv:
                with open(os.path.join(cycle_dir, f'{section}-scores.csv'), 'w') as f:
                    f.write(scores_csv)
                if not rationale_csv and os.path.isfile(rationale_file):
                    log(f'  WARNING: the {section} scores came with no rationale; the '
                        f'earlier {section}-rationale.csv no longer matches them and is removed')
                    os.remove(rationale_file)
            else:
                log(f'  WARNING: no {section} scores could be read from the novel-level reply'
                    + (' (asked twice)' if section in unread and retried else ''))
                _incomplete.append(_item_novel(section))
            if scores_csv and rationale_csv:
                with open(rationale_file, 'w') as f:
                    f.write(rationale_csv)

        log('  Novel-level scoring complete')
    except Exception as e:
        log(f'  WARNING: Novel-level scoring failed: {e}')
        _incomplete.append(_item_novel())


def _run_narrative_scoring(title, metadata_csv, project_dir, cycle_dir,
                           log_dir, prompts_dir, weights_file, dry_run,
                           system=None):
    """Run novel-level narrative framework scoring."""
    narrative_template_file = os.path.join(prompts_dir, 'novel-narrative.md')
    if not os.path.isfile(narrative_template_file):
        log(f'WARNING: Narrative template not found at {narrative_template_file}, skipping')
        _incomplete.append(_item_no_template('narrative scoring'))
        return

    with open(narrative_template_file) as f:
        narrative_template = f.read()

    story_arch = _read_reference(project_dir, ['reference/story-architecture.md',
                                                'references/story-architecture.md'])
    scene_index = ''
    if os.path.isfile(metadata_csv):
        with open(metadata_csv) as f:
            lines = f.readlines()
        scene_index = ''.join(l for i, l in enumerate(lines)
                              if i == 0 or not l.strip().endswith('cut'))

    chapter_map = ''
    chapter_map_file = os.path.join(project_dir, 'reference', 'chapter-map.csv')
    if os.path.isfile(chapter_map_file):
        with open(chapter_map_file) as f:
            chapter_map = f.read()

    from storyforge.scoring import build_weighted_text, parse_score_output

    wt = build_weighted_text(weights_file)

    prompt = narrative_template
    prompt = prompt.replace('{{PROJECT_TITLE}}', title)
    prompt = prompt.replace('{{STORY_ARCHITECTURE}}', story_arch or 'No story architecture found.')
    prompt = prompt.replace('{{SCENE_INDEX}}', scene_index or 'No scene metadata available.')
    prompt = prompt.replace('{{CHAPTER_MAP}}', chapter_map or 'No chapter map available.')
    prompt = prompt.replace('{{WEIGHTED_PRINCIPLES}}', wt)

    narrative_model = select_model('evaluation')
    log(f'  Scoring narrative frameworks (model: {narrative_model})...')

    if dry_run:
        return

    log_file = os.path.join(log_dir, 'score-narrative.json')
    narr_scores = os.path.join(cycle_dir, 'narrative-scores.csv')
    narr_rationale = os.path.join(cycle_dir, 'narrative-rationale.csv')

    try:
        response = invoke_to_file(prompt, narrative_model, log_file, 4096,
                                  system=system)
        text = extract_text(response)
        _log_api_usage(log_file, 'score', 'narrative', narrative_model, project_dir)

        text_log = os.path.join(log_dir, 'score-narrative.log')
        with open(text_log, 'w') as f:
            f.write(text)

        scores_csv, rationale_csv = parse_score_output(text)
        if scores_csv:
            with open(narr_scores, 'w') as f:
                f.write(scores_csv)
            if rationale_csv:
                with open(narr_rationale, 'w') as f:
                    f.write(rationale_csv)
        # judged by this reply, not by a file an earlier run left
        if scores_csv:
            log(f'  Narrative scores saved to {os.path.basename(narr_scores)}')
        else:
            log('  WARNING: Failed to parse narrative scores')
            _incomplete.append(_item_narrative(unreadable=True))
    except Exception as e:
        log(f'  WARNING: Narrative scoring API call failed: {e}')
        _incomplete.append(_item_narrative())


def _count_high_priority(diagnosis_file: str) -> int:
    """Count high-priority principles in a diagnosis CSV."""
    from storyforge.csv_cli import get_column
    return sum(1 for v in get_column(diagnosis_file, 'priority') if v == 'high')


def _run_improvement_cycle(cycle, cycle_dir, project_dir, weights_file,
                           plugin_dir, intent_csv, title, no_apply=False):
    """Run diagnosis, proposals, and apply approved changes.

    *no_apply* leaves every proposal pending and reports it, whatever the
    coaching level: in full coaching a calibration run over a classic
    otherwise rewrote its craft weights (evals F-037)."""
    from storyforge.scoring import generate_diagnosis, generate_proposals
    from storyforge.csv_cli import update_field as csv_update

    log('Improvement cycle: generating diagnosis...')
    t0 = time.monotonic()

    # Previous cycle
    prev_dir = ''
    if cycle > 1:
        prev_dir = os.path.join(project_dir, 'working', 'scores', f'cycle-{cycle - 1}')
        if not os.path.isdir(prev_dir):
            prev_dir = ''

    generate_diagnosis(cycle_dir, prev_dir or '-', weights_file)
    log(f'Improvement cycle: diagnosis complete ({time.monotonic() - t0:.1f}s)')

    log('Improvement cycle: generating proposals...')
    t0 = time.monotonic()
    generate_proposals(cycle_dir, weights_file)

    proposals_file = os.path.join(cycle_dir, 'proposals.csv')
    diagnosis_file = os.path.join(cycle_dir, 'diagnosis.csv')

    if not os.path.isfile(proposals_file):
        log(f'Improvement cycle: no proposals generated ({time.monotonic() - t0:.1f}s)')
        return

    # Count proposals
    with open(proposals_file) as f:
        lines = [l.strip() for l in f if l.strip()]
    proposal_count = len(lines) - 1  # subtract header

    # Count high-priority principles from diagnosis
    high_count = _count_high_priority(diagnosis_file)
    priority_note = f' ({high_count} high-priority principles)' if high_count else ''
    log(f'Improvement cycle: {proposal_count} proposals generated{priority_note} ({time.monotonic() - t0:.1f}s)')

    if proposal_count <= 0:
        return

    coaching = get_coaching_level(project_dir)

    if no_apply:
        log('--no-apply: proposals left pending, nothing applied')
        _print_strict_report(diagnosis_file, proposals_file)
        coaching = 'report-only'
    elif coaching == 'full':
        log('Coaching level: full — auto-approving all proposals')
        _approve_all_proposals(proposals_file)
    elif coaching == 'coach':
        log('Coaching level: coach — proposals require interactive approval')
        # No approved proposals in non-interactive script; skip apply
    elif coaching == 'strict':
        log('Coaching level: strict — diagnosis and proposals generated as report only')
        _print_strict_report(diagnosis_file, proposals_file)
        return

    # Apply approved proposals (only 'full' will have approved proposals here)
    if coaching == 'full':
        log('Improvement cycle: applying proposals...')
        t0 = time.monotonic()
        applied = _apply_proposals(proposals_file, weights_file, intent_csv,
                                   project_dir)
        log(f'Improvement cycle: {applied} proposals applied ({time.monotonic() - t0:.1f}s)')
        if applied:
            log('Run storyforge write to rewrite with updated guidance.')

    # Collect exemplars
    log('Improvement cycle: collecting exemplars...')
    t0 = time.monotonic()
    from storyforge.scoring import collect_exemplars
    collect_exemplars(cycle_dir, project_dir, str(cycle))
    log(f'Improvement cycle: exemplars collected ({time.monotonic() - t0:.1f}s)')

    # Check for validated patterns
    from storyforge.scoring import check_validated_patterns
    validated = check_validated_patterns(project_dir)
    if validated:
        log('Validated tuning patterns found:')
        for line in validated.strip().split('\n'):
            if not line.strip():
                continue
            parts = line.split('|')
            if len(parts) >= 3:
                log(f'  {parts[0]} ({parts[1]}): avg improvement {parts[2]}')

    log('Improvement cycle: complete')


def _approve_all_proposals(proposals_file: str) -> None:
    """Set all pending proposals to approved."""
    with open(proposals_file) as f:
        lines = f.readlines()
    header = lines[0].strip().split('|') if lines else []
    status_idx = header.index('status') if 'status' in header else 6
    with open(proposals_file, 'w') as f:
        for i, line in enumerate(lines):
            if i == 0:
                f.write(line)
                continue
            fields = line.rstrip('\n').split('|')
            if len(fields) > status_idx:
                fields[status_idx] = 'approved'
            f.write('|'.join(fields) + '\n')


def _print_strict_report(diagnosis_file: str, proposals_file: str) -> None:
    """Print diagnosis and proposals for strict mode."""
    print('\n=== Diagnosis Summary ===')
    if os.path.isfile(diagnosis_file):
        with open(diagnosis_file) as f:
            lines = f.readlines()
        if lines:
            d_header = lines[0].strip().split('|')
            d_col = {name: i for i, name in enumerate(d_header)}
            for line in lines[1:]:
                fields = line.strip().split('|')
                priority = fields[d_col['priority']] if 'priority' in d_col and d_col['priority'] < len(fields) else ''
                if priority in ('high', 'medium'):
                    principle = fields[d_col.get('principle', 0)] if d_col.get('principle', 0) < len(fields) else ''
                    scale = fields[d_col.get('scale', 1)] if d_col.get('scale', 1) < len(fields) else ''
                    avg_score = fields[d_col.get('avg_score', 2)] if d_col.get('avg_score', 2) < len(fields) else ''
                    print(f'  {principle} ({scale}): avg {avg_score}, priority {priority}')
    print('\n=== Proposals (not applied) ===')
    if os.path.isfile(proposals_file):
        with open(proposals_file) as f:
            lines = f.readlines()
        if lines:
            p_header = lines[0].strip().split('|')
            p_col = {name: i for i, name in enumerate(p_header)}
            for line in lines[1:]:
                fields = line.strip().split('|')
                pid = fields[p_col.get('id', 0)] if p_col.get('id', 0) < len(fields) else ''
                principle = fields[p_col.get('principle', 1)] if p_col.get('principle', 1) < len(fields) else ''
                change = fields[p_col.get('change', 4)] if p_col.get('change', 4) < len(fields) else ''
                rationale = fields[p_col.get('rationale', 5)] if p_col.get('rationale', 5) < len(fields) else ''
                print(f'  {pid}: {principle} — {change} ({rationale})')
    print()


def _apply_proposals(proposals_file, weights_file, intent_csv, project_dir):
    """Apply approved proposals. Returns count applied."""
    applied = 0

    with open(proposals_file) as f:
        lines = f.readlines()

    if not lines:
        return applied
    header = lines[0].strip().split('|')
    col = {name: i for i, name in enumerate(header)}

    for line in lines[1:]:
        fields = line.strip().split('|')
        if len(fields) < len(header):
            continue
        pid = fields[col.get('id', 0)]
        principle = fields[col.get('principle', 1)]
        lever = fields[col.get('lever', 2)]
        target = fields[col.get('target', 3)]
        change = fields[col.get('change', 4)]
        rationale = fields[col.get('rationale', 5)]
        status = fields[col.get('status', 6)]
        if status != 'approved':
            continue

        if lever == 'craft_weight':
            import re
            m = re.search(r'→\s*(\d+)', change)
            if m:
                update_field(weights_file, principle, 'weight', m.group(1),
                             key_col='principle')
                applied += 1
                update_field(proposals_file, pid, 'status', 'applied')
        elif lever in ('scene_intent', 'voice_guide', 'override'):
            overrides_file = os.path.join(project_dir, 'working', 'overrides.csv')
            if not os.path.isfile(overrides_file):
                with open(overrides_file, 'w') as f:
                    f.write('id|principle|directive|source\n')
            target_id = target if lever == 'scene_intent' else 'global'
            if lever == 'override':
                target_id = target
            with open(overrides_file, 'a') as f:
                f.write(f'{target_id}|{principle}|{change}|{pid}\n')
            applied += 1
            update_field(proposals_file, pid, 'status', 'applied')

    return applied


def _generate_report_and_comment(cycle, cycle_dir, project_dir, score_mode,
                                 scene_count):
    """Generate scoring report and post PR comment."""
    # Calculate total cost
    ledger = os.path.join(project_dir, 'working', 'costs', 'ledger.csv')
    total_cost = 0.0
    if os.path.isfile(ledger):
        with open(ledger) as f:
            lines = f.readlines()
        if lines:
            l_header = lines[0].strip().split('|')
            l_col = {name: i for i, name in enumerate(l_header)}
            op_idx = l_col.get('operation', 1)
            cost_idx = l_col.get('cost_usd', 8)
            for line in lines[1:]:
                parts = line.strip().split('|')
                if len(parts) > max(op_idx, cost_idx) and parts[op_idx] == 'score':
                    try:
                        total_cost += float(parts[cost_idx])
                    except (ValueError, IndexError):
                        pass

    from storyforge.scoring import generate_score_report, build_score_pr_comment
    generate_score_report(cycle_dir, project_dir, str(cycle), score_mode,
                          scene_count, f'{total_cost:.2f}')

    if has_gh():
        comment = build_score_pr_comment(cycle_dir, project_dir, str(cycle),
                                          score_mode, scene_count,
                                          f'{total_cost:.2f}')
        if comment:
            r = subprocess.run(
                ['gh', 'pr', 'view', '--json', 'number', '-q', '.number'],
                capture_output=True, text=True, cwd=project_dir,
            )
            pr_num = r.stdout.strip() if r.returncode == 0 else ''
            if pr_num:
                subprocess.run(
                    ['gh', 'pr', 'comment', pr_num, '--body-file', '-'],
                    input=comment.encode(), capture_output=True, cwd=project_dir,
                )
                log(f'Posted scoring summary to PR #{pr_num}')


def _read_reference(project_dir: str, candidates: list) -> str:
    """Read the first existing reference file that isn't still its template.

    A template copy or an unreadable file is passed over with a log line, so
    a pass scored without the doc says why.
    """
    for ref in candidates:
        path = os.path.join(project_dir, ref)
        if not os.path.isfile(path):
            continue
        if is_unfilled_template(path):
            log(f'  {ref} is still its template; scoring without it')
            continue
        try:
            with open(path, encoding='utf-8-sig') as f:
                return f.read()
        except (OSError, UnicodeDecodeError) as e:
            log(f'WARNING: {ref} could not be read ({e}); scoring without it')
    return ''


def _print_dry_run(score_mode, scene_count, parallel, cycle, eval_model,
                   scene_cost, scene_ids, metadata_csv, cycle_dir,
                   targeted_principles=None):
    """Print dry-run summary."""
    log('============================================')
    log('DRY RUN — Scoring Plan')
    log('============================================')
    log(f'Mode:     {score_mode}')
    if targeted_principles:
        log(f'Principles: {", ".join(targeted_principles)}')
    log(f'Scenes:   {scene_count}')
    log(f'Parallel: {parallel}')
    log(f'Cycle:    {cycle}')
    log(f'Model:    {eval_model}')
    log(f'Estimate: ~${scene_cost:.2f}')
    log('')
    log('Scenes to score:')
    for sid in scene_ids:
        title = get_field(metadata_csv, sid, 'title') or 'untitled'
        log(f'  - {sid} ({title})')
    log('')
    if score_mode == 'batch':
        log(f'Batch mode: {scene_count} Opus calls via Batch API (50% off)')
        log('  Results typically arrive in 2-10 minutes')
    elif score_mode == 'direct':
        log(f'Direct mode: {scene_count} Sonnet calls, real-time, {parallel} parallel')
    else:
        log(f'Direct+deep mode: {scene_count} Opus calls, real-time, {parallel} parallel')
    log('')
    if targeted_principles:
        log('Targeted scoring — skipping act/novel/narrative phases')
    else:
        log('After scene scoring:')
        log('  - Act-level scoring')
        log('  - Novel-level character + genre scoring (1 invocation)')
        log('  - Novel-level narrative framework scoring (1 invocation)')
    log('')
    log(f'Output directory: {cycle_dir}')
    log('============================================')


def _safe_remove(path: str) -> None:
    try:
        if path:
            os.remove(path)
    except OSError:
        pass


if __name__ == '__main__':
    main()
