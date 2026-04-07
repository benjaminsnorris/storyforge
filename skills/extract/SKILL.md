---
name: extract
description: Extract structural data from existing prose into the elaboration pipeline's three-file CSV model. Use when an author has an existing manuscript or scenes and wants to reverse-engineer the structural data (scenes.csv, scene-intent.csv, scene-briefs.csv) for validation, analysis, or expansion planning.
---

# Storyforge Extract — Reverse Elaboration

You are helping an author extract structural data from their existing prose. This is the reverse of the elaboration pipeline: instead of building structure first and writing prose second, you're analyzing prose that already exists and extracting the structural skeleton, narrative intent, and drafting contracts from it.

The goal is to produce data accurate enough for the author to **review and correct**, not build from scratch.

## Locating the Storyforge Plugin

The Storyforge plugin root is two levels up from this skill file's directory (this skill's directory → `skills/` → plugin root).

Store this resolved plugin path for use throughout the session.

## Step 1: Read Project State

1. `storyforge.yaml` — project title, genre, coaching level
2. `scenes/` directory — check how many scene files exist
3. `reference/scenes.csv` — does scene data already exist?
4. `reference/scene-intent.csv` — does intent data exist?
5. `reference/scene-briefs.csv` — does brief data exist?

## Registry Awareness

Read all registry files in `reference/` to know canonical IDs for normalized fields:

- `reference/characters.csv` — canonical character IDs
- `reference/locations.csv` — canonical location IDs
- `reference/values.csv` — canonical value IDs
- `reference/knowledge.csv` — canonical knowledge fact IDs
- `reference/motif-taxonomy.csv` — canonical motif IDs
- `reference/mice-threads.csv` — canonical MICE thread IDs

When extracting data interactively, use canonical IDs from these registries for all registry-backed fields (pov, characters, on_stage, location, value_at_stake, knowledge_in, knowledge_out, motifs, mice_threads). When extraction discovers a new character, location, value, knowledge fact, motif, or MICE thread not already in a registry, add it to the appropriate registry CSV first, then use the new ID.

## Step 2: Determine What Needs Extraction

Based on project state:

- **No scene files** → Author needs to split their manuscript first. Route to `/storyforge:scenes` (setup mode) or help them split interactively.
- **Scene files exist, no CSV data or old metadata CSV** → Full extraction needed (all 4 phases). The extraction will read the prose and build all three CSVs from scratch.
- **Scene files + partial elaboration data** → Targeted extraction — only run phases for missing data.

## Step 3: Execute Extraction

### Option A: Run Autonomously

Provide the command for the author to run:

```bash
cd [project_dir] && [plugin_path]/scripts/storyforge-extract [options]
```

Options:
- `--phase 0` — Characterize manuscript only (cheap, fast, good first step)
- `--phase 1` — Extract skeleton (scenes.csv) only
- `--phase 2` — Extract intent only (needs phase 1)
- `--phase 3` — Extract briefs only (needs phases 1-2)
- `--expand` — Include expansion analysis (for novella-to-novel work)
- `--dry-run` — Print prompts without calling the API

For full extraction with cleanup: `./storyforge extract` (runs all phases + cleanup)
For expansion planning: `./storyforge extract --expand`
For cleanup only (on already-extracted data): `./storyforge extract --cleanup-only`

Cleanup runs automatically after full extraction. It normalizes knowledge wording (fuzzy-matches mismatched facts), fills timeline gaps (interpolates from adjacent scenes), and fixes MICE thread issues (removes duplicates and orphaned closes). In full/coach mode, fixes are applied automatically. In strict mode, issues are reported for the author to fix.

### Option B: Run Interactively

Work through each phase in this conversation:

**Phase 0: Characterize.** Read the full manuscript (concatenate scene files) and produce a structural profile — narrative mode, POV characters, timeline, act structure, central conflict, compression points. Present the profile to the author for confirmation.

**Phase 1: Skeleton.** For each scene, extract: title, POV, location, timeline day, time of day, duration, part assignment. Write to `reference/scenes.csv`. This can be done in batches — present a batch of 10 scenes at a time for the author to review.

**Phase 2: Intent.** For each scene, extract: function, scene type (action/sequel), emotional arc, value at stake, value shift, turning point, characters, on-stage characters, MICE threads. Write to `reference/scene-intent.csv`.

**Phase 3: Briefs.** Two sub-phases:
- 3a (parallel): goal, conflict, outcome, crisis, decision, key actions, key dialogue, emotions, motifs
- 3b (sequential): knowledge_in, knowledge_out, continuity_deps — must process in scene order

Write to `reference/scene-briefs.csv`.

After each phase, commit: `git add -A && git commit -m "Extract: Phase N — [description]" && git push`

## Step 4: Reconcile and Validate

After extraction completes (reconciliation runs automatically after each phase, but can also be run manually):

1. **Reconcile** (if not already done): `./storyforge reconcile`
   - Builds/updates registries (characters, locations, values, MICE threads, knowledge) using Opus
   - Normalizes all CSV fields against canonical IDs
   - Normalizes outcome fields to enum values (yes/yes-but/no/no-and/no-but)
2. **Validate structure**: `./storyforge validate`
3. **Score structure** (optional but recommended): `./storyforge validate --structural`
   - Scores 8 dimensions of story quality from CSV data (deterministic, free, instant)
   - Produces diagnostic findings with craft-grounded explanations
   - Generates proposals in `working/scores/structural-proposals.csv`
4. Present the validation and scoring reports to the author
5. Walk through any validation failures and structural findings

Note: Re-running extraction on a branch with existing data only fills empty fields (preserves prior work). Use `--force` to overwrite existing values when a full re-extraction is desired.

## Step 5: Expansion Analysis (Optional)

If the author is developing a novella into a novel, or wants to identify structural expansion opportunities:

1. Run: `./storyforge extract --expand`
2. Or interactively analyze the extracted data for:
   - **Compressed scenes** — major value shifts in very few words
   - **Knowledge jumps** — characters learning 3+ facts in one scene
   - **Timeline gaps** — days missing between scenes
   - **Thin MICE threads** — threads appearing in only 1-2 scenes
   - **Missing sequels** — action scenes without reaction beats

Present opportunities ranked by priority and let the author decide which to pursue. Then route to `/storyforge:elaborate` to plan the expansion.

## Coaching Level Behavior

- **Full:** Run extraction autonomously, present results with analysis and recommendations for correction.
- **Coach:** Run extraction, walk through each phase's results with the author, discuss concerns and ambiguities, help them decide what to correct.
- **Strict:** Run extraction, present raw data tables for the author to review and correct independently. Flag validation failures but don't interpret them.

## Ensure Feature Branch

Before making any changes, check the current branch:
```bash
git rev-parse --abbrev-ref HEAD
```
- If on `main` or `master`: create a feature branch first:
  ```bash
  git checkout -b "storyforge/extract-$(date '+%Y%m%d-%H%M')"
  ```
- If on any other branch: stay on it — do not create a new branch.

## Commit After Every Deliverable

Each phase's output gets committed immediately:

```bash
git add -A && git commit -m "Extract: Phase N — [description]" && git push
```
