# Review of the gate's two checkers (2026-11-26)

A review of the open checker and the question checker, measured on *Wrath Like Smoke* (iliad-adult, 52 of 92 scenes drafted) and on the recorded evals, with industry research.

**Status:** all seven reports are in.

Everything here is a proposal. Nothing is built, and the spend items need Ben's go-ahead.

## The recommendation

**Run both checkers in tandem, and fix the typed-state checks first.** The two checkers are not rivals: on this book they catch almost entirely different things. And neither one is the gate's main problem. Most of the overnight run's stops, most of its pending scenes and all of its damage to the prose came from the possession, injury and dead-character checks, which found nothing real.

In order:

1. **Fix possession, injury and the dead-character check** (code only). They made 64 findings in the overnight run and none was real.
2. **Fix the fix loop** (code only): stop re-extracting on every fix round, stop dropping true facts, and stop the "never worse" rule discarding good fixes on question noise.
3. **Run the open checker on a scene's first gate run only, with the question checker on every run.** Fix the open checker's caching at the same time.
4. **Repair the question checker's selection**, then raise its cap. Stop asking "promises" that an earlier scene already established.
5. **Let the source check rule on Homer's own oddities**, as an author list and never a silent pass.

Items 1 and 2 should land before drafting resumes. They cost no API spend to build.

## Why: what each layer did on this book

From a replay of the 44 scenes of the overnight run (100 gate runs; every scene reproduced the committed prose byte for byte). The real, false and debatable verdicts are a reader's judgement, not a measurement.

| Layer | Distinct findings | Real | Debatable | False | Cost per gate run |
|---|---|---|---|---|---|
| Blocking read (Opus, 2 readings) | 38 | 29 | 9 | 0 | $0.073 |
| Possession | 43 | 0 | 1 | 42 | under $0.01 (shared typed-state call) |
| Injury | 13 | 0 | 4 | 9 | same call |
| Dead-character check | 8 | 0 | 0 | 8 | same call |
| Question checker: facts | 7 | 1 | 2 | 4 | $0.005 |
| Question checker: promises (blocking) | 9 | 0 | 2 | 7 | $0.004 |
| Open checker (Nov 8 draft, 135 runs) | 47 | 33 | 9 | 5 | $0.46–0.60 |

Sources: [A](A-log-census.md), [B](B-typed-state.md). Report B counted possession slightly differently (36 distinct, 34 false) and reached the same verdict.

- **The blocking read is the gate's best layer.** Keep it as it is, with both readings: the second reading alone found about 14 slips.
- **The open checker was precise on this book.** 70% of its findings were real, and 4 of its 5 false ones were Homer's own inconsistencies. Those verdicts rest on the finding text alone, because the Nov 8 prose is gone.
- **The question checker made one real catch from 2,919 questions.** That catch reached it as an extraction dispute, not as a selected fact.
- **The two barely overlap.** Only 6 of the open checker's 68 raw findings named a ledger fact. The rest were misremembered events, "last night" and "nine days ago" errors, event order, the bibles and camp geography. No question can reach those.

### The gate damaged the prose

- **Phantom injuries.** The injury check carried Hector's momentary "shield arm will not come up" for 42 days, and Diomedes's shoulder likewise. To satisfy it, the fixes wrote a lingering injury into the committed prose of at least three scenes (`polydamas-counsels-a-pause`, `hector-fires-the-ships`, `diomedes-and-odysseus-raid`). Homer has neither.
- **"His own".** The fixes answered false possession findings by inserting "his own helmet", "his own bow", "a sword of his own", and by cutting lines.
- **New errors.** Fixes wrote at least 11 new findings into the prose, 4 of them real blocking errors. Three of those answered a false finding, and 3 are in pending scenes now.
- **A good fix discarded.** In `aphrodite-drives-helen-to-bed` the fix removed a real blocking error. A promise question then flipped on the re-check, and the "never worse" rule threw the fix away.

This is the "writing to avoid errors" problem in a mechanical form: 70 of 119 findings sent to the writer were false.

## Answers to the questions asked

