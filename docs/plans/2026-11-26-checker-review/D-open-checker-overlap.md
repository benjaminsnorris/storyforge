# Report D: the open checker, and how the two checkers overlap item by item

Research agent report, 2026-11-26. Read-only; free replays of the recorded evals and a reading of *Wrath Like Smoke*'s gate logs. No model calls.

## Summary

**Per-item overlap** (measured; my replays reproduce the published figures exactly):

| | Recall of 46 | False alarms on the fact | Control stops |
|---|---|---|---|
| Open, 2 readings | 0.543 (23–26) | 3.7 | 0.74 |
| Questions | 0.391 (17–19) | 1.3 | 0.55 |
| Union | 0.630 (26–31) | 5.0 | 0.77 |
| Intersection | 0.304 (13–15) | 0 | n/a |
| Open, 1 reading | 0.475 (19–25) | 3.0 | 0.73 |
| Questions + 1 open reading | 0.598 (24–30) | 4.3 | 0.75 |

- Same-index runs: both 14, open-only 9–12, questions-only 3–5, neither 15–20.
- 15 positives are never caught by either; 4 have nothing in the book to check against and 10 are soft.
- Most open-only catches are on facts the question layer asked and answered no.

**False alarms are real errors.** All five flagged controls, and about 38 of 42 control findings in run 1, are contradictions with another scene on a different fact. I judged these from the quotes, not the books. A Haiku verify pass has little to kill here: 4 of 964 findings fail the quote check.

**Control stops are mostly shared layers** (measured). They stop 12–17 of 31 controls alone, the blocking read 10–15 of those. The open checker is sole blocker on 7–10, questions on 0–2.

