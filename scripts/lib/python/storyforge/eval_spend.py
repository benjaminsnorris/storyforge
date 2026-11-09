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
import os
from datetime import datetime, timezone

LEDGER_ENV = 'STORYFORGE_EVAL_SPEND_LOG'
BUDGET_ENV = 'STORYFORGE_EVAL_BUDGET_USD'
OVERRIDE_ENV = 'STORYFORGE_EVAL_OVER_BUDGET'
DEFAULT_LEDGER = os.path.join('~', '.storyforge', 'eval-spend.jsonl')


class SpendLedgerError(RuntimeError):
    """The ledger exists but a line can't be read, so the month's spend is unknown."""


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
    with no ledger.

    Raises:
        SpendLedgerError: a line isn't a JSON object with a timestamp and a
            number of dollars.
    """
    month = month or current_month()
    if not os.path.isfile(path):
        return 0.0
    total = 0.0
    with open(path, encoding='utf-8') as f:
        for n, line in enumerate(f, 1):
            if not line.strip():
                continue
            try:
                entry = json.loads(line)
                at, usd = entry['at'], entry['usd']
                if not isinstance(at, str) or not isinstance(usd, (int, float)) \
                        or isinstance(usd, bool):
                    raise TypeError('at must be text and usd a number')
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
    with open(path, 'a', encoding='utf-8') as f:
        f.write(json.dumps(entry, sort_keys=True) + '\n')


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
