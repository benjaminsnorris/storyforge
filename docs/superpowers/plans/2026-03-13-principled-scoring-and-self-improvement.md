# Principled Scoring & Self-Improvement Implementation Plan

> **For agentic workers:** REQUIRED: Use superpowers:subagent-driven-development (if subagents available) or superpowers:executing-plans to implement this plan. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build a scoring system that evaluates scenes against craft engine principles, diagnoses weaknesses, proposes prompt adjustments, and feeds validated improvements back to the plugin.

**Architecture:** New scoring library (`scripts/lib/scoring.sh`) handles score parsing, diagnosis, and proposal generation. New script (`scripts/storyforge-score`) orchestrates the scoring pass. Scoring prompts live in `scripts/prompts/scoring/`. Craft weights in `working/craft-weights.csv` drive weighted prompt injection via updated `prompt-builder.sh`. Plugin insights submitted as GitHub issues.

**Tech Stack:** Pure bash/awk/sed. Pipe-delimited CSV (`;` for arrays). Claude invoked via `claude -p` with `--output-format stream-json`. Sonnet model for all scoring (analytical task).

**Spec:** `docs/superpowers/specs/2026-03-13-principled-scoring-and-self-improvement-design.md`

---

## File Structure

**New files:**
- `references/scoring-rubrics.md` — Score band definitions (1-3, 4-6, 7-8, 9-10) with literary exemplars for each of 25 scene-level + 9 act-level + 8 novel-level principles
- `references/default-craft-weights.csv` — Default weights for all principles, copied to projects on first scoring run
- `scripts/lib/scoring.sh` — Scoring library: score parsing, diagnosis generation, proposal generation, tuning ledger management, pattern validation, plugin insight submission
- `scripts/storyforge-score` — Main scoring script (autonomous, three modes)
- `scripts/prompts/scoring/scene-craft.md` — Prompt template for Scene Craft scoring group
- `scripts/prompts/scoring/prose-craft.md` — Prompt template for Prose Craft scoring group
- `scripts/prompts/scoring/character-craft-scene.md` — Prompt template for scene-level Character Craft
- `scripts/prompts/scoring/rules.md` — Prompt template for Rules to Break scoring group
- `scripts/prompts/scoring/act-level.md` — Prompt template for act/part-level scoring
- `scripts/prompts/scoring/novel-level.md` — Prompt template for novel-level scoring (character arcs + genre)
- `scripts/prompts/scoring/quick.md` — Single-invocation prompt for quick mode
- `skills/score/SKILL.md` — Interactive scoring skill for author review and calibration
- `tests/test-scoring.sh` — Tests for scoring library functions
- `tests/test-score-script.sh` — Tests for storyforge-score script behavior

**Modified files:**
- `scripts/lib/prompt-builder.sh` — Add `build_weighted_directive()` and `get_scene_overrides()`, modify `build_scene_prompt()` to use weighted directives instead of raw craft sections
- `scripts/lib/costs.sh` — Add `score` case to `estimate_cost()`
- `tests/run-tests.sh` — Source `scoring.sh`, register new test suites
- `scripts/lib/common.sh` — Source `scoring.sh`
- `.claude-plugin/plugin.json` — Bump version to 0.17.0

---

## Chunk 1: Scoring Foundation

### Task 1: Create scoring rubrics reference document

**Files:**
- Create: `references/scoring-rubrics.md`

This is a research and writing task. The rubrics are the objective foundation the scoring system stands on.

- [ ] **Step 1: Research and write rubrics for Scene Craft principles (7)**

For each of the 7 Scene Craft principles (Enter Late/Leave Early, Every Scene Must Turn, Scene Emotion vs Character Emotion, Psychic Distance at Scene Level, Show vs Tell in Scenes, Thread Management, Pacing Through Scene Variety), write:
- Score band definitions: 1-3 (weak), 4-6 (developing), 7-8 (strong), 9-10 (masterful)
- 1-2 reference exemplars per band from published works or craft textbooks

Sources to draw from: Gardner's *The Art of Fiction*, Burroway's *Writing Fiction*, McKee's *Story*, Maass's *Writing the Breakout Novel*, Francine Prose's *Reading Like a Writer*.

- [ ] **Step 2: Research and write rubrics for Prose Craft principles (9)**

For each of the 9 Prose Craft principles. Sources: Strunk & White's *The Elements of Style*, Le Guin's *Steering the Craft*, King's *On Writing*, Garner's *Modern American Usage*, Tufte's *Artful Sentences*.

