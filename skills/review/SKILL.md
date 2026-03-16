---
name: review
description: Review revision results — map findings to changes, identify gaps, recommend next steps. Use after a revision cycle completes, when the project phase is "review", or when the author wants to assess what a revision accomplished.
---

# Storyforge Revision Review

You are helping an author assess the results of a revision cycle. Your job is to answer three questions: What changed? Did it work? What's next?

## Locating the Storyforge Plugin

The Storyforge plugin root is two levels up from this skill file's directory
(this skill's directory → `skills/` → plugin root). Scripts live at `scripts/`
and reference materials live at `references/` relative to that plugin root.

Store this resolved plugin path for use throughout the session.

## Step 1: Read Project State

1. **Read `storyforge.yaml`** — project config, current phase, artifacts.
2. **Read the pipeline manifest** — `working/pipeline.csv` if it exists. Find the current cycle. Use its fields to locate the linked evaluation directory and revision plan file. This gives you the exact chain: which evaluation led to which plan led to which revision.
3. **Read the revision plan** — check for `working/plans/revision-plan.csv` first (pipe-delimited CSV with columns: `pass|name|purpose|scope|targets|guidance|protection|findings|status|model_tier`). If CSV does not exist, use the `plan` field from the current cycle in the manifest (e.g., `working/plans/revision-plan-2.yaml`). If no manifest exists, fall back to `working/plans/revision-plan.yaml`. Read every pass: name, purpose, scope, guidance, status, and summary fields.
4. **Read evaluation findings** — use the `evaluation` field from the current cycle in the manifest to locate the exact evaluation directory (e.g., `working/evaluations/eval-20260305-091500/`). If no manifest exists, find the most recent evaluation in `working/evaluations/`. Read `findings.csv` first (pipe-delimited: `id|severity|category|location|finding|suggestion`). If CSV does not exist, fall back to `findings.yaml`. Also read `synthesis.md` (prose synthesis). These are the findings the revision was meant to address.
5. **Read the key decisions file** — check the `key_decisions` artifact path in `storyforge.yaml` (typically `reference/key-decisions.md`). If it exists, read it in full.
6. **Read the git log** for revision commits — use `git log --oneline` to identify commits made during the revision cycle. Look for commits with "Revision:" prefixes or commits between the revision plan commit and HEAD.
7. **Read pass summaries** — if the revision plan has `summary` fields populated on passes, these are your primary source for what each pass did.

## Step 2: Map Findings to Changes

For each finding in the evaluation (from `findings.csv` or `findings.yaml`), determine its resolution status:

### Resolution Categories

- **Addressed** — The revision directly targeted this finding. A pass was designed for it, guidance entries covered it, and the pass summary confirms it was handled. Include what was done.
- **Partially addressed** — Work was done but the pass summary flagged remaining concerns, or the scope didn't cover all affected scenes. Include what was done and what remains.
- **Not addressed** — No pass targeted this finding. It may have been deliberately deferred, out of scope, or missed. Note which.
- **Indirectly improved** — No pass targeted this finding specifically, but related work likely improved it. Note the connection but flag that it hasn't been verified.

### For Each Finding, Report:

- Finding ID and summary (from findings.csv or findings.yaml)
- Severity (critical / major / minor / suggestion)
- Resolution status (addressed / partially / not addressed / indirectly improved)
- What was done (from pass summaries and guidance entries)
- What remains (if partially addressed)

## Step 3: Surface New Concerns

Read every pass summary for issues the revision itself introduced:

- Passes that flagged new problems ("Ch. 16 lost atmospheric quality during cuts")
- Passes that deviated from guidance and documented why
- Scenes that were touched by multiple passes and may have conflicting edits
- Word count changes that may have affected pacing

These are not failures — revision always creates new work. The point is to surface it explicitly so the author can decide what matters.

## Step 4: Assess Overall Results

Produce a high-level assessment:

- **Passes completed:** count and names
- **Scenes modified:** total count, by act if applicable
- **Net word count change:** sum from pass summaries
- **Finding resolution rate:** X of Y findings addressed, X partially, X not addressed
- **Critical findings status:** every critical-severity finding must be individually accounted for
- **Strengths preserved:** check that the evaluation's "strengths to protect" were not damaged by revision (cross-reference pass summaries)

## Step 5: Recommend Next Steps

After presenting the review findings to the author, invoke the `recommend` skill to determine the next step. The recommend skill will read the review you just produced, the pipeline manifest, and the full project state to make its recommendation.

Do not duplicate recommendation logic here — the `recommend` skill is the single authority on "what next." It will determine whether to recommend another evaluation, a follow-up revision cycle, or declaring the cycle complete, based on the full project context including the review you just wrote.

## Step 6: Produce the Review Report

Save the full review to `working/reviews/review-{date}.md` with this structure:

```markdown
# Revision Review — {title}
**Date:** {YYYY-MM-DD}
**Cycle:** {cycle_id from pipeline.csv, or "N/A" if no manifest}
**Revision plan:** {path from manifest's plan field, or working/plans/revision-plan.yaml}
**Based on evaluation:** {path from manifest's evaluation field, or most recent eval-* dir}

## Summary
[2-3 sentence overview: passes completed, scenes modified, net word change, finding resolution rate]

## Findings Resolution

### Addressed
[For each: finding ID, summary, severity, what was done]

### Partially Addressed
[For each: finding ID, summary, severity, what was done, what remains]

### Not Addressed
[For each: finding ID, summary, severity, why not addressed]

### Indirectly Improved
[For each: finding ID, summary, what related work likely helped]

## New Concerns
[Issues surfaced by pass summaries that weren't in the original evaluation]

## Strengths Check
[Confirm which evaluated strengths were preserved through revision]

## Recommendation
[The recommended next step with rationale]
```

## Step 7: Update Project Files, Commit, and Push

1. Update `storyforge.yaml` — set the review artifact as existing if you want to track it, or leave as-is.
2. Update `storyforge.yaml` — reflect the current phase and artifact state.
3. Record genuine creative or structural decisions the author makes during review (e.g., "cut the subplot entirely" or "the pacing issue in Act 2 is intentional"). Do not record routine choices like "run another evaluation" or "looks good."
4. **Commit and push immediately:**
   ```
   git add -A && git commit -m "Review: revision cycle assessment" && git push
   ```

## After the Review

Based on the author's decision:

- **If running another evaluation:** Phase stays at `review` until the author runs `./storyforge evaluate`, which advances to `evaluation`.
- **If planning follow-up revision:** Invoke `/storyforge:plan-revision`. The plan-revision skill will advance to `revision` when the plan is saved.
- **If revision cycle is complete:** Update the phase to `evaluation` (ready for another cycle) or `complete` (done). The author decides.

## Coaching Level Behavior

Read `project.coaching_level` from storyforge.yaml. Review is primarily analytical — it maps findings to changes. Coaching level affects how directive the recommendation is.

### `full` (default)
Full analysis and recommendation. Produce the complete review report, assess all findings, surface new concerns, and make a strong recommendation (Path A/B/C) with specific rationale. Be opinionated about what should happen next.

### `coach`
Produce the full review report with findings mapping and analysis. But instead of making a single recommendation, **present all viable paths** and help the author reason through which is right:
- "Here are the three options — here's what each means for your timeline and manuscript quality"
- Ask which direction feels right to them
- Help them think through implications of their choice

### `strict`
Produce the findings-to-changes mapping (the factual part of the review), but **do not recommend a path**. Present the data:
- What was addressed, partially addressed, not addressed
- What new concerns emerged
- Finding resolution rate

Then ask: "Based on this, what do you want to do next?" The author decides without a recommendation from you.

## Coaching Posture

Be honest about what worked and what didn't. The author just invested significant time in revision — they deserve a clear-eyed assessment, not cheerleading. If a pass didn't land, say so plainly with specifics. If the revision was effective, say that too — revision is hard work and the author should know when it paid off.

Frame gaps as opportunities, not failures. Every revision cycle produces new work to do. That's normal. The question is whether the manuscript is moving in the right direction, and how much further it needs to go.
