"""E7 — classics regression: what the continuity checks flag in books with no
known errors.

Runs today's structural validator over frozen extraction snapshots of public-
domain classics and matches every continuity flag (physical state, timeline,
knowledge) to the author's verdict on it. A classic has no real errors, so
every flag that is not ``real`` is noise; the target is none. A flag with no
verdict is ``unreviewed`` — a new kind of noise, or a real find — and needs the
author before it can be counted either way, so it fails the suite too.

The target is no noise, but the gate is that noise doesn't change unseen
(plan Phase 5: "E7 false-positive rate stable across releases"); a zero gate
failed on every run, so a failing E7 said nothing. Noise must equal
``NOISE_CEILING``: a change that removes flags fails until it lowers the
ceiling (and drops their labels) in the same commit, so the ceiling never has
slack to hide new noise. Every labeled flag must still be raised, exactly once
(``missing_labels``, ``duplicate_flags``), so flags that vanish (a renamed
category, a lost snapshot) fail rather than pass as less noise, and a dropped
flag's stale label can't later match a regression. E7 makes no API calls and
needs only the standard library, so CI runs it on every pull request
(``.github/workflows/e7-classics.yml``, with ``--notes`` to name the flags).

Covers A Christmas Carol's two extraction runs and The Plastic Age's one, and
the deterministic validator only. ``timeline --check`` flags (8 of Carol's 58
labeled, 5 of The Plastic Age's 60) need API calls and are not replayed yet;
Gatsby has no labeled flag set yet.
"""

import csv
import os
import shutil
from collections import Counter

from harness import EVALS_DIR, Gate, Suite, SuiteOutput, migrate_tree

FIXTURES = os.path.join(EVALS_DIR, 'fixtures', 'e7')
CONTINUITY_CATEGORIES = ('physical_state', 'timeline', 'knowledge')
VERDICTS = ('real', 'deliberate', 'extraction-error', 'false-positive')

#: The noise the gate expects: today's replayed count. Lower it when a change
#: removes flags; raising it means accepting new noise (tests/test_evals_e7.py
#: pins its highest value, so that takes a second, visible edit).
NOISE_CEILING = 105


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


def migrated(ref: str, work_dir: str, label: str) -> str:
    """A copy of a snapshot's reference dir with its registries in the
    ledger: the frozen snapshots predate it (``harness.migrate_tree``)."""
    copy = os.path.join(work_dir, 'e7-migrated', label)
    shutil.copytree(ref, os.path.join(copy, 'reference'))
    migrate_tree(copy, label)
    return os.path.join(copy, 'reference')


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
    raised: dict[str, Counter] = {}
    for book, run_name, ref in snapshots:
        labels = load_labels(book)
        flags = continuity_flags(migrated(ref, ctx.work_dir, f'{book}/{run_name}'))
        for flag in flags:
            key = (run_name, flag.get('scene_id', ''), flag['message'])
            raised.setdefault(book, Counter())[key] += 1
            label = labels.get(key)
            verdict = label['ben_verdict'] if label else 'unreviewed'
            counts[verdict] += 1
            code = label['code'] if label else ('PHY' if flag['category'] == 'physical_state'
                                                else 'TIM' if flag['category'] == 'timeline'
                                                else 'KNO')
            by_code.setdefault(code, Counter())[verdict] += 1
            if not label:
                notes.append(f'unreviewed {book}/{run_name}: {flag["message"][:160]}')
        notes.insert(0, f'{book}/{run_name}: {len(flags)} flag(s)')
    # Every labeled flag raised, once: a flag that vanishes must not pass as
    # less noise, and its stale label must not later match a regression.
    missing = duplicates = 0
    for book in sorted({b for b, _, _ in snapshots}):
        seen = raised.get(book, Counter())
        for key in sorted(set(load_labels(book)) - set(seen)):
            missing += 1
            notes.append(f'labeled but not raised {book}/{key[0]}/{key[1]}: {key[2][:160]} '
                         f'(drop its row from flags.csv if the change meant to remove it)')
        for key, n in sorted(seen.items()):
            if n > 1:
                duplicates += n - 1
                notes.append(f'raised {n} times {book}/{key[0]}/{key[1]}: {key[2][:160]}')
    total = sum(counts.values())
    noise = total - counts['real']
    if noise != NOISE_CEILING:
        notes.insert(0, f'noise {noise}, NOISE_CEILING {NOISE_CEILING}: '
                        + (f'lower NOISE_CEILING to {noise}' if noise < NOISE_CEILING
                           else 'new noise; label it, or fix the check that raised it'))
    return SuiteOutput(
        metrics={'flags': total, 'noise': noise,
                 **{v.replace('-', '_'): counts[v] for v in VERDICTS},
                 'unreviewed': counts['unreviewed'], 'snapshots': len(snapshots),
                 'missing_labels': missing, 'duplicate_flags': duplicates},
        by_code={code: dict(c) for code, c in by_code.items()},
        gates=[Gate('unreviewed', counts['unreviewed'], '==', 0),
               Gate('missing_labels', missing, '==', 0),
               Gate('duplicate_flags', duplicates, '==', 0),
               Gate('noise', noise, '==', NOISE_CEILING)],
        notes=notes,
    )


SUITE = Suite('e7-classics', 'Continuity flags raised on classics with no known errors', run)
