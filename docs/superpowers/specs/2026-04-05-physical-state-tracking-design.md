# Physical State Tracking for Characters Across Scenes

## Problem

Novels where characters accumulate injuries, exhaustion, or visible changes need a way to track physical state across scenes. Currently this information is buried in prose descriptions in `key_actions` or `key_dialogue` fields in scene-briefs.csv. A drafter has to hunt for it, and continuity breaks easily.

**Concrete example (Unicorn Tail, 56 scenes):**
- Mal's arm breaks in scene `burns` — needs to be in a sling through at least scene `mal-back` (23 scenes)
- Zara's blistered hand from Hunter residue, escalating Sight damage through `hemorrhage`
- Dex's fire dims permanently at `gathering` — every subsequent scene
- Oren's fragility after near-erasure at `strikes`

The existing knowledge chain (`knowledge_in`/`knowledge_out`) tracks what characters know, but not what has happened to them physically. These are different: knowledge is epistemic (changes decisions), physical state is embodied (changes capability, appearance, and how prose renders action).

## Approach

Follow the carry-forward column pattern established by the knowledge chain. Two new columns on `scene-briefs.csv` — `physical_state_in` and `physical_state_out` — backed by a canonical registry in `reference/physical-states.csv`.

**Why carry-forward columns instead of a state-change log:**
- State is resolved at brief time (sequential), making drafting prompts self-contained
- Parallel drafting waves work without runtime state computation — each scene already has its states pre-populated
- Every integration point (schema, validation, elaboration, reconciliation, extraction, scoring, prompts) has a direct analog in the knowledge chain
- The drafter gets exactly what it needs: current-moment descriptions, not raw logs to interpret

## Data Model

### Registry: `reference/physical-states.csv`

Canonical registry of all physical state entries. Keyed by unique ID, scoped per character.

```
id|character|description|category|acquired|resolves|action_gating
```

| Column | Type | Description |
|--------|------|-------------|
| `id` | kebab-case slug | Unique identifier (e.g., `broken-arm-mal`) |
| `character` | registry (characters.csv) | Which character this state belongs to |
| `description` | free text | Concise, prose-usable description (e.g., "left arm broken, splinted") |
| `category` | enum | `injury`, `equipment`, `ability`, `appearance`, `fatigue` |
| `acquired` | scene ID | Scene where this state is first added to `physical_state_out` |
| `resolves` | scene ID or `never` | Scene where the state is removed from `physical_state_out`, or `never` for permanent states |
| `action_gating` | boolean | Whether this state constrains what the character can physically do |

**Category definitions:**
- **injury** — Broken bones, cuts, burns, wounds. Limits capability, requires acknowledgment in action scenes.
- **equipment** — Items gained or lost that enable or prevent action. Gun acquired, map lost, disguise worn.
- **ability** — Powers, skills, or capacities gained or lost. Can now pick locks; lost the ability to walk.
- **appearance** — Visible changes. New scar, lost weight, different clothing. Doesn't gate action but inconsistency is jarring.
- **fatigue** — Exhaustion, hunger, sleep deprivation. Affects characterization and pacing.

### Columns: `scene-briefs.csv`

Two new columns added to scene-briefs.csv:

```
physical_state_in|physical_state_out
```

| Column | Type | Description |
|--------|------|-------------|
| `physical_state_in` | registry (physical-states.csv), array | State IDs active when scene begins. Semicolon-separated. |
| `physical_state_out` | registry (physical-states.csv), array | State IDs active when scene ends. Includes `physical_state_in` plus new states, minus resolved states. |

**Same pattern as `knowledge_in`/`knowledge_out`:**
- `physical_state_in` for scene N must be a subset of states established in `physical_state_out` from scenes 1..N-1
- New states added in `physical_state_out` must have a corresponding entry in the registry
- States removed in `physical_state_out` (present in `physical_state_in` but absent in `physical_state_out`) represent resolution during the scene

### Granularity Rules

The same litmus test as knowledge facts, adapted for physical state:

