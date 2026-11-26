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
python3 evals/run.py --mode auto --suite gate-set --runs 3   # top a stale frozen suite up
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
| `error` | no measurement: the suite raised, declared no gates, or the cassette logged a failure (a miss on a suite that isn't frozen, a refused live call, an unreadable recording, a frozen suite with no recordings at all); also a run refused before it started (bad arguments, the budget) or a `--baseline` that can't be written (an errored suite, `--suite` given, a stale suite with nothing to carry) | `2` |
| `fail` | the suite measured and a gate didn't hold | `1` |
| `stale` | a **frozen** suite whose only cassette failures are misses: a request changed since it was recorded. No measurement, nothing spent, by policy. An exception the suite raised after the miss is kept as `stale_exception` (with `stale_traceback`) and printed, with the first miss | `0` |
| `pass` | every gate held | `0` |

**Stale is not a failure.** A prompt change is expected to make E4 and E8
stale, and the run (and CI) stays green on it: a run whose worst suite is
stale reports `status=STALE` and exits `0`. Read the report (or the
`[STALE]` lines and the `stale (frozen, ...)` total line) to see which. A
stale suite has no metrics and no gates in the report, no baseline deltas,
and `--baseline` keeps the old baseline's entry for it (marked
`carried_over`); with no old entry to keep, `--baseline` is refused. The
exit code is still what this run measured: a carried-over `fail` doesn't
make it `1`.

## Policy: what to record, and when (#645)

About $276 went on re-recordings over five rounds, and the end-to-end suites'
claims were mostly within run-to-run noise (E6). The cheap suites with fixed,
labelled inputs (E2, E3, the re-check set) are the ones that found real
things. So (plan `docs/plans/2026-11-08-deterministic-gate-and-voiceprint.md`,
Part E):

- **Fixed labelled sets are the default.** A new suite measures a tool against
  fixed inputs with known answers, so a change in the number is a change in
  the tool. Deterministic checks are code: they get unit tests, not a suite.
- **E4 and E8 are frozen** (`Suite(..., frozen=True)`), as are the private sets
  (blocking set, gate set) and `voice-austen`. `auto` and `record`
  replay them; a miss marks them `stale` and spends nothing. They are
  re-recorded only when a decision depends on them, by name and always as
  three runs: `--mode record --suite e4-generation --runs 3` (run 1 to the
  default cassettes, runs 2 and 3 to `fixtures/e6/run2` and `run3`, so
  `consistency.py` reads the spread). A frozen suite gone stale by a
  change downstream of its expensive calls (#713 changed the gate's
  typed-state extraction, after its checker calls) can be **topped up**
  instead: `--mode auto --suite NAME --runs 3` replays every request that
  still matches each run's recording and records only the ones that
  changed (for the gate set, $1.00 of extraction calls instead of about
  $130). A change upstream of the expensive calls changes every later
  request too, so its top-up is close to a full re-record: a top-up is
  forecast and refused as `record` is (spend plus the three runs'
  `usd_if_live` against the budget), and with no figure in the baseline
  the forecast is a lower bound, not a ceiling. It names only frozen
  suites, and refuses a run with no recordings (that would record it in
  full; use `record`). Naming one
  with `--runs` other than 3 is refused, in either mode; `--mode record`
  or `auto` without naming them replays them. At about
  $25 (E4) and $55 (E8) a run, that is past the monthly budget, so it needs
  Ben's approval and `--over-budget`.
- **A new suite that needs live generation for its inputs** (drafted scenes,
  a described voice) records those inputs once, commits them as fixture files,
  and evaluates against the frozen files, so a change to what judges them
  re-records only the cheap part. If the suite itself has to generate end to
  end, mark it `frozen=True`.
