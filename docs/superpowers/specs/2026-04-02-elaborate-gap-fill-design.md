# Elaborate Gap-Fill Mode

**Issue:** #63 — Elaborate should fill gaps in extracted data, not just build from scratch  
**Date:** 2026-04-02

## Problem

After running `storyforge extract` on an existing manuscript, the three-file CSV model is populated but has gaps: missing `type` fields, empty `timeline_day` values, knowledge wording drift, and other validation failures. The elaborate skill only supports building from scratch (spine -> architecture -> map -> briefs). There's no mode for reading existing extracted data and filling just the gaps.

## Design

### State Detection

Gap-fill mode activates when all three conditions hold:

1. `scenes.csv` exists with rows where `status=drafted` (scenes already have prose)
2. `scene-briefs.csv` exists and is populated (extraction filled it)
3. `validate_structure()` returns failures > 0

This is distinct from normal elaboration stages because the CSVs are mostly full but have holes — not empty and waiting to be built from scratch.

### Gap Analysis

When gap-fill mode is detected, validation failures are categorized into gap groups. Each group becomes a batch operation:

| Gap Group | Fields | Batch Type | Model |
|---|---|---|---|
| scene-fields | `type`, `time_of_day`, `duration`, `part` | Parallel (batch API) | Sonnet |
| intent-fields | `scene_type`, `emotional_arc`, `value_at_stake`, `value_shift`, `turning_point` | Parallel (batch API) | Sonnet |
| thread-fields | `threads`, `mice_threads` | Parallel (batch API) | Sonnet |
| location-timeline | `location`, `timeline_day` | Parallel (batch API) | Sonnet |
| knowledge | `knowledge_in`, `knowledge_out`, `continuity_deps` | Sequential (direct API) | Sonnet |
| structural | MICE nesting violations, timeline order | Sequential (needs context) | Sonnet |

**Note on the structural group:** Unlike the other groups which fill empty fields, the structural group fixes *inconsistent* values. For MICE nesting violations, the prompt sends the surrounding scenes' thread state and asks Claude to correct the open/close operations. For timeline order violations, the prompt sends adjacent scenes and asks Claude to resolve the backward jump (adjust the violating scene's `timeline_day` or flag it as intentional). These are advisory-to-blocking fixes that may require author review.

The first four groups are independent — scenes can be processed in parallel because each prompt reads one scene's prose and fills the missing field(s). Knowledge and structural fixes require sequential processing because they depend on cumulative state.

Each gap group gets a focused prompt template. For example, the scene-fields prompt sends the scene prose (or first 500 words) and asks for the specific missing field with constrained choices. Small prompts = cheap.

### Execution Flow

```
1. Validate -> categorize gaps into groups
2. Present summary (coaching-level aware)
3. Run parallel gap groups (batch API)
4. Run sequential gap groups (knowledge/structural)
5. Re-validate -> report results
6. If gaps remain -> offer to re-run
```

**Parallel groups (step 3):** All independent gap groups submit as a single batch. Each scene with gaps gets one request per gap group it belongs to. A scene missing both `type` and `value_shift` gets two requests (one in scene-fields batch, one in intent-fields batch). Results are parsed back into the CSVs using `update_csv_field`.

**Knowledge pass (step 4):** Runs sequentially through all scenes in `seq` order. For each scene with knowledge issues, sends the prose + prior knowledge state + the specific validation failure. Claude normalizes wording to match exact `knowledge_out` from prior scenes. Reuses the Phase 3b extraction pattern.

**Re-validation (step 5):** Three possible outcomes:
- **Clean:** "All validation checks pass. Your extracted data is complete."
- **Improved:** "Down from 65 to 8 failures. Remaining: [summary]. Run again to continue."
- **Stuck:** "Same failures remain — these may need manual attention." (Presents specific issues for author resolution.)

### Iterative Design

Gap-fill is designed to run multiple times. Each run:
1. Re-analyzes current validation state (picks up where last run left off)
2. Only processes scenes/fields that still have gaps
3. Commits results on the same `storyforge/gap-fill-*` branch

This means the author can run gap-fill, review results, manually fix some things, then run again to clean up the rest.

### Coaching Level Behavior

- **full:** "I found 5 gap types across 47 scenes. I'll fill them all — starting with the parallel batches." Auto-executes all groups.
- **coach:** "Here are the gaps I found. Which would you like me to work on?" Presents each group as a choice.
- **strict:** "Validation report: 33 scenes missing `type`, 12 missing `timeline_day`..." Data only, author decides what to fix.

### Integration Points

#### Forge Skill

New check in the recommendation priority list, between "elaboration phase active" and "ready to draft":

```
If scenes.csv has status=drafted rows AND validate_structure() has failures > 0:
    -> "Your extracted data has gaps. Run elaborate to fill them."
    -> Routes to elaborate skill in gap-fill mode
```

#### Elaborate Skill

New mode in mode determination. When gap-fill state is detected, the skill skips normal stage progression and goes straight to gap analysis. Existing modes (spine, architecture, map, briefs, voice, characters, world) are unchanged.

Offers the standard two execution options:
- **Option A:** Run interactively in this conversation
- **Option B:** `cd [project_dir] && [plugin_path]/scripts/storyforge-elaborate --stage gap-fill`

#### Elaborate Script

`--stage gap-fill` becomes a valid stage alongside `spine|architecture|map|briefs`. Internally:
1. Calls `analyze_gaps(ref_dir)` — runs validation and groups failures
2. Builds batch JSONL for parallel groups
3. Submits via `submit_batch` / `poll_batch` / `download_batch_results`
4. Runs sequential knowledge pass if needed
5. Re-validates and reports

#### Python Module (elaborate.py)

Two new functions:
- `analyze_gaps(ref_dir) -> dict` — Runs validation, categorizes failures into gap groups with scene lists and missing fields per group
- `build_gap_fill_prompt(scene_id, gap_group, scene_data, prose_excerpt) -> str` — Builds the focused prompt for each gap type

#### Prompt Templates

New templates in `scripts/prompts/` for each gap group. Short, focused prompts that ask for specific fields only.

### What Does NOT Change

- CSV format (pipe-delimited, same columns)
- Validation logic (same checks, same return structure)
- Extraction pipeline (extract script unchanged)
- Deterministic cleanup functions (still run during extraction)
- Any other existing scripts or skills

## Acceptance Criteria (from issue)

- [x] Elaborate detects post-extraction state (scenes.csv exists, status=drafted, briefs populated, but validation failures > 0)
- [x] Offers targeted gap-fill mode (not full stage rebuild)
- [x] Gap-fill runs as batch API calls for the specific missing fields
- [x] Forge recommends this as the next step after extraction
- [x] Coaching levels apply: full=auto-fill, coach=ask about each gap type, strict=report gaps only
