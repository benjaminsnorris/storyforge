Here is how the data looks after extraction for **The Cartographer's Silence**.

## Overall Shape

6 scenes across 2 parts, 4 characters, 4 locations, 3 MICE threads, 4 values, 5 knowledge items, 5 motifs, 4 physical states. Chapter map covers 3 of the 6 scenes. You have prose for 4 of the 6 scenes (566 words total -- placeholder-scale, not full drafts).

## Data Quality Issues

### Critical: Missing Briefs

Two scenes have no brief data at all:

- **act2-sc01** (Into the Blank) -- has intent data but no row in scene-briefs.csv
- **act2-sc02** (First Collapse) -- has intent data but no row in scene-briefs.csv

These scenes cannot be drafted or validated without briefs.

### Critical: Empty Brief (new-x1)

**new-x1** (The Archivist's Warning) has a row in scene-briefs.csv, but every field is empty except `physical_state_in` and `physical_state_out` (both set to `archive-key-dorren`). Goal, conflict, outcome, crisis, decision, knowledge flow, key actions, dialogue, emotions, motifs -- all blank. This scene is essentially unbriefed.

### Structural: Inconsistent Statuses

Scene statuses are a mix of pipeline stages rather than a consistent post-extraction state:

| Scene | Status |
|-------|--------|
| act1-sc01 | briefed |
| act1-sc02 | briefed |
| new-x1 | mapped |
| act2-sc01 | architecture |
| act2-sc02 | spine |
| act2-sc03 | briefed |

The three briefed scenes do have brief data. But `act2-sc01` at "architecture" and `act2-sc02` at "spine" correctly signal they have not reached the brief stage. `new-x1` at "mapped" is misleading since it has a brief row (albeit empty).

### Registry: Unregistered Location

- **act2-sc03** uses location `Council Chamber` in scenes.csv, but there is no matching entry in locations.csv. The registry has `Pressure Cartography Office`, `Dorren's study`, `Deep Archive`, and `Uncharted Reaches` -- no Council Chamber.
- **act2-sc02** uses location `Eastern Ridge`, also absent from locations.csv.

### Registry: Unregistered Characters

- **act2-sc03** references `Council Members` in scene-intent.csv (both `characters` and `on_stage`), but there is no `council-members` entry in characters.csv. These may be unnamed background characters, but they should either be registered or the reference clarified.

### Knowledge Flow: Gaps

- **new-x1** has empty `knowledge_in` and `knowledge_out` in scene-briefs.csv, but scene-intent.csv says Kael warns about archive inconsistencies. The extraction missed the knowledge flow entirely for this scene.
- **act2-sc01** and **act2-sc02** have no brief rows, so their knowledge flow is untracked. From the intent data, act2-sc01 should feed `subsidence-not-natural` into act2-sc02 and beyond, but this chain is not wired.

### Physical States: Temporal Inconsistencies

- **act1-sc02** lists `physical_state_out` as `archive-key-dorren;exhaustion-tessa` -- but `exhaustion-tessa` is described as "physically exhausted from 4-hour eastern trek" with `acquired: act1-sc02`. Tessa's exhaustion from an eastern trek does not match act1-sc02 (which takes place in Dorren's private study with only Dorren on stage).
- **scar-left-hand-kael** has `acquired: act1-sc01`, but Kael Maren is not listed in the `on_stage` column for act1-sc01 (only Dorren and Tessa are).

### MICE Threads: Incomplete Arcs

- **act2-sc02** closes `milieu:uncharted-reaches` (with `-`), but it was only opened one scene earlier in act2-sc01. A single-scene milieu thread may be intentional, but it is worth verifying.
- The two inquiry threads opened in act1 (`map-anomaly` and `archive-erasure`) are both closed in act2-sc03. No threads carry beyond the six scenes. If the novel continues, thread closure may be premature.

### Chapter Map: Incomplete

The chapter map only covers 3 of 6 scenes:
- Chapter 1: act1-sc01, act1-sc02
- Chapter 2: act2-sc01
- Missing: new-x1, act2-sc02, act2-sc03

### Motifs: Reference Inconsistencies

Scene-intent.csv does not have a motifs column, so motif assignment lives only in the briefs. The motif taxonomy defines 5 motifs with tiers, but the brief data references motif names using slightly different formats (e.g., `maps/cartography` in briefs vs. the `maps` id with `maps/cartography` as an alias in the taxonomy). This works with alias resolution but should be normalized.

## Summary

The extraction captured solid structural data for the Act 1 scenes and act2-sc03. The main gaps are:

1. **Two scenes completely missing briefs** (act2-sc01, act2-sc02)
2. **One scene with an empty brief** (new-x1)
3. **Two unregistered locations** (Council Chamber, Eastern Ridge)
4. **Unregistered characters** (Council Members)
5. **Physical state inconsistencies** (wrong scenes of acquisition, character not on stage)
6. **Incomplete chapter map** (3 of 6 scenes assigned)

The registries (characters, locations, values, MICE threads, knowledge, motifs, physical states) are in decent shape for the scenes that were fully extracted. The priority should be filling in the missing briefs for act2-sc01 and act2-sc02, then running `storyforge-hone` to clean up the registry gaps and normalize references.

Would you like me to run `storyforge-hone` to address the registry and structural issues, or would you prefer to fill in the missing briefs first through elaboration?
