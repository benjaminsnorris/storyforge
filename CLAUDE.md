# Storyforge Plugin Development

## Git Rules — MANDATORY
- **ALWAYS commit and push after every change.** No exceptions.
- Never tell the user something is "done" without having committed and pushed.
- If you make multiple related changes, commit them in logical groups — but do it immediately, not at the end of the conversation.
- Every commit must be pushed before moving on to the next task.
- Commit any uncommitted files before creating branches or PRs.

## Version File
- `.claude-plugin/plugin.json` — **ALWAYS bump `version` on every release commit.**
- Minor version (0.X.0) for new features. Patch version (0.0.X) for fixes.

## Script Standards

All autonomous scripts live in `scripts/` and follow these conventions:

### Shell Basics
- `set -eo pipefail` at the top of every script. **NOT `-u`** (breaks compat).
- Source `scripts/lib/common.sh` first — it provides all shared libraries.
- BSD sed compatibility required: `sed -i ''` (not `sed -i`).
- **No `declare -A`** — bash 3 doesn't support associative arrays. Use `case` statements or functions instead.
- **No `local` outside functions** — `local` is only valid inside functions. Top-level code in case branches or script body must use plain variable assignment.
- Make scripts executable: `chmod +x scripts/storyforge-*`

### Shared Functions — USE THEM
Before writing new code, check if a shared function already exists. Duplicating logic causes bugs (see: `extract_claude_response` parsing bug).

**common.sh:**
- `detect_project_root` — sets `$PROJECT_DIR`
- `extract_claude_response(log_file)` — **THE** way to extract text from Claude stream-json logs. Never write your own parsing.
- `select_model(task_type)` — returns the right model for the task (opus for creative, sonnet for analytical)
- `get_coaching_level` — returns full/coach/strict
- `log(message)` — timestamped logging
- `read_yaml_field(field)` — read from storyforge.yaml
- `create_branch(type, project_dir)` — creates a `storyforge/{type}-*` branch
- `ensure_branch_pushed(project_dir)` — push branch to remote
- `create_draft_pr(title, body, project_dir, label)` — create a draft PR with task checklist
- `update_pr_task(label, project_dir)` — check off a task in the PR
- `register_child_pid($!)` / `unregister_child_pid($pid)` — track background processes for interrupt handling
- `begin_healing_zone(desc)` / `end_healing_zone` — error recovery around Claude invocations

**csv.sh:**
- `get_csv_field(file, id, field, [key_column])` — read one cell
- `get_csv_row(file, id, [key_column])` — read one row
- `get_csv_column(file, field)` — read one column
- `list_csv_ids(file)` — list all IDs in order
- `update_csv_field(file, id, field, value, [key_column])` — update one cell (atomic write)
- `append_csv_row(file, row)` — append a row

**scene-filter.sh:**
- `build_scene_list(metadata_csv)` — populate ALL_SCENE_IDS sorted by seq, excluding cut
- `apply_scene_filter(metadata_csv, mode, [value], [value2])` — filter into FILTERED_IDS
  - Modes: `all`, `scenes` (comma-separated), `single`, `act` (CSV part column), `from_seq` (N or N-M range), `range` (start_id, end_id)

**aliases.sh:**
- `load_alias_map(csv_file)` — build alias lookup temp file from any CSV with name|aliases columns, returns path (caller must cleanup)
- `normalize_aliases(map_file, semicolon_string)` — resolve aliases in semicolon-separated string, case-insensitive, deduplicates
- `load_character_aliases` / `normalize_characters` — backwards-compatible wrappers for the generic functions

**costs.sh:**
- `log_usage(log_file, operation, target, model, [ledger])` — parse stream-json for usage, calculate cost, append to ledger
- `estimate_cost(operation, count, avg_words, model)` — forecast cost
- `check_cost_threshold(estimated)` — prompt if over threshold
- `print_cost_summary(operation, [ledger])` — print end-of-operation totals

