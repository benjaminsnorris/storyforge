# Report A: gate log census for *Wrath Like Smoke*

Read-only census of what each gate layer found, from `~/Developer/iliad-adult/working/logs/gate/`, the cost ledger and the overnight log. No live model calls were made and nothing in any repo was changed.

## Headline

- **The blocking read is the only layer that earns its stops.** Of 119 distinct blocking findings in the question-checker run, 31 were real errors, and 29 of those came from the blocking read (38 findings, 0 false).
- **Possession, injury and life checks produced 64 findings and no real error.** They caused or shared in most stops and most pending scenes.
- **The question layer asked 2,919 fact questions and produced one real catch.** The 30-question cap cut 86% of the questions it generated, and what it kept was almost all traits: 64% trait, 23% relationship, 0% knowledge, 0% timeline.
- **The open checker (old draft, Nov 8) found less often but far better:** 47 distinct findings in 135 runs, 33 real (70%). Almost none could have come from a ledger question.
- **Gate fixes wrote 11 new findings into the prose,** 4 of them real blocking errors; 3 of those are in the pending prose now.

## How this was measured

**Question-checker era (measured).** The logs hold only model replies, and the gate does not log the problems it sends to a fix. So each scene's gate run was replayed offline through the patched Storyforge copy (`~/Developer/storyforge-questions-gate`), with every model call answered from its logged reply:

- the project state came from `git archive` of the commit before each scene's commit;
- the first-gated prose was rebuilt from the session's writer reply and voice-review edits (`working/logs/session/`);
- fix rounds applied the logged `gate-fix` edits.

Checks on the replay: for **44 of 44 scenes** the replayed final prose is byte-identical to the committed scene, the pass/fail outcome matches, and the "Fix round n: N problem(s) sent, M edit(s)" counts match `overnight-write.log` exactly. No call was missing from the logs. Counts below from the replay are therefore exact for those 44 scenes (100 gate runs).

Not covered: `patroclus-quenches-the-fire` (killed mid-gate, never committed; its 3 run folders are in the cost figures only) and the two later `check` runs on `diomedes-spears-ares`.

**Open-checker era (measured counts, judged verdicts).** Findings were parsed from the final reply of each `gate-check-*.json` reading. These are raw model findings, before the gate's quote verification.

**Verdicts (judged by me, not measured).** REAL / FALSE / DEBATABLE are my reading of the finding, its two quotes, and Homer.
- For the 15 pending scenes' findings I read the scene prose (9 scenes in full).
- For the rest I relied on the finding's quotes (the gate verifies them against the prose) and on Butler/Homer from memory, with line numbers given where they decide it.
- The Nov 8 prose no longer exists in `scenes/`, so open-checker verdicts rest on the finding text alone.
- Treat single verdicts as ±1 category; the layer-level pattern is robust.

Scripts and intermediate data are beside this report (`replay.py`, `A-*.py`, `A-*.json`, `replay/`).

---

## 1. Question-checker era: findings and stops by layer

100 gate runs over 44 scenes (2.27 runs per scene).

| | Count |
|---|---|
| Scenes | 44 |
| Passed on the first run | 12 (27%) |
| Stopped on the first run | 32 (73%) |
| Gate runs | 100 (71 stopped, 29 passed) |
| Fix rounds run | 53 (32 first, 21 second) |
| Scenes passed after 1 fix | 10 (one of them by a re-extraction, not the fix) |
| Scenes passed after 2 fixes | 7 |
| Scenes left pending | 15 (14 provisional + `diomedes-spears-ares`, later cleared by `check`) |

### Blocking findings by layer (instances across all 100 runs)

| Layer | Finding instances | Runs it appears in | Runs where it is the only cause | First-run stops it appears in (of 32) | Sole cause on first run | Pending scenes it appears in (of 15) | Sole cause of pending |
|---|---|---|---|---|---|---|---|
| Blocking read | 39 | 35 | 14 | 20 | 9 | 6 | 2 |
| Typed state: possession | 47 | 35 | 14 | 15 | 1 | 9 | 5 |
| Typed state: injury | 13 | 13 | 6 | 6 | 2 | 2 | 1 |
| Typed state: life | 8 | 7 | 1 | 4 | 1 | 1 | 0 |
| Typed state: time | 1 | 1 | 0 | 1 | 0 | 0 | 0 |
| Typed state: place, sky, names, knowledge | 0 | 0 | 0 | 0 | 0 | 0 | 0 |
| Question layer: facts | 7 | 6 | 3 | 3 | 1 | 1 | 1 |
| Question layer: promises (blocking) | 13 | 12 | 3 | 7 | 1 | 1 | 0 |
| Extraction (unresolved `ends`, misquote) | 5 runs | 5 | 1 | 2 | 0 | 1 | 0 |
| Source check | 0 | 0 | 0 | 0 | 0 | 0 | 0 |
| `must:` lines | 0 | 0 | 0 | 0 | 0 | 0 | 0 |
| Persistence | 0 | 0 | 0 | 0 | 0 | 0 | 0 |

The pending columns use the verdict the gate kept. For `aphrodite-drives-helen-to-bed` that is the first run's (its fix was discarded). `diomedes-spears-ares` was held by possession and by the extraction slip together.

Non-blocking output of the same runs:

| Layer | What it produced |
|---|---|
| Question layer: promises (advisory) | 163 advisory broken promises (78 rows left in `working/gate-advisory.csv`) |
| Source check | 25 extracted facts dropped as contradicting Homer (22 distinct); 3 question findings cleared as source-backed |
| Persistence | 160 extracted facts dropped as not lasting, of 2,681 proposed |
| Extraction | "over the cap" note on 100 of 100 runs; 14 `disagrees` disputes passed to the question layer |

### Per scene

Each cell is one gate run: what blocked it, or `pass`.

| Scene | Runs | Run by run | End |
|---|---|---|---|
| agamemnon-tests-the-army | 1 | pass | passed |
| odysseus-beats-thersites | 1 | pass | passed |
| hector-sends-paris-to-duel | 3 | blocking×1 → extraction misquote → pass | passed |
| helen-watches-the-duel | 2 | blocking×1 → pass | passed |
| menelaus-drags-paris | 3 | blocking×1, possession×1 → blocking×1 → possession×1 | **pending** |
| aphrodite-drives-helen-to-bed | 2 | blocking×1 → q-promise×1 | **pending** |
| pandarus-breaks-the-oath | 2 | blocking×1 → pass | passed |
| athena-fires-diomedes | 3 | blocking×1, extraction:ends → injury×1 → blocking×1, injury×1 | **pending** |
| sarpedon-rebukes-hector | 3 | injury×1 → blocking×1, injury×1, q-fact×1 → q-fact×2 | **pending** |
| diomedes-spears-ares | 3 | blocking×3, possession×1 → possession×1, extraction:ends → possession×1, extraction:ends | **pending** |
| glaucus-and-diomedes-trade-armour | 3 | blocking×2, possession×1 → q-fact×1 → pass | passed |
| hector-finds-paris-at-home | 3 | blocking×1 → possession×1 → possession×1 | **pending** |
| hector-farewell-to-andromache | 1 | pass | passed |
| andromache-mourns-a-living-man | 2 | life×1 → pass | passed |
| hector-duels-ajax | 3 | possession×2, q-promise×2 → possession×2 → blocking×1, possession×3 | **pending** |
| priam-sends-idaeus | 1 | pass | passed |
| patroclus-offers-to-cut-hair | 1 | pass | passed |
| both-armies-burn-their-dead | 1 | pass | passed |
| zeus-weighs-the-fates | 3 | blocking×1, possession×1 → life×1, injury×1 → injury×1 | **pending** |
| hector-drives-them-to-the-ships | 3 | blocking×1 → injury×1 → pass | passed |
| hera-and-athena-turned-back | 1 | pass | passed |
| hector-lights-the-watchfires | 1 | pass | passed |
| agamemnon-proposes-flight | 3 | possession×1, q-promise×1 → blocking×1 → pass | passed |
| envoys-feasted-by-achilles | 1 | pass | passed |
| achilles-refuses-the-embassy | 2 | blocking×1 → pass | passed |
| briseis-hears-the-embassy-return | 1 | pass | passed |
| agamemnon-cannot-sleep | 1 | pass | passed |
| diomedes-and-odysseus-raid | 3 | life×1, injury×1 → blocking×1 → possession×1 | **pending** |
| agamemnon-is-wounded | 2 | blocking×1, q-fact×1 → pass | passed |
| odysseus-stands-at-bay | 3 | blocking×1, possession×1, injury×1, q-promise×1 → possession×1 → pass | passed |
| achilles-watches-from-the-stern | 3 | blocking×1, possession×1, q-promise×1 → blocking×1, q-promise×1 → blocking×1 | **pending** |
| patroclus-sent-to-nestor | 2 | q-fact×1 → pass | passed |
| polydamas-reads-the-eagle | 3 | injury×1 → injury×1 → pass | passed |
| sarpedon-tells-glaucus-why | 3 | possession×3, q-promise×1 → possession×1 → pass | passed |
| hector-breaks-the-gate | 3 | blocking×1, time×1 → blocking×1 → pass | passed |
| idomeneus-fights-at-the-ships | 2 | blocking×2, life×1, possession×2 → pass | passed |
| polydamas-counsels-a-pause | 3 | possession×1 → possession×2 → possession×1 | **pending** |
| nestor-finds-the-wounded-kings | 1 | pass | passed |
| hera-seduces-zeus-on-ida | 2 | blocking×1 → pass | passed |
| ajax-fells-hector | 3 | blocking×1, possession×2 → blocking×1, possession×1 → blocking×1, possession×2 | **pending** |
| zeus-wakes-on-ida | 3 | q-promise×1 → q-promise×1 → possession×3 | **pending** |
| apollo-raises-hector | 2 | possession×1, injury×1 → pass | passed |
| ajax-holds-the-ships | 3 | blocking×1, life×1, possession×1, q-fact×1 → possession×1 → blocking×1, life×1 | **pending** |
| hector-fires-the-ships | 5 | possession×1, injury×1, q-promise×1 → blocking×1, possession×1 → blocking×1, life×2, possession×1, q-promise×1 → blocking×1, possession×1 → possession×1, q-promise×1 | **pending** |
---

## 2. Question-checker era: real, false or debatable

119 distinct blocking findings (same scene, layer and quote counted once).

| Layer | Distinct findings | REAL | DEBATABLE | FALSE | Precision (real only) | Real + debatable |
|---|---|---|---|---|---|---|
| Blocking read | 38 | 29 | 9 | 0 | 76% | 100% |
| Typed: possession | 43 | 0 | 1 | 42 | 0% | 2% |
| Typed: injury | 13 | 0 | 4 | 9 | 0% | 31% |
| Typed: life | 8 | 0 | 0 | 8 | 0% | 0% |
| Typed: time | 1 | 1 | 0 | 0 | 100% | 100% |
| Question: facts | 7 | 1 | 2 | 4 | 14% | 43% |
| Question: promises (blocking) | 9 | 0 | 2 | 7 | 0% | 22% |
| **All** | **119** | **31** | **18** | **70** | **26%** | **41%** |
| Question: promises (advisory, final 78 rows, all read) | 78 | 0 | about 3 | about 75 | 0% | 4% |

### Why each layer failed, by cause

**Possession (42 false, 1 debatable):**

