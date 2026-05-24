# Per-level rubrics and cross-level fidelity scoring

Research design doc for issue [#227](https://github.com/benjaminsnorris/storyforge/issues/227), under the umbrella [#224](https://github.com/benjaminsnorris/storyforge/issues/224).

Companion to [the levels-and-shapes doc](2026-05-24-elaboration-levels-design.md) and [the cascade-mechanics doc](2026-05-24-cascade-mechanics-design.md) — read those first; this one refers to the level numbering they establish.

Status: **draft**, expects iteration. Implementation out of scope.

---

## TL;DR

Three score families. Most are cheap; a few are expensive; the expensive ones run on demand.

- **Per-level quality.** Eight rubrics, one per level. Some reuse existing scoring (level 7 already has the 25-principle novel-mode rubric and the 6-principle GN-mode rubric); some are new (logline, synopsis).
- **Cross-level fidelity.** Two scores at each of the seven boundaries: *downward coverage* (deterministic where possible) and *upward faithfulness* (LLM-driven). The prose-tier boundaries (0↔1, 1↔2, 2↔3) get LLM-only scoring; the structural-tier boundaries get deterministic coverage plus optional LLM faithfulness.
- **Cross-cutting consistency.** Registry conformance (deterministic, already partly in `hone`) plus bible consistency (LLM-driven, on-demand).

Two design principles run through the whole proposal:

1. **Don't compose.** Show each axis to the author separately. A single composite number hides which axis is broken and what to fix.
2. **Be choosy.** Add a score only if a bad value means something is broken AND the fix is concrete AND ideally the computation is cheap. Cull aggressively.

---

## Three families of score, side by side

| Family | What it measures | Cost profile | Cadence |
|---|---|---|---|
| Per-level quality | Is this level any good on its own terms? | Mix: cheap for structural (count-based, registry-based); expensive for prose (LLM) | On demand |
| Cross-level fidelity, downward | Does the lower level realize the upper? | Cheap (mostly set coverage) | Always-on (cheap enough to run in `sync` hook) |
| Cross-level fidelity, upward | Does the lower level honor what's above? | Expensive (LLM, semantic) | On demand only |
| Registry consistency | Do structural fields reference real registry entries? | Cheap (set comparison) | Always-on |
| Bible consistency | Does this artifact honor the character/world/voice bibles? | Expensive (LLM) | On demand only |

The two "expensive + on-demand" lines are the ones we have to be most careful about. They want clear, actionable findings or they become noise the author learns to ignore.

---

## Per-level quality rubrics

For each level, what does "good" look like? Some criteria are deterministic; some need an LLM. Some reuse existing scoring; some are new.

### Level 0 — Logline

| Check | Mechanism | Source |
|---|---|---|
| Length ≤ 35 words | deterministic | new |
| Names a protagonist | LLM | new |
| Names a want/goal | LLM | new |
| Names an obstacle | LLM | new |
| Names stakes | LLM | new |
| Genre/tone legible | LLM | new |

All four LLM checks fit in one prompt → one API call. Cheap-enough on-demand.

### Level 1 — Synopsis

| Check | Mechanism | Source |
|---|---|---|
| Length 4–8 sentences | deterministic | new |
| Opens with a hook (inciting incident or premise) | LLM | new |
| Names the protagonist + central conflict | LLM (logline alignment) | new |
| Reveals the ending or resolution (this is internal, not a pitch) | LLM | new |
| Stays at "story" abstraction (no scene-level specifics) | LLM | new |

### Level 2 — Act-shape

| Check | Mechanism | Source |
|---|---|---|
| Exactly 3 paragraphs | deterministic | new |
| Each paragraph names a turn (inciting / midpoint / climax) | LLM | new |
| Escalation is visible (act stakes grow) | LLM | new |
| Theme is implicit in the shape | LLM | new |

### Level 3 — Spine

| Check | Mechanism | Source |
|---|---|---|
| 5–10 events for novel / 4–8 for GN | deterministic | new |
| Events spread roughly evenly across acts | deterministic | new |
| Each event has a non-empty `function` in scene-intent | deterministic | reuse (already validated) |
| Each event is irreducible (cutting it breaks causation) | LLM | new |
| Causal chain holds (event N enables event N+1) | LLM | new |

### Level 4 — Architecture

| Check | Mechanism | Source |
|---|---|---|
| 15–25 scenes total (novel) / 10–18 (GN) | deterministic | new |
| Every scene has `part`, `pov`, `action_sequel`, `emotional_arc`, `value_at_stake`, `value_shift`, `turning_point` | deterministic | reuse (structural validation) |
| Action/sequel alternates | deterministic | new (count check on `action_sequel`) |
| Value shifts present and varied | deterministic | reuse (existing flat-shift check) |
| POV distribution matches story design | deterministic + LLM | new |

### Level 5 — Scene map

| Check | Mechanism | Source |
|---|---|---|
| Every scene has `location`, `timeline_day`, `time_of_day`, `duration` | deterministic | reuse |
| Timeline is causally consistent | deterministic + LLM | reuse partial (timeline construction) |
| POV is on-stage where they're POV | deterministic | reuse (`hone`) |
| MICE threads opened are closed | deterministic | new (set walk on `mice_threads`) |
| Scene types are diverse | deterministic | new (count check) |

### Level 6 — Briefs

| Check | Mechanism | Source |
|---|---|---|
| Goal / conflict / outcome / crisis / decision present | deterministic | reuse (structural scoring) |
| knowledge_in / knowledge_out flow correctly | deterministic | reuse |
| key_dialogue / key_actions specific (not abstract) | LLM | reuse (`hone` abstract detection) |
| GN: panel_breakdown / page_layout / visual_keywords present | deterministic | reuse |
| Brief honors scene-intent's value_at_stake | LLM | new (this is a 5→6 fidelity check too) |

### Level 7 — Draft

**Use existing scoring.** Novel mode: the 25-principle rubric in `scoring.py`. GN mode: the 6-principle deterministic rubric in `scoring_gn.py` plus the 3-persona evaluation panel.

No new per-level rubric needed at level 7. The existing scoring is the rubric.

---

## Cross-level fidelity scoring

At each of the seven level boundaries (0↔1, 1↔2, ..., 6↔7), two scores:

- **Downward coverage** — does the lower level realize the upper?
- **Upward faithfulness** — does the lower level honor what's above?

These are different questions and need different checks.

### The cross-level scoring matrix

| Boundary | Downward (deterministic where possible) | Upward (LLM) |
|---|---|---|
| 0 → 1 Logline → Synopsis | None deterministic — both are prose | "Does the synopsis still describe the logline's story?" |
| 1 → 2 Synopsis → Act-shape | None deterministic | "Does the act-shape match the synopsis's outline?" |
| 2 → 3 Act-shape → Spine | Each spine event maps to one of the three acts (per `part` column) | "Does the spine embody the act-shape's turns?" |
| 3 → 4 Spine → Architecture | Every spine event has descendant scenes in `scenes.csv` (need a `spine_event` reference column — see "Schema additions" below) | "Do the architecture scenes serve the spine?" |
| 4 → 5 Architecture → Map | Every architecture scene has full map columns populated | "Does the map's operational metadata honor architecture's structural intent?" |
| 5 → 6 Map → Briefs | Every map scene has a brief row | "Does the brief honor the scene-intent?" |
| 6 → 7 Briefs → Draft | Every brief has a draft file with word_count > 0 | "Does the draft honor the brief?" (reuse: this is exactly `brief_fidelity` in scoring_gn.py and the upward signal of `revise --findings`) |

### Where the prose tier is special

The 0↔1, 1↔2 boundaries (and partly 2↔3) have no clean deterministic downward checks — both sides are prose. **All scoring at these boundaries is LLM-driven.** That's expensive and noisy, so we should:

- Run these scores only on demand (not in the hook).
- Trigger them from the cascade: if the drift detector sees mismatched `_updated` timestamps between, say, logline and synopsis, *then* run the LLM check.
- Cache results between runs; only re-check if either side has been touched.

### Schema additions to make downward coverage cheap

The deterministic downward check at 3 → 4 (Spine → Architecture) needs a way to map architecture scenes to their parent spine event. Today nothing tracks this — architecture scenes are just rows with `status=architecture`; their relationship to spine events is implicit in the title/sequence.

**Proposed addition: `spine_event` column in `scene-intent.csv`.** When the architecture stage elaborates the spine, each new scene gets the `id` of its parent spine event recorded. Downward coverage becomes a trivial set check.

For 2 → 3 (Act-shape → Spine), the existing `part` column on scenes.csv already partitions spine events into acts; no new column needed. The downward check is "each act has at least one spine event," "each act has events proportional to its length."

For higher levels, the CSV row identity *is* the parent-child relationship (every architecture scene IS a map scene IS a brief IS a draft — same `id`, more columns populated). No new columns needed.

---

## Cross-cutting consistency

### Registry conformance (deterministic)

For every level that has structural data (3–7), check that all references point to real registry entries:

| Reference | Registry | Levels where applicable |
|---|---|---|
| `pov` | `characters.csv` | 4, 5, 6, 7 |
| `characters` | `characters.csv` | 5, 6, 7 |
| `on_stage` | `characters.csv` | 5, 6, 7 |
| `location` | `locations.csv` | 5, 6, 7 |
| `value_at_stake` | `values.csv` | 4, 5, 6, 7 |
| `motifs` | `motif-taxonomy.csv` | 6, 7 |
| `mice_threads` | `mice-threads.csv` | 5, 6, 7 |
| `physical_state_in` / `physical_state_out` | `physical-states.csv` | 6, 7 |

These are pure set comparisons — each one is one CSV read + one set difference. Cheap. Already partly implemented in `hone`. The reorganization here is making the pattern explicit per level instead of hone-specific.

**Score:** for each (level, registry) pair, `coverage = 1.0 - (orphan_count / total_refs)`. A score of 1.0 means every reference resolves; less than 1.0 means orphans exist. Findings are the orphan list with their containing scene IDs.

### Bible consistency (LLM, on demand)

The bibles are richer than the registries — they contain prose descriptions of characters, world systems, voice. Their consistency check is necessarily semantic:

| Check | Levels |
|---|---|
| Does the logline reflect the character bible's protagonist? | 0 |
| Does the synopsis honor the world bible's setting/rules? | 1, 2 |
| Do the briefs honor the voice guide's tone fingerprint? | 6 |
| Do the drafts honor the character/world/voice bibles? | 7 (already partially scored) |

These run on demand only (`storyforge score --against-bibles` or similar). They're slow and noisy enough that they should not be wired into the hook.

---

## Composition (or: deliberately don't)

A scene at level 5 has multiple scores against it:

- Map-level quality score
- Map-level registry consistency
- Architecture → Map downward coverage (was this scene properly elaborated?)
- Architecture → Map upward faithfulness (does the map honor architecture?)
- Map → Briefs downward coverage (does the brief exist?)

Tempting to compose these into one "scene 5 health" number. Don't. The whole point of multi-axis scoring is that different axes mean different things; collapsing them hides which axis is broken.

**Reporting format proposal:** for any level, the author can run `storyforge score --level 5` and get a table:

```
SCENE         Map-quality  Reg-consist  ↓Coverage  ↑Faithful  ↓Briefs
act1-sc01        0.92         1.00       1.00       0.85       1.00
act1-sc02        0.88         1.00       1.00       0.90       0.00*
act1-sc03        0.95         0.83**     1.00       0.88       1.00

*  no brief row yet (forward elaboration needed)
** 1 orphan reference: value_at_stake="grace" not in values.csv
```

One row per scene, one column per axis. Lowest-scoring scenes float to the top via existing sort logic. The asterisks reference notes; the author sees not just a number but the specific finding.

This is exactly how the existing scene-prose scoring already reports. Reuse the table format.

---

## Choosiness pass

Now the uncomfortable part: which of the scores I just proposed actually earn their keep?

### Definitely keep

- **All deterministic checks.** Registry conformance, structural-tier downward coverage, presence/count rubrics. Cheap, signal-rich, fix-actionable.
- **Existing scene-prose scoring** (level 7). Not changing it.
- **Brief-fidelity in `revise`'s `--findings` loop.** Already exists; reuse for 6 → 7 upward.
- **`hone` brief-quality checks.** Already exist; reuse for level 6 quality.

### Probably keep, but on-demand only

- **LLM upward faithfulness at structural boundaries.** Useful when the cascade flags drift. Don't run continuously.
- **Bible consistency.** Useful pre-publish or pre-major-revision. Don't run continuously.
- **Prose-tier LLM quality checks** (logline craft, synopsis structure, etc.). Useful when iterating at the top. Don't run continuously.

### Worth thinking about whether to keep at all

- **MICE threads opened are closed** (level 5 quality). Could be a deterministic walk, but the failure case ("a thread is open at the end") is sometimes intentional. Risk: noise.
- **Causal chain at spine level.** This is a strong claim and probably needs human judgment — an LLM saying "event N doesn't enable event N+1" might be wrong. Might be worth flagging as advisory only.
- **Scene types are diverse.** A genre constraint, not a universal one. Maybe per-genre rubrics. Skip in v1.

### Skip

- **Composite scores.** Explicit non-feature.
- **Time-series scoring** (scene quality improving over revisions). Already exists in `score-history.csv`; not redoing it.
- **Inter-scene narrative-arc scoring.** Tempting but out of scope — the existing architecture-level value-shift checks are the closest we go.

---

## Reuse vs. new code

What carries over from existing scoring, what's new:

| Component | Source | Status |
|---|---|---|
| Deterministic scene-prose scoring (novel + GN) | `scoring.py`, `scoring_gn.py`, etc. | Reuse as-is for level 7 |
| Persona evaluation panel | `cmd_evaluate.py`, `cmd_evaluate_gn.py` | Reuse for level 7 |
| Registry validation logic | `hone.py` | Generalize — apply the pattern at every level, not just briefs |
| Structural scoring (brief-level) | `structural.py` | Reuse for level 6 |
| Findings → revision feedback loop | `cmd_revise.py`, `cmd_revise_gn.py` | Reuse for 6→7 upward fidelity |
| Score history tracking | `history.py`, `score-history.csv` | Reuse, extend schema to include level + boundary scores |
| Per-level quality rubrics for levels 0–5 | — | New |
| LLM faithfulness scoring at boundaries | — | New (small wrapper per boundary; reuses API/cost infra) |
| Cross-cutting bible-consistency scoring | — | New |
| Score reporting at non-scene levels (logline, synopsis, etc.) | — | New |

**Where this lands in code (rough):**

- `scoring_levels.py` — new module: per-level quality rubrics for levels 0–6, dispatching to existing scorers where they exist.
- `scoring_boundary.py` — new module: cross-level fidelity checks, both directions.
- `scoring_consistency.py` — new module: registry + bible conformance, applied per level.
- `cmd_score.py` (and `cmd_score_gn.py`) — extended to accept `--level N`, `--boundary N-M`, or `--all`.

This is implementation detail and out of scope for the design doc, but flagged so future implementers know the existing scoring code doesn't need to be refactored from the ground up.

---

## How the scores feed cascade

This is where #226 and #227 stitch together.

The cascade's deterministic drift detection asks one question: "is something out of date or missing?" That's coverage and freshness, not quality. The scoring family that powers cascade is **downward coverage** + **timestamps**.

The cascade's semantic drift detection asks: "are these two levels still saying the same story?" That's **upward faithfulness** scoring. Cascade triggers these LLM checks on demand when the deterministic signals suggest something may be wrong.

The other score families (per-level quality, bible consistency) are NOT for cascade. They're for the author iterating on a level deciding whether it's good enough to advance from.

So the dependency reads:

- Cascade detection → uses downward coverage + timestamps (cheap)
- Cascade `--semantic` → uses upward faithfulness (expensive)
- Author quality check at any level → uses per-level quality + registry + bible consistency

Three different reasons to score, with three different cost/cadence profiles.

---

## What's deliberately not in this doc

- **Exact LLM prompts** for the new scoring checks. Implementation.
- **Score thresholds** (what counts as "passing" at each level). These should emerge from iteration on real projects, not be locked in at design time.
- **Per-genre rubric variants** (literary vs. thriller vs. romance). Future extension; level rubrics are genre-agnostic for v1.
- **Visualization / dashboard.** Out of scope; the table view above is the v1 surface.
- **Scoring of the bibles themselves.** Are the bibles internally consistent? Are they complete? Open question; flagged as future work.

---

## Open questions

1. **Schema addition for spine_event reference.** Adding `spine_event` to `scene-intent.csv` is the cleanest way to get cheap 3→4 downward coverage. The cost is one new column. Worth it. (Implementation note, but flagged here because the design depends on it.)

2. **Composite "level health" view.** I argued against composition in the report. But for cascade UI ("is level 5 in good shape overall?"), some reduction may be necessary. Probably a *traffic-light* view (green/yellow/red per axis) rather than a single number. Decide during implementation.

3. **What if the existing scene-prose scoring's 25 principles overlap with the brief-level quality rubric?** Some principles (e.g., dialogue compression) are level-7 concerns. Some (economy_clarity) might apply to the synopsis too. Decide per-principle whether it generalizes upward.

4. **Threshold-triggered automatic LLM checks.** If a deterministic check finds a coverage gap, should the system automatically run the LLM faithfulness check for the affected branch? Tempting (it's more thorough) but expensive (could run dozens of LLM calls without asking). Default: no auto-trigger; cascade surfaces the issue and the author decides.

5. **Scoring as part of `sync`.** The deterministic cheap scores (registry, coverage, presence) could run in the pre-commit hook alongside sync. The hook would refuse commits with new orphan registry references, new coverage gaps, etc. This is a *quality gate* that the existing sync hook doesn't have. Author preference — some authors will want it, some will find it noisy. Make it opt-in.

---

## Acceptance criteria for the design

This doc is "done" when:

- Each of the eight levels has a quality rubric, even if it's "reuse existing."
- Each of the seven boundaries has both downward and upward scoring proposals, with explicit "this is LLM-only" or "this has a deterministic check."
- Registry consistency is generalized from `hone` to every level.
- Bible consistency is enumerated and explicitly cost-flagged.
- The choosiness pass has been done — every proposed score has an explicit "keep / on-demand / skip" judgment.
- The relationship to cascade is unambiguous (which scores power cascade, which don't).
- Open questions are listed.

(Self-assessment: all pass at the draft level. Open question 1 — schema addition — and open question 5 — quality gates in sync — want explicit author input before implementation.)
