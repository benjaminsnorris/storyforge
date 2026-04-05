# Structural Scoring Engine — Story Quality from CSV Data

## Problem

The plugin can tell you whether your scene data is *valid* (threads nest, knowledge chains flow, timeline is consistent) and whether your prose is *well-crafted* (25 craft principles scored by AI). But it cannot tell you whether your *story is good* — whether the architecture will produce a compelling reading experience.

Authors need to know: Do I have the right bones? Where is the structure weak? What specific changes would improve it? And after making changes: Did it get better?

## Design Principles

1. **CSV-only** — reads scene data, not prose. Works pre-draft (Path 1) and post-extraction (Path 2). No API calls. Instant, free, deterministic.
2. **Quantified** — every dimension produces a 0-1 score with benchmarks. "Your arc completeness is 0.6 — target 0.8+." Trackable across revision cycles.
3. **Diagnostic** — each score comes with specific findings: which scenes, which fields, what's wrong.
4. **Prescriptive** — each finding maps to a specific CSV change (adapted by coaching level).
5. **Genre-aware** — benchmarks adjust for genre. A thriller's pacing profile differs from literary fiction.

## Empirical Grounding

The scoring dimensions below draw on both craft theory and empirical research:

- **Reagan et al. (2016)** — Sentiment analysis of 1,327 novels identified 6 archetypal emotional arc shapes. Compound arcs with more reversals correlate with higher popularity (measured by Project Gutenberg downloads). Source: "The emotional arcs of stories are dominated by six basic shapes," *EPJ Data Science*.
- **Archer & Jockers (2016)** — Machine learning on ~5,000 novels found bestsellers dedicate ~30% of text to 1-2 dominant topics and show near-sinusoidal emotional oscillation (regular rhythm of highs/lows). The regularity of the beat matters more than the specific shape. Source: *The Bestseller Code*, St. Martin's Press.
- **Coyne (2015)** — 25+ years of editorial analysis codified as: 25/50/25 act proportions, 50-60 scenes at ~2,000 words, five commandments per scene. Source: *The Story Grid*.
- **Brody/Snyder (2018)** — Beat sheet percentages (catalyst at 10%, break into two at 20%, midpoint at 50%, all is lost at 75%) converge with Coyne's proportions. Source: *Save the Cat! Writes a Novel*.
- **McKee (1997)** — Value shifts as the atomic unit of story change. A scene that doesn't shift a value is a nonevent. Source: *Story*.
- **Kowal** — MICE thread nesting, dormancy thresholds (8-10 scenes), thread type balance. Source: *Writing Excuses* workshops.

The 25/50/25 act proportion appears independently in Aristotle, Snyder, Brody, and Coyne — convergent evidence across 2,400 years of story analysis.

## Scoring Dimensions

### 1. Arc Completeness (per character)

**What it measures:** Does each POV character have a complete dramatic arc?

**Empirical basis:** Reagan's 6 archetypal shapes (rags-to-riches, tragedy, man-in-a-hole, Icarus, Cinderella, Oedipus). Compound arcs outperform simple ones. McKee: every scene must shift a value or it's a nonevent.

**How it's computed from CSVs:**

For each POV character, collect their scenes in order. Check:
- **Value variety**: How many distinct value_at_stake values appear across their scenes? A character who faces only "justice" for 30 scenes has a flat arc. Target: 3-6 core values per major character.
- **Arc shape classification**: Map the character's value_shift sequence (+/-, -/+, etc.) to one of Reagan's 6 archetypes. Score higher for compound shapes (Cinderella = rise-fall-rise, Oedipus = fall-rise-fall) than simple ones (pure rise or pure fall). Compound arcs with 2+ reversals are empirically more popular.
- **Reversal count**: How many times does the value_shift direction change sign across the character's scenes? More reversals = more engaging (Reagan). But too many with no progression = oscillation without shape.
- **Transformation signal**: Does the character's emotional_arc description change between their first and last scene? A character who starts "controlled competence" and ends "quiet authority earned through loss" has transformed. A character who starts and ends in the same emotional register hasn't.
- **Crisis escalation**: Do the crisis descriptions in their briefs escalate in stakes? Early crises should be personal/local, late crises should be existential/thematic.

**Score:** 0-1 composite. Average across all POV characters, weighted by scene count.

**Diagnosis examples:**
- "Emmett's arc uses 'justice' as value_at_stake in 22 of 30 scenes — thematic monotony"
- "Cora's arc is simple 'man-in-a-hole' (fall then rise) — consider adding a second reversal for compound structure"
- "Hank's emotional_arc starts 'guarded composure' and ends 'guarded composure' — no transformation"

