"""E8 revision safety: re-run current passes where past passes wrote errors.

See evals/e8/__init__.py. Gate (plan §5, Phase 4): zero errors reintroduced.
"""

from e1 import load_cases, load_holdout
from e8 import DATA_FAMILIES, PassHalted, family, judge, prepare, replay, select
from harness import Gate, Suite, SuiteOutput

MIN_REPLAYED = 15  # below this the rate is too noisy to gate on


def run(ctx):
    sel = select(load_cases(), load_holdout())
    notes = []
    by_code: dict[str, dict[str, float]] = {}
    by_family: dict[str, list[int]] = {}
    reintroduced = replayed = words = prose_hits = halted = unflagged = 0
    for case in sel.cases:
        try:
            project, scene_id = prepare(case, ctx.work_dir)
        except LookupError as e:
            sel.exclude(f'unreplayable: {e}', case['id'])
            continue
        try:
            output = replay(case, project, scene_id)
        except PassHalted as e:
            halted += 1
            notes.append(f'{case["id"]} ({scene_id}): halted, nothing written — {str(e)[:160]}')
            continue
        data = family(case) in DATA_FAMILIES
        unjudged = data and not output.strip()
        if unjudged:  # a data pass that wrote nothing cannot have reintroduced anything
            verdict = {'verdict': 'not_present', 'evidence': ''}
        elif not output.strip():  # prose replays raise rather than return nothing
            raise RuntimeError(f'{case["id"]}: the replay returned no prose')
        else:
            verdict = judge(case, output)
        replayed += 1
        hit = verdict['verdict'] == 'reintroduced'
        reintroduced += hit
        # a gated prose pass that didn't pass leaves the scene listed for the
        # author (revise stops there); one it passed reaches the book unflagged
        flagged = not data and _listed_pending(project, scene_id)
        unflagged += hit and not flagged
        if not data:  # errors per 10k words counts prose only, on both sides
            words += len(output.split())
            prose_hits += hit
        code = by_code.setdefault(case['code'], {'replayed': 0, 'reintroduced': 0})
        code['replayed'] += 1
        code['reintroduced'] += hit
        fam = by_family.setdefault(family(case), [0, 0])
        fam[0] += 1
        fam[1] += hit
        notes.append(f'{case["id"]} ({scene_id}): {verdict["verdict"]}'
                     + (' (wrote nothing; not judged)' if unjudged else '')
                     + (' (the gate did not pass it: listed pending)' if flagged else '')
                     + (f' — "{verdict.get("evidence", "")[:120]}"' if hit else ''))
    # after the loop, which adds the cases prepare() could not replay
    notes[:0] = [f'excluded {len(ids)}: {reason} ({", ".join(ids)})'
                 for reason, ids in sorted(sel.excluded.items())]
    unreplayable = sum(len(v) for k, v in sel.excluded.items() if k.startswith('unreplayable'))
    return SuiteOutput(
        metrics={'replayed': replayed, 'reintroduced': reintroduced,
                 'reintroduced_unflagged': unflagged,
                 'reintroduction_rate': round(reintroduced / replayed, 3) if replayed else 0.0,
                 'errors_per_10k_words': round(prose_hits / words * 10000, 3) if words else 0.0,
                 'unreplayable': unreplayable, 'halted': halted,
                 **{f'family.{k}.replayed': v[0] for k, v in by_family.items()},
                 **{f'family.{k}.reintroduced': v[1] for k, v in by_family.items()}},
        by_code=by_code,
        gates=[Gate('replayed', replayed, '>=', MIN_REPLAYED),
               Gate('reintroduced', reintroduced, '==', 0)],
        notes=notes,
    )


def _listed_pending(project_dir: str, scene_id: str) -> bool:
    """Whether the replay left `scene_id` in working/gate-pending.csv: the
    gate didn't pass it (or couldn't finish), so write/revise stop there
    and the author is told. Every gated family lists it as they do
    (`e8.gate_as_revise`, and naturalness-upstream through revise's own
    `_redraft_scenes`); the pre-pass projects predate the file. An
    unreadable file counts as not listed (write/revise would stop on it)."""
    from storyforge import gate
    try:
        return scene_id in gate.pending(project_dir)
    except gate.GateError:
        return False


SUITE = Suite('e8-revision-safety',
              'Current revision passes vs the E1 errors past passes introduced', run)