**Fix the problems with each?** Yes, but the larger problems are beside them, in the typed-state checks and the fix loop. The open checker needs caching fixes, not accuracy fixes. The question checker needs a different selection order.

**Use them in tandem?** Yes. On the recorded evals the union reaches recall 0.63 against 0.54 (open) and 0.39 (questions), and control stops barely move (0.77 against 0.74). On this book the case is stronger, since they catch different kinds of error. See [D](D-open-checker-overlap.md).

**An entirely different approach?** No. The published ceiling for this task is about 0.55 recall (ConStory-Checker; professional novelists scored 0.14–0.17 on the same set), and the open checker is already there. The gain left is in precision and cost. See [F](F-industry-research.md).

**Can it be programmatic?** In part.
- The rules are already code. Every failure found was in reading prose into records: which object "his shield" is, who "she" is, how bad a wound is.
- Blocking cannot be done by code. The stage sheet is the measured attempt: recall 0.22 with 15.65 false alarms per 10k words, against 0.62 and 1.27 for the read.
- Cheap programmatic wins exist: deaths from the series cast's last scene, carried facts across fix rounds, a namesake guard, and the source's own fact ledger.

**Modern decision models?** I took this to mean small classifier models, rules engines, solvers and routers. Tell me if you meant something else.
- Small entailment and grounding models score at chance on fiction contradiction in two papers. Do not build one.
- Solvers and decision tables have no evidence for this task.
- The useful form is a cascade: a cheap model raises, a stronger one or a second asking confirms. The gate already has this shape.
- Later, once a few hundred findings carry an accept or reject label, a filter trained on those is worth a look.

**Should the question checker look at the reference files?** Not yet.
- This book's own bibles are thin, and `timeline.md` is an empty template.
- The series canon has 80 character sheets with 1,485 bullets that code could turn into standing facts. But the checker already cuts 86% of its questions, traits first. Adding 1,485 more traits would make that worse.
- The open checker already reads the bibles, and 3 of its 33 real catches came from them.
- Revisit after the selection order is fixed (item 8).

**Names.** The name map is a rename table (Butler's names to the retelling's), not an alias list, and only 7 of 483 characters have an alias. In practice it hardly matters here: a patronymic table adds presence in 2 scenes. Namesakes matter more: 49 names are shared by 107 character ids, and a bare name marks all of them present. See [C](C-question-checker.md).

## The changes, ranked by effect on the book

Build times are the agents' estimates. "Top-up" means re-recording only the eval requests that changed.

### First: stop the harm (code only, no spend)

| # | Change | Effect | Build |
|---|---|---|---|
| 1 | **Possession:** scope a bare item ("shield") to its holder; pair the two halves of a handover; treat a misquoted record as unknown; let remains of a destroyed object be discarded | Removes 33 of 34 false findings by a hand trace (not a run). Five pending scenes are pending for nothing else | 1 day |
| 2 | **Injury and dead-character check:** injuries lapse unless the scene shows impairment; a god's healing counts; a death binds a character id, not a bare name; the death sentence is not "presence after death" | Removes all 17 false findings of these two kinds | half a day, plus one prompt line (about $1 top-up) |
| 3 | **Extraction guards:** an `ends` naming a fact the same scene sets up is not a slip; a slip earns its re-extraction even beside other findings | Prevents the `diomedes-spears-ares` halt, which stopped the session with 73 scenes not attempted | a few hours |
| 4 | **Hold-back bug:** a scene stopped on a false finding has the fact behind it kept out of the ledger | Pandarus's death, Aeneas's return and two more true facts are missing today | a few hours |
| 5 | **Carry first-run facts across fix rounds** and re-verify their quotes by code | Saves about $11 and a minute per re-check over 40 scenes. Re-extraction re-rolls about a quarter of the facts while the fix changes about 18 words | 1 day |
| 6 | **"Never worse":** count a finding as fix-introduced only when its quote touches edited text | Stops a flipped answer on unchanged prose from discarding a fix | half a day |