**Track it if:** A drafter who knows about this state writes a *different scene* than one who doesn't. The character physically cannot do something, visibly looks different, or has/lacks a critical object.

**Don't track:** Temporary emotional expressions (crying, blushing), scene-local conditions (wet from rain), minor cosmetic details (hair messy). These belong in `emotions` or `key_actions`.

**Target density:** 0-2 state changes per scene. A 50-scene novel should have 15-40 total state entries, not 200+.

## Schema Definition

Add to `COLUMN_SCHEMA` in `schema.py`:

```python
'physical_state_in': {
    'type': 'registry', 'registry': 'physical-states.csv', 'array': True,
    'file': 'scene-briefs.csv', 'stage': 'brief',
    'description': 'Physical state IDs active when scene begins. Normalized against reference/physical-states.csv.',
},
'physical_state_out': {
    'type': 'registry', 'registry': 'physical-states.csv', 'array': True,
    'file': 'scene-briefs.csv', 'stage': 'brief',
    'description': 'Physical state IDs active when scene ends. Includes physical_state_in plus new, minus resolved. Normalized against reference/physical-states.csv.',
},
```

Registry schema for `physical-states.csv`:

```python
'physical_states_character': {
    'type': 'registry', 'registry': 'characters.csv', 'array': False,
    'file': 'physical-states.csv', 'stage': 'brief',
    'description': 'Character this state belongs to.',
},
'physical_states_category': {
    'type': 'enum', 'values': VALID_PHYSICAL_STATE_CATEGORIES,
    'file': 'physical-states.csv', 'stage': 'brief',
    'description': 'State category: injury, equipment, ability, appearance, fatigue.',
},
'physical_states_acquired': {
    'type': 'scene_ids', 'file': 'physical-states.csv', 'stage': 'brief',
    'description': 'Scene where this state is acquired.',
},
'physical_states_resolves': {
    'type': 'free_text', 'file': 'physical-states.csv', 'stage': 'brief',
    'description': 'Scene ID where resolved, or "never" for permanent.',
},
'physical_states_action_gating': {
    'type': 'boolean', 'file': 'physical-states.csv', 'stage': 'brief',
    'description': 'Whether this state constrains character capability.',
},
```

## Validation

### Structural Validation (elaborate.py)

New function `_validate_physical_states()`, called from `validate_structure()`. Mirrors `_validate_knowledge()`.

**Check 1 — State persistence (advisory):**
Walk scenes in seq order, accumulating `available_states` per character. For each scene, verify that every ID in `physical_state_in` exists in `available_states` for the relevant character. A state that appears without being acquired is flagged.

```python
def _validate_physical_states(scenes_map, briefs_map, checks):
    """Check physical state flow: physical_state_in must come from prior scenes."""
    sorted_ids = sorted(scenes_map.keys(),
                        key=lambda sid: int(scenes_map[sid].get('seq', 0)))

    available_states = set()

    for sid in sorted_ids:
        brief = briefs_map.get(sid, {})
        state_in = brief.get('physical_state_in', '').strip()

        if state_in:
            states_in = {s.strip() for s in state_in.split(';') if s.strip()}
            unknown = states_in - available_states
            if unknown:
                checks.append(_check(
                    'physical_state', 'state-availability', False,
                    f"Scene {sid} references physical states not established by prior scenes: "
                    f"{sorted(unknown)}",
                    scene_id=sid,
                    severity='advisory',
                ))

        state_out = brief.get('physical_state_out', '').strip()
        if state_out:
            for state_id in state_out.split(';'):
                state_id = state_id.strip()
                if state_id:
                    available_states.add(state_id)
```

Note: The pseudocode uses a flat set for simplicity. The actual implementation should load the physical-states.csv registry to scope states per character (using the `character` column), so that validation can also flag scenes where an on-stage character has active states not listed in `physical_state_in`.

**Check 2 — State disappearance (advisory):**
If a state is in `physical_state_in` for scene N but absent from `physical_state_out` for scene N, and the state's `resolves` field doesn't point to scene N, flag it. A state that silently vanishes without resolution is the most common continuity error.

