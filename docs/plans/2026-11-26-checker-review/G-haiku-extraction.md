# Report G: Haiku against Sonnet for the gate's fact extraction

Research agent report, 2026-11-26. A live measurement (Ben's go): $5.52 of model spend, not charged to the eval budget or the book's cost ledger. Nothing in any repo was changed.

## 1. Verdict

**Haiku fails the criterion on both tests, and the result is not ambiguous.** On the book, Haiku captured 45–47% of continuity-critical facts against Sonnet's 81% on identical prompts; on E3 it averaged 0.728 recall against the 0.82 floor. Confidence is high (about 95%) that Haiku is materially worse at this job as the gate is built today.

- **Book gap:** −35 points, 95% CI −41 to −29 (paired bootstrap over 224 items; −39 to −29 when resampled by scene). The criterion allowed 3 points.
- **Every scene agrees:** Haiku was below Sonnet on all 12 scenes in both runs.
- **Error rates:** Haiku's wrong-fact rate is about three times Sonnet's; wrong-subject rates are about equal; Haiku had the only misquote, which would block the gate.

## 2. Tables

### Recall on continuity-critical facts (strict "captured"; captured + partial in brackets)

All four columns are scored against the same 224-item ground-truth list. "Sonnet logged" is the latest logged gate reply per scene; all 12 were valid (every quote is in the current prose, and the prompt sizes match to within 31 tokens in total).

| Scene | n | Haiku run 1 | Haiku run 2 | Sonnet fresh | Sonnet logged |
|---|---|---|---|---|---|
| athena-fires-diomedes | 20 | 0.55 (0.80) | 0.55 (0.75) | 0.90 (1.00) | 0.80 (1.00) |
| agamemnon-is-wounded | 19 | 0.53 (0.63) | 0.68 (0.89) | 1.00 (1.00) | 1.00 (1.00) |
| glaucus-and-diomedes-trade-armour | 17 | 0.53 (0.76) | 0.53 (0.76) | 0.94 (0.94) | 0.94 (1.00) |
| hector-duels-ajax | 19 | 0.42 (0.68) | 0.37 (0.58) | 0.79 (0.89) | 0.89 (0.89) |
| ajax-fells-hector | 18 | 0.44 (0.78) | 0.50 (0.72) | 0.83 (0.94) | 0.67 (0.94) |
| hector-farewell-to-andromache | 16 | 0.31 (0.50) | 0.50 (0.69) | 0.62 (0.88) | 0.69 (0.75) |
| idomeneus-fights-at-the-ships | 22 | 0.45 (0.82) | 0.41 (0.77) | 0.77 (0.91) | 0.82 (0.91) |
| odysseus-stands-at-bay | 20 | 0.30 (0.65) | 0.50 (0.95) | 0.85 (1.00) | 1.00 (1.00) |
| sarpedon-rebukes-hector | 17 | 0.53 (0.88) | 0.47 (0.71) | 0.59 (1.00) | 0.65 (0.94) |
| ajax-holds-the-ships | 19 | 0.42 (0.63) | 0.42 (0.79) | 0.84 (0.89) | 0.95 (0.95) |
| hector-drives-them-to-the-ships | 17 | 0.47 (0.82) | 0.29 (0.71) | 0.76 (0.88) | 0.71 (0.94) |
| hector-fires-the-ships | 20 | 0.40 (0.65) | 0.40 (0.65) | 0.75 (0.90) | 0.75 (0.90) |
| **Total** | **224** | **0.446 (0.719)** | **0.469 (0.750)** | **0.808 (0.938)** | **0.826 (0.938)** |
| Captured / partial / missing | | 100 / 61 / 63 | 105 / 63 / 56 | 181 / 29 / 14 | 185 / 25 / 14 |

- **Old six vs new six:** Haiku 0.47 / 0.52 on the original six scenes and 0.43 / 0.42 on the six new dense ones; Sonnet 0.85 / 0.84 and 0.77 / 0.82.
- **Run-to-run:** Haiku's two runs differ by 2.2 points in total (CI −8 to +4) but agree on only 70% of items. The two Sonnet samples differ by 1.8 points and agree on 88%.
- **Two Haiku runs combined** capture 59% of new facts; two Sonnets capture 91%.

**Fairer cut, drawn up after unblinding.** 41 of the 224 items are things the prompt already holds: a plan fact "already recorded for this scene" (for example `agamemnon-arm-wounded`, `ajax-has-hector-sword`) or a state carried in from an earlier scene. The prompt tells the model not to restate these, so omitting them is correct. On the remaining 183 new facts:

| | Haiku 1 | Haiku 2 | Sonnet fresh | Sonnet logged |
|---|---|---|---|---|
| All new facts (183) | 0.459 | 0.514 | 0.863 | 0.874 |
| Deaths (52) | 0.52 | 0.60 | 0.88 | 0.94 |
| Wounds (16) | 0.62 | 0.75 | 0.94 | 0.94 |
| Possessions and handovers (29) | 0.45 | 0.48 | 0.83 | 0.79 |
| Where people are, arrivals, departures (44) | 0.30 | 0.25 | 0.80 | 0.77 |
| Oaths, orders, promises (12) | 0.25 | 0.33 | 0.83 | 0.92 |
| Backstory and identity (30) | 0.60 | 0.73 | 0.93 | 0.93 |
| Missing outright | 48 | 38 | 5 | 6 |
| Deaths and wounds missing outright (of 68) | 11 | 7 | 1 | 1 |

The gap on new facts is −38 points (CI −45 to −31). Counting partials as captured it is still −21 (CI −26 to −16).

### Error rates

| | Haiku 1 | Haiku 2 | Sonnet fresh | Sonnet logged |
|---|---|---|---|---|
| Rows produced (12 scenes) | 289 | 305 | 398 | 397 |
| Wrong facts | 10 (3.5%) | 8 (2.6%) | 4 (1.0%) | 4 (1.0%) |
| Wrong subject, all kinds | 16 (5.5%) | 18 (5.9%) | 18 (4.5%) | 23 (5.8%) |
| of which wrong homonym | 10 | 12 | 11 | 10 |
| of which filed under killer or relative | 6 | 2 | 6 | 8 |
| Blank subject | 12 | 12 | 6 | 6 |
| Blank where a clear subject exists | 3 | 1 | 0 | 1 |
| Two people merged in one row | 0 | 3 | 11 | 10 |
| Trivial rows | 5 (1.7%) | 11 (3.6%) | 38 (9.5%) | 33 (8.3%) |
| Misquotes (`quotes.quote_in`) | 0 | 1 | 0 | 0 |
| Subject not in the registries | 0 | 1 | 0 | 0 |
| `supersedes` / `ends` links emitted | 6 | 7 | 23 | 23 |
| Bad links (`supersedes`, `ends`, `ends again`) | 0 | 0 | 0 | 0 |
| Gate-blocking problems (`gate.UNRESOLVED`) | 0 | 1 (the misquote) | 0 | 0 |
| Schema failures or truncation | 0 | 0 | 0 | 0 |

- **Against the criterion:** wrong facts are worse on Haiku; misquotes and blocking problems are worse by one event in 594 rows; wrong subjects are a tie; link errors are a tie at zero.
- **Homonyms are a shared weakness, not a Haiku one.** All four outputs picked the same wrong ids for Tlepolemus, Melanippus, Thoas, Amphimachus and Hypsenor.
- **Haiku is cleaner on two counts:** fewer trivial rows and fewer merged rows. That is the other side of writing fewer rows.

### Tokens, latency and cost per extraction call (12 scenes, about 30.7k input tokens each)

| | Haiku 1 | Haiku 2 | Sonnet fresh | Sonnet logged |
|---|---|---|---|---|
| Output tokens, mean (max) | 11,192 (20,200) | 12,702 (21,935) | 9,550 (15,042) | 8,514 (17,314) |
| of which thinking | 8,816 (79%) | 10,192 (80%) | 5,720 (60%) | 4,679 (55%) |
| Answer tokens, mean | 2,376 | 2,511 | 3,829 | 3,835 |
| Latency, median (max) | 44.7 s (78.9) | 44.9 s (95.1) | 51.6 s (94.0) | not logged |
| Cost per call | $0.0087 | $0.0094 | $0.157 | $0.147 |

Haiku is not faster in any useful way: it thinks about 1.7 times as much as Sonnet and then writes a shorter answer.

**Projected saving** over the remaining 40 scenes at 2.3 gate runs each (92 calls): Sonnet costs about $14.4 at this run's $0.157 per call ($11.7 at the $0.127 you quoted), Haiku about $0.83. The saving is $11–14 for the rest of the book.

### E3 on Haiku (three runs)

Extraction calls on Haiku, Opus judge unchanged, same 49 cases.

| | Captured | Partial | Missing | Recall | Dropped by the persistence check |
|---|---|---|---|---|---|
| Sonnet, recorded baseline | 43 | 5 | 1 | 0.878 | 38 |
| Haiku run 1 | 37 | 9 | 3 | 0.755 | 24 |
| Haiku run 2 | 35 | 11 | 3 | 0.714 | 24 |
| Haiku run 3 | 35 | 11 | 3 | 0.714 | 26 |
| **Haiku mean** | 35.7 | 10.3 | 3 | **0.728** | |

- **Recall half of the criterion:** fails (0.728 against 0.82). Haiku is 6–8 captured facts below Sonnet, against Sonnet's known run-to-run range of about 3.
- **Missing half:** passes exactly (3 against Sonnet's 1 plus 2).
- **Stable misses:** nine cases were never captured in any of the three runs: governor-015 and -016, lantern-folk-003, -005, -006, -013 and -018, thornwall-002 and -021. Sonnet's recorded run misses or half-captures five of those.
- **By code**, pooled over the three runs: WLD 0.40, TIM 0.67, PRM 0.67, PHY 0.71, TRT 0.86, KNO 1.00.

## 3. Which facts differ

**Haiku missed or blurred in both runs, Sonnet captured: 65 items.** The ones that matter most:

- **Wounds:**
  - Coon spearing Agamemnon's left forearm (already a plan fact, but run 1 had no row at all);
  - Diomedes pulling the arrow from his foot;
  - Odysseus pulling out Socus's spear and bleeding;
  - Diomedes' spear stunning Hector on the helmet;
  - Hector vomiting blood at the ford;
  - Diomedes' blood-stiffened shoulder.
- **Deaths:**
  - Teucer killing Imbrius (run 2 credited the kill to the small Ajax);
  - the three unnamed kills in `ajax-holds-the-ships`;
  - Hippolochus's hands;
  - partial only on Othryoneus, Oenomaus, Aphareus, Thymbraeus and his driver, Cleitus, Melanippus, the scarlet-plume Trojan, and the priest's son.
- **Possessions and objects:**
  - the hole in Diomedes' corslet;
  - Aeneas's horses captured and sent to the ships;
  - Glaucus seen in plain bronze;
  - Ajax's spear through Hector's shield and corslet;
  - the stone caving in Hector's shield;
  - Achilles' corslet too tight on Patroclus;
  - the Xanthus, Balius and Pedasus team (partial);
  - Teucer's change from bow to spear and shield (partial);
  - Idomeneus's two spears left in bodies (partial).
- **Where people are:**
  - Agamemnon leaving for the ships;
  - Hector hanging back from Agamemnon;
  - Hector carried to the Scamander ford (partial);
  - the fighting being at the ships;
  - the Achaeans falling back to the huts;
  - Hector's hand on Protesilaus's stern, ship not yet alight;
  - the rallied captains;
  - Menelaus stopped from accepting the duel;
  - the nine volunteers;
  - Diomedes ordering the Argives back from Ares.
- **Orders, oaths and prayers:**
  - Nestor's no-stripping order;
  - the Glaucus–Diomedes pact (already a plan fact);
  - Hector's prayer for his son;
  - Achilles telling Patroclus to arm;
  - Achilles' prayer to Zeus for Patroclus's safe return with the armour — the one that pays off at Patroclus's death.

A further 39 items were missed by one Haiku run and not the other. These include the deaths of Asaeus, Autonous, Opites, Deiopites, Chersidamas and Bienor's driver, the red dew, "defend the ships yourselves", and Hector's refusal to stay on the wall.

**Sonnet missed or blurred, both Haiku runs captured: 3 items**

- The right side of Diomedes' shoulder wound (Sonnet relied on the plan fact).
- Paris killing Menesthius (partial).
- The small Ajax killing Satnius (partial).

Another 6 items were caught by only one Haiku run, among them Teucer's bad arm, "not the child in the womb", and the helmet set down with the spear leaned at the gate.

**Nobody captured: 23 items.** Most are restatements the prompt forbids or detail the plan fact already carries:

- the sword and belt exchange;
- Sarpedon's left thigh;
- Teucer's collarbone;
- Hector's shield arm;
- Ajax wearing Hector's sword.

Real shared gaps:

- Hector's bloodied right hand;
- Eurypylus's thigh wound, as told to Achilles;
- the Trojans wavering at the end of `ajax-fells-hector`;
- Ajax giving way once the pike is cut.

## 4. Haiku-specific failure modes and middle options

- **Under-extraction is the failure.** Haiku wrote 24 rows per scene to Sonnet's 33. It records what a thing is and who is related to whom, and skips what happened to people: the event rows are the ones that go missing.
- **Reads "don't restate" too broadly.** It emitted a third as many `supersedes` / `ends` links (6–7 against 23). No link was wrong, but state changes go unrecorded, so stale states stay in force.
- **Wrong facts are misattributions:**
  - Gorgythion given the reins instead of Archeptolemus;
  - the small Ajax "killing" Imbrius;
  - Poseidon closing Zeus's eyes;
  - Melanippus's nine years at the front given to Ajax;
  - an unnamed victim named as Antiphus.
- **Thinking and the token cap.** The code sends no thinking setting for either model; both think by default, and nothing in `api.py` treats them differently (same `max_tokens` of 8,000 + 16,000). Haiku's largest replies used 20,200 and 21,935 of that 24,000, so the denser scenes ahead risk truncation, which stops the gate. Sonnet's largest was 15,042 (17,314 in the logs).
- **One made-up subject id** (`cretan-knee-wounded`) and one misquote in 594 rows.

Middle options:

- **Haiku for re-checks, Sonnet at commit:** not supported. A re-check that sees half the facts will miss changed facts and will rarely end stale states, and each Haiku run sees a different half.
- **Two Haiku runs merged:** not supported (59% against 86%).
- **Sonnet with thinking off or capped:** the most promising option, but untested here. Thinking is 55–60% of Sonnet's output tokens, about $0.05–0.06 of each $0.15 call, so up to roughly a third off if recall holds.
- **Sonnet through the Batch API for re-checks** (half price) is also untested; whether it is practical depends on whether re-checks can wait.

## 5. What ran, what it cost, what was written

**Part A (book)**

- **Prompts.** I rebuilt the production prompt offline for 12 scenes: your six plus `idomeneus-fights-at-the-ships`, `odysseus-stands-at-bay`, `sarpedon-rebukes-hector`, `ajax-holds-the-ships`, `hector-drives-them-to-the-ships` and `hector-fires-the-ships`. Each is built as a re-check would build it from the current ledger.
- **What a re-check prompt implies.** The scene's own earlier commitments are removed, 200 facts in force are offered (215 to 1,121 left out by the cap), and one to three plan facts are listed as already recorded.
- **Calls.** 24 Haiku and 12 Sonnet calls through `api._send`, with identical requests apart from the model id.
- **Ground truth.** The earlier analyst's fact list was not on disk (only `subj.py`), so I wrote all 224 items from the prose before any output was parsed or read.
- **Scoring.** Twelve separate scorer agents each scored one scene from a packet with the four outputs shuffled and unlabelled. I spot-checked two scenes after unblinding and the verdicts held.
- **Mechanical checks.** Production `parse_commitments_response`, `quote_in` and `commitment_rows` were run offline on every reply.
- **Persistence check not run.** Outputs are scored before it; it could only lower recall further.

**Part B (E3)**

- **How it ran.** E3's own `select`, `extract` and `judge` were called from my script, with the extraction model swapped to Haiku in memory.
- **Volume.** Three full runs: 504 Haiku calls and 147 Opus judge calls, including a two-case trial.
- **Trees.** Materialised under the scratch folder (1.1 GB) and deleted afterwards.

**Actual spend, from usage fields at Storyforge's price table**

| | Calls | Cost |
|---|---|---|
| Part A, Haiku | 24 | $0.217 |
| Part A, Sonnet | 12 | $1.883 |
| Part B, Haiku | 504 | $0.975 |
| Part B, Opus judge | 147 | $2.449 |
| **Total** | **687** | **$5.52** |

That is under the $7 cap. Sonnet ran above my $1.50 estimate because its outputs were longer than the logged average.

**Spend tracking**

- **Eval spend ledger:** nothing was recorded against the eval budget. No cassette or spend-log variable was set, and `~/.storyforge/eval-spend.jsonl` is unchanged at 7,982 lines, last modified Nov 17.
- **Book cost ledger:** not written by me. Its last line is 11:36 today, before my first call.

**Repos**

- **`git status`:** `iliad-adult` and `homer` are clean. `storyforge` shows only untracked `sf-wt/` (dated Nov 8). `evals` shows only three untracked `projects/telemachy-teen/working/` files (dated Nov 7). All of these predate this work.
- **`baseline.json`, the cassettes and `commitments.csv`** are untouched.
- **Bytecode caches:** Part A's imports may have refreshed git-ignored `__pycache__` files in `storyforge`.

**Disk:** 56 GB free at the end; the scratch folder is 5.2 MB.

Everything is in `scratchpad/haiku-extract/`. The files to open first are `gt.py` (ground truth), `scored.json` (per-item verdicts and row flags) and `mech.json` (tokens, cost and production-check results per reply).

## 6. Not done, and what remains uncertain

- **Persistence pass and the full gate were not run.** The effect on gate findings is inferred from the missing facts, not measured.
- **One judge per scene, no second scorer.** Absolute recall depends on my ground-truth list and on a strict reading of "captured". Sonnet's 81–83% here against the earlier analyst's 89% reflects that strictness and the restatement items. The Haiku–Sonnet gap is far larger than any plausible scoring noise, and is still 21 points if every partial counts as captured.
- **The "already in ledger" exclusion was drawn up after unblinding**, by my reading of the prompts. It moves both arms and does not change the conclusion.
- **Only one fresh Sonnet run per scene.** The logged replies serve as the second sample and agree within 2 points.
- **No Haiku prompt tuning was tried.** A prompt that tells Haiku to record every death, wound and handover might close part of the gap. This measurement says only that the current prompt and settings do not transfer.
- **Sonnet with thinking off, and Batch pricing, were not tested.**
- **The homonym and filed-under-killer defects are unchanged by model choice.** They need a fix in the prompt or in code.
