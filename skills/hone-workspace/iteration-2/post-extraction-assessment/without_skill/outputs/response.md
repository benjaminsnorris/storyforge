Here's how your data looks after extraction for **The Cartographer's Silence** (6 scenes across 2 parts).

## Overall Assessment

The extraction captured a solid structural skeleton, but there are meaningful gaps -- particularly in scene-briefs.csv where two scenes are missing briefs entirely, and in the registry CSVs where some references in the scene data don't resolve to registry entries. This is typical post-extraction; the data needs a honing pass before you draft.

## scenes.csv -- Structural Data

**Good shape.** All 6 scenes have id, seq, title, part, pov, location, timeline_day, time_of_day, duration, type, and status populated. No missing structural fields.

Issues found:

- **Status inconsistency:** Scenes are at mixed elaboration stages -- `briefed` (3), `mapped` (1), `architecture` (1), `spine` (1). This is expected if extraction hit different scenes at different depths, but you'll want to promote act2-sc01 and act2-sc02 forward before drafting.
- **Location registry mismatches:** Two locations in scenes.csv don't match registry IDs:
  - `act2-sc02` references "Eastern Ridge" -- no entry in locations.csv (closest is "Uncharted Reaches").
  - `act2-sc03` references "Council Chamber" -- no entry in locations.csv at all.

## scene-intent.csv -- Narrative Dynamics

**Mostly complete.** All 6 scenes have rows. The function, action_sequel, emotional_arc, value_at_stake, value_shift, turning_point, characters, and on_stage columns are populated for all scenes.

Issues found:

- **Missing MICE threads:** act1-sc02 has an empty `mice_threads` field. Given it's the scene where Dorren discovers the vanished village, it should probably open or advance an inquiry thread.
- **Character reference "Council Members"** in act2-sc03 doesn't resolve to any character in characters.csv. Either add a registry entry or normalize to individual names.
- **Pell appears in on_stage** for act2-sc01 but has no aliases in characters.csv (empty aliases field). Minor, but worth noting.

## scene-briefs.csv -- Drafting Contracts

**This is the weakest area.** Only 4 of 6 scenes have briefs. Two scenes are missing:

- **act2-sc01** ("Into the Blank") -- no row in scene-briefs.csv at all. Status is `architecture`, so it hasn't been briefed yet.
- **act2-sc02** ("First Collapse") -- no row in scene-briefs.csv at all. Status is `spine`, so it's the least-developed scene.

For the 4 scenes that have briefs:

- **new-x1** ("The Archivist's Warning") has a row but it's almost entirely empty -- only `physical_state_in` and `physical_state_out` are populated. The goal, conflict, outcome, crisis, decision, knowledge_in/out, key_actions, key_dialogue, emotions, and motifs fields are all blank. This scene needs full brief development.
- **act1-sc01** has a fully populated brief but note that `knowledge_in` is empty (first scene, so this is correct).
- **act1-sc02** and **act2-sc03** have complete briefs.

## Registry CSVs -- Reference Data

**characters.csv (4 entries):** Clean. All characters referenced in scene data exist here. One gap: "Council Members" in scene-intent appears as a group name with no registry entry.

**locations.csv (4 entries):** Missing 2 locations referenced in scenes.csv:
- Eastern Ridge (act2-sc02)
- Council Chamber (act2-sc03)

**mice-threads.csv (3 entries):** All MICE thread references in scene-intent resolve correctly. The thread types (inquiry, milieu) are valid.

**values.csv (4 entries):** All value_at_stake references resolve. Clean.

**knowledge.csv (5 entries):** All knowledge_in/knowledge_out references in scene-briefs resolve correctly.

**motif-taxonomy.csv (5 entries):** The motif references in scene-briefs use compound forms (e.g., "maps/cartography", "depth/descent", "blindness/seeing") that match the aliases in the taxonomy. These should resolve via alias lookup. Clean.

**physical-states.csv (4 entries):** Two issues:
- `exhaustion-tessa` is acquired in `act1-sc02` but Tessa doesn't appear in that scene (she's in act1-sc01 and act2-sc01+). The acquisition scene looks wrong -- act2-sc01 (the 4-hour trek) would make more sense.
- `scar-left-hand-kael` is acquired in `act1-sc01` but Kael doesn't appear in that scene's on_stage list (he's first on_stage in new-x1). The acquisition should probably be `pre-story` or `new-x1`.

## chapter-map.csv -- Assembly

**Incomplete.** Only maps 3 of 6 scenes across 2 chapters. Missing scenes: new-x1, act2-sc02, act2-sc03. This is fine for now -- chapter mapping typically happens closer to production -- but flagging it.

## Recommended Next Steps

1. **Run `storyforge-hone --domain registries`** to normalize character/location/motif references against the registry CSVs and add the missing location entries (Eastern Ridge, Council Chamber).

2. **Develop briefs for the 3 under-specified scenes** (act2-sc01, act2-sc02, new-x1). You can do this with the elaborate skill targeting those scenes, or run `storyforge-elaborate --stage briefs --scenes act2-sc01,act2-sc02,new-x1`.

3. **Fix the physical-states acquisition scenes** -- exhaustion-tessa and scar-left-hand-kael point to scenes where those characters aren't present.

4. **Add the missing MICE thread** for act1-sc02.

5. **Decide on "Council Members"** -- add as a group entry in characters.csv, or replace with individual character names.

After those fixes, you'll have clean data for drafting. The structural bones are solid -- the extraction captured the narrative dynamics well, it's mainly the briefs and registry cross-references that need attention.
