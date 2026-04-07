# Hone Skill -- Files Read and Actions Proposed

## Files Read

### Project Configuration
- `storyforge.yaml` -- project metadata, phase (drafting), coaching level (default/full), parts structure

### Scene CSV Files (core three-file model)
- `reference/scenes.csv` -- 6 scenes, statuses ranging from spine to briefed, all word_count 0
- `reference/scene-briefs.csv` -- only 4 rows (header + act1-sc01, act1-sc02, new-x1, act2-sc03); new-x1 is nearly empty; act2-sc01 and act2-sc02 missing entirely
- `reference/scene-intent.csv` -- 6 rows, mostly populated; act1-sc02 missing mice_threads

### Registry CSVs
- `reference/characters.csv` -- 4 characters
- `reference/locations.csv` -- 4 locations (missing Eastern Ridge)
- `reference/knowledge.csv` -- 5 knowledge beats
- `reference/values.csv` -- 4 values
- `reference/mice-threads.csv` -- 3 MICE threads
- `reference/physical-states.csv` -- 4 physical states (exhaustion-tessa has inconsistent acquired scene)
- `reference/motif-taxonomy.csv` -- 5 motifs (acceptable-variance alias questionable under water)

### Other
- `reference/chapter-map.csv` -- 2 chapters mapped, 3 scenes unassigned
- `working/pipeline.csv` -- 3 evaluation cycles, all in evaluating status
- `working/scores/` -- empty directory, no scoring data

## Skill Mode Determination

The user asked "What's the data quality looking like?" without specifying a domain. Per SKILL.md Step 2 "if invoked without direction, assess the project state":

1. Checked for scoring data -- none exists (empty scores directory)
2. Checked for structural proposals -- none exist
3. Checked for empty required fields -- significant gaps found (3 scenes missing briefs, 1 scene with empty brief row)
4. Checked registry state -- registries exist but have some inconsistencies

Conclusion: assessment mode. Present findings across all four domains and recommend priorities.

## Actions Proposed

### Priority 1: Fill Gaps (critical)
- Fill briefs for new-x1 (empty row exists), act2-sc01, act2-sc02 (no rows at all)
- Fill mice_threads for act1-sc02 in scene-intent.csv
- Recommended command: `storyforge-hone --domain gaps` or `storyforge-elaborate --stages briefs --scenes new-x1,act2-sc01,act2-sc02`

### Priority 2: Registry Normalization (moderate)
- Add Eastern Ridge to locations.csv (referenced in scenes.csv but missing from registry)
- Verify exhaustion-tessa acquired scene (act1-sc02 lists only Dorren on_stage)
- Review acceptable-variance alias under water motif
- Recommended command: `storyforge-hone --domain registries`

### Priority 3: Chapter Map Completion (minor)
- Assign new-x1, act2-sc02, act2-sc03 to chapters
- This is an elaborate task, not hone

### Priority 4: Scoring Baseline (deferred)
- Run scoring after gaps are filled to establish baseline
- Recommended command: `storyforge-score`

## Actions NOT Taken
- No scripts were executed (simulation mode)
- No files were modified in the test project (read-only)
- No commits were made
- No brief concretization was attempted (the existing briefs are already concrete)
