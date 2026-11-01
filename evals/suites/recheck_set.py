"""The re-check set on E1 cases: rejecting an error's established fact must
re-check the scene that contradicted it. See ``evals/recheck``."""

from collections import Counter, defaultdict

import recheck
from harness import Gate, Suite, SuiteOutput

RECALL_GATE = 0.9
MIN_CASES = 15


def _rate(hit: int, of: int) -> float:
    return round(hit / of, 4) if of else 0.0


def run(ctx):
    from storyforge import ledger
    cases, excluded = recheck.select()
    notes = []
    by_tree = defaultdict(list)
    for case in cases:
        by_tree[(case['repo'], recheck.prose_spans(case['established'])[0]['commit'])].append(case)
    verdicts: Counter = Counter()
    hits = Counter()            # by verdict
    by_code: dict[str, Counter] = {}
    sizes, fractions = [], []
    controls = controls_in = unrelated_cases = 0
    for (repo, commit), group in sorted(by_tree.items()):
        project = recheck.project_for(group[0], commit, ctx.work_dir)
        recheck.check_migrated(project)
        order = ledger.scene_order(project)
        gone = recheck.gone_scenes(project)
        items = []
        for case in group:
            placed = recheck.place(case, project, order, gone)
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
        notes.append(f'{repo}@{commit[:8]}: phase 4 over {len(subset)} scenes; '
                     f'{recheck.unplaced(rows, subset)} ledger facts name a scene outside '
                     'the subset (offered to none)')
        for it in items:
            cid = it.case['id']
            where = f'{cid} ({it.established} → {", ".join(it.contradicted)})'
            if it.dropped:
                where += f' [left out: {"; ".join(it.dropped)}]'
            verdict = recheck.judge(it, rows)
            verdicts[verdict['verdict']] += 1
            code = by_code.setdefault(it.case['code'], Counter())
            code['cases'] += 1
            if verdict['verdict'] == recheck.NO_ROWS:
                notes.append(f'{where}: the establishing scene has no binding ledger rows')
                continue
            if verdict['verdict'] == 'missing':
                notes.append(f'{where}: fact not in the ledger')
                continue
            found = recheck.recheck_set(project, rows, verdict['ids'], order)
            hit = bool(set(it.contradicted) & set(found.scenes))
            if verdict['verdict'] == 'captured':
                code['captured'] += 1
                code['hit'] += hit
                sizes.append(len(found.scenes))
                later = recheck.later_usable(project, it.established, order, gone)
                if not later:   # place guarantees a contradicting scene after it
                    raise RuntimeError(f'{cid}: no usable scene after {it.established}')
                fractions.append(len(found.scenes) / later)
                controls += len(it.controls)
                controls_in += len(set(it.controls) & set(found.scenes))
            hits[verdict['verdict']] += hit
            unrelated_cases += bool(found.unrelated)
            extra = ''.join(f'; {label}: {"; ".join(vals)}' for label, vals in (
                ('unrelated', found.unrelated), ('not listed', found.not_listed)) if vals)
            notes.append(f'{where}: {verdict["verdict"]} {";".join(verdict["ids"])}, '
                         f'{"HIT" if hit else "MISS"}, set {len(found.scenes)}{extra}')
    measured = sum(verdicts.values())
    captured = verdicts['captured']
    recall = _rate(hits['captured'], captured)
    return SuiteOutput(
        metrics={
            'cases': measured, 'captured': captured, 'partial': verdicts['partial'],
            'missing': verdicts['missing'], 'no_rows': verdicts[recheck.NO_ROWS],
            'excluded': sum(len(ids) for ids in excluded.values()),
            'recall': recall,
            'recall_with_partial': _rate(hits['captured'] + hits['partial'],
                                         captured + verdicts['partial']),
            'recall_end_to_end': _rate(hits['captured'], measured),
            'set_size_mean': round(sum(sizes) / len(sizes), 2) if sizes else 0.0,
            'set_fraction_mean': round(sum(fractions) / len(fractions), 4) if fractions else 0.0,
            'control_inclusion': _rate(controls_in, controls),
            'controls': controls,
            'unrelated_cases': unrelated_cases,
        },
        # a code with nothing captured has no recall to report
        by_code={code: {'cases': c['cases'], 'captured': c['captured'],
                        **({'recall': _rate(c['hit'], c['captured'])} if c['captured'] else {})}
                 for code, c in by_code.items()},
        gates=[Gate('captured', captured, '>=', MIN_CASES), Gate('recall', recall, '>=', RECALL_GATE)],
        notes=[f'excluded {len(ids)}: {reason}' for reason, ids in sorted(excluded.items())]
        + notes
        + ['recall: of the cases judged captured, the share whose re-check set holds a '
           'contradicting scene (the scenes the reject flow lists now, or the ones its '
           'revision lists). Commitments exist only for the extracted subset (each case\'s '
           'establishing and contradicting scenes and up to 2 controls), and phase 4 is '
           'offered the subset\'s facts only, so set_fraction_mean is a floor; '
           'control_inclusion is an upper bound on needless inclusion (controls sit next to '
           'the two sides).'],
    )


SUITE = Suite('recheck-set', 'Phase 4: rejecting an E1 error\'s established fact re-checks '
              'the scene that contradicted it', run)
