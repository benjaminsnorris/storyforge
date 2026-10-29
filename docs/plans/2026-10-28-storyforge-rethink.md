# Storyforge Rethink — Plan

Date: 2026-10-28 (revised twice the same day: Ben's decisions, then the corpus survey). Status: approved direction; handoff to an implementing agent (Opus in Claude Code). Read Section 6 first: it records what is decided. The corpus survey is in `docs/plans/2026-10-28-storyforge-corpus-survey.md` beside this file; Section 4.4 summarizes what it changed.

## 1. Principle

> A novel is a set of commitments to the reader. Storyforge's job is to make every commitment explicit, at the granularity a reader would notice, and to let nothing into the book that hasn't been checked against them.

Corollaries:

1. **Granularity is set by the reader, not plot logic.** A fact belongs in the ledger if a later scene could contradict it in a way a reader would notice. This replaces the 0–2 facts/scene cap and POV-only tracking. The rubric is in Section 6, decision 5.
2. **Reliability is a property of the loop, not the data model.** The CSVs stay the backbone. The missing piece is the gate: nothing commits without a check.
3. **Origin doesn't matter.** Plan facts, Claude's prose, and Ben's prose (advisor mode) are checked identically. One architecture serves all three coaching levels.
4. **Commitments include promises, not only facts.** A brief's outcome, a scene's emotional resolution, the voice guide's rhythm, and target length are commitments. The gate holds them too.

**Binding policy: default-accept with audit (decided).** A fact extracted from committed prose binds all later prose immediately. Ben reviews digests on the cadence in decision 2. Rejecting a fact marks it `rejected`, and the dependency graph lists every scene that leaned on it for re-check.

## 2. What the system guarantees, by level

| Level | Guarantee | Where it's checked |
|---|---|---|
| Plan | Structure is coherent: every scene has a function, value shift, and intent; MICE threads open and close; arcs resolve | Existing CSV validation (keep) |
| Scene | Prose keeps its brief's promises and contradicts no binding commitment | **The gate (new)** |
| Sentence | Prose matches voice and the character's state at that moment | Voice checks (existing, rerouted to the gate) + per-character state slice (new) |
| Book | Timeline is consistent; every promise to the reader is paid off; no commitment is contradicted anywhere | Timeline pass (keep), whole-book checker on the full manuscript in context (new) |

## 3. Architecture

### 3.1 The ledger

One new file, `commitments.csv`, joined to scenes by scene ID. It is the single store of what the book has committed to. Columns:

- `id`
- `scene_id` — where it was established
- `type` — `physical` | `timeline` | `knowledge` | `relationship` | `trait` | `world` | `promise`
- `subject` — canonical ID (character, location, object) or scene ID for promises
- `statement` — one declarative sentence
- `quote` — the prose or plan text that establishes it
- `origin` — `plan` | `prose` | `author`
- `status` — `binding` | `pending` (not yet committed) | `rejected` | `superseded`
- `mutable` — `state` (changes over time: injury, possession, location, knowledge) | `fixed` (eye color, backstory, a sister's name)
- `known_by` — characters who know it (knowledge facts)
- `supersedes` — id of the earlier state this replaces (mutable facts)
- `depends_on` — ids this commitment relies on
- `reviewed` — blank | `seen` | timestamp of Ben's audit (see decision 2)
- `introduced_by` — the command or pass that wrote the establishing text (`draft`, `redraft`, `polish`, `continuity-audit`, `author`, …). The survey showed Storyforge's own revision passes introduce or reintroduce many errors; this column makes that measurable.

Per-character state "as of scene N" is derived, not stored: the latest unsuperseded `state` facts for that subject up to N. This replaces the static character bible as drafting context; the bible becomes the `fixed` facts plus voice.

**Migration (decided):** `knowledge.csv` and `physical-states.csv` are migrated into `commitments.csv` (`type=knowledge`; `type=physical, mutable=state`) and then removed. A migration script runs once per book repo and is verified by round-tripping the old files out of the new one. Keep `characters.csv`, `locations.csv` as ID registries, with one addition: `characters.csv` gains a `pronouns` column. The survey's clearest regression (slipform: Pell's pronoun fixed by hand, then undone by a redraft) happened because no file recorded it.

### 3.2 The gate

Runs after every draft, redraft, or revision of a scene, and on human-written prose in advisor mode:

1. **Extract** candidate commitments from the scene using the rubric in decision 5. Strongest model, extended thinking, structured output. No cap on count.
2. **Check** the scene against the ledger slice (all binding facts for the scene's characters, location, objects, and timeline position) and against the brief's promises. The checker is tool-using: it can search the manuscript and query the ledger rather than relying on a fixed bundle.
3. **Fix** with targeted edits for each flagged contradiction or broken promise; re-check once.
4. **Commit** the scene and its extracted facts as `binding`. Append the facts to the scene's audit entry (decision 2).
5. **Fail loud.** Any step that fails halts the chain and reports. No warn-and-continue.

In advisor mode, step 3 becomes a report instead of an edit.

### 3.3 The loop

Sequential drafting by default. Each scene is drafted from: its brief, the ledger slice, per-character state as of that scene, and prior prose per decision 4. Parallel waves return only when an eval shows no reliability loss (Phase 3 measures this).

### 3.4 Revision

Changing a scene re-runs the gate for it, then for every scene whose commitments `depends_on` anything that changed. Rewrites draft from plan + binding ledger, with the old prose supplied as voice reference only.

### 3.5 Export and the boundary with Storygild and Bookshelf (decided)

- Core gains an `export` command that emits one canonical JSON bundle of the book's structured state: scenes, intent, briefs, registries, `commitments.csv`, diagnostics results, timeline, eval results, and audit entries. The bundle carries a `schema_version`. It changes in the same commit as any schema change and is covered by tests.
- **Bookshelf** (bennorris.com) renders dashboards from the bundle. Core does not know Bookshelf exists. If a renderer already lives in Bookshelf, it switches to the bundle; if it lives in the plugin today, it moves out.
- **Storygild** is a separate plugin for illustration, covers, graphic-novel packaging, press kits, and script packages. It reads the export bundle and pins a `schema_version`. Manuscript export and `produce` stay in core because a novel-writing tool must produce a novel.

## 4. Evals (built before any change)

"Reliable, consistent, accurate" in measurable terms:

- **Accurate:** contradictions per 10,000 words (CP10k) and broken promises per scene (BPS).
- **Reliable:** the checker's recall and precision on known errors.
- **Consistent:** run-to-run variance of the above on the same inputs.

### 4.1 Error taxonomy

| Code | Type | Example |
|---|---|---|
| PHY | Physical continuity | Object in two places; injury vanishes; weather flips |
| TIM | Timeline | Day/time/duration/sequence contradictions |
| KNO | Knowledge | Character acts on a fact they couldn't know |
| REL | Relationship | Neighbor becomes ex-partner |
| TRT | Trait/identity | Name, age, appearance, backstory drift |
| WLD | World/plausibility | Rules of the setting violated |
| PRM | Promise | Brief outcome missing; resolution dropped; length doubled |
| VOI | Voice | Rhythm flattens to default; character sounds generic |

### 4.2 Eval suites

**E1 — Real failures corpus (gold set).**
Mined from the git history of Ben's novel repos (decision 1). For each case: repo, scene (slug id at HEAD), error code, the contradicting pair (fact A in scene X, fact B in scene Y, each quoted at the pre-fix commit), the fix commit, `introduced_by` (which pass wrote the error), and whether a later pass regressed it. The survey estimates 125–150 prose cases, ~30 CSV/brief-level cases, and 15–20 unfixed contradictions still at HEAD. Target: 100+ labeled prose cases. Hold out 20% by repo-stratified sample. Contents may be used in the public plugin's fixtures. Three subsets are tagged for separate reporting: `author-labeled` (cases Ben flagged himself in Bookshelf annotations or read notes), `tool-introduced` (errors a Storyforge pass created), and `unfixed-at-head` (should-flag positives with no fix diff).

**E2 — Detection benchmark.**
Input: manuscript + ledger. Output: flagged contradictions. Sources: E1 cases plus labeled injections into public-domain prose (The Great Gatsby, A Christmas Carol) across all codes. Metrics: recall and precision per code. Shipping gate for the checker: recall ≥ 0.9 on PHY/TIM/KNO/REL/TRT, precision ≥ 0.8.

**E3 — Extraction benchmark.**
Every E1 error implies a fact that should have been in the ledger; measure whether extraction produces it from the establishing scene. Add hand-labeled chapters from Gatsby and A Christmas Carol. Metric: recall of "facts that later mattered." Secondary: over-extraction rate.

**E4 — Generation benchmark.**
Draft a fixed test text end to end (decision 7). Judge with the shipped checker plus human spot-check. Metrics: CP10k, BPS, length drift vs brief target, VOI score from existing diagnostics. Headline number.

**E5 — Roundtrip eval.**
Redraft scenes from plan + binding ledger only; count fact mismatches against the original prose. Each mismatch is a ledger gap.

**E6 — Consistency.**
Run E2 and E4 three times; report variance. Flag any eval whose variance exceeds the improvement claimed.

**E7 — Classics regression (advisor mode).**
Run extraction + checker on Gatsby, A Christmas Carol, and later classics. Metric: false-positive rate. Any flag is either a checker bug or a real find.

**E8 — Revision safety.**
Apply the current revision passes (redraft-from-brief, polish, continuity-audit) to a clean, fully-labeled scene set and count errors introduced or reintroduced. Built from the `tool-introduced` subset of E1 (governor's Tessa/Elias burns, shared-dark's chair and "three nights," slipform's Pell pronoun, thornwall's hallucinated name Voss). Metric: errors introduced per pass per 10k words. This is the eval Phase 4 must pass; it did not exist in the first draft of this plan because the survey is what revealed the pattern.

**A Christmas Carol is in progress now** as the second classic. That run continues as Phase 0 data collection: every flag gets Ben's verdict (real / false positive) for E7, every missed fact gets noted for E3, and no prompt tuning is done to make the run look clean.

### 4.3 Corpus skew and supplements

The real corpus is heavy on TIM (counts, durations, day math) and TRT (names, pronouns, roles), thin on KNO, REL and PRM, and almost empty of VOI. E2 and E3 therefore supplement with injected KNO/REL/PRM cases in the classics and with the roundtrip test's REL/PRM/VOI failures (Desta's relationship, the dropped resolution, voice compression). Report every metric per code so the skew can't hide a weak code behind a strong average.

### 4.4 What the survey changed

- **guardian does not exist.** The repos with Storyforge data are shared-dark, thornwall, lantern-folk, governor, meridian-line, understory, slipform, and ashes (ashes yields nothing yet).
- **Labeling is cheaper than expected:** shared-dark and thornwall carry author-written label sets (Bookshelf annotations with `category: continuity`; first- and second-read notes; continuity trackers). The Bookshelf annotation flow is already an audit UI in practice, which supports putting the audit digest into the export bundle (3.5).
- **Storyforge introduces errors.** Redraft, polish, and continuity-audit passes are a first-class error source. Hence the `introduced_by` column, E8, and the Phase 4 gate.
- **Unrecorded facts caused regressions**, exactly as the principle predicts: Pell's pronoun, Wick's location and the survivor count (lantern-folk), Talia's rescue state (slipform), thornwall's personnel numbers. These go into E3 as must-extract facts and into the rubric's always-capture list.
- **Silent failures are documented:** understory's `timeline-fix` pass changed nothing and was marked complete; thornwall's continuity-audit overwrote `council.md` with agent scratch text; meridian-line's hone pass moved an alias between characters. These are Phase 1 bug tickets and loud-failure test cases.
- **Three scene-id eras per repo.** Every repo except lantern-folk renamed positional ids to slugs; pre-rename diffs need an id map (thornwall must be mapped by content because git's rename detection mispairs files). Knowledge CSVs were wiped mid-history in thornwall and shared-dark, so pre-reset knowledge ids don't join. Author retcons (thornwall's Hessal, meridian-line's Lena/Cora swap, understory's 43→66-day expansion) are not errors and must be excluded. Bundled audit commits must be split into one case per fix.

### 4.5 Harness

- `evals/` directory, one command, model calls recorded to fixtures so reruns are free.
- Every eval emits JSON metrics by code; `baseline.json` is committed before Phase 1.
- Cost budget per full run reported with results.
- Agent-executable without Ben.

## 5. Phases

### Phase 0 — Evals and baseline
- Corpus survey done (`docs/plans/2026-10-28-storyforge-corpus-survey.md`). Label shared-dark fully first, then thornwall, then lantern-folk; governor and meridian-line as needed to reach 100+. Build E2, E3, E5, E7, E8 harness. Baseline the current system. Log the survey's Storyforge bugs as tickets (no fixes yet).
- Success: `baseline.json` exists; E1 has 100+ prose cases with the three subsets tagged; suite runs unattended.
- Keep everything. Nothing changes in the plugin.

### Phase 1 — Cheap fixes
- Upgrade pinned models. Route all fact work (extraction, continuity, timeline, fact-check) to the strongest model with extended thinking. Replace "KEY: value" parsers with structured outputs. Convert every warn-and-continue to a halt.
- Success: E2 recall improves over baseline; zero silent failures in a full run, including regression tests for the survey's three silent-failure cases (a pass that changes nothing cannot report complete; a pass cannot overwrite a reference doc; an alias cannot move between characters without a ledger supersede).
- Rebuild: `extract.py`, parser consumers in `prompts.py`. Delete: obsolete parsers.

#### Phase 1 bug checklist (survey bugs, checked against v1.71.0 on 2026-10-28)

Each needs a fix and a regression test. Line numbers are as of v1.71.0.

- [ ] **Physical state assigned to the wrong character** (governor `d7e98f3`: Elias's burns given to Tessa, then propagated to 80 scenes). hone picks a new state's `character` from reference text, scene ids, and the character list only (`hone.py:487-499`), never the prose or the scene's `on_stage`; nothing checks `character` against `on_stage` at the `acquired` scene (`elaborate._validate_physical_states`), and `propagate_physical_states` (`hone.py:2682`) spreads the error.
- [ ] **A pass that changes nothing is marked complete** (understory `5ac1c26`). `3c0dfba` added a no-change check only for hone-routed passes. The structural/registry path (`cmd_revise.py:2360-2414`) logs "no CSV blocks found" or turns an apply error into a WARNING, then commits and marks `completed` (`:2512-2513`); a prose reply with no scene markers is also marked completed (`:2428`).
- [ ] **Structural pass writes duplicate `seq` and blank `pov`** (understory `bbfc945`). New rows are built from the model's fields unchecked (`cmd_revise.py:2399-2401`); `existing[sid].update(... if v ...)` (`:2398`) can never clear a field.
- [ ] **Duplicate `seq` is never reported** (thornwall `seq` 58). `cleanup`'s seq check (`cmd_cleanup.py:1586-1599`) flags gaps and decimals only; no uniqueness check exists in `cleanup` or `validate`.
- [ ] **Scene file overwritten with the model's raw reply** (thornwall `19530d5`). `parsing._write_scene` guards against truncation and big word-count drops, but `_redraft_scenes` writes `extracted if extracted else response` with no guard (`cmd_revise.py:1299,1316`), and `revise --interactive` runs `claude --dangerously-skip-permissions`, which writes scene files directly (`cmd_revise.py:2330-2335`).
- [ ] **Alias collision leftover** (meridian-line `5433d3f`; the main bug was fixed by `3486915`). `resolve_alias_collisions` (`hone.py:286-313`) gives a shared alias to whichever entry comes first in the file; add a test that a mapping pass never takes an alias away from its current owner.

Revision passes that wrote errors in shared-dark (E1 `tool-introduced` cases; E8 material): `prose-craft-tightening`, `continuity-audit`, `continuity-fixes`, `theory-as-dialogue`, `somatic-vocabulary-diversification`, `naturalness`.

### Phase 2 — Ledger and export
- Add `commitments.csv` and the rubric-driven extraction prompt. Migrate `knowledge.csv` and `physical-states.csv`. Derive per-character state. Audit entries and digest command (decision 2). `export` command with `schema_version`.
- Success: E3 recall ≥ 0.85 on E1-derived facts; E5 mismatches drop vs baseline; export round-trips in tests.
- Rebuild: knowledge extraction, character context assembly. Keep: registries, bible (slimmed to fixed facts + voice).

### Phase 3 — The gate and sequential loop
- Extract → check → fix → commit after every scene. Sequential drafting with prior prose per decision 4, including the context-size experiment. Tool-using checker. Advisor-mode report path.
- Success: E4 CP10k and BPS drop by half or more vs baseline; E2 precision ≥ 0.8. Then test parallel waves vs sequential on E4; keep parallel only if equal.
- Rebuild: `cmd_write.py` drafting loop, `_verify_and_commit_scene`, `select_revision_model`. Delete: open-loop wave scheduler if evals say so.

### Phase 4 — Safe revision
- Dependency graph from `depends_on`; re-check set after any edit; rewrite-from-ledger command; reject-fact flow in the audit.
- Success: E5 on rewritten scenes ≤ Phase 2 level; a rejected fact produces the correct re-check set on E1 cases; **E8 errors-introduced-per-pass is zero on the labeled set** (this is the gate that matters most, given the survey).

### Phase 5 — Health and Storygild
- Classics regression (E7) in CI. Move illustration, covers, graphic novels, press kits, and script packages into the Storygild plugin reading the export bundle. Cut `CLAUDE.md` to what an agent needs today; move bug history to `docs/history.md`.
- Success: core line count and `CLAUDE.md` length down materially; E7 false-positive rate stable across releases; Storygild runs against a pinned `schema_version`.

## 6. Decisions

### Decided

**1. Corpus sources.** Ben's novel repos may be used, including in public fixtures. The survey (`docs/plans/2026-10-28-storyforge-corpus-survey.md`) ranked them: **shared-dark** (label first: ~62 fix commits, two author-written label sets, full novel length, fix-induced regressions), **thornwall** (strong provenance, mostly numeric TIM/TRT, three id eras), **lantern-folk** (dense and fast to label, but an illustrated children's book; use it as the afternoon schema pilot if one is wanted), **governor** (self-labeled continuity report; many tool-introduced errors), **meridian-line** (PHY quantities, TIM counts), then understory, slipform, ashes for specific cases only. guardian does not exist.

**2. Audit cadence.** Audit entries are a free byproduct of the gate (the extracted facts for a scene), so they are written **per scene, always**, to an audit log the author can read at any pace. What costs something is Ben's attention, so surfacing is tiered:

- **Immediate (halts the run):** a new fact that supersedes a binding `fixed` fact, a fact extraction flagged low-confidence, or any contradiction with the plan. These stop the chain in any mode.
- **Per act (default digest):** all new binding facts since the last digest, grouped by subject, with `fixed` facts first, then relationship and knowledge, then physical state. Marking a fact `seen` or `rejected` here is the audit.
- **On demand:** `storyforge audit` at any point, optionally scoped to a character, a thread, or a scene range.
- A `--review-every N` option exists for runs where Ben wants tighter cadence; default is per act.

**3. Migration.** `knowledge.csv` and `physical-states.csv` are migrated into `commitments.csv` and retired. No compatibility layer.

**4. Drafting context.** More is better where cache makes it cheap. Baseline for Phase 3: the preceding scene in full, the most recent scene of each active thread in full, the ledger slice, and per-character state. Phase 3 then runs an experiment: that window vs the full manuscript-so-far (with prompt caching), measured on E4 and cost per scene. The default becomes whichever scores equal or better on E4 at acceptable cost; a tie goes to more context.

**5. Reader-noticeable rubric.** Draft text for the extraction prompt (Ben to refine wording and add 2–3 categories from his own books; dialogue content counts when it conveys information, not when it's texture):

> Extract every commitment the scene makes to the reader. A commitment is a claim about the story's world that a later scene could contradict in a way a careful reader would notice. For each sentence that establishes something, ask three questions:
>
> 1. **Is it specific?** Does it name or imply a particular thing: an object, a place, a time, a distance, a name, a relationship, a piece of knowledge, a trait, a stated intention? Moods, impressions, and general atmosphere are not specific.
> 2. **Does it persist past this scene?** States that carry forward (an injury, who holds the key, what a character has been told, where an object is kept) count. Momentary description (hands shaking, a flush of anger, the quality of the light) does not, unless it reveals a persistent state (hands shaking because he has been poisoned is a state; capture the poisoning).
> 3. **Could a later sentence break it?** If you cannot write one sentence that would contradict it, it is not a commitment.
>
> If all three are yes, record it as one declarative sentence with its quote. There is no cap. Record the claim, not the image: "Marley's ghost wears a chain made of cash-boxes, keys, padlocks, ledgers, deeds and purses," not "the chain is described vividly."
>
> Always capture: names and their spellings; pronouns and gender; ages and dates; who is related to whom and how; who knows what, and who told them; injuries, illness, possessions, and the locations of people and objects at scene end; the time of day and day the scene occurs; elapsed time stated relative to another event ("three weeks ago," "eight days ago"); counts and quantities (how many survivors, how many records, how many guards); distances and travel times; stated rules of the world; anything a character promises or threatens; anything the narrator states as fact about the past; information conveyed in dialogue.
>
> Never capture: a character's emotion in the moment; sensory texture that recurs nowhere; the narrator's opinions; metaphor read literally; dialogue that is texture rather than information.

Calibration examples for the prompt: "Desta is Corvin's neighbor and friend" is a commitment (it broke in the roundtrip test). "Corvin left a note," what it said, and who found it are commitments. "The surveyor's hands are shaking" is not. From A Christmas Carol: "Scrooge's nephew is Fred and his dead sister was Fan" is three commitments; "the fog came pouring in at every chink" is none.

**6. Scope split.** Separate plugin, named **Storygild**, reading the core export bundle at a pinned `schema_version`. Dashboard rendering lives in Bookshelf, not in either plugin.

**7. E4 test text (decided by the survey's ranking, pending Ben's veto).** shared-dark, Act 1: it is full novel length, its labels are the author's own, and E1, E4, and E8 then share a world. lantern-folk is the fallback when a cheap, fast E4 run is needed during development (15 scenes, 20k words).

### Open

None. Ben can reopen any of the above.

## 7. Implementation chunks for the agent

Each chunk is independently verifiable. Do them in order.

0. **Corpus survey.** Done; see `docs/plans/2026-10-28-storyforge-corpus-survey.md`. Read its per-repo data-quality notes before touching any repo.
1. `evals/harness` — runner, fixture recording, result schema, baseline command. Verify: runs on an empty suite.
2. `evals/e1-corpus` — labeling template with the fields in 4.2 E1; per-repo scene-id maps (slipform's full map is already in the survey; build the others, thornwall by content); exclude author retcons; split bundled fix commits; restrict `git log -S` to `-- scenes/`. Label shared-dark, then thornwall, then lantern-folk, then governor until 100+ prose cases; tag the three subsets; hold out 20% stratified by repo. Verify: counts per code and per subset, holdout file.
3. `evals/e2-detection` + `evals/e7-classics` + `evals/e8-revision-safety` — Gatsby and A Christmas Carol fixtures with injected KNO/REL/PRM errors; fold in Ben's Carol verdicts; E8 built from the `tool-introduced` subset. Verify: baseline numbers recorded per code.
4. `evals/e3-extraction`, `evals/e5-roundtrip`. Verify: baseline numbers recorded.
5. Phase 1: models, thinking, structured outputs, loud failures, plus fixes for the survey's bug tickets. Verify: E2 and a full run with zero silent failures, including the three silent-failure regression tests.
6. `commitments.csv` schema (with `introduced_by`), `pronouns` on `characters.csv`, rubric prompt, migration script (with round-trip test; handle lantern-folk's `fact` column and missing physical-states, and understory's header whitespace), derived state, audit log and digest, `export` with `schema_version`. Verify: E3, E5, export round-trip across all eight repos.
7. Gate pipeline, sequential loop, tiered audit surfacing, context-size experiment. Verify: E4, E6, experiment report.
8. Dependency graph, re-check set, rewrite-from-ledger, reject flow; every revision pass runs through the gate. Verify: E5, E1 re-check cases, E8 at zero.
9. Storygild extraction into its own plugin; Bookshelf consumes the export bundle; `CLAUDE.md` slim. Verify: E7 unchanged, line counts, Storygild runs on a pinned schema.
