# Elaboration Pipeline Design

**Date:** 2026-04-01
**Status:** Approved
**Scope:** Full pipeline redesign — from seed to production

## Problem

The current Storyforge pipeline drafts prose early and then runs expensive evaluate/revise cycles (4-6 rounds) to fix structural problems — continuity errors, knowledge violations, dropped threads, pacing issues, character arc gaps. These problems are baked in at draft time and costly to fix in prose. Revision passes sometimes introduce new problems, creating further cycles.

The core insight: if structural integrity is verified before prose exists, most of these problems never occur. Editing becomes pre-work instead of post-work. The actual writing becomes one of the final steps.

## Design Principles

1. **Progressive elaboration.** Start with the bones of the story and add detail in stages. Each stage is validated before the next begins.
2. **Validate cheap, fix cheap.** Catch problems when they're CSV cell edits, not prose rewrites.
3. **Parallel drafting.** Briefs should contain enough structural detail that scenes can be drafted independently and cohere.
4. **Evaluation feeds upstream.** When evaluators find a problem, the fix goes to the briefs, not to the prose. Revised briefs produce revised scenes that have the fix built in.
5. **Coaching levels are roles, not dosages.** Full = Claude as creative partner. Coach = Claude as dramaturg. Strict = Claude as continuity editor. Each role is genuinely valuable.

## Pipeline Overview

```
Seed → Spine → Architecture → Scene Map → Briefs → Validate → Draft → Evaluate → Polish → Produce
         ↑         ↑              ↑           ↑                                        ↑
      PR gate   PR gate       PR gate     PR gate                                  PR gate
```

Each stage boundary is a PR. Claude creates a branch, does the work, opens a draft PR. Author merges to advance. In full mode, Claude can chain stages if the author says "keep going." In strict mode, every PR is a genuine review gate.

## Scene Data Model

Three pipe-delimited CSV files in `reference/`, joined by `id`. Python helpers provide a unified interface; a validation script ensures cross-file consistency.

### `reference/scenes.csv` — structural identity and position

| Column | Populated at | Description |
|--------|-------------|-------------|
| `id` | spine | Descriptive slug, also filename |
| `seq` | spine | Reading order (integer) |
| `title` | spine | Working title for the scene |
| `part` | architecture | Act/part number |
| `pov` | architecture | POV character |
| `location` | map | Physical place |
| `timeline_day` | map | Chronological position |
| `time_of_day` | map | morning/afternoon/evening/night |
| `duration` | map | How long the scene spans in story-time |
| `status` | all | spine/architecture/mapped/briefed/drafted/polished |
| `word_count` | draft | Actual (0 until drafted) |
| `target_words` | map | Target for the scene |

### `reference/scene-intent.csv` — purpose, dynamics, tracking

| Column | Populated at | Description |
|--------|-------------|-------------|
| `id` | spine | Matches scenes.csv |
| `function` | spine | Why the scene exists — must be testable |
| `scene_type` | architecture | action or sequel (Swain). Action = goal/conflict/outcome. Sequel = reaction/dilemma/decision |
| `emotional_arc` | architecture | Start → end emotional state |
| `value_at_stake` | architecture | The value being tested: safety, love, justice, truth, etc. (McKee) |
| `value_shift` | architecture | Polarity change: +/-, -/+, +/++, -/-- (Story Grid) |
| `turning_point` | architecture | action or revelation — varying these prevents monotony (Story Grid) |
| `threads` | architecture | Story threads this scene touches |
| `characters` | map | All characters present or referenced |
| `on_stage` | map | Characters physically present (subset of characters) |
| `mice_threads` | map | Open/close MICE threads: `+milieu:canyon`, `-inquiry:who-killed-father` (Kowal FILO nesting) |

### `reference/scene-briefs.csv` — the drafting contract

