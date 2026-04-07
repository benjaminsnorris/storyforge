# Upstream Naturalness Fix Pipeline

## Problem

Prose naturalness revision passes fail to improve scores when the root cause is upstream — conflict-free briefs, emotional ceilings from voice guides, or observation-only scene designs. The current pipeline hardcodes `fix_location: craft` for all naturalness and polish passes, so scenes get re-polished cycle after cycle without improvement. Three systems (scoring, evaluation, hone) each see part of the problem but cannot communicate:

- **Scoring** detects low naturalness but diagnosis is purely numeric — never asks *why*
- **Evaluation** findings assign `fix_location: brief` or `craft` per finding, but `--polish` and `--naturalness` ignore them
- **Hone** checks brief quality for abstract language and verbosity, but not for conflict-free scenes

## Solution Overview

Five changes that close the loop:

1. **Score history tracking** — cross-cycle score comparison
2. **Conflict-quality detection** — catch briefs that lack genuine dramatic opposition
3. **Causal routing in diagnosis** — attribute naturalness problems to root causes
4. **Upstream pass in revision** — fix briefs before polishing prose
5. **AI pattern regression detection** — flag scenes stuck in revision loops

## 1. Score History Tracking

### New file: `working/scores/score-history.csv`

Pipe-delimited. Columns: `cycle|scene_id|principle|score`. Appended after each scoring cycle.

Growth: scenes × principles × cycles. A 100-scene novel with 25 principles over 10 cycles = 25K rows — trivially small.

### New module: `scripts/lib/python/storyforge/history.py`

```python
def append_cycle(scores_dir: str, cycle: int, project_dir: str) -> int:
    """Read scene-scores.csv from scores_dir, append rows to score-history.csv.
    Returns number of rows appended."""

def get_scene_history(project_dir: str, scene_id: str, principle: str) -> list[tuple[int, float]]:
    """Returns list of (cycle, score) tuples for one scene+principle."""

def detect_stalls(project_dir: str, principle: str,
                  min_cycles: int = 2, max_score: float = 3.0) -> list[dict]:
    """Find scenes where principle has scored <= max_score for >= min_cycles
    consecutive cycles without improvement.
    Returns: [{scene_id, scores: [(cycle, score)], cycles_stalled: int}]"""

def detect_regressions(project_dir: str, principle: str,
                       threshold: float = -0.5) -> list[dict]:
    """Find scenes where principle score dropped by >= threshold.
    Returns: [{scene_id, from_cycle, to_cycle, from_score, to_score, delta}]"""
```

### Integration point: `cmd_score.py`

After writing scene-scores.csv and before the improvement cycle, call `append_cycle()`. This is a single append operation — no disruption to existing flow.

## 2. Conflict-Quality Detection

### New issue type: `conflict_free`

Added to `detect_brief_issues()` in `hone.py` via a new `detect_conflict_free()` function.

**Two detection methods, both deterministic, zero API cost:**

#### Keyword check

Scan the `conflict` field for observation/contemplation patterns vs. opposition patterns.

Observation indicators (scene describes watching, not colliding):
- `notices`, `observes`, `discovers`, `reflects`, `grapples with`, `contemplates`, `realizes`, `wonders`, `considers`, `processes`, `absorbs`, `witnesses`

Opposition indicators (something resists the protagonist):
- `refuses`, `blocks`, `demands`, `threatens`, `confronts`, `denies`, `challenges`, `prevents`, `forbids`, `attacks`, `rejects`, `opposes`, `locks`, `traps`, `forces`

Flag when: conflict field has zero opposition indicators AND at least one observation indicator.

#### Structural cross-reference

