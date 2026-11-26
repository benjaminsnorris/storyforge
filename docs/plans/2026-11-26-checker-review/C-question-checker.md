# Report C: the question checker's coverage holes

Research agent report, 2026-11-26, on *Wrath Like Smoke* (iliad-adult). Read-only; no model calls.

**This report is partial.** The disk filled during the `gate-set-questions` replay, so the agent stopped before writing its full report. What follows is its summary. Not done:

- the `gate-set-questions` replay and a reading of `gate_set_questions.py`;
- exact ranks under the proposed ordering;
- the measured fraction of subjectless facts that name matching can assign;
- the 15-example tables of cut and subjectless facts.

## Measured

The ledger is `reference/commitments.csv`, 1,487 rows. The agent's simulator reproduces the run log exactly where checked (27 subjectless at seq 10, 47 at seq 20, 86 subjectless and 437 cut at seq 57).

| Per scene (53 files) | Median | Max |
|---|---|---|
| Live facts | 596 | 1,146 |
| No subject | 60 | 86 |
| Absent | 337 | 837 |
| Qualify | 148 | 467 |
| Cut by cap | 118 | 437 |

- **The cap's order is the main defect.** `facts_to_ask` sorts by type (trait first), then oldest scene first (`questions.py:350-354`), so 84% of qualifying questions are cut and late scenes ask only old traits.
- **Asked vs qualified:** trait 889 of 936, relationship 334 of 759, physical 192 of 2,246, world 26, knowledge 21, timeline 9. Only 273 of 1,296 askable facts were ever asked.
- **The open checker finds the opposite mix here:** of 50 contradictions, 27 are timeline and 11 physical; only 3 of its 55 findings cite a ledger fact.
- **Yield:** 2,979 question slots gave 15 two-yes answers on 7 facts. Aeneas's hip (physical, 1-2 scenes old) is the real one. The other five are old traits: two stale states, one source-backed, one pedantic, one wrong man (two Dolops).
- **Cost:** about $0.0085 a run for the whole layer ($0.0048 facts, $0.0037 promises), with no caching. Uncapped worst case is about $0.07 a run.
- **Uncapping alone would backfire:** about 0.37% of questions give a false two-yes, so 300-470 questions means 1.1-1.7 false stops a run.
- **Aliases:** patronymics are rare (68 phrases). A code-built table of 510 phrases adds presence in 2 scenes, 40 facts.
- **Homonyms matter more:** 49 names are shared by 107 character ids, and a bare name marks all of them present.
- **Subjectless:** 124 at HEAD, 92 of them the briefs' knowledge rows. Those name a character in the statement, so roughly three-quarters look assignable; this is an estimate.
- **Reference:** the book's bibles are thin and `timeline.md` is an empty template. The series canon has 80 sheets with 1,485 bullets keyed by character id, convertible by code.
- **Deaths:** `death_scene` is blank for all 483 characters, so `check_life` rests on Haiku's records alone.
- **`question-set` replay:** PASS, recall 0.7647 (13 of 17), 0 false alarms.

## Ranked fixes

| # | Fix | Kind | Build |
|---|---|---|---|
| 1 | Reorder: disputes, in-force physical states of the on-stage cast, last 5 scenes, then by salience | code | half a day |
| 2 | Drop stale `state` traits past a day boundary | code | 2-3 h |
| 3 | Subjects from names in the statement | code | half a day |
| 4 | Cap to 60-90, in batches of 30 | code | 2 h, after 1-2 |
| 5 | Homonym guard | code | 2-3 h |
| 6 | Series sheets as standing facts | code | 1 day |
| 7 | "That morning"/"yesterday" in typed state | prompt | half a day |
| 8 | Patronymic table | code | 2 h |

Fixes 1-4 change no prompt text but do change the recorded requests, so `gate-set-questions` needs a paid top-up (its recording cost $35; Ben's go). Fix 7 re-records the typed-state suites.

## Confidence

- **High:** the selection measurements and the cost figures.
- **Medium:** the prioritisation. It is reasoned from 7 facts that the current order happened to ask, and was not rerun.
- **Low:** the subjectless fraction and the bible fact count.

## A separate check on names (main session)

- `../homer/name-map/iliad.csv` is a one-to-one rename table (Butler's names to the retelling's), applied at `source import`. It holds no epithets or patronymics.
- The question checker places a subject by the `name` and `aliases` columns of `reference/characters.csv` and `locations.csv` (`ledger.subject_names`). Only 7 of 483 characters have an alias, all spelling variants.
- Across the drafted scenes, the five main patronymics (Atreus, Tydeus, Peleus, Telamon, Priam) appear about 35 times. In all but one scene the plain name appears too. The exception is "son of Telamon" in `zeus-nods-to-thetis`.