| Column | Populated at | Description |
|--------|-------------|-------------|
| `id` | brief | Matches scenes.csv |
| `goal` | brief | POV character's concrete goal entering (Swain) |
| `conflict` | brief | What opposes the goal |
| `outcome` | brief | How the scene ends: yes / no / yes-but / no-and (Weiland) |
| `crisis` | brief | The dilemma: best bad choice or irreconcilable goods (Story Grid Five Commandments) |
| `decision` | brief | What the character chooses |
| `knowledge_in` | brief | What POV character knows entering |
| `knowledge_out` | brief | What POV character knows leaving |
| `key_actions` | brief | Concrete things that happen (semicolon-separated) |
| `key_dialogue` | brief | Specific lines or exchanges that must appear |
| `emotions` | brief | Emotional beats in sequence |
| `motifs` | brief | Recurring images/symbols deployed |
| `continuity_deps` | brief | Scene IDs this scene depends on (for parallel drafting) |
| `has_overflow` | brief | Whether `briefs/{id}.md` exists for extended detail |

### Design rationale

**Three files instead of one.** A single 30-column CSV is unwieldy to read, edit, and pass to Claude. Three files with clear consumers (structural = production/pacing, intent = evaluation/tracking, brief = drafting) keep each file focused. Python helpers join them transparently.

**CSV over markdown for briefs.** CSV cells are queryable, filterable, and token-efficient for batch operations. Validation can read specific columns without parsing prose. Complex scenes that need richer guidance use the `briefs/{id}.md` overflow mechanism.

**Replaces scene-metadata.csv and scene-intent.csv.** The current two-file split (metadata vs intent) was somewhat arbitrary. The new three-file split is organized by consumer and elaboration stage.

### Python helpers — `scripts/lib/scenes.py`

```python
get_scene(id)                    # Returns all columns across all three files
get_scenes(columns=[], filters={})  # Query with column selection and filtering
get_column(name)                 # One column across all scenes
update_scene(id, updates={})     # Update specific columns atomically
add_scenes(rows)                 # Append new scene rows
validate_stage(stage)            # Run structural checks for current depth
```

The bash CSV helpers (`scripts/lib/csv.sh`) remain available for scripts that need them.

## Elaboration Stages

### Stage 1: Spine

**Input:** Author's seed — logline, genre, thematic territory, constraints.

**Produces:**
- `reference/story-architecture.md` — premise, theme (as question, not statement), three-level conflict (external/internal/thematic), ending
- `reference/character-bible.md` — protagonist with wound/lie/need/want, antagonist force, 1-2 key relationships. Not exhaustive.
- `reference/scenes.csv` — 5-10 rows: `id`, `seq`, `title`, `status=spine`
- `reference/scene-intent.csv` — matching rows: `function` only

The spine is the irreducible story. Each event connects causally (but/therefore, not and-then). Readable as a single-paragraph summary.

**Validation:**
- Every spine event connects causally to adjacent events
- Protagonist's wound/lie produces a want that drives the external conflict
- Ending resolves all three conflict levels (external/internal/thematic)
- Premise is testable as a controlling idea (McKee)

**PR:** Branch `storyforge/spine-*`.

### Stage 2: Architecture

**Input:** Approved spine.

**Produces:**
- `scenes.csv` expanded: spine events grow to 15-25 scenes. `part`, `pov` columns populated.
- `scene-intent.csv` populated: `scene_type`, `emotional_arc`, `value_at_stake`, `value_shift`, `turning_point`, `threads`
- Character bible deepened: supporting characters with wound/lie/need
- `reference/world-bible.md` created if genre requires it

This is where Swain's action/sequel rhythm becomes visible, McKee's value shifts create a trackable arc, and the thread structure takes shape.

**Validation:**
- No flat polarity stretches (3+ scenes with no value shift)
- Action/sequel rhythm balanced (no 4+ consecutive same type)
- Every thread introduced has a planned resolution
- Turning point types vary across sequences
- POV distribution is intentional
- Parts hit roughly right proportions (first act ~25%, midpoint ~50%, climax ~75-85%)
- Character arcs have structural progression points (lie reinforced → challenged → confronted → truth/refusal)

**PR:** Branch `storyforge/architecture-*`.

### Stage 3: Scene Map

**Input:** Approved architecture.

**Produces:**
- Full scene count (40-60 scenes): gaps filled, transitions added
- `scenes.csv` fully populated: `location`, `timeline_day`, `time_of_day`, `duration`
- `scene-intent.csv` deepened: `characters`, `on_stage`, `mice_threads`
- `reference/continuity-tracker.md` initialized with timeline and character starting states

