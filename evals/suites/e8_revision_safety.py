"""E8 revision safety: re-run current passes where past passes wrote errors.

See evals/e8/__init__.py. Gate (plan §5, Phase 4): zero errors reintroduced.
"""

from e1 import load_cases, load_holdout
from e8 import judge, prepare, redraft, select
from harness import Gate, Suite, SuiteOutput

MIN_REPLAYED = 15  # below this the rate is too noisy to gate on


def run(ctx):
    sel = select(load_cases(), load_holdout())
    notes = [f'excluded {len(ids)}: {reason}' for reason, ids in sorted(sel.excluded.items())]
    by_code: dict[str, dict[str, float]] = {}
    reintroduced = replayed = words = 0
    for case in sel.cases:
        try:
            project, scene_id = prepare(case, ctx.work_dir)
        except LookupError as e:
            sel.exclude(f'unreplayable: {e}', case['id'])
            continue
        prose = redraft(project, scene_id)
        verdict = judge(case, prose)
        replayed += 1
        words += len(prose.split())
        hit = verdict['verdict'] == 'reintroduced'
        reintroduced += hit
        code = by_code.setdefault(case['code'], {'replayed': 0, 'reintroduced': 0})
        code['replayed'] += 1
        code['reintroduced'] += hit
        notes.append(f'{case["id"]} ({scene_id}): {verdict["verdict"]}'
                     + (f' — "{verdict.get("evidence", "")[:120]}"' if hit else ''))
    unreplayable = sum(len(v) for k, v in sel.excluded.items() if k.startswith('unreplayable'))
    return SuiteOutput(
        metrics={'replayed': replayed, 'reintroduced': reintroduced,
                 'reintroduction_rate': round(reintroduced / replayed, 3) if replayed else 0.0,
                 'errors_per_10k_words': round(reintroduced / words * 10000, 3) if words else 0.0,
                 'unreplayable': unreplayable},
        by_code=by_code,
        gates=[Gate('replayed', replayed, '>=', MIN_REPLAYED),
               Gate('reintroduced', reintroduced, '==', 0)],
        notes=notes,
    )


SUITE = Suite('e8-revision-safety',
              'Current redraft-from-brief pass vs the E1 errors past passes introduced', run)
