#!/usr/bin/env python3
"""Run the Storyforge eval suites.

    python3 evals/run.py                      # all suites, replay recorded calls (free)
    python3 evals/run.py --suite e2-detection # one suite (repeatable)
    python3 evals/run.py --mode auto          # replay what exists, record the rest (spends)
    python3 evals/run.py --mode record        # re-record every call (spends)
    python3 evals/run.py --mode record --suite e4-generation --runs 3   # a frozen suite
    python3 evals/run.py --baseline           # also write evals/baseline.json
    python3 evals/run.py --list

Writes the full report to evals/results/latest.json and prints a summary; when
evals/baseline.json exists the summary includes per-metric deltas against it.

E4 and E8 are frozen (#645): auto and record replay them, and a miss makes
them stale rather than errored. Live calls count against a monthly eval
budget (evals/config.json) kept in the eval spend ledger
(storyforge.eval_spend); --over-budget REASON is the only way past it.

Exit code: 0 pass (stale suites included: stale is not a failure), 1 a gate
failed, 2 a suite errored (no measurement) or the run was refused.
"""

from __future__ import annotations

import argparse
import json
import math
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from harness import EVALS_DIR, compare, discover, overall_status, run_all  # noqa: E402

SUITES_DIR = os.path.join(EVALS_DIR, 'suites')
CASSETTES_DIR = os.path.join(EVALS_DIR, 'fixtures', 'cassettes')
#: Runs 2 and up of ``--runs N`` record here as run2/, run3/ (E6's layout)
RUNS_DIR = os.path.join(EVALS_DIR, 'fixtures', 'e6')
RESULTS_FILE = os.path.join(EVALS_DIR, 'results', 'latest.json')
BASELINE_FILE = os.path.join(EVALS_DIR, 'baseline.json')
CONFIG_FILE = os.path.join(EVALS_DIR, 'config.json')
#: Stale is not a failure: a frozen suite missing its cassette after a prompt
#: change is expected, and CI must stay green on it (#645)
EXIT_CODES = {'pass': 0, 'fail': 1, 'error': 2, 'stale': 0}
DEFAULT_MONTHLY_BUDGET = 25.0
#: A frozen suite is recorded as this many independent runs, never fewer
FROZEN_RUNS = 3


class Refused(Exception):
    """The run was refused before anything ran (exit 2)."""


def parse_args(argv):
    parser = argparse.ArgumentParser(prog='evals/run.py', description=__doc__.splitlines()[0])
    parser.add_argument('--suite', action='append', default=[], help='Run only this suite')
    parser.add_argument('--mode', choices=('replay', 'record', 'auto'), default='replay')
    parser.add_argument('--runs', type=int, default=1,
                        help=f'Record N independent runs (record mode only): run 1 to the '
                             f'default cassettes, run K to evals/fixtures/e6/runK. A frozen '
                             f'suite (E4, E8) is recorded only by name and only as '
                             f'--runs {FROZEN_RUNS}')
    parser.add_argument('--over-budget', metavar='REASON', default='',
                        help='Spend past the monthly eval budget; REASON (who approved it '
                             'and why) is printed, put in the report and written on every '
                             'ledger line this run adds')
    parser.add_argument('--baseline', action='store_true', help='Write evals/baseline.json')
    parser.add_argument('--list', action='store_true', help='List suites and exit')
    parser.add_argument('--notes', action='store_true',
                        help="Print each suite's notes (CI uses it to name what failed)")
    parser.add_argument('--suites-dir', default=SUITES_DIR, help=argparse.SUPPRESS)
    parser.add_argument('--cassettes-dir', default=CASSETTES_DIR, help=argparse.SUPPRESS)
    parser.add_argument('--results-file', default=RESULTS_FILE, help=argparse.SUPPRESS)
    parser.add_argument('--baseline-file', default=BASELINE_FILE, help=argparse.SUPPRESS)
    parser.add_argument('--runs-dir', default=RUNS_DIR, help=argparse.SUPPRESS)
    parser.add_argument('--config-file', default=CONFIG_FILE, help=argparse.SUPPRESS)
    parser.add_argument('--spend-log', default=None, help=argparse.SUPPRESS)
    return parser.parse_args(argv)


