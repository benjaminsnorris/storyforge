# Report E: extraction and the source check

Research agent report, 2026-11-26, on *Wrath Like Smoke* (iliad-adult) gate logs. Read-only; no model calls. The GitHub issue search for earlier extraction comparisons found nothing relevant and individual issues were not opened.

## Summary

**Measured (117 extraction calls, 51 scenes, 16–17 Nov):**
- **Size and cost:** 29.9k input and 6.7k output tokens, $0.127 a call, $14.82 in all (43% of the gate's logged $34.85).
- **Latency:** median 42 s, p90 about 77 s. The brief's 90 s was the largest scene.
- **Driver:** output tokens at a steady ~153 tok/s; 51% of output is thinking, which nobody asked for. Zero cache reads or writes in all 253 logged calls.
- **Dependent calls:** persistence ($0.024) and the source check ($0.065, median 26 s) re-run with every extraction. The three together are 71% of gate cost.
- **Re-extraction is a re-roll.** A fix changes about 18 words of about 1,600, yet about 25% of facts differ between a run and its recheck. Only 28 of 970 differing facts touch edited text; same-prose pairs differ just as much.
- **Subjectless facts are mostly plan rows:** 91 of 123. Only 32 of 1,362 extracted facts are blank, mostly legitimately.
- **Source check:** 2,963 fact rulings, 28 "contradicts" covering 18 distinct facts. I judge 7 real and 11 false; each false one silently drops a true fact.

**Ranked recommendations:**

| # | Change | Kind | Saves (40 scenes) | Verify |
|---|---|---|---|---|
| 1 | Carry first-run facts across fix rounds, re-verify quotes by code, skip re-extraction | Pure code; requests unchanged | ~$11, ~1 min per recheck | Free replay of `recheck-set` and `gate-set` |
| 2 | Let the source rule on same-scene blocking and possession findings; still rule when the earlier scene's source doesn't fit | Prompt change to `gate_source` | Clears about 8 of 14 pending | 14 labelled cases from the logs, under $1 |
| 3 | Fix the hold-back that drops true facts on a false-positive provisional commit | Pure code | Ledger quality | Regression test |
| 4 | Presence-gate plan facts on any registry name in the statement | Pure code | Closes most of the "never asked" hole | Free |
| 5 | Turn extraction thinking off | Request-body change, so re-record | ~$3; 42 s → ~18 s | ~$2 |
| 6 | Haiku for extraction | Model swap, so re-record | ~$11 alone, ~$5 after #1 | ~$6; needs Ben's go |
| 7 | Prompt caching, Batch API | Prompt change / n.a. | Under $2; nothing after #1 | Skip |

- **#1 detail:** the logs show re-extraction adds no recall; it re-rolls. About 0.18 genuinely new facts per recheck come from edited text. Ben chooses between accepting that loss and one extra extraction at commit (saving about $5 instead).
- **#2 detail:** the Aeneas finding went unruled only because the earlier scene's source passed the 40k-character cap, although the healing passage was already in this scene's own source. Cleared findings should become author notes, never silent passes: whether Homer's inconsistencies stay is Ben's call.
- **#3 detail:** Pandarus's death is missing from the ledger for this reason.
- **#6 evidence:** the only recorded comparison (E3, 28 Oct) has Haiku missing 13 of 49 against Sonnet's 9, with Sonnet's own range at 3. It is weak and predates the current rubric.

**The source oracle already exists.** `reference/source/iliad/commitments.csv` holds 3,387 facts over all 239 Butler scenes, 2,939 with verbatim quotes, and nothing in the gate reads it as facts. It follows Butler, whose slips differ from Homer.

**Confidence:**
- **High:** the token, cost and latency measurements and the code reading.
- **Medium:** the fact-churn rate (my matcher under-matches; true overlap is nearer 85–90%) and the real/false split of source verdicts (four rest on Homer line references from memory).
- **Low:** the Haiku question, until measured.

## Part 1: extraction

### 1. What it is and why it is slow

- **Code path:** `gate._extract` calls `extract.build_commitments_prompt`, then `persistence.judge`, then `extract.commitment_rows`.
- **Schema (`COMMITMENTS_SCHEMA`):** a list of `{type, subject, statement, quote, mutable, supersedes, ends}`, all required. `subject` may be an empty string, and the prompt allows blank "when it has no single subject".
- **Model and limits:** Sonnet (`select_model('evaluation')`), 8,000 answer tokens plus a 16,000 thinking allowance. No thinking or effort setting is sent, so thinking is adaptive.
- **Prompt order:** rubric, scene prose, registries, up to 200 facts in force, how-to. The logs keep only replies, so I rebuilt one prompt offline (`hector-fires-the-ships`):

| Part | Share of input |
|---|---|
| Offered facts (200 of 1,321 in force; 1,121 left out) | ~54% |
| Registries | ~19% |
| Scene | ~17% |
| Rubric and how-to | ~10% |

**Measured, 16–17 Nov (117 calls):**

| | Mean | Median | p90 | Max |
|---|---|---|---|---|
| Input tokens | 29,893 | 30,266 | 31,650 | 32,526 |
| Output tokens | 6,686 | 6,422 | 11,648 | 17,314 |
| of which thinking | 3,401 | 3,226 | 7,049 | 11,847 |
| Visible answer | 3,285 | 3,223 | 4,732 | 5,796 |
| Latency (file mtimes) | 49 s | 42 s | 77 s | — |

- **Cost split:** $0.127 a call: 47% input, 27% thinking, 26% answer.
- **Speed:** output runs at ~153 tok/s whatever the size. On the 136 calls of 8 Nov, latency correlates 0.98 with output tokens and 0.55 with input.
- **Thinking:** 27 calls did none. They took a median 18 s against 48 s, and paired within a scene they yielded 1.3 fewer facts of about 28 (n=18).
- **Volume:** about 28 facts a run, about 118 tokens a fact.
- **Cap risk:** the largest answer was 5,796 of the 8,000 cap. A cut-off raises `GateError` and stops the session, and the remaining scenes are the densest. Raising the cap is free.
- **Other gate steps over the same runs:** blocking $8.46, source $7.23, persistence $2.75, questions $0.87, typed state $0.72.

### 2. Would a smaller model hold up?

**Recorded evidence:** one comparison, in rethink-status "E3 tier comparison" (fixtures in `evals/fixtures/tier-comparison/`).

| Model | Captured | Partial | Missing |
|---|---|---|---|
| Haiku 5.5 | 13 | 23 | 13 |
| Sonnet 5.5 | 12 | 28 | 9 |
| Opus 5.5 | 13 | 29 | 7 |

- The status doc's own later note: Sonnet's misses vary by 3 run to run, so "Haiku drops facts" holds weakly.
- It predates structured outputs, the persistence pass and the current rubric. Today's E3 recall is 0.878.
- Haiku 5.5 is priced at $0.10/$0.50 against Sonnet's $2/$10, so a swap cuts extraction by about 95%.

**Cheapest measurement that would settle it:**
- **E3 on Haiku:** `STORYFORGE_MODEL=claude-haiku-5-5`, Opus judge unchanged, 3 runs. My estimate is about $2 a run, most of it the judge; the monthly eval budget is $25.
- **This book:** 12 scenes × 2 Haiku readings of the identical prompt (about $0.20), scored against a hand-made list of continuity-critical facts. The quality read already has 97 such items for 6 scenes; about 190 items gives roughly ±2.5 points.
- **Pass criterion:** mean E3 recall at least 0.82 and missing no more than Sonnet's plus 2; on the book list, recall within 3 points of Sonnet's 89%, with wrong-fact, misquote and wrong-subject rates no worse.
- **What not to use:** agreement with a Sonnet run, since Sonnet agrees with itself only about 75–85%.

### 3. Savings without a model swap

**(a) How different is a re-extraction?** Across 65 consecutive pairs from 16–17 Nov:
- 75% of facts matched; 24% of the first reading's facts vanished and 26% new ones appeared, though their text was untouched.
- 16 lost and 12 gained facts touched edited words, which is 0.18 genuinely new facts per recheck.
- Among matched facts, 5% had an identical statement, 17% a different subject and 22% a different type.
- Three pairs with no fix between them show the same churn (20/26, 31/40, 37/45 matched).
- My matcher under-matches. Reading one pair by hand, 2 of the 6 "unmatched" facts on each side were the same fact with a different type and quote. True overlap is nearer 85–90%.
- **Conclusion:** the recall cost Ben feared from incremental extraction is not in the logs. The risk is bounded by the 0.18 facts per recheck.

**(b) What a recheck consumes from a fresh extraction:**
- halts on a changed fixed fact;
- extractor slips, which caused one stop in 44 scenes and are themselves a failure mode;
- disputes sent to the question layer;
- the facts sent to the source check;
- the commit.

The fix rounds are driven by blocking, possession and question findings, none of which need the scene's own extraction. `steady_facts` and `_keep_steady` already do the keeping for committed scenes; nothing carries uncommitted first-run facts across fix rounds. Doing so is pure code and sends byte-identical requests, so no re-recording. It would also make the source memo hit: today it is keyed on fact wording, so churn defeats it (112 source calls for 117 extractions).

**(c) Prompt caching.** About 83% of the input is identical between a run and its recheck, but the scene sits ahead of it and no `cache_control` is set. Reordering saves about $0.045 a recheck. It is a prompt change, and worth nothing after (b).

**(d) Thinking off or a tighter schema.** Thinking off saves $0.034 a call and more than half the latency. The cassette keys on the whole request body, so this forces re-recording. Trimming the schema is not worth it: the statement and quote are the bulk.

**(e) Batch API.** The next scene's gate needs the ledger, so only `check --pending` cascades could use it. It is also refused under a cassette.

### 4. Quality on six scenes

Read in full by a subagent: `athena-fires-diomedes`, `agamemnon-is-wounded`, `glaucus-and-diomedes-trade-armour`, `hector-duels-ajax`, `ajax-fells-hector`, `hector-farewell-to-andromache`.

- **Recall:** 86 of 97 continuity-critical facts from prose rows (89%); 94% with plan rows.
- **Trivial:** 28 of 173 rows (16%), plus about 14 myth rows in one scene.
- **Wrong:** 3 — a stale state, an over-read, and a Homer detail not in the prose.
- **Blank subjects:** 6, of which 5 legitimate.
- **Wrong subjects are the real problem:**
  - homonym picks (`tros-son-of-alastor`, `oeneus-slain-by-achilles`);
  - deaths filed under the father or the killer;
  - two people in one row.
- **High-value misses:**
  - Pandarus's death;
  - the sword and belt exchange;
  - the right-shoulder side of Diomedes's wound.

**Why Pandarus's death is missing.** It was extracted in all three runs, then held back at the provisional commit as "states what stopped the commit". The finding was the 5.290 oddity. The same hold-back took Aeneas's return, the lot falling to Ajax, and Diomedes handing the spoils to Odysseus.

**Subjectless facts.** The schema allows a blank and the extractor rarely uses it. The hole is in the plan rows: 91 of 124 have no subject.
- Assigning one subject by code is unsafe: a first-name rule agrees with the model's own choice on only 76% of rows.
- Gating a question on any registry name in the statement would cover 83 of the 91 (8 name nobody).

## Part 2: the source check

### 5. What it does today

- **When:** one Sonnet call per gate run, for scenes mapped in `reference/source-map.csv` (87 of 92; 1 to 8 source scenes each).
- **What is sent:** the mapped source scenes' briefs and prose (12k characters a scene, 40k a call), the version rules, the map note, the scene, the extracted facts, and verified contradictions with an earlier scene.
- **What it rules:** each fact as agrees, contradicts or not-in-source; each contradiction as backs this, earlier or neither.
- **Not sent:** same-scene blocking and possession findings.
- **Cost and latency:** $0.065 and a median 26 s a call; $7.23 over 112 calls.

**Its 18 distinct "contradicts" verdicts:**

| Class | Count | Examples |
|---|---|---|
| Real departure from Butler | 7 | Paris's arrow for a spear; Idomeneus's spear left in Oenomaus; Briseis taken before the ship sails; Polydamas's "scattered" reversed |
| Verdict contradicts its own reasoning | 5 | "…so the source is not contradicted"; "(Wait: … matches the source.)" |
| Butler slip or misread, draft correct | 6 | see below |

The six in the last row:
- **Lycophron** falls from the "prow" in Butler; Homer 15.435 has the stern.
- **The wine** is "ten thousand measures" in Butler; Homer 7.471 has a thousand.
- **Odysseus** has "sword-wounds" in Butler's Book 16, against Butler's own Book 11 spear. This true wound fact was dropped in 5 runs.
- **Eurypylus** says "take me to your ship" in Butler.
- **Machaon and Podalirius:** the check read "the one… the other" backwards.
- **Ajax "knew well":** a pronoun misread. I could not find Butler's line by search, so this is the least certain.

Butler's wording is verified in the source files for the first four; the Homer line references are from memory.

The eight contradiction rulings look sound. Three were not ruled on: two because the earlier scene's source would pass 40k characters, one because a plan row points at a merged scene id.

### 6. Homer's oddities, and how the source could clear them

| Finding | Layer | Licensing passage (source scene) |
|---|---|---|
| Menelaus throws the hilt down | possession | "the sword fell shivered in three or four pieces from his hand" (`paris-and-menelaus-duel`) |
| Spear rises yet exits under the chin | blocking | Iliad 5.290, by line reference only (`aeneas-and-pandarus-confront-diomed`). The prose's "goes up" is its own addition: half real |
| Diomedes's shoulder used at full strength | typed state | Athena's strengthening, 5.121ff, by line reference only (`pandarus-wounds-diomed-and-minerva`) |
| Aeneas back at the front | questions | "Latona and Diana healed him… they could not ask him how it had all happened" (`apollo-repels-diomed-and-rallies`, mapped to this very scene) |
| Diomedes throws in Book 8 | typed state | 5.795ff and the next-day throw: not located in the source files |
| Diomedes hands the spoils up | possession | "placed the blood-stained spoils in the hands of Ulysses" (`heroes-return-with-horses`) |
| Theano lays the robe | possession | The source has the robe laid on Minerva's knees (`hector-asks-hecuba-for-offering`); the Theano line itself was not located |
| Athena disarms Ares | possession | 15.125: not located |

**Why the Aeneas finding went unruled.** `gate_source.review` skips a contradiction when the earlier scene's source does not fit the budget. `athena-fires-diomedes` alone has 34k characters of source. The healing passage was in this scene's own source, already in the call.

**Proposed design:**
1. Still rule on a contradiction using this scene's source when the earlier scene's does not fit.
2. Add every blocking finding, same-scene ones included, as a third list. Ask: does the source narrate this same sequence? Answer source-has-it, prose-departs or silent, with a verbatim source quote that code verifies.
3. Route source-has-it to an author list, as `gate-source-fix.csv` is today, not to a stop. Never clear silently.

- **Mapping:** already there (`source-map.csv`, `gate_source.setup().refs`). There are no line numbers, only scene files.
- **Cost:** a few hundred tokens in a call already being made. As a separate Haiku call with about 4k tokens of source, about $0.0005.
- **Risk of clearing a real error:** the 5.290 case shows it — Homer licenses the wound path, not the prose's "goes up". The quote check and the three-way verdict are the guard.
- **Test set:** the 14 pending scenes. The five real slips are staging the draft invented, so the source should be silent on them:
  - Paris on the bed;
  - Ajax's baldric;
  - the right-shoulder arrow and the shield arm;
  - Hector's "empty hands";
  - the unclear "he".
- **What to tell Ben:** the check rules by Butler, so he should decide whether Butler-against-Homer verdicts drop facts at all.

### 7. The source as an oracle

It is already built. `reference/source/iliad/commitments.csv`:
- 3,387 rows over all 239 source scenes;
- 2,939 from the commitments pass, with verbatim Butler quotes;
- 1,107 physical; by keyword, 106 mention wounds, 379 deaths and 147 armour;
- 288 with no subject; about 176k tokens by character count.

It holds both "Diomedes's stone crushed the cup-bone joint of Aeneas' hip" and "Apollo, Leto and Artemis healed Aeneas in Pergamus". `prompts_source.source_scene_block` loads it for briefs; `gate_source` never queries it as facts.

`../homer` adds:
- `name-map/iliad.csv`, mapping source ids to book ids;
- `series-bible/cast.md`, with how each person dies and (per that file) a `cast.csv` of first and last scene for 529 people;
- a day-level `timeline.md`.

It has no wound or armour timeline.

**Uses, cheapest first:**
- **Deaths by code:** anyone on stage after their last source scene. No model call.
- **Retrieval for adjudication:** source facts about the finding's subject between the two source scenes.
- **Entering state for the writer:** who is wounded, dead or wearing what, so errors are prevented instead of caught.

A typed begin/end timeline would need one pass over the 239 scenes; I estimate about $1.50 on Haiku, by analogy with the gate's typed-state call. The ledger inherits the extractor's limits (89% recall, homonym subjects) and Butler's slips.

**Files**
- Scripts and data: `scratchpad/` (`stats.py`, `diff.py`, `diff.json`, `src.py`, `src.out`, `quality/subj.py`)
- Code read: `~/Developer/storyforge/scripts/lib/python/storyforge/` (`gate.py`, `extract.py`, `gate_source.py`, `persistence.py`, `api.py`, `cassette.py`)
- Source ledger: `~/Developer/iliad-adult/reference/source/iliad/commitments.csv`
