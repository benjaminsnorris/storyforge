# Elaborate Gap-Fill Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a gap-fill mode to the elaborate skill and script that detects post-extraction validation failures and fills missing fields via targeted batch API calls.

**Architecture:** Two new Python functions in `elaborate.py` (`analyze_gaps` and `build_gap_fill_prompt`) provide gap analysis and prompt generation. The `storyforge-elaborate` script gains a `--stage gap-fill` option that uses the batch API for parallel field groups and sequential API for knowledge fixes. The elaborate skill and forge skill each get a new state detection check.

**Tech Stack:** Python (elaborate.py, prompts_elaborate.py), Bash (storyforge-elaborate), Batch API (api.py)

---

### Task 1: `analyze_gaps` function in elaborate.py

**Files:**
- Modify: `scripts/lib/python/storyforge/elaborate.py` (append after `validate_structure`, ~line 709)
- Test: `tests/test-elaborate.sh` (append new test section)

- [ ] **Step 1: Write the failing test**

Append to `tests/test-elaborate.sh`:

```bash
# ============================================================================
# analyze_gaps
# ============================================================================

# Create a post-extraction fixture: drafted scenes with gaps
TMP_REF=$(mktemp -d)

# scenes.csv — all drafted, but some missing type and timeline_day
cat > "${TMP_REF}/scenes.csv" <<'GAPCSV'
id|seq|title|part|pov|location|timeline_day|time_of_day|duration|type|status|word_count|target_words
scene-01|1|Opening|1|Alice|The Lab|1|morning|2 hours|character|drafted|2500|2500
scene-02|2|Discovery|1|Alice|The Lab||afternoon||action|drafted|3000|3000
scene-03|3|Confrontation|1|Bob|Council Room|2|evening|1 hour||drafted|2000|2000
scene-04|4|Escape|2|Alice|The Tunnel|3|night|30 minutes|action|drafted|1800|1800
GAPCSV

# scene-intent.csv — some missing value_shift and scene_type
cat > "${TMP_REF}/scene-intent.csv" <<'GAPCSV'
id|function|scene_type|emotional_arc|value_at_stake|value_shift|turning_point|threads|characters|on_stage|mice_threads
scene-01|Establish the lab|action|calm to focused|truth|+/-|revelation|discovery|Alice;Bob|Alice|+inquiry:anomaly
scene-02|Find the anomaly||tense to shocked|safety||action|discovery;danger|Alice|Alice|
scene-03|Confront the council|sequel|resolve to anger|justice|+/-|revelation|politics|Bob;Council|Bob;Council|
scene-04|Escape the collapse|action|fear to relief|life|-/+|action|danger|Alice|Alice|-inquiry:anomaly
GAPCSV

# scene-briefs.csv — all populated (post-extraction state)
cat > "${TMP_REF}/scene-briefs.csv" <<'GAPCSV'
id|goal|conflict|outcome|crisis|decision|knowledge_in|knowledge_out|key_actions|key_dialogue|emotions|motifs|continuity_deps|has_overflow
scene-01|Set up the experiment|Equipment is faulty|yes-but|Fix equipment or start anyway|Starts anyway|Lab is funded|Lab equipment is faulty;experiment started|Checks equipment;Starts experiment|"We proceed"|calm;determination|lab-lights||false
scene-02|Investigate the anomaly|Anomaly is dangerous|no-and|Retreat or push deeper|Pushes deeper|Lab equipment is faulty;experiment started|Anomaly is real;it is spreading|Scans anomaly;Takes samples|"This shouldn't be possible"|curiosity;shock;fear|anomaly-glow|scene-01|false
scene-03|Get council to act|Council dismisses evidence|no|Accept dismissal or go rogue|Goes rogue|Anomaly is real;it is spreading|Council will not help;must act alone|Presents evidence;Council votes no|"Noted for the record"|resolve;anger;defiance|governance-weight|scene-02|false
scene-04|Escape the tunnel|Tunnel is collapsing|yes|Save samples or save self|Saves self|Council will not help;must act alone|Survived;samples lost|Runs;Dodges debris;Reaches exit|"Leave it!"|fear;relief|depth-descent|scene-03|false
GAPCSV

RESULT=$(python3 -c "
${PY}
from storyforge.elaborate import analyze_gaps
import json
gaps = analyze_gaps('${TMP_REF}')
print(json.dumps(gaps, indent=2))
")

# Should detect gap groups
assert_contains "$RESULT" '"scene-fields"' "analyze_gaps: detects scene-fields group"
assert_contains "$RESULT" '"intent-fields"' "analyze_gaps: detects intent-fields group"
assert_contains "$RESULT" '"scene-03"' "analyze_gaps: scene-03 missing type"
assert_contains "$RESULT" '"scene-02"' "analyze_gaps: scene-02 missing timeline_day"

# Should include total counts
TOTAL=$(python3 -c "
${PY}
from storyforge.elaborate import analyze_gaps
gaps = analyze_gaps('${TMP_REF}')
print(gaps['total_gaps'])
")

assert_not_empty "$TOTAL" "analyze_gaps: returns total_gaps count"

# Should not flag scenes with no gaps
assert_not_contains "$RESULT" '"scene-01": {' "analyze_gaps: scene-01 has no completeness gaps"

rm -rf "$TMP_REF"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `./tests/run-tests.sh tests/test-elaborate.sh`
Expected: FAIL — `analyze_gaps` not defined.

- [ ] **Step 3: Write the implementation**

Add to `scripts/lib/python/storyforge/elaborate.py` after the `validate_structure` function (after line 708):

```python
# Gap group definitions: which fields belong to which group
_GAP_GROUPS = {
    'scene-fields': {
        'fields': ['type', 'time_of_day', 'duration', 'part'],
        'file': 'scenes.csv',
        'batch_type': 'parallel',
    },
    'intent-fields': {
        'fields': ['scene_type', 'emotional_arc', 'value_at_stake',
                    'value_shift', 'turning_point'],
        'file': 'scene-intent.csv',
        'batch_type': 'parallel',
    },
    'thread-fields': {
        'fields': ['threads', 'mice_threads'],
        'file': 'scene-intent.csv',
        'batch_type': 'parallel',
    },
    'location-timeline': {
        'fields': ['location', 'timeline_day'],
        'file': 'scenes.csv',
        'batch_type': 'parallel',
    },
    'knowledge': {
        'fields': ['knowledge_in', 'knowledge_out', 'continuity_deps'],
        'file': 'scene-briefs.csv',
        'batch_type': 'sequential',
    },
}


