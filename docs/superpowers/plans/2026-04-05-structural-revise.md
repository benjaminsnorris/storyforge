# Structural Revise Mode Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add `--structural` flag to `storyforge-revise` that reads structural proposals, auto-generates a CSV-only revision plan, executes fixes via Claude, skips re-drafting, and re-validates scores.

**Architecture:** Mirrors the existing `--polish` pattern. A new `STRUCTURAL_MODE` flag gates plan generation (from `structural-proposals.csv`), adds `registry` to the upstream fix_location handling, and skips the re-draft block. After all passes, re-runs structural scoring and prints a before/after delta.

**Tech Stack:** Bash (storyforge-revise), Python (structural.py for re-scoring), existing CSV libraries.

---

### Task 1: Add `--structural` flag and argument parsing

**Files:**
- Modify: `scripts/storyforge-revise:69-123` (argument parsing block)

- [ ] **Step 1: Write the test**

Add to `tests/test-dry-run.sh` (which tests argument parsing and dry-run behavior):

```bash
# ============================================================================
# --structural flag: generates plan from structural proposals
# ============================================================================

# Set up structural proposals fixture
mkdir -p "${PROJECT_DIR}/working/scores"
cat > "${PROJECT_DIR}/working/scores/structural-proposals.csv" << 'PROPOSALS'
id|dimension|fix_location|target|change|rationale|status
sp001|arc_completeness|intent|scene-a|vary value_at_stake|scene-a: only 1 value at stake, score 0.80|pending
sp002|thematic_concentration|registry|global|consolidate values.csv|Thematic fragmentation: 40 distinct values, score 0.30|pending
PROPOSALS

RESULT=$("${PLUGIN_DIR}/scripts/storyforge-revise" --structural --dry-run 2>&1 || true)
assert_contains "$RESULT" "Structural mode" "structural: log message confirms structural mode"
assert_contains "$RESULT" "arc_completeness" "structural: plan includes arc_completeness pass"
assert_contains "$RESULT" "thematic_concentration" "structural: plan includes thematic_concentration pass"

# Verify revision-plan.csv was generated
assert_file_exists "${PROJECT_DIR}/working/plans/revision-plan.csv" "structural: revision-plan.csv created"
PLAN_CONTENT=$(cat "${PROJECT_DIR}/working/plans/revision-plan.csv")
assert_contains "$PLAN_CONTENT" "intent" "structural: plan has intent fix_location"
assert_contains "$PLAN_CONTENT" "registry" "structural: plan has registry fix_location"
assert_contains "$PLAN_CONTENT" "sonnet" "structural: plan uses sonnet model tier"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `./tests/run-tests.sh tests/test-dry-run.sh 2>&1 | tail -20`
Expected: FAIL — `--structural` is an unknown argument.

- [ ] **Step 3: Add `--structural` flag to argument parser**

In `scripts/storyforge-revise`, add the flag variable alongside `POLISH_MODE`:

```bash
STRUCTURAL_MODE=false
```

Add to the `while` loop `case` block, after the `--polish)` case:

```bash
        --structural)
            STRUCTURAL_MODE=true
            shift
            ;;
```

Add mutual exclusion check after the argument parsing loop (after line 123):

```bash
if [[ "$STRUCTURAL_MODE" == true && "$POLISH_MODE" == true ]]; then
    echo "ERROR: --structural and --polish are mutually exclusive." >&2
    exit 1
fi
```

Update the help text (line 99) to include `--structural`:

```bash
            echo "Usage: storyforge-revise [--dry-run] [--interactive] [--structural] [--coaching LEVEL] [PASS_NUM]"
```

And add a help line after the `--coaching` line:

```bash
            echo "  --structural    Auto-generate plan from structural proposals (CSV-only, no prose)"
