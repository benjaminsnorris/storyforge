# CSV Data Format and Cost Tracking Design

**Date:** 2026-03-12
**Branch:** feature/scene-metadata
**Status:** Draft

## Problem

Storyforge's structured data is stored in YAML files and markdown frontmatter. Every time a script invokes Claude, it reads these files into the prompt — repeating field names for every entry. A 100-scene YAML index wastes ~3,000–5,000 tokens on redundant field labels per read. Across drafting, evaluation, and revision, this adds up to significant unnecessary cost.

Additionally, there is no cost tracking. Scripts invoke Claude dozens of times per operation with no visibility into token usage, actual cost, or cost forecasting. If Storyforge becomes a commercial product, per-operation cost data is essential for pricing.

## Goals

1. Reduce token usage for structured data by eliminating repeated field names.
2. Track token usage and cost per Claude invocation with cumulative reporting.
3. Forecast costs before expensive autonomous operations.
4. Migrate four existing book projects to the new format.
5. Design the data layer to support future principled scoring and adaptive prompt tuning systems.

## Non-Goals

- Implementing the principled scoring system (future work).
- Implementing adaptive prompt tuning (future work).
- Changing prose reference documents (character bible, world bible, voice guide, etc.).
- Changing the storyforge.yaml project configuration format.

## Design

### File Format Convention

All structured data files use **pipe-delimited CSV**:

- **Extension:** `.csv`
- **Field delimiter:** single pipe `|`
- **Array delimiter within fields:** double pipe `||`
- **First row:** header with field names
- **No quoting** — pipes and double-pipes do not appear in natural prose
- **No trailing delimiters**
- **Encoding:** UTF-8
- **Newlines:** LF (Unix-style)
- **Empty fields:** zero characters between delimiters (e.g., `value1||value3`)

Example:

```
id|title|pov|characters|threads
the-finest-cartographer|The Finest Cartographer|Dorren Hayle|Dorren Hayle||Tessa Merrin||Pell|institutional failure||chosen blindness||the anomaly
```

### Scene Files

Scene files become pure prose markdown with **no frontmatter**. The filename is the scene identity:

```
scenes/the-finest-cartographer.md
scenes/the-footnote.md
scenes/the-weight-of-the-rim.md
```

The filename (without `.md`) is the scene ID. This ID is the key that links to all CSV metadata. Scene files contain only prose — no YAML block, no metadata.

### Scene Metadata: Two CSV Files

Organized by access pattern — scripts that only need structural data do not pay for loading creative intent.

#### `scenes/metadata.csv` — Structural Metadata

Read by all scripts (drafting, evaluation, revision, assembly, review).

| Column | Type | Description |
|--------|------|-------------|
| `id` | string | Scene ID (matches filename) |
| `seq` | integer | Ordering position (reorderable without renaming files) |
| `title` | string | Scene title |
| `pov` | string | Point-of-view character |
| `setting` | string | Physical location |
| `part` | integer | Part/act number |
| `type` | string | Scene type (character, plot, world, action, transition, confrontation) |
| `timeline_day` | integer | Day number in story timeline |
| `time_of_day` | string | Temporal marker (morning, afternoon, evening, night) |
| `status` | string | Lifecycle status (planned, drafted, revised, cut, merged) |
| `word_count` | integer | Actual word count |
| `target_words` | integer | Target word count |

Per-project custom fields (currently `scene_extensions` in storyforge.yaml) become additional columns appended after the standard fields.

Example:

```
id|seq|title|pov|setting|part|type|timeline_day|time_of_day|status|word_count|target_words
the-finest-cartographer|1|The Finest Cartographer|Dorren Hayle|Pressure Cartography Office|1|character|1|morning|revised|952|1200
the-footnote|2|The Footnote|Tessa Merrin|Pressure Cartography Office|1|confrontation|2|morning|revised|780|800
```

#### `scenes/intent.csv` — Creative Intent

Read during drafting, revision, scene design, and revision planning.

