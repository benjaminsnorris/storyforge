"""E8 revision safety: re-run current passes where past passes wrote errors.

See evals/e8/__init__.py. Gate (plan §5, Phase 4): zero errors reintroduced.
"""

from e1 import load_cases, load_holdout
from e8 import PassHalted, family, judge, prepare, replay, select
from harness import Gate, Suite, SuiteOutput

MIN_REPLAYED = 15  # below this the rate is too noisy to gate on


def run(ctx):
    sel = select(load_cases(), load_holdout())
    notes = [f'excluded {len(ids)}: {reason}' for reason, ids in sorted(sel.excluded.items())]
    by_code: dict[str, dict[str, float]] = {}
    by_family: dict[str, list[int]] = {}
    reintroduced = replayed = words = halted = 0
    for case in sel.cases:
        try:
            project, scene_id = prepare(case, ctx.work_dir)
        except LookupError as e:
            sel.exclude(f'unreplayable: {e}', case['id'])
            continue
        try:
            prose = replay(case, project, scene_id)
        except PassHalted as e:
            halted += 1
            notes.append(f'{case["id"]} ({scene_id}): halted, nothing written — {str(e)[:160]}')
            continue
        verdict = judge(case, prose)
        replayed += 1
        words += len(prose.split())
        hit = verdict['verdict'] == 'reintroduced'
        reintroduced += hit
        code = by_code.setdefault(case['code'], {'replayed': 0, 'reintroduced': 0})
        code['replayed'] += 1
        code['reintroduced'] += hit
        fam = by_family.setdefault(family(case), [0, 0])
        fam[0] += 1
        fam[1] += hit
        notes.append(f'{case["id"]} ({scene_id}): {verdict["verdict"]}'
                     + (f' — "{verdict.get("evidence", "")[:120]}"' if hit else ''))
    unreplayable = sum(len(v) for k, v in sel.excluded.items() if k.startswith('unreplayable'))
    return SuiteOutput(
        metrics={'replayed': replayed, 'reintroduced': reintroduced,
                 'reintroduction_rate': round(reintroduced / replayed, 3) if replayed else 0.0,
                 'errors_per_10k_words': round(reintroduced / words * 10000, 3) if words else 0.0,
                 'unreplayable': unreplayable, 'halted': halted,
                 **{f'family.{k}.replayed': v[0] for k, v in by_family.items()},
                 **{f'family.{k}.reintroduced': v[1] for k, v in by_family.items()}},
        by_code=by_code,
        gates=[Gate('replayed', replayed, '>=', MIN_REPLAYED),
               Gate('reintroduced', reintroduced, '==', 0)],
        notes=notes,
    )


SUITE = Suite('e8-revision-safety',
              'Current revision passes vs the E1 errors past passes introduced', run)