def monthly_budget(config_file: str) -> float:
    """The monthly eval budget in USD: ``monthly_budget_usd`` in
    evals/config.json, $25 when nothing exists at that path. Anything there
    that doesn't give a finite, non-negative number (a directory, a dangling
    symlink, NaN) refuses the run: a guessed budget is no guard."""
    if not os.path.lexists(config_file):
        return DEFAULT_MONTHLY_BUDGET
    try:
        with open(config_file) as f:
            value = json.load(f)['monthly_budget_usd']
        if isinstance(value, bool) or not isinstance(value, (int, float)) \
                or not math.isfinite(value) or value < 0:
            raise ValueError(f'{value!r} is not a non-negative number')
    except (OSError, ValueError, KeyError, TypeError) as e:
        raise Refused(f'{config_file}: monthly_budget_usd unreadable ({e})') from e
    return float(value)


def _forecast(suites, baseline_file: str, runs: int) -> tuple[float, list[str]]:
    """What recording ``suites`` live costs, ``runs`` times, from each one's
    ``usd_if_live`` in the baseline; and the suites it has no figure for (no
    entry, or one without a usable figure). No baseline file at all leaves
    every suite without a figure.

    Raises:
        Refused: the baseline exists but can't be read, so no figure is known.
    """
    by_suite = {}
    if os.path.lexists(baseline_file):
        try:
            with open(baseline_file) as f:
                results = json.load(f).get('results', [])
            if not isinstance(results, list):
                raise TypeError('results is not a list')
        except (OSError, ValueError, TypeError, AttributeError) as e:
            raise Refused(f'the baseline {baseline_file} can\'t be read for the forecast '
                          f'({type(e).__name__}: {e})') from e
        for r in results:
            try:
                usd = r['cost']['usd_if_live']
            except (KeyError, TypeError):
                continue
            if isinstance(usd, (int, float)) and not isinstance(usd, bool) \
                    and math.isfinite(usd) and usd >= 0 and isinstance(r.get('suite'), str):
                by_suite[r['suite']] = usd
    known = [by_suite[s.name] for s in suites if s.name in by_suite]
    return round(sum(known) * runs, 2), [s.name for s in suites if s.name not in by_suite]


def _plan_recording(args, suites) -> set[str]:
    """Check --runs against the frozen-suite rules; the frozen suites this
    run may record."""
    if args.runs < 1:
        raise Refused('--runs must be at least 1')
    if args.runs > 1 and args.mode != 'record':
        raise Refused('--runs records independent runs, so it needs --mode record')
    if args.runs > 1 and args.baseline:
        raise Refused('--baseline takes one run; drop --runs')
    named = {s.name for s in suites if s.frozen and s.name in args.suite}
    if named and args.mode == 'auto':
        raise Refused(f'{", ".join(sorted(named))} is frozen: auto would only replay it. '
                      f'Replay it with the default mode, or re-record it on purpose with '
                      f'--mode record --suite NAME --runs {FROZEN_RUNS}.')
    if args.mode != 'record':
        return set()
    if named and args.runs != FROZEN_RUNS:
        raise Refused(f'{", ".join(sorted(named))} is frozen: it is recorded only as '
                      f'--runs {FROZEN_RUNS} (one run can\'t separate a change from noise). '
                      f'Re-record it only when a decision depends on it.')
    return named