**scoring.sh:**
- `init_craft_weights(project_dir, plugin_dir)` — ensure weights file exists
- `get_effective_weight(weights_file, principle)` — author_weight if set, else weight
- `parse_score_output(log_file, score_target, rationale_target)` — extract score CSVs
- `merge_score_files(target, source)` — merge CSV files (append rows or join columns)
- `generate_diagnosis(scores_dir, prev_dir, weights_file)` — analyze scores
- `generate_proposals(scores_dir, weights_file)` — propose improvements

### Script Structure Pattern
Every autonomous script should:
1. Parse arguments (`--dry-run`, `--scenes`, `--act`, `--parallel`, `-h`)
2. `detect_project_root`
3. Read project info (`PROJECT_TITLE` from storyforge.yaml)
4. Create branch: `create_branch "type" "$PROJECT_DIR"`
5. Commit any changed files, then `ensure_branch_pushed`
6. Cost forecast: `estimate_cost` + `check_cost_threshold`
7. Create draft PR: `create_draft_pr` with task checklist
8. Main work loop (parallel batches if applicable)
9. Update PR tasks as phases complete
10. Cost summary: `print_cost_summary`
11. Commit and push results

### Parallel Execution Pattern
```bash
PARALLEL=${STORYFORGE_THING_PARALLEL:-6}
batch_start=0
while (( batch_start < TOTAL )); do
    batch_pids=()
    batch_ids=()
    batch_end=$(( batch_start + PARALLEL ))
    (( batch_end > TOTAL )) && batch_end=$TOTAL

    for (( i=batch_start; i<batch_end; i++ )); do
        id="${IDS[$i]}"
        batch_ids+=("$id")
        (
            # Worker subshell — writes results to temp files
            # Use extract_claude_response for parsing
            # Write status to ${DIR}/.status-${id}
        ) &
        batch_pids+=($!)
        register_child_pid $!
    done

    for pid in "${batch_pids[@]}"; do
        wait "$pid" 2>/dev/null || true
        unregister_child_pid "$pid" 2>/dev/null || true
    done

    # Merge results from batch (sequential, no concurrent writes)
    for id in "${batch_ids[@]}"; do
        # Read temp files, update CSVs
    done
    batch_start=$batch_end
done
```

### Claude Invocation — Autonomous (Direct API)
```bash
_SF_INVOCATION_START=$(date +%s)
export _SF_INVOCATION_START

begin_healing_zone "description"

invoke_anthropic_api "$prompt" "$MODEL" "$log_file" 4096

end_healing_zone

response=$(extract_api_response "$log_file")
log_api_usage "$log_file" "operation" "$target" "$MODEL"
```

### Claude Invocation — Autonomous (Batch API)
```bash
# Build JSONL — one request per line
for id in "${IDS[@]}"; do
    prompt=$(build_prompt "$id")
    jq -nc --arg id "$id" --arg model "$MODEL" --arg prompt "$prompt" '{
        custom_id: $id,
        params: { model: $model, max_tokens: 4096, messages: [{role: "user", content: $prompt}] }
    }' >> "$BATCH_FILE"
done

BATCH_ID=$(submit_batch "$BATCH_FILE")
poll_batch "$BATCH_ID"
download_batch_results "$BATCH_ID" "$OUTPUT_DIR" "$LOG_DIR"

# Process results: ${id}.txt (text), ${id}.json (usage), .status-${id} (ok/fail)
```

### Claude Invocation — Interactive (Claude Code)
```bash
claude -p "$prompt" \
    --model "$MODEL" \
    --dangerously-skip-permissions \
    --output-format stream-json \
    --verbose \
    > "$log_file" 2>&1
response=$(extract_claude_response "$log_file")
log_usage "$log_file" "operation" "$target" "$MODEL"
```

## Skill Standards

Interactive skills live in `skills/{name}/SKILL.md`.

### Frontmatter
```yaml
---
name: skill-name
description: One-line description. Used by Claude Code to decide when to invoke.
---
```

### Required Sections
1. **Locating the Storyforge Plugin** — resolve plugin root path
2. **Read Project State** — list which files to read
3. **Determine Mode** — what to do based on user's request
4. **Commit After Every Deliverable** — `git add -A && git commit -m "..." && git push`
5. **Coaching Level Behavior** — adapt for full/coach/strict

### Script Delegation Pattern
When a skill delegates to an autonomous script, always offer two options:

> **Option A: Run it here**
> I'll launch the script in this conversation. [If the script invokes Claude: "This requires unsetting CLAUDECODE."]
>
> **Option B: Run it yourself**
> Copy this command and run it in a separate terminal:
> ```bash
> cd [project_dir] && [plugin_path]/scripts/storyforge-thing [flags]
> ```

Wait for the author's choice. If Option B, provide the full command and end.

### Coaching Level Adaptation
- **full:** Proactive. Recommend actions, offer to run, explain implications. Creative partner.
- **coach:** Guided. Present options as questions, help the author think through decisions. Don't do creative work.
- **strict:** Passive. Report data, provide commands, don't interpret or recommend. Author makes all decisions.

## CSV Data Format

All structured data uses pipe-delimited CSV:
- **Field delimiter:** `|`
- **Array delimiter within fields:** `;`
- **First row:** header with field names
- **No quoting** — pipes don't appear in natural prose
- **Semicolons in content:** use comma instead or escape as `\;`
- **Empty fields:** zero characters between delimiters

### Key CSV Files

**Elaboration pipeline (new projects):**
- `reference/scenes.csv` — structural identity (id, seq, title, part, pov, location, timeline_day, time_of_day, duration, type, status, word_count, target_words)
- `reference/scene-intent.csv` — narrative dynamics (id, function, scene_type, emotional_arc, value_at_stake, value_shift, turning_point, threads, characters, on_stage, mice_threads)
- `reference/scene-briefs.csv` — drafting contracts (id, goal, conflict, outcome, crisis, decision, knowledge_in, knowledge_out, key_actions, key_dialogue, emotions, motifs, continuity_deps, has_overflow)

**Legacy (existing projects):**
- `reference/scene-metadata.csv` — structural metadata (id, seq, title, pov, location, part, type, etc.)
- `reference/scene-intent.csv` — creative intent (id, function, emotional_arc, characters, threads, motifs)

**Shared:**
- `working/craft-weights.csv` — craft principle weights (keyed by `principle` column, not `id`)
- `working/costs/ledger.csv` — per-invocation cost tracking
- `reference/chapter-map.csv` — chapter-to-scene mapping

### Scene Files
- Pure prose markdown. **No YAML frontmatter.**
- Filename is the scene ID: `scenes/the-finest-cartographer.md` → id is `the-finest-cartographer`
- Word count, status, and all metadata live in the CSV files, not in the scene file.

## Testing

Tests live in `tests/test-*.sh`. Auto-discovered by `tests/run-tests.sh`.

### Assertion Functions
- `assert_equals "expected" "actual" "label"`
- `assert_contains "$string" "substring" "label"`
- `assert_not_contains "$string" "substring" "label"`
- `assert_empty "$var" "label"`
- `assert_not_empty "$var" "label"`
- `assert_file_exists "/path" "label"`
- `assert_matches "$string" "regex" "label"`
- `assert_exit_code "0" "$?" "label"`

### Test Pattern
```bash
#!/bin/bash
# test-thing.sh — Tests for thing

# Tests use $FIXTURE_DIR, $PROJECT_DIR, $PLUGIN_DIR, $TMPDIR
# Libraries are already sourced by run-tests.sh

RESULT=$(some_function "input")
assert_equals "expected" "$RESULT" "function: does the thing"
```

Run: `./tests/run-tests.sh` (all suites) or `./tests/run-tests.sh tests/test-thing.sh` (one suite).

## Architecture Quick Reference

- **Scripts** (`scripts/storyforge-*`) — autonomous execution. Invoke Claude, create branches/PRs, commit.
- **Skills** (`skills/*/SKILL.md`) — interactive Claude Code sessions. Guide the author, delegate to scripts.
- **Libraries** (`scripts/lib/*.sh`) — shared bash functions. Sourced by common.sh.
- **Python modules** (`scripts/lib/python/storyforge/`) — scene data helpers, extraction, scoring, prompts, visualization.
- **Prompts** (`scripts/prompts/`) — prompt templates for evaluators and scoring.
- **References** (`references/`) — craft engine, scoring rubrics, schemas, default weights.
- **Templates** (`templates/`) — project scaffolding for init.
- **Tests** (`tests/`) — assertion-based bash tests.
- **Docs** (`docs/`) — GitHub Pages site with visualization pages.