```

- [ ] **Step 4: Run test to verify argument is accepted**

Run: `./tests/run-tests.sh tests/test-dry-run.sh 2>&1 | tail -20`
Expected: Still fails (plan generation not implemented yet), but no "Unknown argument" error.

- [ ] **Step 5: Commit**

```bash
git add scripts/storyforge-revise tests/test-dry-run.sh
git commit -m "Add --structural flag parsing to storyforge-revise"
git push
```

---

### Task 2: Auto-generate revision plan from structural proposals

**Files:**
- Modify: `scripts/storyforge-revise:53-61` (plan generation block, after polish mode)

- [ ] **Step 1: Add structural plan generation**

After the polish mode block (line 61), add the structural mode block:

```bash
# --- Structural mode: auto-generate plan from structural proposals ---
if [[ "$STRUCTURAL_MODE" == true ]]; then
    PROPOSALS_FILE="${PROJECT_DIR}/working/scores/structural-proposals.csv"
    if [[ ! -f "$PROPOSALS_FILE" ]]; then
        echo "ERROR: No structural proposals found at ${PROPOSALS_FILE}" >&2
        echo "Run: storyforge-validate --structural" >&2
        exit 1
    fi

    # Check for pending proposals
    PENDING_COUNT=$(grep -c '|pending$' "$PROPOSALS_FILE" 2>/dev/null || echo "0")
    if (( PENDING_COUNT == 0 )); then
        echo "ERROR: No pending proposals in ${PROPOSALS_FILE}" >&2
        echo "All proposals are already completed. Re-run validation to generate new ones." >&2
        exit 1
    fi

    # Save pre-revision scores for delta comparison
    STRUCTURAL_PRE_SCORES="${PROJECT_DIR}/working/scores/structural-latest.csv"
    if [[ -f "$STRUCTURAL_PRE_SCORES" ]]; then
        cp "$STRUCTURAL_PRE_SCORES" "${PROJECT_DIR}/working/scores/structural-pre-revision.csv"
    fi

    log "Structural mode — generating CSV-only revision plan from ${PENDING_COUNT} proposals..."
    mkdir -p "$(dirname "$CSV_PLAN_FILE")"

    # Generate plan: group proposals by dimension, order by fix_location priority
    PYTHONPATH="$PYTHON_LIB" python3 -c "
import sys, csv, io
sys.path.insert(0, '${PYTHON_LIB}')

proposals_file = '${PROPOSALS_FILE}'

# Read proposals
rows = []
with open(proposals_file) as f:
    reader = csv.DictReader(f, delimiter='|')
    for row in reader:
        if row.get('status', '').strip() == 'pending':
            rows.append(row)

# Group by dimension
from collections import OrderedDict
groups = OrderedDict()
for row in rows:
    dim = row['dimension']
    if dim not in groups:
        groups[dim] = {'fix_location': row['fix_location'], 'targets': [], 'rationales': []}
    t = row.get('target', 'global').strip()
    if t and t != 'global':
        groups[dim]['targets'].append(t)
    groups[dim]['rationales'].append(row.get('rationale', row.get('change', '')))

# Order by fix_location priority: structural -> intent -> registry -> brief
priority = {'structural': 0, 'intent': 1, 'registry': 2, 'brief': 3}
sorted_dims = sorted(groups.items(), key=lambda x: priority.get(x[1]['fix_location'], 9))

# Write plan
header = 'pass|name|purpose|scope|targets|guidance|protection|findings|status|model_tier|fix_location'
lines = [header]
for i, (dim, info) in enumerate(sorted_dims, 1):
    name = f'structural-{dim.replace(\"_\", \"-\")}'
    purpose = '; '.join(info['rationales'])
    targets = ';'.join(info['targets']) if info['targets'] else ''
    fix_loc = info['fix_location']
    lines.append(f'{i}|{name}|{purpose}|full|{targets}||all-strengths||pending|sonnet|{fix_loc}')

with open('${CSV_PLAN_FILE}', 'w') as f:
    f.write('\n'.join(lines) + '\n')

print(f'Generated {len(sorted_dims)} passes')
for i, (dim, info) in enumerate(sorted_dims, 1):
    print(f'  Pass {i}: {dim} (fix_location: {info[\"fix_location\"]})')
"

    USE_CSV_PLAN=true
fi
```

- [ ] **Step 2: Run the dry-run test**

Run: `./tests/run-tests.sh tests/test-dry-run.sh 2>&1 | tail -20`
Expected: Tests for structural flag should pass (plan generation works, dry-run prints prompts).

- [ ] **Step 3: Commit**

```bash
git add scripts/storyforge-revise
git commit -m "Generate revision plan from structural proposals in --structural mode"
git push
```

---

### Task 3: Add `registry` fix_location support to prompt building and CSV application

**Files:**
- Modify: `scripts/storyforge-revise:757` (upstream prompt condition)
- Modify: `scripts/storyforge-revise:901` (upstream CSV application condition)
- Modify: `scripts/storyforge-revise:935-940` (file_map in CSV application)

- [ ] **Step 1: Write the test**

Add to `tests/test-dry-run.sh`:

```bash
# ============================================================================
# --structural: registry fix_location produces registry prompt
# ============================================================================

