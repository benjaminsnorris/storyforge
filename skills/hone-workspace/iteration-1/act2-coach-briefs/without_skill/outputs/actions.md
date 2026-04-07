# Files Read

| File | Purpose |
|------|---------|
| `tests/fixtures/test-project/storyforge.yaml` | Project config -- title, parts, phase, coaching level |
| `tests/fixtures/test-project/reference/scenes.csv` | Scene index -- identified act 2 scenes (part=2): act2-sc01, act2-sc02, act2-sc03 |
| `tests/fixtures/test-project/reference/scene-briefs.csv` | Brief data -- found act2-sc01 and act2-sc02 missing, act2-sc03 present |
| `tests/fixtures/test-project/reference/scene-intent.csv` | Intent data -- cross-referenced on_stage, emotional_arc, mice_threads for act 2 scenes |
| `tests/fixtures/test-project/reference/characters.csv` | Character registry -- validated character references |
| `tests/fixtures/test-project/reference/locations.csv` | Location registry -- validated location references |
| `tests/fixtures/test-project/reference/knowledge.csv` | Knowledge registry -- validated knowledge_in/knowledge_out chains |
| `tests/fixtures/test-project/reference/mice-threads.csv` | MICE thread registry -- validated thread references |
| `tests/fixtures/test-project/reference/values.csv` | Values registry -- validated value_at_stake references |
| `tests/fixtures/test-project/reference/motif-taxonomy.csv` | Motif registry -- found alias vs canonical ID mismatch in act2-sc03 motifs |
| `tests/fixtures/test-project/reference/physical-states.csv` | Physical state registry -- found continuity issue with exhaustion-tessa in act2-sc03 |
| `tests/fixtures/test-project/reference/chapter-map.csv` | Chapter mapping -- context for act structure |
| `tests/fixtures/test-project/scenes/act2-sc01.md` | Draft prose for act2-sc01 -- noted it exists despite no brief |
| `scripts/lib/python/storyforge/hone.py` | Hone implementation -- understood abstractness detection logic and concretization prompt builder |

# Actions Proposed (coaching mode -- no changes made)

## Critical

1. **Create briefs for act2-sc01 and act2-sc02.** These scenes have no rows in scene-briefs.csv. The hone briefs domain cannot operate on scenes without brief data. Suggested path: run elaboration pipeline or extract from existing prose (act2-sc01 has a draft).

## Moderate

2. **Concretize act2-sc03 crisis and decision fields.** Both fields use abstract/thematic language rather than physical beats. The hone abstractness detector would flag these (abstract indicators present, concrete indicators absent). Recommended rewriting as physical actions the POV character performs.

3. **Fix physical_state_in continuity error in act2-sc03.** `exhaustion-tessa` is listed as a physical state entering the scene, but Tessa Merrin is not in the `on_stage` column for this scene. Either add Tessa to on_stage or remove the physical state reference.

## Minor

4. **Normalize motif aliases in act2-sc03.** The `motifs` field uses `governance-as-weight` and `blindness/seeing` (aliases) instead of canonical IDs `governance` and `blindness`. The registries domain of hone would fix this automatically.

# What Hone Would Do (if run)

Running `storyforge-hone --domain briefs --act 2 --coaching coach` would:
- Scan act2-sc01, act2-sc02, act2-sc03 for abstract language in key_actions, crisis, and decision fields
- Skip act2-sc01 and act2-sc02 (no brief data to analyze)
- Flag act2-sc03's crisis and decision fields as abstract
- In coach mode: present the findings and ask the author how to rewrite, rather than invoking Claude to rewrite automatically
- Save coaching notes to `working/coaching/` directory
