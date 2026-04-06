---
name: hone
description: Improve CSV data quality — concretize abstract briefs, fix over-specified beats, fill gaps, normalize registries, apply structural fixes. Use when the author wants to improve brief quality, fix abstract language, fill missing fields, normalize data, or when scoring reveals brief/structural issues.
---

# Storyforge Hone

You are helping an author improve the quality of their scene CSV data. Hone consolidates four domains of CSV quality work: registry normalization, brief concretization, structural fixes from evaluation findings, and gap filling.

**When to use hone vs. other tools:**
- **Hone** — CSV data quality: abstract briefs, over-specified beats, missing fields, inconsistent registries, evaluation-driven CSV fixes
- **Revise** — prose quality: craft passes, polish, voice consistency
- **Elaborate** — building new structure: spine, architecture, scene map, briefs from scratch
- **Extract** — reverse engineering structure from existing prose

## Locating the Storyforge Plugin

The Storyforge plugin root is two levels up from this skill file's directory (this skill's directory → `skills/` → plugin root).

Store this resolved plugin path for use throughout the session.

## Step 1: Read Project State

Read the following files to understand the full context:

- `storyforge.yaml` — project configuration, coaching level
- `reference/scenes.csv` — scene metadata (status, seq, part, target_words)
- `reference/scene-briefs.csv` — drafting contracts (key_actions, crisis, decision, knowledge_in/out, key_dialogue, emotions)
- `reference/scene-intent.csv` — narrative dynamics (function, value_at_stake, value_shift, emotional_arc)
- `working/scores/latest/scene-scores.csv` — latest scoring (if exists, check prose_naturalness)
- `working/scores/structural-proposals.csv` — structural proposals (if exists)

## Step 2: Determine Coaching Level

Check the coaching level from `storyforge.yaml`, `--coaching` flag, or `STORYFORGE_COACHING` env var (default: `full`).

**If coaching level is `coach` or `strict`, go directly to the Coach/Strict Flow section below** before doing anything else. The rest of this skill assumes `full` coaching level unless noted.

## Step 3: Determine Domain

Based on the author's request and project state:

**"Hone" / "Improve my briefs" / "Concretize" / "Fix abstract language":**
→ Briefs domain. Detect and rewrite abstract/over-specified brief fields.

**"Fill gaps" / "Missing fields" / "What's incomplete?":**
→ Gaps domain. Scan for empty required fields and report (or fill via elaborate).

**"Reconcile" / "Normalize" / "Build registries" / "Clean up values":**
→ Registries domain. Build canonical registries and normalize field values.

**"Fix CSV issues" / "Apply evaluation fixes" / "Upstream fixes":**
→ Structural domain. Apply CSV fixes from evaluation findings.

**"Hone everything" / "Full data quality pass":**
→ All domains in order: registries → gaps → structural → briefs.

**If invoked without direction**, assess the project state:
1. Check if scoring data exists — if `prose_naturalness` scores are low, recommend briefs domain
2. Check for structural proposals — if they exist with brief/intent/structural fix_locations, recommend structural domain
3. Check for empty required fields — if gaps found, recommend gaps domain
4. If registries haven't been built recently, recommend registries domain
5. Present findings and ask what the author wants to focus on

## Step 4: Assess Domain Needs

### Briefs Domain

Brief quality problems go beyond abstract language. When assessing briefs, check for all of these issues:

**Abstract language** — thematic/narrator-voice descriptions instead of physical action:
- "the realization building" instead of "her hands stop moving"
- "tension deepening" instead of "the room goes quiet"
- "connecting X to Y" instead of "she looks from the map to the letter"

Run abstract language detection to quantify:

```python
from storyforge.hone import detect_abstract_fields
from storyforge.elaborate import _read_csv_as_map

briefs_map = _read_csv_as_map('reference/scene-briefs.csv')
flagged = detect_abstract_fields(briefs_map)
```

**Over-specified beats** — too many key_actions for the scene's word count. A 2,500-word scene with 5 key_actions forces one mandatory beat every 500 words, leaving no room for atmosphere, interiority, or organic pacing. Rule of thumb: 2-3 key_actions per 2,500 words. Flag scenes where `len(key_actions.split(';')) > target_words / 800`.

**Prescriptive dialogue** — exact quotes in `key_dialogue` make surrounding prose contort to deliver specific lines. Better to use dialogue direction ("Dorren rationalizes the anomaly using institutional language") than exact lines ("The eastern readings are within acceptable variance"). Flag scenes where `key_dialogue` contains quoted strings.

**Procedural goals** — goals framed as tasks ("Complete the quarterly audit") instead of dramatic questions ("Prove the maps are accurate before the review deadline"). The goal shapes how the drafter opens the scene — procedural goals produce bureaucratic openings.

**Emotional arc granularity** — 4+ beat emotional arcs (e.g., "competence;unease;self-doubt;resolve") force artificial escalation-and-recovery. 2-beat arcs (start state → end state) let the drafter find the middle ground organically. Flag scenes where `len(emotions.split(';')) > 3`.

Present all findings together — abstract detection is one signal among several.

### Gaps Domain

Run gap detection:

```python
from storyforge.hone import detect_gaps
from storyforge.elaborate import _read_csv_as_map

scenes = _read_csv_as_map('reference/scenes.csv')
intent = _read_csv_as_map('reference/scene-intent.csv')
briefs = _read_csv_as_map('reference/scene-briefs.csv')
gaps = detect_gaps(scenes, intent, briefs)
```