This is where Rowling's subplot grid becomes real — every thread tracked per scene, every character's presence recorded, MICE threads opened and closed in proper nesting order.

**Validation:**
- Timeline consistency (no backward jumps without explicit markers)
- Every character referenced exists in the character bible
- MICE thread nesting is valid (FILO order)
- No thread dormant for more than 8-10 scenes without acknowledgment
- Every scene has at least one on-stage character
- Location names are consistent (same place, same name)
- Total target_words sums to within 10% of manuscript target

**PR:** Branch `storyforge/map-*`.

### Stage 4: Briefs

**Input:** Approved scene map.

**Produces:**
- `reference/scene-briefs.csv` fully populated: all columns
- `reference/voice-guide.md` created if not already
- Complex scenes get `briefs/{id}.md` overflow (climax, major turning points, intricate information management)

The briefs are the drafting contract. When read in sequence (goal → conflict → outcome → crisis → decision per scene), they should tell a coherent story.

**Validation:**
- Every scene has goal/conflict/outcome
- knowledge_out minus knowledge_in is consistent with what happens in the scene
- No character learns something in scene N that isn't established by a prior scene's knowledge_out
- continuity_deps form a valid DAG (no circular dependencies)
- Scenes with no continuity_deps can be drafted in parallel
- Structural scoring passes (see Scoring section)

**PR:** Branch `storyforge/briefs-*`.

## Validation Engine

### Level 1: Structural validation (deterministic, no Claude, instant)

Runs automatically after every CSV change. Python script.

**Identity & completeness:**
- Every `id` in intent and briefs exists in scenes.csv
- No orphaned rows
- Required columns for current status are populated

**Timeline & continuity:**
- Timeline days consistent with seq order
- Scene durations don't overlap impossibly
- knowledge_out from scene N available as knowledge_in for later scenes referencing it
- No character acts on information not in a prior scene's knowledge_out

**Thread management:**
- Every thread referenced has been introduced
- No thread dormant beyond configurable threshold (default 8 scenes)
- MICE threads nest in valid FILO order
- Every opened thread has a planned close

**Character consistency:**
- Every character name exists in character bible
- POV characters have wound/lie/need defined
- on_stage is always a subset of characters

**Structural scoring (brief stage):**
- Every briefed scene has a non-flat value_shift
- goal/conflict/outcome chain complete
- crisis is a genuine dilemma
- Turning point types vary across sequences
- Action/sequel rhythm has no 4+ consecutive same type
- Total target_words within 10% of manuscript target

### Level 2: Narrative validation (Claude-powered, at PR gates)

- Scene functions advance the story (no redundant scenes)
- Character arcs progress through wound → lie challenged → confrontation → truth/refusal
- Emotional pacing reads well when scanning emotional_arc column in sequence
- Thematic threads deepen rather than just repeat
- Briefs read as a coherent, escalating story
- Evaluator perspectives flag structural concerns (developmental, genre, first reader)
- Voice guide is achievable given what the briefs require

### Validation output

