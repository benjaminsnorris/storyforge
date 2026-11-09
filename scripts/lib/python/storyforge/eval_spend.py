"""The eval spend ledger and the monthly eval budget (#645).

Every live call the eval cassette makes (``record`` or ``auto`` mode) is paid
for, and the harness's own cost report lives in a temp dir and
``evals/results/latest.json``, which the next run overwrites. Neither says
what this month has cost. This ledger does: one JSON line per live call,
appended by ``cassette.request`` the moment the reply arrives (before the
recording is saved, so a call that fails to save is still counted), in a
file outside the repo so every worktree and clone on the machine shares it.

- ``STORYFORGE_EVAL_SPEND_LOG``: the ledger file (default
  ``~/.storyforge/eval-spend.jsonl``). The cassette writes to it only when
  this is set; ``evals/run.py`` sets it.
- ``STORYFORGE_EVAL_BUDGET_USD``: the monthly budget. When set, the cassette
  refuses a live call once the month's spend has reached it.
- ``STORYFORGE_EVAL_OVER_BUDGET``: a reason. When set, nothing is refused,
  and every call recorded carries the reason (``run.py --over-budget``).

The month is the UTC calendar month of each line's timestamp. A line that
can't be read is never skipped: what it cost is unknown, so the month's
spend can't be checked and ``month_spend`` raises.
"""

from __future__ import annotations

import json
import math
import os
import re
from datetime import datetime, timezone

LEDGER_ENV = 'STORYFORGE_EVAL_SPEND_LOG'
BUDGET_ENV = 'STORYFORGE_EVAL_BUDGET_USD'
OVERRIDE_ENV = 'STORYFORGE_EVAL_OVER_BUDGET'
DEFAULT_LEDGER = os.path.join('~', '.storyforge', 'eval-spend.jsonl')


class SpendLedgerError(RuntimeError):
    """The ledger exists but can't be read (or a line in it can't), so the
    month's spend is unknown."""


#: The start of the ISO timestamp ``record`` writes: the month is its first 7 characters
_AT = re.compile(r'\d{4}-\d{2}-\d{2}T')


def default_ledger() -> str:
    return os.path.expanduser(os.environ.get(LEDGER_ENV) or DEFAULT_LEDGER)


def current_month(now: datetime | None = None) -> str:
    return (now or datetime.now(timezone.utc)).strftime('%Y-%m')


def _tokens(usage: dict, key: str) -> int:
    value = usage.get(key)
    return value if isinstance(value, int) else 0


def usage_cost(model: str, usage: dict | None) -> float:
    """What one reply cost, from its model and ``usage`` block."""
    from storyforge.costs import calculate_cost
    usage = usage if isinstance(usage, dict) else {}
    return calculate_cost(
        model, _tokens(usage, 'input_tokens'), _tokens(usage, 'output_tokens'),
        cache_read=_tokens(usage, 'cache_read_input_tokens'),
        cache_create=_tokens(usage, 'cache_creation_input_tokens'))


def month_spend(path: str, month: str | None = None) -> float:
    """USD the ledger records for ``month`` (default: this UTC month); 0.0
    when nothing exists at ``path`` yet.

    Raises:
        SpendLedgerError: something exists at ``path`` but can't be read as a
            file (a directory, a dangling symlink, no permission), or a line
            isn't a JSON object with an ISO timestamp and a finite,
            non-negative number of dollars.
    """
    month = month or current_month()
    if not os.path.lexists(path):
        return 0.0
    total = 0.0
    try:
        with open(path, encoding='utf-8') as f:
            lines = f.readlines()
    except (OSError, UnicodeDecodeError) as e:
        raise SpendLedgerError(
            f'the eval spend ledger {path} can\'t be read ({type(e).__name__}: {e}), so '
            f'this month\'s eval spend is unknown.') from e
    for n, line in enumerate(lines, 1):
        if not line.strip():
            continue
        try:
            entry = json.loads(line)
            at, usd = entry['at'], entry['usd']
            if not isinstance(at, str) or not _AT.match(at):
                raise ValueError(f'at {at!r} is not an ISO timestamp')
            if not isinstance(usd, (int, float)) or isinstance(usd, bool) \
                    or not math.isfinite(usd) or usd < 0:
                raise ValueError(f'usd {usd!r} is not a non-negative number of dollars')
        except (ValueError, KeyError, TypeError) as e:
            raise SpendLedgerError(
                f'{path} line {n} can\'t be read ({type(e).__name__}: {e}), so this '
                f'month\'s eval spend is unknown. Fix or remove the line.') from e
        if at.startswith(month):
            total += usd
    return round(total, 4)


def record(path: str, *, suite: str, model: str, usd: float,
           over_budget: str = '') -> None:
    """Append one live call to the ledger."""
    os.makedirs(os.path.dirname(os.path.abspath(path)), exist_ok=True)
    entry = {'at': datetime.now(timezone.utc).isoformat(timespec='seconds'),
             'suite': suite, 'model': model, 'usd': round(usd, 6)}
    if over_budget:
        entry['over_budget'] = over_budget
    with open(path, 'a+b') as f:
        # A last line cut short (a crash mid-write) gets its own line ending,
        # so this entry is never glued onto it and lost with it
        f.seek(0, os.SEEK_END)
        lead = b''
        if f.tell():
            f.seek(-1, os.SEEK_END)
            lead = b'' if f.read(1) == b'\n' else b'\n'
        f.write(lead + (json.dumps(entry, sort_keys=True) + '\n').encode('utf-8'))


def refusal(path: str, budget: float) -> str:
    """Why a live call must not be made now ('' when it may). A ledger that
    can't be read is a refusal: the spend it would check is unknown."""
    try:
        spent = month_spend(path)
    except SpendLedgerError as e:
        return str(e)
    if spent >= budget:
        return (f'the monthly eval budget is spent: ${spent:.2f} of ${budget:.2f} this month '
                f'({path}). Ask Ben, then re-run with --over-budget "<reason>".')
    return ''