Present results:
- Number of gaps by file (scene-intent.csv vs scene-briefs.csv)
- Which scenes have the most gaps
- Recommend `storyforge-elaborate --gap-fill` to fill them

### Registries Domain

Check if registries exist in `reference/` (characters.csv, locations.csv, values.csv, etc.). If missing or stale, recommend running registries.

### Structural Domain

Check `working/scores/structural-proposals.csv` for unaddressed proposals with `fix_location` in {brief, intent, structural}. Present any findings.

## Step 5: Execute

### Command Builder

Map the author's request to the right flags:

| Author says | Flag |
|-------------|------|
| "act 2" / "part 2" | `--act 2` |
| "these scenes" / specific IDs | `--scenes ID,ID` |
| "coaching mode" / "coach" | `--coaching coach` |
| "just show me" / "dry run" | `--dry-run` |
| "briefs" / "concretize" | `--domain briefs` |
| "registries" / "reconcile" | `--domain registries` |
| "gaps" / "missing fields" | `--domain gaps` |
| "everything" | (no --domain flag = all) |

Offer the standard two options for script delegation:

> **Option A: Run it here**
> I'll launch the hone script in this conversation. This invokes Claude API calls for registry builds and brief concretization, so I need to unset the CLAUDECODE variable. Estimated cost: ~$X.
>
> **Option B: Run it yourself**
> Copy this command and run it in a separate terminal:
> ```bash
> cd [project_dir] && [plugin_path]/scripts/storyforge-hone [flags]
> ```

Wait for the author's choice. If Option B, provide the full command and end.

### Example Commands

```bash
# All domains
./storyforge hone

# Just briefs (concretize + over-specification fixes)
./storyforge hone --domain briefs

# Briefs for a specific act
./storyforge hone --domain briefs --act 2

# Briefs for specific scenes
./storyforge hone --domain briefs --scenes scene-a,scene-b

# Just registries (same as old storyforge reconcile)
./storyforge hone --domain registries

# Registry sub-domains for extraction phase
./storyforge hone --phase 1

# Dry run — see what would change
./storyforge hone --dry-run

# Override coaching level
./storyforge hone --coaching coach

# Combined: act 2 briefs in coaching mode
./storyforge hone --domain briefs --act 2 --coaching coach
```

## Step 6: Review Results

After hone completes (any domain):

1. Summarize what changed (scenes affected, fields updated)
2. If briefs were concretized, show before/after for 2-3 representative scenes
3. If registries were built, note how many entries and normalizations
4. If gaps were found, list the most critical ones
5. Recommend next steps:
   - After briefs: "Re-draft affected scenes to pick up the new concrete briefs"
   - After registries: "Run validation to check consistency"
   - After gaps: "Run elaborate --gap-fill to fill missing fields"
   - After structural: "Re-validate to check score improvement"

## Step 7: Commit After Every Deliverable

After any changes to project files:

```bash
git add -A && git commit -m "Hone: [domain] — [summary]" && git push
```

---

## Coach/Strict Flow

This section governs behavior when the coaching level is `coach` or `strict`. When either level is active, follow this flow instead of the default Step 4-6 above.

### Coach Mode (coaching level = `coach`)

Coach mode proposes changes for the author's review instead of applying them directly. Follow these steps in order:

**1. Detect issues** — Run the same analysis as full mode (abstract detection, over-specification, gaps, etc.) but do not modify any CSV files.

**2. Save proposals to `working/hone/`** — Create this directory if it doesn't exist. For each flagged scene, write a proposal file:

```
working/hone/briefs-{scene-id}.md    — brief concretization proposals
working/hone/analysis-{scene-id}.md  — gap/structural analysis
```

Each proposal file should contain:
- The current field value
- What's wrong with it (abstract language, over-specified, etc.)
- A suggested rewrite
- The reasoning behind the change

**3. Walk through proposals interactively** — This is the most valuable part of coach mode. For each flagged scene:
- Show the current field value
- Explain what the issue is and why it matters for drafting quality
- Present the suggested rewrite
- Ask the author: "Does this work, or would you change it?"
- Apply the author's chosen version (or skip if they decline)

**4. Commit after each batch** — After the author approves a group of changes:
```bash
git add -A && git commit -m "Hone: briefs (coach) — [summary of what changed]" && git push
```

**5. Script delegation in coach mode** — When offering the script command, include `--coaching coach`:
```bash
cd [project_dir] && [plugin_path]/scripts/storyforge-hone --domain briefs --act [N] --coaching coach
```
The script will save proposals to `working/hone/` without modifying CSVs. You can then walk through the proposals with the author interactively in this conversation.

### Strict Mode (coaching level = `strict`)

Strict mode reports findings without interpretation or recommendations. The author makes all decisions.

**1. Detect and report** — Run analysis, present raw data:
- Which fields are flagged, with indicator counts
- Which fields are empty
- Which registry entries are missing

**2. Save analysis to `working/hone/`**:
```
working/hone/constraints-{scene-id}.md  — findings only, no proposals
```

**3. Provide commands** — Give the author the exact commands to run, but do not recommend which to run first. No creative proposals, no rewrites, no prioritization.