**Live cost findings** (measured in Wrath's logs):
- The checker layer costs $0.49–0.53 per gate run; a reading takes a median 17 s.
- About 60% of a reading is re-writing a ~33k-token user message, mostly character sheets, to the cache.
- Switching between the two output schemas caused 14 of 18 full cache misses inside the 5-minute window.
- In 37 rechecks, 6 new findings were reading variance and 2 were fix-introduced.

**Hybrid estimates** (recall measured by join; cost estimated from token counts, checker layer per gate run):

| Design | Recall | Cost as is | With caching fixes |
|---|---|---|---|
| Tandem, 2 readings | 0.63 | $0.51 | ~$0.34 |
| (i) Questions + 1 Opus reading | 0.60 | $0.25–0.35 | $0.10–0.26 |
| (ii) Open on first run only | 0.63 first run | ~$22 for the rest of the book | ~$13 with one reading |
| (iii) Generator + Haiku filter | 0.30 to 0.63 | open cost + $0.01 | |
| (iv) Open only where not asked | ≤0.49 | ~$0.20 | $0.05–0.10 |

- Tandem and one reading are pure code. One reading's eval is already in the recordings.
- Sonnet has no recorded data; three runs would cost about $60.
- (iv) is a full re-record, about $130.
- The question half of every figure assumes seeded facts; unseeded it scored 0.02–0.04.

**Batch API:** used by enrich, evaluate, elaborate, extract and brief-writing, never by the gate. A warm cache (95% off the prefix) beats batch (50%) for this workload.

**Risk for the remaining book:** it is at 86,685 words and `FULL_MAX_WORDS` is 100,000. In about 8 scenes the open checker drops to window mode, which no recording measures.

**Confidence:** high on overlap, layer attribution and cache behaviour; medium on cost projections; low on (iii) and Sonnet.

**Two problems to pass on:**
- The scratchpad is shared. My `pkill -f replay.py` may have killed another agent's replay processes; its `replay_all.log` may be missing a scene or two.
- My first replay filled the disk (about 29 GB) for roughly three minutes around 11:44–11:47 before I deleted the copies.

Scripts and data are in `scratchpad/D/`; per-item data is `out/per-item.json` there.

Paths below are relative to `~/Developer/storyforge/scripts/lib/python/storyforge/` unless they start with `/` or `~`.

## What was measured and how

- **Recorded evals.** I replayed `gate-set` and `gate-set-questions`, three runs each, with a driver that calls `gate_set.runner.gate_one` under `STORYFORGE_CASSETTE_MODE=replay`. It dumps every finding, each reading's result and each call's token usage. The recordings are on `~/Developer/evals` main (the `gate-set-recording-677` branch is merged).
- **Check against published numbers.** Open 26/23/26 of 46, false alarms 5/3/3, control stops 23/22/24 of 31. Questions 19/17/18, false alarms 1/2/1, control stops 15/19/17. All match.
- **Live logs.** 312 open-checker calls in `~/Developer/iliad-adult/working/logs/gate/` (Nov 8 pipeline draft, Nov 15–16 sessions), all `claude-opus-5-5`.
- **Not available.** No Sonnet recording of the open checker exists (all 462 recorded readings and all 312 live calls are Opus). E4 and E8 are stale and were not replayed. The 17-case set has only its published totals.

## 1. How the open checker works

### The request

| Part | What it holds | Where |
|---|---|---|
| System block 1 | Bibles, bible rows and series canon, whole and uncapped; 5-minute cache breakpoint | `checker.py:398-411`, `reference_docs` `:347-395` |
| System blocks 2..n | "THE STORY SO FAR": one block per earlier scene, verbatim, with its `when`; 5-minute breakpoint on the last | `checker.py:412-418` |
| User message | Scene prose, brief, **series character sheets for the cast**, disputes, the full scene list with calendar, instructions, and a reading note for reading 2+ | `build_prompt` `checker.py:777-817`, `_sheets_text` `:750-756` |
| Tools | `search_manuscript`, `read_scene`, `query_ledger`, sent strict | `checker.py:614-640` |
| Output | `SCHEMA` (`findings`, `kept`), or `DISPUTE_SCHEMA` (adds `cleared`) only when extraction raised disputes | `checker.py:121-156`, chosen at `:948` |
| Limits | `max_tokens=8000` plus a 16,000 thinking allowance; `MAX_TURNS=24` | `checker.py:946`, `api.py:37` |

- **Story so far.** `prompts.prior_scenes(..., 'full')` sends every earlier scene until the earlier prose passes `FULL_MAX_WORDS = 100_000` (`prompts.py:2320`, `:2348-2382`). Past it the checker gets the window: the preceding scene and the latest scene of each MICE thread (`checker.py:481-489`).
- **Model.** `select_model('checking')` is the Opus tier (`common.py:1149`). `STORYFORGE_MODEL` overrides everything; `gate_scene(check_model=)` overrides just this call.
- **Sizes.** In the corpus recordings the first request is 92k–137k tokens (lantern-folk 24k), of which the user message is about 8k. In Wrath the reference block is about 18k tokens, the story so far about 155k now, and the user message about 33k. The sheets are roughly two thirds of that (7–11 sheets a scene).

### Readings, merging and verification

- **Two readings** (`GATE_READINGS = 2`, `checker.py:896`), run one after the other (`:923-929`). Reading 2 is the same request with one sentence appended (`_reading_note`, `:772-774`).
- **The merge is a union** (`merge_readings`, `:1053-1115`). Two findings are one when they share code, source and overlapping quotes (`_same_finding`, `:1035-1042`).
- **Verification is quote matching only** (`_verify`, `:824-883`). The scene quote must be in the scene; the established quote must be in the scene, file, calendar line or brief item it names. A finding that fails is `unverified` and still blocks. Nothing adjudicates whether the two quotes actually contradict.
- **Measured.** 960 verified findings against 4 unverified across all recorded readings. 66% of reading 1's contradiction findings recur in reading 2 (259 of 392). Readings average 2.65 tool calls; 7% use none.
- **What findings cite** (recorded): another scene 585, the calendar 189, a brief promise 171, a reference file 8, a bare ledger fact 7.

### Caching today

| Between | Behaviour | Evidence |
|---|---|---|
| Reading 1 and reading 2 | System prefix is read from cache; the **whole user message is written again**, because it is one block and the reading note changes its end | Recorded: reading 2 reads 125,831 and writes 8,111. Wrath: reads 47,878, writes 33,276 |
| A gate run and its rechecks | The same, when inside 5 minutes; changed prose rewrites the user message | Wrath Nov 8: all 35 recheck first readings hit the system prefix |
| One scene and the next | The breakpoint moves to the new last scene; the earlier prefix is read if still warm | Wrath Nov 8: 82 of 95 first readings hit or extended |
| A scene with disputes and one without | **Full miss, bibles included**: `output_config` differs and sits ahead of the system prompt | Wrath, inside 280 s: 274 of 274 same-schema calls hit; 14 of 18 schema switches missed completely |
| Past 100k words | Window mode: the chosen scenes change each time, so only the bibles block hits | Wrath Nov 8 after about seq 62: hit fraction 0.5–0.7 |

### Cost per reading

Opus rates per million tokens: $4 input, $5 cache write, $0.20 cache read, $20 output. With R the reference block, S the story so far and U the user message:

- Warm: `0.2·(R+S) + 5·U`, plus about $0.03 of output and tool turns.
- Cold: `5·(R+S+U)`, plus the same.

| | Warm reading | Cold reading |
|---|---|---|
| Corpus recordings (R+S ≈ 130k, U ≈ 8k) | $0.13–0.19 | $0.53–0.81 |
| Wrath at seq 8 (R+S ≈ 48k, U ≈ 33k) | $0.21 measured | $0.39–0.47 measured |
| Wrath now (R+S ≈ 173k, U ≈ 33k) | about $0.23 | about $1.05 (Nov 8 measured $1.09–1.13 at a 202k prefix) |

- **Measured per gate run, checker layer only:** recordings $0.45; Wrath Nov 8 $0.36, Nov 15 $0.49, Nov 16 $0.53.
- **Measured latency:** a reading takes a median 16–17 s (p90 23 s), so two readings are about 35 s.

### What caching could save (estimated from measured token counts)

| Change | Saves | Kind of change |
|---|---|---|
| Put the reading note in its own block, with a breakpoint before it | About $0.16 per reading 2 in Wrath; reading 2 falls from about $0.21 to about $0.05 | Code; same text, different request body |
| Move sheets and scene list ahead of the prose in that cached part | About $0.10 more per recheck first reading | Prompt order changes |
| One output schema for every scene, or let the question layer rule disputes | Each avoided miss is $0.35 at Nov 16 sizes, about $1 now | Changes the request for dispute scenes |
| 1-hour TTL on the two system breakpoints, as `session.CACHE_TTL` does | Removes the over-5-minute misses (7 in the logs) | Code; request body changes |
| Raise the cap for the checker only | Keeps the whole story past 100k words for about $0.05 a warm reading | Code; needs the model's window confirmed (a 204k-token request succeeded on Nov 8) |

The cassette keys on the whole request body (`cassette.py:127`), `cache_control` included. Every row above makes the frozen suites stale unless the key is normalised (drop `cache_control`, join adjacent text blocks) and the stored recordings re-keyed, which is free. Only the schema change could alter model output.

## 2. Per-item overlap

The full 77-row table prints from `D/an2.py`. By case, the share of positives caught averaged over three runs:

| Case | Code | n | Open | Questions | Either | Note |
|---|---|---|---|---|---|---|
| governor-014 | REL | 1 | 1.00 | 1.00 | 1.00 | |
| governor-018 | TRT | 5 | 0.93 | 0.93 | 1.00 | |
| governor-022 | TIM | 2 | 0.50 | 0.67 | 0.83 | |
| governor-023 | TRT | 2 | 1.00 | 0.50 | 1.00 | |
| governor-024 | TRT | 6 | 0.83 | 0.00 | 0.83 | identity swap; 2 never asked |
| governor-025 | PHY | 5 | 0.20 | 0.20 | 0.20 | 4 never asked |
| governor-026 | PHY | 2 | 1.00 | 1.00 | 1.00 | |
| lantern-folk-020 | TRT | 1 | 0.00 | 0.00 | 0.00 | unseeded |
| shared-dark-030 | PHY | 1 | 0.00 | 0.00 | 0.00 | |
| shared-dark-037 | KNO | 3 | 0.67 | 0.33 | 1.00 | complementary |
| shared-dark-040 | TIM | 4 | 0.92 | 1.00 | 1.00 | |
| shared-dark-041 | TIM | 2 | 0.17 | 1.00 | 1.00 | questions only |
| thornwall-020 | TIM | 3 | 0.78 | 0.00 | 0.78 | unseeded; calendar |
| thornwall-024 | TIM | 3 | 0.00 | 0.00 | 0.00 | unseeded |
| thornwall-025 | TRT | 6 | 0.00 | 0.00 | 0.00 | asked every time |

Every catch in both suites came from the checker layer itself. The shared layers caught no labelled positive in any run.

### (a) Union and intersection

| Same-index runs | Both | Open only | Questions only | Neither | Union recall | Union false alarms | Intersection recall | Intersection false alarms |
|---|---|---|---|---|---|---|---|---|
| Run 1 | 14 | 12 | 5 | 15 | 31/46 = 0.674 | 6 | 0.304 | 0 |
| Run 2 | 14 | 9 | 3 | 20 | 26/46 = 0.565 | 5 | 0.304 | 0 |
| Run 3 | 14 | 12 | 4 | 16 | 30/46 = 0.652 | 4 | 0.304 | 0 |

- Over all nine pairings: union 26–31 (mean 0.630), union false alarms 4–7 (mean 5.0), intersection 13–15 (mean 0.304).
- Caught at least once in three runs: open 28, questions 19, either 31. Caught in all three: open 20, questions 16.
- **Where the open checker's edge is.** Among the 31–32 positives whose fact the question layer asked, questions caught 16–18, the open checker 19–21, and either 21–25. Among the 14–15 not asked, questions caught 1 and the open checker 4–5.

### (b) One reading against two

| Run | Reading 1 | Reading 2 | Union | Both | False alarms: r1 / r2 / union / both |
|---|---|---|---|---|---|
| 1 | 24 (0.522) | 21 (0.457) | 26 | 19 | 5 / 3 / 5 / 3 |
| 2 | 19 (0.413) | 21 (0.457) | 23 | 17 | 3 / 3 / 3 / 3 |
| 3 | 21 (0.457) | 25 (0.543) | 26 | 20 | 1 / 3 / 3 / 1 |

- Pooling the six readings: one reading 0.475, any two 0.545, any three 0.576, any four 0.594, all six 0.609. False alarms rise 3.0, 3.9, 4.3, 4.6, 5.0.
- Requiring two readings to agree: recall 0.404, false alarms 2.1.
- Per model: no data. The only cross-model figure is the question layer on the 17-case set (Haiku 8, Sonnet 9; `docs/history.md:623`).

### (c) What the false alarms are

All five control items the open checker flagged on the labelled sentence:

| Control | Runs | What it found |
|---|---|---|
| governor-018-3fc5a808 | 1, 2 | The casualty list names two children; `the-rupture` kills an old woman and a girl |
| governor-023-07f75dbc | 1 | Victims placed in unit seven and a corridor; two other scenes say stairwell and unit two |
| governor-025-2edc3822 | 1, 2, 3 | Age sixty-eight; the casualty report and the scene's own last line say seventy-three |
| governor-026-0e79a746 | 1, 3 | Child aged seven; a later scene says nine |
| governor-026-84413638 | 1, 2, 3 | Dead child is a boy on the ground floor; `the-rupture` has a girl from unit four |

- Each is a contradiction with another scene of the pre-pass book, on a different fact than the labelled one. The question layer's two (governor-022-15fc1d00, governor-025-9e136fba) are the same kind.
- Of the 42 open-checker findings on control scenes in run 1, I judged about 38 clear contradictions and about 4 small but true (stood against sat; twelve paces against fifteen). I judged from the two quotes and the explanation and did not open the books.
- **Would a Haiku yes/no pass, asked twice with both quotes, kill them?** On this data no, and it shouldn't: the claims hold. Control stops would stay at 0.71–0.77.
- **Would it kill true catches?** Unmeasured. The nearest figure is the question layer's 0.53–0.56 recall on facts it asked, which is a harder task. The intersection (0.304) is the floor.
- Wrath's live false positives (Homer's own oddities, a change the story shows) are kinds this set has no labels for.

