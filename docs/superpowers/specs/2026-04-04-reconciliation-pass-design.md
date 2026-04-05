# Post-Extraction Reconciliation Pass

## Problem

Per-scene extraction (Sonnet) produces good individual results but no cross-scene consistency. Evidence from four novels:

- **Knowledge facts**: Same concept gets different wording in different scenes. Backstory facts appear in knowledge_in but were never established in any prior knowledge_out. (Governor: 5 missing knowledge_in; Meridian: 62 chain failures)
- **MICE threads**: Opens and closes use different names for the same thread. Types missing. (Governor: 149 nesting violations; Meridian: 107; Thornwall: 20)
- **Values**: Over-specified per scene rather than mapped to core themes. (Meridian: 42 unique values for 66 scenes, should be 8-15)
- **Characters/locations**: Naming drift — same entity gets different spellings, capitalization, full vs short names. (Thornwall: Kael vs kael vs Kael Davreth; Governor: 5 variants of "resonance chamber")
- **Outcomes**: Narrative elaborations instead of enum values. (All four projects affected)

Projects with registries (Thornwall) are significantly cleaner, proving that registry-based normalization fixes the drift.

## Solution

A reconciliation pass that runs after each extraction phase:

1. **Registry build** (Opus) — Send full column of extracted values + existing registry to Opus. Get back canonical registry with IDs and aliases.
2. **Field normalization** (deterministic Python) — Resolve every CSV field value against the registry's alias map, write canonical ID back.

### When It Runs

- After Phase 1 (skeleton): **characters**, **locations**
- After Phase 2 (intent): **values**, **MICE threads**
- After Phase 3 (briefs): **knowledge facts**, **outcomes**
- Standalone via `storyforge-reconcile` for existing projects

## Domain Specifications

### Characters (after Phase 1)

**Input:** `pov` from scenes.csv, `characters` and `on_stage` from scene-intent.csv, existing `characters.csv`, character-bible.md.

**Opus prompt:** Produce canonical character registry from all character references. Each entry: id (kebab-case slug), name (display name), aliases (semicolon-separated variants), role (protagonist/antagonist/supporting/minor/referenced).

**Normalization:** Resolve pov, characters, on_stage to canonical IDs.

### Locations (after Phase 1)

**Input:** `location` from scenes.csv, existing `locations.csv`.

**Opus prompt:** Produce canonical location registry. Collapse variants (e.g., "resonance chamber and central column (300 feet below surface)" and "Resonance chamber, central column..." are the same place). Each entry: id, name, aliases.

**Normalization:** Resolve location to canonical IDs.

### Values (after Phase 2)

**Input:** `value_at_stake` from scene-intent.csv, existing `values.csv`.

**Opus prompt:** A novel should have 8-15 core thematic values. Collapse over-specified entries ("justice-specifically-whether-institutional-forms..." → "justice"). Each entry: id (abstract concept), name, aliases.

**Normalization:** Resolve value_at_stake to canonical IDs.

### MICE Threads (after Phase 2)

**Input:** Full `mice_threads` timeline (every +/- entry with scene ID and sequence), existing `mice-threads.csv`.

**Opus prompt:** Three tasks:
1. Build registry — each unique thread gets id, name, type (milieu/inquiry/character/event), aliases
2. Match orphaned closes to opens — if `-inquiry:can-Cora-be-trusted-at-Lenas-table` has no open but `+inquiry:can-cora-be-trusted` exists, they're the same thread
3. Flag true orphans and fill missing types

**Normalization:** Rewrite mice_threads entries with canonical thread IDs. Matched orphans get their +/- entries corrected.

### Knowledge Facts (after Phase 3)

**Input:** `knowledge_in` and `knowledge_out` from scene-briefs.csv (in scene sequence order), existing `knowledge.csv`.

**Opus prompt:** Produce canonical knowledge registry. Each entry: id, name, aliases, category (identity/motive-intent/capability-constraint/state-change/stakes-threat/relationship-shift). Backstory facts that characters know before scene 1 should be marked with origin=backstory. Normalize knowledge_in and knowledge_out to use canonical IDs. Ensure knowledge_out of scene N feeds knowledge_in of subsequent scenes.

**Normalization:** Resolve both knowledge_in and knowledge_out to canonical IDs. Add backstory facts to registry so validator doesn't flag them.

### Outcomes (after Phase 3)

**No Opus needed.** Deterministic: parse first token to extract enum value (yes, yes-but, no, no-and), discard narrative elaboration. Elaborated outcomes all start with the enum value followed by " — ".

## Script: `storyforge-reconcile`

Standalone script following standard patterns.

### Arguments

- `--domain <name>` — Run one domain (characters, locations, values, mice-threads, knowledge, outcomes). Default: all in order.
- `--phase <N>` — Run domains for that extraction phase (1=characters+locations, 2=values+mice-threads, 3=knowledge+outcomes).
- `--dry-run` — Show what would change without writing.
- `-h, --help` — Usage.

### Flow

1. Parse args, `detect_project_root`
2. For each domain in order:
   a. Read relevant CSV column(s)
   b. Read existing registry if present
   c. Build Opus prompt (skip for deterministic domains)
   d. Call Anthropic API (direct, single prompt per domain)
   e. Parse response into registry CSV
   f. Write/update registry file
   g. Run deterministic normalization against registry
   h. Write updated scene CSV(s)
   i. Commit: `Reconcile: {domain} — {N} entries, {M} normalizations`
3. Run validation, report results
4. Push

### Integration with `storyforge-extract`

After each phase's commit:
```bash
"${SCRIPT_DIR}/storyforge-reconcile" --phase 1  # after Phase 1
"${SCRIPT_DIR}/storyforge-reconcile" --phase 2  # after Phase 2
"${SCRIPT_DIR}/storyforge-reconcile" --phase 3  # after Phase 3
```

Skipped in `--dry-run` mode. Respects `STORYFORGE_MODEL` override.

## Python Module: `storyforge/reconcile.py`

### Functions

- `build_registry_prompt(domain, raw_values, existing_registry, context)` — Build Opus prompt for a domain
- `parse_registry_response(response, domain)` — Parse Opus output into registry rows
- `normalize_column(csv_map, column, alias_map)` — Deterministic normalization of a CSV column
- `normalize_mice_threads(intent_map, alias_map)` — Special handling for +/- prefix format
- `normalize_outcomes(briefs_map)` — Deterministic enum extraction
- `build_backstory_facts(knowledge_registry)` — Identify facts needed before scene 1

### Reuses Existing Infrastructure

- `_read_csv_as_map`, `_write_csv`, `_FILE_MAP` from elaborate.py
- `load_alias_map`, `normalize_aliases` from aliases infrastructure
- `load_registry_alias_maps`, `normalize_fields` from enrich.py
- `invoke_anthropic_api`, `extract_api_response`, `log_api_usage` from common.sh

## Cost Estimate

Per full reconciliation (all 6 domains) on a 100-scene novel:
- 5 Opus API calls (characters, locations, values, MICE threads, knowledge)
- 1 deterministic pass (outcomes)
- ~50K input tokens, ~10K output tokens
- ~$1-2 total

## Commit Strategy

One commit per domain so diffs show exactly what changed per reconciliation step.
