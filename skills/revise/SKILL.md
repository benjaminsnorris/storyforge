---
name: revise
description: Plan and execute revision — analyze evaluation findings, create upstream + craft passes, execute them, and review results. Use when the author has evaluation results and wants to revise, or after scoring reveals issues, or when the author asks to polish prose.
---

# Storyforge Revise

You are helping an author plan and execute revisions. This skill handles the full cycle: analyze findings, build a revision plan, execute passes (upstream CSV fixes + prose polish), and assess results.

## Locating the Storyforge Plugin

The Storyforge plugin root is two levels up from this skill file's directory (this skill's directory → `skills/` → plugin root).

Store this resolved plugin path for use throughout the session.

## Step 1: Read Project State

1. `storyforge.yaml` — phase, coaching level
2. `working/pipeline.csv` — current cycle status
3. Latest evaluation: `working/evaluations/eval-*/findings.yaml` or `synthesis.md`
4. Latest scoring: `working/scores/latest/diagnosis.csv`, `fidelity-scores.csv`
5. Structural scoring: `working/scores/structural-latest.csv`, `working/scores/structural-proposals.csv`
6. Existing revision plan: `working/plans/revision-plan.csv`
7. Latest review: `working/reviews/` (most recent)

## Step 2: Determine Mode

Based on the author's request and project state:

### "Revise" / "Fix the issues" / "Plan revision"
→ Full revision cycle: analyze findings, plan passes, execute, review.

### "Polish" / "Clean up the prose" / "Polish pass"
→ Craft-only revision: skip planning, target scenes with low craft scores. Equivalent to `./storyforge revise --polish`.

### "Polish until it's good" / "Keep polishing" / "Autonomous polish"
→ Convergence loop: scores scenes, identifies weak principles, generates targeted polish plan, executes, re-scores, repeats until scores stabilize or no high/medium priority issues remain. Equivalent to `./storyforge revise --polish --loop`. Use `--max-loops N` to cap iterations (default 5).

### "Fix AI patterns" / "Naturalness" / "Remove AI artifacts" / "Sounds like a machine"
→ Targeted 3-pass revision for specific AI prose patterns: metaphor restatement, interpretive tagging, ending template. Equivalent to `./storyforge revise --naturalness`. Use when scoring shows low `prose_naturalness` but high structural/fidelity scores — the sign that the brief is solid but the prose has AI artifacts. The `--naturalness` and `--polish` passes dynamically load vocabulary from `references/ai-tell-words.csv` (the universal AI-tell word list). When a project has `reference/voice-profile.csv`, its `banned_words` field is merged with the universal list, creating a project-specific vocabulary constraint for revision prompts.

### Upstream Fix Routing (automatic in --polish --loop)

When `--polish --loop` detects that a scene's naturalness is stalled because of a conflict-free or abstract brief, it automatically:

1. **Rewrites the brief** — conflict, goal, crisis, and decision fields get genuine dramatic opposition
2. **Re-drafts the scene** — fresh draft using the new brief
3. **Then polishes** — normal craft polish on the re-drafted scene

The `--naturalness` mode also checks for upstream causes before running its 3-pass craft plan.

### "How did the revision go?" / "Review results"
→ Assessment mode: read the most recent revision results, compare before/after, identify remaining issues, recommend next steps.

### Evaluation exists but no plan yet
→ Start at planning. Analyze findings and propose passes.

### Plan exists with pending passes
→ Start at execution. Offer to run the pending passes.

### All passes completed
→ Start at review. Assess what changed.

### Reader Annotations

The revision pipeline checks for `working/annotations.csv` and incorporates unaddressed reader annotations into the revision plan. Pink annotations (Needs Revision) become craft findings. Orange annotations (Cut / Reconsider) become structural findings. Green annotations (Strong Passage) become protection constraints that shield those passages from rewrite during polish. Use `--no-annotations` to exclude annotations from a specific run.

## Step 3: Plan the Revision

Read evaluation findings and scoring data. Categorize each finding by where the fix belongs.

### Structural Proposals

If `working/scores/structural-proposals.csv` exists, these are unaddressed structural findings from the last `storyforge validate --structural` run. Each proposal has:
- **dimension**: which scoring dimension flagged it (arc_completeness, thematic_concentration, pacing_shape, etc.)
- **fix_location**: where the fix lives (structural/intent/brief/registry) — same routing as evaluation findings
- **target**: scene ID or 'global'
- **change**: what to do
- **rationale**: why (score + data)