- **The continuity checks (#648) are code**, tested in
  `tests/test_continuity.py`; their precision on a real book is measured,
  free, by `typed-state-set` (#744, below). The gate now reads each scene's
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
  in the baseline, times `--runs`) passes the budget. A suite with no
  baseline figure counts as $0 there (named in a WARNING: the forecast is a
  lower bound, and the per-call check below is its guard); a frozen suite
  with no figure, or a baseline that can't be read, refuses `record`
  without `--over-budget`. `--mode auto` records
  only misses, so it is refused once the budget is spent. During either, the
  cassette refuses each live call once the month reaches the budget (the
  suite errors with `BudgetRefused`; what was recorded replays free on the
  next `auto`), so at most one call per thread goes past it. A ledger line
  that can't be read refuses too (so does a ledger path that exists but
  isn't a readable file): the month's spend is unknown.
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
holds the request: `Suite(..., cassettes=fn)` names the directory. `fn(run)`
gets the run's label (`''`, or `run2`, `run3` for `--runs 3`, each recorded
on its own) and raises `harness.SuiteUnavailable` when the private repo isn't
on this machine: the suite is then `stale` with the reason (exit code
unaffected, listed as "unavailable here"), so CI and every public clone stay
green, and `--baseline` keeps the old baseline's measurement of it (or writes
it as unavailable when there is none). `--cassettes-dir` doesn't move a
private suite's recordings, and while it runs a cassette miss withholds the
prompt's opening. The suite's notes and metrics reach `baseline.json`, so
they carry counts and case ids, never a quote; per-case outcomes and findings
go to the private repo (gitignored there).

