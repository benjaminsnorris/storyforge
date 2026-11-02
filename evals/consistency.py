#!/usr/bin/env python3
"""E6 consistency: replay the paid suites' three independent runs, report spread.

    python3 evals/consistency.py                 # replay all three runs (free), write evals/e6/spread.json
    python3 evals/consistency.py --suite NAME    # only this suite (repeatable): its entries in
                                                 # spread.json are replaced, the others kept
    python3 evals/consistency.py --report FILE   # also save each run's full report under FILE's stem

Run 1 is ``fixtures/cassettes``; runs 2 and 3 are ``fixtures/e6/run2`` and
``run3``. See ``evals/e6`` for why this is not a default suite.
Also writes evals/e6/e8-cases.json: each E8 case's outcome per run (when
E8 was replayed). ``git_sha`` in spread.json is per suite, per run: a suite
re-recorded alone (``--suite``) is a later commit than the rest.
Exit code: 0 every run replayed, 2 a suite errored in some run (1 from an
uncaught crash).
"""

from __future__ import annotations

import argparse
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import e6  # noqa: E402
from harness import EVALS_DIR, discover, run_all  # noqa: E402

SPREAD_FILE = os.path.join(EVALS_DIR, 'e6', 'spread.json')
CASES_FILE = os.path.join(EVALS_DIR, 'e6', 'e8-cases.json')

# Moves the status doc reported from single runs, each to be read against
# E6's range: (suite, metric, claimed delta, where it was claimed). Deltas
# are exact counts over the suite's cases, not the rounded figures: a delta
# equal to the range must compare equal.
CLAIMS = (
    ('e3-extraction', 'recall', 2 / 49,
     'structured outputs: recall 0.245 -> 0.286 (12 -> 14 of 49; v1.83.0)'),
    ('e3-extraction', 'recall_with_partial', 3 / 49,
     'structured outputs: with partial 0.816 -> 0.755 (40 -> 37 of 49; v1.83.0)'),
    ('e3-extraction', 'missing', 2,
     'tier comparison: Opus misses 7, Sonnet 9 (v1.81.0)'),
    ('e3-extraction', 'missing', 4,
     'tier comparison: Haiku misses 13, Sonnet 9 (v1.81.0)'),
    ('e2-corpus-drift', 'recall', 3 / 51,
     'v1.80.0 re-record on new models: recall 0.16 -> 0.10 (8 -> 5 of 51)'),
    ('e2-corpus-drift', 'precision', 0.10,
     'v1.80.0 re-record on new models: precision 0.30 -> 0.40'),
    ('e4-generation', 'cp10k', 2.1,
     're-pin to 5e9bdf39: CP10k 18.2 -> 16.1 (v1.84.2)'),
    ('e8-revision-safety', 'reintroduced', 1,
     'E8 gaps: reintroduced 5 -> 6 (#383; one new case, thornwall-020)'),
    ('e4-generation', 'cp10k_passed', 3.42 - 2.09,
     "what the gate stops on: CP10k in the gate's passed scenes 3.42 -> 2.09 (#480)"),
    ('e4-generation', 'gate_missed', 1,
     'what the gate stops on: gate missed 5 -> 4 (#480)'),
    ('e4-generation', 'gate_failed', 1,
     'a second fix round: still failing after the fixes 3 -> 4 (#482)'),
    ('e4-generation', 'gate_fixed', 1,
     'a second fix round: fixed 9 -> 10 (#482)'),
    ('e4-generation', 'cp10k_passed', 2.17 - 2.09,
     'a second fix round: CP10k in passed scenes 2.09 -> 2.17 (#482)'),
)


def parse_args(argv):
    parser = argparse.ArgumentParser(prog='evals/consistency.py',
                                     description=__doc__.splitlines()[0])
    parser.add_argument('--suite', action='append', default=[],
                        help='Replay only this suite (repeatable); the others keep their '
                             'entries in the spread file')
    parser.add_argument('--report', help='Save each run\'s full report as FILE-runN.json')
    parser.add_argument('--spread-file', default=SPREAD_FILE, help=argparse.SUPPRESS)
    parser.add_argument('--cases-file', default=CASES_FILE, help=argparse.SUPPRESS)
    return parser.parse_args(argv)


def main(argv=None) -> int:
    args = parse_args(argv)
    wanted = args.suite or list(e6.SUITES)
    unknown = sorted(set(wanted) - set(e6.SUITES))
    if unknown:
        print(f'ERROR: not an E6 suite: {", ".join(unknown)} (E6 runs {", ".join(e6.SUITES)})',
              file=sys.stderr)
        return 2
    suites = [s for s in discover(os.path.join(EVALS_DIR, 'suites')) if s.name in wanted]
    missing = sorted(set(wanted) - {s.name for s in suites})
    if missing:
        print(f'ERROR: suite(s) not found: {", ".join(missing)}', file=sys.stderr)
        return 2
    reports = {}
    for run, parts in e6.RUN_DIRS.items():
        print(f'Replaying {run} ...', flush=True)
        reports[run] = run_all(suites, 'replay', os.path.join(EVALS_DIR, *parts))
        if args.report:
            stem, _ = os.path.splitext(args.report)
            with open(f'{stem}-{run}.json', 'w') as f:
                json.dump(reports[run], f, indent=2, sort_keys=True)
                f.write('\n')
    summary = e6.summarize(reports)
    summary['git_sha'] = {s.name: {run: r['git_sha'] for run, r in reports.items()}
                          for s in suites}
    if args.suite:
        try:
            with open(args.spread_file) as f:
                summary = e6.merge(json.load(f), summary)
        except (OSError, ValueError, KeyError, TypeError) as e:
            print(f'ERROR: can\'t merge into {args.spread_file} ({e}); replay every suite '
                  f'(no --suite) to write it afresh', file=sys.stderr)
            return 2
    summary['claims'] = [{**e6.exceeds(summary, suite, metric, delta), 'claim': claim}
                         for suite, metric, delta, claim in CLAIMS]
    with open(args.spread_file, 'w') as f:
        json.dump(summary, f, indent=2, sort_keys=True)
        f.write('\n')
    if 'e8-revision-safety' in wanted:
        with open(args.cases_file, 'w') as f:
            json.dump(e6.case_outcomes(reports), f, indent=1, sort_keys=True)
            f.write('\n')
    print(_summary(summary))
    print(f'Spread: {args.spread_file}')
    return 2 if summary['errored'] else 0


def _summary(summary: dict) -> str:
    lines = []
    for suite, metrics in summary['suites'].items():
        lines.append(suite)
        for name, row in metrics.items():
            if row['range'] == 0 and not row.get('missing_in'):
                continue
            values = ', '.join(f'{v:g}' for v in row['values'])
            gap = f'  (missing in {", ".join(row["missing_in"])})' if row.get('missing_in') else ''
            lines.append(f'  {name}: {values}  range {row["range"]:g}{gap}')
    for suite, why in summary['errored'].items():
        lines.append(f'{suite}: ERRORED — ' + '; '.join(f'{r}: {w}' for r, w in why.items()))
    lines.append('Claims against run-to-run range:')
    for c in summary['claims']:
        verdict = ('no verdict: ' + c['why'] if c['within_noise'] is None
                   else 'WITHIN NOISE' if c['within_noise'] else 'outside noise')
        lines.append(f'  {c["suite"]} {c["metric"]} Δ{c["claimed_delta"]:g} vs range '
                     f'{c["range"] if c["range"] is not None else "-"}: {verdict} — {c["claim"]}')
    return '\n'.join(lines)


if __name__ == '__main__':
    sys.exit(main())