# Create proposals with only a registry fix
cat > "${PROJECT_DIR}/working/scores/structural-proposals.csv" << 'PROPOSALS'
id|dimension|fix_location|target|change|rationale|status
sp001|thematic_concentration|registry|global|consolidate values.csv|Thematic fragmentation: 40 distinct values, score 0.30|pending
PROPOSALS

# Create a values.csv registry for the prompt to reference
mkdir -p "${PROJECT_DIR}/reference"
cat > "${PROJECT_DIR}/reference/values.csv" << 'VALUES'
id|name|aliases
justice|Justice|
truth|Truth|
justice-procedural|Justice — procedural|
VALUES

RESULT=$("${PLUGIN_DIR}/scripts/storyforge-revise" --structural --dry-run 2>&1 || true)
assert_contains "$RESULT" "registry" "structural-registry: prompt references registry"
assert_contains "$RESULT" "values.csv" "structural-registry: prompt references values.csv"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `./tests/run-tests.sh tests/test-dry-run.sh 2>&1 | tail -20`
Expected: FAIL — registry is not recognized as an upstream fix_location.

- [ ] **Step 3: Add `registry` to upstream fix_location conditions**

In `scripts/storyforge-revise`, update the two condition checks that gate upstream revision.

At line 757 (prompt building), change:

```bash
    if [[ "$_fix_location" == "brief" || "$_fix_location" == "intent" || "$_fix_location" == "structural" ]]; then
```

to:

```bash
    if [[ "$_fix_location" == "brief" || "$_fix_location" == "intent" || "$_fix_location" == "structural" || "$_fix_location" == "registry" ]]; then
```

At line 901 (CSV application), make the same change:

```bash
    if [[ "$_fix_location" == "brief" || "$_fix_location" == "intent" || "$_fix_location" == "structural" || "$_fix_location" == "registry" ]]; then
```

- [ ] **Step 4: Build a registry-aware prompt for registry fix_location**

In the upstream prompt building Python block (starting at line 759), add a branch for registry fix_location. Replace the existing upstream prompt block with one that detects registry mode and includes the registry file contents.

After the existing upstream prompt block's `print(f'''You are performing an upstream revision...`)` section, wrap the prompt in a condition. When `_fix_location` is `registry`, the prompt should:

1. Show the full registry CSV (e.g., values.csv, mice-threads.csv)
2. Show all scene-intent rows that reference registry values
3. Ask Claude to output two fenced blocks:
   - `registry-csv` — the consolidated registry
   - `intent-csv` — updated scene-intent rows with canonical IDs

Add this before the existing upstream prompt (inside the Python `-c` block):

```python
fix_location = '${_fix_location}'

if fix_location == 'registry':
    # Determine which registry based on dimension
    dimension = '${PASS_NAME}'.replace('structural-', '').replace('-', '_')
    registry_map = {
        'thematic_concentration': ('values.csv', 'value_at_stake'),
        'mice_health': ('mice-threads.csv', 'mice_threads'),
    }
    registry_file, intent_field = registry_map.get(dimension, ('values.csv', 'value_at_stake'))
    registry_path = os.path.join(ref_dir, registry_file)

    registry_content = ''
    if os.path.exists(registry_path):
        registry_content = open(registry_path).read()

    # Load intent data showing current usage of registry values
    intent_path = os.path.join(ref_dir, 'scene-intent.csv')
    intent_content = ''
    if os.path.exists(intent_path):
        intent_content = open(intent_path).read()

    print(f'''You are consolidating a registry for a novel's structural data.

## Pass: ${PASS_NAME}
## Purpose: ${PASS_PURPOSE}
## Fix Location: registry

## Guidance
${_csv_guidance:-No specific guidance provided.}

## Current Registry: {registry_file}

```registry-csv
{registry_content}```

## Current Scene Intent (showing {intent_field} usage)

```intent-csv
{intent_content}```

## Instructions

1. Consolidate the registry by merging near-duplicate entries. Keep distinct thematic values that serve different narrative purposes. Merge entries that are overly specific variations of the same core value.
2. For each merged entry, add the old names as aliases (semicolon-separated).
3. Update all scene-intent rows to use the consolidated canonical IDs in the {intent_field} column.
4. Output TWO fenced blocks:

```registry-csv
(full consolidated registry — id|name|aliases header, then all rows)
```

```intent-csv
(only rows where {intent_field} changed — full row with all columns)
```

Rules:
- Preserve all scene IDs and non-{intent_field} columns exactly
- Use pipe delimiters
- Every old value must map to exactly one new canonical value
''')
else:
    # existing upstream prompt for intent/structural/brief
```

