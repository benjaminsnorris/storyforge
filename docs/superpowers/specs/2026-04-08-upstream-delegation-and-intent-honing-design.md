# Upstream Delegation to Hone & Intent Quality Detection

**Date:** 2026-04-08
**Status:** Proposed

## Problem

Revision passes with `fix_location=brief` silently produce zero changes. The upstream path in `cmd_revise.py` builds a generic prompt that doesn't specify CSV schemas, causing Claude to return `scene_id` instead of `id` as the key column. The merge code finds no matching rows and marks the pass as "completed" with nothing written.

Meanwhile, `hone` already has robust schema-aware CSV editing for briefs (abstract detection, concretization prompts, trim prompts). But `hone` has no support for intent quality, and no way to accept external evaluation findings as input.

## Solution

Three changes:

1. **Revise delegates upstream passes to hone** instead of building its own prompts
2. **Hone accepts external findings** via a findings file, so evaluation-driven fixes flow through hone's quality pipeline
3. **Hone gains intent quality detection and fixing** (`hone_intent()` alongside `hone_briefs()`)
4. **Revise validates that changes happened** before marking a pass complete

## Design

### 1. Findings File Format

When revise encounters a pass with `fix_location` in `(brief, intent)`, it writes a findings file:

**Path:** `working/plans/hone-findings-{pass_name}.csv`

**Format:** Pipe-delimited CSV:

```
scene_id|target_file|fields|guidance
four-at-table|scene-briefs.csv|goal;conflict;crisis;decision|Fix hallucinated characters: Voss, Dren, Linn don't exist in the novel
settling-rhythm|scene-briefs.csv|conflict;outcome|Conflict is abstract — needs physical obstacle Kael can act against
not-alone|scene-intent.csv|function;emotional_arc|Function is vague — center on Kael's deliberation as dramatic spine
```

Columns:
- `scene_id` — which scene to fix
- `target_file` — which CSV to modify (`scene-briefs.csv` or `scene-intent.csv`)
- `fields` — semicolon-separated field names to rewrite
- `guidance` — pass-specific instruction from the revision plan

### 2. Hone: External Findings Support

#### hone.py changes

New function `load_external_findings(findings_file)`:
- Reads the findings CSV
- Returns a list of issue dicts in hone's standard format:
  ```python
  {
      'scene_id': 'four-at-table',
      'field': 'goal',
      'issue': 'evaluation',
      'value': '<current value from CSV>',
      'guidance': 'Fix hallucinated characters...',
  }
  ```
- One issue dict per scene+field combination (a row with `fields=goal;conflict` becomes two issue dicts)

Modified `hone_briefs()` signature:
```python
def hone_briefs(
    ref_dir, project_dir, scene_ids=None, threshold=3.5,
    model='', log_dir='', coaching_level='full', dry_run=False,
    findings_file=None,  # NEW
) -> dict:
```

When `findings_file` is provided:
- Load external findings via `load_external_findings()`
- Filter to entries where `target_file == 'scene-briefs.csv'`
- Merge with issues from `detect_brief_issues()` (external findings take priority — if both flag the same scene+field, keep the external one since it has specific guidance)
- Process `issue='evaluation'` entries with a new `build_evaluation_fix_prompt()`

New function `build_evaluation_fix_prompt(scene_id, fields, current_values, guidance, voice_guide, character_entry)`:
- Similar to `build_concretize_prompt` but includes the evaluation guidance text
- Includes the exact column schema for the target file (from `_BRIEFS_COLS`)
- Asks Claude to rewrite specific fields according to the guidance
- Output format: same labeled-line format as `build_concretize_prompt` (`field: [rewritten value]`)
- Parsed by the existing `parse_concretize_response()`

#### cmd_hone.py changes

New CLI flag: `--findings <file>`

```python
parser.add_argument('--findings', metavar='FILE',
                    help='External findings file (from evaluation/revision)')
```

When provided:
- Pass `findings_file` to `hone_briefs()` and `hone_intent()`
- Compatible with `--domain briefs`, `--domain intent`, or domain auto-detection from the findings file

### 3. Hone: Intent Quality Detection (`hone_intent()`)

New function in `hone.py`. Follows the same pattern as `hone_briefs()`.

