"""The re-check set on E1 cases: rejecting an error's established fact must
list the scene that contradicted it. See ``evals/recheck``."""

from collections import Counter, defaultdict

import recheck
from harness import Gate, Suite, SuiteOutput

RECALL_GATE = 0.9
MIN_CASES = 15


def run(ctx):
    from storyforge import ledger
    cases, excluded = recheck.select()
    notes = []
    by_tree = defaultdict(list)
    for case in cases:
        est = next(s for s in case['established'] if s.get('source', 'prose') == 'prose')
        by_tree[(case['repo'], est['commit'])].append(case)
    verdicts: Counter = Counter()
    hits = Counter()            # by verdict
    by_code: dict[str, Counter] = {}
    sizes, fractions = [], []
    controls = controls_in = unrelated_cases = 0
    for (repo, commit), group in sorted(by_tree.items()):
        project = recheck.project_for(group[0], commit, ctx.work_dir)
        order = ledger.scene_order(project)
        items = []
        for case in group:
            placed = recheck.place(case, project, order)
            if isinstance(placed, str):
                excluded.setdefault(placed, []).append(case['id'])
            else:
                items.append(placed)
        if not items:
            continue
        subset = sorted({s for it in items for s in [it.established, *it.contradicted, *it.controls]},
                        key=order.get)
        recheck.commit_subset(project, subset)
        rows = ledger.load(project)
        for it in items:
            cid = it.case['id']
            verdict = recheck.judge(it, rows)
            verdicts[verdict['verdict']] += 1
            code = by_code.setdefault(it.case['code'], Counter())
            code['cases'] += 1
            if not verdict['ids']:
                notes.append(f'{cid} ({it.established} → {", ".join(it.contradicted)}): '
                             'fact not in the ledger')
                continue
            scenes, unrelated = recheck.recheck_set(project, rows, verdict['ids'])
            hit = bool(set(it.contradicted) & set(scenes))
            if verdict['verdict'] == 'captured':
                code['captured'] += 1
                code['hit'] += hit
                sizes.append(len(scenes))
                later = recheck.later_with_prose(project, it.established, order)
                fractions.append(len(scenes) / later if later else 0.0)
                controls += len(it.controls)
                controls_in += len(set(it.controls) & set(scenes))
            hits[verdict['verdict']] += hit
            unrelated_cases += bool(unrelated)
            notes.append(f'{cid} ({it.established} → {", ".join(it.contradicted)}): '
                         f'{verdict["verdict"]} {";".join(verdict["ids"])}, '
                         f'{"HIT" if hit else "MISS"}, set {len(scenes)}'
                         + (f'; unrelated: {"; ".join(unrelated)}' if unrelated else ''))
    measured = sum(verdicts.values())
    captured = verdicts['captured']
    recall = round(hits['captured'] / captured, 4) if captured else 0.0
    with_partial = verdicts['captured'] + verdicts['partial']
    return SuiteOutput(
        metrics={
            'cases': measured, 'captured': captured, 'partial': verdicts['partial'],
            'missing': verdicts['missing'],
            'recall': recall,
            'recall_with_partial': round((hits['captured'] + hits['partial']) / with_partial, 4)
            if with_partial else 0.0,
            'recall_end_to_end': round(hits['captured'] / measured, 4) if measured else 0.0,
            'set_size_mean': round(sum(sizes) / len(sizes), 2) if sizes else 0.0,
            'set_fraction_mean': round(sum(fractions) / len(fractions), 4) if fractions else 0.0,
            'control_inclusion': round(controls_in / controls, 4) if controls else 0.0,
            'controls': controls,
            'unrelated_cases': unrelated_cases,
        },
        by_code={code: {'cases': c['cases'], 'captured': c['captured'],
                        'recall': round(c['hit'] / c['captured'], 4) if c['captured'] else 0.0}
                 for code, c in by_code.items()},
        gates=[Gate('captured', captured, '>=', MIN_CASES), Gate('recall', recall, '>=', RECALL_GATE)],
        notes=[f'excluded {len(ids)}: {reason}' for reason, ids in sorted(excluded.items())]
        + notes
        + ['recall: of the cases whose fact the judge found recorded, the share whose re-check '
           'set (cmd_audit._reject_recheck) holds a contradicting scene. Commitments exist only '
           'for the extracted subset (each case\'s two scenes and its controls), so '
           'set_fraction_mean is a floor; control_inclusion estimates over-inclusion.'],
    )


SUITE = Suite('recheck-set', 'Phase 4: rejecting an E1 error\'s established fact re-checks '
              'the scene that contradicted it', run)