`working/validation/validate-{timestamp}.md`:
- Pass/fail per check category
- Specific failures with scene IDs and column references
- Severity: **blocking** (must fix before advancing) vs **advisory** (author's judgment)

Blocking failures prevent stage advancement.

## Scoring

Scoring operates at two points in the pipeline.

### Pre-draft structural scoring (after briefs)

Deterministic, no Claude. Reads brief CSV columns and flags scenes that are structurally weak:

- Value shift is flat (+/+)
- Goal/conflict/outcome chain incomplete
- Crisis not a genuine dilemma
- Turning point type matches 3+ adjacent scenes
- Action/sequel rhythm imbalanced

This catches "this scene has no conflict" at the brief stage where fixing it costs one CSV edit.

### Post-draft craft scoring (after drafting)

The existing craft scoring rubrics run against prose: enter late/leave early, psychic distance, thread management, pacing through variety, etc.

The new addition: **score-to-brief comparison.** Did the prose deliver what the brief promised?

- Brief says `value_shift: -/+` but craft score for "every scene turns" is 2/5 → the turn didn't land
- Brief says `scene_type: action` but prose reads as sequel → drafter drifted
- Brief says `key_dialogue: "The numbers don't lie"` but the line doesn't appear → contractual miss

This comparison makes evaluation findings actionable — they point to specific brief columns, not vague prose quality.

## Drafting

### Parallel wave drafting

The `continuity_deps` column defines a dependency graph. Scenes with no deps (or whose deps are all drafted) can run simultaneously.

- **Wave 1:** All scenes with no continuity_deps
- **Wave 2:** Scenes whose deps were all in wave 1
- **Wave 3:** etc.

Most novels would have 3-5 waves covering 40-60 scenes. Each wave runs in parallel (batch API in full mode).

### What the drafter receives

Per scene:
1. Voice guide
2. Craft principles (weighted directive)
3. The scene's full row across all three CSVs
4. Brief rows of its continuity_deps (context for what happened before)
5. Relevant character bible entries (only on_stage characters)
6. Overflow brief if has_overflow is true

The full manuscript is NOT included. The brief is the contract. This keeps prompts focused and token cost predictable.

### Post-draft verification

After all scenes draft, a lightweight check confirms prose matches the brief contract:
- Character knows what knowledge_out says by scene end
- Key dialogue lines appeared (or close paraphrases)
- Value shift landed as specified
- Word count within tolerance of target_words

Mismatches are flagged. Minor deviations (dialogue rephrased) are fine. Structural violations go back to the author.

### Stitching pass

A light pass reads adjacent scene endings/openings and smooths transitions. This handles the seams between independently drafted scenes. It's not revision — just continuity of reading experience.

### Coaching levels

- **Full:** Draft complete prose from brief.
- **Coach:** Produce expanded scene writing guides (brief columns rendered as narrative guidance with voice notes and craft reminders). Author writes prose.
- **Strict:** Pass through brief data formatted for author reference. No creative contribution.

## Evaluation and Feedback Loop

### Evaluators stay, role changes

Same six perspectives (literary agent, developmental editor, line editor, genre expert, first reader, writing coach). Findings are categorized by where the fix belongs:

- **Structural findings** → traceable to a brief column → fix in scene-briefs.csv → re-validate → re-draft affected scenes
- **Architectural findings** → traceable to intent/structure → fix in scene-intent.csv or scenes.csv → cascade through briefs → re-draft
- **Craft findings** → prose-level only → queue for polish (no brief changes)

### Expected cycle count

- **Usually 1 cycle.** Structural pre-work catches most problems. First evaluation mostly surfaces craft findings.
- **Occasionally 2 cycles** if evaluation reveals an architectural issue cascading through multiple scenes.
- **Rarely 3+.** Hitting 3 cycles means the briefs stage didn't do its job.

## Polish

Replaces the current multi-cycle revision pipeline. Structural integrity is guaranteed by brief/validation work. Polish is prose-only.

**Covers:**
- Voice consistency with voice guide
- Craft quality (enter late/leave early, psychic distance, show vs tell)
- Prose naturalness (AI-pattern issues: antithesis framing, tricolon, hedge-stacking)
- Transition smoothness
- Dialogue authenticity
- Line-level rhythm and precision

**Does NOT cover:** Continuity, knowledge violations, thread management, structural pacing, scene function. All handled upstream.

**Targeted:** Scenes with high craft scores get a light touch. Scenes with low scores get substantive polish. One pass.

**Coaching levels:**
- **Full:** Claude polishes prose.
- **Coach:** Claude produces craft notes per scene. Author polishes.
- **Strict:** Craft scores only. Author polishes.

## Production

Unchanged: assembly, epub/PDF/HTML, dashboard, cover, press kit, bookshelf publishing. The manuscript arriving at production should be cleaner — fewer last-minute fixes during assembly.

## Coaching Levels Summary

| Stage | Full | Coach | Strict |
|-------|------|-------|--------|
| Seed | Author provides | Author provides | Author provides |
| Spine | Claude proposes, PR for review | Claude presents options, author chooses | Author writes, Claude formats |
| Architecture | Claude builds, PR for review | Claude proposes, author decides | Author designs, Claude validates |
| Scene Map | Claude generates, validate checks | Claude fills gaps, author validates | Author maps, Claude validates |
| Briefs | Claude writes, validate checks | Claude drafts, author edits | Author writes, **Claude validates** |
| Validate | Internal guardrail | Checks framed as questions | **Exhaustive continuity editor** |
| Draft | Claude writes in parallel | Claude produces writing guides | Author writes from brief data |
| Evaluate | Routes findings upstream | Same diagnostics, as discussion | Scores + findings for author |
| Polish | Claude polishes | Claude provides craft notes | Scores only |
| Produce | Claude assembles | Collaborative | Author-driven with tooling |

In strict mode, validate is the product. An author who writes their own outlines and prose gets an exhaustive structural checker — the kind of mechanical verification that's genuinely hard for humans across 50+ scenes.

In full mode, validate is the guardrail that keeps autonomous agents honest and operating at a consistently high level.

## Migration

**New projects** get the elaboration pipeline by default. `/storyforge:init` sets up the three-file CSV structure.

**Existing projects** keep working. No forced migration. An optional migration skill can:
1. Split existing `scene-metadata.csv` + `scene-intent.csv` into the new three-file structure
2. Backfill status based on what exists (prose exists → `drafted`)
3. Leave brief columns empty for retroactive fill or future-only use

Old scripts continue to work for unmigrated projects. New scripts coexist.

## New and Modified Components

### New scripts
- `scripts/storyforge-validate` — structural validation, outputs report
- `scripts/storyforge-elaborate` — runs a single elaboration stage, creates branch and PR
- `scripts/storyforge-polish` — targeted prose polish based on craft scores
- `scripts/lib/scenes.py` — Python helpers for scene CSV operations
- `scripts/lib/validate.py` — structural validation engine

### Modified scripts
- `scripts/storyforge-write` — reads from brief CSV; supports parallel wave drafting
- `scripts/storyforge-evaluate` — categorizes findings as structural/craft/architectural; maps to brief columns
- `scripts/storyforge-score` — adds structural scoring from brief columns (pre-draft)

### New/modified skills
- `skills/elaborate/SKILL.md` — new interactive elaboration hub (preferred over extending forge, which stays as the legacy routing skill for existing projects)
- `skills/scenes/SKILL.md` — works with three-file model
- `skills/develop/SKILL.md` — becomes spine stage entry point
- `skills/plan-revision/SKILL.md` — routes findings to brief/intent/structural fixes
- `skills/recommend/SKILL.md` — understands elaboration stages, recommends next based on status depth

## Craft Research Sources

The scene data model and validation checks draw from established craft traditions:

- **Dwight Swain** (*Techniques of the Selling Writer*): Scene/sequel pattern, goal/conflict/outcome, reaction/dilemma/decision, motivation-reaction units
- **Robert McKee** (*Story*): Value at stake, value shift/polarity, turning points (action vs revelation), scene as smallest unit of change
- **Shawn Coyne** (Story Grid): Five Commandments (inciting incident, progressive complications, crisis, climax, resolution), 14-column spreadsheet, polarity tracking
- **K.M. Weiland** (*Structuring Your Novel*, *Creating Character Arcs*): Scene question/answer (yes/no/yes-but/no-and), wound/lie/need/want arc structure
- **Mary Robinette Kowal** (MICE Quotient): Thread typing (milieu/inquiry/character/event), FILO nesting order
- **Randy Ingermanson** (Snowflake Method): Progressive elaboration from one sentence to scene-level detail
- **J.K. Rowling**: Subplot grid — explicit columns per thread tracked per chapter
- **Brandon Sanderson**: "Points on the map" — know your ending and major waypoints, leave paths open

## Open Questions

These items should evolve through use on actual projects:

1. **Exact brief column schema.** The columns listed here are a starting point. The first project through the pipeline will reveal which columns are essential and which are overhead.
2. **Structural scoring thresholds.** What polarity-flat stretch length is too many? What thread dormancy count triggers a warning? These should be configurable per project.
3. **Parallel drafting granularity.** How fine-grained should continuity_deps be? Scene-level? Or can we group scenes into "drafting clusters" that share context?
4. **Voice proofing.** Should 2-3 sentinel scenes be drafted early (opening, midpoint, climax) as voice proofs before committing to full parallel drafting?
5. **Overflow brief format.** What structure works best for the `briefs/{id}.md` files? Beat-by-beat? Narrative paragraph? This needs experimentation.
