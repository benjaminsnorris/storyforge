"""storyforge hone — CSV data quality tool.

Domains:
    registries   Build canonical registries, normalize field values
    briefs       Concretize abstract brief language as concrete physical beats
    structural   Fix CSV fields from evaluation findings
    gaps         Fill empty required fields from context

Usage:
    storyforge hone                              # Run all domains
    storyforge hone --domain briefs              # Run one domain
    storyforge hone --domain registries --phase 1
    storyforge hone --scenes ID,ID               # Scope to specific scenes
    storyforge hone --diagnose                   # Read-only assessment
    storyforge hone --dry-run                    # Show what would change
"""

import argparse
import json
import os
import sys

from storyforge.common import (
    detect_project_root, log, read_yaml_field, select_model,
    get_coaching_level, install_signal_handlers,
)
from storyforge.git import commit_and_push


ALL_DOMAINS = ['registries', 'gaps', 'structural', 'briefs']
PHASE1_REGISTRY = ['characters', 'locations']
PHASE2_REGISTRY = ['values', 'mice-threads']
PHASE3_REGISTRY = ['knowledge', 'outcomes', 'physical-states']
ALL_REGISTRY_SUBS = ['characters', 'locations', 'values', 'mice-threads',
                     'knowledge', 'outcomes', 'physical-states']


def parse_args(argv):
    parser = argparse.ArgumentParser(prog='storyforge hone',
                                     description='CSV data quality tool')
    parser.add_argument('--domain', type=str, default=None,
                        help='Run specific domains (comma-separated)')
    parser.add_argument('--phase', type=int, default=None,
                        help='Registry sub-domains for extraction phase (1/2/3)')
    parser.add_argument('--scenes', type=str, default=None,
                        help='Comma-separated scene IDs')
    parser.add_argument('--act', '--part', type=str, default=None,
                        help='Scope to scenes in part/act N')
    parser.add_argument('--threshold', type=float, default=3.5,
                        help='Prose naturalness threshold for briefs (default: 3.5)')
    parser.add_argument('--coaching', choices=['full', 'coach', 'strict'], default=None,
                        help='Override coaching level')
    parser.add_argument('--diagnose', action='store_true',
                        help='Read-only assessment (structural scoring + brief quality + gaps)')
    parser.add_argument('--dry-run', action='store_true',
                        help='Show what would change without modifying files')
    return parser.parse_args(argv)


def main(argv=None):
    args = parse_args(argv or [])

    install_signal_handlers()
    project_dir = detect_project_root()
    ref_dir = os.path.join(project_dir, 'reference')
    log_dir = os.path.join(project_dir, 'working', 'logs')
    os.makedirs(log_dir, exist_ok=True)

    # Coaching level
    if args.coaching:
        os.environ['STORYFORGE_COACHING'] = args.coaching
    coaching = args.coaching or get_coaching_level(project_dir)

    # Build domain list
    domains = _resolve_domains(args)

    # API key check
    if not args.dry_run and not args.diagnose and not os.environ.get('ANTHROPIC_API_KEY'):
        needs_api = any(d not in ('outcomes',) for d in domains)
        if needs_api and coaching != 'strict':
            log('ERROR: ANTHROPIC_API_KEY not set. Required for hone domains.')
            sys.exit(1)

    title = read_yaml_field('project.title', project_dir) or 'Untitled'
    model = select_model('synthesis')

    log('============================================')
    log('Storyforge Hone')
    log(f'Project: {title}')
    if args.diagnose:
        log('Mode: diagnose (read-only)')
    else:
        log(f'Domains: {" ".join(domains)}')
    log(f'Coaching: {coaching}')
    if args.scenes:
        log(f'Scenes: {args.scenes}')
    if not args.diagnose:
        log(f'Model: {model}')
    log('============================================')

    # Scene filter
    scene_filter = _resolve_scene_filter(args, ref_dir)

    if args.diagnose:
        _run_diagnose(ref_dir, project_dir, scene_filter)
        log('')
        log('============================================')
        log('Diagnose complete (read-only, no files changed)')
        log('============================================')
        return

    # Run domains
    for domain in domains:
        log(f'\n--- Hone: {domain} ---')
        _run_domain(domain, ref_dir, project_dir, log_dir, model, coaching,
                    scene_filter, args.threshold, args.dry_run)

    log('\n============================================')
    log('Hone complete')
    log('============================================')