| Column | Type | Description |
|--------|------|-------------|
| `id` | string | Scene ID (matches filename) |
| `function` | string | Why this scene exists — specific and testable |
| `emotional_arc` | string | How emotion shifts within the scene |
| `characters` | array | All characters present or referenced (`||`-separated) |
| `threads` | array | Story threads touched (`||`-separated) |
| `motifs` | array | Recurring imagery/language patterns (`||`-separated) |
| `notes` | string | Directorial or craft notes |

Example:

```
id|function|emotional_arc|characters|threads|motifs|notes
the-finest-cartographer|Establishes Dorren as institutional gatekeeper; introduces Junction 14 assignment|Controlled competence giving way to buried unease|Dorren Hayle||Tessa Merrin||Pell||Calla||Nessa Vyre|institutional failure||chosen blindness||the anomaly||maps and territory|maps/cartography||governance-as-weight||hands||blindness/seeing|
```

#### Future: `scenes/scores.csv` — Principle Scores

Not implemented in this design. Planned for the principled scoring system. Will use the same `id` key with one column per craft principle, holding numeric scores (1-10 or 1-100).

### Reference Data CSV Files

#### `reference/chapter-map.csv`

Maps scenes to chapters for production assembly.

| Column | Type | Description |
|--------|------|-------------|
| `seq` | integer | Chapter order |
| `title` | string | Chapter title |
| `heading` | string | Heading style (e.g., "Chapter 1", "Part One", custom) |
| `part` | integer | Part number |
| `scenes` | array | Scene IDs in order (`||`-separated) |

#### `reference/timeline.csv`

Chronological events for continuity.

| Column | Type | Description |
|--------|------|-------------|
| `day` | integer/string | Timeline position (day number or date) |
| `time` | string | Time of day or specific time |
| `event` | string | What happens |
| `scenes` | array | Related scene IDs (`||`-separated) |
| `notes` | string | Continuity notes |

#### `reference/key-decisions.csv`

Decisions affecting the story, recorded by the system.

| Column | Type | Description |
|--------|------|-------------|
| `id` | string | Decision ID (e.g., `kd001`) |
| `date` | string | ISO date |
| `decision` | string | What was decided (one sentence) |
| `affects` | array | Scene IDs affected (`||`-separated) |
| `rationale` | string | Why (one sentence) |
| `active` | boolean | Whether the decision is still in effect |

### Working Data CSV Files

#### `working/costs/ledger.csv`

Append-only log of every Claude invocation. One row per invocation.

| Column | Type | Description |
|--------|------|-------------|
| `timestamp` | string | ISO 8601 timestamp |
| `operation` | string | Operation type: draft, evaluate, synthesize, revise, assemble, review, heal |
| `target` | string | What was operated on (scene ID, evaluator name, pass name) |
| `model` | string | Model used (e.g., `claude-opus-4-6`, `claude-sonnet-4-6`) |
| `input_tokens` | integer | Input tokens consumed |
| `output_tokens` | integer | Output tokens generated |
| `cache_read` | integer | Tokens read from cache |
| `cache_create` | integer | Tokens written to cache |
| `cost_usd` | decimal | Calculated cost in USD |
| `duration_s` | integer | Wall-clock seconds |

#### `working/costs/summary.csv`

Regenerated from ledger on demand or at end of each operation.

| Column | Type | Description |
|--------|------|-------------|
| `operation` | string | Operation type |
| `invocations` | integer | Number of Claude invocations |
| `total_input` | integer | Total input tokens |
| `total_output` | integer | Total output tokens |
| `total_cache_read` | integer | Total cache reads |
| `total_cost_usd` | decimal | Total cost in USD |

#### `working/evaluations/{eval-dir}/findings.csv`

Evaluation findings from the panel.

