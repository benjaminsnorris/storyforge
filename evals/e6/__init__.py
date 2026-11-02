"""E6 — consistency: how much do the paid suites move between runs of the
same code?

Plan §4.2: run E2 and E4 three times and report the variance, flagging any eval
whose variance exceeds the improvement claimed. E3 and E8 are run too, because
E3's recall moves and tier comparison and E8's reintroduction counts were all
single runs read "inside noise until E6".

Run 1 is the default recordings (``fixtures/cassettes/``). Runs 2 and 3 are
independent live recordings under ``fixtures/e6/run2`` and ``run3``, of the
code run 1 had when they were made; run 1 moves on with every re-record, so
a run-2/3 recording replays only from a checkout of its commit (spread.json's
``git_sha`` names it, per suite). Each run's recordings replay for free, so the spread can be
recomputed without spending; ``evals/consistency.py`` does that.

**Not a default suite.** The extra runs are a snapshot of one commit's
prompts. Any prompt change is a recording miss, and keeping E6 in
``run.py``'s default set would mean either an error on every prompt change or
two fresh live runs of every paid suite (about $36) each time. Re-record E6
when a variance question needs today's code, not on every change.
"""

from __future__ import annotations

import math
import re

SUITES = ('e2-carol', 'e2-corpus-drift', 'e3-extraction', 'e4-generation',
          'e8-revision-safety')
RUN_DIRS = {'run1': ('fixtures', 'cassettes'),
            'run2': ('fixtures', 'e6', 'run2'),
            'run3': ('fixtures', 'e6', 'run3')}


def flatten(result: dict) -> dict[str, float]:
    """A suite result's numeric metrics, ``by_code`` ones as ``CODE.metric``."""
    flat = {k: v for k, v in result.get('metrics', {}).items() if _numeric(v)}
    for code, metrics in result.get('by_code', {}).items():
        for name, value in metrics.items():
            if _numeric(value):
                flat[f'{code}.{name}'] = value
    return flat


def _numeric(value) -> bool:
    return isinstance(value, (int, float)) and not isinstance(value, bool)


def spread(values: list[float]) -> dict:
    """Mean, sample standard deviation, min, max and range of one metric."""
    n = len(values)
    mean = sum(values) / n
    sd = math.sqrt(sum((v - mean) ** 2 for v in values) / (n - 1)) if n > 1 else 0.0
    return {'values': values, 'mean': round(mean, 6), 'sd': round(sd, 6),
            'min': min(values), 'max': max(values),
            'range': round(max(values) - min(values), 6)}


def summarize(reports: dict[str, dict]) -> dict:
    """Per suite, per metric, the spread across runs.

    ``reports`` maps a run name to a ``run.py``-shaped report. A suite that
    errored in any run is listed under ``errored`` with no spread, because a
    missing measurement is not a low one. A metric missing from some runs (a
    code that showed up in one run only) is spread over the runs that have it,
    with ``missing_in`` naming the others. For a count, a missing ``by_code``
    entry means zero, but this can't tell a count from a rate, so it says so
    rather than filling in a zero.
    """
    runs = list(reports)
    out: dict = {'runs': runs, 'suites': {}, 'errored': {}}
    by_run = {run: {r['suite']: r for r in report['results']}
              for run, report in reports.items()}
    suites = sorted({s for results in by_run.values() for s in results})
    for suite in suites:
        bad = {run: ('suite not in this run' if suite not in by_run[run]
                     else by_run[run][suite].get('error') or 'errored (no message)')
               for run in runs
               if suite not in by_run[run] or by_run[run][suite]['status'] == 'error'}
        if bad:
            out['errored'][suite] = bad
            continue
        flats = {run: flatten(by_run[run][suite]) for run in runs}
        metrics = {}
        for name in sorted({m for flat in flats.values() for m in flat}):
            present = [run for run in runs if name in flats[run]]
            row = spread([flats[run][name] for run in present])
            missing = [run for run in runs if run not in present]
            if missing:
                row['missing_in'] = missing
            metrics[name] = row
        out['suites'][suite] = metrics
    return out


def merge(old: dict, new: dict) -> dict:
    """``old`` (a spread file) with ``new``'s suites in place of its own:
    each suite ``new`` replayed (spread or errored) replaces its spread, its
    errored entry and its ``git_sha``; the others are kept as they were.

    Raises:
        ValueError: ``old`` is not a spread file of the same runs with a
            per-suite ``git_sha`` (``{suite: {run: sha}}``).
    """
    if not isinstance(old, dict):
        raise ValueError('it is not a JSON object')
    if old.get('runs') != new['runs']:
        raise ValueError(f'its runs are {old.get("runs")}, not {new["runs"]}')
    sha = old.get('git_sha')
    if not isinstance(sha, dict) or any(not isinstance(v, dict) for v in sha.values()):
        raise ValueError('its git_sha is not per suite ({suite: {run: sha}})')
    replayed = set(new['suites']) | set(new['errored'])
    out = {'runs': new['runs'],
           'suites': {s: m for s, m in old['suites'].items() if s not in replayed},
           'errored': {s: w for s, w in old['errored'].items() if s not in replayed},
           'git_sha': {s: v for s, v in sha.items() if s not in replayed}}
    out['suites'].update(new['suites'])
    out['errored'].update(new['errored'])
    out['git_sha'].update({s: v for s, v in new['git_sha'].items() if s in replayed})
    return out


_ROUNDING = 5e-4


def exceeds(summary: dict, suite: str, metric: str, claimed_delta: float) -> dict:
    """Whether one metric's run-to-run range is at least a claimed improvement.

    The plan's flag: an eval whose variance exceeds the improvement claimed
    can't support that claim. Range (max - min over the runs) is the measure,
    since three runs give too little for a confidence interval.
    """
    row = summary['suites'].get(suite, {}).get(metric)
    if row is None or row.get('missing_in'):
        why = ('suite errored or not run' if suite not in summary['suites']
               else 'no run measured this metric' if row is None
               else 'metric not measured in every run')
        return {'suite': suite, 'metric': metric, 'claimed_delta': claimed_delta,
                'range': None, 'within_noise': None, 'why': why}
    # Suites round their metrics to 4 places, so a range built from them can
    # fall just short of an exact delta it equals
    return {'suite': suite, 'metric': metric, 'claimed_delta': claimed_delta,
            'range': row['range'],
            'within_noise': row['range'] + _ROUNDING >= abs(claimed_delta)}


_CASE_NOTE = re.compile(r'^(\S+-\d+) \([^)]*\): (\w+)')


def case_outcomes(reports: dict[str, dict], suite: str = 'e8-revision-safety') -> dict:
    """Each case's outcome per run (``reintroduced``, ``consistent``,
    ``not_present``, ``halted``), read from the suite's notes, which name
    every replayed case as ``<case> (<scene>): <outcome>``."""
    out: dict[str, dict[str, str]] = {}
    for run, report in reports.items():
        for result in report['results']:
            if result['suite'] != suite:
                continue
            for note in result.get('notes', []):
                m = _CASE_NOTE.match(note)
                if m:
                    out.setdefault(m.group(1), {})[run] = m.group(2)
    return out
