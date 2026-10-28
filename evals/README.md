# Storyforge evals

Measures whether Storyforge is reliable, consistent, and accurate. Plan and
suite definitions (E1–E7): `docs/plans/2026-10-28-storyforge-rethink.md`.

```bash
python3 evals/run.py               # every suite, replaying recorded API calls (free)
python3 evals/run.py --suite NAME  # one suite (repeatable)
python3 evals/run.py --mode auto   # replay what exists, record the rest (spends)
python3 evals/run.py --mode record # re-record every call (spends)
python3 evals/run.py --baseline    # also write evals/baseline.json
python3 evals/run.py --list
```

Exit code: `0` every gate passed, `1` a gate failed, `2` a suite errored (no
measurement). The full report goes to `evals/results/latest.json` (gitignored);
when `evals/baseline.json` exists the report carries per-metric deltas.

## Adding a suite

Create `evals/suites/<name>.py`:

```python
from harness import Gate, Suite, SuiteOutput

def run(ctx):                       # ctx.work_dir is a fresh temp dir
    ...                             # call storyforge in-process, or subprocess with env=ctx.env()
    return SuiteOutput(
        metrics={'recall': 0.82},
        by_code={'PHY': {'recall': 0.9}},          # codes from harness.ERROR_CODES
        gates=[Gate('recall', 0.82, '>=', 0.9)],
    )

SUITE = Suite('e2-detection', 'Contradiction detection on labeled cases', run)
```

## Recorded API calls

Every Anthropic call goes through `api._api_request`, which consults
`storyforge.cassette` when `STORYFORGE_CASSETTE` is set. The harness sets it to
`evals/fixtures/cassettes/<suite>/` for each suite. Replay mode never goes live:
a call with no recording raises `CassetteMiss` and the suite errors. Recordings
are keyed by a hash of the request, so any prompt change is a miss — re-record
that suite with `--mode auto`. The Batch API is refused under a cassette; run
commands in direct mode.

Cost is reported per suite: `usd_spent` (live calls this run) and `usd_if_live`
(what the run would cost without recordings).
