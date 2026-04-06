---
name: hone
description: Improve CSV data quality — concretize abstract briefs, fill gaps, normalize registries, apply structural fixes. Use when the author wants to improve brief quality, fix abstract language, fill missing fields, normalize data, or when scoring reveals brief/structural issues.
---

# Storyforge Hone

You are helping an author improve the quality of their scene CSV data. Hone consolidates four domains of CSV quality work: registry normalization, brief concretization, structural fixes from evaluation findings, and gap filling.

**When to use hone vs. other tools:**
- **Hone** — CSV data quality: abstract briefs, missing fields, inconsistent registries, evaluation-driven CSV fixes
- **Revise** — prose quality: craft passes, polish, voice consistency
- **Elaborate** — building new structure: spine, architecture, scene map, briefs from scratch
- **Extract** — reverse engineering structure from existing prose

## Locating the Storyforge Plugin

The Storyforge plugin root is two levels up from this skill file's directory (this skill's directory → `skills/` → plugin root).

Store this resolved plugin path for use throughout the session.

## Step 1: Read Project State

Read the following files to understand the full context:

- `storyforge.yaml` — project configuration, coaching level
- `reference/scenes.csv` — scene metadata (status, seq, part)
- `reference/scene-briefs.csv` — drafting contracts (key_actions, crisis, decision, knowledge_in/out)
- `reference/scene-intent.csv` — narrative dynamics (function, value_at_stake, value_shift, emotional_arc)
- `working/scores/latest/scene-scores.csv` — latest scoring (if exists, check prose_naturalness)
- `working/scores/structural-proposals.csv` — structural proposals (if exists)

## Step 2: Determine Mode

Based on the author's request and project state:

**"Hone" / "Improve my briefs" / "Concretize" / "Fix abstract language":**
→ Briefs domain. Detect and rewrite abstract brief fields as concrete physical beats.

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

## Step 3: Assess Domain Needs

### Briefs Domain

Run abstract language detection to show the author what would be flagged:

```python
from storyforge.hone import detect_abstract_fields
from storyforge.elaborate import _read_csv_as_map

briefs_map = _read_csv_as_map('reference/scene-briefs.csv')
flagged = detect_abstract_fields(briefs_map)
```

Present results:
- Number of scenes with abstract brief fields
- Which fields are abstract and why (show the indicator counts)
- Example of the worst offender (highest abstract count)

If no scenes are flagged, report that briefs look concrete and skip.

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

## Step 4: Execute

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

### Common Commands

```bash
# All domains
./storyforge hone

# Just briefs (concretize abstract language)
./storyforge hone --domain briefs

# Just briefs for specific scenes
./storyforge hone --domain briefs --scenes scene-a,scene-b

# Just registries (same as old storyforge reconcile)
./storyforge hone --domain registries

# Registry sub-domains for extraction phase
./storyforge hone --phase 1

# Dry run — see what would change
./storyforge hone --dry-run

# Override coaching level
./storyforge hone --coaching coach
```

### Interactive Brief Concretization

At coaching levels **coach** and **strict**, hone saves proposals and analysis to `working/hone/` rather than modifying CSVs directly. In this skill, you can help the author interactively:

1. Read the proposals/analysis files in `working/hone/`
2. Walk through each flagged field with the author
3. Discuss the abstract → concrete transformation
4. Apply the author's chosen rewrites to the CSVs
5. Commit after each batch of changes

This is the most valuable mode for authors who want to understand and control the concretization process.

## Step 5: Review Results

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

## Step 6: Commit After Every Deliverable

After any changes to project files:

```bash
git add -A && git commit -m "Hone: [domain] — [summary]" && git push
```

## Coaching Level Behavior

- **full:** Run domains directly. Rewrites applied to CSVs. Show before/after. Proactively recommend which domains to run based on scoring data.
- **coach:** Present analysis and proposals. Save to `working/hone/`. Walk through rewrites interactively. Help the author understand why fields are abstract and what concrete alternatives look like. Don't apply changes without author approval.
- **strict:** Report findings only. Save analysis to `working/hone/`. Provide data (which fields are abstract, which are empty, indicator counts). No rewrites proposed. Author makes all decisions.