Structural fixes should generally precede craft passes, as they affect what the prose needs to deliver. Run `storyforge validate --structural` after structural/intent/brief passes to verify scores improved before starting craft passes.

Categorize each finding by where the fix belongs:

| fix_location | Target file | What it fixes |
|-------------|-------------|---------------|
| `structural` | scenes.csv | POV, timeline, part structure, scene additions/removals |
| `intent` | scene-intent.csv | Value shifts, scene type, character presence |
| `brief` | scene-briefs.csv | Knowledge chain, goal/conflict/outcome, key actions |
| `craft` | Prose directly | Voice, rhythm, dialogue, naturalness |

### Registry-Backed Fields

When fixing CSV fields interactively (upstream passes), all registry-backed fields must use canonical IDs from `reference/` registries (characters.csv, locations.csv, values.csv, knowledge.csv, motif-taxonomy.csv, mice-threads.csv). Read the registries before making CSV edits. If a fix introduces a new entity, add it to the appropriate registry first.

### Ordering Principles (upstream first)

1. **Structural passes first** — scene additions, removals, reordering
2. **Intent passes second** — value shift corrections, MICE thread management
3. **Brief passes third** — knowledge chain fixes, goal/conflict/outcome
4. **Craft passes last** — prose polish (only after all upstream changes settle)
5. **Validate** after all passes

Each upstream pass automatically re-drafts affected scenes from updated briefs.

### Plan Format

Write the plan to `working/plans/revision-plan.csv`:

```
pass|name|purpose|scope|targets|guidance|protection|findings|status|model_tier|fix_location
1|knowledge-chain-fix|Fix knowledge violations flagged in evaluation|scene-level|scene-a;scene-b|Specific guidance here|voice-quality|F001;F003|pending|sonnet|brief
2|mice-thread-fix|Fix MICE thread nesting issues|full||Ensure FILO nesting order|all-strengths|F007|pending|sonnet|intent
3|prose-tightening|Voice consistency and AI pattern cleanup|full||Follow voice guide strictly|scene-30b|F012;F015|pending|opus|craft
```

### Presenting the Plan

Present each pass with:
- Name and purpose
- Which scenes are affected
- What will change (upstream CSV updates or prose edits)
- Key guidance decisions (with rationale the author can review)

Ask the author to approve before executing. They can edit any guidance entry.

## Step 4: Execute the Revision

Offer two options:

> **Option A: Run it here**
> I'll execute the revision passes in this conversation.
>
> **Option B: Run it yourself**
> ```bash
> cd [project_dir] && [plugin_path]/scripts/storyforge-revise [flags]
> ```
> For craft-only: `./storyforge revise --polish`
> For autonomous polish loop (score→polish→re-score until stable): `./storyforge revise --polish --loop`
> For AI pattern removal: `./storyforge revise --naturalness`
> For structural-only (CSV fixes, no prose): `./storyforge revise --structural`

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

If Option A, delegate to the revise script with the plan already saved.

The revise script:
- Reads the plan CSV
- For upstream passes (fix_location: brief/intent/structural): asks Claude to produce corrected CSV rows, applies them, re-drafts affected scenes
- For craft passes: edits prose directly
- Commits after each pass
- Runs validation after all passes

## Step 5: Review Results

After all passes complete (or when the author asks "how did it go"):

1. Read the revision branch's diff (what changed)
2. Run validation — how many issues remain vs before?
3. Check scoring — did craft scores improve?
4. Check fidelity — did the re-drafted scenes deliver their updated briefs?

Present:
- **What improved:** Specific findings resolved, validation failures reduced
- **What remains:** Outstanding issues, new issues introduced
- **Recommendation:** Ready to merge, needs another cycle, or needs author attention

## Step 6: Ensure Feature Branch

Before making any changes, check the current branch:
```bash
git rev-parse --abbrev-ref HEAD
```
- If on `main` or `master`: create a feature branch first:
  ```bash
  git checkout -b "storyforge/revise-$(date '+%Y%m%d-%H%M')"
  ```
- If on any other branch: stay on it — do not create a new branch.

## Step 7: Commit

After every deliverable:
```bash
git add -A && git commit -m "Revision: [what was done]" && git push
```

## Coaching Level Behavior

### Full (default)
Analyze findings, propose the plan with specific guidance, execute all passes autonomously, present results.

### Coach
Analyze findings, present options for each pass ("I see three approaches to the knowledge chain issue — which direction?"). Author decides. Execute on approval.

### Strict
Report findings and validation data. Author creates the plan. Skill formats it into CSV and provides the execution command.