#### Intent Issue Detectors

`detect_intent_issues(intent_map, scenes_map, briefs_map, scene_ids=None)` — runs all detectors, returns combined issue list.

**Detectors (priority order):**

**a) `detect_vague_function(intent_map, scene_ids)`**
- Scans `function` field for abstract language without concrete action
- Abstract indicators: realizes, deepens, emerges, transforms, grows, learns, bonds, connects, evolves, processes, reflects, grapples
- Concrete indicators: says, asks, discovers, decides, refuses, confesses, chooses, confronts, reveals, finds, witnesses, reads, writes, signs
- Flags when: abstract_count >= 2 AND abstract_count > concrete_count
- Returns: `{scene_id, field='function', issue='vague', abstract_count, concrete_count, value}`

**b) `detect_overlong_function(intent_map, scene_ids)`**
- Function is a scene-level statement, not a brief summary
- Flags when: char_count > 400 (functions should be 1-3 sentences)
- Returns: `{scene_id, field='function', issue='overlong', char_count, value}`

**c) `detect_flat_emotional_arc(intent_map, scene_ids)`**
- Emotional arc should be a transition ("X giving way to Y"), not a single state
- Scans for transition phrases: "giving way to", "shifting to", "breaking into", "dissolving into", "transforming into", "to"
- Flags when: non-empty field has no transition phrase
- Returns: `{scene_id, field='emotional_arc', issue='flat', value}`

**d) `detect_abstract_emotional_arc(intent_map, scene_ids)`**
- Emotional arc should use grounded emotion words, not abstractions
- Abstract: tension, emotion, feeling, turmoil, struggle, growth, shift, realization, understanding, complexity, process
- Grounded: grief, joy, fear, anger, shame, relief, longing, tenderness, dread, exhilaration, guilt, warmth, pride, regret, hope, despair
- Flags when: abstract_count > grounded_count AND field is non-empty
- Returns: `{scene_id, field='emotional_arc', issue='abstract', abstract_count, concrete_count, value}`

**e) `detect_onstage_subset_violation(intent_map, scene_ids)`**
- Every entry in `on_stage` must also appear in `characters`
- Flags when: any on_stage entry is not in the characters set
- Returns: `{scene_id, field='on_stage', issue='not_subset', violating=[...], value}`

**f) `detect_value_shift_outcome_mismatch(intent_map, briefs_map, scene_ids)`**
- Cross-file check: value_shift polarity should align with outcome
- Rules:
  - outcome=`yes` → expect shift ending positive (`/+` or `/++`)
  - outcome=`no` → expect shift ending negative (`/-` or `/--`)
  - outcome=`yes-but` → any mixed shift acceptable
  - outcome=`no-and` → expect shift ending negative
- Flags clear mismatches (e.g., outcome=`yes` with shift=`+/-`)
- Returns: `{scene_id, field='value_shift', issue='outcome_mismatch', value_shift, outcome, value}`

#### Intent Fixing

`hone_intent()` signature:

```python
def hone_intent(
    ref_dir, project_dir, scene_ids=None,
    model='', log_dir='', coaching_level='full', dry_run=False,
    findings_file=None,
) -> dict:
```

Flow:
1. Load intent_map, scenes_map, briefs_map
2. Run `detect_intent_issues()` to find quality issues
3. If `findings_file` provided, load and merge external findings (filtered to `target_file == 'scene-intent.csv'`)
4. Group issues by scene
5. For `issue='vague'` and `issue='abstract'` on function/emotional_arc: use `build_intent_fix_prompt()` (new) to rewrite via API
6. For `issue='evaluation'`: use `build_evaluation_fix_prompt()` with guidance
7. For structural issues (not_subset, outcome_mismatch): fix deterministically (no API call needed)
8. Write back to `scene-intent.csv`

New function `build_intent_fix_prompt(scene_id, fields, current_values, issues, voice_guide)`:
- Tells Claude which specific issue each field has
- For vague functions: "Rewrite as a testable statement — what the character physically does or decides"
- For flat emotional arcs: "Rewrite as 'X giving way to Y' with grounded emotion words"
- For abstract emotional arcs: "Replace abstract emotion words with concrete ones"
- Output format: labeled lines, parsed by existing `parse_concretize_response()`

