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
- **The continuity checks (#648) are code**, tested in
  `tests/test_continuity.py`, not a suite. The gate now reads each scene's
  typed state (one more call), so E4's and E8's gate runs miss on it and stay
  `stale` until Ben re-measures them for recall on KNO, PHY, TIM and WLD
  (three runs, over the monthly budget: his decision).
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

## Private suites: the blocking set (#646)

Some labelled sets are the author's unpublished prose, and this repo is
public. Such a set lives in the private storyforge-evals repo
(benjaminsnorris/storyforge-evals), cloned at `STORYFORGE_PRIVATE_EVALS_DIR`
(default `~/Developer/evals`), and so do its recordings, since a recording
holds the request: `Suite(..., cassettes=fn)` names the directory (`fn`
raises, erroring the suite, when the private repo isn't there; `--cassettes-dir`
doesn't move it). The suite's notes and metrics reach `baseline.json`, so they
carry counts and case ids, never a quote; per-case outcomes and findings go to
the private repo (gitignored there).

`blocking-set` measures today's blocking read (`storyforge.blocking`, #626,
two readings per scene) against 118 known blocking slips (34 that gawain's
readers and Ben found, 10 from gawain's blocking run, 74 from Wrath's last gate
run, each with its fix verdict), 13 readings people judged plausible and left
alone, and 14 clean scenes (`evals/blocking_set`; how each case was found:
`blocking-set/README.md` in storyforge-evals). It reports recall overall, per
category (`recall_hands`, `_posture`, `_sightline`, `_worn`, `_position`,
`_light`, `_other`), per book and per finder (`recall_found_by_readers` is the
independent measure; the `tool` cases were found by the same read), false
alarms per 10,000 words of clean prose, and `left_flagged`. It gates each on
its recorded value (`FLOORS` in the suite, #488). The #647 stage sheet is
measured on the same set before the whole-scene read is retired (plan A4;
`blocking-set-sheet` below). The two suites share `evals/blocking_set/runner.py`.

**Not recorded yet** (forecast about $6.60, past an issue's $5): until then it
errors in replay with a cassette miss. To record: check out the evals PR's
branch (`blocking-set-646`) at `~/Developer/evals`, run
`python3 evals/run.py --mode auto --suite blocking-set`, commit the cassettes
there, then set `FLOORS` from the report and refresh `baseline.json`.

### The stage sheet on the set (#647)

`blocking-set-sheet` runs the stage sheet (`storyforge.stage_sheet`: a small
model records each scene's physical action as transitions, code checks them,
a yes/no question asked twice covers the rest) on the same scenes and scores
it the same way, gating on its own recorded values (`FLOORS` in
`evals/suites/blocking_set_sheet.py`). It also reports `events`,
`questions_asked` and `scenes_with_unchecked` (scenes where something
couldn't be checked; per-scene counts in the private outcomes file). Its
recordings are in `blocking-set/cassettes/blocking-set-sheet/` and its
per-case outcomes in `blocking-set/results/latest-stage-sheet.json`, both in
storyforge-evals (benjaminsnorris/storyforge-evals#78, stacked on #77;
first recorded 2026-11-09 for $0.49 on haiku 5.5, re-recorded after #671's
review fixes for $0.85).

**Side by side:** `python3 evals/run.py --suite blocking-set --suite
blocking-set-sheet`. The read runs first and writes `results/latest.json`;
the sheet's notes then compare the two case by case (caught by both, only
by one, the case ids each alone caught, and left readings flagged). The gate
keeps the read (`gate.GATE_BLOCKING_METHOD = 'read'`) until the sheet's
recall is at least the read's with no more false alarms (plan A4).

The model is the stage sheet's default (the extraction tier);
`STORYFORGE_STAGE_SHEET_MODEL` runs another, which is a different request:
`--mode auto` records it beside the default's, and a replay without the
variable replays the default's.

## The question set (#649)

`question-set` measures the gate's question layer (`storyforge.questions`,
plan A3): narrow yes/no questions from the ledger, each asked twice, a
finding only when both answers say yes and the quote is in the scene. The
cases are *A Christmas Carol* (public domain, the E2 book) and facts Dickens
establishes, written as ledger facts of the types the layer asks about
(`evals/fixtures/question-set/cases.json`): 17 of E2's injected errors that
break a trait, relationship, physical or world fact, the 13 scenes they are
in as Dickens wrote them, and E2's 8 benign rewordings, so 38 scene variants
and 96 questions with known answers (17 `yes`). Each scene is asked about
the same facts in every variant, so a fact that is true of the scene is
asked beside the one an injection breaks. It reports `recall` (a finding
on the injected words), `recall_any` (a finding anywhere in the scene),
`false_alarms` (split into controls, benign edits and the other facts of an
error variant), `split` and `misquoted`, by code, and gates each of
`FLOORS` on its recorded value. It measures the questions, the prompt and
the model; which facts are asked, for whom, is code, tested in
`tests/test_questions.py`.

The model is the layer's default (the extraction tier).
`STORYFORGE_QUESTIONS_MODEL` (or `STORYFORGE_MODEL`) runs another, a
different request: record it with `--cassettes-dir
evals/fixtures/tier-comparison/<model>` so the default's recordings stay
the baseline's. A recording costs cents on haiku.

Recorded 2026-11-09 on haiku 5.5 ($0.04): recall 0.47 (8 of 17; PHY 0.8,
TRT 0.5, REL 0.4, WLD 0.0), no false alarm on 79 questions whose answer is
`no`, 3 split answers. Sonnet 5.5 on the same set (replay it with
`STORYFORGE_MODEL=claude-sonnet-5-5 ... --cassettes-dir
evals/fixtures/tier-comparison/claude-sonnet-5-5`, $0.54) caught one more
(0.53), with no false alarms and no splits, at 13 times the price, so haiku
stays the default. The misses are mostly the prompt's caution (an injected
wrong name read as "a character's mistake", a denial of kinship read as
"self-deprecating") and split answers, not the model. Its `baseline.json`
entry was added by hand from the replay (`--baseline` is refused while E3,
E5 and recheck-set error on this base); the next full `--baseline` rewrites
it the same.

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