### (d) The 15 neither catches

| Items | Why |
|---|---|
| thornwall-025 (6) | Three different lists of four closed Holds. The seeded fact names only two, so it can't rule out the name in the evidence; the open checker doesn't treat a variant list as a contradiction |
| governor-025 (4) | "Upper floor" against "first floor"; the victim is "the old lady", unnamed, so the fact isn't asked. The open checker reports other errors in these scenes but not this one |
| thornwall-024 (3) | "Decades ago" against sixteen years; the pre-pass book never dates the entry outside the gated scene |
| lantern-folk-020 (1) | A pronoun; the pre-pass book gives the character none outside the gated scene |
| shared-dark-030 (1) | "Stiff leather" gloves against insulated gloves bought earlier; asked every time, answered no |

The practical ceiling on this set is about 31–36 of 46.

## 3. What stops the controls

A control is "stopped" when the gate doesn't pass it for any reason. By layer, over 31 controls:

| Recording | Stopped | Checker layer blocks | Shared layers block | Checker is sole blocker | Shared only |
|---|---|---|---|---|---|
| Open run 1 | 23 | 14 | 16 | 7 | 9 |
| Open run 2 | 22 | 15 | 12 | 10 | 7 |
| Open run 3 | 24 | 18 | 17 | 7 | 6 |
| Questions run 1 | 15 | 4 | 15 | 0 | 11 |
| Questions run 2 | 19 | 7 | 17 | 2 | 12 |
| Questions run 3 | 17 | 5 | 16 | 1 | 12 |

