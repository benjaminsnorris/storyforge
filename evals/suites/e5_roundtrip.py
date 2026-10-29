"""E5 roundtrip: redraft a fixed sample from plan + ledger, count changed facts.
See ``evals/e5``."""

from collections import Counter

import e5
from harness import Gate, Suite, SuiteOutput


def run(ctx):
    project = e5.project(ctx.work_dir)
    scenes = e5.sample(project)
    by_code: Counter = Counter()
    notes = []
    for sid in scenes:
        _, mismatches = e5.roundtrip(project, sid)
        by_code.update(m['code'] for m in mismatches)
        notes.append(f'{sid}: {len(mismatches)} mismatch(es)'
                     + ''.join(f'\n    {m["code"]}: {m.get("fact", "")[:140]}' for m in mismatches))
    total = sum(by_code.values())
    return SuiteOutput(
        metrics={'scenes': len(scenes), 'mismatches': total,
                 'mismatches_per_scene': round(total / len(scenes), 3) if scenes else 0.0},
        by_code={code: {'mismatches': n} for code, n in by_code.items()},
        gates=[Gate('scenes', len(scenes), '>=', e5.SAMPLE)],
        notes=notes,
    )


SUITE = Suite('e5-roundtrip', 'Redraft from plan + ledger; facts the redraft changes', run)