def _check_budget(args, suites, record_frozen: set[str], ledger: str) -> dict:
    """Refuse a run the monthly budget can't cover; the report's budget block.

    ``record`` is refused when this month's spend plus the forecast (each
    recorded suite's ``usd_if_live`` in the baseline, times ``--runs``) passes
    the budget; ``auto`` records only misses, so it is refused only once the
    budget is spent. Either way the cassette refuses each live call once the
    month reaches the budget.

    A suite with no baseline figure adds $0 to the forecast, so for it the
    forecast is a lower bound: named in a WARNING, and the cassette's
    per-call check is its guard. A frozen suite recorded with no figure is
    refused (a cut-off three-run recording leaves its cassettes mixed), as is
    a baseline that can't be read; ``--over-budget`` lifts both."""
    from storyforge import eval_spend
    budget = monthly_budget(args.config_file)
    try:
        spent = eval_spend.month_spend(ledger)
    except eval_spend.SpendLedgerError as e:
        if not args.over_budget:
            raise Refused(str(e)) from e
        print(f'WARNING: {e}', file=sys.stderr)
        spent = None
    recording = [s for s in suites if not s.frozen or s.name in record_frozen]
    try:
        forecast, unknown = _forecast(recording, args.baseline_file, args.runs)
    except Refused as e:
        if not args.over_budget:
            raise
        print(f'WARNING: {e}', file=sys.stderr)
        forecast, unknown = 0.0, [s.name for s in recording]
    source = args.config_file if os.path.lexists(args.config_file) else \
        f'default; {args.config_file} absent'
    info = {'monthly_usd': budget, 'ledger': ledger, 'spent_before_usd': spent,
            'forecast_usd': forecast, 'forecast_unknown': unknown,
            'over_budget': args.over_budget or None}
    spent_text = 'unknown' if spent is None else f'${spent:.2f}'
    bound = 'at most ' if args.mode == 'auto' else ''
    print(f'Eval budget: {spent_text} of ${budget:.2f} ({source}) spent this month '
          f'({ledger}); this run, {bound}${forecast:.2f} if every call goes live'
          + (f' (no figure for {", ".join(unknown)}: not in the baseline)' if unknown else ''))
    if unknown and args.mode == 'record':
        print(f'WARNING: no baseline figure for {", ".join(unknown)}, so the forecast counts '
              f'it as $0 and is a lower bound; the per-call budget check still applies.',
              file=sys.stderr)
    if args.over_budget:
        print(f'WARNING: --over-budget: the monthly eval budget is not enforced for this run. '
              f'Reason: {args.over_budget}', file=sys.stderr)
        return info
    unforecast_frozen = sorted(set(unknown) & record_frozen)
    if unforecast_frozen:
        raise Refused(
            f'{", ".join(unforecast_frozen)} has no usd_if_live in the baseline, so its '
            f'{args.runs}-run recording can\'t be forecast, and a recording the budget cuts '
            f'off partway leaves its cassettes mixed. Ask Ben; with his approval re-run with '
            f'--over-budget "<who approved, why>".')
    over = spent >= budget if args.mode == 'auto' else spent + forecast > budget
    if over:
        raise Refused(
            f'the monthly eval budget would be passed: {spent_text} spent of ${budget:.2f}'
            + (f', and this run forecasts ${forecast:.2f}' if args.mode == 'record' else '')
            + '. Ask Ben; with his approval re-run with --over-budget "<who approved, why>".')
    return info


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
        if r.get('stale'):
            lines.append(f"      stale: {r['stale']}")
            first_miss = next((f for f in r.get('cassette_failures', [])
                               if f.startswith('CassetteMiss')), '')
            if first_miss:
                lines.append(f"      first miss: {first_miss}")
            if r.get('stale_exception'):
                lines.append(f"      raised after the miss (kept, assumed its consequence): "
                             f"{r['stale_exception']}")
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
    stale = [r['suite'] for r in report['results'] if r['status'] == 'stale']
    if stale:
        lines.append(f"  stale (frozen, not re-recorded, nothing spent; exit code unaffected): "
                     f"{', '.join(stale)}")
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
    except Refused as e:
        print(f'ERROR: refused: {e}', file=sys.stderr)
        return 2
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

    from storyforge import eval_spend
    args.over_budget = args.over_budget.strip()
    record_frozen = _plan_recording(args, suites)
    ledger = os.path.expanduser(args.spend_log) if args.spend_log else eval_spend.default_ledger()
    budget = None
    if args.mode != 'replay':
        budget = _check_budget(args, suites, record_frozen, ledger)
    env = {eval_spend.LEDGER_ENV: ledger,
           eval_spend.BUDGET_ENV: str(budget['monthly_usd']) if budget else '',
           eval_spend.OVERRIDE_ENV: args.over_budget}
    saved = {k: os.environ.get(k) for k in env}
    os.environ.update(env)
    try:
        report = run_all(suites, args.mode, args.cassettes_dir, record_frozen=record_frozen)
        extra = {f'run{k}': run_all(suites, args.mode, os.path.join(args.runs_dir, f'run{k}'),
                                    record_frozen=record_frozen)
                 for k in range(2, args.runs + 1)}
    finally:
        for key, value in saved.items():
            if value is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = value
    if extra:
        report['extra_runs'] = extra
        report['status'] = overall_status([report['status']]
                                          + [r['status'] for r in extra.values()])
    if record_frozen and report['status'] == 'error':
        dirs = [os.path.join(args.cassettes_dir, name) for name in sorted(record_frozen)]
        dirs += [os.path.join(args.runs_dir, f'run{k}', name)
                 for k in range(2, args.runs + 1) for name in sorted(record_frozen)]
        print('WARNING: a run of this frozen recording errored, so these cassettes may now '
              'mix new and old recordings: ' + ', '.join(dirs) + '. Re-record all '
              f'{args.runs} runs, or restore them with git checkout.', file=sys.stderr)
    if budget:
        try:
            budget['spent_after_usd'] = eval_spend.month_spend(ledger)
        except eval_spend.SpendLedgerError as e:
            budget['spent_after_usd'] = None
            print(f'WARNING: {e}', file=sys.stderr)
        report['budget'] = budget
    deltas = None
    if os.path.isfile(args.baseline_file):
        with open(args.baseline_file) as f:
            baseline = json.load(f)
        deltas = compare(report, baseline)
        report['baseline_comparison'] = deltas
    _write_json(args.results_file, report)
    print(_summary(report, deltas, notes=args.notes))
    for run, extra_report in report.get('extra_runs', {}).items():
        print(f'--- {run} ({os.path.join(args.runs_dir, run)})')
        print(_summary(extra_report, None, notes=args.notes))
    if report.get('extra_runs'):
        print('Recompute the run-to-run spread from the new runs: python3 evals/consistency.py '
              + ' '.join(f'--suite {s.name}' for s in suites))
    if budget:
        after = budget['spent_after_usd']
        print(f"Eval budget: {'unknown' if after is None else f'${after:.2f}'} of "
              f"${budget['monthly_usd']:.2f} spent this month"
              + (f" (over budget: {budget['over_budget']})" if budget['over_budget'] else ''))
    print(f'Report: {args.results_file}')

    #: What this run measured; a carried-over baseline entry never changes it
    exit_code = EXIT_CODES[report['status']]
    if args.baseline:
        if report['status'] == 'error':
            print('ERROR: not writing a baseline over a suite that errored — '
                  'a missing measurement is not a low one.', file=sys.stderr)
            return 2
        if args.suite:
            print('ERROR: --baseline needs every suite; drop --suite.', file=sys.stderr)
            return 2
        report.pop('baseline_comparison', None)
        refused = _carry_stale(report, args.baseline_file)
        if refused:
            print(f'ERROR: not writing a baseline: {refused}', file=sys.stderr)
            return 2
        _write_json(args.baseline_file, report)
        print(f'Baseline: {args.baseline_file}')
    return exit_code