- **Inside the shared layers:** the blocking read blocks 10–15 controls, typed state 3–4, unresolved extraction 0–2.
- **The floor with no checker at all is 0.39–0.55.** The two suites' shared layers are separate recordings of the same requests, so their spread (12–17) is run-to-run noise.
- **The checker's own contribution:** open adds 7–10 controls, questions 0–2.
- **"Clean" is not clean.** The open checker's stops on controls are mostly real contradictions (2c), so its extra 7–10 are not false stops. I did not read the blocking read's findings; whether its 10–15 are real decides how much of the floor is noise.
- **Typed state is nearly inert here.** These corpus books have no typed state for earlier scenes (the notes say "69 earlier scene(s) have no typed state yet"). It will stop more in Wrath.
- Running both checkers barely moves control stops: 23–25 of 31. The question layer's blocks fall on scenes already stopped.

## 4. Hybrid designs

Recall, false alarms and control stops are computed from the recordings by joining per item (ranges over all pairings). Cost and latency are for the checker layer in Wrath per gate run, estimated from measured token counts; add about $0.31 for the shared layers.

| Design | Recall | False alarms on the fact | Control stops | Cost per run, as is | With the caching fixes | Latency |
|---|---|---|---|---|---|---|
| Open, 2 readings (default) | 0.543 (23–26) | 3.7 | 0.74 | $0.50 measured; $0.5–0.7 at today's length | about $0.33 | 35 s |
| Questions only | 0.391 (17–19) | 1.3 | 0.55 | $0.01 | same | 15–55 s |
| Tandem: questions + open, 2 readings | 0.630 (26–31) | 5.0 | 0.77 | $0.51 | about $0.34 | 35 s if run together |
| (i) Questions + open, 1 reading, Opus | 0.598 (24–30) | 4.3 | 0.75 | $0.25–0.35 | about $0.26 first run, $0.10 recheck | 17–25 s |
| (i) the same on Sonnet | unmeasured | unmeasured | unmeasured | about 55% of the Opus figure | | similar |
| (ii) Tandem on the first run; rechecks run questions, shared layers and a yes/no on the first run's findings | 0.630 on the first run | 5.0 | 0.77 | $0.51 first run, $0.01 recheck | $0.34 and $0.01 | recheck drops 35 s |
| (iii) Open as generator, double-asked Haiku as filter | between 0.30 and 0.54–0.63 | 0 to 5 | 0.48 to 0.77 | open cost + $0.002–0.01 | | +5–10 s |
| (iv) Questions + open only where the fact wasn't asked | at most 0.493 (21–24) | 1.3 | not computable | about $0.20 | $0.05–0.10 | 17 s |