- [ ] **Step 5: Add `registry-csv` to the file_map in CSV application**

In the CSV application Python block (around line 935), add registry mappings. After the existing `file_map` dict:

```python
    file_map = {
        'scenes-csv': ('scenes.csv', _FILE_MAP['scenes.csv']),
        'scenes-csv-update': ('scenes.csv', _FILE_MAP['scenes.csv']),
        'intent-csv': ('scene-intent.csv', _FILE_MAP['scene-intent.csv']),
        'briefs-csv': ('scene-briefs.csv', _FILE_MAP['scene-briefs.csv']),
        'registry-csv': None,  # handled separately below
    }
```

And add handling for the registry-csv block after the main loop:

```python
# Handle registry-csv blocks — overwrite the full registry file
if 'registry-csv' in blocks:
    reg_rows = csv_block_to_rows(blocks['registry-csv'])
    if reg_rows:
        # Determine registry file from dimension
        dimension = '${PASS_NAME}'.replace('structural-', '').replace('-', '_')
        reg_map = {
            'thematic_concentration': 'values.csv',
            'mice_health': 'mice-threads.csv',
        }
        reg_file = reg_map.get(dimension, 'values.csv')
        reg_path = os.path.join(ref_dir, reg_file)

        # Write registry — preserve original column order
        if os.path.exists(reg_path):
            with open(reg_path) as f:
                header = f.readline().strip().split('|')
        else:
            header = list(reg_rows[0].keys())

        with open(reg_path, 'w') as f:
            f.write('|'.join(header) + '\n')
            for row in reg_rows:
                f.write('|'.join(row.get(c, '') for c in header) + '\n')
        updated_files.append(reg_file)
```

- [ ] **Step 6: Run the test**

Run: `./tests/run-tests.sh tests/test-dry-run.sh 2>&1 | tail -20`
Expected: PASS

- [ ] **Step 7: Commit**

```bash
git add scripts/storyforge-revise tests/test-dry-run.sh
git commit -m "Add registry fix_location support for structural revision"
git push
```

---

### Task 4: Skip re-drafting in structural mode

**Files:**
- Modify: `scripts/storyforge-revise:975-1015` (re-draft block)

- [ ] **Step 1: Write the test**

Add to `tests/test-dry-run.sh`:

```bash
# ============================================================================
# --structural: STRUCTURAL_MODE variable is exported for downstream use
# ============================================================================

# Verify the STRUCTURAL_MODE flag is set in structural mode
cat > "${PROJECT_DIR}/working/scores/structural-proposals.csv" << 'PROPOSALS'
id|dimension|fix_location|target|change|rationale|status
sp001|pacing_shape|intent|global|adjust value_shift|score 0.62 below target 0.75|pending
PROPOSALS

RESULT=$("${PLUGIN_DIR}/scripts/storyforge-revise" --structural --dry-run 2>&1 || true)
assert_contains "$RESULT" "Structural mode" "structural-no-redraft: structural mode active"
assert_not_contains "$RESULT" "Re-drafting" "structural-no-redraft: no re-draft mention in dry run"
```

- [ ] **Step 2: Gate the re-draft block with STRUCTURAL_MODE**

In `scripts/storyforge-revise`, wrap the re-draft block (lines 975-1015) with a structural mode check. Change:

```bash
                # Check if we should re-draft affected scenes
                AFFECTED=$(echo "$UPSTREAM_RESULT" | grep "Affected scenes:" | sed 's/Affected scenes: //')
                if [[ -n "$AFFECTED" && "$AFFECTED" != "none" ]]; then
                    log "  Re-drafting affected scenes..."
```

to:

```bash
                # Check if we should re-draft affected scenes (skip in structural mode)
                AFFECTED=$(echo "$UPSTREAM_RESULT" | grep "Affected scenes:" | sed 's/Affected scenes: //')
                if [[ -n "$AFFECTED" && "$AFFECTED" != "none" && "$STRUCTURAL_MODE" != true ]]; then
                    log "  Re-drafting affected scenes..."
```