`blocking-set` measures today's blocking read (`storyforge.blocking`, #626,
two readings per scene) against 118 known blocking slips (34 that gawain's
readers and Ben found, 10 from gawain's blocking run, 74 from Wrath's last gate
run, each with its fix verdict), 13 readings people judged plausible and left
alone, and 14 clean scenes (`evals/blocking_set`; how each case was found:
`blocking-set/README.md` in storyforge-evals). It reports recall overall, per
category (`recall_hands`, `_posture`, `_sightline`, `_worn`, `_position`,
`_light`, `_other`), per book (`recall_book_gawain`, `_wrath`) and per finder
(`recall_found_by_readers` is the independent measure; the `tool` cases were
found by the same read), false alarms per 10,000 words of clean prose, and
`left_flagged` (left readings a verified finding lands on). Each of those is
gated on its recorded value (`FLOORS` in the suite, #488); `unlabelled_flags`
and the counts are reported, not gated. A finding catches at most one case,
matched by place (whole words, a `...` quote's parts in order), so a short or
shared line can't inflate recall. The clean scenes are all gawain's (no Wrath
scene has had a human read), so the false-alarm rate is one book's. The #647
stage sheet is measured on the same set before the whole-scene read is
retired (plan A4;
`blocking-set-sheet` below). The two suites share `evals/blocking_set/runner.py`.

The suite is **frozen** (#645): `auto` and `record` replay it, and a miss is
`stale`. **Recorded 2026-11-09** as three runs ($20.31, Ben's approval over
the monthly budget): `cassettes/blocking-set/` and `cassettes/run2/`,
`run3/` beside the set, with run 1's per-case outcomes frozen in
`baseline-cases.json` there (storyforge-evals `blocking-set-baseline`).
`FLOORS` hold run 1's values. Over the three runs:

| metric | run 1 | run 2 | run 3 |
|---|---|---|---|
| recall (117 in-scene slips; the 118th needs other scenes) | 0.615 | 0.650 | 0.650 |
| recall, slips people found (34) | 0.324 | 0.382 | 0.412 |
| recall, slips a read found (83) | 0.735 | 0.759 | 0.747 |
| false alarms per 10k clean words | 1.27 | 1.27 | 0.85 |
| flags | 99 | 101 | 96 |

The small categories (6 to 12 cases each) move most between runs:
sightline 0.33 / 0.67 / 0.75, other 0.58 / 0.92 / 0.83, posture 0.91 / 0.55
/ 0.82, light 0.33 / 0.50 / 0.17. The stage sheet's recall of 0.22 and 15.65
false alarms per 10k (its `FLOORS` in `evals/suites/blocking_set_sheet.py`)
are far from the read's, so the read stays the gate's default.

`RECORDED` in each suite pins the set (`blocking_set.fingerprint`: the
labels and every scene) and the number of recordings the floors were
measured on. A different set errors; a replay with fewer recordings (the
private repo on a branch without them) is unavailable and says which
checkout to use, rather than reading the misses as a changed request.

To re-record (only when a decision depends on it):
`python3 evals/run.py --mode record --suite blocking-set --runs 3`, then
replay run 1, copy the private `results/latest.json` to
`baseline-cases.json`, and set `FLOORS` and `RECORDED` from the report and
`blocking_set.fingerprint` / `.recordings`.

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
recorded on purpose beside the default's, and a replay without the
variable replays the default's.

Like `blocking-set`, the suite is **frozen** (#645; `auto` and `record`
replay it, a miss is `stale`, recording takes `--mode record --suite
blocking-set-sheet --runs 3`), and without the private checkout it is
`stale` (unavailable), not an error. Its harness (`check_all`,
`floor_gates`, the outcomes file) is `blocking-set`'s, in
`evals/blocking_set/runner.py`, so the two suites score, match and gate
identically. The recordings so far are the main run only (made before the
suite was frozen).

## The gate set (#677)

Decision 5 removes the open checker once the typed checks (#648) and the
question layer (#649) match its recall on the frozen E4 and E8. Re-recording
those (about $240) mostly redrafts prose. The gate set measures the gate
alone on prose E8 already recorded and judged: every past E8 recording's
judge calls (the main cassettes and E6's runs 2 and 3) hold a replayed
scene and a verdict on one known error, an E1 `tool-introduced` case.

- **Built for free** by `python3 evals/gate_set/build.py`, which finds each
  judge call's case by its prompt (`e8.judge_prompt` around the scene) and
  writes the set to the private storyforge-evals repo (`gate-set/`, private
  like the blocking set: the prose is the corpus books'). A judge call no
  case frames, or a verdict that won't parse, stops the build. Data-family
  judge calls aren't gated, so they're left out.
- **Roles.** A `reintroduced` replay whose evidence sentence falls at
  exactly one place in its prose is a `positive`. Each positive pairs with
  at most one `consistent` replay of the same case (its evidence also at one
  place): a `control`, so there are fewer controls than positives. The rest
  are `spare`: `not_present` replays, paraphrased or repeated evidence, and
  every replay of a case in `e8.EXCLUDED_CASES` (E8 doesn't replay those;
  for most, the pre-pass book already has the error). `validate` checks the
  stored roles against this rule. Built 2026-11-09: 351 items, 46 positives
  over 15 cases (TRT 20, TIM 14, PHY 8, KNO 3, REL 1; no WLD), 31 controls.
- **Measured.** Each run item's pre-pass book is materialized
  (`e8.prepare`, so the corpus books must be cloned as for E8), the prose
  written in and gated once (`gate.gate_scene`, no fix loop, `before` the
  book before it). `recall`: positives with a blocking verified finding
  whose quote overlaps the evidence sentence's place (as the blocking set
  matches; a broken promise has no quote, so it can't catch);
  `recall_per_case` weighs each case the same, since positives cluster
  (the most has 6); `stop_rate_positive` is E8's own measure (not passed,
  for any reason); `false_alarm_on_fact` counts controls with a finding on
  their correct statement of the fact. A stop for another reason isn't
  scored: the label covers one error.
- **Two suites**: `gate-set` (the open checker, today's default) and
  `gate-set-questions` (`check --questions`), each with its own recordings
  under `gate-set/cassettes/` and outcomes in `gate-set/results/`.
- **Recorded 2026-11-16** (three runs each, with Ben's approval and
  `--over-budget`: about $43 a run for `gate-set`, $12 for
  `gate-set-questions`, seeded with each case's fact, #723). `gate-set` was
  topped up after #713 changed the typed-state extraction ($1.00), and
  `gate-set-questions` after a name written surname first ("Erdel, Tam")
  started to count as present (2026-11-17, $0.02). `FLOORS`
  are run 1's, so missing recordings are the harness's error (a misplaced
  directory). Before a suite's first recording a replay is `stale`
  (unavailable, "not recorded yet", with the record command).
- **Fails loudly.** A gate that can't finish an item counts as a stop and
  is named in the notes, but if it finishes none the suite errors; the
  question layer without the typed state errors up front; a cassette miss
  during a run errors before any outcome is written. Each recorded run
  overwrites the private `results/` file.
- **Labels.** E8's judge is one Opus reading, tied to a known error, so
  these labels are firmer than E4's (an Opus judge against an Opus checker).
  The E4 half (shared-dark Act 1 drafts gated in order) is a follow-up.

## The typed-state set (#744)

`typed-state-set` replays the gate's typed-state checks (possession,
injury, life, time, travel, knowledge, names, sky: `storyforge.continuity`)
on *Wrath Like Smoke*'s overnight gate run of 2026-11-16/17 and scores
every finding against the checker review's verdict
(`docs/plans/2026-11-26-checker-review/`, report A section 2: real,
debatable or false). It measures the checks before and after a change to
them (#732 possession, #733 injury and life), at no cost in any mode.

- **A run** is one scene's gate run: the book's repo at the commit before
  the scene's (what the gate read), with the scene's prose, stage sheet and
  typed state from its own commit, run through `continuity.check_continuity`
  with the extraction call answered from the saved typed state
  (`typed_state_set.replay`). Everything but the model's reply is today's
  code, so a change to the checks needs nothing re-recorded; a change to
  what extraction returns (#748) needs new replies.
- **Which runs.** The book commits each scene once, so the set holds each
  scene's final gate run: 43 runs (`aphrodite-drives-helen-to-bed` is left
  out: its saved state is of a fix the gate discarded). The other 57 runs'
  replies are only in the gate logs (gitignored), so 17 of the review's 65
  typed-state verdicts are on a run in the set: 14 possession, 2 injury, 1
  life. `set.json` lists every run left out and why.
- **Reports**, per check and overall: `findings`, `_false`, `_debatable`,
  `_real` (labelled findings by verdict), `_unlabelled` (a finding no label
  covers: a new kind, to read in the private results), `_precision` (real
  over findings, when there are any), `real_missed` and `cleared` (labels no
  finding is on any more). Gated on today's values (`FLOORS`, exact, #488):
  a fall in a findings, false or unlabelled count is a gain to move the
  floor to in the same commit.
- **Baseline, 2026-11-26 (main at 1.191.0, before #732 and #733):** 17
  findings, all labelled: possession 14 (all false), injury 2 (1 false, 1
  debatable), life 1 (false); precision 0. `cleared` 0.
- **With #732 (1.192.2):** 3 findings: possession 0 (14 false cleared;
  owner-scoped objects, and an unowned name held again by its loser in a
  later scene is a note: Agamemnon's and Ares's spears), injury and life
  unchanged. Nothing real lost, nothing unlabelled.
- **Not measured.** Recall: the only real typed-state catch (a time
  finding, Q80) is on a first run. Seeded errors in clean scenes (a wrong
  holder, a dead man acting, a healed wound) are the follow-up that
  measures it. The names check runs without the book's name map (it lives
  in another repo, `../homer`), and says so in every run's notes.
- **Private**, like the blocking set: the set (`typed-state-set/` in
  storyforge-evals, with its files stored once each, gzipped, by hash) and
  the per-run results stay there; notes carry label ids, scene ids and
  counts. `RECORDED_SET` in the suite pins the set's fingerprint. Rebuild
  with `python3 evals/typed_state_set/build.py --book-repo
  ~/Developer/iliad-adult` (free; it reads the branch
  `storyforge/write-20261116-2234` and report A).

## The question set (#649)

`question-set` measures the gate's question layer (`storyforge.questions`,
plan A3): narrow yes/no questions from the ledger, each asked twice (a
third time when the two split), a finding on two yeses with the quote in the
scene. The
cases are *A Christmas Carol* (public domain, the E2 book) and facts Dickens
establishes, written as ledger facts of the types the layer asks about
(`evals/fixtures/question-set/cases.json`): 17 of E2's injected errors that
break a trait, relationship, physical or world fact, the 13 scenes they are
in as Dickens wrote them, and E2's 8 benign rewordings, so 38 scene variants
and 96 questions with known answers (17 `yes`). Each scene is asked about
the same facts in every variant, so a fact that is true of the scene is
asked beside the one an injection breaks. It reports `recall` (a finding
on the injected words), `recall_any` (a finding on the broken fact, quoting
anywhere in the scene), `false_alarms` (broken down into controls, benign
edits and the other facts of an error variant), `split` and `misquoted`, by
code (3 to 6 cases a code: too few to compare codes), and gates each of
`FLOORS` on its recorded value.

`recall` asks every labelled fact, so it measures the questions, the prompt
and the model. The gate asks only what its selection picks, so the suite
also runs that selection on each variant, free (#673's review): each
scene's labelled `cast` (who a perfect typed state would put there) as `at`
records, its scenes.csv locations and the registry names in its prose,
through `questions.present_subjects` and `facts_to_ask`.
`selection_lost` counts the `yes` facts the gate would not ask (1:
qs-018, Belle's scene never names Marley) and `recall_selected` the
recall the gate would get (caught and selected). The brief's promise
questions and disputes have no cases yet.

The model is the layer's default (the extraction tier).
`STORYFORGE_QUESTIONS_MODEL` (or `STORYFORGE_MODEL`) runs another, a
different request: record it with `--cassettes-dir
evals/fixtures/tier-comparison/<model>` so the default's recordings stay
the baseline's. A recording costs cents on haiku.

**Recorded 2026-11-16 on haiku 5.5 (about $0.05): recall 0.76 (13 of 17), no
false alarm; a second recording gave the same.** Three questions split
(the qs-016, qs-033 and qs-035 variants): the third asking made qs-016's
salary a finding (`tie_found` 1), and the other two split, then no. Two
changes did it, from the misses' own reasons: the prompt counts dialogue
and a character's memory as the book's word unless the scene itself shows
it wrong (a wrong name, kinship, place or past in a character's mouth was
read as "a character's mistake"), and checks every clause, since agreement
elsewhere in the scene was cancelling a contradiction in one sentence
("When in doubt, no" is gone); and a question the two askings split on is
asked a third time, two yeses of three a finding (three of the first
version's misses were splits). Still missed: qs-009 (a "heavy, sturdy boy"
against Tiny Tim's crutch, an inference), qs-018 (asked, and answered no:
the scene never names Marley; the gate's selection wouldn't ask it either),
qs-033 (the niece smiling at the unseen Scrooge) and qs-035 (Islington as
where the turkey goes, not said to be their home); the last two split. The
scorer's `lands_on` now takes a quote shorter than `SHARED_RUN` when it
holds every word the injection changed (`changed_words`; `validate` refuses
an error case whose injection changes none): an earlier try's qs-013
finding quoted only `"Frank!"` and was scored a miss. In the committed
recording every catch quotes three words or more, so the old scorer gives
the same 0.76. A first try put one case's words in the prompt as an
example (15 of 17); it was taken out, since a prompt fitted to its test set
says nothing about other books. 17 cases is a small set, tuned on: the gate set
(#677) is the check on prose it hasn't seen. The tier-comparison recording
below (sonnet) is of the 2026-11-09 prompt: a replay of it now errors on its
first call (a cassette miss) until it is re-recorded.

Recorded 2026-11-09 on haiku 5.5 ($0.04): recall 0.47 (8 of 17; PHY 0.8,
TRT 0.5, REL 0.4, WLD 0.0), no false alarm on 79 questions whose answer is
`no`, 3 split answers. Sonnet 5.5 on the same set (replay it with
`STORYFORGE_MODEL=claude-sonnet-5-5 ... --cassettes-dir
evals/fixtures/tier-comparison/claude-sonnet-5-5`, $0.54) caught one more
(0.53), with no false alarms and no splits, at 13 times the price, so haiku
stays the default. The misses are mostly the prompt's caution (an injected
wrong name read as "a character's mistake", a denial of kinship read as
"self-deprecating") and split answers, not the model. The open checker's
"about 12 of 17" (`e2-carol-checker`) is scored by scene, any code, any
words, from one opus reading per edited scene (the gate makes two); the
layer's 8 count only a finding on the injected words. Two cases only the
layer caught (qs-017, qs-021), so the two together caught 14. Its
`baseline.json` entry was added by hand from the replay (`--baseline` is refused while E3,
E5 and recheck-set error on this base); the next full `--baseline` rewrites
it the same.

## Converting a bible essay (#702)

`bibles-convert` measures `storyforge bibles convert` (`storyforge.bibles_convert`:
one structured call turns a character, world or systems bible essay into
fact rows, the lines it quotes and terse notes) on a labelled set:
`fixtures/bibles-convert/`, an invented book (*The Salt Ledger*) written for
the suite, so no real prose is in it. Its three essays are shaped like the
essays the elaborate stages wrote before #657, interpretation and
descriptions of speech included. `labels.json` gives, per essay, the facts
it settles (keyword groups a row's statement must hold, the type and subject
a right row has, which are secrets and which are open questions), its
interpretation (traps), the lines it quotes, its descriptions of speech, and
what resists rows. The suite reports `fact_recall`, `type_accuracy`,
`subject_accuracy`, `secrets_kept`, `open_kept`, `interpretation_rows` and
`interpretation_notes` (drafting reads bible-notes.md whole, so a note leaks
as a row does), `speech_descriptions` (a description of speech kept as a
fact or note), `voice_recall`, `description_as_voice`, `invented_lines`
(lines the reply gave that the essay doesn't quote: code leaves them out)
and `note_recall`, each gated on its recorded value (`FLOORS`, #488); how a
run compares with the bar for importing unread (`TRUST_BAR`) is a note.

**Recorded 2026-11-15** on sonnet 5.5, the command's default (`MODEL_TASK`,
the evaluation tier), for $0.07: every one of 49 labelled facts found,
type right on 48, subject right on 28 of 29 scored, both secrets as
knowledge rows, both open questions as `?` rows, every quoted line kept and
none invented, no interpretation and no description of speech in a row or
a note; one of the two notes came back as a world fact (`note_recall`
0.5). A first recording ($0.07), before the prompt said interpretation and
descriptions of speech aren't notes or facts either, put the essay's arc,
POV plan and "mirror" framing in two notes and four descriptions of speech
in trait rows; the prompt and a code rule (`SPEECH_CATEGORIES`) changed for
it, and the scoring then counted notes too. Four labels were corrected
after that first reading, each a matcher fault, never a widened answer: a
combined ferry fact a `without` word excluded, "the next" for "the next
night", a relationship's subject as either side, and a world fact's subject
left unscored. Three essays are a small set: it shows the prompt's rules
hold on essays shaped like the old stages', not how a long real bible
converts, which is why `convert` writes rows for review by default.

Not frozen (three cheap calls): a change to the prompt or schema is a
recording miss, re-recorded with `--mode auto --suite bibles-convert`.
With `FLOORS` unset and no recordings, a replay is unavailable (`stale`),
not an error.

## Writing in the voice (#654)

`voice-austen` is the Austen reference voiceprint's test 6 (plan B7): can
`write`, given her voice, write a scene that sounds like her? The fixture
book (`evals/fixtures/voice-austen/`) is an original one-scene comedy of
manners (a card party in a country town about 1810, about 2,000 words, none
of her characters or events) whose `voice:` block names
`references/voiceprints/austen`, so the drafting prompt carries her
description and exemplars (all from *Pride and Prejudice*). The scene is
drafted as `write` drafts it in direct mode (its default, not `--session`):
the shared context plus `cmd_write._build_prompt`, the reply held to
`write`'s checks, no gate and no refusal fallback. Then:

- **the meter** (free) compares the draft with her fingerprint and with the
  seven other authors' of the reference tests: `meter_rank` (1: she is
  nearest), `meter_distance_austen`, `meter_margin` (nearest other minus
  hers), and `austen_held_out_median` (her own held-out chunks' distance,
  for scale). Her fingerprint is the whole of *Pride and Prejudice*, each
  other author's ten chunks, which favours her a little;
- **the judge** (Opus) reads the draft beside four unlabelled samples of
  about 500 words, Austen (*Persuasion*, held out), Brunton (*Self-Control*),
  Eliot (*Middlemarch*) and Dickens (*A Christmas Carol*), every name in them
  replaced by an invented one, and names whose voice it is, four times, the
  order turned so each sample sits in each place once: `judge_austen`.

It is **frozen**; the gates hold run 1's values (rank 2, judge 4 of 4) and
the plan's target (rank 1, judge naming her) is in the notes. **Recorded
2026-11-15** as three runs, $0.87 (Ben's approval over the monthly budget):

| | run 1 | run 2 | run 3 |
|---|---|---|---|
| words | 1417 | 1462 | 1856 |
| meter: Austen's place among eight | 2 (Dickens nearer) | 2 (Brunton nearer) | 1 |
| her distance | 0.890 | 0.858 | 0.717 |
| margin (nearest other minus hers) | -0.054 | -0.081 | 0.083 |
| judge named her | 4 of 4 | 4 of 4 | 4 of 4 |

**The meter misses the plan's target in two runs of three.** An earlier
recording the same day (judge shown the samples' real names, since
replaced; same drafting prompt) put her first in all three runs, by 0.018
to 0.069, so over six drafts she is nearest in four, and never by much.
Every draft is further from her than any of her own held-out chunks (median
0.462, furthest 0.630). The measures furthest from her are function words
(more *a*, *at*, *very*, *over*, fewer *any* than she uses); the leaders
change from draft to draft.

**Length doesn't explain the misses.** The two that missed are the short
drafts (about 1,450 words), but the meter tells her own prose apart at that
length. Cut into chunks of each size, *Emma* and *Persuasion* rank her
nearest of the eight:

| chunk | chunks | her place 1 | median margin |
|---|---|---|---|
| 1,000 words | 225 | 98% | 0.231 |
| 1,450 words | 159 | 99% | 0.258 |
| 2,000 words | 116 | 100% | 0.293 |

Her own prose leads by about 0.26 at the drafts' length; the drafts led by
-0.08 to +0.08. A 2,000-word draft would gain about 0.03, so the misses are
the drafts, not the meter.

**The judge names her every time**, but it isn't blind: with the names
replaced it still says Austen's sample "is in fact from *Persuasion*" (and,
once, names "Mary and Charles Musgrove", which are not in the sample: it
knows the book), and its reasons lean on the Regency drawing room, which
only her sample and Brunton's share.

### The control (`voice-austen-control`)

The same scene drafted with the same request less the voice: the fixture's
`voice:` block is cut, so the shared context has no description and no
exemplars, and everything else is byte for byte what `voice-austen` sends
(a test checks it). `write` itself won't send it (it refuses a book with no
voice), and its prompt still says "Write toward the voice's passages", with
none to write toward. Frozen; the gates hold run 1's values in the
direction of the comparison (`meter_rank >= 8`, `judge_austen <= 4`).
**Recorded 2026-11-15** as three runs, $1.17 (Ben's approval over the
monthly budget):

| | run 1 | run 2 | run 3 |
|---|---|---|---|
| words | 1930 | 1739 | 1782 |
| meter: Austen's place among eight | 8 | 7 | 6 |
| nearest | Gatsby | Brimming Cup | Brimming Cup |
| her distance | 1.019 | 1.039 | 0.966 |
| margin | -0.254 | -0.266 | -0.195 |
| judge named her | 4 of 4 | 4 of 4 | 4 of 4 |

**The exemplars move the meter a long way; the judge doesn't see it.**
With the voice, her distance is 0.72 to 0.89 and she is first or second;
without it, 0.97 to 1.04 and sixth to last, nearest the twentieth-century
Americans. The judge names her 4 of 4 either way, so in this suite it
measures the setting and the comedy of manners, not the voice: test 6's
judge half doesn't tell a voiced draft from one with none. The meter is the
half that does, and it says the exemplars get the drafts most of the way
to her, not all of it.

To re-record (only when a decision depends on it):
`python3 evals/run.py --mode record --suite voice-austen --runs 3` (or
`--suite voice-austen-control`), then set `RECORDED_RANK` and
`RECORDED_JUDGE` in that suite from run 1. `evals/consistency.py` doesn't
read them (E6's suites only): the tables above are the spread.

## Recorded API calls

Every Anthropic call goes through `api._api_request`, which consults
`storyforge.cassette` when `STORYFORGE_CASSETTE` is set. The harness sets it to
`evals/fixtures/cassettes/<suite>/` for each suite. Replay mode never goes live:
a call with no recording raises `CassetteMiss` and the suite errors (a frozen
suite is `stale` instead). Recordings are keyed by a hash of the request as
the model reads it (`cassette.normal_body`: `cache_control` left out wherever
it sits, adjacent text blocks joined, #741), so any prompt change is a miss —
re-record that suite with `--mode auto` (a frozen one only as above) — but a
change to where a request is cached, or for how long, is not. Each cassette
directory names its key scheme in `KEY_SCHEME`; a directory without it holds
recordings keyed by the raw body, and the harness renames them before the
suite runs (free; the suite's notes say how many, for the repo that holds
them to commit). By hand: `python3 -m storyforge.cassette rekey DIR...` from
`scripts/lib/python`. A prompt that embeds a temp path, date, or id
changes every run and can never replay; keep those out of what a suite sends.
The Batch API is refused under a cassette; run commands in direct mode.
In `record` mode a request already recorded earlier in the same run replays
that recording rather than going live again, so two cases that send the same
request (two facts from one scene) see the same reply and stay replayable.
Under a cassette the refusal fallback (`fallbacks`) is stripped from every
request, recording and replay alike, so a recording is always the requested
model's reply or its refusal: evals measure the requested model.

A test can read a committed recording directly too: the Austen voice
description and exemplar shortlist (#651) are frozen in
`tests/fixtures/voiceprint/cassette/`, and `tests/test_voiceprint_description.py`
parses their replies against the recorded sample rather than replaying the
request (see `references/voiceprints/README.md`).

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
