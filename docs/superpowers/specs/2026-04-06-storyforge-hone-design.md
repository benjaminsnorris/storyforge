# storyforge-hone: CSV Data Quality Tool

## Problem

CSV data quality work is scattered across four different tools:
- `storyforge-reconcile` — registry normalization
- `storyforge-validate` — detection only (no fixes)
- `storyforge-revise` — structural CSV fixes mixed in with prose revision
- `storyforge-elaborate --gap-fill` — filling missing fields

A new requirement — brief concretization (rewriting abstract brief language as concrete physical beats) — doesn't fit cleanly in any of them. Meanwhile, the evaluate → revise cycle routes `fix_location: 'brief'` findings to revise, which then does CSV edits that are conceptually different from prose revision.

## Solution

A single script, `storyforge-hone`, that owns all CSV data quality work. It absorbs `storyforge-reconcile` and adds new domains. No prose is touched. Domain-based passes each follow the pattern: read CSVs → detect problems → improve fields → write back.

`storyforge-reconcile` becomes a backwards-compatible alias for `storyforge-hone --domain registries`.

## Domains

### registries (absorbs storyforge-reconcile)

Exactly what `storyforge-reconcile` does today. Build canonical registries (Opus), normalize field values against alias maps (deterministic). Sub-domains: characters, locations, values, mice-threads, knowledge, outcomes, physical-states.

No changes to the existing reconciliation logic — it moves into `storyforge-hone` as-is.

### briefs (new)

Concretize abstract brief language as concrete physical/sensory beats. Targets: `key_actions`, `knowledge_in`, `knowledge_out`, `crisis`, `decision`.

**Detection:** Classify each field value as abstract or concrete. Abstract indicators: thematic verbs (realizes, connects, recognizes, crystallizes, deepens, builds), narrator language (the tension, the parallel, the realization), emotion names used as actions (grief washing over, clarity emerging). Concrete indicators: subject-verb-object with physical nouns, body parts, objects, locations, sensory details.

**Trigger:** Scenes where prose_naturalness scores below threshold (configurable, default 3.5). Also runs manually via `--domain briefs`.

**Action (by coaching level):**
- **full:** Claude reads scene brief, voice guide, character bible entry for POV character, and (if available) the existing scene prose. Rewrites abstract fields as concrete physical beats. Writes directly to scene-briefs.csv.
- **coach:** Claude produces proposed rewrites. Saves to `working/hone/briefs-{scene_id}.md` for author review. Author applies manually.
- **strict:** Claude reports which fields are abstract and why. Saves analysis to `working/hone/briefs-analysis-{scene_id}.md`. No rewrites proposed.