And add a log line for structural mode after the `fi` that closes the re-draft block (around line 1015):

```bash
                if [[ -n "$AFFECTED" && "$AFFECTED" != "none" && "$STRUCTURAL_MODE" == true ]]; then
                    log "  Structural mode — skipping re-draft for ${AFFECTED}"
                fi
```

- [ ] **Step 3: Run the test**

Run: `./tests/run-tests.sh tests/test-dry-run.sh 2>&1 | tail -20`
Expected: PASS

- [ ] **Step 4: Commit**

```bash
git add scripts/storyforge-revise tests/test-dry-run.sh
git commit -m "Skip re-drafting in structural revision mode"
git push
```

---

### Task 5: Re-validate and print score deltas after structural passes

**Files:**
- Modify: `scripts/storyforge-revise` (after the main pass loop, before final commit)

- [ ] **Step 1: Write the test**

Add to `tests/test-structural.sh`:

```bash
# ============================================================================
# print_score_delta: formats before/after comparison
# ============================================================================

RESULT=$(python3 -c "
${PY}
from storyforge.structural import print_score_delta

pre = {
    'arc_completeness': {'score': 0.80, 'target': 0.80},
    'thematic_concentration': {'score': 0.30, 'target': 0.60},
    'pacing_shape': {'score': 0.62, 'target': 0.75},
}
post = {
    'arc_completeness': {'score': 0.85, 'target': 0.80},
    'thematic_concentration': {'score': 0.50, 'target': 0.60},
    'pacing_shape': {'score': 0.62, 'target': 0.75},
}

output = print_score_delta(pre, post)
print(output)
")
assert_contains "$RESULT" "arc_completeness" "print_score_delta: includes dimension names"
assert_contains "$RESULT" "+0.05" "print_score_delta: shows positive delta"
assert_contains "$RESULT" "+0.20" "print_score_delta: shows thematic improvement"
assert_contains "$RESULT" "0.00" "print_score_delta: shows no-change"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `./tests/run-tests.sh tests/test-structural.sh 2>&1 | tail -20`
Expected: FAIL — `print_score_delta` doesn't exist.

- [ ] **Step 3: Implement `print_score_delta` in structural.py**

Add to `scripts/lib/python/storyforge/structural.py`, near the other output formatters (around line 1516):

```python
def print_score_delta(pre_scores, post_scores):
    """Format a before/after comparison of structural scores.

    Args:
        pre_scores: dict of {dimension: {'score': float, 'target': float}}
        post_scores: dict of {dimension: {'score': float, 'target': float}}

    Returns:
        Formatted string with dimension, before, after, delta columns.
    """
    lines = []
    lines.append(f"{'Dimension':<28} {'Before':>7} {'After':>7} {'Delta':>7}  Status")
    lines.append('-' * 65)

    all_dims = sorted(set(list(pre_scores.keys()) + list(post_scores.keys())))
    for dim in all_dims:
        pre = pre_scores.get(dim, {}).get('score', 0)
        post = post_scores.get(dim, {}).get('score', 0)
        target = post_scores.get(dim, {}).get('target', pre_scores.get(dim, {}).get('target', 0))
        delta = post - pre

        delta_str = f"+{delta:.2f}" if delta > 0 else f"{delta:.2f}"
        status = "improved" if delta > 0.005 else ("declined" if delta < -0.005 else "unchanged")
        if post >= target and pre < target:
            status = "now passing"

        lines.append(f"  {dim:<26} {pre:>6.2f}  {post:>6.2f}  {delta_str:>6}  {status}")

    return '\n'.join(lines)


def load_scores_as_dict(csv_path):
    """Load a structural-latest.csv into a dict for delta comparison.

    Returns:
        dict of {dimension: {'score': float, 'target': float}}
    """
    result = {}
    if not os.path.exists(csv_path):
        return result
    rows = _read_csv(csv_path)
    for row in rows:
        dim = row.get('dimension', '').strip()
        if dim and dim != 'overall':
            result[dim] = {
                'score': float(row.get('score', 0)),
                'target': float(row.get('target', 0)),
            }
    return result