def _resolve_domains(args) -> list[str]:
    if args.domain:
        return [d.strip() for d in args.domain.split(',')]
    if args.phase:
        return {1: PHASE1_REGISTRY, 2: PHASE2_REGISTRY, 3: PHASE3_REGISTRY}.get(args.phase, [])
    return list(ALL_DOMAINS)


def _resolve_scene_filter(args, ref_dir: str) -> list[str] | None:
    if args.scenes:
        return [s.strip() for s in args.scenes.split(',')]
    if args.act:
        from storyforge.elaborate import _read_csv
        rows = _read_csv(os.path.join(ref_dir, 'scenes.csv'))
        return [r['id'] for r in rows if r.get('part', '') == args.act]
    return None


def _run_domain(domain: str, ref_dir: str, project_dir: str, log_dir: str,
                model: str, coaching: str, scene_filter: list[str] | None,
                threshold: float, dry_run: bool) -> None:
    char_bible = os.path.join(project_dir, 'reference', 'character-bible.md')

    if domain in ALL_REGISTRY_SUBS:
        _run_registry_domain(domain, ref_dir, project_dir, log_dir, model,
                             char_bible, dry_run)
    elif domain == 'registries':
        for sub in ALL_REGISTRY_SUBS:
            log(f'  --- registries/{sub} ---')
            if dry_run:
                log('    (dry-run)')
                continue
            _run_registry_domain(sub, ref_dir, project_dir, log_dir, model,
                                 char_bible, dry_run)
    elif domain == 'briefs':
        _run_briefs_domain(ref_dir, project_dir, log_dir, model, coaching,
                           scene_filter, threshold, dry_run)
    elif domain == 'gaps':
        _run_gaps_domain(ref_dir, project_dir, scene_filter, dry_run)
    elif domain == 'structural':
        log('  (structural CSV fixes route through evaluation findings — run after storyforge-evaluate)')
    else:
        log(f'WARNING: Unknown domain: {domain}')


def _run_registry_domain(domain: str, ref_dir: str, project_dir: str,
                         log_dir: str, model: str, char_bible: str,
                         dry_run: bool) -> None:
    if dry_run:
        if domain == 'outcomes':
            log('  (deterministic — no API call needed)')
        else:
            from storyforge.hone import build_registry_prompt
            context = ''
            if domain == 'characters' and os.path.isfile(char_bible):
                with open(char_bible) as f:
                    context = f.read()
            prompt = build_registry_prompt(domain, ref_dir, context=context)
            log(f'  Prompt for {domain} ({len(prompt)} chars)')
        return

    from storyforge.hone import reconcile_domain
    context = ''
    if domain == 'characters' and os.path.isfile(char_bible):
        with open(char_bible) as f:
            context = f.read()

    result = reconcile_domain(domain, ref_dir, model, log_dir, context=context)
    entries = result.get('registry_entries', 0)
    normalized = result.get('fields_normalized', 0)
    log(f'  Registry: {entries} entries, {normalized} normalizations')

    commit_and_push(project_dir,
                    f'Hone: registries/{domain} — {entries} entries, {normalized} normalizations',
                    ['reference/', 'working/logs/'])