**Check 3 — On-stage relevance (advisory):**
If a character has an active action-gating state and is in `on_stage` for a scene, but the state ID is not in `physical_state_in`, flag it. The scene should acknowledge the state.

### Schema Validation (schema.py)

Standard registry validation — every ID in `physical_state_in`/`physical_state_out` must exist in `physical-states.csv`. Handled automatically by existing `_check_registry()` infrastructure.

### Granularity Validation (schema.py)

New function `validate_physical_state_granularity()`, parallel to `validate_knowledge_granularity()`:
- Flag state descriptions > 20 words (too verbose for carry-forward)
- Flag scenes with > 3 new states (too many changes at once)
- Flag registries with > 2× scene count entries (over-specified)

## Structural Scoring

New scoring function `score_physical_state_chain()` in `structural.py`, parallel to `score_knowledge_chain()`.

**Four dimensions:**

1. **Coverage (40%)** — What fraction of scenes with on-stage characters who have active states include those states in `physical_state_in`? Low coverage means states are being ignored.

2. **Persistence (35%)** — What fraction of states that should persist (based on `acquired`/`resolves` range) actually appear in the correct range of scenes? Gaps indicate dropped states.

3. **Action-gating enforcement (15%)** — For scenes with action-gating states, does `key_actions` avoid incompatible actions? Keyword-level check (e.g., "grips with both hands" + broken arm state). Advisory, not deterministic.

4. **Density (10%)** — `min(1.0, total_states / (n * 0.3))`. Penalizes too few states relative to scene count. Lower weight than knowledge because not every novel needs heavy physical state tracking.

**Composite:** `coverage * 0.4 + persistence * 0.35 + gating * 0.15 + density * 0.10`