| Cause | Findings |
|---|---|
| Two different objects of the same kind: the check keys on "sword", "shield", "bow", "helmet", not on whose | 28 |
| One hand-over, throw or taking read as two conflicting records | 10 |
| A generic object matched across scenes ("the arrow was destroyed" two scenes ago, another man's) | 2 |
| Remnant of a destroyed object (the hilt after the sword shatters) | 1 |
| Line of dialogue given to the wrong speaker by the state extraction | 1 |

**Injury (9 false, 4 debatable):** every one is a wound Homer heals by a god or drops. Hector's "shield arm will not come up" (duel, day 23) fired 6 times on days 25–26; Diomedes' shoulder 5 times; Aeneas' hip twice.

**Life (8 false):**
- 4 are Homer's homonyms (two Pisanders, two Dolopes, two Menesthii).
- 3 are the death and the "presence" in the same sentence.
- 1 is an unnamed "the boy" (Astyanax matched to the dead Adrestus).

**Question facts (1 real, 2 debatable, 4 false):**
- The real catch: "hit bone" against the brief's "grazing the bone" (`sarpedon-rebukes-hector`). It reached the question layer as an extraction dispute, not as a selected fact.
- Debatable: Aeneas back in the front, flagged twice from two ledger facts.
- False: two stale state or attire facts, one over-read general trait, one Homeric homonym.

**Question promises:** the advisory ones are almost all one pattern. A registry fact set up in an earlier scene is listed in a later brief and asked as "The brief has the scene establish: ...". Example, asked of `hector-fires-the-ships`: "Agamemnon's heralds took Briseis from Achilles' hut". Three more are the brief's `outcome` field holding only "yes".

### Every blocking finding, classified

`Qn` numbers follow reading order. "Runs" lists the run folders the finding appeared in (`.` is the first run).

| # | Scene | Runs | Layer | Scene quote (or promise) | Verdict | Reason | Log file |
|---|---|---|---|---|---|---|---|
| Q1 | hector-sends-paris-to-duel | . | blocking | Behind him, his brother is standing up again in the leopard skin. Hector doesn't turn around. | **REAL** | sightline: Hector sees Paris behind him without turning; "again" has no antecedent | `working/logs/gate/hector-sends-paris-to-duel/20261116-225008-17167/gate-blocking-hector-sends-paris-to-duel.json (+ .r2)` |
| Q2 | helen-watches-the-duel | . | blocking | Aethra gets to her feet slowly and says nothing. | **REAL** | posture: "already up", then gets to her feet | `working/logs/gate/helen-watches-the-duel/20261116-225755-17167/gate-blocking-helen-watches-the-duel.json (+ .r2)` |
| Q3 | menelaus-drags-paris | . | blocking | He turns around with it. | **DEBATABLE** | facing is unclear, not wrong | `working/logs/gate/menelaus-drags-paris/20261116-230445-17167/gate-blocking-menelaus-drags-paris.json (+ .r2)` |
| Q4 | menelaus-drags-paris | . | typed:possession | dragging at the spear caught in his shield. | **FALSE** | one hand-over, throw or taking read as two conflicting records (Menelaus's thrown spear is stuck in Paris's shield, Il. 3.355-360) | `working/logs/gate/menelaus-drags-paris/20261116-230445-17167/gate-state-menelaus-drags-paris.json` |
| Q5 | menelaus-drags-paris | recheck | blocking | Menelaus brings the sword down on the ridge of his helmet with both hands, up on his toes, all his weight goin | **DEBATABLE** | Homer 3.362 has the overhead blow; a Homeric shield hangs on a baldric | `working/logs/gate/menelaus-drags-paris/20261116-230445-17167/recheck/gate-blocking-menelaus-drags-paris.json (+ .r2)` |
| Q6 | menelaus-drags-paris | recheck-2 | typed:possession | He throws the hilt down. | **FALSE** | remnant of a destroyed object: the hilt after the sword shatters (Il. 3.363) | `working/logs/gate/menelaus-drags-paris/20261116-230445-17167/recheck-2/gate-state-menelaus-drags-paris.json` |
| Q7 | aphrodite-drives-helen-to-bed | . | blocking | takes his hand, and goes with him to the bed. | **REAL** | Paris is on the bed already (pending; its fix was discarded, see section 6) | `working/logs/gate/aphrodite-drives-helen-to-bed/20261116-231524-17167/gate-blocking-aphrodite-drives-helen-to-bed.json (+ .r2)` |
| Q8 | aphrodite-drives-helen-to-bed | recheck | q-promise | Aphrodite rescued Paris from the duel | **FALSE** | registry fact of the previous scene; appeared only on the re-check (answer variance) | `working/logs/gate/aphrodite-drives-helen-to-bed/20261116-231524-17167/recheck/gate-questions-aphrodite-drives-helen-to-bed-promises.json (+ .a2)` |
| Q9 | pandarus-breaks-the-oath | . | blocking | He sets the notch to the string and draws, string and notch together, back to his chest, until the bronze head | **DEBATABLE** | Homer 4.112-124 never shows him pick the bow up either | `working/logs/gate/pandarus-breaks-the-oath/20261116-232048-17167/gate-blocking-pandarus-breaks-the-oath.json (+ .r2)` |
| Q10 | athena-fires-diomedes | . | blocking | He jumps down off the step. | **REAL** | placed beside the chariot, then jumps down from it | `working/logs/gate/athena-fires-diomedes/20261116-232924-17167/gate-blocking-athena-fires-diomedes.json (+ .r2)` |
| Q11 | athena-fires-diomedes | recheck | typed:injury | He lifts it to his chest and then above his head. | **DEBATABLE** | Athena lightens his limbs after the wound (Il. 5.121-132) before he lifts the stone; second quote is text a fix wrote | `working/logs/gate/athena-fires-diomedes/20261116-232924-17167/recheck/gate-state-athena-fires-diomedes.json` |
| Q12 | athena-fires-diomedes | recheck-2 | blocking | It goes up, into Pandarus's face, beside the nose, by the eye. | **DEBATABLE** | Homer's own wound path (Il. 5.290-293); pending | `working/logs/gate/athena-fires-diomedes/20261116-232924-17167/recheck-2/gate-blocking-athena-fires-diomedes.json (+ .r2)` |
| Q13 | athena-fires-diomedes | recheck-2 | typed:injury | It comes up easily, though the shoulder tears | **DEBATABLE** | Athena lightens his limbs after the wound (Il. 5.121-132) before he lifts the stone; second quote is text a fix wrote | `working/logs/gate/athena-fires-diomedes/20261116-232924-17167/recheck-2/gate-state-athena-fires-diomedes.json` |
| Q14 | sarpedon-rebukes-hector | . | typed:injury | Not limping. | **DEBATABLE** | Apollo heals Aeneas offstage (Il. 5.445-448, 512-516); the scene does not show it | `working/logs/gate/sarpedon-rebukes-hector/20261116-234231-17167/gate-state-sarpedon-rebukes-hector.json` |
| Q15 | sarpedon-rebukes-hector | recheck | blocking | Ajax is on him in three strides, his heel on the man's back, dragging the spear out. | **REAL** | belly wound, falls on his face, yet heel on his back and the spear drawn out | `working/logs/gate/sarpedon-rebukes-hector/20261116-234231-17167/recheck/gate-blocking-sarpedon-rebukes-hector.json (+ .r2)` |
| Q16 | sarpedon-rebukes-hector | recheck | typed:injury | on his own two legs | **DEBATABLE** | Apollo heals Aeneas offstage (Il. 5.445-448, 512-516); the scene does not show it | `working/logs/gate/sarpedon-rebukes-hector/20261116-234231-17167/recheck/gate-state-sarpedon-rebukes-hector.json` |
| Q17 | sarpedon-rebukes-hector | recheck | q-fact | Hector hears it hit bone. | **REAL** | "hit bone" vs "grazing the bone" (Il. 5.661); fixed | `working/logs/gate/sarpedon-rebukes-hector/20261116-234231-17167/recheck/gate-questions-sarpedon-rebukes-hector.json (+ .a2/.a3)` |
| Q18 | sarpedon-rebukes-hector | recheck-2 | q-fact | and he grins at them and goes straight into the front | **DEBATABLE** | Aeneas back in the front: Apollo heals him offstage in Homer; final prose flags it ("no time ... to ask how"). One issue, two ledger facts | `working/logs/gate/sarpedon-rebukes-hector/20261116-234231-17167/recheck-2/gate-questions-sarpedon-rebukes-hector.json (+ .a2/.a3)` |
| Q19 | sarpedon-rebukes-hector | recheck-2 | q-fact | and he grins at them and goes straight into the front | **DEBATABLE** | Aeneas back in the front: Apollo heals him offstage in Homer; final prose flags it ("no time ... to ask how"). One issue, two ledger facts | `working/logs/gate/sarpedon-rebukes-hector/20261116-234231-17167/recheck-2/gate-questions-sarpedon-rebukes-hector.json (+ .a2/.a3)` |
| Q20 | diomedes-spears-ares | . | blocking | he is lifting the strap away from the wound with two fingers and wiping the blood off under it | **REAL** | lifts the shield strap after the shield is off | `working/logs/gate/diomedes-spears-ares/20261116-235310-17167/gate-blocking-diomedes-spears-ares.json (+ .r2)` |
| Q21 | diomedes-spears-ares | . | blocking | Diomedes keeps hold of it. | **REAL** | throws the spear, then "keeps hold of it" (Homer 5.856: a thrust) | `working/logs/gate/diomedes-spears-ares/20261116-235310-17167/gate-blocking-diomedes-spears-ares.json (+ .r2)` |
| Q22 | diomedes-spears-ares | . | blocking | The ichor runs out between his fingers, gold and clear, down his thigh, onto the floor. | **REAL** | hand taken off the wound, then ichor runs between his fingers | `working/logs/gate/diomedes-spears-ares/20261116-235310-17167/gate-blocking-diomedes-spears-ares.json (+ .r2)` |
| Q23 | diomedes-spears-ares | . | typed:possession | it goes away over the back of the chariot and is lost | **FALSE** | one hand-over, throw or taking read as two conflicting records (Athena turns Ares' spear aside, Il. 5.853; second one accepted by hand) | `working/logs/gate/diomedes-spears-ares/20261116-235310-17167/gate-state-diomedes-spears-ares.json` |
| Q24 | diomedes-spears-ares | recheck | typed:possession | Diomedes keeps hold of it. | **FALSE** | two different objects of the same kind (the check keys on "sword"/"shield"/"bow", not on whose) | `working/logs/gate/diomedes-spears-ares/20261116-235310-17167/recheck/gate-state-diomedes-spears-ares.json` |
| Q25 | diomedes-spears-ares | recheck-2 | typed:possession | and is lost | **FALSE** | one hand-over, throw or taking read as two conflicting records (Athena turns Ares' spear aside, Il. 5.853; second one accepted by hand) | `working/logs/gate/diomedes-spears-ares/20261116-235310-17167/recheck-2/gate-state-diomedes-spears-ares.json` |
| Q26 | glaucus-and-diomedes-trade-armour | . | blocking | The corslet comes off over his head, heavy, and the light goes off it onto the dust as he sets it in Diomedes' | **REAL** | corslet comes off over a head still helmeted | `working/logs/gate/glaucus-and-diomedes-trade-armour/20261117-001537-83154/gate-blocking-glaucus-and-diomedes-trade-armour.json (+ .r2)` |
| Q27 | glaucus-and-diomedes-trade-armour | . | blocking | The boy sits back in the dust, his hands still lifted. | **REAL** | hands "still lifted" after clasping the knees | `working/logs/gate/glaucus-and-diomedes-trade-armour/20261117-001537-83154/gate-blocking-glaucus-and-diomedes-trade-armour.json (+ .r2)` |
| Q28 | glaucus-and-diomedes-trade-armour | . | typed:possession | The gold helmet, the gold greaves | **FALSE** | two different objects of the same kind (the check keys on "sword"/"shield"/"bow", not on whose) | `working/logs/gate/glaucus-and-diomedes-trade-armour/20261117-001537-83154/gate-state-glaucus-and-diomedes-trade-armour.json` |
| Q29 | glaucus-and-diomedes-trade-armour | recheck | q-fact | He is red-faced and bareheaded under the dust. | **FALSE** | stale attire fact from scene 1 (gold band) vs "bareheaded" in battle | `working/logs/gate/glaucus-and-diomedes-trade-armour/20261117-001537-83154/recheck/gate-questions-glaucus-and-diomedes-trade-armour.json (+ .a2/.a3)` |
| Q30 | hector-finds-paris-at-home | . | blocking | He sets the bow down across the stool. | **REAL** | lays the bow across the stool he is sitting on | `working/logs/gate/hector-finds-paris-at-home/20261117-002958-83154/gate-blocking-hector-finds-paris-at-home.json (+ .r2)` |
| Q31 | hector-finds-paris-at-home | recheck | typed:possession | the curved bow across his knees | **FALSE** | two different objects of the same kind (the check keys on "sword"/"shield"/"bow", not on whose) | `working/logs/gate/hector-finds-paris-at-home/20261117-002958-83154/recheck/gate-state-hector-finds-paris-at-home.json` |
| Q32 | hector-finds-paris-at-home | recheck-2 | typed:possession | Theano lays the robe across the knees | **FALSE** | one hand-over, throw or taking read as two conflicting records (the prose says "She takes the robe from his mother") | `working/logs/gate/hector-finds-paris-at-home/20261117-002958-83154/recheck-2/gate-state-hector-finds-paris-at-home.json` |
| Q33 | andromache-mourns-a-living-man | . | typed:life | The boy is on the nurse's shoulder. | **FALSE** | unnamed "the boy": Astyanax matched to Adrestus, who died | `working/logs/gate/andromache-mourns-a-living-man/20261117-004414-83154/gate-state-andromache-mourns-a-living-man.json` |
| Q34 | hector-duels-ajax | . | typed:possession | Hector puts the helmet on. | **FALSE** | two different objects of the same kind (the check keys on "sword"/"shield"/"bow", not on whose) | `working/logs/gate/hector-duels-ajax/20261117-005039-83154/gate-state-hector-duels-ajax.json` |
| Q35 | hector-duels-ajax | . | typed:possession | his bow unslung | **FALSE** | two different objects of the same kind (the check keys on "sword"/"shield"/"bow", not on whose) | `working/logs/gate/hector-duels-ajax/20261117-005039-83154/gate-state-hector-duels-ajax.json` |
| Q36 | hector-duels-ajax | . | q-promise | Carries the silver-studded sword Hector gave him after their duel | **FALSE** | the scene shows the gift; the promise is worded as the later state ("carries", "wears") | `working/logs/gate/hector-duels-ajax/20261117-005039-83154/gate-questions-hector-duels-ajax-promises.json (+ .a2)` |
| Q37 | hector-duels-ajax | . | q-promise | Wears the purple belt Ajax gave him after their duel | **FALSE** | the scene shows the gift; the promise is worded as the later state ("carries", "wears") | `working/logs/gate/hector-duels-ajax/20261117-005039-83154/gate-questions-hector-duels-ajax-promises.json (+ .a2)` |
| Q38 | hector-duels-ajax | recheck | typed:possession | a helmet Hector hasn't seen before with a red crest | **FALSE** | two different objects of the same kind (the check keys on "sword"/"shield"/"bow", not on whose) | `working/logs/gate/hector-duels-ajax/20261117-005039-83154/recheck/gate-state-hector-duels-ajax.json` |
| Q39 | hector-duels-ajax | recheck | typed:possession | He puts the sword back in its sheath. | **FALSE** | two different objects of the same kind (the check keys on "sword"/"shield"/"bow", not on whose) | `working/logs/gate/hector-duels-ajax/20261117-005039-83154/recheck/gate-state-hector-duels-ajax.json` |
| Q40 | hector-duels-ajax | recheck-2 | blocking | Then he takes it in one huge hand and slings the baldric over his shoulder. | **REAL** | no free hand for the baldric (pending) | `working/logs/gate/hector-duels-ajax/20261117-005039-83154/recheck-2/gate-blocking-hector-duels-ajax.json (+ .r2)` |
| Q41 | hector-duels-ajax | recheck-2 | typed:possession | on his own head a new helmet with a red crest | **FALSE** | two different objects of the same kind (the check keys on "sword"/"shield"/"bow", not on whose) | `working/logs/gate/hector-duels-ajax/20261117-005039-83154/recheck-2/gate-state-hector-duels-ajax.json` |
| Q42 | hector-duels-ajax | recheck-2 | typed:possession | with his own bow unslung | **FALSE** | two different objects of the same kind (the check keys on "sword"/"shield"/"bow", not on whose) | `working/logs/gate/hector-duels-ajax/20261117-005039-83154/recheck-2/gate-state-hector-duels-ajax.json` |
| Q43 | hector-duels-ajax | recheck-2 | typed:possession | Across from him Ajax is drawing his. | **FALSE** | two different objects of the same kind (the check keys on "sword"/"shield"/"bow", not on whose) | `working/logs/gate/hector-duels-ajax/20261117-005039-83154/recheck-2/gate-state-hector-duels-ajax.json` |
| Q44 | zeus-weighs-the-fates | . | blocking | The two squires were left with the downed team, cutting it free. | **DEBATABLE** | squires unintroduced (Homer 8.113 has them) | `working/logs/gate/zeus-weighs-the-fates/20261117-011619-83154/gate-blocking-zeus-weighs-the-fates.json (+ .r2)` |
| Q45 | zeus-weighs-the-fates | . | typed:possession | stood in the car with his spear | **DEBATABLE** | throws his spear, later "with his spear": a second spear is plausible, not shown | `working/logs/gate/zeus-weighs-the-fates/20261117-011619-83154/gate-state-zeus-weighs-the-fates.json` |
| Q46 | zeus-weighs-the-fates | recheck | typed:life | Eniopeus. | **FALSE** | the death and the "presence" are the same moment (naming the dead man, death throes) | `working/logs/gate/zeus-weighs-the-fates/20261117-011619-83154/recheck/gate-state-zeus-weighs-the-fates.json` |
| Q47 | zeus-weighs-the-fates | recheck | typed:injury | Hector had to grab for the reins himself | **FALSE** | Hector's shield arm from the duel three days earlier; Homer heals him at once (7.272) and never mentions it again; one flags his RIGHT hand | `working/logs/gate/zeus-weighs-the-fates/20261117-011619-83154/recheck/gate-state-zeus-weighs-the-fates.json` |
| Q48 | zeus-weighs-the-fates | recheck-2 | typed:injury | Diomedes threw. | **FALSE** | Diomedes' shoulder from Book 5, two or three days on; Athena healed it; Homer has him throw freely | `working/logs/gate/zeus-weighs-the-fates/20261117-011619-83154/recheck-2/gate-state-zeus-weighs-the-fates.json` |
| Q49 | hector-drives-them-to-the-ships | . | blocking | He has no spear. He has nothing in his hands. | **REAL** | the spear he was holding vanishes | `working/logs/gate/hector-drives-them-to-the-ships/20261117-012811-83154/gate-blocking-hector-drives-them-to-the-ships.json (+ .r2)` |
| Q50 | hector-drives-them-to-the-ships | recheck | typed:injury | Hector throws. | **FALSE** | Hector's shield arm from the duel three days earlier; Homer heals him at once (7.272) and never mentions it again; one flags his RIGHT hand | `working/logs/gate/hector-drives-them-to-the-ships/20261117-012811-83154/recheck/gate-state-hector-drives-them-to-the-ships.json` |
| Q51 | agamemnon-proposes-flight | . | typed:possession | with his cloak pulled close | **FALSE** | two different objects of the same kind (the check keys on "sword"/"shield"/"bow", not on whose) | `working/logs/gate/agamemnon-proposes-flight/20261117-014703-83154/gate-state-agamemnon-proposes-flight.json` |
| Q52 | agamemnon-proposes-flight | . | q-promise | Agamemnon offers Achilles gifts without an apology | **DEBATABLE** | brief says "without an apology"; Homer 9.115-120 has Agamemnon admit fault in council | `working/logs/gate/agamemnon-proposes-flight/20261117-014703-83154/gate-questions-agamemnon-proposes-flight-promises.json (+ .a2)` |
| Q53 | agamemnon-proposes-flight | recheck | blocking | They pour it over his hands and he rubs them together and holds them out to be dried. | **REAL** | leaning on the scepter while both hands are washed | `working/logs/gate/agamemnon-proposes-flight/20261117-014703-83154/recheck/gate-blocking-agamemnon-proposes-flight.json (+ .r2)` |
| Q54 | achilles-refuses-the-embassy | . | blocking | A thousand fires on the plain; Achilles has seen them through the smoke-hole. | **REAL** | plain fires seen through a roof smoke-hole | `working/logs/gate/achilles-refuses-the-embassy/20261117-020118-83154/gate-blocking-achilles-refuses-the-embassy.json (+ .r2)` |
| Q55 | diomedes-and-odysseus-raid | . | typed:life | Rhesus's heels drum twice on the ground | **FALSE** | the death and the "presence" are the same moment (naming the dead man, death throes) | `working/logs/gate/diomedes-and-odysseus-raid/20261117-021804-83154/gate-state-diomedes-and-odysseus-raid.json` |
| Q56 | diomedes-and-odysseus-raid | . | typed:injury | He throws. | **FALSE** | Diomedes' shoulder from Book 5, two or three days on; Athena healed it; Homer has him throw freely | `working/logs/gate/diomedes-and-odysseus-raid/20261117-021804-83154/gate-state-diomedes-and-odysseus-raid.json` |
| Q57 | diomedes-and-odysseus-raid | recheck | blocking | leads them out across the causeway, over the ditch, toward the ships | **REAL** | direction: from the gate, the causeway leads away from the ships | `working/logs/gate/diomedes-and-odysseus-raid/20261117-021804-83154/recheck/gate-blocking-diomedes-and-odysseus-raid.json (+ .r2)` |
| Q58 | diomedes-and-odysseus-raid | recheck-2 | typed:possession | hands them up to him | **FALSE** | two different objects of the same kind (the check keys on "sword"/"shield"/"bow", not on whose); Dolon's bow hung in the tamarisk, Odysseus keeps his own | `working/logs/gate/diomedes-and-odysseus-raid/20261117-021804-83154/recheck-2/gate-state-diomedes-and-odysseus-raid.json` |
| Q59 | agamemnon-is-wounded | . | blocking | He is standing among the Trojans who have turned at the gate, and he is shouting, going along the line of them | **REAL** | both men at the Scaean gate, yet "across the field" from each other | `working/logs/gate/agamemnon-is-wounded/20261117-023046-83154/gate-blocking-agamemnon-is-wounded.json (+ .r2)` |
| Q60 | agamemnon-is-wounded | . | q-fact | as tall as Agamemnon | **FALSE** | a general impression (a head taller than those around him) vs one tall opponent | `working/logs/gate/agamemnon-is-wounded/20261117-023046-83154/gate-questions-agamemnon-is-wounded.json (+ .a2/.a3)` |
| Q61 | odysseus-stands-at-bay | . | blocking | He takes Odysseus's hand in his own. | **DEBATABLE** | Homer 11.487-488 has Menelaus lead him by the hand | `working/logs/gate/odysseus-stands-at-bay/20261117-023953-83154/gate-blocking-odysseus-stands-at-bay.json (+ .r2)` |
| Q62 | odysseus-stands-at-bay | . | typed:possession | The shield comes out of the dust like a wall walking. | **FALSE** | two different objects of the same kind (the check keys on "sword"/"shield"/"bow", not on whose) | `working/logs/gate/odysseus-stands-at-bay/20261117-023953-83154/gate-state-odysseus-stands-at-bay.json` |
| Q63 | odysseus-stands-at-bay | . | typed:injury | and throws | **FALSE** | Diomedes' shoulder from Book 5, two or three days on; Athena healed it; Homer has him throw freely | `working/logs/gate/odysseus-stands-at-bay/20261117-023953-83154/gate-state-odysseus-stands-at-bay.json` |
| Q64 | odysseus-stands-at-bay | . | q-promise | Socus's spear tore the flesh from his ribs, though Athena kept it from his vitals | **DEBATABLE** | Athena's part omitted (Il. 11.437); over-specified promise | `working/logs/gate/odysseus-stands-at-bay/20261117-023953-83154/gate-questions-odysseus-stands-at-bay-promises.json (+ .a2)` |
| Q65 | odysseus-stands-at-bay | recheck | typed:possession | The shield comes out of the dust | **FALSE** | two different objects of the same kind (the check keys on "sword"/"shield"/"bow", not on whose) | `working/logs/gate/odysseus-stands-at-bay/20261117-023953-83154/recheck/gate-state-odysseus-stands-at-bay.json` |
| Q66 | achilles-watches-from-the-stern | . | blocking | a dark stain spreading down from the shoulder under the bronze, a hand clamped over it | **DEBATABLE** | pedantic: a stain spreading below the bronze can be seen | `working/logs/gate/achilles-watches-from-the-stern/20261117-025148-83154/gate-blocking-achilles-watches-from-the-stern.json (+ .r2)` |
| Q67 | achilles-watches-from-the-stern | . | typed:possession | with a tall shield | **FALSE** | two different objects of the same kind (the check keys on "sword"/"shield"/"bow", not on whose) | `working/logs/gate/achilles-watches-from-the-stern/20261117-025148-83154/gate-state-achilles-watches-from-the-stern.json` |
| Q68 | achilles-watches-from-the-stern | .,recheck | q-promise | Paris's three-barbed arrow struck his right shoulder, taking him out of the fighting | **FALSE** | POV: Achilles watches from far off and cannot know whose arrow or which shoulder | `working/logs/gate/achilles-watches-from-the-stern/20261117-025148-83154/gate-questions-achilles-watches-from-the-stern-promises.json (+ .a2)` |
| Q69 | achilles-watches-from-the-stern | recheck | blocking | Past the Myrmidons sitting on the sand, who turn their heads to watch him. | **REAL** | Myrmidons placed inside the courtyard, passed after he leaves it | `working/logs/gate/achilles-watches-from-the-stern/20261117-025148-83154/recheck/gate-blocking-achilles-watches-from-the-stern.json (+ .r2)` |
| Q70 | achilles-watches-from-the-stern | recheck-2 | blocking | his hand going up toward the arrow standing in his right shoulder | **REAL** | right-shoulder arrow, shield (left) arm drops; the quote is text a fix wrote (pending) | `working/logs/gate/achilles-watches-from-the-stern/20261117-025148-83154/recheck-2/gate-blocking-achilles-watches-from-the-stern.json (+ .r2)` |
| Q71 | patroclus-sent-to-nestor | . | q-fact | Achilles is waiting for a name | **FALSE** | stale state fact (sits on the bench, day 10) vs standing on the stern on day 26 (Il. 11.600) | `working/logs/gate/patroclus-sent-to-nestor/20261117-030157-83154/gate-questions-patroclus-sent-to-nestor.json (+ .a2/.a3)` |
| Q72 | polydamas-reads-the-eagle | . | typed:injury | lifts the spear a little | **FALSE** | Hector's shield arm from the duel three days earlier; Homer heals him at once (7.272) and never mentions it again; one flags his RIGHT hand | `working/logs/gate/polydamas-reads-the-eagle/20261117-031050-83154/gate-state-polydamas-reads-the-eagle.json` |
| Q73 | polydamas-reads-the-eagle | recheck | typed:injury | lifts the spear a little in his right hand | **FALSE** | Hector's shield arm from the duel three days earlier; Homer heals him at once (7.272) and never mentions it again; one flags his RIGHT hand | `working/logs/gate/polydamas-reads-the-eagle/20261117-031050-83154/recheck/gate-state-polydamas-reads-the-eagle.json` |
| Q74 | sarpedon-tells-glaucus-why | . | typed:possession | Teucer is at the parapet with the bow | **FALSE** | one hand-over, throw or taking read as two conflicting records (Pandion carries Teucer's bow to him, Il. 12.372) | `working/logs/gate/sarpedon-tells-glaucus-why/20261117-031936-83154/gate-state-sarpedon-tells-glaucus-why.json` |
| Q75 | sarpedon-tells-glaucus-why | . | typed:possession | his hand around the shaft | **FALSE** | generic object matched across scenes: another man's arrow/spear "destroyed" earlier | `working/logs/gate/sarpedon-tells-glaucus-why/20261117-031936-83154/gate-state-sarpedon-tells-glaucus-why.json` |
| Q76 | sarpedon-tells-glaucus-why | . | typed:possession | with the spear still hanging from his shield | **FALSE** | two different objects of the same kind (the check keys on "sword"/"shield"/"bow", not on whose) | `working/logs/gate/sarpedon-tells-glaucus-why/20261117-031936-83154/gate-state-sarpedon-tells-glaucus-why.json` |
| Q77 | sarpedon-tells-glaucus-why | . | q-promise | Teucer's arrow struck his bare arm as he scaled the wall, disabling it from fighting | **FALSE** | model confused; the brief itself says shoulder in one field and arm in another | `working/logs/gate/sarpedon-tells-glaucus-why/20261117-031936-83154/gate-questions-sarpedon-tells-glaucus-why-promises.json (+ .a2)` |
| Q78 | sarpedon-tells-glaucus-why | recheck | typed:possession | One hand closes on a stone and stays closed. | **FALSE** | one hand-over, throw or taking read as two conflicting records (Ajax's stone kills Epicles) | `working/logs/gate/sarpedon-tells-glaucus-why/20261117-031936-83154/recheck/gate-state-sarpedon-tells-glaucus-why.json` |
| Q79 | hector-breaks-the-gate | . | blocking | Up to the right, under the tower, the Lycians are still locked in the breach | **REAL** | left/right not updated after he turns round | `working/logs/gate/hector-breaks-the-gate/20261117-033322-82654/gate-blocking-hector-breaks-the-gate.json (+ .r2)` |
| Q80 | hector-breaks-the-gate | . | typed:time | two days ago | **REAL** | calendar: "two days ago" is three | `working/logs/gate/hector-breaks-the-gate/20261117-033322-82654/gate-state-hector-breaks-the-gate.json` |
| Q81 | hector-breaks-the-gate | recheck | blocking | There are Achaeans in front of him. A dozen. More. They were behind the doors, holding the bars up with their  | **REAL** | nothing behind the gate, then a dozen men behind it | `working/logs/gate/hector-breaks-the-gate/20261117-033322-82654/recheck/gate-blocking-hector-breaks-the-gate.json (+ .r2)` |
| Q82 | idomeneus-fights-at-the-ships | . | blocking | His spear goes in at the throat under the chin and out at the back of the neck. | **DEBATABLE** | spear retrieval elided, as in Homer 13.370-388 | `working/logs/gate/idomeneus-fights-at-the-ships/20261117-034247-82654/gate-blocking-idomeneus-fights-at-the-ships.json (+ .r2)` |
| Q83 | idomeneus-fights-at-the-ships | . | blocking | Alcathous lies on his back with the first spear still standing in his chest, and Oenomaus on his face with the | **DEBATABLE** | two spears, four spear kills: count unclear | `working/logs/gate/idomeneus-fights-at-the-ships/20261117-034247-82654/gate-blocking-idomeneus-fights-at-the-ships.json (+ .r2)` |
| Q84 | idomeneus-fights-at-the-ships | . | typed:life | take a blow on his helmet from Pisander's axe | **FALSE** | Homer's homonyms: two Pisanders (11.122, 13.601, 16.193), two Dolopes (11.302, 15.525), two Menesthii (7.9, 16.173) | `working/logs/gate/idomeneus-fights-at-the-ships/20261117-034247-82654/gate-state-idomeneus-fights-at-the-ships.json` |
| Q85 | idomeneus-fights-at-the-ships | . | typed:possession | I broke mine on Deiphobus's shield. | **FALSE** | speaker misattributed: Meriones says the line (Il. 13.256) | `working/logs/gate/idomeneus-fights-at-the-ships/20261117-034247-82654/gate-state-idomeneus-fights-at-the-ships.json` |
| Q86 | idomeneus-fights-at-the-ships | . | typed:possession | He has a shield and he doesn't lift it. | **FALSE** | two different objects of the same kind (the check keys on "sword"/"shield"/"bow", not on whose) | `working/logs/gate/idomeneus-fights-at-the-ships/20261117-034247-82654/gate-state-idomeneus-fights-at-the-ships.json` |
| Q87 | polydamas-counsels-a-pause | . | typed:possession | his round shield up in front of him | **FALSE** | two different objects of the same kind (the check keys on "sword"/"shield"/"bow", not on whose) | `working/logs/gate/polydamas-counsels-a-pause/20261117-035327-82654/gate-state-polydamas-counsels-a-pause.json` |
| Q88 | polydamas-counsels-a-pause | recheck | typed:possession | with his spear up | **FALSE** | generic object matched across scenes: another man's arrow/spear "destroyed" earlier | `working/logs/gate/polydamas-counsels-a-pause/20261117-035327-82654/recheck/gate-state-polydamas-counsels-a-pause.json` |
| Q89 | polydamas-counsels-a-pause | recheck | typed:possession | with his own shield up in front of him | **FALSE** | two different objects of the same kind (the check keys on "sword"/"shield"/"bow", not on whose) | `working/logs/gate/polydamas-counsels-a-pause/20261117-035327-82654/recheck/gate-state-polydamas-counsels-a-pause.json` |
| Q90 | polydamas-counsels-a-pause | recheck-2 | typed:possession | that wall of a shield on his arm | **FALSE** | two different objects of the same kind (the check keys on "sword"/"shield"/"bow", not on whose) | `working/logs/gate/polydamas-counsels-a-pause/20261117-035327-82654/recheck-2/gate-state-polydamas-counsels-a-pause.json` |
| Q91 | hera-seduces-zeus-on-ida | . | blocking | She watched the head turn from the plain, and the brows go up | **REAL** | head turns "from the plain" though he was looking toward Thrace | `working/logs/gate/hera-seduces-zeus-on-ida/20261117-041843-82654/gate-blocking-hera-seduces-zeus-on-ida.json (+ .r2)` |
| Q92 | ajax-fells-hector | . | blocking | The spear goes out of his hand. | **REAL** | spear already thrown | `working/logs/gate/ajax-fells-hector/20261117-042659-82654/gate-blocking-ajax-fells-hector.json (+ .r2)` |
| Q93 | ajax-fells-hector | .,recheck,recheck-2 | typed:possession | the strap of the sword with the silver studs on its hilt | **FALSE** | two different objects of the same kind (the check keys on "sword"/"shield"/"bow", not on whose) | `working/logs/gate/ajax-fells-hector/20261117-042659-82654/gate-state-ajax-fells-hector.json` |
| Q94 | ajax-fells-hector | . | typed:possession | his shield swings away from his side | **FALSE** | two different objects of the same kind (the check keys on "sword"/"shield"/"bow", not on whose) | `working/logs/gate/ajax-fells-hector/20261117-042659-82654/gate-state-ajax-fells-hector.json` |
| Q95 | ajax-fells-hector | recheck | blocking | Ilioneus falls forward with both hands out in front of him. | **REAL** | falls forward onto a spear standing out of his eye (Homer 14.495: he sits down) | `working/logs/gate/ajax-fells-hector/20261117-042659-82654/recheck/gate-blocking-ajax-fells-hector.json (+ .r2)` |
| Q96 | ajax-fells-hector | recheck-2 | blocking | His empty hands fly open. | **REAL** | still has his shield; the quote is text a fix wrote (pending) | `working/logs/gate/ajax-fells-hector/20261117-042659-82654/recheck-2/gate-blocking-ajax-fells-hector.json (+ .r2)` |
| Q97 | ajax-fells-hector | recheck-2 | typed:possession | over the rim of Hector's shield | **FALSE** | two different objects of the same kind (the check keys on "sword"/"shield"/"bow", not on whose) | `working/logs/gate/ajax-fells-hector/20261117-042659-82654/recheck-2/gate-state-ajax-fells-hector.json` |
| Q98 | zeus-wakes-on-ida | .,recheck | q-promise | Apollo guards Hector | **FALSE** | "guards" vs "restores": wording | `working/logs/gate/zeus-wakes-on-ida/20261117-043915-82654/gate-questions-zeus-wakes-on-ida-promises.json (+ .a2)` |
| Q99 | zeus-wakes-on-ida | recheck-2 | typed:possession | took the helmet off his head | **FALSE** | one hand-over, throw or taking read as two conflicting records (Athena takes them off Ares, Il. 15.125) | `working/logs/gate/zeus-wakes-on-ida/20261117-043915-82654/recheck-2/gate-state-zeus-wakes-on-ida.json` |
| Q100 | zeus-wakes-on-ida | recheck-2 | typed:possession | the shield off his arm | **FALSE** | one hand-over, throw or taking read as two conflicting records (Athena takes them off Ares, Il. 15.125) | `working/logs/gate/zeus-wakes-on-ida/20261117-043915-82654/recheck-2/gate-state-zeus-wakes-on-ida.json` |
| Q101 | zeus-wakes-on-ida | recheck-2 | typed:possession | the spear out of his fist | **FALSE** | one hand-over, throw or taking read as two conflicting records (Athena takes them off Ares, Il. 15.125) | `working/logs/gate/zeus-wakes-on-ida/20261117-043915-82654/recheck-2/gate-state-zeus-wakes-on-ida.json` |
| Q102 | apollo-raises-hector | . | typed:possession | He takes the whip from Cebriones' hand | **FALSE** | one hand-over, throw or taking read as two conflicting records | `working/logs/gate/apollo-raises-hector/20261117-045433-82654/gate-state-apollo-raises-hector.json` |
| Q103 | apollo-raises-hector | . | typed:injury | Hector puts his spear into | **FALSE** | Hector's shield arm from the duel three days earlier; Homer heals him at once (7.272) and never mentions it again; one flags his RIGHT hand | `working/logs/gate/apollo-raises-hector/20261117-045433-82654/gate-state-apollo-raises-hector.json` |
| Q104 | ajax-holds-the-ships | . | blocking | Lycophron comes down off the prow headfirst. He lands on the sand by Ajax's feet | **REAL** | prow vs stern (Butler says prow; the Greek and the staging say stern) | `working/logs/gate/ajax-holds-the-ships/20261117-050201-82654/gate-blocking-ajax-holds-the-ships.json (+ .r2)` |
| Q105 | ajax-holds-the-ships | . | typed:life | Ajax sees the Trojan's spear punch through Meges' shield | **FALSE** | Homer's homonyms: two Pisanders (11.122, 13.601, 16.193), two Dolopes (11.302, 15.525), two Menesthii (7.9, 16.173) | `working/logs/gate/ajax-holds-the-ships/20261117-050201-82654/gate-state-ajax-holds-the-ships.json` |
| Q106 | ajax-holds-the-ships | . | typed:possession | a shield of four hides on his shoulder | **FALSE** | two different objects of the same kind (the check keys on "sword"/"shield"/"bow", not on whose) | `working/logs/gate/ajax-holds-the-ships/20261117-050201-82654/gate-state-ajax-holds-the-ships.json` |
| Q107 | ajax-holds-the-ships | . | q-fact | Lampus's son. | **FALSE** | Homer's second Dolops (son of Lampus, 15.525); a fair name-collision flag, not an error | `working/logs/gate/ajax-holds-the-ships/20261117-050201-82654/gate-questions-ajax-holds-the-ships.json (+ .a2/.a3)` |
| Q108 | ajax-holds-the-ships | recheck | typed:possession | They hit his helmet, one, and another | **FALSE** | two different objects of the same kind (the check keys on "sword"/"shield"/"bow", not on whose) | `working/logs/gate/ajax-holds-the-ships/20261117-050201-82654/recheck/gate-state-ajax-holds-the-ships.json` |
| Q109 | ajax-holds-the-ships | recheck-2 | blocking | He can't stop it going back after that. | **REAL** | unclear "He"/"it" (pending) | `working/logs/gate/ajax-holds-the-ships/20261117-050201-82654/recheck-2/gate-blocking-ajax-holds-the-ships.json (+ .r2)` |
| Q110 | ajax-holds-the-ships | recheck-2 | typed:life | while he's bent over his horses, the reins in his hands | **FALSE** | the death and the "presence" are the same moment (naming the dead man, death throes) | `working/logs/gate/ajax-holds-the-ships/20261117-050201-82654/recheck-2/gate-state-ajax-holds-the-ships.json` |
| Q111 | hector-fires-the-ships | . | typed:possession | The sword, with the silver studs on the hilt | **FALSE** | two different objects of the same kind (the check keys on "sword"/"shield"/"bow", not on whose) | `working/logs/gate/hector-fires-the-ships/20261117-051345-82654/gate-state-hector-fires-the-ships.json` |
| Q112 | hector-fires-the-ships | . | typed:injury | Achilles watches him step back from the stern and swing. | **FALSE** | Hector's shield arm from the duel three days earlier; Homer heals him at once (7.272) and never mentions it again; one flags his RIGHT hand | `working/logs/gate/hector-fires-the-ships/20261117-051345-82654/gate-state-hector-fires-the-ships.json` |
| Q113 | hector-fires-the-ships | .,partial-1,partial-2 | q-promise | Hector set an Achaean ship on fire | **FALSE** | Homer 16.122-123: the Trojans throw the fire; pending | `working/logs/gate/hector-fires-the-ships/20261117-051345-82654/gate-questions-hector-fires-the-ships-promises.json (+ .a2)` |
| Q114 | hector-fires-the-ships | recheck,recheck-2 | blocking | Hector takes a torch from the man behind him and throws it up onto the stern | **REAL** | no free hand for the torch; the quote is text a fix wrote | `working/logs/gate/hector-fires-the-ships/20261117-051345-82654/recheck/gate-blocking-hector-fires-the-ships.json (+ .r2)` |
| Q115 | hector-fires-the-ships | recheck,partial-1 | typed:possession | Achilles' own sword, with the silver studs on the hilt | **FALSE** | two different objects of the same kind (the check keys on "sword"/"shield"/"bow", not on whose) | `working/logs/gate/hector-fires-the-ships/20261117-051345-82654/recheck/gate-state-hector-fires-the-ships.json` |
| Q116 | hector-fires-the-ships | partial-1 | blocking | He's on a ship's bench, low down in the hull of a black ship with a high curved stern, and he has a long pike  | **REAL** | standing low in the hull he cannot strike down over the side; fix-era prose | `working/logs/gate/hector-fires-the-ships/20261117-051345-82654/partial-1/gate-blocking-hector-fires-the-ships.json (+ .r2)` |
| Q117 | hector-fires-the-ships | partial-1 | typed:life | Menesthius to the first. | **FALSE** | Homer's homonyms: two Pisanders (11.122, 13.601, 16.193), two Dolopes (11.302, 15.525), two Menesthii (7.9, 16.173) | `working/logs/gate/hector-fires-the-ships/20261117-051345-82654/partial-1/gate-state-hector-fires-the-ships.json` |
| Q118 | hector-fires-the-ships | partial-1 | typed:life | Pisander, the best spear among them after Patroclus | **FALSE** | Homer's homonyms: two Pisanders (11.122, 13.601, 16.193), two Dolopes (11.302, 15.525), two Menesthii (7.9, 16.173) | `working/logs/gate/hector-fires-the-ships/20261117-051345-82654/partial-1/gate-state-hector-fires-the-ships.json` |
| Q119 | hector-fires-the-ships | recheck-2,partial-2 | typed:possession | on its baldric across his shoulder | **FALSE** | two different objects of the same kind (the check keys on "sword"/"shield"/"bow", not on whose) | `working/logs/gate/hector-fires-the-ships/20261117-051345-82654/recheck-2/gate-state-hector-fires-the-ships.json` |
---

## 3. The question layer in detail

All figures measured, from the replayed prompts joined to the logged answers.

| | Count |
|---|---|
| Runs | 100 |
| Fact questions generated (asked + cut by the cap) | 21,104 |
| Asked | 2,919 (14%) |
| Cut by the 30 cap | 18,185 (86%) |
| Runs at the cap | 97 of 100 (the other 3 are `hector-sends-paris-to-duel`, 2–4 questions) |
| Generated per run | median 205, max 467 |
| Holding facts never turned into a question: no subject | 64 per run on average (27 at the start, 86 at the end) |
| Holding facts skipped: subject not in the scene | 439 per run on average |
| Distinct facts behind the 2,919 questions | 245 |
| "Yes" answers, first asking | 11 (0.4%) |
| "Yes" answers, second asking | 14 (0.5%) |
| Yes from both | 8 |
| Split, sent to a third asking | 9 |
| Third asking said yes | 7 |
| Findings made (two yeses, quote verified) | 11 |
| ... cleared by the source check | 3 |
| ... merged with a typed-state finding on the same quote | 1 |
| ... sent to a fix | 7 (1 real) |
| Promise questions asked | 1,274 (12.7 per run) |
| Promises: yes/yes | 1,017 (80%) |
| Promises: no/no | 176 (14%): 163 advisory, 13 blocking |
| Promises: split | 81 (6%) |

### What the 30 were about

| Type | Asked | Share of asked | Cut by the cap |
|---|---|---|---|
| trait | 1,881 | 64% | 113 |
| relationship | 676 | 23% | 613 |
| physical | 317 | 11% | 3,481 |
| world | 30 | 1% | 3,414 |
| dispute (from extraction) | 15 | 0.5% | 0 |
| knowledge | 0 | 0% | 4,053 |
| timeline | 0 | 0% | 1,583 |
| type unknown (fact id since replaced) | – | – | 4,928 |

- The cap cuts from the end of a list sorted by type (`QUESTION_TYPES`: trait first), then by scene order.
- So from about scene 20 on, the 30 are the oldest trait facts about whoever is on stage.
- In 8 of the 44 first runs all 30 were traits (11 counting runs with 29 traits and one dispute).
- The same facts are asked again and again:

| Times asked | Fact |
|---|---|
| 60 | Agamemnon wears a purple cloak, a gold band around his head, and a ring on his right hand. |
| 60 | Agamemnon is a heavy man with gray in his beard. |
| 60 | Ajax is enormous in build and sits on a bench at the assembly. |
| 59 | Menelaus has yellow hair. |
| 56 | Hector has a beard on his face. |
| 49 | Achilles likes his lamb off the bone with the fat crisp at the edges. |
| 49 | Achilles sleeps on his back with one arm over his face, falling asleep at once after nights he wants Briseis. |

Mostly trivia. The facts that produced the open checker's real catches (who was where, what happened in what order, what day it was) are `physical`, `world`, `knowledge` and `timeline`, the types the cap removes.

### Representative questions, verbatim

Good (a real or arguable contradiction is reachable):

1. `sarpedon-rebukes-hector`, re-check (a dispute; the layer's one real catch):
   > 1. Established in sarpedon-rebukes-hector: "Tlepolemus's spear pierced his left thigh, the point grazing the bone"
   > Its words there: "Tlepolemus's took Sarpedon in the left thigh and went deep, hard enough that Hector saw him jerk as the point struck bone."
   > Question: A reader took this scene to change the fact: "Hector hears it hit bone.". Does the scene contradict the fact, so that it no longer holds as stated? Answer `no` only when the scene clearly leaves it standing (it adds detail, or shows the change happening); if you can't tell, answer `yes` and quote the words the reader took as the change.
2. `sarpedon-rebukes-hector` (yes/yes; debatable):
   > 17. Established in athena-fires-diomedes: "Diomedes hurls a huge stone at Aeneas's hip, breaking the joint and tearing the skin open to the bone, so Aeneas goes down on his knees half-conscious."
   > Its words there: "He hears the joint go, a wet crunch, and the stone's rough edge tears the skin open to the bone."
   > Question: Does this scene describe Aeneas or what Aeneas has or can do in a way this fact rules out?
3. `ajax-holds-the-ships` (yes/yes; a true name collision, Homer's own):
   > 12. Established in odysseus-stands-at-bay: "Dolops is the son of Clytius and had a laugh audible from the next ship."
   > Its words there: "Dolops, Clytius's son, who had a laugh you could hear from the next ship."
   > Question: Does this scene show or say something about Dolops that this fact rules out?

Bad (trivia, or a fact that should have ended):

4. `hector-fires-the-ships`:
   > 14. Established in patroclus-watches-the-idle-days: "Achilles likes his lamb off the bone with the fat crisp at the edges."
   > Its words there: "Lamb, off the bone, the fat crisp at the edges the way he likes it."
   > Question: Does this scene show or say something about Achilles that this fact rules out?
5. `hector-fires-the-ships` (asked in 60 runs; made a false finding in `glaucus-and-diomedes-trade-armour`):
   > 1. Established in chryses-ransom-refused: "Agamemnon wears a purple cloak, a gold band around his head, and a ring on his right hand."
   > Its words there: "A purple cloak, a gold band around his head."
   > Question: Does this scene show or say something about Agamemnon that this fact rules out?
6. `hector-fires-the-ships`:
   > 5. Established in briseis-led-from-the-hut: "Achilles sleeps on his back with one arm over his face, falling asleep at once after nights he wants Briseis."
   > Its words there: "afterward he sleeps at once, on his back, with one arm over his face."
   > Question: Does this scene show or say something about Achilles that this fact rules out?
7. `hector-fires-the-ships` (a day-10 state asked as a permanent trait; made 3 false findings in 2 scenes):
   > 10. Established in briseis-led-from-the-hut: "Since he came back from the assembly, Achilles has sat on the bench against the wall of his own hut, facing the ships."
   > Its words there: "Achilles is sitting on the bench against the wall of his own hut, facing the ships, as he has sat since he came back."
   > Question: Does this scene show or say something about Achilles that this fact rules out?
8. `agamemnon-is-wounded` (yes/yes; false):
   > 16. Established in helen-watches-the-duel: "Agamemnon stands a head taller than the men around him and looks very much like a king."
   > Its words there: "a head taller than the men around him"
   > Question: Does this scene show or say something about Agamemnon that this fact rules out?
9. `hector-breaks-the-gate`:
   > 25. Established in andromache-mourns-a-living-man: "Hector's cloak hangs on a peg by the door of his house, with his second spear behind it."
   > Its words there: "his cloak hanging on its peg by the door and his second spear behind it"
   > Question: Does this scene describe Hector or what Hector has or can do in a way this fact rules out?
10. `hector-fires-the-ships`, promises (blocking, false: Homer 16.122 has the Trojans throw the fire; the fix it triggered wrote a blocking error):
    > 14. The brief has the scene establish: "Hector set an Achaean ship on fire"
    > Question: Does this scene establish it?
11. `odysseus-beats-thersites`, promises (advisory noise):
    > 1. The brief's outcome: "yes"
    > Question: Does this scene deliver it?

---

## 4. Open-checker era

### Counts (measured)

| | Nov 8 (old draft, 93 scenes) | Nov 15–16 (new draft, scenes 1–9) |
|---|---|---|
| Gate runs with a check | 135 (93 first runs, 42 re-checks) | 21 (10 first runs, 11 re-checks) |
| Raw findings, reading 1 | 32 | 4 |
| Raw findings, reading 2 | 30 | 2 |
| Union (distinct per run) | 43 | 4 |
| Found by both readings | 19 (44% of the union) | 2 (50%) |
| Only reading 1 / only reading 2 | 13 / 11 | 2 / 0 |
| Runs with no finding | 98 (73%) | 18 (86%) |
| First runs with a finding | 28 of 93 (30%) | 2 of 10 |
| Tool calls per reading | 4.6 | 5.0 |

By code, Nov 8 raw findings (62): TIM 24, PHY 18, TRT 6, KNO 4, PRM 4, REL 3, WLD 3. By where the broken fact lives: an earlier scene 44, a bible or the calendar 13, the brief 5.

The Nov 8 gate had no blocking read and no typed-state checks, so the two eras' stop rates are not like for like.

### Real, false or debatable (all 47 distinct findings; judged from the finding text)

| | Count | Share |
|---|---|---|
| REAL | 33 | 70% |
| DEBATABLE | 9 | 19% |
| FALSE | 5 | 11% |

- 4 of the 5 false and 1 debatable are Homer's own inconsistencies or wording (gold vs bronze floor; who built Laomedon's wall; "you went to his hut").
- **The two readings:** of the 21 findings both readings made, 18 were real (86%). Of the 26 only one reading made, 15 were real (58%). Keeping only agreed findings would raise precision to 86% and lose 15 of the 33 real ones.
- Repeats: one real error (sword vs spear for Aphrodite's wound) came back unfixed on two re-checks; one false one (Laomedon's wall) on one.

### What the real catches were, and whether a question could have made them

| Kind | Real findings | Example |
|---|---|---|
| A character misremembers or the narration contradicts how an earlier scene happened | 10 | Apollo healed Hector at the ford, remembered as "by the ships" (O13); who held the steering oar (O46/O47) |
| Calendar: "this morning", "last night", "nine days ago" | 7 | "Everything Odysseus had offered last night" was two nights ago (O4) |
| Order of events across scenes | 5 | Odysseus sees Briseis led off before he sails; she was led off after (O29) |
| Reference bible or series canon | 3 | Andromache "nine" at her father's funeral, but Thebe fell during the war (O9) |
| Camp geography | 2 | The Ithacans "at the far end"; they are in the middle (O32) |
| Kinship said wrongly in dialogue | 2 | "your grandfather" for Laothoe's father, said to Hector (O22) |
| Logic | 2 | "a dead man's plain bronze" that is the living Diomedes' (O38) |
| Object or life across scenes | 2 | Pedasus, killed the day before, yoked again (O3); Ajax's belt worn after Hector took it off (O1) |

- Only 6 of the 68 raw findings named a ledger fact; the rest cited prose, a bible or the calendar directly. That is the measured ceiling on what fact questions could have reached, before selection.
- After selection it is lower still: the cap removed all knowledge and timeline questions (section 3).
- The typed time check could reach some calendar errors with a number in them ("nine days ago"). It fired once in the question era and was right.
- Nothing in the question-era gate looks at event order, remembered events, geography or the bibles.

### Every open-checker finding, classified

| # | Scene | Run | Readings | Code | Scene quote | Verdict | Kind: reason | Log file |
|---|---|---|---|---|---|---|---|---|
| O1 | achilles-kills-hector | 20261108 . | 1 | PHY | the purple belt Ajax gave him had worked round so the knot sat against his hip | **REAL** | object: belt taken off and sent to Troy, worn again | `working/logs/gate/achilles-kills-hector/20261108-062415-61316/gate-check-achilles-kills-hector.json (+ .r2)` |
| O2 | achilles-meets-aeneas | 20261108 . | 1 | TIM | A man came out of the Trojan front before the lines had closed. | **REAL** | order: lines already closed in the scene before | `working/logs/gate/achilles-meets-aeneas/20261108-055017-61316/gate-check-achilles-meets-aeneas.json (+ .r2)` |
| O3 | achilles-renounces-his-wrath | 20261108 . | 1+2 | PHY | Outside the gate Automedon and Alcimus were yoking the horses, the two that weren't mortal and the b | **REAL** | object/life: Pedasus died the day before (Il. 16.467), yoked again | `working/logs/gate/achilles-renounces-his-wrath/20261108-054051-61316/gate-check-achilles-renounces-his-wrath.json (+ .r2)` |
| O4 | achilles-renounces-his-wrath | 20261108 . | 1+2 | TIM | Everything Odysseus had offered last night, he would give. | **REAL** | calendar: "last night" was two nights ago | `working/logs/gate/achilles-renounces-his-wrath/20261108-054051-61316/gate-check-achilles-renounces-his-wrath.json (+ .r2)` |
| O5 | achilles-watches-from-the-stern | 20261108 . | 1 | PRM | Someone shouted, a long way off. The shout had a name in it he couldn't hear. | **DEBATABLE** | brief: brief names Idomeneus; scene has "someone" (POV-limited) | `working/logs/gate/achilles-watches-from-the-stern/20261108-040612-61316/gate-check-achilles-watches-from-the-stern.json (+ .r2)` |
| O6 | achilles-watches-from-the-stern | 20261108 . | 2 | PHY | They came at the gate in the wall at full stretch, through it, and along the inside, past the Cretan | **REAL** | geography: Ajax's and Achilles' ships are at opposite ends (Il. 11.5-9) | `working/logs/gate/achilles-watches-from-the-stern/20261108-040612-61316/gate-check-achilles-watches-from-the-stern.json (+ .r2)` |
| O7 | agamemnon-proposes-flight | 20261108 . | 1+2 | TIM | the shout he had heard on the sand that morning when this same boy told them to refuse everything | **REAL** | calendar: "that morning" was the morning before | `working/logs/gate/agamemnon-proposes-flight/20261108-034054-61316/gate-check-agamemnon-proposes-flight.json (+ .r2)` |
| O8 | agamemnon-proposes-flight | 20261108 . | 2 | KNO | I'll tell you what I've thought since the day you went to Achilles' hut and took the girl. | **FALSE** | homer: Homer's own words (Il. 9.106-107: 'you went and took the girl from his hut') | `working/logs/gate/agamemnon-proposes-flight/20261108-034054-61316/gate-check-agamemnon-proposes-flight.json (+ .r2)` |
| O9 | andromache-mourns-a-living-man | 20261108 . | 1+2 | TIM | She'd been nine, standing with her mother at the edge of the crowd while the bronze went black in th | **REAL** | bible: Thebe fell during the war; she cannot have been nine | `working/logs/gate/andromache-mourns-a-living-man/20261108-030917-61316/gate-check-andromache-mourns-a-living-man.json (+ .r2)` |
| O10 | andromache-mourns-a-living-man | 20261108 recheck | 1 | TRT | He'd killed her father in the gate and then stood back from the body as if he'd been shown something | **REAL** | memory: who burned Eetion (Il. 6.416-419: Achilles did) | `working/logs/gate/andromache-mourns-a-living-man/20261108-030917-61316/recheck/gate-check-andromache-mourns-a-living-man.json (+ .r2)` |
| O11 | antilochus-brings-the-news | 20261108 . | 2 | KNO | that while he was still alive, the best of the Myrmidons would go down under Trojan hands and not se | **DEBATABLE** | homer: Homer has both (Il. 17.408-411 vs 18.9-11) | `working/logs/gate/antilochus-brings-the-news/20261108-052632-61316/gate-check-antilochus-brings-the-news.json (+ .r2)` |
| O12 | antilochus-cuts-past-menelaus | 20261108 . | 2 | PRM | Nobody saw what took it. He saw Eumelus's mares pull away and his own horses slacken under him, and  | **DEBATABLE** | brief: gods of the brief not named in the scene | `working/logs/gate/antilochus-cuts-past-menelaus/20261108-064013-61316/gate-check-antilochus-cuts-past-menelaus.json (+ .r2)` |
| O13 | apollo-hides-hector-in-mist | 20261108 . | 1+2 | PHY | He had heard it yesterday by the ships when it lifted him off the ground with his ribs mending under | **REAL** | memory: healed at the ford, remembered as by the ships | `working/logs/gate/apollo-hides-hector-in-mist/20261108-055241-61316/gate-check-apollo-hides-hector-in-mist.json (+ .r2)` |
| O14 | apollo-hides-hector-in-mist | 20261108 . | 2 | PRM | He'd been told to wait, he thought, and a god had told him, and a man who goes against a god's word  | **DEBATABLE** | brief: nuance of a brief beat | `working/logs/gate/apollo-hides-hector-in-mist/20261108-055241-61316/gate-check-apollo-hides-hector-in-mist.json (+ .r2)` |
| O15 | apollo-raises-hector | 20261108 . | 2 | TIM | He'd stood before it at noon and reckoned a morning's work with ropes and oxen. | **REAL** | calendar: "at noon" was yesterday near dusk | `working/logs/gate/apollo-raises-hector/20261108-045047-61316/gate-check-apollo-raises-hector.json (+ .r2)` |
| O16 | athena-fires-diomedes | 20261108 . | 1+2 | TIM | Diomedes had been on the sand that morning when Achilles threw down the staff, and he'd seen the dus | **DEBATABLE** | calendar: "that morning when Achilles threw down the staff" can be read correctly; both readings flagged it | `working/logs/gate/athena-fires-diomedes/20261108-165120-62958/gate-check-athena-fires-diomedes.json (+ .r2)` |
| O17 | athena-fires-diomedes | 20261108 recheck | 1+2 | PHY | He drew his sword, came in close and drove it at the hand that held the robe shut. | **REAL** | memory: sword here, spear in the later scene (Il. 5.336: spear); repeated across two re-checks unfixed | `working/logs/gate/athena-fires-diomedes/20261108-165120-62958/recheck/gate-check-athena-fires-diomedes.json (+ .r2)` |
| O18 | athena-fires-diomedes | 20261108 recheck-2 | 2 | PHY | He came in close and drove his sword at the hand that held the robe shut. | **REAL** | memory: sword here, spear in the later scene (Il. 5.336: spear); repeated across two re-checks unfixed | `working/logs/gate/athena-fires-diomedes/20261108-165120-62958/recheck-2/gate-check-athena-fires-diomedes.json (+ .r2)` |
| O19 | both-armies-burn-their-dead | 20261108 . | 1+2 | TRT | He was an old man and he'd done this before, in Sparta, in a hall with a fire, pouring the wine whil | **REAL** | memory: Priam's hall moved to Sparta | `working/logs/gate/both-armies-burn-their-dead/20261108-031946-61316/gate-check-both-armies-burn-their-dead.json (+ .r2)` |
| O20 | briseis-counts-the-pyres | 20261115 . | 1+2 | TIM | The mules are screaming before the light goes. | **REAL** | order: order of the same events reversed between two scenes | `working/logs/gate/briseis-counts-the-pyres/20261115-191127-75417/gate-check-briseis-counts-the-pyres.json (+ .r2)` |
| O21 | briseis-led-from-the-hut | 20261116 recheck | 1 | TIM | Nine nights she stood in it and watched the pyres. | **DEBATABLE** | count: nine nights vs about seven: pedantic | `working/logs/gate/briseis-led-from-the-hut/20261116-135733-18652/recheck/gate-check-briseis-led-from-the-hut.json (+ .r2)` |
| O22 | hector-alone-at-the-gate | 20261108 . | 1 | REL | If he's got them alive we'll ransom them, there's bronze, there's gold, your grandfather gave enough | **REAL** | kinship: 'your grandfather' for Laothoe's father, said to Hector (Il. 22.51) | `working/logs/gate/hector-alone-at-the-gate/20261108-061305-61316/gate-check-hector-alone-at-the-gate.json (+ .r2)` |
| O23 | hector-alone-at-the-gate | 20261108 . | 1 | PHY | where Andromache had stood with the child on her hip and told him to put the army | **DEBATABLE** | memory: where she stood, who held the child: compressed memory | `working/logs/gate/hector-alone-at-the-gate/20261108-061305-61316/gate-check-hector-alone-at-the-gate.json (+ .r2)` |
| O24 | hector-drives-them-to-the-ships | 20261108 . | 1 | TIM | Hector had shouted *girl* at his back this morning, and here he was, first over. | **REAL** | calendar: "this morning" was after noon | `working/logs/gate/hector-drives-them-to-the-ships/20261108-032740-61316/gate-check-hector-drives-them-to-the-ships.json (+ .r2)` |
| O25 | hector-drives-them-to-the-ships | 20261108 recheck | 1 | PHY | They were in through the gate. They were among the ships. | **REAL** | bible: in through the gate a day early (canon: day 26), and against its own next lines | `working/logs/gate/hector-drives-them-to-the-ships/20261108-032740-61316/recheck/gate-check-hector-drives-them-to-the-ships.json (+ .r2)` |
| O26 | hector-finds-paris-at-home | 20261108 . | 2 | PRM | His mother came across the courtyard to him with her hands already out. She took his right hand in b | **DEBATABLE** | brief: Laodice missing (Il. 6.252) | `working/logs/gate/hector-finds-paris-at-home/20261108-030216-61316/gate-check-hector-finds-paris-at-home.json (+ .r2)` |
| O27 | hector-fires-the-ships | 20261108 . | 1+2 | TIM | they'd been waiting nine days for anyone to tell them anything | **REAL** | calendar: nine days idle vs sixteen | `working/logs/gate/hector-fires-the-ships/20261108-050000-61316/gate-check-hector-fires-the-ships.json (+ .r2)` |
| O28 | hector-sends-paris-to-duel | 20261108 . | 2 | TIM | The watch on the tomb of Aesyetes had sent word in the night that the Achaean camp was in uproar, me | **REAL** | order: a night report of something that happens after dawn | `working/logs/gate/hector-sends-paris-to-duel/20261108-023016-61316/gate-check-hector-sends-paris-to-duel.json (+ .r2)` |
| O29 | odysseus-returns-chryseis | 20261116 . | 1+2 | PHY | Odysseus saw her go past the ships this morning, before they sailed, with a cloak over her head. | **REAL** | order: Odysseus sees her led off before sailing; she was led off after he sailed | `working/logs/gate/odysseus-returns-chryseis/20261116-205650-59386/gate-check-odysseus-returns-chryseis.json (+ .r2)` |
| O30 | odysseus-returns-chryseis | 20261116 . | 1 | TIM | Ten days ago he stood on the beach with the rest of them and watched that hand hold the god's wreath | **DEBATABLE** | calendar: ten days vs nine: off by one | `working/logs/gate/odysseus-returns-chryseis/20261116-205650-59386/gate-check-odysseus-returns-chryseis.json (+ .r2)` |
| O31 | pandarus-breaks-the-oath | 20261108 . | 1+2 | WLD | They sat on the gold floor of Zeus's hall with their cups, and the light came up off the floor into  | **FALSE** | homer: Homer's own: golden floor (Il. 4.2) vs bronze-floored house (1.426) | `working/logs/gate/pandarus-breaks-the-oath/20261108-024219-61316/gate-check-pandarus-breaks-the-oath.json (+ .r2)` |
| O32 | patroclus-ghost-begs-burial | 20261108 . | 1 | WLD | somebody laughing at the far end where the Ithacans were. | **REAL** | geography: Odysseus's ships are in the middle (Il. 11.5-6) | `working/logs/gate/patroclus-ghost-begs-burial/20261108-063230-61316/gate-check-patroclus-ghost-begs-burial.json (+ .r2)` |
| O33 | polydamas-counsels-a-pause | 20261108 . | 1+2 | TIM | At the trench, before the snake fell, the gold ring on that spear had been a hand's breadth from his | **REAL** | order: threat placed before the snake fell | `working/logs/gate/polydamas-counsels-a-pause/20261108-043532-61316/gate-check-polydamas-counsels-a-pause.json (+ .r2)` |
| O34 | polydamas-reads-the-eagle | 20261108 . | 1+2 | TIM | He'd done this on the Batieia nine days ago and it was easier now, because they'd learned to listen. | **REAL** | calendar: nine days ago vs three | `working/logs/gate/polydamas-reads-the-eagle/20261108-041436-61316/gate-check-polydamas-reads-the-eagle.json (+ .r2)` |
| O35 | priam-opens-the-gates | 20261108 . | 2 | KNO | He looked for the crest of horsehair over bronze that wasn't Hector's own armour and was. | **FALSE** | brief: registry knowledge echoed as a promise | `working/logs/gate/priam-opens-the-gates/20261108-060831-61316/gate-check-priam-opens-the-gates.json (+ .r2)` |
| O36 | sarpedon-rebukes-hector | 20261108 . | 2 | KNO | They'd seen it from the Trojan front and some of them had stopped fighting to watch. | **REAL** | memory: "some stopped to watch" vs "none had stopped" (the reading gave no reason) | `working/logs/gate/sarpedon-rebukes-hector/20261108-025136-61316/gate-check-sarpedon-rebukes-hector.json (+ .r2)` |
| O37 | sarpedon-tells-glaucus-why | 20261108 . | 1+2 | TIM | After Troy is taken and the ships have gone home, the wall will last one more season. | **REAL** | bible: series canon: wall destroyed four days after sailing, not 'one more season' | `working/logs/gate/sarpedon-tells-glaucus-why/20261108-042044-61316/gate-check-sarpedon-tells-glaucus-why.json (+ .r2)` |
| O38 | sarpedon-tells-glaucus-why | 20261108 recheck | 1+2 | PHY | Glaucus was at his shoulder in a dead man's plain bronze, the plate punched through below the right  | **REAL** | logic: 'a dead man's bronze' that is Diomedes', who is alive | `working/logs/gate/sarpedon-tells-glaucus-why/20261108-042044-61316/recheck/gate-check-sarpedon-tells-glaucus-why.json (+ .r2)` |
| O39 | spoils-of-the-night-raid | 20261108 . | 1+2 | TIM | I've fought the Trojans longer than either of you has been alive. | **REAL** | logic: Nestor fighting Trojans longer than grown men have lived | `working/logs/gate/spoils-of-the-night-raid/20261108-035658-61316/gate-check-spoils-of-the-night-raid.json (+ .r2)` |
| O40 | the-gods-come-to-blows | 20261108 . | 1+2 | TIM | You swore to your mother this morning that you'd fight for the Achaeans, and here you are with the T | **REAL** | calendar: "this morning" was four days ago | `working/logs/gate/the-gods-come-to-blows/20261108-060354-61316/gate-check-the-gods-come-to-blows.json (+ .r2)` |
| O41 | the-gods-come-to-blows | 20261108 . | 1 | TRT | I built his wall. You minded his cattle up in the folds of Ida. | **FALSE** | homer: Homer's own: Il. 21.441-449 (Poseidon alone) vs 7.452 (both); repeated on the re-check | `working/logs/gate/the-gods-come-to-blows/20261108-060354-61316/gate-check-the-gods-come-to-blows.json (+ .r2)` |
| O42 | the-gods-come-to-blows | 20261108 recheck | 1+2 | TRT | I built his wall. You minded his cattle up in the folds of Ida. | **FALSE** | homer: Homer's own: Il. 21.441-449 (Poseidon alone) vs 7.452 (both); repeated on the re-check | `working/logs/gate/the-gods-come-to-blows/20261108-060354-61316/recheck/gate-check-the-gods-come-to-blows.json (+ .r2)` |
| O43 | zeus-weeps-blood-for-sarpedon | 20261108 . | 1+2 | REL | The Earth-shaker had a grandson's son lying at the ships already, killed by a spear that was thrown  | **REAL** | kinship: Amphimachus is Poseidon's grandson (Il. 13.207) | `working/logs/gate/zeus-weeps-blood-for-sarpedon/20261108-050850-61316/gate-check-zeus-weeps-blood-for-sarpedon.json (+ .r2)` |
| O44 | zeus-weighs-hectors-fate | 20261108 . | 1+2 | PHY | He had stood on this floor with his own son dying in the Lycian line and said the same thing in near | **REAL** | memory: Olympus vs Ida for an earlier exchange / where the scales were | `working/logs/gate/zeus-weighs-hectors-fate/20261108-061827-61316/gate-check-zeus-weighs-hectors-fate.json (+ .r2)` |
| O45 | zeus-weighs-hectors-fate | 20261108 recheck | 1 | PHY | The scales were on the arm of his chair where he had left them at noon two days ago. | **REAL** | memory: Olympus vs Ida for an earlier exchange / where the scales were | `working/logs/gate/zeus-weighs-hectors-fate/20261108-061827-61316/recheck/gate-check-zeus-weighs-hectors-fate.json (+ .r2)` |
| O46 | briseis-led-from-the-hut | 20261108 (recheck-pending) | 1 | PHY | Odysseus stood at the steering oar. She knew him at that distance by how he stood, short in the leg  | **REAL** | memory: who held the steering oar: one issue, found from both scenes | `working/logs/gate/recheck/briseis-led-from-the-hut/20261108-072632-42651/gate-check-briseis-led-from-the-hut.json (+ .r2)` |
| O47 | odysseus-returns-chryseis | 20261108 (recheck-pending) | 1 | PHY | Odysseus took the steering oar himself for the last of the way in. The man who'd held it since noon  | **REAL** | memory: who held the steering oar: one issue, found from both scenes | `working/logs/gate/recheck/odysseus-returns-chryseis/20261108-072839-42651/gate-check-odysseus-returns-chryseis.json (+ .r2)` |
---

## 5. Cost and latency

### Question-checker era, per layer (measured from the logs' usage fields; 103 run folders)

Prices that reproduce the ledger rows exactly: Opus 5.5 $4 / $20 per million tokens in / out, Sonnet 5.5 $2 / $10, Haiku 5.5 $0.10 / $0.50.

| Layer | Model | Calls | Tokens in | Tokens out (of which thinking) | Total cost | Mean per gate run | Share | Median seconds per call |
|---|---|---|---|---|---|---|---|---|
| Extraction | Sonnet | 103 | 3,142,911 | 712,224 (366,231) | $13.41 | $0.130 | 42% | 42 |
| Blocking read (2 readings) | Opus | 204 | 896,460 | 197,362 (188,209) | $7.53 | $0.073 | 24% | 9.4 each |
| Source check | Sonnet | 99 | 1,524,898 | 362,695 (175,011) | $6.68 | $0.065 | 21% | 27 |
| Persistence | Sonnet | 102 | 657,641 | 114,473 (0) | $2.46 | $0.024 | 8% | 8 |
| Typed state | Haiku | 101 | 1,043,624 | 1,096,726 (888,798) | $0.65 | $0.006 | 2% | 46 |
| Question facts (2–3 askings) | Haiku | 213 | 1,487,822 | 678,111 (380,840) | $0.49 | $0.005 | 1.5% | 13 each |
| Question promises (2 askings) | Haiku | 204 | 944,550 | 575,555 (353,194) | $0.38 | $0.004 | 1.2% | 13 each |
| **Gate total** | | | | | **$31.60** | **$0.307** (median $0.305, range $0.11–$0.49) | | about 190 s summed |
| Gate fixes (writer session) | Opus | 55 | 15,455,324 (cache writes and reads) | 19,005 | $50.56 | $0.92 per fix | | |

- No gate call used the prompt cache (all cache fields are 0). Only the writer's fix did.
- The ledger's gate total for the run is $32.31; the $0.71 difference is the later `check` runs.
- Seconds are from log file modification times, calls being sequential. Extraction's 42 s median (range 12–112) is from the run folder's timestamp, first runs only. The brief's "~90 s" is high for the median.
- Time per run: the question layer takes about 52 s (27%) and the typed state 46 s (24%), for 3% of the cost. Extraction takes 42 s for 42% of the cost.
- Cost per scene: $0.72 for the gate, plus $1.15 for gate fixes as they were priced that night.

### Open-checker era (measured)

| | Nov 8 | Nov 15–16 |
|---|---|---|
| Check layer per gate run (2 readings) | mean $0.458, median $0.436 | mean $0.599, median $0.594 |
| Other gate layers per run | $0.201 | $0.219 |
| Check layer total | $61.83 (135 runs) | $12.57 (21 runs) |
| First reading started cold (cache write of 80% or more of the context) | 13 of 93 first runs (15 of 135 runs) | 10 of 21 runs |

How the check's context grows with sequence (Nov 8 first runs; "context" is the largest request of reading 1):

| Sequence | Context tokens | Check cost per run |
|---|---|---|
| 1 | 36,708 | $0.41 (cold) |
| 10 | 62,004 | $0.37 |
| 20 | 87,478 | $0.44 |
| 30 | 112,744 | $0.46 |
| 40 | 144,254 | $0.69 |
| 50 | 168,634 | $0.45 |
| 57 | 186,548 | $0.41 |
| 63 | 204,371 | $1.37 (cold) |
| 65 | 209,030 | $0.67 |
| 66 | 44,781 | $0.30 |
| 66–96 (30 runs) | median 51,907 | mean $0.46, range $0.26–$0.77 |

- Context grows by about 2,700 tokens per scene (fit: 33,100 + 2,708 × sequence) until the story so far passes `prompts.FULL_MAX_WORDS` (100,000 words).
- At sequence 66 it drops to the window (the preceding scene and each thread's latest scene). Tool calls per reading then rise from 2.5 to 6.5.
- Cost follows the cache more than the size. Warm at sequences 50–65: $0.35–$0.80, mean $0.53. Cold at the same size: $1.37.
- On Nov 8 scenes ran back to back and the 5-minute cache stayed warm. With today's gate (blocking, typed state, drafting and voice review between checks), 10 of the 21 Nov 15–16 runs started cold.
- The window did not stop it finding things: 10 of the 30 windowed first runs had a finding, against 18 of 63 with the full story.

### Projection: open checker for scenes 58–92 (estimate)

The current draft is 86,685 words through sequence 57, about 1,635 a scene, so it reaches the 100,000-word cap about 8 scenes on.

| Stretch | Scenes | Context | Check cost per gate run | Per scene at 2.1 runs | Stretch total |
|---|---|---|---|---|---|
| Full story (to about sequence 65) | 8 | 190–215k tokens | cold about $1.50, warm about $0.55 | about $2.10 | about $17 |
| Window (after the cap) | 32 | 45–70k tokens | $0.46 (Nov 8) to $0.60 (Nov 15–16) | $1.00–$1.25 | $32–$40 |
| **Open checker, 40 scenes** | | | | | **about $50–$57; plausible range $35–$70** |
| Question layer, 40 scenes | | | $0.0084 | $0.019 | about $0.80 |

Assumptions:
- one cold first reading per scene, then warm, as on Nov 15–16;
- 2.1 gate runs per scene (the Nov 15–16 rate; the question run made 2.27);
- no change to the 5-minute cache on the check.

This prices the check layer only. It does not count fix rounds the open checker's findings would add, or those the typed-state false positives already cause.

---

## 6. Surprises

**Layers that never fired.** Place, sky, names and knowledge checks made no finding in 100 runs. `must:` lines made none (the briefs mark none). Persistence and the source check never stop a scene by design.

**A good fix was thrown away on question-layer noise.** `aphrodite-drives-helen-to-bed`:
- the first run found one real blocking error (Paris already on the bed);
- the fix removed it;
- on the re-check the promise questions newly answered no/no to a registry promise from the previous scene ("Aphrodite rescued Paris from the duel");
- the "never worse" rule read that as a problem the fix brought in and discarded the fix;
- the scene is pending with the original error.

**The "never worse" rule fired 3 times in 2 scenes:** that discard, and two partial fixes in `hector-fires-the-ships`.

**Fixes wrote 11 new findings into the prose** (the finding's quote is text a fix wrote; matched by string, so a lower bound):

| Scene | What the fix answered | What it wrote | Result |
|---|---|---|---|
| `ajax-fells-hector` | Real blocking error (spear already thrown) | "His empty hands fly open." | New real blocking error (he still has his shield); pending |
| `achilles-watches-from-the-stern` | False promise finding (which shoulder, whose arrow) | "the arrow standing in his right shoulder" | New real blocking error (shield arm is the left); pending |
| `hector-fires-the-ships` | False promise finding ("Hector set a ship on fire"; Homer has the Trojans throw it) | "Hector takes a torch from the man behind him and throws it" | New real blocking error (no free hand), twice; caught by "never worse" |
| `hector-duels-ajax` | Blocking and promise findings | "slings the baldric over his shoulder" | New real blocking error; pending |
| `hector-duels-ajax`, `polydamas-counsels-a-pause`, `hector-fires-the-ships` (5 findings) | False possession findings | "his own bow", "his own shield", "Achilles' own sword" | The same possession finding again on the new words |
| `athena-fires-diomedes`, `polydamas-reads-the-eagle` | False injury findings | "though the shoulder tears", "in his right hand" | The same injury finding again |

**The injury check is rewriting Homer.** To satisfy it, the fixes gave Hector a lingering shield arm three days after the duel and Diomedes a "bad shoulder" on the night raid:
- `polydamas-counsels-a-pause`: "where Hector's shield arm is still slow from Ajax's stone";
- `hector-fires-the-ships`: "his shield arm still held close against his side";
- `diomedes-and-odysseus-raid`: "He throws, stiffly, the bad shoulder dragging at it."

Homer has neither. These are in the committed prose.

**Findings repeated unfixed across rounds:** 7 (5 possession, 2 promise). The fix cannot satisfy a check that is wrong about the object.

**No finding was made twice by two layers in one run.** One question finding was merged into a typed injury finding on the same quote. Aeneas' hip was raised three ways across rounds (injury, then two question facts).

**Layers disagree about Lycophron** (`ajax-holds-the-ships`). The blocking read rightly flagged "prow" against the staging under the stern, and the fix changed it to "stern". The source check then dropped the fact because Butler's text says "prow".

**The source check's own rulings are mixed.** Of the 22 distinct facts it dropped:
- sound: Idomeneus draws his spear out of Oenomaus (13.509); Paris uses a spear, not an arrow (15.341); Hector calls for fire on the ships, not the wall;
- wrong: Machaon and Podalirius "reversed" (a misreading of "the one ... the other"); "he knew well who it was" given to Polydamas; Polydamas' "scattered" line (the extractor had misread the scene);
- Butler's own slips taken as truth: "sword-wounds" for Odysseus; "ten thousand measures" of wine.

It cleared 3 false question findings and stopped nothing. I did not classify all 22.

**The extraction "over the cap" note fired on 100 of 100 runs** (1,021 facts in force left out by `ajax-fells-hector`). The extractor is not shown most of the ledger either.

**The one halt** (`diomedes-spears-ares`) was the extractor ending a fact the same scene introduces, on both re-checks.

**Environment note.** Mid-task the disk filled (ENOSPC) and no command could start for a while. The scratchpad folder is shared: other agents' files are in it, including a `work/` folder of about 10 GB of eval runs. I deleted nothing of theirs; my own snapshots were removed after each replay.

---

## Measured vs estimated

| Claim | Basis |
|---|---|
| Stops, fix rounds, findings per layer, question counts, answer counts | Measured by replay; 44 of 44 scenes reproduce the committed prose and the log's fix-round counts |
| Cost and tokens per layer | Measured from usage fields; prices checked against ledger rows |
| Seconds per layer | Measured from file times; extraction from folder timestamps |
| Open-checker counts, overlap, context growth | Measured from the logs |
| REAL / FALSE / DEBATABLE | Judged; pending scenes read in full, the rest from verified quotes and Homer; open-era from finding text only |
| Fix-introduced count (11) | Measured by string match; a lower bound |
| Open-checker projection for scenes 58–92 | Estimate from the Nov 8 and Nov 15–16 cost curves |