| Column | Type | Description |
|--------|------|-------------|
| `id` | string | Finding ID (e.g., `f001`) |
| `evaluator` | string | Which evaluator raised it |
| `severity` | string | critical, major, minor, suggestion |
| `category` | string | Finding category (pacing, dialogue, continuity, etc.) |
| `scenes` | array | Affected scene IDs (`||`-separated) |
| `summary` | string | One-line description |
| `recommendation` | string | Suggested fix (one sentence) |
| `status` | string | open, addressed, dismissed |

#### `working/evaluations/{eval-dir}/strengths.csv`

Same structure without severity:

| Column | Type | Description |
|--------|------|-------------|
| `id` | string | Strength ID |
| `evaluator` | string | Which evaluator flagged it |
| `category` | string | Category |
| `scenes` | array | Example scene IDs (`||`-separated) |
| `summary` | string | One-line description |

#### `working/evaluations/{eval-dir}/false-positives.csv`

| Column | Type | Description |
|--------|------|-------------|
| `id` | string | ID |
| `source` | string | Original evaluator |
| `claim` | string | What the evaluator flagged |
| `reality` | string | Why it's a false positive |
| `key_decision` | string | Related key decision ID if applicable |

#### `working/plans/revision-plan.csv`

| Column | Type | Description |
|--------|------|-------------|
| `pass` | integer | Pass number (execution order) |
| `name` | string | Pass name (e.g., "strengthen-dialogue") |
| `purpose` | string | What this pass aims to fix |
| `scope` | string | full, act, or scenes |
| `targets` | array | Target scene IDs if scope is scenes (`||`-separated) |
| `guidance` | string | Concise revision guidance |
| `protection` | array | What NOT to change (`||`-separated) |
| `findings` | array | Finding IDs this pass addresses (`||`-separated) |
| `status` | string | pending, in-progress, complete |
| `model_tier` | string | opus or sonnet |

#### `working/pipeline.csv`

| Column | Type | Description |
|--------|------|-------------|
| `cycle` | integer | Cycle number |
| `started` | string | ISO date |
| `status` | string | active, complete |
| `evaluation` | string | Evaluation directory name |
| `plan` | string | Revision plan filename |
| `summary` | string | One-line cycle summary |

### Files That Stay as Markdown

These are prose documents where the content is narrative text, not structured data:

- `reference/character-bible.md`
- `reference/world-bible.md`
- `reference/voice-guide.md`
- `reference/story-architecture.md`
- `reference/continuity-tracker.md`
- `reference/scene-log.md`
- `reference/resolved-threads.md`
- `storyforge.yaml` (project configuration — hierarchical, not tabular)

## Cost Tracking System

### Token Capture

After every Claude invocation in autonomous scripts, the `log_usage()` function:

1. Parses the stream-json output for the final `message_delta` event containing `usage` data.
2. Calculates cost using model-specific pricing constants stored in `common.sh`.
3. Appends one row to `working/costs/ledger.csv`.
4. Creates the `working/costs/` directory and CSV header on first use.

### Pricing Constants

Stored in `common.sh`, updatable as pricing changes:

```bash
# Pricing per million tokens (USD)
PRICING_OPUS_INPUT=15.00
PRICING_OPUS_OUTPUT=75.00
PRICING_OPUS_CACHE_READ=1.50
PRICING_OPUS_CACHE_CREATE=18.75
PRICING_SONNET_INPUT=3.00
PRICING_SONNET_OUTPUT=15.00
PRICING_SONNET_CACHE_READ=0.30
PRICING_SONNET_CACHE_CREATE=3.75
```

Override via environment variables: `STORYFORGE_PRICING_OPUS_INPUT`, etc.

### Cost Forecasting

Before each autonomous operation, scripts estimate cost:

1. Count scenes/evaluators/passes in scope.
2. Estimate input tokens from: word counts in `metadata.csv` (prose ≈ 1.3 tokens/word), reference document sizes, prompt template overhead.
3. Estimate output tokens from historical averages in `ledger.csv` (if available) or defaults.
4. Calculate estimated cost using pricing constants and the model that will be used.
5. Print forecast: `"This evaluation will process ~45,000 words across 6 evaluators. Estimated cost: ~$2.50"`