Over the remaining 40 scenes at 2.3 gate runs each (92 runs), the checker layer comes to roughly:
- default: $46–64;
- (i) on Opus: about $28 as is, about $16 with the caching fixes;
- (ii): about $22, or about $13 with one reading.

### Notes on each

- **Tandem.** Pure code: call `_ask_questions` in open mode too; its de-duplication against existing findings is already there (`gate.py:3763-3767`). It also lets the question layer rule disputes, which removes the schema switch. The recall figure joins two recordings, and the question suite had each case's fact seeded. Unseeded it scored 0.02–0.04, so in a real book the question half is worth what the ledger holds.
- **(i) One reading.** Pure code (`GATE_READINGS = 1`). Reading 1's request is unchanged, so the existing recordings already measure it. It gives up about 7 points of recall against two readings and gets about 5.5 back from the question layer on seeded facts. Sonnet needs a paid recording: about $20 a run, $60 for three.
- **(ii) Open on the first run only.** Wrath's logs support it. In 37 open-checker rechecks, 49 first-run findings became 10: 2 persisted, 2 were on the fix's new words (one recheck), and 6 were new findings elsewhere (five rechecks). Those 6 are reading variance, each starting another fix round. The risk is the one recheck in 37 where the fix introduced a contradiction; the question layer and shared layers still run on the fixed prose. It needs a small new prompt, recorded for cents. No labelled set measures fix-introduced errors; E8 would, and it is stale.
- **(iii) Generator and filter.** The recorded data gives no reason to expect fewer stops, because there is little false to remove. It would guard against Wrath's live kinds of false positive, which need labels from this book. A cheap test exists: run the verifier over the 960 recorded findings (under $1 on Haiku, as a top-up downstream of the Opus calls). Score wrongly killed catches on the positives' on-evidence findings, with Wrath's hand-read pending findings as the false set.
- **(iv) Restricted open checker.** The upper bound from the recordings is 0.49, below one plain open reading plus questions (0.60). It is also a prompt change to every checker call: a full re-record, about $130.

