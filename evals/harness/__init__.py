"""Eval harness: suite discovery, cassette wiring, result schema, baseline.

A suite is a module in ``evals/suites/`` exposing ``SUITE = Suite(...)``. Its
``run(ctx)`` returns a ``SuiteOutput``: metrics (with an optional per-error-code
breakdown) and gates. The harness adds provenance, cost, timing, and status,
and the runner turns the set into one JSON report and an exit code — so an
agent can run the suite and read pass/fail without a person.

Status is one of three values, and they are not interchangeable:
``pass`` (every gate held), ``fail`` (the suite ran and a gate did not), and
``error`` (the suite could not produce a measurement). A baseline is refused
over an ``error`` result, because a missing number is not a low one.

A suite is ``error`` — whatever it returned — when it declares no gates (it
measured nothing anyone could fail), or when the cassette logged a failure
during it. The second matters because command code swallows API exceptions
into skipped scenes, so a replay miss can otherwise come back as a confident
number computed over whatever survived.
"""

from __future__ import annotations

import importlib.util
import json
import operator
import os
import subprocess
import sys
import tempfile
import time
import traceback
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Callable, Literal

EVALS_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
REPO_ROOT = os.path.dirname(EVALS_DIR)
PYTHON_LIB = os.path.join(REPO_ROOT, 'scripts', 'lib', 'python')
if PYTHON_LIB not in sys.path:
    sys.path.insert(0, PYTHON_LIB)

SCHEMA_VERSION = 1
ERROR_CODES = ('PHY', 'TIM', 'KNO', 'REL', 'TRT', 'WLD', 'PRM', 'VOI')

Mode = Literal['replay', 'record', 'auto']
Status = Literal['pass', 'fail', 'error']

_OPS = {'>=': operator.ge, '>': operator.gt, '<=': operator.le,
        '<': operator.lt, '==': operator.eq}


@dataclass
class Gate:
    name: str
    actual: float
    op: str
    threshold: float

    def __post_init__(self):
        if self.op not in _OPS:
            raise ValueError(f'gate {self.name!r}: unknown op {self.op!r}')

    @property
    def passed(self) -> bool:
        return _OPS[self.op](self.actual, self.threshold)

    def to_dict(self) -> dict:
        return {'name': self.name, 'actual': self.actual, 'op': self.op,
                'threshold': self.threshold, 'passed': self.passed}


@dataclass
class SuiteOutput:
    metrics: dict[str, float] = field(default_factory=dict)
    by_code: dict[str, dict[str, float]] = field(default_factory=dict)
    gates: list[Gate] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)

    def __post_init__(self):
        unknown = set(self.by_code) - set(ERROR_CODES)
        if unknown:
            raise ValueError(f'unknown error codes in by_code: {sorted(unknown)}')


@dataclass
class SuiteContext:
    name: str
    mode: Mode
    cassette_dir: str
    work_dir: str
    repo_root: str = REPO_ROOT

    def env(self) -> dict[str, str]:
        """Environment for a subprocess that should share this suite's cassette."""
        env = dict(os.environ)
        env['STORYFORGE_CASSETTE'] = self.cassette_dir
        env['STORYFORGE_CASSETTE_MODE'] = self.mode
        return env


@dataclass
class Suite:
    name: str
    description: str
    run: Callable[[SuiteContext], SuiteOutput]


def discover(suites_dir: str) -> list[Suite]:
    """Load every ``SUITE`` from ``suites_dir/*.py``, sorted by name."""
    if not os.path.isdir(suites_dir):
        raise RuntimeError(f'suites directory not found: {suites_dir}')
    suites = []
    for filename in sorted(os.listdir(suites_dir)):
        if not filename.endswith('.py') or filename.startswith('_'):
            continue
        path = os.path.join(suites_dir, filename)
        spec = importlib.util.spec_from_file_location(f'evals_suite_{filename[:-3]}', path)
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        suite = getattr(module, 'SUITE', None)
        if not isinstance(suite, Suite):
            raise RuntimeError(f'{path} defines no SUITE = Suite(...)')
        suites.append(suite)
    names = [s.name for s in suites]
    duplicates = {n for n in names if names.count(n) > 1}
    if duplicates:
        raise RuntimeError(f'duplicate suite names: {sorted(duplicates)}')
    return suites


