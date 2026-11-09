# Storyforge evals

Measures whether Storyforge is reliable, consistent, and accurate. Plan and
suite definitions (E1–E8): `docs/plans/2026-10-28-storyforge-rethink.md`; E9 (extract phase 5's reference completeness): `docs/plans/2026-10-30-extract-upper-layers.md`.
What exists, the baseline, and what's next: `docs/plans/2026-10-28-rethink-status.md`.

```bash
python3 evals/run.py               # every suite, replaying recorded API calls (free)
python3 evals/run.py --suite NAME  # one suite (repeatable)
python3 evals/run.py --mode auto   # replay what exists, record the rest (spends; frozen suites replay)
python3 evals/run.py --mode record # re-record every call (spends; frozen suites replay)
python3 evals/run.py --mode record --suite e4-generation --runs 3   # re-record a frozen suite, on purpose
python3 evals/run.py --over-budget "Ben approved, #NNN" ...         # spend past the monthly budget
python3 evals/run.py --baseline    # also write evals/baseline.json
python3 evals/run.py --list
```

The full report goes to `evals/results/latest.json` (gitignored); when
`evals/baseline.json` exists the report carries per-metric deltas.

### Exit codes and suite status

Each suite ends in one of four states, and the run's status is its worst
suite's, in this order:

| status | meaning | exit code |
|---|---|---|
| `error` | no measurement: the suite raised, declared no gates, or the cassette logged a failure (a miss on a suite that isn't frozen, a refused live call, an unreadable recording); also a run refused before it started (bad arguments, the budget) | `2` |
| `fail` | the suite measured and a gate didn't hold | `1` |
| `stale` | a **frozen** suite whose only cassette failures are misses: a request changed since it was recorded. No measurement, nothing spent, by policy | `0` |
| `pass` | every gate held | `0` |

**Stale is not a failure.** A prompt change is expected to make E4 and E8
stale, and the run (and CI) stays green on it: a run whose worst suite is
stale reports `status=STALE` and exits `0`. Read the report (or the
`[STALE]` lines and the `stale (frozen, ...)` total line) to see which. A
stale suite has no metrics and no gates in the report, no baseline deltas,
and `--baseline` keeps the old baseline's entry for it (marked
`carried_over`); with no old entry to keep, `--baseline` is refused.

## Policy: what to record, and when (#645)

About $276 went on re-recordings over five rounds, and the end-to-end suites'
claims were mostly within run-to-run noise (E6). The cheap suites with fixed,
labelled inputs (E2, E3, the re-check set) are the ones that found real
things. So (plan `docs/plans/2026-11-08-deterministic-gate-and-voiceprint.md`,
Part E):

- **Fixed labelled sets are the default.** A new suite measures a tool against
  fixed inputs with known answers, so a change in the number is a change in
  the tool. Deterministic checks are code: they get unit tests, not a suite.
- **E4 and E8 are frozen** (`Suite(..., frozen=True)`). `auto` and `record`
  replay them; a miss marks them `stale` and spends nothing. They are
  re-recorded only when a decision depends on them, by name and always as
  three runs: `--mode record --suite e4-generation --runs 3` (run 1 to the
  default cassettes, runs 2 and 3 to `fixtures/e6/run2` and `run3`, so
  `consistency.py` reads the spread). Anything else is refused. At about
  $25 (E4) and $55 (E8) a run, that is past the monthly budget, so it needs
  Ben's approval and `--over-budget`.
- **A new suite that needs live generation for its inputs** (drafted scenes,
  a described voice) records those inputs once, commits them as fixture files,
  and evaluates against the frozen files, so a change to what judges them
  re-records only the cheap part. If the suite itself has to generate end to
  end, mark it `frozen=True`.
- **Monthly budget.** `evals/config.json` sets `monthly_budget_usd` ($25 when
  the file is absent; a file that doesn't give a non-negative number refuses
  the run). Every live call the cassette makes is appended to the eval spend
  ledger (`storyforge.eval_spend`: one JSON line per call with time, suite,
  model and dollars, at `~/.storyforge/eval-spend.jsonl` or
  `$STORYFORGE_EVAL_SPEND_LOG`, outside the repo so every worktree shares
  it). The month is the UTC calendar month. `--mode record` is refused when
  this month's spend plus its forecast (each recorded suite's `usd_if_live`
  in the baseline, times `--runs`) passes the budget; `--mode auto` records
  only misses, so it is refused once the budget is spent. During either, the
  cassette refuses each live call once the month reaches the budget (the
  suite errors with `BudgetRefused`; what was recorded replays free on the
  next `auto`), so at most one call per thread goes past it. A ledger line
  that can't be read refuses too: the month's spend is unknown.
  `--over-budget REASON` is the only override: it is printed as a warning,
  stored in the report's `budget` block, and written on every ledger line the
  run adds. Agents don't pass it without Ben's say-so. Replay never checks
  the budget: it never spends. Spend outside `run.py` (a hand-set
  `STORYFORGE_CASSETTE`, a command run on a real book) isn't in the ledger.

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
# an expensive end-to-end suite: Suite(..., run, frozen=True)  (see the policy above)
```

A gate no run passes says nothing, so a failing suite stops meaning
anything. Gate on what the suite records today (E7's `NOISE_CEILING`, E2's
`e2.FLOORS`: the value must equal it, so a gain moves it in the same commit)
and give the plan's target as a note (#488).

## Recorded API calls

Every Anthropic call goes through `api._api_request`, which consults
`storyforge.cassette` when `STORYFORGE_CASSETTE` is set. The harness sets it to
`evals/fixtures/cassettes/<suite>/` for each suite. Replay mode never goes live:
a call with no recording raises `CassetteMiss` and the suite errors (a frozen
suite is `stale` instead). Recordings are keyed by a hash of the request, so
any prompt change is a miss — re-record that suite with `--mode auto` (a
frozen one only as above). A prompt that embeds a temp path, date, or id
changes every run and can never replay; keep those out of what a suite sends.
The Batch API is refused under a cassette; run commands in direct mode.
In `record` mode a request already recorded earlier in the same run replays
that recording rather than going live again, so two cases that send the same
request (two facts from one scene) see the same reply and stay replayable.
Under a cassette the refusal fallback (`fallbacks`) is stripped from every
request, recording and replay alike, so a recording is always the requested
model's reply or its refusal: evals measure the requested model.

A suite reports `error`, whatever it returned, when the cassette logged any
failure during it (command code often catches API errors and skips the scene,
which would otherwise turn a replay gap into a confident partial number), or
when it declares no gates.

Cost is reported per suite: `usd_spent` (live calls this run) and `usd_if_live`
(what the run would cost without recordings). `unpriced_calls` counts calls
to a model `costs.py` has no price for (they are costed at sonnet rates).

## Run-to-run spread (E6)

`evals/fixtures/e6/run2` and `run3` are two more independent recordings of
the paid suites, beside the default ones (run 1).
`python3 evals/consistency.py` replays all three and writes the per-metric
spread to `evals/e6/spread.json` (and each E8 case's outcome per run to
`evals/e6/e8-cases.json`). Like any recording they replay only while the
requests match, so a prompt change since they were recorded is a miss;
they are not re-recorded on every change (see `evals/e6/__init__.py`).
`--suite NAME` replays one suite and replaces only its entries in
`spread.json`, whose `git_sha` is per suite, the commit each was replayed
at. E4's three runs are of #482's gate (one checker reading): replay them
from a worktree at d3536986, since run 1 has since been re-recorded with two
readings and a replay at a later commit misses (`--suite` then leaves the
file as it was). The other suites' runs 2 and 3 were recorded at v1.87.1
(3c01088d). Results and reading are in the status doc.

## Model-tier comparisons

`evals/fixtures/tier-comparison/<model>/` holds recordings of a suite run with
`STORYFORGE_MODEL=<model>`, kept outside `cassettes/` so the baseline's
recordings stay those of the default routing. To replay one for free:

```bash
STORYFORGE_MODEL=claude-opus-5-5 python3 evals/run.py --suite e3-extraction \
    --cassettes-dir evals/fixtures/tier-comparison/claude-opus-5-5
```

The override also reaches every `select_model` call, so only suites whose
judge uses `model_for_tier` directly (E3 does) compare the work alone.
Results and the decision taken are in `docs/plans/2026-10-28-rethink-status.md`.