def _run_briefs_domain(ref_dir: str, project_dir: str, log_dir: str,
                       model: str, coaching: str, scene_filter: list[str] | None,
                       threshold: float, dry_run: bool) -> None:
    from storyforge.elaborate import _read_csv_as_map
    from storyforge.hone import detect_brief_issues, hone_briefs

    briefs = _read_csv_as_map(os.path.join(ref_dir, 'scene-briefs.csv'))
    scenes = _read_csv_as_map(os.path.join(ref_dir, 'scenes.csv'))
    issues = detect_brief_issues(briefs, scenes, scene_filter)

    by_type: dict[str, list] = {}
    for i in issues:
        by_type.setdefault(i['issue'], []).append(i)

    total = len(issues)
    affected = len(set(i['scene_id'] for i in issues))
    n_abstract = len(by_type.get('abstract', []))
    n_overspec = len(by_type.get('overspecified', []))
    n_verbose = len(by_type.get('verbose', []))

    log(f'  Issues found: {total} across {affected} scenes')
    log(f'    abstract: {n_abstract}  overspecified: {n_overspec}  verbose: {n_verbose}')

    if dry_run:
        for i in issues:
            issue = i['issue']
            if issue == 'overspecified':
                log(f"  {i['scene_id']}.{i['field']}: {issue} ({i['beat_count']} beats, {i.get('target_words', 0)} target words)")
            elif issue == 'verbose':
                log(f"  {i['scene_id']}.{i['field']}: {issue} ({i['char_count']} chars, max {i['max_chars']})")
            elif issue == 'abstract':
                log(f"  {i['scene_id']}.{i['field']}: {issue} (abstract={i['abstract_count']}, concrete={i['concrete_count']})")
        return

    if total == 0:
        log('  No brief quality issues found')
        return

    result = hone_briefs(
        ref_dir, project_dir,
        scene_ids=scene_filter,
        threshold=threshold,
        model=model,
        log_dir=log_dir,
        coaching_level=coaching,
        dry_run=False,
    )

    rewritten = result.get('scenes_rewritten', 0)
    fields = result.get('fields_rewritten', 0)
    log(f'  Rewritten: {rewritten} scenes, {fields} fields')

    if rewritten > 0:
        commit_and_push(project_dir,
                        f'Hone: briefs — {rewritten} scenes concretized ({fields} fields)',
                        ['reference/', 'working/'])


def _run_gaps_domain(ref_dir: str, project_dir: str,
                     scene_filter: list[str] | None, dry_run: bool) -> None:
    from storyforge.elaborate import _read_csv_as_map
    from storyforge.hone import detect_gaps, propagate_physical_states

    scenes = _read_csv_as_map(os.path.join(ref_dir, 'scenes.csv'))
    intent = _read_csv_as_map(os.path.join(ref_dir, 'scene-intent.csv'))
    briefs = _read_csv_as_map(os.path.join(ref_dir, 'scene-briefs.csv'))

    gaps = detect_gaps(scenes, intent, briefs, scene_filter)
    gap_count = len(gaps)
    gap_scenes = len(set(g['scene_id'] for g in gaps))
    log(f'  Gaps found: {gap_count} empty fields across {gap_scenes} scenes')

    # Physical state propagation (deterministic)
    prop = propagate_physical_states(ref_dir, dry_run=dry_run)
    log(f'  Physical state propagation: {prop["states_propagated"]} states '
        f'across {prop["scenes_updated"]} scenes ({len(prop["changes"])} field updates)')

    if dry_run:
        return

    if len(prop['changes']) > 0:
        commit_and_push(project_dir,
                        f'Hone: gaps — propagate {prop["states_propagated"]} physical states '
                        f'across {prop["scenes_updated"]} scenes',
                        ['reference/'])

    if gap_count > 0:
        log(f'  ({gap_count} remaining gaps require storyforge-elaborate --gap-fill)')