def analyze_gaps(ref_dir: str) -> dict:
    """Analyze validation failures and categorize them into gap groups.

    Returns a dict with:
        - 'groups': dict of group_name -> {'fields': [...], 'scenes': {scene_id: [missing_fields]}, 'batch_type': str}
        - 'structural': list of non-completeness validation failures (MICE, timeline, knowledge-availability)
        - 'total_gaps': int count of all individual field gaps
        - 'validation': the full validation report
    """
    report = validate_structure(ref_dir)

    # Collect per-scene missing fields from completeness failures
    scene_missing: dict[str, list[str]] = {}
    for failure in report['failures']:
        if failure['category'] == 'completeness' and failure.get('scene_id'):
            sid = failure['scene_id']
            msg = failure['message']
            # Extract field names from "missing required columns: ['field1', 'field2']"
            if 'missing required columns:' in msg:
                bracket_start = msg.index('[')
                bracket_end = msg.index(']') + 1
                fields = eval(msg[bracket_start:bracket_end])
                scene_missing[sid] = fields

    # Categorize into gap groups
    groups: dict[str, dict] = {}
    total_gaps = 0

    for group_name, group_def in _GAP_GROUPS.items():
        group_fields = set(group_def['fields'])
        scenes_in_group: dict[str, list[str]] = {}

        for sid, missing in scene_missing.items():
            overlap = [f for f in missing if f in group_fields]
            if overlap:
                scenes_in_group[sid] = overlap
                total_gaps += len(overlap)

        if scenes_in_group:
            groups[group_name] = {
                'fields': group_def['fields'],
                'scenes': scenes_in_group,
                'batch_type': group_def['batch_type'],
                'count': sum(len(v) for v in scenes_in_group.values()),
            }

    # Collect structural failures (non-completeness)
    structural = [
        f for f in report['failures']
        if f['category'] in ('threads', 'timeline', 'knowledge')
        and f['severity'] == 'blocking'
    ]

    return {
        'groups': groups,
        'structural': structural,
        'total_gaps': total_gaps,
        'validation': report,
    }
```

- [ ] **Step 4: Run test to verify it passes**

Run: `./tests/run-tests.sh tests/test-elaborate.sh`
Expected: All `analyze_gaps` tests PASS.

- [ ] **Step 5: Commit**

```bash
git add scripts/lib/python/storyforge/elaborate.py tests/test-elaborate.sh
git commit -m "Add analyze_gaps function to elaborate.py"
git push
```

---

### Task 2: `build_gap_fill_prompt` function in prompts_elaborate.py

**Files:**
- Modify: `scripts/lib/python/storyforge/prompts_elaborate.py` (append after `csv_block_to_rows`, ~line 500)
- Test: `tests/test-elaborate.sh` (append new test section)

- [ ] **Step 1: Write the failing test**

Append to `tests/test-elaborate.sh`:

```bash
# ============================================================================
# build_gap_fill_prompt
# ============================================================================

TMP_REF=$(mktemp -d)
TMP_SCENES="${TMP_REF}/scenes"
mkdir -p "${TMP_SCENES}"
mkdir -p "${TMP_REF}/reference"

# Create a scene file
cat > "${TMP_SCENES}/scene-03.md" <<'PROSE'
Bob strode into the council chamber. The long table gleamed under the gas lamps.
"We have evidence," he said, laying the maps flat. "The eastern ridge is failing."
The council members exchanged glances. No one spoke for a long moment.
PROSE

# Create minimal CSVs
cat > "${TMP_REF}/reference/scenes.csv" <<'GAPCSV'
id|seq|title|part|pov|location|timeline_day|time_of_day|duration|type|status|word_count|target_words
scene-03|3|Confrontation|1|Bob|Council Room|2|evening|1 hour||drafted|2000|2000
GAPCSV

cat > "${TMP_REF}/reference/scene-intent.csv" <<'GAPCSV'
id|function|scene_type|emotional_arc|value_at_stake|value_shift|turning_point|threads|characters|on_stage|mice_threads
scene-03|Confront the council|sequel|resolve to anger|justice|+/-|revelation|politics|Bob;Council|Bob;Council|
GAPCSV

cat > "${TMP_REF}/reference/scene-briefs.csv" <<'GAPCSV'
id|goal|conflict|outcome|crisis|decision|knowledge_in|knowledge_out|key_actions|key_dialogue|emotions|motifs|continuity_deps|has_overflow
scene-03|Get council to act|Council dismisses|no|Accept or go rogue|Goes rogue|Evidence exists|Council will not help|Presents evidence|"Noted"|resolve;anger|governance|scene-02|false
GAPCSV

