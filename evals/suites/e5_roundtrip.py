"""E5 roundtrip: redraft a fixed sample from plan + ledger, count changed facts.
See ``evals/e5``. The headline redraft is a rewrite (the original a voice
reference only), as write and revise run it; ``ledger_only.*`` redrafts from
the plan and ledger alone."""

from collections import Counter

import e5
from harness import Gate, Suite, SuiteOutput


def run(ctx):
    project = e5.project(ctx.work_dir)
    scenes = e5.sample(project)
    e5.commit_prose(project, scenes)
    by_code: Counter = Counter()
    ledger_only: Counter = Counter()
    notes = []
    for sid in scenes:
        _, mismatches = e5.roundtrip(project, sid)
        _, gaps = e5.roundtrip(project, sid, rewrite=False)
        by_code.update(m['code'] for m in mismatches)
        ledger_only.update(m['code'] for m in gaps)
        notes.append(f'{sid}: {len(mismatches)} mismatch(es) rewritten, {len(gaps)} from the '
                     f'plan and ledger alone'
                     + ''.join(f'\n    {m["code"]}: {m.get("fact", "")[:140]}' for m in mismatches))
    total = sum(by_code.values())
    gaps_total = sum(ledger_only.values())
    per_scene = round(total / len(scenes), 3) if scenes else 0.0
    return SuiteOutput(
        metrics={'scenes': len(scenes), 'mismatches': total, 'mismatches_per_scene': per_scene,
                 'ledger_only.mismatches': gaps_total,
                 'ledger_only.mismatches_per_scene':
                     round(gaps_total / len(scenes), 3) if scenes else 0.0,
                 **{f'ledger_only.{code}': n for code, n in sorted(ledger_only.items())}},
        by_code={code: {'mismatches': n} for code, n in by_code.items()},
        gates=[Gate('scenes', len(scenes), '>=', e5.SAMPLE),
               Gate('mismatches_per_scene', per_scene, '<=', e5.PHASE2_PER_SCENE)],
        notes=notes,
    )


SUITE = Suite('e5-roundtrip', 'Rewrite from plan + ledger; facts the rewrite changes', run)