### Evidence needed before switching the default

- Tandem or (i): nothing more from the gate set. Decision 5 names E4 and E8, which are stale, so either re-measure them or decide on the gate set.
- Sonnet: a recorded three-run suite.
- Window mode: any measurement at all. Most of the remaining book will be checked in a mode no recording covers.

## 5. Batch API and other discounts

- **Used today** by `enrich`, `evaluate`, `elaborate`, `extract` and `write --batch` (briefs under coach or strict coaching only): `cmd_enrich.py:687-712`, `cmd_evaluate.py:1172-1197`, `cmd_elaborate.py:401-410`, `cmd_extract.py:633-640`, `cmd_write.py:200-213`. `calculate_cost_from_usage(batch=True)` applies the 50% (`api.py:775`).
- **Not used** by the gate, the checker, the question layer or the blocking read. The cassette refuses batch calls, so a batched gate could not be recorded.
- **In-session gating can't use it.** The writer waits on the result, and the open checker is a multi-turn tool loop that a batch can't hold in one request.
- **A deferred end-of-act sweep could**, for single-call layers (questions, blocking read, a tool-less open reading). For the open checker it is the wrong lever: batch takes 50% off, and a warm cache takes 95% off the prefix, which is most of the request.
- No priority or flex tier is referenced in `api.py`.