**Prompt:** For each flagged scene, the prompt includes:
- Current field values (what to rewrite)
- Voice guide (POV character's sensory palette, metaphor domain)
- Character bible entry (what this character notices, how they process)
- The concretization rule: "Every action must be something the POV character physically does or perceives. No thematic descriptions, no narrator interpretations, no emotion names as events."
- Example of abstract → concrete transformation (from our experiment)

**Output format:** Same pipe-delimited CSV fields, same format. The rewrite replaces the field value in-place.

### structural (absorbs revise upstream CSV fixes)

Fix specific CSV fields based on evaluation findings where `fix_location` is `brief`, `intent`, or `structural`. Currently this logic lives conceptually in `storyforge-revise` but the revise skill/script would route these findings to `storyforge-hone --domain structural` instead.

**Detection:** Read `working/scores/` for findings with `fix_location` in `{brief, intent, structural}`. Or read evaluation synthesis for scene-specific recommendations that target CSV data.

**Action:** For each finding, Claude reads the current CSV values and the finding, then applies the fix. Same coaching level behavior as briefs domain.

### gaps (absorbs elaborate gap-fill)

Fill empty fields from context — existing scene data, neighboring scenes, and optionally prose. Currently in `storyforge-elaborate --gap-fill`.

**Detection:** Scan CSV columns for empty fields that should be populated given the scene's status. Uses the `_REQUIRED_BY_STATUS` mapping from elaborate.py.

**Action:** Claude reads surrounding scene data (prior/next scenes, same-part scenes) and fills missing fields. Same coaching level behavior.

## Interface

```
storyforge-hone                              # Run all domains in order
storyforge-hone --domain briefs              # Run one domain
storyforge-hone --domain registries,briefs   # Run specific domains in order
storyforge-hone --domain registries --phase 1  # Run registry sub-domains for extraction phase 1
storyforge-hone --scenes ID,ID               # Scope to specific scenes
storyforge-hone --act N                      # Scope to a part/act
storyforge-hone --threshold 3.5              # prose_naturalness threshold for briefs domain
storyforge-hone --dry-run                    # Show what would change
storyforge-hone --coaching LEVEL             # Override coaching level
-h, --help                                   # Usage
```

## Domain Ordering

When running all domains: `registries` → `gaps` → `structural` → `briefs`

Rationale: registries must normalize IDs before other domains reference them. Gaps fill empty fields so structural and briefs have data to work with. Structural fixes address evaluation findings. Briefs concretization runs last because it rewrites field values that the other domains may have just populated or fixed.

## Integration Points

### storyforge-extract
Currently calls `storyforge-reconcile --phase N` after each extraction phase. Changes to: `storyforge-hone --domain registries --phase N`.

### storyforge-revise
Currently handles upstream CSV fixes inline. Changes to: route `fix_location: {brief, intent, structural}` findings to `storyforge-hone --domain structural` before running prose craft passes. The revise skill/script calls hone as a pre-step.

### storyforge-elaborate
Currently has `--gap-fill` mode. Changes to: `storyforge-hone --domain gaps`. The elaborate script's gap-fill code moves to hone.

### storyforge-reconcile
Becomes a wrapper: `exec storyforge-hone --domain registries "$@"`. Backwards-compatible.

### Scoring → Hone trigger
When `storyforge-score` or `storyforge-validate --structural` produces findings with `fix_location: 'brief'`, the recommendations output should suggest `storyforge-hone --domain briefs --scenes <flagged-scene-ids>`.

## Python Module: storyforge/hone.py

New module absorbing `reconcile.py` functions and adding new domain logic.

### From reconcile.py (moved, not duplicated):
- `_collect_*` functions (column value collectors)
- `build_registry_prompt()` (registry prompt builder)
- `parse_registry_response()` (response parser)
- `write_registry()` (registry writer)
- `apply_updates()` (update applicator)
- `apply_registry_normalization()` (field normalizer)
- `_REGISTRY_COLUMNS`, `_DOMAIN_TO_REGISTRY`, `_DOMAIN_TARGETS` (mappings)

### New functions:
- `detect_abstract_fields(ref_dir, scene_ids=None, threshold=3.5)` — Scan brief fields for abstract language. Returns list of `{scene_id, field, value, abstract_indicators}`.
- `build_concretize_prompt(scene_id, project_dir, plugin_dir, fields)` — Build prompt to rewrite abstract fields as concrete beats. Includes voice guide, character bible, current values.
- `parse_concretize_response(response, scene_id, fields)` — Parse Claude's rewrites back into field values.
- `build_structural_fix_prompt(scene_id, finding, project_dir)` — Build prompt for a specific structural fix from evaluation findings.
- `detect_gaps(ref_dir, scene_ids=None)` — Scan for empty required fields by status.
- `build_gap_fill_prompt(scene_id, project_dir, plugin_dir, missing_fields)` — Build prompt to fill missing fields from context.

### Abstract language detection (keyword-based):

```python
ABSTRACT_INDICATORS = {
    'realizes', 'recognizes', 'connects', 'crystallizes', 'deepens',
    'builds', 'grows', 'shifts', 'transforms', 'emerges', 'settles',
    'dawns', 'unfolds', 'intensifies', 'resolves',
    'the realization', 'the parallel', 'the tension', 'the connection',
    'the weight of', 'the cost of', 'the truth of',
    'beginning to', 'starting to', 'learning to',
}

CONCRETE_INDICATORS = {
    'hands', 'eyes', 'door', 'walks', 'picks up', 'sets down',
    'turns', 'stops', 'reaches', 'holds', 'drops', 'pulls',
    'sits', 'stands', 'crosses', 'opens', 'closes',
}
```

A field is flagged as abstract when it has 2+ abstract indicators and fewer concrete indicators than abstract ones. This is a heuristic, not a classifier — false positives are acceptable because the concretization prompt will skip fields that are already concrete.

## Script: storyforge-hone

Follows standard script patterns (set -eo pipefail, source common.sh, detect_project_root, etc.).

### Flow:
1. Parse args
2. `detect_project_root`
3. Read project info
4. Create branch: `storyforge/hone-*`
5. For each domain in order:
   a. Detect which scenes need work (scoring threshold, empty fields, abstract language, structural findings)
   b. Skip domain if no scenes flagged (log: "Domain X: nothing to do")
   c. Build prompts (batch API for full coaching, skip for strict)
   d. Call Anthropic API (Opus for briefs/structural/gaps, same as reconcile for registries)
   e. Parse responses
   f. Apply changes to CSV files
   g. Commit: `Hone: {domain} — {N} scenes updated`
6. Run validation after all domains
7. Push, update PR

### Coaching level behavior:
- **full:** Rewrites applied directly to CSVs. Committed and pushed.
- **coach:** Proposed rewrites saved to `working/hone/`. Author reviews. Changes not applied to CSVs until author runs `storyforge-hone --apply`.
- **strict:** Analysis saved to `working/hone/`. No rewrites proposed. Information only.

## Migration

- `storyforge-reconcile` becomes a thin wrapper calling `storyforge-hone --domain registries "$@"`
- `storyforge-elaborate --gap-fill` becomes a thin wrapper calling `storyforge-hone --domain gaps "$@"`
- Existing `reconcile.py` functions move to `hone.py`. `reconcile.py` re-exports them for backwards compatibility.
- The revise skill documentation updates to route upstream CSV fixes through `storyforge-hone --domain structural`
- CLAUDE.md script table updated

## Tests

New test suite: `tests/test-hone.sh`

Tests from `test-reconcile.sh` move here (registry domain tests). New tests for:
- Abstract language detection (keyword matching)
- Concretize prompt building
- Concretize response parsing
- Gap detection
- Domain ordering
- Coaching level routing (full writes, coach saves proposals, strict saves analysis)
- Backwards compatibility of storyforge-reconcile wrapper
- Scene filter interaction with domain logic

## Cost Estimate

Per domain on a 60-scene novel:
- **registries:** ~$1-2 (5 Opus calls, same as current reconcile)
- **briefs:** ~$3-5 (1 Opus call per flagged scene, typically 10-20 scenes below threshold)
- **structural:** ~$1-3 (1 Opus call per finding, typically 5-15 findings)
- **gaps:** ~$1-2 (1 Opus call per scene with gaps, typically 5-10 scenes)
- **Full run (all domains):** ~$6-12

## Version

Bump to 0.64.0 (minor — new feature, absorbs existing functionality).