- [ ] **Step 3: Research and write rubrics for Character Craft (scene-level: 2, act-level: 2, novel-level: 4)**

For Egri's Premise, Testing Characters (scene-level), Character Web, Character as Theme (act-level), Want/Need, Wound/Lie, Flaws as Strengths, Voice as Character (novel-level). Sources: Egri's *The Art of Dramatic Writing*, Truby's *The Anatomy of Story*, Weiland's *Creating Character Arcs*.

- [ ] **Step 4: Research and write rubrics for Rules to Break (7)**

For each rule. These rubrics must assess whether violations are intentional/effective vs accidental/harmful. Sources: Strunk & White, Le Guin, King.

- [ ] **Step 5: Research and write rubrics for Narrative Frameworks (7 act-level) and Genre (4 novel-level)**

For each framework and genre convention. Sources: Campbell's *The Hero with a Thousand Faces*, Snyder's *Save the Cat*, Truby, Harmon.

- [ ] **Step 6: Commit**

```bash
git add references/scoring-rubrics.md
git commit -m "Add scoring rubrics with literary exemplars for all craft principles"
git push
```

### Task 2: Create default craft weights and scoring library foundation

**Files:**
- Create: `references/default-craft-weights.csv`
- Create: `scripts/lib/scoring.sh`
- Create: `tests/test-scoring.sh`

- [ ] **Step 1: Create default craft weights file**

Create `references/default-craft-weights.csv` with all principles at default weights:

```
section|principle|weight|author_weight|notes
scene_craft|enter_late_leave_early|5||
scene_craft|every_scene_must_turn|7||
scene_craft|scene_emotion_vs_character|5||
scene_craft|psychic_distance_scene|5||
scene_craft|show_vs_tell_scenes|6||
scene_craft|thread_management|5||
scene_craft|pacing_variety|5||
prose_craft|economy_clarity|5||
prose_craft|sentence_as_thought|5||
prose_craft|writers_toolbox|5||
prose_craft|precision_language|5||
prose_craft|persuasive_structure|5||
prose_craft|fictive_dream|5||
prose_craft|scene_vs_summary|6||
prose_craft|sound_rhythm_pov|5||
prose_craft|permission_honesty|5||
character_craft|egri_premise|5||
character_craft|testing_characters|4||
character_craft|want_need|6||
character_craft|wound_lie|6||
character_craft|character_as_theme|5||
character_craft|character_web|5||
character_craft|flaws_as_strengths|5||
character_craft|voice_as_character|5||
rules|show_dont_tell|5||
rules|avoid_adverbs|5||
rules|avoid_passive|5||
rules|write_what_you_know|3||
rules|no_weather_dreams|4||
rules|avoid_said_bookisms|5||
rules|kill_darlings|4||
narrative|campbells_monomyth|5||
narrative|three_act|5||
narrative|save_the_cat|4||
narrative|truby_22|5||
narrative|harmon_circle|5||
narrative|kishotenketsu|3||
narrative|freytag|5||
genre|trope_awareness|5||
genre|archetype_vs_cliche|5||
genre|genre_contract|6||
genre|subversion_awareness|4||
```

- [ ] **Step 2: Write failing tests for scoring library**

Create `tests/test-scoring.sh` with tests for:
- `init_craft_weights()` — copies defaults to project if missing
- `get_effective_weight()` — returns author_weight if set, else weight
- `parse_scene_scores()` — parses Claude's structured score output into CSV
- `generate_diagnosis()` — identifies weakest principles from score files
- `generate_proposals()` — creates proposals from diagnosis

```bash
#!/bin/bash
# test-scoring.sh — Tests for scoring library

# --- init_craft_weights ---
WEIGHTS_FILE="$TMPDIR/craft-weights.csv"
rm -f "$WEIGHTS_FILE"
init_craft_weights "$TMPDIR" "$PLUGIN_DIR"
assert_file_exists "$WEIGHTS_FILE" "init_craft_weights: creates weights file"
HEADER=$(head -1 "$WEIGHTS_FILE")
assert_contains "$HEADER" "section|principle|weight" "init_craft_weights: correct header"
ECON=$(get_csv_field "$WEIGHTS_FILE" "economy_clarity" "weight")
assert_equals "5" "$ECON" "init_craft_weights: default weight for economy"

# --- get_effective_weight ---
RESULT=$(get_effective_weight "$WEIGHTS_FILE" "economy_clarity")
assert_equals "5" "$RESULT" "get_effective_weight: returns weight when no author_weight"

# Set an author weight
update_csv_field "$WEIGHTS_FILE" "economy_clarity" "author_weight" "8"
RESULT=$(get_effective_weight "$WEIGHTS_FILE" "economy_clarity")
assert_equals "8" "$RESULT" "get_effective_weight: returns author_weight when set"
```