def _carry_stale(report: dict, baseline_file: str) -> str:
    """Put the old baseline's entry in place of each stale suite's result
    (marked ``carried_over``): a frozen suite keeps its last measurement
    until it is re-recorded on purpose. Returns why it can't ('' when it
    can): a stale suite the old baseline has no measurement of, or an old
    baseline that can't be read. The run's exit code is not recomputed from
    the carried entries: it reports what this run measured."""
    stale = [r['suite'] for r in report['results'] if r['status'] == 'stale']
    if not stale:
        return ''
    try:
        with open(baseline_file) as f:
            old = {r['suite']: r for r in json.load(f).get('results', [])}
    except FileNotFoundError:
        old = {}
    except (OSError, ValueError, TypeError, AttributeError, KeyError) as e:
        return (f'{", ".join(stale)} is stale and the old baseline {baseline_file} can\'t be '
                f'read to keep its measurement ({type(e).__name__}: {e})')
    missing = [s for s in stale if s not in old or old[s].get('status') not in ('pass', 'fail')]
    if missing:
        return (f'{", ".join(missing)} is stale and the old baseline has no measurement '
                f'of it to keep')
    for i, r in enumerate(report['results']):
        if r['status'] == 'stale':
            report['results'][i] = {**old[r['suite']], 'carried_over': True}
    report['status'] = overall_status(r['status'] for r in report['results'])
    return ''


if __name__ == '__main__':
    sys.exit(main())