#### cmd_hone.py changes for intent domain

Add `'intent'` as a recognized domain:

```python
elif domain == 'intent':
    _run_intent_domain(ref_dir, project_dir, log_dir, model, coaching,
                       scene_filter, dry_run, findings_file)
```

`_run_intent_domain()` follows the same pattern as `_run_briefs_domain()`:
- Load data, run detection, report summary, call `hone_intent()` if issues found

### 4. Revise: Delegation and Validation Gate

#### Replacing the upstream path

In `cmd_revise.py`, replace lines 1368-1550 (the inline upstream prompt building and CSV parsing) with:

```python
if fix_location in ('brief', 'intent'):
    # Write findings file for hone
    findings_path = os.path.join(
        project_dir, 'working', 'plans',
        f'hone-findings-{pass_name}.csv')
    _write_hone_findings(findings_path, fix_location, targets, guidance)

    # Snapshot target CSV for validation
    target_csv = os.path.join(project_dir, 'reference',
        'scene-briefs.csv' if fix_location == 'brief' else 'scene-intent.csv')
    old_hash = _file_hash(target_csv)

    # Delegate to hone
    from storyforge.hone import hone_briefs, hone_intent
    hone_fn = hone_briefs if fix_location == 'brief' else hone_intent
    result = hone_fn(
        ref_dir=os.path.join(project_dir, 'reference'),
        project_dir=project_dir,
        scene_ids=[t.strip() for t in targets.split(';')] if targets else None,
        model=pass_model,
        log_dir=log_dir,
        coaching_level=effective_coaching,
        findings_file=findings_path,
    )

    # Validation gate
    new_hash = _file_hash(target_csv)
    if old_hash == new_hash:
        log(f'  FAILED: Pass "{pass_name}" produced no changes to {os.path.basename(target_csv)}')
        _update_pass_field(plan_rows, pass_num, 'status', 'failed', csv_plan_file)
        # Continue to next pass — don't exit
        continue
    else:
        fields_changed = result.get('fields_rewritten', 0)
        scenes_changed = result.get('scenes_rewritten', 0)
        log(f'  Upstream: {scenes_changed} scenes, {fields_changed} fields rewritten')

    # Redraft affected scenes (full coaching mode only)
    if effective_coaching == 'full' and targets:
        affected = [t.strip() for t in targets.split(';') if t.strip()]
        _redraft_from_briefs(project_dir, affected, pass_model, log_dir)
```

#### `_write_hone_findings()`

```python
def _write_hone_findings(path, fix_location, targets, guidance):
    """Write a findings file for hone from revision plan pass data."""
    os.makedirs(os.path.dirname(path), exist_ok=True)
    target_file = 'scene-briefs.csv' if fix_location == 'brief' else 'scene-intent.csv'
    scene_ids = [t.strip() for t in targets.split(';')] if targets else []
    with open(path, 'w') as f:
        f.write('scene_id|target_file|fields|guidance\n')
        for sid in scene_ids:
            # All fields for the target file (hone will detect which need work)
            f.write(f'{sid}|{target_file}||{guidance}\n')
```

Note: `fields` is left empty to let hone detect which fields need work. The guidance provides the evaluation context.

#### `_file_hash()`

```python
import hashlib

def _file_hash(path):
    """SHA-256 of file contents, or empty string if file doesn't exist."""
    if not os.path.isfile(path):
        return ''
    with open(path, 'rb') as f:
        return hashlib.sha256(f.read()).hexdigest()
```

#### `_redraft_from_briefs()`

```python
def _redraft_from_briefs(project_dir, scene_ids, model, log_dir):
    """Re-draft scenes from their updated briefs."""
    from storyforge.cmd_write import _build_prompt, _extract_scene_from_response
    from storyforge.api import invoke_to_file

    log(f'  Redrafting {len(scene_ids)} scenes from updated briefs...')
    scenes_dir = os.path.join(project_dir, 'scenes')

    for sid in scene_ids:
        log(f'    Redrafting: {sid}')
        prompt = _build_prompt(sid, project_dir, 'full', use_briefs=True)
        log_file = os.path.join(log_dir, f'redraft-{sid}.json')
        invoke_to_file(prompt, model, log_file, max_tokens=16384,
                       label=f'redraft {sid}')
        scene_file = os.path.join(scenes_dir, f'{sid}.md')
        _extract_scene_from_response(log_file, scene_file)

    commit_and_push(
        project_dir,
        f'Revision: redraft {len(scene_ids)} scenes from corrected briefs',
        ['scenes/', 'reference/', 'working/'])
```