### 2. Thematic Concentration

**What it measures:** Does the novel explore a focused set of themes, or scatter across too many?

**Empirical basis:** Archer & Jockers found bestsellers dedicate ~30% of text to 1-2 dominant topics. Non-bestsellers need 6+ topics to fill 40%. Tighter thematic control correlates with commercial success.

**How it's computed:**

- Count distinct value_at_stake values across all scenes
- Compute the Herfindahl index (sum of squared proportions) — measures concentration
- **Dominance check**: Do the top 2 values account for ≥30% of scenes? (Archer/Jockers bestseller threshold)
- A novel with 3 values each appearing 33% of the time scores high (focused)
- A novel with 42 values each appearing 1-3% of the time scores low (scattered)
- Target: 8-15 distinct values with clear dominance hierarchy

**Score:** 0-1 based on Herfindahl index, calibrated to genre benchmarks.

**Diagnosis examples:**
- "42 distinct values for 66 scenes — too fragmented for reader to track thematic threads"
- "Top 3 values (justice, truth, safety) account for 72% of scenes — strong thematic spine"

### 3. Pacing Shape

**What it measures:** Does the novel's tension follow a compelling shape?

**Empirical basis:** Coyne/Brody/Snyder: 25/50/25 act proportions with midpoint at 50%, climax at 85-90%. Archer & Jockers: bestsellers show near-sinusoidal emotional oscillation — the regularity of the beat matters more than the specific shape. Reagan: compound arcs with more reversals correlate with popularity.

**How it's computed:**

Each scene gets a tension score derived from:
- **value_shift polarity**: -/-- and +/- are high tension (things getting worse or reversals), +/+ and -/+ are lower tension (things improving)
- **action_sequel type**: action scenes are higher tension than sequel scenes
- **outcome type**: no-and is highest tension, yes is lowest

Plot the tension scores across the novel's sequence. Compute:
- **Act structure proportions**: Does ~25% of the novel establish status quo (Act 1), ~50% complicate (Act 2), ~25% resolve (Act 3)? Check using the `part` column weighted by `target_words`.
- **Midpoint presence**: Is there a significant tension peak or reversal near seq 50%?
- **Climax positioning**: Is the highest-tension scene in the final 15% of the sequence?
- **Denouement**: Do the last 5-10% of scenes show tension decrease (resolution)?
- **Beat regularity** (Archer/Jockers): Compute the autocorrelation of the tension sequence at lag 2-4. A regular oscillation pattern (high-low-high-low) scores higher than long runs of same-direction shifts. Bestsellers show near-sinusoidal regularity — the rhythm of emotional beats is more predictive of success than the overall arc shape.
- **Scene count and length**: 50-60 scenes at ~2,000 words is the commercial baseline (Coyne). Significant deviation may indicate structural issues.

**Score:** 0-1 composite of the above sub-metrics.

**Diagnosis examples:**
- "No tension peak near midpoint (seq 33) — the middle third feels flat"
- "Climax is at seq 48 of 66 (73%) — too early, the final quarter has no peak"
- "Beat regularity is 0.3 — long runs of same-polarity shifts (seq 12-19 all negative). Bestsellers average 0.6+ regularity"
- "Act 1 is 38% of word count — front-loaded, target 25%"

### 4. Character Presence

**What it measures:** Are important characters earning their screentime? Do they appear on stage enough to feel real?

**How it's computed:**

For each character in characters.csv:
- Count on_stage appearances vs. character mentions (referenced but not present)
- Measure presence gaps: longest streak of consecutive scenes where the character is absent
- For POV characters: what percentage of the novel do they narrate?
- For antagonists: are they on_stage enough to feel like a real threat?

**Score:** 0-1 based on:
- POV characters should narrate at least 15% of scenes each
- Antagonists should be on_stage in at least 10% of scenes
- No important character should have a gap longer than 15-20% of total scenes
- Supporting characters with high mention count but low on_stage ratio are "told not shown"

**Diagnosis examples:**
- "Keele (antagonist) is on_stage in only 5 of 66 scenes (8%) — feels like a plot device"
- "Thomas disappears from seq 28-45 (26% of novel) — reader forgets him"
- "Dorren is mentioned in 40 scenes but on_stage in only 6 — almost entirely exposition"

### 5. MICE Thread Health

**What it measures:** Beyond nesting validity, are threads narratively effective?

**How it's computed:**

