# Score-to-Revision Flow: Narrative Radar Chart & Pipeline Fixes

**Date:** 2026-03-14
**Status:** Approved

## Summary

Three changes to improve how scores visualize and drive revision:

1. Move Narrative framework scoring from per-scene to novel-level
2. Add a radar chart to the dashboard showing the narrative craft profile
3. Fix two broken links in the score → diagnosis → proposal → revision pipeline

## Motivation

Narrative frameworks (Campbell's Monomyth, Three Act, etc.) describe whole-manuscript structure. Scoring them per-scene is meaningless. An author's narrative profile is a creative choice — leaning into Three Act but not Kishotenketsu isn't a deficiency.

Meanwhile, the existing pipeline has two dead ends: `working/overrides.csv` is written but never read, and scoring proposals never reach revision planning.

## Change 1: Novel-Level Narrative Scoring

### Current state

The 7 Narrative principles are scored per-scene alongside the other 37 principles in `storyforge-score`. The diagnostics.csv has ~4 markers per narrative principle, asked about individual scenes.

### Proposed state

- **Remove** the 7 Narrative principles from the per-scene scoring pass (scene-level diagnostics)
- **Add** a novel-level narrative scoring pass that runs once per cycle after scene scoring completes
- This pass reads the full scene index (metadata + intent CSVs), the chapter map, and story architecture to evaluate manuscript alignment with each framework
- Uses a single API call (Sonnet) with all structural data inlined

### Output

`working/scores/cycle-N/narrative-scores.csv`:
```
principle|score|rationale
campbells_monomyth|4|Strong departure and ordeal arcs; weak return sequence...
three_act|5|Clear act breaks, rising complications, climactic resolution...
save_the_cat|3|Opening image and catalyst present; missing fun-and-games...
truby_22|2|Self-revelation present but weak need/desire distinction...
harmon_circle|4|Strong want/get/pay cycle; return arc underdeveloped...
kishotenketsu|1|No discernible four-act twist structure...
freytag|3|Exposition and climax clear; falling action rushed...
```

### Score interpretation

The meaning shifts from the per-scene scale:
- **5** = Strongly aligned with this framework
- **4** = Mostly aligned, minor gaps
- **3** = Partially aligned, some structural beats present
- **2** = Loosely aligned, a few elements present
- **1** = Not using this framework (which is fine — it's a creative choice)

### Changes to diagnostics.csv

Remove the 7 Narrative rows from the scene-level diagnostics. Create a separate `references/narrative-diagnostics.md` (or inline in the scoring prompt) with novel-level evaluation criteria for each framework.

### Changes to storyforge-score

- After scene scoring and before diagnosis, run the narrative scoring pass
- Skip narrative principles in the scene scoring loop
- Narrative scores feed into the dashboard but NOT into diagnosis/proposals (they're informational)

## Change 2: Narrative Radar Chart

### Location

New panel on the dashboard (`working/dashboard.html`), placed after the existing score heatmap.

### Design

Polar/radar chart with:
- **7 spokes**, one per narrative framework
- **5 concentric rings** representing score values 1-5
- Each framework's **wedge filled** to its score level
- Fill color uses existing score color variables (`--score-low` through `--score-high`)
- Labels around the perimeter with framework short names
- Score value displayed at the tip of each wedge

### Data source

Reads `narrative-scores.csv` from the latest scoring cycle directory. If no narrative scores exist, shows placeholder text: "Run a scoring cycle to see narrative profile."

### Aggregation

Whole manuscript only — one radar for the entire book. No per-act or per-scene breakdown.

### Technical approach

SVG-based, generated in the same vanilla JS pattern as existing dashboard charts. No external dependencies. Supports dark/light mode via CSS variables.

## Change 3: Pipeline Fixes

### Fix 1: plan-revision reads scoring data

**Current:** `plan-revision` skill reads only evaluation findings (`findings.yaml`/`findings.csv`).

**Proposed:** When building revision passes, the skill also reads:
- `working/scores/latest/diagnosis.csv` — high-priority craft deficits
- `working/scores/latest/proposals.csv` — recommended improvements

Scoring data supplements evaluation findings. Evaluation findings drive pass structure (what to fix); scoring proposals inform pass guidance (how craft principles should shift).

### Fix 2: Overrides consumed during revision

**Current:** `storyforge-revise` never reads `working/overrides.csv`.

**Proposed:** When building the revision prompt for each pass:
1. Read `working/overrides.csv`
2. Filter for entries relevant to the pass's scope (matching scenes or principles)
3. Include as additional guidance in the prompt: "The following craft overrides have been approved: [voice_guide entries, scene_intent entries]"

### Fix 3: Manual invocation preserved

The author controls the flow between steps. No automation chaining score → plan → revise. Each step requires explicit invocation.

## What doesn't change

- The other 37 principles (Scene Craft, Prose Craft, Character Craft, Rules, Genre) still score per-scene
- The existing score heatmap remains for per-scene/per-principle detail
- The diagnosis → proposals flow for non-narrative principles is untouched
- The evaluate → plan-revision → revise path still works independently of scoring
- Craft weight calibration via the score skill is unchanged

## Implementation order

1. Extract narrative principles from scene-level scoring
2. Add novel-level narrative scoring pass to `storyforge-score`
3. Add radar chart to `storyforge-visualize`
4. Update `plan-revision` skill to read scoring data
5. Update `storyforge-revise` to consume `working/overrides.csv`
6. Update `score` skill review mode to display narrative profile
7. Tests