Uses `cmd_write.py`'s existing `_build_prompt()` (with `use_briefs=True`) and `_extract_scene_from_response()` to build brief-aware drafting prompts and extract prose from API responses.

### 5. What Gets Removed

The entire inline upstream prompt builder and CSV block parser in `cmd_revise.py` (lines 1368-1550):
- The inline prompt at line 1396
- The `parse_stage_response` / `csv_block_to_rows` imports
- The `_read_csv_as_map` / `_write_csv` / `_FILE_MAP` imports
- The `csv_file_map` dict
- The merge loop

This code is replaced by the hone delegation described above.

The `fix_location in ('structural', 'registry')` case stays in revise for now — those pass types are less common and work differently (structural modifies scenes.csv positioning, not content quality).

## Testing

### Unit tests for intent detection (new)

- `test_detect_vague_function` — flags abstract functions, passes concrete ones
- `test_detect_overlong_function` — flags >400 char functions
- `test_detect_flat_emotional_arc` — flags single-state arcs, passes "X giving way to Y"
- `test_detect_abstract_emotional_arc` — flags abstract emotion words
- `test_detect_onstage_subset_violation` — flags on_stage entries not in characters
- `test_detect_value_shift_outcome_mismatch` — flags polarity vs outcome conflicts
- `test_detect_intent_issues_combined` — runs all detectors

### Unit tests for findings file (new)

- `test_load_external_findings` — parses findings CSV into issue dicts
- `test_findings_merge_with_detected` — external findings take priority over detected
- `test_hone_briefs_with_findings` — end-to-end: findings file → brief changes (mocked API)
- `test_hone_intent_with_findings` — end-to-end: findings file → intent changes (mocked API)

### Unit tests for validation gate (new)

- `test_file_hash_consistent` — same content → same hash
- `test_file_hash_detects_change` — different content → different hash
- `test_write_hone_findings` — correct CSV format
- `test_upstream_pass_fails_on_no_change` — pass marked 'failed' when CSV unchanged

### Regression test for the original bug

- `test_upstream_pass_no_longer_silently_succeeds` — simulate the old flow with `scene_id` vs `id` mismatch, verify it now produces actual changes via hone

## Migration

- No data migration needed — findings files are ephemeral (written and consumed within a single revision run)
- Existing revision plans with `fix_location=brief` passes work unchanged — revise reads the same plan format, just delegates differently
- The `--findings` flag on `storyforge hone` is additive — existing hone usage unchanged

## Files Changed

| File | Change |
|------|--------|
| `scripts/lib/python/storyforge/hone.py` | Add `load_external_findings()`, `build_evaluation_fix_prompt()`, `detect_intent_issues()` (6 detectors), `build_intent_fix_prompt()`, `hone_intent()`. Modify `hone_briefs()` to accept `findings_file`. |
| `scripts/lib/python/storyforge/cmd_hone.py` | Add `--findings` flag, `_run_intent_domain()`, add `'intent'` to domain dispatch. |
| `scripts/lib/python/storyforge/cmd_revise.py` | Replace upstream path (lines 1368-1550) with hone delegation + validation gate. Add `_write_hone_findings()`, `_file_hash()`, `_redraft_from_briefs()`. |
| `skills/hone/SKILL.md` | Document intent domain and `--findings` usage. |
| `skills/revise/SKILL.md` | Document that brief/intent passes delegate to hone. |
| `tests/test_hone_intent.py` | New: intent detection tests. |
| `tests/test_hone_findings.py` | New: external findings loading and integration tests. |
| `tests/test_revise_upstream.py` | New: validation gate and delegation tests. |
| `CLAUDE.md` | Add `hone_intent` to shared module docs, add `intent` to hone domain list. |