For each thread in the MICE timeline:
- **Lifespan**: How many scenes between open and close? Very short (1-2 scenes) may be trivial. Very long (>50% of novel) may be dormant.
- **Dormancy**: Longest gap between consecutive scenes that reference the thread. Threads dormant for >8-10 scenes lose reader attention.
- **Resolution positioning**: Do major threads close in the final act? Closing too early deflates tension.
- **Open/close ratio**: What fraction of opened threads actually close? Below 0.6 suggests abandonment.
- **Type balance**: A healthy novel has threads from all four MICE types. A novel with only inquiry threads feels like a mystery regardless of genre.

**Score:** 0-1 composite.

**Diagnosis examples:**
- "Thread 'who-killed-rowan' is dormant for scenes 15-38 (23 scenes) — reader has forgotten the question"
- "85 of 180 threads never close (47%) — too many loose ends"
- "90% of threads are inquiry type — story feels interrogative, needs more milieu/character threads"

### 6. Knowledge Chain Integrity

**What it measures:** Does information flow create dramatic irony and drive decisions?

**How it's computed:**

- **Chain coverage**: What fraction of scenes have both knowledge_in and knowledge_out populated?
- **Fact utilization**: How many registered facts actually appear in at least 2 scenes' knowledge chains? Facts that appear once are noise.
- **Dramatic irony potential**: Are there scenes where one POV character knows something another doesn't, and both are on_stage? This creates tension the reader can feel.
- **Decision gating**: Do knowledge_in facts actually connect to the scene's crisis/decision? A scene where the character acts on information they just learned is structurally strong.
- **Backstory dependency**: What fraction of scene 1's knowledge_in is backstory? High backstory dependency means the story requires too much prior context.

**Score:** 0-1 composite.

**Diagnosis examples:**
- "Only 53 of 97 scenes have knowledge_out — 45% of scenes don't teach the reader anything new"
- "Fact 'keele-ordered-rowan-killed' appears in 12 scenes but is never the basis of a crisis — dramatic potential wasted"
- "Scenes 1-5 require 8 backstory facts — too much assumed context"

### 7. Scene Function Variety

**What it measures:** Is each scene earning its place? Are scenes doing different things?

**How it's computed:**

- **Function uniqueness**: How many scenes have genuinely distinct functions? If 10 scenes all say "protagonist investigates clue," they're structurally redundant.
- **Function type distribution**: action vs. sequel, revelation vs. action turning points. Healthy variety prevents monotony.
- **Scene type spread**: distribution across action/character/confrontation/dialogue/introspection/plot/revelation/transition/world types.
- **Outcome variety**: distribution across yes/yes-but/no/no-and. Heavy skew toward one outcome (e.g., 67% yes-but) reduces unpredictability.

**Score:** 0-1 based on entropy/variety metrics.

**Diagnosis examples:**
- "8 consecutive action scenes (seq 12-19) — reader fatigue from relentless pace"
- "44 of 66 outcomes are yes-but (67%) — pattern becomes predictable"
- "15 scenes have function containing 'discovers' — investigation pattern is repetitive"

### 8. Structural Completeness

**What it measures:** Is the scene data complete enough to assess and draft from?

**How it's computed:**

For each scene, check which fields are populated across all three CSVs. Score based on:
- **Required fields**: Every scene should have function, value_at_stake, value_shift, emotional_arc, goal, conflict, outcome, crisis, decision
- **Enrichment fields**: knowledge_in/out, key_actions, key_dialogue, emotions, motifs, continuity_deps, mice_threads
- **Weight by status**: drafted scenes with empty briefs score lower than spine scenes with empty briefs

**Score:** 0-1 ratio of populated to expected fields.

This is the simplest dimension — it mostly answers "have we done enough elaboration work to assess the other dimensions?"

## Overall Score

Weighted average of all 8 dimensions. Weights are author-configurable via `working/structural-weights.csv` (same pattern as craft-weights.csv). Default weights:

| Dimension | Default Weight |
|-----------|---------------|
| Arc Completeness | 1.0 |
| Thematic Concentration | 0.8 |
| Pacing Shape | 1.0 |
| Character Presence | 0.7 |
| MICE Thread Health | 0.6 |
| Knowledge Chain Integrity | 0.5 |
| Scene Function Variety | 0.7 |
| Structural Completeness | 0.3 |

Lower weights on knowledge chain and structural completeness because they're more about data quality than story quality. Higher weights on arcs and pacing because those are what readers feel most.

## Output Format

### Score Card