def _run_diagnose(ref_dir: str, project_dir: str, scene_filter: list[str] | None) -> None:
    from storyforge.elaborate import _read_csv_as_map
    from storyforge.hone import detect_brief_issues, detect_gaps
    from storyforge.structural import structural_score

    scenes = _read_csv_as_map(os.path.join(ref_dir, 'scenes.csv'))
    intent = _read_csv_as_map(os.path.join(ref_dir, 'scene-intent.csv'))
    briefs = _read_csv_as_map(os.path.join(ref_dir, 'scene-briefs.csv'))

    # Part 1: Structural scores
    print('\n=== Structural Scores ===\n')
    scores = structural_score(ref_dir)
    dims = scores.get('dimensions', [])
    for dim in dims:
        name = dim.get('label', dim.get('name', '?'))
        score = dim.get('score', 0)
        bar = '#' * int(score * 20) + '.' * (20 - int(score * 20))
        print(f'  {name:30s} [{bar}] {score:.2f}')
        for f in dim.get('findings', [])[:3]:
            msg = f.get('message', '') if isinstance(f, dict) else str(f)
            print(f'    - {msg}')
    overall = scores.get('overall_score', scores.get('overall', 0))
    print(f'\n  Overall structural score: {overall:.2f}')

    # Part 2: Brief quality
    print('\n=== Brief Quality Issues ===\n')
    issues = detect_brief_issues(briefs, scenes, scene_filter)
    by_type: dict[str, list] = {}
    for i in issues:
        by_type.setdefault(i['issue'], []).append(i)

    if not issues:
        print('  No brief quality issues found.')
    else:
        for issue_type in ['abstract', 'overspecified', 'verbose']:
            items = by_type.get(issue_type, [])
            if not items:
                continue
            print(f'  {issue_type} ({len(items)} issues):')
            for item in items:
                if issue_type == 'overspecified':
                    print(f'    {item["scene_id"]}.{item["field"]}: {item["beat_count"]} beats, {item.get("target_words", 0)} target words')
                elif issue_type == 'verbose':
                    print(f'    {item["scene_id"]}.{item["field"]}: {item["char_count"]} chars (max {item["max_chars"]})')
                elif issue_type == 'abstract':
                    print(f'    {item["scene_id"]}.{item["field"]}: abstract={item["abstract_count"]}, concrete={item["concrete_count"]}')
            print()

    # Part 3: Gaps
    print('=== Gaps ===\n')
    gaps = detect_gaps(scenes, intent, briefs, scene_filter)
    if not gaps:
        print('  No missing required fields.')
    else:
        by_scene: dict[str, list[str]] = {}
        for g in gaps:
            by_scene.setdefault(g['scene_id'], []).append(g['field'])
        for sid, fields in sorted(by_scene.items()):
            print(f'  {sid}: missing {", ".join(fields)}')

    # Part 4: Exemplars
    print('\n=== Prose Exemplars ===\n')
    try:
        import storyforge.exemplars as ex_mod
        ex = ex_mod.validate_project_exemplars(project_dir)
        if not ex['has_any']:
            print('  No exemplars found. Add reference/prose-exemplars.md or reference/exemplars/{pov}.md')
        else:
            for f in ex['files']:
                v = f['validation']
                status = 'PASS' if v['valid'] else 'ISSUES'
                print(f'  {f["pov"]}: {v["word_count"]} words [{status}]')
                for issue in v['issues']:
                    print(f'    - {issue}')
            if ex['missing_povs']:
                print(f'  Missing per-POV exemplars: {", ".join(ex["missing_povs"])}')
    except Exception as e:
        print(f'  (exemplar validation unavailable: {e})')

    # Summary
    print('\n=== Summary ===\n')
    print(f'  Structural score:    {overall:.2f}')
    print(f'  Brief issues:        {len(issues)} across {len(set(i["scene_id"] for i in issues))} scenes')
    print(f'  Gaps:                {len(gaps)} empty fields across {len(set(g["scene_id"] for g in gaps))} scenes')
    clean = len(set(scenes.keys()) - set(i['scene_id'] for i in issues) - set(g['scene_id'] for g in gaps))
    print(f'  Clean scenes:        {clean} / {len(scenes)}')

    # Recommendations
    recs = []
    if issues:
        recs.append('Run: storyforge hone --domain briefs')
    if gaps:
        recs.append('Run: storyforge hone --domain gaps')
    dormant = []
    for dim in dims:
        for f in dim.get('findings', []):
            msg = f.get('message', '') if isinstance(f, dict) else str(f)
            if 'dormant' in msg.lower():
                dormant.append(msg)
    if dormant:
        recs.append(f'MICE dormancy: {len(dormant)} threads need intermediate mentions')
        recs.append('Run: storyforge elaborate --mice-fill')
    if recs:
        print('\n  Recommendations:')
        for r in recs:
            print(f'    -> {r}')