- [ ] **Step 3: Create scoring library with weight management functions**

Create `scripts/lib/scoring.sh`:

```bash
#!/bin/bash
# scoring.sh — Scoring library for principled evaluation
#
# Functions for craft weight management, score parsing, diagnosis,
# proposal generation, tuning ledger, and plugin insight submission.

# init_craft_weights(project_dir, plugin_dir)
# Copy default weights to project if craft-weights.csv doesn't exist
init_craft_weights() {
    local project_dir="$1" plugin_dir="$2"
    local weights_file="${project_dir}/working/craft-weights.csv"
    local defaults="${plugin_dir}/references/default-craft-weights.csv"
    if [[ ! -f "$weights_file" ]]; then
        mkdir -p "$(dirname "$weights_file")"
        cp "$defaults" "$weights_file"
    fi
}

# get_effective_weight(weights_file, principle)
# Return author_weight if set, otherwise weight
get_effective_weight() {
    local weights_file="$1" principle="$2"
    local author_w
    author_w=$(get_csv_field "$weights_file" "$principle" "author_weight")
    if [[ -n "$author_w" ]]; then
        echo "$author_w"
    else
        get_csv_field "$weights_file" "$principle" "weight"
    fi
}
```

Note: The `id` column in `default-craft-weights.csv` is `principle`, not `id`. The `get_csv_field` function matches on the first column by default — but our weights file uses `principle` as the key, not `id`. We need to either: (a) add an `id` column that duplicates `principle`, or (b) make `get_csv_field` configurable for which column is the key. Option (a) is simpler — add `id` as first column where `id` = `principle` value. Actually, looking at `get_csv_field` implementation, it always looks for a column named `id`. So the weights file needs an `id` column, or we need to update `get_csv_field` to accept a key column parameter.

**Decision:** Update `get_csv_field` and related functions to accept an optional key column parameter (default "id"). This is a small change to csv.sh.

- [ ] **Step 4: Update csv.sh to support custom key columns**

Add an optional 4th parameter to `get_csv_field`:

```bash
# get_csv_field(file, id, field, [key_column])
# key_column defaults to "id"
```

Same for `get_csv_row`, `update_csv_field`.

- [ ] **Step 5: Run tests**

Run: `./tests/run-tests.sh`
Expected: All PASS

- [ ] **Step 6: Commit**

```bash
git add references/default-craft-weights.csv scripts/lib/scoring.sh tests/test-scoring.sh scripts/lib/csv.sh
git commit -m "Add scoring foundation: default craft weights, scoring library, custom key columns in csv.sh"
git push
```

### Task 3: Create scoring prompt templates

**Files:**
- Create: `scripts/prompts/scoring/scene-craft.md`
- Create: `scripts/prompts/scoring/prose-craft.md`
- Create: `scripts/prompts/scoring/character-craft-scene.md`
- Create: `scripts/prompts/scoring/rules.md`
- Create: `scripts/prompts/scoring/act-level.md`
- Create: `scripts/prompts/scoring/novel-level.md`
- Create: `scripts/prompts/scoring/quick.md`

Each prompt template follows this structure:

- [ ] **Step 1: Create scene-craft.md scoring prompt**

```markdown
You are scoring a scene against Scene Craft principles. For each principle, assign a score from 1-10 based on the rubric provided.

## Principles to Score

{{RUBRIC_SECTIONS}}

## Scene to Evaluate

**Title:** {{SCENE_TITLE}}
**POV:** {{SCENE_POV}}
**Setting:** {{SCENE_SETTING}}
**Function:** {{SCENE_FUNCTION}}

{{SCENE_TEXT}}

## Craft Weights (author priorities)

{{WEIGHTED_PRINCIPLES}}

## Output Format

Respond with EXACTLY this CSV format, one header row followed by one data row. No other text.

```
id|enter_late_leave_early|every_scene_must_turn|scene_emotion_vs_character|psychic_distance_scene|show_vs_tell_scenes|thread_management|pacing_variety
{{SCENE_ID}}|SCORE|SCORE|SCORE|SCORE|SCORE|SCORE|SCORE
```

Then on a new line, output the rationale CSV:

```
id|enter_late_leave_early|every_scene_must_turn|scene_emotion_vs_character|psychic_distance_scene|show_vs_tell_scenes|thread_management|pacing_variety
{{SCENE_ID}}|ONE_SENTENCE|ONE_SENTENCE|ONE_SENTENCE|ONE_SENTENCE|ONE_SENTENCE|ONE_SENTENCE|ONE_SENTENCE
```
```