Flag scenes where ALL of:
- `conflict` field is non-empty (so it's not caught by gap detection)
- `outcome` is `yes` (no resistance — protagonist got what they wanted)
- `value_shift` is flat (`+/+` or `-/-`) (no change in value polarity)

A scene with no value shift and an easy win structurally cannot have real conflict, regardless of what the conflict field says.

#### Return format

Matches existing issue format:
```python
{
    'scene_id': str,
    'field': 'conflict',  # always conflict for this issue type
    'value': str,          # current conflict field value
    'issue': 'conflict_free',
    'reason': 'keyword' | 'structural' | 'both',
    # For keyword matches:
    'observation_count': int,
    'opposition_count': int,
    # For structural matches:
    'outcome': str,
    'value_shift': str,
}
```

## 3. Causal Routing in Diagnosis

### Extended diagnosis.csv

Add column: `root_cause` (values: `brief`, `intent`, `voice_guide`, `craft`).

### Attribution logic in `generate_diagnosis()`

For each principle/scene pair flagged as high or medium priority:

1. **Check stall history** (if score-history.csv exists): Is this scene stalled on this principle for 2+ cycles? If yes, elevate to `brief` cause candidate.

2. **Check brief quality**: Does `detect_brief_issues()` flag this scene with `conflict_free`, `abstract`, or `overspecified`? If yes → `root_cause: brief`.

3. **Check evaluation findings** (if evaluation data exists in `working/evaluations/`): What `fix_location` did evaluators assign for this scene? Use as override if available.

4. **Default**: `root_cause: craft`.

Priority: evaluation findings > brief quality check > stall history > default.

### No breaking changes

Existing consumers of diagnosis.csv that don't read `root_cause` are unaffected — it's an additional column.

## 4. Upstream Pass in Revision

### Modified `--polish --loop` flow

Before generating craft passes each iteration, read diagnosis for scenes with `root_cause: brief`:

1. **Brief rewrite pass**: For stalled scenes with conflict-free or abstract briefs, generate a brief-rewrite prompt. Use the existing `fix_location: brief` code path in the revision executor (already implemented, just never reached by polish/naturalness). The prompt rewrites `conflict`, `goal`, `crisis`, and `decision` fields to introduce genuine opposition.

2. **Re-draft pass**: After brief rewrites, re-draft the affected scenes using `cmd_write` logic (brief-aware drafting). This ensures the new conflict actually manifests in prose.

3. **Craft polish**: Proceed with normal craft polish for all scenes (including the re-drafted ones).

This means a `--polish --loop` run might look like:
- Iteration 1: Fix 3 briefs, re-draft 3 scenes, polish all scenes
- Iteration 2: Score, no more upstream issues, polish remaining craft issues
- Iteration 3: Score, converged

### Modified `--naturalness` flow

Same logic: check diagnosis before generating the 3-pass naturalness plan. Exclude stalled-upstream scenes from craft passes and insert brief rewrite + re-draft for those scenes.

### Guarding against unnecessary re-drafts

Only re-draft if:
- The brief was actually modified (field values changed)
- The scene has been scored at least once (we have baseline data)
- The scene's naturalness score is ≤ 3.0 (don't re-draft scenes that are fine)

## 5. AI Pattern Regression Detection

### In `history.py`

`detect_regressions()` finds scenes where a principle score dropped significantly between consecutive cycles. This catches cases where a revision pass made things worse (like `community` going from 3 to 2).

### In `hone --diagnose`

Add a new section to diagnose output:

```
=== Score Trends ===

  Stalled (2+ cycles without improvement):
    community: naturalness stuck at 2 (cycles 5, 6, 9)
    deeper: naturalness stuck at 3 (cycles 6, 7, 9)

  Regressions:
    community: naturalness dropped 3 → 2 (cycle 5 → 6)

  Recommendation: These scenes need upstream fixes (brief rewrite),
  not more prose revision. Run: storyforge revise --polish --loop
```

This gives the author visibility into why certain scenes aren't improving.

## 6. Documentation Updates

### CLAUDE.md

- Add `history.py` to shared modules table with function signatures
- Add `conflict_free` to brief issue types list
- Add `score-history.csv` to key CSV files section
- Add `root_cause` column to diagnosis.csv description

### Hone skill (skills/hone/SKILL.md)

- Update diagnose flow to mention stall detection and conflict-free briefs
- Add score trends section to diagnose output description
- In full coaching mode: when stalls detected, explain upstream routing and run `--polish --loop` which now handles it automatically

### Revise skill (skills/revise/SKILL.md)

- Document that `--polish --loop` now auto-detects upstream causes
- Explain the brief-rewrite → re-draft → polish flow
- Note that `--naturalness` also checks upstream causes
- Add guidance: if naturalness isn't improving after 2 polish passes, the system will automatically try brief rewrites

### Forge skill (skills/forge/SKILL.md)

- Update routing: when naturalness is stalled, explain the upstream fix rather than recommending another polish pass
- Add to the recommendation engine: check score history before suggesting revision approaches

## File Changes Summary

| File | Change |
|------|--------|
| `scripts/lib/python/storyforge/history.py` | **New** — score history tracking, stall/regression detection |
| `scripts/lib/python/storyforge/hone.py` | Add `detect_conflict_free()`, integrate into `detect_brief_issues()` |
| `scripts/lib/python/storyforge/cmd_hone.py` | Add score trends section to `_run_diagnose()` |
| `scripts/lib/python/storyforge/scoring.py` | Add `root_cause` column to `generate_diagnosis()` |
| `scripts/lib/python/storyforge/cmd_score.py` | Call `append_cycle()` after scoring |
| `scripts/lib/python/storyforge/cmd_revise.py` | Upstream pass in `--polish --loop` and `--naturalness` |
| `CLAUDE.md` | Document new module, file, issue type, column |
| `skills/hone/SKILL.md` | Update diagnose flow |
| `skills/revise/SKILL.md` | Document upstream routing |
| `skills/forge/SKILL.md` | Update recommendation routing |