COST_KEYS = ('calls', 'replayed_calls', 'unpriced_calls', 'input_tokens',
             'output_tokens', 'usd_if_live', 'usd_spent')
_PRICED_FAMILIES = ('opus', 'sonnet', 'haiku')


def _tokens(usage: dict, key: str) -> int:
    value = usage.get(key)
    return value if isinstance(value, int) else 0


def read_cassette_log(log_file: str) -> tuple[dict, list[str]]:
    """Sum the cassette log into cost totals; also return the failures it recorded.

    An unreadable line is itself reported as a failure rather than skipped,
    since it most likely belongs to a call that was then not counted.
    """
    from storyforge.costs import calculate_cost
    totals = dict.fromkeys(COST_KEYS, 0)
    totals['usd_if_live'] = totals['usd_spent'] = 0.0
    failures = []
    if not os.path.isfile(log_file):
        return totals, failures
    with open(log_file) as f:
        for n, line in enumerate(f, 1):
            if not line.strip():
                continue
            try:
                entry = json.loads(line)
            except ValueError:
                failures.append(f'cassette log line {n} is not JSON')
                continue
            if not isinstance(entry, dict):
                failures.append(f'cassette log line {n} is not an object')
                continue
            if 'error' in entry:
                failures.append(str(entry['error']))
                continue
            usage = entry.get('usage') if isinstance(entry.get('usage'), dict) else {}
            model = str(entry.get('model') or '')
            if not any(family in model.lower() for family in _PRICED_FAMILIES):
                totals['unpriced_calls'] += 1  # costs.py would silently price it as sonnet
            usd = calculate_cost(
                model, _tokens(usage, 'input_tokens'), _tokens(usage, 'output_tokens'),
                cache_read=_tokens(usage, 'cache_read_input_tokens'),
                cache_create=_tokens(usage, 'cache_creation_input_tokens'))
            totals['calls'] += 1
            totals['input_tokens'] += _tokens(usage, 'input_tokens')
            totals['output_tokens'] += _tokens(usage, 'output_tokens')
            totals['usd_if_live'] += usd
            if entry.get('replayed'):
                totals['replayed_calls'] += 1
            else:
                totals['usd_spent'] += usd
    totals['usd_if_live'] = round(totals['usd_if_live'], 4)
    totals['usd_spent'] = round(totals['usd_spent'], 4)
    return totals, failures


def provenance() -> dict:
    with open(os.path.join(REPO_ROOT, '.claude-plugin', 'plugin.json')) as f:
        version = json.load(f)['version']
    sha = subprocess.run(['git', 'rev-parse', 'HEAD'], cwd=REPO_ROOT,
                         capture_output=True, text=True)
    dirty = subprocess.run(['git', 'status', '--porcelain'], cwd=REPO_ROOT,
                           capture_output=True, text=True)
    return {
        'storyforge_version': version,
        'git_sha': sha.stdout.strip() if sha.returncode == 0 else 'unknown',
        'git_dirty': bool(dirty.stdout.strip()) if dirty.returncode == 0 else None,
    }