- [ ] **Step 2: Create prose-craft.md, character-craft-scene.md, rules.md**

Same pattern, different principle sets and column names. Each references the relevant rubric sections.

- [ ] **Step 3: Create act-level.md and novel-level.md**

Act-level scores all scenes in an act together for narrative framework and relational character craft. Novel-level scores the full character arcs and genre conventions. These prompts receive larger context (all scenes in scope).

- [ ] **Step 4: Create quick.md**

Single prompt that scores ALL scene-level principles at once for a given scene. Less accurate but fast.

- [ ] **Step 5: Commit**

```bash
git add scripts/prompts/scoring/
git commit -m "Add scoring prompt templates for all modes and principle groups"
git push
```

---

## Chunk 2: Scoring Script

### Task 4: Create storyforge-score script

**Files:**
- Create: `scripts/storyforge-score`
- Modify: `scripts/lib/scoring.sh` — add score parsing functions
- Create: `tests/test-score-script.sh`

- [ ] **Step 1: Write failing tests for score parsing**

Add to `tests/test-scoring.sh`:

```bash
# --- parse_score_output ---
# Mock Claude output with score CSV + rationale CSV
MOCK_OUTPUT="$TMPDIR/mock-score-output.txt"
cat > "$MOCK_OUTPUT" << 'EOF'
id|enter_late_leave_early|every_scene_must_turn
act1-sc01|8|9

id|enter_late_leave_early|every_scene_must_turn
act1-sc01|Opens at desk action|Clear turn when anomaly surfaces
EOF

SCORES_DIR="$TMPDIR/test-scores"
mkdir -p "$SCORES_DIR"
parse_score_output "$MOCK_OUTPUT" "$SCORES_DIR" "scene-scores" "scene-rationale"
assert_file_exists "$SCORES_DIR/scene-scores.csv" "parse_score_output: creates scores file"
assert_file_exists "$SCORES_DIR/scene-rationale.csv" "parse_score_output: creates rationale file"
SCORE=$(get_csv_field "$SCORES_DIR/scene-scores.csv" "act1-sc01" "enter_late_leave_early")
assert_equals "8" "$SCORE" "parse_score_output: correct score value"
```

- [ ] **Step 2: Implement score parsing in scoring.sh**

```bash
# parse_score_output(output_file, scores_dir, scores_name, rationale_name)
# Extract score CSV and rationale CSV from Claude's response
parse_score_output() {
    local output_file="$1" scores_dir="$2" scores_name="$3" rationale_name="$4"
    local scores_csv="${scores_dir}/${scores_name}.csv"
    local rationale_csv="${scores_dir}/${rationale_name}.csv"

    # Extract the two CSV blocks from the output
    # First block is scores (contains only numbers), second is rationale (contains text)
    # Parse by finding lines that match the CSV header pattern
    local in_block=0 block_count=0
    local current_file=""

    while IFS= read -r line; do
        # Skip empty lines and markdown fences
        [[ -z "$line" ]] && continue
        [[ "$line" == '```' ]] && continue
        [[ "$line" == '```csv' ]] && continue

        # Detect header line (starts with "id|")
        if [[ "$line" == id\|* ]]; then
            block_count=$((block_count + 1))
            if [[ $block_count -eq 1 ]]; then
                current_file="$scores_csv"
            else
                current_file="$rationale_csv"
            fi
            echo "$line" > "$current_file"
            continue
        fi

        # Data row (append to current file)
        if [[ -n "$current_file" ]] && [[ "$line" != \#* ]]; then
            echo "$line" >> "$current_file"
        fi
    done < "$output_file"
}
```

- [ ] **Step 3: Create storyforge-score script — argument parsing and framework**

Create `scripts/storyforge-score` with:
- Argument parsing: `--quick`, `--deep`, `--scenes ID,ID`, `--act N`, `--interactive`
- Project detection, scene list building from metadata.csv
- Cycle directory management (create `working/scores/cycle-N/`, update `latest` symlink)
- Cost forecasting before scoring begins

```bash
#!/bin/bash
set -eo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
source "${SCRIPT_DIR}/lib/common.sh"

MODE="grouped"  # grouped | quick | deep
SCOPE="full"    # full | scenes | act
SCENE_FILTER=""
ACT_FILTER=""
INTERACTIVE=false

while [[ $# -gt 0 ]]; do
    case "$1" in
        --quick)       MODE="quick"; shift ;;
        --deep)        MODE="deep"; shift ;;
        --grouped)     MODE="grouped"; shift ;;
        --scenes)      SCOPE="scenes"; SCENE_FILTER="$2"; shift 2 ;;
        --act)         SCOPE="act"; ACT_FILTER="$2"; shift 2 ;;
        --interactive|-i) INTERACTIVE=true; shift ;;
        *) echo "Unknown option: $1"; exit 1 ;;
    esac
