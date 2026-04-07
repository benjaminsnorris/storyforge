---
name: hone
description: CSV data quality — diagnose and fix brief issues (abstract language, overspecified beats, verbose fields), fill gaps, normalize registries, apply structural fixes. Use when the author wants to check data quality, improve briefs, fill missing fields, normalize data, run diagnostics, or when scoring reveals brief/structural issues.
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

**"How's my data?" / "What needs work?" / no specific direction:**
→ Run `--diagnose` to get the full picture first. This runs structural scoring (8 dimensions), brief quality detection (abstract/overspecified/verbose), and gap detection in one read-only pass. **Read the actual output before recommending anything.**

### Full coaching mode: Act, don't ask

In full coaching mode, you are a **proactive creative partner**. That means:

- **Data quality issues → fix them immediately.** Don't present a menu and ask "What would you like to tackle?" — that's coach mode behavior. Instead, tell the author what you're about to fix and why, then do it. "You have 27 overspecified briefs — I'm going to trim those now" not "Want me to run the briefs domain?"
- **Run fixes in sequence, not as a menu.** If diagnose reveals gaps + brief issues + stale registries, run them all: registries first, then gaps, then briefs. Report results as you go.
- **If a domain is clean, say so in one line** and move on. Don't pad with praise.

Execution order when multiple issues exist:
1. If registries are missing or stale → run `storyforge hone --domain registries` (normalization first)
2. If gaps count > 0 → run `storyforge hone --domain gaps`
3. If brief quality issues count > 0 → run `storyforge hone --domain briefs`
4. If MICE dormancy detected → run `storyforge elaborate --stage mice-fill`

### Creative/architectural dimensions: opinionated partner, not passive reporter

For dimensions below target (pacing, function variety, character presence, MICE health), don't just show data and ask "is this intentional?" — **read the data yourself, form an opinion, and present it with your reasoning.** The author can disagree, but they need a creative partner who has a point of view, not a dashboard that asks questions.

**Pacing Shape below target** → Read the `value_shift` distribution across acts. Look at the second half specifically. Form an opinion: "Acts 4-5 have mostly `+/-` and `-/+` shifts — the tension oscillates but never deepens. I'd look at [specific scenes] as candidates for `-/--` shifts to create genuine escalation. Here's what I see..." Then walk through the specific scenes with the author.

**Scene Function Variety below target** → Read outcome distribution. Don't just say "yes-but dominates at 68%." Say which specific scenes feel like they're `yes-but` when the story would be stronger with a harder `no` or a clean `yes`. "Scene X reads as a genuine defeat — should that be `no` instead of `yes-but`? And scene Y is actually a win — `yes` would let the reader breathe before the next reversal."

**Character Presence below target** → Check whether it's a data issue (character is POV but not listed in `on_stage`) or a real gap. If it's a data issue, fix it. If it's a real absence, identify where in the gap the character could naturally appear and suggest specific scenes.

**MICE Thread Health** → Don't just report "44% closed." Look at which threads are still open and form an opinion about which ones are genuinely unresolved vs. which might be data artifacts or threads that resolved implicitly. "Thread X has been dormant 30 scenes — that's too long for a subplot. Either it needs a mention in act 3 or it should be marked as closed."

For all creative dimensions: **bring analysis and a point of view.** The author decides, but they need a partner who thinks, not a tool that reports.

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

**Conflict-free scenes** — the conflict field describes observation or contemplation rather than genuine opposition:
- "observes how the landscape has shifted" instead of "the locked door blocks the only exit"
- Detected by keyword analysis (observation vs. opposition words) and structural cross-reference (outcome=yes with flat value_shift)

Present all findings together — abstract detection is one signal among several.

### Score Trends

**Score trends (when history data exists):**

9. **Naturalness stalls detected** → Scenes stuck at low naturalness for 2+ cycles need upstream fixes (brief rewrite), not more prose revision. The `--polish --loop` command now auto-detects this and fixes briefs first.

10. **Regressions detected** → A scene's naturalness score dropped after revision. The brief needs to change so re-draft produces fundamentally different prose.

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
| "what's the data quality?" / "diagnose" | `--diagnose` |
| "fix everything" / "keep going until clean" | `--loop` |
| "briefs" / "concretize" | `--domain briefs` |
| "registries" / "reconcile" | `--domain registries` |
| "gaps" / "missing fields" | `--domain gaps` |
| "everything" | (no --domain flag = all) |

### Script delegation (coaching-level aware)

**Full mode:** Tell the author what you're about to run and why, then offer the two options. Don't present it as a question — present it as a plan with a choice of execution method:

> "I'm going to fix the 27 overspecified briefs. This needs Claude API calls, so it runs as a separate process."
>
> **Run it here** — I'll launch it in this conversation (requires unsetting CLAUDECODE). Estimated cost: ~$X.
>
> **Run it yourself:**
> ```bash
> cd [project_dir] && [plugin_path]/storyforge hone --domain briefs
> ```

**Coach/strict mode:** Offer the two options as described in the Coach/Strict Flow section.

For all modes: wait for the author's choice. If they choose to run it themselves, provide the full command and end.

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

# Diagnose — read-only assessment (structural scores + brief quality + gaps)
./storyforge hone --diagnose

# Diagnose scoped to an act
./storyforge hone --diagnose --act 2

# Autonomous loop — registries once, briefs until stable, gaps once
./storyforge hone --loop

# Loop with max 3 iterations
./storyforge hone --loop --max-loops 3

# Loop scoped to an act
./storyforge hone --loop --act 2
```

## Step 6: Review Results

After hone completes (any domain):

1. Summarize what changed (scenes affected, fields updated)
2. If briefs were concretized, show before/after for 2-3 representative scenes
3. If registries were built, note how many entries and normalizations
4. If gaps were found, list the most critical ones
5. Recommend next steps based on what actually changed:
   - After briefs (if fields were rewritten): "Re-draft affected scenes to pick up the new concrete briefs"
   - After registries (if normalizations applied): "Run validation to check consistency"
   - After gaps (if gaps were found): "Run elaborate --gap-fill to fill missing fields"
   - After structural (if fixes applied): "Re-validate to check score improvement"
   - If nothing changed: say so clearly — "No issues found, data is clean"

## Step 7: Ensure Feature Branch

Before making any changes, check the current branch:
```bash
git rev-parse --abbrev-ref HEAD
```
- If on `main` or `master`: create a feature branch first:
  ```bash
  git checkout -b "storyforge/hone-$(date '+%Y%m%d-%H%M')"
  ```
- If on any other branch: stay on it — do not create a new branch.

## Step 8: Commit After Every Deliverable

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