```

- [ ] **Step 4: Run test to verify it passes**

Run: `./tests/run-tests.sh tests/test-structural.sh 2>&1 | tail -20`
Expected: PASS

- [ ] **Step 5: Add re-validation to storyforge-revise**

In `scripts/storyforge-revise`, after the main pass loop ends (find the closing of the main `for` loop — the line with `done` that ends pass iteration), add the structural re-validation block:

```bash
# --- Structural mode: re-validate and print score delta ---
if [[ "$STRUCTURAL_MODE" == true && "$DRY_RUN" != true ]]; then
    log "Re-running structural validation..."

    POST_SCORES=$(PYTHONPATH="$PYTHON_LIB" python3 -c "
import sys, os, json
sys.path.insert(0, '${PYTHON_LIB}')
from storyforge.structural import structural_score, save_structural_scores, load_scores_as_dict, print_score_delta

ref_dir = os.path.join('${PROJECT_DIR}', 'reference')
report = structural_score(ref_dir)
save_structural_scores(report, '${PROJECT_DIR}')

# Load pre-revision scores
pre_path = os.path.join('${PROJECT_DIR}', 'working', 'scores', 'structural-pre-revision.csv')
post_path = os.path.join('${PROJECT_DIR}', 'working', 'scores', 'structural-latest.csv')

pre = load_scores_as_dict(pre_path)
post = load_scores_as_dict(post_path)

print(print_score_delta(pre, post))

# Print new overall
overall = report.get('overall', 0)
print(f'\nOverall: {overall:.2f}')
" 2>&1)

    echo ""
    echo "=== Structural Score Delta ==="
    echo "$POST_SCORES"
    echo ""

    # Mark completed proposals
    PROPOSALS_FILE="${PROJECT_DIR}/working/scores/structural-proposals.csv"
    if [[ -f "$PROPOSALS_FILE" ]]; then
        sed -i '' 's/|pending$/|completed/' "$PROPOSALS_FILE"
        log "Marked all proposals as completed in structural-proposals.csv"
    fi
fi
```

- [ ] **Step 6: Commit**

```bash
git add scripts/storyforge-revise scripts/lib/python/storyforge/structural.py tests/test-structural.sh
git commit -m "Add score delta reporting after structural revision"
git push
```

---

### Task 6: Update help text and documentation

**Files:**
- Modify: `scripts/storyforge-revise:99-111` (help text)
- Modify: `skills/revise/SKILL.md` (skill documentation)

- [ ] **Step 1: Update revise script help text**

The help text updates were already included in Task 1 Step 3. Verify they're present by reading the help output:

Run: `./scripts/storyforge-revise --help`

Expected output should include:
```
  --structural    Auto-generate plan from structural proposals (CSV-only, no prose)
```

- [ ] **Step 2: Add `--structural` mode documentation to the revise skill**

In `skills/revise/SKILL.md`, add a section after the existing "Script Delegation Pattern" section (or wherever the skill describes modes). Add:

```markdown
### Structural Mode

When the author wants to improve structural scores without touching prose, delegate to the script:

> **Option A: Run it here**
> I'll launch `storyforge-revise --structural` in this conversation.
>
> **Option B: Run it yourself**
> ```bash
> cd [project_dir] && [plugin_path]/scripts/storyforge-revise --structural
> ```

This reads `working/scores/structural-proposals.csv` (from `storyforge-validate --structural`), generates a CSV-only revision plan, and executes each pass. No prose files are touched. After all passes, it re-validates and prints a score delta.

Use `--structural --dry-run` to preview the plan and prompts without executing.
```

- [ ] **Step 3: Commit**

```bash
git add scripts/storyforge-revise skills/revise/SKILL.md
git commit -m "Update help text and skill docs for --structural mode"
git push
```

---

### Task 7: End-to-end verification on Night Watch

**Files:** None (manual verification)

- [ ] **Step 1: Dry-run on Night Watch**

Run from Night Watch project directory:

```bash
cd /Users/cadencedev/Developer/night-watch && /Users/cadencedev/Developer/storyforge/scripts/storyforge-revise --structural --dry-run
```

Verify:
- Plan is generated with correct passes (one per dimension below target)
- Passes are ordered: structural -> intent -> registry -> brief
- Each prompt includes the right CSV data and registries
- No mention of re-drafting or prose

- [ ] **Step 2: Run all Storyforge tests**

```bash
cd /Users/cadencedev/Developer/storyforge && ./tests/run-tests.sh
```

Expected: All tests pass, including new structural and dry-run tests.

- [ ] **Step 3: Bump version and commit**

Update `.claude-plugin/plugin.json` version from current to next patch.

```bash
git add .claude-plugin/plugin.json
git commit -m "Bump version to X.Y.Z — add --structural revise mode"
git push
```