done

detect_project_root
METADATA_CSV="${PROJECT_DIR}/scenes/metadata.csv"
INTENT_CSV="${PROJECT_DIR}/scenes/intent.csv"
SCENES_DIR="${PROJECT_DIR}/scenes"
PLUGIN_DIR=$(get_plugin_dir)

# Initialize craft weights if needed
init_craft_weights "$PROJECT_DIR" "$PLUGIN_DIR"

# Determine cycle
# ... (read from pipeline.yaml or create standalone)

# Build scene list based on scope
# ... (from metadata.csv, filter by scope)

# Cost forecast
# ... (estimate_cost "score" ...)

# Main scoring loop
# ... (per mode: grouped, quick, or deep)
```

- [ ] **Step 4: Implement grouped scoring mode**

The main scoring loop for grouped mode. For each scene in scope:
1. Read scene text from `scenes/{id}.md`
2. Read metadata and intent from CSV
3. Read craft weights
4. Read rubric sections from `references/scoring-rubrics.md`
5. For each scoring group (scene-craft, prose-craft, character-craft-scene, rules):
   a. Build prompt from template
   b. Invoke Claude with `--output-format stream-json`
   c. Parse score output
   d. Merge into the cycle's score CSVs
   e. Log usage

After all scenes scored:
6. Run act-level scoring (one per act)
7. Run novel-level scoring (once)

- [ ] **Step 5: Implement quick and deep modes**

Quick: same loop but uses `quick.md` template (all principles in one call per scene).
Deep: same loop but one invocation per principle per scene.

- [ ] **Step 6: Make executable, run tests**

```bash
chmod +x scripts/storyforge-score
```

Run: `./tests/run-tests.sh`
Expected: All PASS

- [ ] **Step 7: Commit**

```bash
git add scripts/storyforge-score scripts/lib/scoring.sh tests/test-scoring.sh tests/test-score-script.sh
git commit -m "Add storyforge-score script with grouped, quick, and deep scoring modes"
git push
```

---

## Chunk 3: Improvement Cycle

### Task 5: Implement diagnosis and proposal generation

**Files:**
- Modify: `scripts/lib/scoring.sh` — add diagnosis and proposal functions
- Modify: `tests/test-scoring.sh` — add tests

- [ ] **Step 1: Write failing tests for diagnosis generation**

```bash
# --- generate_diagnosis ---
# Create mock score files
DIAG_DIR="$TMPDIR/test-diag"
mkdir -p "$DIAG_DIR"
cat > "$DIAG_DIR/scene-scores.csv" << 'EOF'
id|economy_clarity|sentence_as_thought|thread_management
sc01|3|7|4
sc02|4|8|5
sc03|2|6|3
EOF