### Cost Threshold

- Environment variable: `STORYFORGE_COST_THRESHOLD` (default: `10` USD)
- If estimated cost exceeds threshold, prompt for confirmation **before the operation begins**.
- Once confirmed, the operation runs to completion without interruption.
- If under threshold, proceed automatically.
- Set to `0` to always confirm. Set to a high value to never confirm.

### End-of-Operation Summary

After every autonomous operation completes, print:

```
Evaluation complete. 8 invocations.
  Input:  142,300 tokens
  Output:  38,200 tokens
  Cache:   45,000 tokens read
  Cost:    $2.47 (estimated: $2.50)
```

### Summary Regeneration

`working/costs/summary.csv` is regenerated:
- At the end of each autonomous operation
- On demand via a future `storyforge costs` command
- By aggregating all rows in `ledger.csv` grouped by operation type

## Migration

### `storyforge-migrate` Script

A new script at `scripts/storyforge-migrate` that converts existing projects to the CSV format.

#### Behavior

1. **Dry-run by default** — prints what it would do without making changes. Pass `--execute` to perform the migration.
2. **Backs up originals** — copies `scene-index.yaml`, scene files, and other affected files to `working/backups/pre-migration/`.
3. **Reads from wherever metadata lives:**
   - YAML scene index → extract fields
   - Scene file frontmatter → extract fields
   - When both exist for the same field, prefer the richer source (more data wins)