Item 5 has one choice for Ben. The logs show about 0.18 genuinely new facts per re-check come from edited text. Either accept that loss, or run one extra extraction when the scene commits (saving about $5 instead of $11).

Item 6 is my inference from one case; the mechanism should be confirmed in code before building.

### Second: the checkers

| # | Change | Effect | Build and verify |
|---|---|---|---|
| 7 | **Tandem, open checker on the first gate run only.** Re-checks run the question checker and the shared layers | Keeps the open checker's catches for about $13–22 over the rest of the book, against $46–64 as it runs today. In 37 logged re-checks, 6 of its 8 new findings were reading variance, each starting another fix round | 1–2 days. Code, plus a small re-check prompt recorded for cents |
| 8 | **Question order:** disputes first, then physical states of the on-stage cast, then the last five scenes. Drop stale state traits. Then raise the cap to 60–90 | Today 192 of 2,246 qualifying physical facts are asked, against 889 of 936 traits. Raising the cap alone would add 1–2 false stops a run | 1 day. Top-up of `gate-set-questions` (the full recording cost $35) |
| 9 | **Promise questions:** do not ask a brief's "promise" that an earlier scene already established | 7 of 9 blocking promise findings were false and none was real; so were about 75 of 78 advisory ones | half a day; same top-up as 8 |
| 10 | **Open checker caching:** reading note in its own block; one output schema; a one-hour cache | Reading 2 falls from about $0.21 to about $0.05. Switching schema caused 14 of 18 full cache misses | 1 day. Re-keying the recordings is free |
| 11 | **Source check:** rule on same-scene blocking and possession findings; rule from this scene's source when the earlier scene's does not fit | Clears about 8 of the 14 pending scenes' findings to an author list | 1 day. Prompt change; a 14-case test from the logs, under $1 |

On item 7, two readings or one: keep two. On this book 15 of the 33 real catches came from a single reading, and after item 10 the second reading costs about $0.05.

On item 7's risk: the open checker drops to a window of recent scenes once the story passes 100,000 words, about 8 scenes from now. No recorded eval measures that mode. On the Nov 8 draft it still found things (10 of 30 windowed first runs had a finding, against 18 of 63 with the full story).

### Third: cheaper and safer

| # | Change | Effect | Build and verify |
|---|---|---|---|
| 12 | **Extraction thinking.** Turn Sonnet's thinking off or cap it. Keep Sonnet: Haiku failed the test (report G) | Thinking off: 42 s to about 18 s, about $3 saved. Haiku captured 45–47% of continuity-critical facts against Sonnet's 81% on the same prompts | about $2 to re-record for thinking off |
| 13 | **A typed-state eval suite** from this run's classified findings | Typed state has no eval, which is why 64 false findings came as a surprise. The labels now exist | 1 day; free to build |
| 14 | **Deaths by code** from the series cast's last scene | `death_scene` is blank for all 483 characters, so the dead-character check rests on Haiku alone | half a day |
| 15 | **Namesake guard** in the question checker | 49 names shared by 107 ids | 2–3 hours |
| 16 | **Use the source's fact ledger** (`reference/source/iliad/commitments.csv`, 3,387 facts over 239 Butler scenes) to give the writer each scene's entering state | Prevents errors instead of catching them. Nothing in the gate reads it as facts today | 1–2 days |

### Do not build

- A small entailment model as a pre-filter (chance on fiction).
- Raising the question cap without the reorder.
- An open checker restricted to what questions miss (upper bound 0.49 recall, and a $130 re-record).
- The open checker on Sonnet, for now (no recorded data; $60 to find out).
- The Batch API for the gate (a warm cache saves more, and the writer waits on the result).
- The stage sheet in place of the blocking read.
- Haiku for extraction, including Haiku for re-checks only or two Haiku runs merged (report G).
- A generic verify pass on open-checker findings. Its recorded "false alarms" are real contradictions on other facts, and on this book its false ones are Homer's. Item 11 is the verifier this book needs.

## Issues

Each build item has an issue. **[ISSUES.md](ISSUES.md) has the order, what can run in parallel (up to six at once), and the smallest set to merge before a redraft.** **[PILOT.md](PILOT.md)** is the runbook for the pilot before the redraft, and what's left after it.