RESULT=$(python3 -c "
${PY}
from storyforge.prompts_elaborate import build_gap_fill_prompt
prompt = build_gap_fill_prompt(
    scene_id='scene-03',
    gap_group='scene-fields',
    missing_fields=['type'],
    project_dir='${TMP_REF}',
    scenes_dir='${TMP_SCENES}',
)
print(prompt)
")

assert_contains "$RESULT" "scene-03" "build_gap_fill_prompt: includes scene ID"
assert_contains "$RESULT" "type" "build_gap_fill_prompt: asks for missing field"
assert_contains "$RESULT" "Bob" "build_gap_fill_prompt: includes prose excerpt"
assert_contains "$RESULT" "council chamber" "build_gap_fill_prompt: includes scene prose"

rm -rf "$TMP_REF"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `./tests/run-tests.sh tests/test-elaborate.sh`
Expected: FAIL — `build_gap_fill_prompt` not defined.

- [ ] **Step 3: Write the implementation**

Add to `scripts/lib/python/storyforge/prompts_elaborate.py` after the `csv_block_to_rows` function (after line 500):

```python
# ============================================================================
# Gap-fill prompt builders
# ============================================================================

_FIELD_INSTRUCTIONS = {
    'type': (
        'Classify the scene type. Choose exactly one from: '
        'character, plot, world, action, transition, confrontation, dialogue, introspection, revelation.'
    ),
    'time_of_day': (
        'Determine the time of day. Choose exactly one from: '
        'morning, afternoon, evening, night, dawn, dusk.'
    ),
    'duration': (
        'Estimate the in-story duration of this scene (e.g., "2 hours", "30 minutes", "15 minutes").'
    ),
    'part': (
        'Determine which act/part this scene belongs to (integer, e.g., 1, 2, 3).'
    ),
    'scene_type': (
        'Classify as action or sequel using Swain\'s scene/sequel pattern. '
        'Action: character pursues a goal and meets conflict. '
        'Sequel: character reacts, processes, and decides next move.'
    ),
    'emotional_arc': (
        'Describe the emotional progression in the format "starting_emotion to ending_emotion" '
        '(e.g., "controlled competence to buried unease").'
    ),
    'value_at_stake': (
        'Identify the abstract value at stake. Choose from: '
        'safety, love, justice, truth, freedom, honor, life, identity, loyalty, power — '
        'or name a specific value if none fit.'
    ),
    'value_shift': (
        'Determine the polarity shift using +/- notation: '
        '+/- (positive to negative), -/+ (negative to positive), '
        '+/++ (good to better), -/-- (bad to worse), '
        '+/+ (no change, positive), -/- (no change, negative).'
    ),
    'turning_point': (
        'Identify the turning point type. Choose: action (character does something) '
        'or revelation (character learns something new).'
    ),
    'threads': (
        'List the story threads this scene advances, semicolon-separated '
        '(e.g., "trust;betrayal;investigation").'
    ),
    'mice_threads': (
        'List MICE thread operations: +type:name to open, -type:name to close. '
        'Types: milieu, inquiry, character, event. '
        'Semicolon-separated (e.g., "+inquiry:who-killed-X;-milieu:the-castle").'
    ),
    'location': (
        'Identify the primary location where this scene takes place. '
        'Use a canonical name consistent with other scenes.'
    ),
    'timeline_day': (
        'Determine what day number this scene takes place on (integer, starting from 1). '
        'Consider the surrounding scenes for context.'
    ),
}


def build_gap_fill_prompt(
    scene_id: str,
    gap_group: str,
    missing_fields: list[str],
    project_dir: str,
    scenes_dir: str,
) -> str:
    """Build a focused prompt to fill specific missing fields for one scene.

    Args:
        scene_id: The scene to fill gaps for.
        gap_group: Name of the gap group (for context in prompt).
        missing_fields: List of field names that need values.
        project_dir: Path to the book project.
        scenes_dir: Path to the scenes/ directory with prose files.

    Returns:
        Prompt string for Claude.
    """
    from .elaborate import get_scene

    ref_dir = os.path.join(project_dir, 'reference')
    scene_data = get_scene(scene_id, ref_dir)

    # Read prose excerpt (first 500 words)
    prose_path = os.path.join(scenes_dir, f'{scene_id}.md')
    prose = _read_file(prose_path)
    if prose:
        words = prose.split()
        if len(words) > 500:
            prose = ' '.join(words[:500]) + '\n[... truncated ...]'

    # Build field instructions
    field_instructions = []
    for field in missing_fields:
        instruction = _FIELD_INSTRUCTIONS.get(field, f'Provide a value for {field}.')
        field_instructions.append(f'- **{field}**: {instruction}')

    # Build existing data summary
    existing_data = []
    if scene_data:
        for key, val in scene_data.items():
            if val and key not in ('id',) and key not in missing_fields:
                existing_data.append(f'- {key}: {val}')

    return f"""You are filling missing metadata for a scene in a novel. Read the prose excerpt and existing data, then provide ONLY the missing fields.

## Scene: {scene_id}

### Existing Data
{chr(10).join(existing_data) if existing_data else '(no existing data)'}

### Prose Excerpt
{prose if prose else '(no prose available)'}

## Missing Fields — Fill These

{chr(10).join(field_instructions)}

## Output Format

Respond with ONLY a pipe-delimited CSV row. The header is:

id|{"|".join(missing_fields)}

Provide exactly one data row:

{scene_id}|<values>

No explanation. No markdown fencing. Just the header line and the data line.
"""
```

- [ ] **Step 4: Run test to verify it passes**

Run: `./tests/run-tests.sh tests/test-elaborate.sh`
Expected: All `build_gap_fill_prompt` tests PASS.

- [ ] **Step 5: Commit**

```bash
git add scripts/lib/python/storyforge/prompts_elaborate.py tests/test-elaborate.sh
git commit -m "Add build_gap_fill_prompt to prompts_elaborate.py"
git push
```

---

### Task 3: Knowledge gap-fill prompt builder

**Files:**
- Modify: `scripts/lib/python/storyforge/prompts_elaborate.py` (append after `build_gap_fill_prompt`)
- Test: `tests/test-elaborate.sh` (append new test section)

- [ ] **Step 1: Write the failing test**

Append to `tests/test-elaborate.sh`:

```bash
# ============================================================================
# build_knowledge_fix_prompt
# ============================================================================

TMP_REF=$(mktemp -d)
TMP_SCENES="${TMP_REF}/scenes"
mkdir -p "${TMP_SCENES}" "${TMP_REF}/reference"

cat > "${TMP_SCENES}/scene-02.md" <<'PROSE'
Alice ran the scanner across the anomaly. The readings confirmed what she feared.
"This shouldn't be possible," she whispered. The anomaly was real, and spreading.
PROSE

cat > "${TMP_REF}/reference/scenes.csv" <<'GAPCSV'
id|seq|title|part|pov|location|timeline_day|time_of_day|duration|type|status|word_count|target_words
scene-01|1|Opening|1|Alice|The Lab|1|morning|2 hours|character|drafted|2500|2500
scene-02|2|Discovery|1|Alice|The Lab|1|afternoon|1 hour|action|drafted|3000|3000
GAPCSV

cat > "${TMP_REF}/reference/scene-intent.csv" <<'GAPCSV'
id|function|scene_type|emotional_arc|value_at_stake|value_shift|turning_point|threads|characters|on_stage|mice_threads
scene-01|Establish the lab|action|calm to focused|truth|+/-|revelation|discovery|Alice|Alice|
scene-02|Find the anomaly|action|tense to shocked|safety|-/+|action|discovery|Alice|Alice|
GAPCSV

cat > "${TMP_REF}/reference/scene-briefs.csv" <<'GAPCSV'
id|goal|conflict|outcome|crisis|decision|knowledge_in|knowledge_out|key_actions|key_dialogue|emotions|motifs|continuity_deps|has_overflow
scene-01|Set up experiment|Equipment faulty|yes-but|Fix or start|Starts anyway||Lab equipment is faulty;experiment started|Checks equipment|"We proceed"|calm|lights||false
scene-02|Investigate anomaly|Dangerous|no-and|Retreat or push|Pushes deeper|Equipment is broken;experiment began|Anomaly is real;it is spreading|Scans anomaly|"Impossible"|shock|glow|scene-01|false
GAPCSV

RESULT=$(python3 -c "
${PY}
from storyforge.prompts_elaborate import build_knowledge_fix_prompt

# scene-02 has knowledge_in wording that doesn't match scene-01's knowledge_out
# scene-01 outputs: 'Lab equipment is faulty;experiment started'
# scene-02 inputs: 'Equipment is broken;experiment began' (paraphrased!)

prior_knowledge = {'Lab equipment is faulty', 'experiment started'}
prompt = build_knowledge_fix_prompt(
    scene_id='scene-02',
    project_dir='${TMP_REF}',
    scenes_dir='${TMP_SCENES}',
    available_knowledge=prior_knowledge,
)
print(prompt)
")

assert_contains "$RESULT" "scene-02" "build_knowledge_fix_prompt: includes scene ID"
assert_contains "$RESULT" "Lab equipment is faulty" "build_knowledge_fix_prompt: includes available knowledge"
assert_contains "$RESULT" "knowledge_in" "build_knowledge_fix_prompt: asks for knowledge_in"

rm -rf "$TMP_REF"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `./tests/run-tests.sh tests/test-elaborate.sh`
Expected: FAIL — `build_knowledge_fix_prompt` not defined.

- [ ] **Step 3: Write the implementation**

Add to `scripts/lib/python/storyforge/prompts_elaborate.py` after `build_gap_fill_prompt`:

```python
def build_knowledge_fix_prompt(
    scene_id: str,
    project_dir: str,
    scenes_dir: str,
    available_knowledge: set[str],
) -> str:
    """Build a prompt to fix knowledge_in/knowledge_out wording for one scene.

    Args:
        scene_id: The scene to fix.
        project_dir: Path to the book project.
        scenes_dir: Path to the scenes/ directory with prose files.
        available_knowledge: Set of exact knowledge_out strings from all prior scenes.

    Returns:
        Prompt string for Claude.
    """
    from .elaborate import get_scene

    ref_dir = os.path.join(project_dir, 'reference')
    scene_data = get_scene(scene_id, ref_dir)

    # Read prose excerpt
    prose_path = os.path.join(scenes_dir, f'{scene_id}.md')
    prose = _read_file(prose_path)
    if prose:
        words = prose.split()
        if len(words) > 500:
            prose = ' '.join(words[:500]) + '\n[... truncated ...]'

    current_kin = scene_data.get('knowledge_in', '') if scene_data else ''
    current_kout = scene_data.get('knowledge_out', '') if scene_data else ''

    sorted_knowledge = sorted(available_knowledge) if available_knowledge else ['(none yet — this is the first scene)']

    return f"""You are fixing the knowledge chain for a scene in a novel. The knowledge_in field must use EXACT wording from prior scenes' knowledge_out.

## Scene: {scene_id}

### Prose Excerpt
{prose if prose else '(no prose available)'}

### Current Values (may have wording mismatches)
- knowledge_in: {current_kin}
- knowledge_out: {current_kout}

### Available Knowledge (exact wording from all prior scenes' knowledge_out)
{chr(10).join(f'- {k}' for k in sorted_knowledge)}

## Instructions

1. Rewrite knowledge_in using ONLY facts from the available knowledge list above, using their EXACT wording. Drop any facts not in the list. Add any facts from the list that this POV character would know entering this scene.
2. Rewrite knowledge_out as: the corrected knowledge_in PLUS any new facts learned during this scene (read the prose to determine what's new).
3. List continuity_deps: the scene IDs whose knowledge_out contributed facts to this scene's knowledge_in.

## Output Format

Respond with ONLY a pipe-delimited CSV row. The header is:

id|knowledge_in|knowledge_out|continuity_deps

Provide exactly one data row. Semicolon-separate multiple values within a field.
No explanation. No markdown fencing. Just the header line and the data line.
"""
```

- [ ] **Step 4: Run test to verify it passes**

Run: `./tests/run-tests.sh tests/test-elaborate.sh`
Expected: All `build_knowledge_fix_prompt` tests PASS.

- [ ] **Step 5: Commit**

```bash
git add scripts/lib/python/storyforge/prompts_elaborate.py tests/test-elaborate.sh
git commit -m "Add build_knowledge_fix_prompt to prompts_elaborate.py"
git push
```

---

### Task 4: `--stage gap-fill` in storyforge-elaborate script

**Files:**
- Modify: `scripts/storyforge-elaborate` (lines 36-77 for args, new section for gap-fill execution)

- [ ] **Step 1: Update argument parsing to accept gap-fill stage**

In `scripts/storyforge-elaborate`, change the stage validation case statement (line 74-77) from:

```bash
case "$STAGE" in
    spine|architecture|map|briefs) ;;
    *) echo "ERROR: Unknown stage: $STAGE (expected: spine|architecture|map|briefs)" >&2; exit 1 ;;