### Scripts

| Script | Purpose |
|--------|---------|
| `storyforge-write` | Draft scenes (reads briefs if available, supports parallel wave drafting) |
| `storyforge-evaluate` | Multi-agent evaluation panel (6 evaluators + synthesis) |
| `storyforge-revise` | Execute revision passes from a plan |
| `storyforge-score` | Craft scoring (25 principles + fidelity scoring against briefs) |
| `storyforge-elaborate` | Run elaboration stages (spine/architecture/map/briefs) |
| `storyforge-extract` | Extract structural data from existing prose (reverse elaboration) |
| `storyforge-polish` | Targeted prose polish on low-scoring scenes |
| `storyforge-validate` | Structural validation against scene CSVs |
| `storyforge-enrich` | Metadata enrichment from prose |
| `storyforge-assemble` | Chapter assembly + epub/PDF/HTML generation |
| `storyforge-visualize` | Multi-page manuscript dashboard |
| `storyforge-timeline` | Timeline construction |
| `storyforge-cleanup` | Project structure cleanup |

### Skills

| Skill | Purpose |
|-------|---------|
| `forge` | Hub — reads project state, recommends next action, routes to skills |
| `elaborate` | All creative development: spine → architecture → voice → map → briefs. Character, world, story architecture. |
| `extract` | Reverse elaboration — extract structural data from existing prose |
| `revise` | Plan + execute revision (upstream CSV fixes + prose polish). `--polish` for craft-only. |
| `score` | Craft + fidelity scoring |
| `publish` | Assemble web book + generate dashboard + push to bookshelf |
| `produce` | Epub, PDF, print formats |
| `init` | New project initialization |
| `cover` | Cover design |
| `title` | Title development |
| `press-kit` | Marketing materials |

### Elaboration Pipeline

New projects use the elaboration pipeline: progressive structural development before drafting.

```
Seed → Spine → Architecture → Scene Map → Briefs → Validate → Draft → Evaluate → Polish → Produce
```

Each stage populates columns in the three-file CSV model. Validation gates between stages catch structural issues before they become prose problems. Evaluation findings route back to the appropriate CSV (brief/intent/structural) for upstream fixes rather than prose revision.

Key principles:
- **Validate cheap, fix cheap** — catch problems as CSV edits, not prose rewrites
- **Parallel drafting** — scenes with no `continuity_deps` can be drafted simultaneously
- **Evaluation feeds upstream** — findings map to `fix_location` (brief/intent/structural/craft)
- **Coaching levels are roles** — full=creative partner, coach=dramaturg, strict=continuity editor

### Python Modules

| Module | Purpose |
|--------|---------|
| `elaborate.py` | Scene data helpers (get/set/query), validation engine, wave planner, structural scoring |
| `extract.py` | Extraction prompt builders, response parsers, cleanup, expansion analysis |
| `prompts.py` | Scene drafting prompt builders (legacy + brief-aware) |
| `prompts_elaborate.py` | Elaboration stage prompt builders |
| `scoring.py` | Score parsing, diagnosis, proposals, fidelity scoring |
| `visualize.py` | Dashboard data loading |
| `enrich.py` | Metadata enrichment |
| `assembly.py` | Chapter assembly |
| `parsing.py` | Scene content extraction |
| `api.py` | Anthropic API helpers |
| `costs.py` | Cost calculation |
| `project.py` | Project state management |

## Commit Message Prefixes
Use domain-specific prefixes:
- `Draft scene:` / `Develop:` / `Voice:` / `Evaluate:` / `Revision:` / `Produce:` / `Review:` / `Title:` / `Press kit:` / `Cover:` — for book project work
- `Elaborate:` — elaboration pipeline stages
- `Extract:` — reverse elaboration from prose
- `Score:` — scoring cycles
- `Polish:` — prose polish passes
- `Enrich:` — metadata enrichment
- `Visualize:` — dashboard generation
- `Add` / `Update` / `Fix` / `Remove` — for plugin development
- `Bump version to X.Y.Z` — version bumps
