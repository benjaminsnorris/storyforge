# Storyforge evals

Measures whether Storyforge is reliable, consistent, and accurate. Plan and
suite definitions (E1–E8): `docs/plans/2026-10-28-storyforge-rethink.md`; E9 (extract phase 5's reference completeness): `docs/plans/2026-10-30-extract-upper-layers.md`.
What exists, the baseline, and what's next: `docs/plans/2026-10-28-rethink-status.md`.

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
that suite with `--mode auto`. A prompt that embeds a temp path, date, or id
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
`spread.json`, whose `git_sha` is per suite: E4's runs 2 and 3 are of
d3536986 (#482's gate, one checker reading; replay them from a worktree
at that commit), the other suites' of v1.87.1 (3c01088d). Results and
reading are in the status doc.

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