esac
```

to:

```bash
case "$STAGE" in
    spine|architecture|map|briefs|gap-fill) ;;
    *) echo "ERROR: Unknown stage: $STAGE (expected: spine|architecture|map|briefs|gap-fill)" >&2; exit 1 ;;
esac
```

And update the usage text (line 40-43) from:

```
Stages:
  spine          Build the 5-10 irreducible story events
  architecture   Expand spine to 15-25 scenes with structure
  map            Full scene map with locations, timeline, characters
  briefs         Write drafting contracts for each scene
```

to:

```
Stages:
  spine          Build the 5-10 irreducible story events
  architecture   Expand spine to 15-25 scenes with structure
  map            Full scene map with locations, timeline, characters
  briefs         Write drafting contracts for each scene
  gap-fill       Fill missing fields in extracted scene data
```

- [ ] **Step 2: Add gap-fill execution path**

After the API key check block (line 85) and before the "Project info" section (line 97), the existing check requires `ANTHROPIC_API_KEY` for non-interactive, non-dry-run. This already covers gap-fill since it uses the API.

Now, after the "Build prompt" section and before the "Branch and PR" section, insert a conditional block. Replace the entire section from `log "Building ${STAGE} prompt..."` (line 109) through the end of "Parse response and apply updates" (line 355) by wrapping the existing code in an if/else:

Insert **before** line 109 (`log "Building ${STAGE} prompt..."`):

```bash
if [[ "$STAGE" == "gap-fill" ]]; then
    # ============================================================================
    # Gap-fill: analyze gaps, batch-fill parallel fields, sequential knowledge fix
    # ============================================================================

    REF_DIR="${PROJECT_DIR}/reference"
    SCENES_DIR="${PROJECT_DIR}/scenes"
    GAP_DIR="${PROJECT_DIR}/working/gap-fill"
    mkdir -p "$GAP_DIR"

    log "Analyzing gaps..."

    GAP_ANALYSIS=$(PYTHONPATH="$PYTHON_LIB" python3 -c "
import json
from storyforge.elaborate import analyze_gaps
gaps = analyze_gaps('${REF_DIR}')
print(json.dumps(gaps))
")

    TOTAL_GAPS=$(echo "$GAP_ANALYSIS" | python3 -c "import sys, json; g=json.load(sys.stdin); print(g['total_gaps'])")
    GROUP_COUNT=$(echo "$GAP_ANALYSIS" | python3 -c "import sys, json; g=json.load(sys.stdin); print(len(g['groups']))")

    if [[ "$TOTAL_GAPS" == "0" && "$GROUP_COUNT" == "0" ]]; then
        log "No gaps found — all validation checks pass."
        # Still run validation to show clean report
    else
        log "Found ${TOTAL_GAPS} field gaps across ${GROUP_COUNT} group(s)"

        # Print gap summary
        echo "$GAP_ANALYSIS" | python3 -c "
import sys, json
gaps = json.load(sys.stdin)
for name, group in gaps['groups'].items():
    scenes = group['scenes']
    count = group['count']
    print(f'  {name}: {count} missing field(s) across {len(scenes)} scene(s)')
" | while IFS= read -r line; do log "$line"; done

        if [[ "$DRY_RUN" == true ]]; then
            log "DRY RUN — would fill these gaps"
            echo "$GAP_ANALYSIS" | python3 -c "
import sys, json
gaps = json.load(sys.stdin)
for name, group in gaps['groups'].items():
    print(f'=== {name} ({group[\"batch_type\"]}) ===')
    for sid, fields in group['scenes'].items():
        print(f'  {sid}: {fields}')
"
            exit 0
        fi

        # --- Branch and PR ---
        create_branch "gap-fill" "$PROJECT_DIR"
        ensure_branch_pushed "$PROJECT_DIR"

        PR_BODY="## Gap-Fill: ${PROJECT_TITLE}

**Gaps found:** ${TOTAL_GAPS} across ${GROUP_COUNT} group(s)

### Tasks
- [ ] Fill parallel field gaps
- [ ] Fix knowledge chain
- [ ] Validate"

        create_draft_pr "Elaborate: ${PROJECT_TITLE} — gap-fill" "$PR_BODY" "$PROJECT_DIR" "elaboration"

        GAP_MODEL=$(select_model "evaluation")  # Sonnet for analytical gap-fill

        # --- Parallel gap groups: build single batch ---
        PARALLEL_GROUPS=$(echo "$GAP_ANALYSIS" | python3 -c "
import sys, json
gaps = json.load(sys.stdin)
parallel = {k: v for k, v in gaps['groups'].items() if v['batch_type'] == 'parallel'}
print(json.dumps(parallel))
")

        PARALLEL_COUNT=$(echo "$PARALLEL_GROUPS" | python3 -c "import sys, json; g=json.load(sys.stdin); print(sum(len(v['scenes']) for v in g.values()))")

        if [[ "$PARALLEL_COUNT" != "0" ]]; then
            log "Building batch for ${PARALLEL_COUNT} parallel gap-fill requests..."

            BATCH_FILE="${GAP_DIR}/gap-fill-batch.jsonl"
            BATCH_OUTPUT="${GAP_DIR}/batch-output"
            BATCH_LOGS="${GAP_DIR}/batch-logs"
            mkdir -p "$BATCH_OUTPUT" "$BATCH_LOGS"

            PYTHONPATH="$PYTHON_LIB" python3 -c "
import json, sys
from storyforge.prompts_elaborate import build_gap_fill_prompt

parallel_groups = json.loads('''${PARALLEL_GROUPS}''')
project_dir = '${PROJECT_DIR}'
scenes_dir = '${SCENES_DIR}'
model = '${GAP_MODEL}'

with open('${BATCH_FILE}', 'w') as f:
    for group_name, group_data in parallel_groups.items():
        for scene_id, missing_fields in group_data['scenes'].items():
            prompt = build_gap_fill_prompt(
                scene_id=scene_id,
                gap_group=group_name,
                missing_fields=missing_fields,
                project_dir=project_dir,
                scenes_dir=scenes_dir,
            )
            custom_id = f'{group_name}:{scene_id}'
            req = {
                'custom_id': custom_id,
                'params': {
                    'model': model,
                    'max_tokens': 256,
                    'messages': [{'role': 'user', 'content': prompt}],
                },
            }
            f.write(json.dumps(req) + '\n')
print('ok')
"

            log "Submitting batch..."
            BATCH_ID=$(PYTHONPATH="$PYTHON_LIB" python3 -m storyforge.api submit-batch "$BATCH_FILE")
            log "Batch ID: ${BATCH_ID}"

            log "Polling batch..."
            RESULTS_URL=$(PYTHONPATH="$PYTHON_LIB" python3 -m storyforge.api poll-batch "$BATCH_ID")

            log "Downloading results..."
            SUCCEEDED=$(PYTHONPATH="$PYTHON_LIB" python3 -m storyforge.api download-results "$RESULTS_URL" "$BATCH_OUTPUT" "$BATCH_LOGS")

            # Parse and apply results
            log "Applying parallel gap-fill results..."

            PYTHONPATH="$PYTHON_LIB" python3 -c "
import os, json
from storyforge.elaborate import update_scene
from storyforge.prompts_elaborate import csv_block_to_rows

batch_logs = '${BATCH_LOGS}'
ref_dir = '${REF_DIR}'
batch_output = '${BATCH_OUTPUT}'
applied = 0

for fname in os.listdir(batch_logs):
    if not fname.endswith('.txt'):
        continue
    custom_id = fname[:-4]  # strip .txt
    status_file = os.path.join(batch_output, f'.status-{custom_id}')
    if not os.path.exists(status_file) or open(status_file).read().strip() != 'ok':
        continue

    text = open(os.path.join(batch_logs, fname)).read().strip()
    # Parse the CSV response (header + one data row)
    rows = csv_block_to_rows(text)
    if not rows:
        continue

    row = rows[0]
    scene_id = row.get('id', '')
    if not scene_id:
        # custom_id format is group:scene_id
        scene_id = custom_id.split(':', 1)[-1] if ':' in custom_id else ''
    if not scene_id:
        continue

    updates = {k: v for k, v in row.items() if k != 'id' and v.strip()}
    if updates:
        update_scene(scene_id, ref_dir, updates)
        applied += 1

print(f'Applied {applied} gap-fill results')
" 2>&1 | while IFS= read -r line; do log "  $line"; done

            update_pr_task "Fill parallel field gaps" "$PROJECT_DIR" 2>/dev/null || true
        fi

        # --- Sequential knowledge fix ---
        KNOWLEDGE_GROUP=$(echo "$GAP_ANALYSIS" | python3 -c "
import sys, json
gaps = json.load(sys.stdin)
kg = gaps['groups'].get('knowledge', {})
print(json.dumps(kg))
")

        KNOWLEDGE_COUNT=$(echo "$KNOWLEDGE_GROUP" | python3 -c "import sys, json; g=json.load(sys.stdin); print(len(g.get('scenes', {})))")

        # Also check for knowledge-availability validation failures
        KNOWLEDGE_FAILURES=$(echo "$GAP_ANALYSIS" | python3 -c "
import sys, json
gaps = json.load(sys.stdin)
kf = [f for f in gaps['validation']['failures'] if f['category'] == 'knowledge']
print(len(kf))
")

        if [[ "$KNOWLEDGE_COUNT" != "0" || "$KNOWLEDGE_FAILURES" != "0" ]]; then
            log "Running sequential knowledge fix (${KNOWLEDGE_COUNT} empty fields, ${KNOWLEDGE_FAILURES} wording mismatches)..."

            _SF_INVOCATION_START=$(date +%s)
            export _SF_INVOCATION_START

            PYTHONPATH="$PYTHON_LIB" python3 -c "
import os, json
from storyforge.elaborate import get_scenes, update_scene
from storyforge.prompts_elaborate import build_knowledge_fix_prompt, csv_block_to_rows
from storyforge.api import invoke, extract_text

ref_dir = '${REF_DIR}'
scenes_dir = '${SCENES_DIR}'
project_dir = '${PROJECT_DIR}'
model = '${GAP_MODEL}'
log_dir = '${GAP_DIR}/knowledge-logs'
os.makedirs(log_dir, exist_ok=True)

# Get all scenes in seq order
all_scenes = get_scenes(ref_dir, columns=[
    'id', 'seq', 'knowledge_in', 'knowledge_out', 'continuity_deps',
])

# Build cumulative knowledge
available_knowledge = set()
fixed = 0

for scene in all_scenes:
    sid = scene['id']
    kin = scene.get('knowledge_in', '').strip()
    kout = scene.get('knowledge_out', '').strip()

    # Check if this scene has knowledge issues
    needs_fix = False
    if not kin and int(scene.get('seq', 0)) > 1:
        needs_fix = True
    elif not kout:
        needs_fix = True
    elif kin and available_knowledge:
        facts_in = {f.strip() for f in kin.split(';') if f.strip()}
        if not facts_in.issubset(available_knowledge):
            needs_fix = True

    if needs_fix:
        prompt = build_knowledge_fix_prompt(
            scene_id=sid,
            project_dir=project_dir,
            scenes_dir=scenes_dir,
            available_knowledge=available_knowledge,
        )

        log_file = os.path.join(log_dir, f'{sid}.json')
        response = invoke(prompt, model, max_tokens=512)
        with open(log_file, 'w') as f:
            json.dump(response, f)

        text = extract_text(response)
        rows = csv_block_to_rows(text)
        if rows:
            row = rows[0]
            updates = {k: v for k, v in row.items() if k != 'id' and v.strip()}
            if updates:
                update_scene(sid, ref_dir, updates)
                fixed += 1
                # Update kout for subsequent scenes
                new_kout = updates.get('knowledge_out', kout)
                if new_kout:
                    for fact in new_kout.split(';'):
                        fact = fact.strip()
                        if fact:
                            available_knowledge.add(fact)
                continue

    # Accumulate knowledge from existing data
    if kout:
        for fact in kout.split(';'):
            fact = fact.strip()
            if fact:
                available_knowledge.add(fact)

print(f'Fixed {fixed} scenes')
" 2>&1 | while IFS= read -r line; do log "  $line"; done

            update_pr_task "Fix knowledge chain" "$PROJECT_DIR" 2>/dev/null || true
        fi

        # Commit gap-fill results
        (
            cd "$PROJECT_DIR"
            git add -A
            git commit -m "Elaborate: gap-fill pass" 2>/dev/null || true
            git push 2>/dev/null || true
        )
    fi

    # ============================================================================
    # Validate (always runs, even if no gaps were found)
    # ============================================================================

    log "Running validation..."

    VALIDATE_RESULT=$(PYTHONPATH="$PYTHON_LIB" python3 -c "
import json
from storyforge.elaborate import validate_structure
report = validate_structure('${REF_DIR}')
print(json.dumps(report))
")

    VALIDATE_PASSED=$(echo "$VALIDATE_RESULT" | python3 -c "import sys, json; r=json.load(sys.stdin); print(r['passed'])")
    VALIDATE_FAILURES=$(echo "$VALIDATE_RESULT" | python3 -c "import sys, json; r=json.load(sys.stdin); print(len(r['failures']))")
    INITIAL_GAPS="${TOTAL_GAPS:-0}"

    if [[ "$VALIDATE_PASSED" == "True" ]]; then
        log "Validation passed — all gaps filled."
    else
        log "Validation: ${VALIDATE_FAILURES} issue(s) remaining (started with ${INITIAL_GAPS} field gaps)"
        echo "$VALIDATE_RESULT" | python3 -c "
import sys, json
r = json.load(sys.stdin)
for f in r['failures']:
    sev = f.get('severity', 'blocking')
    scene = f.get('scene_id', '')
    prefix = f'  [{sev}]'
    if scene:
        prefix += f' {scene}:'
    print(f\"{prefix} {f['message']}\")
" | while IFS= read -r line; do log "$line"; done
        log ""
        log "Run gap-fill again to continue filling remaining gaps."
    fi

    update_pr_task "Validate" "$PROJECT_DIR" 2>/dev/null || true

    # Commit validation report
    VALIDATE_FILE="${PROJECT_DIR}/working/validation/validate-$(date '+%Y%m%d-%H%M%S').md"
    mkdir -p "$(dirname "$VALIDATE_FILE")"
    echo "$VALIDATE_RESULT" | python3 -c "
import sys, json
r = json.load(sys.stdin)
print('# Validation Report: gap-fill')
print()
print(f'**Passed:** {r[\"passed\"]}')
print(f'**Checks:** {len(r[\"checks\"])}')
print(f'**Failures:** {len(r[\"failures\"])}')
print()
if r['failures']:
    print('## Failures')
    print()
    for f in r['failures']:
        sev = f.get('severity', 'blocking')
        scene = f.get('scene_id', '')
        msg = f['message']
        if scene:
            print(f'- **[{sev}]** {scene}: {msg}')
        else:
            print(f'- **[{sev}]** {msg}')
" > "$VALIDATE_FILE"

    (
        cd "$PROJECT_DIR"
        git add -A
        git commit -m "Elaborate: gap-fill validation report" 2>/dev/null || true
        git push 2>/dev/null || true
    )

    # Review phase
    run_review_phase "elaboration" "$PROJECT_DIR"

    log ""
    log "============================================"
    log "Gap-fill complete."
    if [[ "$VALIDATE_PASSED" == "True" ]]; then
        log "Validation: PASSED"
    else
        log "Validation: ${VALIDATE_FAILURES} issue(s) remaining — run again to continue"
    fi
    log "============================================"

    print_cost_summary "elaborate-gap-fill" 2>/dev/null || true
    exit 0
fi
```

Insert this block right before the existing `log "Building ${STAGE} prompt..."` line (line 109). The `exit 0` at the end ensures the rest of the script (spine/architecture/map/briefs path) is skipped.

- [ ] **Step 3: Run the script with --dry-run to verify argument parsing**

Run: `cd /Users/cadencedev/Developer/storyforge && ./scripts/storyforge-elaborate --stage gap-fill --dry-run 2>&1 | head -5`
Expected: No "Unknown stage" error. Should log "Analyzing gaps..." or similar.

- [ ] **Step 4: Commit**

```bash
git add scripts/storyforge-elaborate
git commit -m "Add --stage gap-fill to storyforge-elaborate script"
git push
```

---

### Task 5: Update elaborate skill for gap-fill mode

**Files:**
- Modify: `skills/elaborate/SKILL.md`

- [ ] **Step 1: Add gap-fill state detection to Step 2**

In `skills/elaborate/SKILL.md`, replace the stage detection table (lines 33-41) from:

```markdown
| Phase in YAML | scenes.csv rows | Intent depth | Briefs | Current stage |
|---------------|----------------|--------------|--------|---------------|
| spine | 0 | — | — | Needs spine |
| spine | 5-10 | function only | — | Spine done, ready for architecture |
| architecture | 15-25 | has value_shift, threads | — | Architecture done, ready for map |
| scene-map | 40-60 | has characters, on_stage | — | Map done, ready for briefs |
| briefs | 40-60 | full | has goal/conflict/outcome | Briefs done, ready for drafting |
| drafting+ | — | — | — | Past elaboration — redirect to forge |
```

with:

```markdown
| Phase in YAML | scenes.csv rows | Intent depth | Briefs | Validation | Current stage |
|---------------|----------------|--------------|--------|------------|---------------|
| spine | 0 | — | — | — | Needs spine |
| spine | 5-10 | function only | — | — | Spine done, ready for architecture |
| architecture | 15-25 | has value_shift, threads | — | — | Architecture done, ready for map |
| scene-map | 40-60 | has characters, on_stage | — | — | Map done, ready for briefs |
| briefs | 40-60 | full | has goal/conflict/outcome | — | Briefs done, ready for drafting |
| drafting+ | status=drafted | populated but gaps | populated | failures > 0 | **Gap-fill mode** |
| drafting+ | — | — | — | passes | Past elaboration — redirect to forge |
```

- [ ] **Step 2: Add gap-fill mode to Step 3**

In `skills/elaborate/SKILL.md`, add a new entry to the mode list after the "Validate" entry (after line 53):

```markdown
- **Gap-fill state detected** (scenes are drafted, briefs populated, but validation fails) → Gap-fill mode. Analyze gaps and offer to fill them.
```

- [ ] **Step 3: Add Gap-Fill Stage section to Step 4**

In `skills/elaborate/SKILL.md`, add a new subsection after the "Voice Stage" section (after line 161) and before "Character Development":

```markdown
### Gap-Fill Stage (Interactive)

This mode activates when post-extraction data has validation gaps. Run `analyze_gaps()` from `elaborate.py` to categorize failures.

1. Present the gap summary to the author:
   - List each gap group with count of scenes and missing fields
   - Note any structural issues (MICE nesting, timeline order, knowledge wording)
2. Adapt to coaching level:
   - **Full:** "I found N gap types across M scenes. I'll fill them all — starting with the parallel batches."
   - **Coach:** "Here are the gaps I found. Which would you like me to work on?" (present each group as a choice)
   - **Strict:** "Validation report: X scenes missing `type`, Y missing `timeline_day`..." (data only)
3. Offer the standard two execution options:

> **Option A: Run it here**
> I'll work through the gaps in this conversation, filling fields by reading the prose.
>
> **Option B: Run it autonomously**
> Copy this command and run it in a separate terminal:
> ```bash
> cd [project_dir] && [plugin_path]/scripts/storyforge-elaborate --stage gap-fill
> ```
> This creates a branch, fills gaps via batch API, validates, and opens a PR.

If Option A, work through each gap group interactively:
- For each scene with missing fields, read the prose excerpt and propose values
- Apply updates using `update_scene()` from `elaborate.py`
- After all groups, re-run validation
- If gaps remain, offer to continue

4. Commit: `git add -A && git commit -m "Elaborate: gap-fill" && git push`
```

- [ ] **Step 4: Commit**

```bash
git add skills/elaborate/SKILL.md
git commit -m "Update elaborate skill with gap-fill mode detection and stage"
git push
```

---

### Task 6: Update forge skill to recommend gap-fill

**Files:**
- Modify: `skills/forge/SKILL.md`

- [ ] **Step 1: Add gap-fill detection to Guided Mode priorities**

In `skills/forge/SKILL.md`, in the Guided Mode section (lines 156-172), add a new priority between item 1 and item 2. Change:

```markdown
**1. Elaboration phase:** If phase is `spine`/`architecture`/`scene-map`/`briefs` → "Continue elaboration" → invoke `elaborate`.

**2. Ready to draft:** If briefs are complete and validated → "Draft your scenes" → provide `./storyforge write` command.
```

to:

```markdown
**1. Elaboration phase:** If phase is `spine`/`architecture`/`scene-map`/`briefs` → "Continue elaboration" → invoke `elaborate`.

**1.5. Post-extraction gaps:** If `scenes.csv` has rows with `status=drafted` AND `scene-briefs.csv` is populated AND `validate_structure()` returns failures > 0 → "Your extracted data has structural gaps. Run elaborate to fill them." → invoke `elaborate` (which will detect gap-fill state).

**2. Ready to draft:** If briefs are complete and validated → "Draft your scenes" → provide `./storyforge write` command.
```

- [ ] **Step 2: Renumber subsequent priorities**

Renumber 2→2, 3→3, etc. (the existing numbering is fine since 1.5 slots between 1 and 2).

- [ ] **Step 3: Commit**

```bash
git add skills/forge/SKILL.md
git commit -m "Update forge skill to recommend gap-fill after extraction"
git push
```

---

### Task 7: Test fixtures for gap-fill scenarios

**Files:**
- Create: `tests/fixtures/test-project/scenes/act1-sc01.md` (minimal prose fixture)
- Create: `tests/fixtures/test-project/scenes/act1-sc02.md`

The existing test fixtures have scene CSV data but no prose files for the `build_gap_fill_prompt` tests to use in integration. The unit tests in Tasks 2-3 create their own tmp fixtures, but having prose files in the standard fixture dir enables future integration tests.

- [ ] **Step 1: Create minimal prose fixtures**

```bash
mkdir -p tests/fixtures/test-project/scenes
```

Write `tests/fixtures/test-project/scenes/act1-sc01.md`:

```markdown
Dorren Hayle spread the quarterly pressure maps across the lightbox, the translucent sheets layering atop one another like geological strata. The eastern sector readings caught his eye first — a cluster of values that sat within acceptable variance but formed a pattern he hadn't seen before.

"The eastern readings are within acceptable variance," he noted aloud, more to convince himself than inform Tessa, who was cataloguing samples at the far bench.

She glanced up. "Acceptable is not the same as explained, Dorren."

He filed the anomaly as instrument error in the official log. But in his private journal — the leather-bound book he kept in the false bottom of his desk drawer — he sketched the pattern and wrote a single question mark beneath it.
```

Write `tests/fixtures/test-project/scenes/act1-sc02.md`:

```markdown
The forty-year archive occupied the lowest level of the Cartography Office, where the air smelled of foxed paper and lamp oil. Dorren carried three maps: the current quarter, the twenty-year survey, and the oldest he could find — a hand-drawn sheet from the founding era.

He overlaid them on the comparison table. The village was there forty years ago. It was there twenty years ago. It was not there now.

"It was there forty years ago. It isn't there now. There is no note," he whispered, running his fingers across the blank space where the village should have been. No removal order. No marginal annotation. No record at all.

Someone had erased a village from the maps, and done so without leaving a trace.
```

- [ ] **Step 2: Commit**

```bash
git add tests/fixtures/test-project/scenes/
git commit -m "Add prose fixtures for gap-fill integration tests"
git push
```

---

### Task 8: Bump version and final verification

**Files:**
- Modify: `.claude-plugin/plugin.json` (bump version)

- [ ] **Step 1: Run the full test suite**

Run: `./tests/run-tests.sh`
Expected: All tests pass, including new gap-fill tests.

- [ ] **Step 2: Bump version**

Read `.claude-plugin/plugin.json` and bump the minor version (e.g., `0.49.0` → `0.50.0`).

- [ ] **Step 3: Commit version bump**

```bash
git add .claude-plugin/plugin.json
git commit -m "Bump version to 0.50.0"
git push
```