```
Structural Score: 0.68 / 1.00

  Arc Completeness:       0.72  ████████░░  (target: 0.80+)
  Thematic Concentration: 0.45  █████░░░░░  (target: 0.60+)
  Pacing Shape:           0.81  █████████░  (target: 0.75+)
  Character Presence:     0.65  ███████░░░  (target: 0.70+)
  MICE Thread Health:     0.58  ██████░░░░  (target: 0.60+)
  Knowledge Chain:        0.70  ████████░░  (target: 0.60+)
  Scene Function Variety: 0.73  ████████░░  (target: 0.65+)
  Structural Completeness:0.95  ██████████  (target: 0.80+)
```

### Diagnosis (coaching level: full)

```
## Top Findings

1. **Thematic Concentration: 0.45** — 42 distinct values for 66 scenes.
   Your top 3 values (justice, truth, safety) cover 51% of scenes, but the
   remaining 39 values fragment the thematic spine.
   → Consolidate values.csv to 10-12 core themes. Map specific variants
     to abstract concepts (justice-specifically-restorative → justice).

2. **Character Presence: 0.65** — Keele (antagonist) on-stage in 5/66
   scenes (8%). Thomas absent from seq 28-45.
   → Add Keele to on_stage in 3-4 mid-novel scenes. Add a Thomas
     scene or reference between seq 28 and 35.

3. **Arc Completeness: 0.72** — Emmett uses 'justice' in 22/30 scenes.
   → Vary Emmett's value_at_stake: introduce 'loyalty' or 'identity'
     for 5-8 scenes in the mid-section.
```

### Diagnosis (coaching level: coach)

```
## Questions to Consider

1. **Thematic Concentration: 0.45** — You have 42 distinct values.
   - Which 8-10 values are truly at the heart of this story?
   - Can you group the specific variants under broader themes?

2. **Character Presence: 0.65** — Keele appears in 5 scenes.
   - Is Keele's limited presence intentional (looming threat) or
     a gap (reader forgets he exists)?
   - Where might Thomas make a brief appearance in seq 28-45?
```

### Diagnosis (coaching level: strict)

```
## Data

Thematic Concentration: 0.45 (42 distinct values, Herfindahl 0.08)
Character Presence: 0.65 (Keele on_stage 5/66, Thomas gap 28-45)
Arc Completeness: 0.72 (Emmett justice 22/30, Cora 4 values)
```

## Implementation

### Module: `scripts/lib/python/storyforge/structural.py`

Pure Python, no API calls. Functions:

- `score_arcs(scenes_map, intent_map, briefs_map)` → dict per character
- `score_thematic_concentration(intent_map)` → float + findings
- `score_pacing(scenes_map, intent_map, briefs_map)` → float + findings
- `score_character_presence(scenes_map, intent_map)` → float + findings
- `score_mice_health(scenes_map, intent_map)` → float + findings
- `score_knowledge_chain(scenes_map, briefs_map)` → float + findings
- `score_function_variety(intent_map, briefs_map)` → float + findings
- `score_completeness(scenes_map, intent_map, briefs_map)` → float + findings
- `structural_score(ref_dir, weights_file=None)` → full report dict
- `format_scorecard(report)` → terminal-printable score card
- `format_diagnosis(report, coaching_level)` → diagnostic text

### Script: integrated into `storyforge-validate`

Add `--structural` flag to storyforge-validate. When present, run structural scoring after validation and include in the report. This keeps one command for "check my data."

Or: add as a mode to the existing `storyforge-score` script — `storyforge score --structural` (since it's a scoring system, just structural rather than craft).

### Tracking

Store results in `working/scores/structural-YYYYMMDD-HHMMSS.csv` alongside craft scores. The visualization dashboard can then show structural score trends over time.

## Genre Calibration

Default targets assume general literary/commercial fiction. Genre presets adjust:

| Genre | Arc target | Pacing notes | Thread ratio target |
|-------|-----------|-------------|-------------------|
| Thriller | 0.75 | Climax at 85-90%, escalation mandatory | 0.8+ close ratio |
| Literary fiction | 0.85 | Midpoint reversal optional, denouement longer | 0.6+ close ratio |
| Romance | 0.80 | Dual arcs required, midpoint crisis mandatory | 0.7+ close ratio |
| Mystery | 0.70 | Inquiry threads dominant (>50%), all must close | 0.9+ close ratio |
| Fantasy | 0.75 | Milieu threads prominent, longer lifespans OK | 0.7+ close ratio |

Genre is read from `storyforge.yaml` `project.genre` field.

## Cost

Zero. All computation is deterministic Python over CSV data. No API calls. Can run 100 times per revision cycle.