def run_suite(suite: Suite, mode: Mode, cassettes_root: str) -> dict:
    """Run one suite with its cassette active; never raises, except on Ctrl-C."""
    cassette_dir = os.path.join(cassettes_root, suite.name)
    saved = {k: os.environ.get(k) for k in
             ('STORYFORGE_CASSETTE', 'STORYFORGE_CASSETTE_MODE', 'STORYFORGE_CASSETTE_LOG')}
    started = time.time()
    result = {'suite': suite.name, 'description': suite.description, 'mode': mode,
              'started_at': datetime.now(timezone.utc).isoformat(timespec='seconds'),
              'status': 'error', 'metrics': {}, 'by_code': {}, 'gates': [],
              'notes': [], 'error': None}
    with tempfile.TemporaryDirectory(prefix=f'eval-{suite.name}-') as work_dir:
        log_file = os.path.join(work_dir, '.cassette-log.jsonl')
        os.environ['STORYFORGE_CASSETTE'] = cassette_dir
        os.environ['STORYFORGE_CASSETTE_MODE'] = mode
        os.environ['STORYFORGE_CASSETTE_LOG'] = log_file
        try:
            output = suite.run(SuiteContext(suite.name, mode, cassette_dir, work_dir))
            if not isinstance(output, SuiteOutput):
                raise TypeError(f'run() returned {type(output).__name__}, not SuiteOutput')
            result['metrics'] = output.metrics
            result['by_code'] = output.by_code
            result['gates'] = [g.to_dict() for g in output.gates]
            result['notes'] = output.notes
            if not output.gates:
                result['error'] = 'suite declared no gates, so it measured nothing that could fail'
            else:
                result['status'] = 'pass' if all(g.passed for g in output.gates) else 'fail'
        except (Exception, SystemExit) as e:  # a command calling sys.exit must not kill the run
            result['error'] = f'{type(e).__name__}: {e}'
            result['traceback'] = traceback.format_exc()
        finally:
            for key, value in saved.items():
                if value is None:
                    os.environ.pop(key, None)
                else:
                    os.environ[key] = value
        try:
            result['cost'], failures = read_cassette_log(log_file)
        except OSError as e:
            result['cost'], failures = dict.fromkeys(COST_KEYS, 0), [f'cassette log unreadable: {e}']
        if failures:
            result['status'] = 'error'
            result['cassette_failures'] = failures
            result['error'] = result['error'] or (
                f'{len(failures)} cassette failure(s), e.g. {failures[0]}')
        if result['error']:
            result['status'] = 'error'
    result['duration_s'] = round(time.time() - started, 2)
    return result


def run_all(suites: list[Suite], mode: Mode, cassettes_root: str) -> dict:
    results = [run_suite(s, mode, cassettes_root) for s in suites]
    statuses = {r['status'] for r in results}
    overall: Status = 'error' if 'error' in statuses else 'fail' if 'fail' in statuses else 'pass'
    return {
        'schema_version': SCHEMA_VERSION,
        **provenance(),
        'mode': mode,
        'status': overall,
        'suite_count': len(results),
        'cost': {k: round(sum(r['cost'][k] for r in results), 4) for k in COST_KEYS},
        'results': results,
    }


def compare(report: dict, baseline: dict) -> dict[str, dict[str, dict]]:
    """Per suite, per metric: baseline value, current value, delta.

    Covers ``metrics`` and ``by_code`` (as ``CODE.metric``). A metric present
    on only one side is reported with the other side ``None`` rather than
    dropped, so a metric that stopped being emitted is visible. A suite in only
    one of the two runs is listed the same way.
    """
    def flatten(result: dict) -> dict[str, float]:
        flat = dict(result.get('metrics', {}))
        for code, metrics in result.get('by_code', {}).items():
            for name, value in metrics.items():
                flat[f'{code}.{name}'] = value
        return flat

    base_by_suite = {r['suite']: flatten(r) for r in baseline.get('results', [])}
    current_by_suite = {r['suite']: flatten(r) for r in report['results']}
    out = {}
    for suite in sorted(set(current_by_suite) | set(base_by_suite)):
        current = current_by_suite.get(suite, {})
        base = base_by_suite.get(suite, {})
        rows = {}
        for name in sorted(set(current) | set(base)):
            b, c = base.get(name), current.get(name)
            rows[name] = {'baseline': b, 'current': c,
                          'delta': None if b is None or c is None else round(c - b, 6)}
        out[suite] = rows
    return out
