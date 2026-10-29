"""E7 — classics regression: what the continuity checks flag in books with no
known errors.

Runs today's structural validator over frozen extraction snapshots of public-
domain classics and matches every continuity flag (physical state, timeline,
knowledge) to the author's verdict on it. A classic has no real errors, so
every flag that is not ``real`` is noise; the target is none. A flag with no
verdict is ``unreviewed`` — a new kind of noise, or a real find — and needs the
author before it can be counted either way, so it fails the suite too.

v1 covers A Christmas Carol's two extraction runs and the deterministic
validator only. ``timeline --check`` flags (8 of the 68 labeled) need API calls
and are not replayed yet; Gatsby has no labeled flag set yet.
"""

import csv
import os
from collections import Counter

from harness import EVALS_DIR, Gate, Suite, SuiteOutput

FIXTURES = os.path.join(EVALS_DIR, 'fixtures', 'e7')
CONTINUITY_CATEGORIES = ('physical_state', 'timeline', 'knowledge')
VERDICTS = ('real', 'deliberate', 'extraction-error', 'false-positive')


def book_snapshots():
    """(book, run, reference dir) for every frozen snapshot."""
    for book in sorted(os.listdir(FIXTURES)):
        book_dir = os.path.join(FIXTURES, book)
        if not os.path.isdir(book_dir):
            continue
        for run in sorted(os.listdir(book_dir)):
            ref = os.path.join(book_dir, run, 'reference')
            if os.path.isdir(ref):
                yield book, run, ref


def load_labels(book: str) -> dict[tuple[str, str, str], dict]:
    with open(os.path.join(FIXTURES, book, 'flags.csv'), newline='') as f:
        rows = list(csv.DictReader(f, delimiter='|'))
    bad = [r for r in rows if r.get('ben_verdict') not in VERDICTS]
    if bad:
        raise ValueError(f'{book}: {len(bad)} flag(s) with no valid ben_verdict')
    return {(r['run'], r['scene_id'], r['flag']): r for r in rows
            if r['source'].startswith('validate')}


def continuity_flags(ref_dir: str) -> list[dict]:
    from storyforge.elaborate import validate_structure
    return [c for c in validate_structure(ref_dir)['checks']
            if not c['passed'] and c['category'] in CONTINUITY_CATEGORIES]


def run(ctx):
    counts: Counter = Counter()
    by_code: dict[str, dict[str, float]] = {}
    notes = []
    snapshots = list(book_snapshots())
    if not snapshots:
        raise RuntimeError(f'no snapshots under {FIXTURES}')
    for book, run_name, ref in snapshots:
        labels = load_labels(book)
        flags = continuity_flags(ref)
        for flag in flags:
            label = labels.get((run_name, flag.get('scene_id', ''), flag['message']))
            verdict = label['ben_verdict'] if label else 'unreviewed'
            counts[verdict] += 1
            code = label['code'] if label else ('PHY' if flag['category'] == 'physical_state'
                                                else 'TIM' if flag['category'] == 'timeline'
                                                else 'KNO')
            by_code.setdefault(code, Counter())[verdict] += 1
            if not label:
                notes.append(f'unreviewed {book}/{run_name}: {flag["message"][:160]}')
        notes.insert(0, f'{book}/{run_name}: {len(flags)} flag(s)')
    total = sum(counts.values())
    noise = total - counts['real']
    return SuiteOutput(
        metrics={'flags': total, 'noise': noise,
                 **{v.replace('-', '_'): counts[v] for v in VERDICTS},
                 'unreviewed': counts['unreviewed'], 'snapshots': len(snapshots)},
        by_code={code: dict(c) for code, c in by_code.items()},
        gates=[Gate('unreviewed', counts['unreviewed'], '==', 0),
               Gate('noise', noise, '==', 0)],
        notes=notes,
    )


SUITE = Suite('e7-classics', 'Continuity flags raised on classics with no known errors', run)