4. **Outputs CSV files** — writes `metadata.csv`, `intent.csv`, and other CSV files.
5. **Strips frontmatter** from scene files, leaving pure prose.
6. **Renames scene files** to slug-based IDs when they use numeric names:
   - `001.md` → derives slug from title in metadata (e.g., `claires-cold.md`)
   - `ch01-sc01.md` → derives slug from title (e.g., `the-finest-cartographer.md`)
   - Already slug-based files (like Rend's `s01-morning-hold.md`) → rename to just the slug portion
7. **Generates `seq` column** from the original file/index ordering.
8. **Normalizes field names** — maps known aliases:
   - `location` → `setting`
   - `words` → `word_count`
   - `word_target` → `target_words`
   - `time` → `time_of_day`
   - `threads_planted`, `threads_advanced`, `threads_resolved` → merged into `threads` array
9. **Preserves unrecognized fields** — custom fields (like Rend's `tension`) become extra columns in `metadata.csv`.

#### Per-Book Migration

| Book | Scene count | Index source | Frontmatter source | File rename |
|------|------------|-------------|-------------------|-------------|
| Governor | 97 | Lean — supplement from frontmatter | Rich — primary source | ch01-sc01 → slug |
| Night-Watch | ~100 | Rich — primary source | Strip minimal frontmatter | 001.md → slug |
| Meridian Line | ~50 | Rich — primary source | Strip minimal frontmatter | 001.md → slug |
| Rend | ~40 | Rich — primary source | Strip minimal frontmatter | Normalize slug format |

#### Additional File Migration

The script also converts (when present):
- `reference/chapter-map.yaml` → `reference/chapter-map.csv`
- `reference/timeline.md` (markdown table) → `reference/timeline.csv`
- `reference/key-decisions.md` → `reference/key-decisions.csv`
- `working/evaluations/*/findings.yaml` → `findings.csv`, `strengths.csv`, `false-positives.csv`
- `working/plans/revision-plan-*.yaml` → `working/plans/revision-plan.csv`
- `working/pipeline.yaml` → `working/pipeline.csv`

#### Flags

- `--dry-run` (default) — show what would change without changing anything
- `--execute` — perform the migration
- `--project-dir PATH` — target project directory (default: current directory)
- `--skip-rename` — convert metadata but don't rename scene files
- `--skip-backup` — skip creating backups (not recommended)

## Script Integration

### New Functions in `common.sh`

**CSV Reading:**
- `read_csv(file)` — reads a pipe-delimited CSV, returns rows as associative arrays or field-indexed values
- `get_csv_field(file, id, field)` — look up a single field for a given ID
- `get_csv_row(file, id)` — return all fields for a given ID
- `get_csv_column(file, field)` — return all values for a given field

**Cost Tracking:**
- `log_usage(log_file, operation, target, model)` — parse stream-json log file for usage data, calculate cost, append to ledger.csv
- `estimate_cost(operation, scope_count, avg_words, model)` — forecast cost for an operation
- `check_cost_threshold(estimated_cost)` — prompt for confirmation if over threshold, return 0 to proceed or 1 to abort
- `print_cost_summary(operation)` — print end-of-operation cost report from ledger entries

**Pricing:**
- `get_model_pricing(model, token_type)` — return per-million-token price for a model and token type (input, output, cache_read, cache_create)

### Changes to Existing Scripts

**`scripts/lib/prompt-builder.sh`:**
- `get_scene_metadata()` reads from `metadata.csv` instead of scene-index.yaml
- `get_scene_intent()` reads from `intent.csv` when creative context is needed
- `build_scene_prompt()` updated to use CSV readers

**`scripts/storyforge-write`:**
- Add cost forecast before starting
- Call `log_usage()` after each scene invocation
- Update `word_count` and `status` in `metadata.csv` after drafting
- Print cost summary at end

**`scripts/storyforge-evaluate`:**
- Add cost forecast (this is typically the most expensive operation)
- Call `log_usage()` after each evaluator and synthesis invocation
- Write findings to CSV instead of YAML
- Print cost summary at end

**`scripts/storyforge-revise`:**
- Add cost forecast per revision cycle
- Call `log_usage()` after each pass
- Update `word_count` in `metadata.csv` after revision
- Read revision plan from CSV instead of YAML
- Print cost summary at end

**`scripts/storyforge-assemble`:**
- Read chapter map from CSV instead of YAML
- Call `log_usage()` for assembly invocations
- Print cost summary at end

**Skills (`scenes`, `plan-revision`, `review`, etc.):**
- `scenes` skill reads/writes CSV instead of YAML when designing or modifying scenes
- `plan-revision` skill writes revision-plan.csv instead of YAML
- `review` skill reads findings from CSV
- No cost tracking in interactive skills (Claude Code manages its own usage)

### Backward Compatibility

During the transition period, scripts check for CSV files first. If not found, they fall back to reading YAML. This allows gradual migration without breaking unmigrated projects. A deprecation warning is printed when the YAML fallback is used.

## Token Savings Estimate

For a 100-scene project:

| File | YAML tokens (est.) | CSV tokens (est.) | Savings |
|------|-------------------|--------------------|---------|
| Scene metadata (structural) | ~8,000 | ~3,500 | ~4,500 |
| Scene intent (creative) | ~6,000 | ~3,000 | ~3,000 |
| Chapter map | ~2,000 | ~800 | ~1,200 |
| Findings (30 entries) | ~3,000 | ~1,200 | ~1,800 |
| Revision plan (5 passes) | ~1,500 | ~600 | ~900 |

**Per-read savings: ~11,400 tokens.** Across a full evaluate-revise cycle that reads these files multiple times, estimated savings of **30,000–50,000 tokens per cycle**.

## Future Extensibility

This design explicitly supports the planned principled scoring and adaptive prompt tuning systems:

- **`scenes/scores.csv`** — one row per scene, one column per craft principle, numeric scores. Same `id` key as metadata.csv and intent.csv.
- **Author calibration** — author score overrides and priority weights fit the same CSV format.
- **Prompt tuning records** — `working/tuning.csv` could track principle weightings and prompt adjustments over time.
- **Cost tracking** — the ledger already captures per-invocation data, so scoring passes produce more ledger rows automatically.
- **Cross-project analysis** — consistent CSV format across all books enables aggregate cost and quality analysis.