generate_diagnosis "$DIAG_DIR" "" "$TMPDIR/craft-weights.csv"
assert_file_exists "$DIAG_DIR/diagnosis.csv" "generate_diagnosis: creates diagnosis file"
RESULT=$(head -2 "$DIAG_DIR/diagnosis.csv" | tail -1)
assert_contains "$RESULT" "economy_clarity" "generate_diagnosis: identifies weakest principle"
```

- [ ] **Step 2: Implement `generate_diagnosis()`**

Reads score CSVs, computes per-principle averages, identifies worst scenes per principle, compares to previous cycle (if `prev_dir` provided), writes `diagnosis.csv`.

```bash
# generate_diagnosis(scores_dir, prev_scores_dir, weights_file)
generate_diagnosis() {
    local scores_dir="$1" prev_dir="$2" weights_file="$3"
    local diagnosis_file="${scores_dir}/diagnosis.csv"
    echo "principle|scale|avg_score|worst_items|delta_from_last|priority" > "$diagnosis_file"

    # Process scene-scores.csv
    local scores_file="${scores_dir}/scene-scores.csv"
    [[ -f "$scores_file" ]] || return 0

    local header
    header=$(head -1 "$scores_file")

    # For each principle column (skip id)
    local col=2
    for principle in $(echo "$header" | tr '|' '\n' | tail -n +2); do
        # Calculate average
        local avg
        avg=$(awk -F'|' -v c=$col 'NR>1 && $c != "" { sum+=$c; n++ } END { if(n>0) printf "%.1f", sum/n; else print "0" }' "$scores_file")

        # Find worst scenes (below average)
        local worst
        worst=$(awk -F'|' -v c=$col -v avg="$avg" 'NR>1 && $c != "" && $c < avg { print $1 }' "$scores_file" | head -5 | tr '\n' ';' | sed 's/;$//')

        # Get delta from previous cycle
        local delta=""
        if [[ -n "$prev_dir" && -f "${prev_dir}/scene-scores.csv" ]]; then
            local prev_avg
            prev_avg=$(awk -F'|' -v c=$col 'NR>1 && $c != "" { sum+=$c; n++ } END { if(n>0) printf "%.1f", sum/n; else print "0" }' "${prev_dir}/scene-scores.csv")
            delta=$(awk "BEGIN { printf \"%+.1f\", $avg - $prev_avg }")
        fi

        # Compute priority
        local weight
        weight=$(get_effective_weight "$weights_file" "$principle" 2>/dev/null || echo "5")
        local priority="low"
        if (( $(awk "BEGIN { print ($avg < 4) }") )); then priority="high"
        elif (( $(awk "BEGIN { print ($avg < 6) }") )); then priority="medium"
        fi
        # Boost priority if regressing
        if [[ -n "$delta" ]] && (( $(awk "BEGIN { print ($delta < -0.5) }") )); then
            priority="high"
        fi

        echo "${principle}|scene|${avg}|${worst}|${delta}|${priority}" >> "$diagnosis_file"
        col=$((col + 1))
    done
}
```

- [ ] **Step 3: Write failing tests for proposal generation**

```bash
# --- generate_proposals ---
generate_proposals "$DIAG_DIR" "$TMPDIR/craft-weights.csv"
assert_file_exists "$DIAG_DIR/proposals.csv" "generate_proposals: creates proposals file"
RESULT=$(cat "$DIAG_DIR/proposals.csv")
assert_contains "$RESULT" "economy_clarity" "generate_proposals: proposes for weakest principle"
assert_contains "$RESULT" "craft_weight" "generate_proposals: proposes weight change"
```

- [ ] **Step 4: Implement `generate_proposals()`**

Reads diagnosis, generates proposals for high-priority items. Proposes craft weight increases for low-scoring principles.

- [ ] **Step 5: Implement tuning ledger functions**

```bash
# record_tuning(project_dir, cycle, proposal_id, principle, lever, change, score_before, score_after, kept)
# append_csv_row to working/tuning.csv

# check_validated_patterns(project_dir)
# Read tuning.csv, find principle+lever combinations with 3+ successful applications
```

- [ ] **Step 6: Run tests, commit**

```bash
git add scripts/lib/scoring.sh tests/test-scoring.sh
git commit -m "Add diagnosis, proposal generation, and tuning ledger to scoring library"
git push
```

### Task 6: Wire improvement cycle into storyforge-score

**Files:**
- Modify: `scripts/storyforge-score`

- [ ] **Step 1: Add diagnosis step after scoring completes**

After all score CSVs are written, call `generate_diagnosis()` with current and previous cycle directories.

- [ ] **Step 2: Add proposal step**

Call `generate_proposals()` to create proposals.csv.

- [ ] **Step 3: Add approval step per coaching level**

- Full: auto-approve all proposals
- Coach: print proposals, prompt for approval
- Strict: print report only

- [ ] **Step 4: Add apply step**

For approved proposals, update the relevant levers:
- `craft_weight` → `update_csv_field` on `working/craft-weights.csv`
- `scene_intent` → `update_csv_field` on `scenes/intent.csv`
- `override` → write to `working/scores/cycle-N/overrides.csv`

- [ ] **Step 5: Add cost summary and git commit at end**

Print cost summary, commit score files and any weight/intent changes.

- [ ] **Step 6: Run tests, commit**

```bash
git add scripts/storyforge-score
git commit -m "Wire full improvement cycle into storyforge-score"
git push
```

---

## Chunk 4: Prompt Integration

### Task 7: Update prompt-builder for weighted directives

**Files:**
- Modify: `scripts/lib/prompt-builder.sh`
- Modify: `tests/test-prompt-builder.sh`

- [ ] **Step 1: Write failing tests for `build_weighted_directive`**

```bash
# Create a test weights file
WEIGHTS="$TMPDIR/test-weights.csv"
cp "$PLUGIN_DIR/references/default-craft-weights.csv" "$WEIGHTS"
update_csv_field "$WEIGHTS" "economy_clarity" "weight" "9" "principle"
update_csv_field "$WEIGHTS" "write_what_you_know" "weight" "2" "principle"

