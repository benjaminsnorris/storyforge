# Post-Extraction Assessment -- Files Read and Actions Proposed

## Files Read

### Project Configuration
- `/Users/cadencedev/Developer/storyforge/tests/fixtures/test-project/storyforge.yaml` -- project metadata, phase, parts

### Core Scene CSVs
- `/Users/cadencedev/Developer/storyforge/tests/fixtures/test-project/reference/scenes.csv` -- 6 scenes, structural data
- `/Users/cadencedev/Developer/storyforge/tests/fixtures/test-project/reference/scene-intent.csv` -- 6 rows, narrative dynamics
- `/Users/cadencedev/Developer/storyforge/tests/fixtures/test-project/reference/scene-briefs.csv` -- 4 rows (2 scenes missing, 1 nearly empty)

### Registry CSVs
- `/Users/cadencedev/Developer/storyforge/tests/fixtures/test-project/reference/characters.csv` -- 4 characters
- `/Users/cadencedev/Developer/storyforge/tests/fixtures/test-project/reference/locations.csv` -- 4 locations
- `/Users/cadencedev/Developer/storyforge/tests/fixtures/test-project/reference/mice-threads.csv` -- 3 threads
- `/Users/cadencedev/Developer/storyforge/tests/fixtures/test-project/reference/values.csv` -- 4 values
- `/Users/cadencedev/Developer/storyforge/tests/fixtures/test-project/reference/knowledge.csv` -- 5 knowledge items
- `/Users/cadencedev/Developer/storyforge/tests/fixtures/test-project/reference/motif-taxonomy.csv` -- 5 motifs
- `/Users/cadencedev/Developer/storyforge/tests/fixtures/test-project/reference/physical-states.csv` -- 4 physical states

### Other Reference Files
- `/Users/cadencedev/Developer/storyforge/tests/fixtures/test-project/reference/chapter-map.csv` -- 2 chapters mapped

### Scene Files (existence check only)
- `scenes/` directory -- 4 scene files present (act1-sc01.md, act1-sc02.md, act2-sc01.md, new-x1.md)

### Plugin Reference
- `/Users/cadencedev/Developer/storyforge/scripts/lib/python/storyforge/schema.py` -- enum definitions for validation context

## Issues Found

### Critical (blocks drafting)
1. **Missing briefs:** act2-sc01 and act2-sc02 have no rows in scene-briefs.csv
2. **Empty brief:** new-x1 has a row but nearly all fields are blank
3. **Missing location registry entries:** "Eastern Ridge" and "Council Chamber" referenced in scenes.csv but absent from locations.csv

### Moderate (data integrity)
4. **Physical state acquisition errors:** exhaustion-tessa acquired in act1-sc02 (Tessa not on_stage there); scar-left-hand-kael acquired in act1-sc01 (Kael not on_stage there)
5. **Unresolved character reference:** "Council Members" in act2-sc03 scene-intent has no characters.csv entry
6. **Missing MICE thread:** act1-sc02 has empty mice_threads field

### Minor (cleanup)
7. **Mixed elaboration statuses:** scenes range from spine to briefed -- expected post-extraction but worth normalizing
8. **Incomplete chapter map:** only 3 of 6 scenes assigned to chapters
9. **Pell has no aliases** in characters.csv (empty field)
10. **Scene files:** act2-sc02 and act2-sc03 have no .md files in scenes/ (2 of 6 missing)

## Actions Proposed

1. **Run `storyforge-hone --domain registries`** -- normalize references, add missing location entries (Eastern Ridge, Council Chamber), resolve "Council Members"
2. **Run `storyforge-elaborate --stage briefs --scenes act2-sc01,act2-sc02,new-x1`** -- develop briefs for the 3 under-specified scenes
3. **Fix physical-states.csv** -- correct acquired scene for exhaustion-tessa (should be act2-sc01) and scar-left-hand-kael (should be pre-story or new-x1)
4. **Add MICE thread to act1-sc02** -- likely +inquiry:map-anomaly or continuation of the thread opened in act1-sc01
5. **Run `storyforge-hone --domain gaps`** -- detect structural gaps across all CSVs after fixes