| Item | Issue |
|---|---|
| 1. Possession | #732 |
| 2. Injury and dead-character check | #733 |
| 3. Extraction guards | #734 |
| 4. Hold-back bug | #735 |
| 5. Carry facts across fix rounds | #736 |
| 6. "Never worse" | #737 |
| 7. Tandem | #738 |
| 8. Question order and cap | #739 |
| 9. Promise questions | #740 |
| 10. Open checker caching | #741 |
| 11. Source check | #742 |
| 12. Extraction thinking and model | #743 |
| 13. Typed-state eval suite | #744 |
| 14. Deaths by code | #745 |
| 15. Namesake guard | #746 |
| 16. Entering state from the source ledger | #747 |
| Extractor names the owner (report B, F6) | #748 |
| A claim in speech is not narration | #749 |

## Decisions for Ben

**Artistic:**
- **Decided 2026-11-26: Homer's own inconsistencies.** Divine repairs kept, with the license on the page; physical slips inside a scene smoothed; conflicting accounts in speech kept (homer PR 5, iliad-adult PR 24).
- **Decided 2026-11-26: Homer over Butler.** Homer wins, and a fact is never dropped because it disagrees with Butler alone. Known slips are in `../homer/errata/iliad.csv`.
- **Still open: the phantom-injury lines.** Hector's stiff shield arm and Diomedes's bad shoulder are in the committed prose of about ten scenes on iliad-adult PR 23. The briefs also carried Diomedes's shoulder wound to Book 19; iliad-adult PR 24 ends it in Book 5. A redraft would clear the prose.
- **Still open: redraft or continue.** See ISSUES.md, "Before a redraft".

**Spend:**
- Top-ups for items 2, 8, 9 and 11: a few dollars each, by the agents' estimates.
- Item 12's re-record: about $2.
- Not recommended now: Sonnet for the open checker ($60); a fresh E4 and E8 for decision 5.

**Decision 5** asked whether the question checker can replace the open checker. On this book's evidence the answer is no, and the question is the wrong one: run both. I'd close it that way without re-recording E4 and E8.

## What is uncertain

- **Verdicts are judgements.** Real and false were assigned by agents reading findings, not by you. The open checker's rest on finding text alone.
- **The possession fix was traced by hand**, because the disk filled before the prototype could run.
- **Cost projections are estimates** from measured token counts.
- **The question reorder is reasoned from 7 facts** and was not rerun.
- **Report C is partial.** The `gate-set-questions` replay it planned was done by report D instead.
- **No evidence covers the densest scenes still to come.** Patroclus in Achilles's armour, then Hector in it, is the case owner-scoped possession exists for. It needs the extractor to name the owner, which is a prompt change (report B, fix F6).

## Reports

| Report | Covers | Status |
|---|---|---|
| [A: gate-log census](A-log-census.md) | What each gate layer found on this book, real or false, with cost per layer | done |
| [B: typed state and blocking](B-typed-state.md) | Possession false positives, the blocking read, injury and life checks, the `diomedes-spears-ares` halt | done |
| [C: question checker](C-question-checker.md) | The 30-question cap, subjectless facts, names, reference files | partial (disk filled) |
| [D: open checker and overlap](D-open-checker-overlap.md) | Item-by-item comparison of the two checkers on the recorded evals; hybrid designs | done |
| [E: extraction and source check](E-extraction-source.md) | Extraction cost and churn, the source check's verdicts, Homer's oddities | done |
| [F: industry research](F-industry-research.md) | Published benchmarks, find-then-verify, small models, pricing, evaluation practice | done |
| [G: Haiku for extraction](G-haiku-extraction.md) | A live comparison of Haiku and Sonnet on 12 scenes and on E3 (Ben's go; $5.52, not charged to the eval budget) | done |

Each report is a research agent's own account, lightly reformatted, and states what it measured and what it estimated. All were read-only with no model calls, except G. Scratch scripts the reports mention lived in a temp folder and are not kept.