RESULT=$(build_weighted_directive "$TMPDIR")
assert_contains "$RESULT" "economy" "build_weighted_directive: includes high-weight principle"
assert_not_contains "$RESULT" "write_what_you_know" "build_weighted_directive: excludes low-weight principle"
```

- [ ] **Step 2: Implement `build_weighted_directive()`**

```bash
# build_weighted_directive(project_dir)
# Read craft-weights.csv, build a weighted summary of craft principles
build_weighted_directive() {
    local project_dir="$1"
    local weights_file="${project_dir}/working/craft-weights.csv"
    [[ -f "$weights_file" ]] || return 0

    local plugin_dir
    plugin_dir=$(get_plugin_dir)
    local craft_file="${plugin_dir}/references/craft-engine.md"

    echo "## Craft Priorities"
    echo ""
    echo "Pay particular attention to these principles:"
    echo ""

    # Read each principle, get effective weight, include if >= 7
    while IFS='|' read -r section principle weight author_weight notes; do
        [[ "$section" == "section" ]] && continue  # skip header
        local eff_w="$weight"
        [[ -n "$author_weight" ]] && eff_w="$author_weight"

        if (( eff_w >= 7 )); then
            echo "- **${principle}** (priority: ${eff_w}/10)"
        fi
    done < "$weights_file"

    echo ""
    echo "Follow all craft principles, but weight your attention toward the priorities above."
}
```

- [ ] **Step 3: Implement `get_scene_overrides()`**

```bash
# get_scene_overrides(scene_id, project_dir)
# Read current cycle's overrides.csv for scene-specific instructions
get_scene_overrides() {
    local scene_id="$1" project_dir="$2"
    local latest="${project_dir}/working/scores/latest/overrides.csv"
    [[ -f "$latest" ]] || return 0

    # Get all overrides for this scene
    awk -F'|' -v id="$scene_id" 'NR>1 && $1 == id { print "- " $3 }' "$latest"
}
```

- [ ] **Step 4: Modify `build_scene_prompt()` to use weighted directives**

In `build_scene_prompt()`, when `craft-weights.csv` exists:
- Replace the `extract_craft_sections 2 3 4 5` call with `build_weighted_directive`
- Append scene overrides from `get_scene_overrides`
- Keep the `extract_craft_sections` fallback when weights file doesn't exist

- [ ] **Step 5: Run tests**

Run: `./tests/run-tests.sh`
Expected: All PASS (test-prompt-builder and all others)

- [ ] **Step 6: Commit**

```bash
git add scripts/lib/prompt-builder.sh tests/test-prompt-builder.sh
git commit -m "Replace raw craft engine injection with weighted directives in prompt-builder"
git push
```

---

## Chunk 5: Plugin Learning, Skill, and Finalization

### Task 8: Add plugin insight submission

**Files:**
- Modify: `scripts/lib/scoring.sh`

- [ ] **Step 1: Implement `submit_plugin_insight()`**

```bash
# submit_plugin_insight(principle, lever, change, avg_improvement, project_title, evidence_csv)
# Creates a GitHub issue on the storyforge repo with structured insight data
submit_plugin_insight() {
    local principle="$1" lever="$2" change="$3" avg_improvement="$4"
    local project_title="$5" evidence="$6"

    # Check if auto-issues are enabled
    local auto_issues
    auto_issues=$(read_yaml_field "auto_issues" 2>/dev/null || echo "true")
    [[ "${STORYFORGE_AUTO_ISSUES:-$auto_issues}" == "false" ]] && return 0

    # Check if gh CLI is available
    has_gh || { log "WARNING: gh CLI not available, skipping plugin insight submission"; return 0; }

    local section
    section=$(get_csv_field "${PROJECT_DIR}/working/craft-weights.csv" "$principle" "section" "principle")

    local body
    body=$(cat <<INSIGHT_EOF
## Plugin Insight: ${section} — ${principle}

**Source project:** ${project_title}
**Average improvement:** ${avg_improvement}

### Change
${change}

### Evidence
${evidence}

### Recommendation
Update \`references/default-craft-weights.csv\` based on this validated pattern.
INSIGHT_EOF
    )

    gh issue create \
        --repo benjaminsnorris/storyforge \
        --title "Plugin Insight: ${principle} — ${lever}" \
        --body "$body" \
        --label "plugin-insight,${section}" \
        2>/dev/null || log "WARNING: Failed to create plugin insight issue"
}
```

- [ ] **Step 2: Wire into `check_validated_patterns()`**

After checking tuning ledger, if a pattern is validated (3+ successes), call `submit_plugin_insight`.

- [ ] **Step 3: Commit**

```bash
git add scripts/lib/scoring.sh
git commit -m "Add plugin insight submission via GitHub issues"
git push
```

### Task 9: Create interactive scoring skill

**Files:**
- Create: `skills/score/SKILL.md`

- [ ] **Step 1: Create the scoring skill**

The skill provides interactive scoring review and author calibration:
- Show scores for a scene, invite author to adjust
- Present diagnosis and proposals for review
- Allow author to set author_weight values
- Write author scores to `scenes/author-scores.csv`

Follow the existing skill pattern from `skills/scenes/SKILL.md`.

- [ ] **Step 2: Commit**

```bash
git add skills/score/SKILL.md
git commit -m "Add interactive scoring skill for author review and calibration"
git push
```

### Task 10: Add author calibration support

**Files:**
- Modify: `scripts/lib/scoring.sh`

- [ ] **Step 1: Implement author score delta tracking**

When `scenes/author-scores.csv` exists alongside system scores, compute deltas and record in tuning ledger.

- [ ] **Step 2: Implement exemplar collection**

After scoring, check for 9+ scores. Extract the strongest passage from those scenes and append to `working/exemplars.csv`.

```bash
# collect_exemplars(scores_dir, project_dir, cycle)
# For any scene scoring 9+ on a principle, extract a short passage
collect_exemplars() {
    local scores_dir="$1" project_dir="$2" cycle="$3"
    local exemplars_file="${project_dir}/working/exemplars.csv"
    local scores_file="${scores_dir}/scene-scores.csv"
    [[ -f "$scores_file" ]] || return 0

    if [[ ! -f "$exemplars_file" ]]; then
        echo "principle|scene_id|score|excerpt|cycle" > "$exemplars_file"
    fi

    # For each cell with score >= 9, extract passage
    # (Implementation uses awk to find high-scoring cells,
    # then reads the scene file to get rationale text as excerpt)
}
```

- [ ] **Step 3: Commit**

```bash
git add scripts/lib/scoring.sh
git commit -m "Add author calibration and exemplar collection"
git push
```

### Task 11: Register scoring library, add score operation to costs, update tests

**Files:**
- Modify: `scripts/lib/common.sh` — source scoring.sh
- Modify: `scripts/lib/costs.sh` — add `score` case to estimate_cost
- Modify: `tests/run-tests.sh` — source scoring.sh

- [ ] **Step 1: Source scoring.sh in common.sh and run-tests.sh**

Add `source "${SCRIPT_DIR}/scoring.sh"` in common.sh after costs.sh.
Add `source "${PLUGIN_DIR}/scripts/lib/scoring.sh"` in run-tests.sh.

- [ ] **Step 2: Add `score` case to `estimate_cost` in costs.sh**

```bash
score) est_output=$(awk "BEGIN { printf \"%d\", $scope_count * 500 }") ;;
```

- [ ] **Step 3: Run full test suite**

Run: `./tests/run-tests.sh`
Expected: All tests pass

- [ ] **Step 4: Commit**

```bash
git add scripts/lib/common.sh scripts/lib/costs.sh tests/run-tests.sh
git commit -m "Register scoring library and add score operation to cost tracking"
git push
```

### Task 12: Version bump

**Files:**
- Modify: `.claude-plugin/plugin.json`

- [ ] **Step 1: Bump version to 0.17.0**

- [ ] **Step 2: Commit**

```bash
git add .claude-plugin/plugin.json
git commit -m "Bump version to 0.17.0 for principled scoring system (v0.17.0)"
git push
```