**Orchestrator weight:** `'physical_state': 0.3` (lower than knowledge_chain's 0.5 — physical state is important but optional for some genres).

**Target score:** `0.50`

Add `physical_state_in` and `physical_state_out` to `ENRICHMENT_FIELDS` in structural.py.

## Elaboration Pipeline Integration

### Brief Stage (prompts_elaborate.py)

Add physical state instructions to `build_briefs_prompt()`, alongside the existing knowledge instructions:

```
- **physical_state_in**: Semicolon-separated state IDs the POV character (and on-stage characters) carry INTO this scene. Use EXACT IDs from prior scenes' physical_state_out. Only include states that affect what characters can do, how they look, or what they have. Injuries, equipment, abilities, appearance changes, fatigue.
- **physical_state_out**: physical_state_in plus 0-2 NEW states acquired during this scene, minus any states that resolve during this scene. If a character's broken arm gets treated, remove the broken-arm ID and add a splinted-arm ID.
```

Rules section addition:
```
- physical_state_in must reference IDs established in prior scenes' physical_state_out
- Target 0-2 state changes per scene. A full novel should have 15-40 total state entries.
- Action-gating states (injuries, equipment) must be reflected in key_actions for scenes where the character acts
- States persist until explicitly resolved — do not silently drop them
```

Output format: add `physical_state_in|physical_state_out` to the briefs-csv header.

### Knowledge Fix Prompt Pattern

New function `build_physical_state_fix_prompt()` in prompts_elaborate.py, parallel to `build_knowledge_fix_prompt()`. Called when validation flags state-availability issues. Shows:
- Scene prose (first 500 words)
- Current (possibly wrong) physical_state_in/physical_state_out
- Available states from prior scenes with exact IDs
- Registry entries for reference

## Drafting Prompt Integration

### prompts.py — `build_scene_prompt_from_briefs()`

Add a new section to the drafting prompt, between dependency context and voice guide:

```python
# Physical state context
state_in = scene.get('physical_state_in', '').strip()
if state_in:
    state_ids = [s.strip() for s in state_in.split(';') if s.strip()]
    # Resolve state IDs to descriptions via registry
    state_lines = []
    for sid in state_ids:
        state_entry = states_registry.get(sid, {})
        char = state_entry.get('character', 'unknown')
        desc = state_entry.get('description', sid)
        gating = state_entry.get('action_gating', 'false') == 'true'
        line = f"- **{char}**: {desc}"
        if gating:
            line += " *(action-gating)*"
        state_lines.append(line)

    state_block = "## Active Physical States\n\n"
    state_block += "Characters entering this scene carry these states:\n\n"
    state_block += '\n'.join(state_lines)
```

Add to the task block (coaching_level == 'full'):
```
- Acknowledge all action-gating physical states — characters cannot use injured limbs, don't have lost equipment
- Physical states in physical_state_out must be reflected in the prose (acquired through action, not narration)
```

Add to the dependency scene summary:
```python
dep_summary = (
    f"**{dep_id}** — {dep.get('function', '')}\n"
    f"  outcome: {dep.get('outcome', '')}\n"
    f"  knowledge_out: {dep.get('knowledge_out', '')}\n"
    f"  physical_state_out: {dep.get('physical_state_out', '')}\n"
    f"  emotional_arc: {dep.get('emotional_arc', '')}"
)
```

## Extraction (Reverse Elaboration)

### Phase 3c: Physical State Chain (Sequential)

New extraction phase, runs after Phase 3b (knowledge). Must be sequential because state accumulates across scenes.

New function `build_physical_state_prompt()` in extract.py:

**Inputs:**
- scene_id, scene_text
- skeleton (for pov, on_stage)
- prior_states: dict mapping character → set of active state IDs with descriptions
- prior_scene_summaries (last 10)
- registries_text (existing physical-states.csv if present)

**Prompt pattern (mirrors `build_knowledge_prompt`):**
```
Track the physical state of characters through this scene.

## On-stage characters: {on_stage}

## Active physical states entering this scene:
{prior_states_formatted}

## Scene: {scene_id}
{scene_text}

## Instructions

Extract physical state changes. Only track states that affect what characters can do, how they look, or what they have.

Categories: injury, equipment, ability, appearance, fatigue.

Litmus test: Would a drafter who knows about this state write a *different scene* than one who doesn't?

PHYSICAL_STATE_IN: [semicolon-separated state IDs active at START]
PHYSICAL_STATE_OUT: [semicolon-separated state IDs active at END — state_in plus new, minus resolved]
NEW_STATES: [one per line: id|character|description|category|action_gating]
RESOLVED_STATES: [semicolon-separated state IDs that resolve during this scene]
```

New function `parse_physical_state_response()`: Extract labeled fields, return dict with `physical_state_in`, `physical_state_out`, `_new_states` (list of registry rows), `_resolved` (list of IDs).

### Integration with `storyforge-extract`

After Phase 3b commits, run Phase 3c. Then reconciliation picks up `physical-states` as a new domain.

## Reconciliation

### New Domain: `physical-states` (after Phase 3c)

Add to `reconcile.py`:

**Collection:** `_collect_physical_state_chain()` — gather all `physical_state_in`/`physical_state_out` values in scene seq order plus all `NEW_STATES` entries from extraction.

**Registry prompt:** Send raw state entries + existing registry to Opus. Instructions:
- Merge variants (same injury described differently in different scenes)
- Assign canonical IDs (kebab-case: `broken-arm-mal`, `has-compass-elena`)
- Validate character names against characters.csv
- Confirm `acquired` and `resolves` scene IDs exist in scenes.csv
- Ensure `category` and `action_gating` are set for every entry

**Normalization:** Resolve `physical_state_in` and `physical_state_out` to canonical IDs. Write updated scene-briefs.csv and physical-states.csv.

**Domain order:** Runs in Phase 3, after knowledge and outcomes: characters → locations → values → mice-threads → knowledge → outcomes → **physical-states**.

## Continuity Dependencies

Physical states should influence `continuity_deps`. If scene N acquires a state that scene M references in `physical_state_in`, scene M depends on scene N.

The briefs prompt already instructs: "continuity_deps should list the minimum set of scenes whose knowledge_out this scene needs." Expand to: "continuity_deps should list scenes whose knowledge_out or physical_state_out this scene needs."

This ensures the wave planner (`compute_drafting_waves()`) correctly orders scenes with physical state dependencies. No changes needed to the wave planner itself — it already reads `continuity_deps`.

## Tests

### test-physical-state.sh

New test suite covering:

**CSV operations:**
- Read/write `physical-states.csv` registry
- Read/write `physical_state_in`/`physical_state_out` columns in scene-briefs.csv

**Schema validation:**
- Registry type validation for `physical_state_in`/`physical_state_out`
- Category enum validation
- Action_gating boolean validation
- Scene_ids validation for `acquired`/`resolves`

**Structural validation:**
- State persistence: state in `physical_state_in` of scene N must come from prior `physical_state_out`
- State disappearance: state in `physical_state_in` but not `physical_state_out` without resolution
- On-stage relevance: character with active state is on-stage but state not in `physical_state_in`

**Scoring:**
- `score_physical_state_chain()` returns valid 0-1 score
- Coverage, persistence, action-gating, density dimensions
- Edge cases: no states (score 0), all states present (score 1), partial coverage

**Fixtures:**
- Add `physical-states.csv` to `tests/fixtures/test-project/reference/`
- Add `physical_state_in`/`physical_state_out` columns to fixture `scene-briefs.csv`

### Existing test updates

- `test-schema.sh`: Add cases for `physical_state_in`/`physical_state_out` registry validation
- `test-structural.sh`: Add `score_physical_state_chain()` to structural score tests
- `test-elaborate.sh`: Update `validate_structure()` tests to include physical state checks

## File Changes Summary

| File | Change |
|------|--------|
| `reference/physical-states.csv` | New registry file (per project) |
| `reference/scene-briefs.csv` | Add `physical_state_in`, `physical_state_out` columns |
| `scripts/lib/python/storyforge/schema.py` | Add column schema entries, enum, granularity validation |
| `scripts/lib/python/storyforge/elaborate.py` | Add `_validate_physical_states()`, call from `validate_structure()` |
| `scripts/lib/python/storyforge/structural.py` | Add `score_physical_state_chain()`, add to orchestrator |
| `scripts/lib/python/storyforge/prompts.py` | Add physical state block to drafting prompts |
| `scripts/lib/python/storyforge/prompts_elaborate.py` | Add instructions to briefs prompt, add fix prompt |
| `scripts/lib/python/storyforge/extract.py` | Add Phase 3c: `build_physical_state_prompt()`, parser |
| `scripts/lib/python/storyforge/reconcile.py` | Add `physical-states` domain |
| `scripts/storyforge-extract` | Add Phase 3c orchestration |
| `scripts/storyforge-reconcile` | Add `physical-states` to domain list |
| `scripts/storyforge-validate` | Physical state checks included via `validate_structure()` |
| `tests/test-physical-state.sh` | New test suite |
| `tests/fixtures/test-project/reference/physical-states.csv` | New fixture |
| `tests/fixtures/test-project/reference/scene-briefs.csv` | Add columns to fixture |

## Cost Estimate

Per reconciliation of physical-states domain on a 100-scene novel:
- 1 Opus API call (registry building + normalization)
- ~20K input tokens, ~5K output tokens
- ~$0.50-1.00

Per extraction Phase 3c on a 100-scene novel:
- 100 sequential Sonnet calls (one per scene)
- ~15K input tokens per call, ~500 output tokens per call
- ~$5-8 total

## Migration

Existing projects without physical state data are unaffected:
- Empty `physical_state_in`/`physical_state_out` columns pass validation (not required fields)
- `score_physical_state_chain()` returns 0.0 with no findings when no states exist
- Schema validation skips empty registry columns when registry file doesn't exist
- No changes needed to existing scene-briefs.csv files until the author chooses to add physical state tracking
