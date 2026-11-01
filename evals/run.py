#!/usr/bin/env python3
"""Run the Storyforge eval suites.

    python3 evals/run.py                      # all suites, replay recorded calls (free)
    python3 evals/run.py --suite e2-detection # one suite (repeatable)
    python3 evals/run.py --mode auto          # replay what exists, record the rest (spends)
    python3 evals/run.py --mode record        # re-record every call (spends)
    python3 evals/run.py --baseline           # also write evals/baseline.json
    python3 evals/run.py --list

Writes the full report to evals/results/latest.json and prints a summary; when
evals/baseline.json exists the summary includes per-metric deltas against it.
Exit code: 0 pass, 1 a gate failed, 2 a suite errored (no measurement).
"""

from __future__ import annotations

import argparse
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from harness import EVALS_DIR, compare, discover, run_all  # noqa: E402

SUITES_DIR = os.path.join(EVALS_DIR, 'suites')
CASSETTES_DIR = os.path.join(EVALS_DIR, 'fixtures', 'cassettes')
RESULTS_FILE = os.path.join(EVALS_DIR, 'results', 'latest.json')
BASELINE_FILE = os.path.join(EVALS_DIR, 'baseline.json')
EXIT_CODES = {'pass': 0, 'fail': 1, 'error': 2}


def parse_args(argv):
    parser = argparse.ArgumentParser(prog='evals/run.py', description=__doc__.splitlines()[0])
    parser.add_argument('--suite', action='append', default=[], help='Run only this suite')
    parser.add_argument('--mode', choices=('replay', 'record', 'auto'), default='replay')
    parser.add_argument('--baseline', action='store_true', help='Write evals/baseline.json')
    parser.add_argument('--list', action='store_true', help='List suites and exit')
    parser.add_argument('--notes', action='store_true',
                        help="Print each suite's notes (CI uses it to name what failed)")
    parser.add_argument('--suites-dir', default=SUITES_DIR, help=argparse.SUPPRESS)
    parser.add_argument('--cassettes-dir', default=CASSETTES_DIR, help=argparse.SUPPRESS)
    parser.add_argument('--results-file', default=RESULTS_FILE, help=argparse.SUPPRESS)
    parser.add_argument('--baseline-file', default=BASELINE_FILE, help=argparse.SUPPRESS)
    return parser.parse_args(argv)


def _write_json(path: str, data: dict) -> None:
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, 'w') as f:
        json.dump(data, f, indent=2, sort_keys=True)
        f.write('\n')


def _summary(report: dict, deltas: dict | None, notes: bool = False) -> str:
    lines = [f"{report['suite_count']} suite(s), mode={report['mode']}, "
             f"status={report['status'].upper()}, storyforge {report['storyforge_version']} "
             f"@ {report['git_sha'][:10]}{' (dirty)' if report['git_dirty'] else ''}"]
    if not report['results']:
        lines.append('No suites found. Add a module defining SUITE to evals/suites/.')
    reported = {r['suite'] for r in report['results']}
    for name in sorted(set(deltas or {}) - reported):
        lines.append(f"  [MISSING] {name}: in the baseline, not in this run")
    for r in report['results']:
        lines.append(f"  [{r['status'].upper()}] {r['suite']} ({r['duration_s']}s, "
                     f"{r['cost']['calls']} calls, ${r['cost']['usd_spent']} spent, "
                     f"${r['cost']['usd_if_live']} if live)")
        if r['error']:
            lines.append(f"      error: {r['error']}")
        for g in r['gates']:
            mark = 'ok  ' if g['passed'] else 'FAIL'
            lines.append(f"      {mark} {g['name']}: {g['actual']} {g['op']} {g['threshold']}")
        if notes:
            lines.extend(f"      note: {n}" for n in r['notes'])
        for name, row in (deltas or {}).get(r['suite'], {}).items():
            if row['delta'] not in (None, 0):
                lines.append(f"      {name}: {row['baseline']} -> {row['current']} "
                             f"({row['delta']:+})")
            elif row['baseline'] is None or row['current'] is None:
                lines.append(f"      {name}: {row['baseline']} -> {row['current']}")
    cost = report['cost']
    lines.append(f"Total: {cost['calls']} calls ({cost['replayed_calls']} replayed), "
                 f"${cost['usd_spent']} spent, ${cost['usd_if_live']} if live")
    if cost['unpriced_calls']:
        lines.append(f"  {cost['unpriced_calls']} call(s) used a model with no known price "
                     f"and were costed at sonnet rates")
    return '\n'.join(lines)


def main(argv=None) -> int:
    from storyforge.__main__ import python_too_old
    too_old = python_too_old(sys.version_info)
    if too_old:
        print('ERROR: ' + too_old, file=sys.stderr)
        return 2
    args = parse_args(sys.argv[1:] if argv is None else argv)
    if os.path.isfile(args.results_file):
        os.remove(args.results_file)  # a crash must not leave the last run's report to be read as this one's
    try:
        return _main(args)
    except Exception as e:  # infrastructure, not a measurement: never exit 1 ("a gate failed")
        print(f'ERROR: {type(e).__name__}: {e}', file=sys.stderr)
        return 2


def _main(args) -> int:
    suites = discover(args.suites_dir)
    if args.list:
        for s in suites:
            print(f'{s.name}: {s.description}')
        return 0
    if args.suite:
        known = {s.name for s in suites}
        unknown = [n for n in args.suite if n not in known]
        if unknown:
            print(f'ERROR: unknown suite(s): {", ".join(unknown)}', file=sys.stderr)
            return 2
        suites = [s for s in suites if s.name in args.suite]

    report = run_all(suites, args.mode, args.cassettes_dir)
    deltas = None
    if os.path.isfile(args.baseline_file):
        with open(args.baseline_file) as f:
            baseline = json.load(f)
        deltas = compare(report, baseline)
        report['baseline_comparison'] = deltas
    _write_json(args.results_file, report)
    print(_summary(report, deltas, notes=args.notes))
    print(f'Report: {args.results_file}')

    if args.baseline:
        if report['status'] == 'error':
            print('ERROR: not writing a baseline over a suite that errored — '
                  'a missing measurement is not a low one.', file=sys.stderr)
            return 2
        if args.suite:
            print('ERROR: --baseline needs every suite; drop --suite.', file=sys.stderr)
            return 2
        report.pop('baseline_comparison', None)
        _write_json(args.baseline_file, report)
        print(f'Baseline: {args.baseline_file}')
    return EXIT_CODES[report['status']]


if __name__ == '__main__':
    sys.exit(main())
