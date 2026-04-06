# Post-Extraction Assessment: Files Read and Proposed Actions

## Files Read

### Project Configuration
- `storyforge.yaml` -- project metadata, phase (drafting), parts, production settings

### Core CSV Files (Three-File Model)
- `reference/scenes.csv` -- 6 scenes, structural identity
- `reference/scene-intent.csv` -- 6 rows, narrative dynamics
- `reference/scene-briefs.csv` -- 4 rows (act2-sc01 and act2-sc02 missing), drafting contracts

### Registry CSVs
- `reference/characters.csv` -- 4 characters
- `reference/locations.csv` -- 4 locations
- `reference/mice-threads.csv` -- 3 threads
- `reference/values.csv` -- 4 values
- `reference/knowledge.csv` -- 5 knowledge items
- `reference/motif-taxonomy.csv` -- 5 motifs with tiers
- `reference/physical-states.csv` -- 4 physical states

### Other Reference Files
- `reference/chapter-map.csv` -- 2 chapters covering 3 scenes

### Scene Files
- `scenes/act1-sc01.md` -- 251 words
- `scenes/act1-sc02.md` -- 104 words
- `scenes/act2-sc01.md` -- 103 words
- `scenes/new-x1.md` -- 108 words

### Working Directory
- Listed contents: coaching, evaluations, logs, pipeline.csv, plans, reviews, scores

## Proposed Actions

### Immediate (Run storyforge-hone)
1. **Registry domain** -- register `Council Chamber` and `Eastern Ridge` in locations.csv; register or clarify `Council Members` in characters.csv
2. **Structural domain** -- fix physical state acquisition scenes (exhaustion-tessa acquired in act1-sc02 does not match scene context; scar-left-hand-kael acquired in act1-sc01 but Kael not on stage)
3. **Gaps domain** -- detect and report the missing briefs for act2-sc01 and act2-sc02; flag the empty brief for new-x1

### Follow-Up (Elaborate or Manual)
4. **Fill briefs** for act2-sc01 and act2-sc02 via `storyforge-elaborate --stage briefs --scenes act2-sc01,act2-sc02`
5. **Flesh out new-x1 brief** -- either re-extract from the scene prose or elaborate from intent data
6. **Complete chapter map** -- assign new-x1, act2-sc02, act2-sc03 to chapters
7. **Normalize motif references** in briefs to use canonical registry IDs
8. **Verify MICE thread arc lengths** -- confirm single-scene milieu thread (uncharted-reaches) is intentional
9. **Validate knowledge flow chain** through act2 scenes once briefs exist
