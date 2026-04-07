# Hone Skill -- Files Read and Actions Proposed

## Files Read

### Project Config
- `storyforge.yaml` -- project title, genre, phase (drafting), coaching level (default/full), parts

### Scene CSVs (the three-file model)
- `reference/scenes.csv` -- 6 scenes across 2 parts, statuses range from spine to briefed
- `reference/scene-briefs.csv` -- only 4 rows (act1-sc01, act1-sc02, new-x1, act2-sc03); act2-sc01 and act2-sc02 are entirely missing
- `reference/scene-intent.csv` -- all 6 scenes present with data

### Registry CSVs
- `reference/characters.csv` -- 4 characters
- `reference/locations.csv` -- 4 locations
- `reference/values.csv` -- 4 values
- `reference/knowledge.csv` -- 5 knowledge items
- `reference/mice-threads.csv` -- 3 MICE threads
- `reference/motif-taxonomy.csv` -- 5 motifs with tiers
- `reference/physical-states.csv` -- 4 physical states

### Scoring/Proposals (checked, not found)
- `working/scores/latest/scene-scores.csv` -- does not exist
- `working/scores/structural-proposals.csv` -- does not exist

## Domain Assessment Summary

### Gaps Domain -- CRITICAL
- **3 of 6 scenes lack usable briefs**
  - new-x1: row exists but nearly all fields empty
  - act2-sc01: no row in scene-briefs.csv at all
  - act2-sc02: no row in scene-briefs.csv at all
- These scenes cannot be drafted without briefs

### Briefs Domain -- MODERATE
Issues found in the 3 populated briefs (act1-sc01, act1-sc02, act2-sc03):
- **Over-specified beats**: act1-sc01 has 5 key_actions / 2500 words, act2-sc03 has 5 / 2200 words
- **Prescriptive dialogue**: All 3 scenes contain exact quoted dialogue in key_dialogue field
- **Emotional arc granularity**: All 3 scenes have 4-beat arcs (should be 2)
- **Procedural goals**: act1-sc01 goal is task-framed, not dramatic-question-framed

### Registries Domain -- MINOR
- Registries exist and are mostly clean
- One normalization issue: scenes.csv uses "The Uncharted Reaches" but locations.csv canonical name is "Uncharted Reaches"

### Structural Domain -- NO DATA
- No scoring data exists (no scene-scores.csv)
- No structural proposals exist
- Cannot assess structural domain without prior evaluation/scoring

## Actions Proposed

1. **Fill gaps** (priority 1) -- Run `storyforge-hone --domain gaps` or `storyforge-elaborate --gap-fill` to populate missing brief rows for new-x1, act2-sc01, act2-sc02
2. **Concretize briefs** (priority 2) -- Run `storyforge-hone --domain briefs` to fix abstract language, trim key_actions, replace exact dialogue with direction, compress emotional arcs
3. **Registry normalization** (priority 3) -- Run `storyforge-hone --domain registries` to fix the location name inconsistency

## Skill Flow Followed

1. Read project state (Step 1) -- read storyforge.yaml, all three scene CSVs, all registries, checked for scores
2. Determined coaching level (Step 2) -- no coaching level set in YAML, defaulted to `full`
3. Determined domain (Step 3) -- user asked "what's the data quality looking like" without specifying a domain, so followed the "invoked without direction" path: assessed all domains and presented findings
4. Assessed domain needs (Step 4) -- ran through gaps, briefs quality (abstract language, over-specification, prescriptive dialogue, emotional arc granularity, procedural goals), registries, and structural
5. Offered execution options (Step 5) -- presented Option A (run here) and Option B (run yourself) with specific commands
6. Did NOT execute anything or modify files -- awaiting author's choice
