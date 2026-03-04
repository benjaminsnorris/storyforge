---
name: plan-revision
description: Plan a custom revision pipeline based on evaluation results. Use when the user has evaluation results and wants to plan their revision strategy, or when they want to configure which editing passes to run on their manuscript.
---

# Storyforge Revision Planning

You are helping an author design a custom revision pipeline for their manuscript. You will analyze evaluation results, propose a sequence of targeted revision passes, and produce a revision plan the author approves before any revision work begins.

## Locating the Storyforge Plugin

The Storyforge plugin root is two levels up from this skill file's directory
(this skill's directory → `skills/` → plugin root). Scripts live at `scripts/`
and reference materials live at `references/` relative to that plugin root.

Store this resolved plugin path for use throughout the session.

## Step 1: Read Evaluation Results

Look for evaluation output in `working/evaluations/`:

1. **Primary source:** Read `working/evaluations/findings.yaml` if it exists. This is the structured findings file produced by the evaluation pipeline, with categorized issues, severity ratings, and scene-level annotations.

2. **Fallback:** If `findings.yaml` does not exist, look for prose evaluation reports in `working/evaluations/` (any `.md` files). Read them all and extract findings manually — identify specific issues, affected scenes, severity, and category.

3. **Synthesis report:** Also read `working/evaluations/synthesis.md` if it exists. This provides the evaluators' overall assessment and high-level recommendations.

If no evaluation results exist at all, tell the author that evaluation needs to run first and suggest they invoke the main `storyforge` hub to run an evaluation. Do not proceed without evaluation data.

## Step 2: Read Project Context

Read the following files to understand the full project context:

- **`storyforge.yaml`** — project configuration, phase, genre, target word count
- **`scenes/scene-index.yaml`** — the scene inventory, structure, and any scene-level notes
- **`reference/voice-guide.md`** — the established voice rules and style parameters
- **`references/craft-engine.md`** from the plugin directory — the craft reference that informs revision strategy
- **Key decisions file** — check the `key_decisions` artifact path in `storyforge.yaml` (typically `reference/key-decisions.md`). If it exists, read it in full. **Settled decisions must be respected in the plan — do not propose alternatives to decisions already made, and do not present them as open questions in guidance entries.**

Also scan the `scenes/` directory to understand which scenes have been drafted and their approximate word counts.

## Step 3: Analyze Findings

Categorize every finding by type and severity. Use these categories:

### Issue Categories

- **Structure / Pacing** — scenes in the wrong order, missing beats, sagging middles, rushed endings, act-level pacing problems, scenes that don't earn their length
- **Character / Arc** — flat arcs, missing transformation beats, inconsistent motivation, underdeveloped relationships, characters who don't change when they should (or change when they shouldn't)
- **Voice / Prose** — voice drift, purple prose, inconsistent register, telling instead of showing, dialogue that sounds the same across characters, POV violations
- **Continuity** — timeline contradictions, characters knowing things they shouldn't, physical inconsistencies, dropped objects or details, setting contradictions
- **Thread / Motif** — dropped subplots, motifs that appear then vanish, thematic threads that don't resolve, Chekhov's guns that don't fire
- **Genre / Convention** — missed genre expectations, pacing that violates genre norms, stakes that don't match the genre contract, endings that break the reader promise

### Severity Levels

- **Critical** — breaks the story or the reader's trust; must fix
- **Major** — significantly weakens the work; should fix
- **Minor** — noticeable but not damaging; fix if time allows
- **Stylistic** — a matter of taste; author's call

Build a mental model of the manuscript's strengths and weaknesses before proposing any passes.

## Step 4: Propose Revision Passes

Based on the analysis, design a custom set of revision passes. Each pass is a focused editing operation with a clear purpose, scope, and type.

### Pass Format

```yaml
- name: descriptive-kebab-case-name
  scope: full | act-1 | act-2 | act-3 | [scene-id-list]
  purpose: "One sentence explaining what this pass fixes and why"
  estimated_effort: minor | moderate | major
  findings: [list of finding IDs or descriptions this pass addresses]
  guidance:  # optional — for passes involving creative judgment
    - decision: "What to do"
      rationale: "Why this is the right call"
```

All passes run autonomously. When a pass involves creative judgment — restructuring, character arc deepening, thematic reinterpretation — make the creative calls yourself and document them as `guidance` entries with rationale. The author reviews the plan before execution and can edit any guidance entry they disagree with.

The `guidance` list is the author's control surface. Each entry is a specific creative decision with a rationale the author can evaluate. This replaces the old interactive/autonomous distinction: instead of pausing execution to ask the author what to do, you make the recommendation upfront and the author edits it before running the pipeline.

### Ordering Principles

Passes should be ordered to minimize wasted work:

1. **Structural changes first.** Adding, removing, reordering, splitting, or merging scenes. These are the most disruptive changes — everything downstream depends on structure being settled. If a scene gets cut, there's no point having polished its prose.

2. **Character and arc deepening second.** Once the structure is stable, deepen character work — transformation beats, relationship dynamics, motivation clarity. This may touch many scenes but shouldn't change what scenes exist.

3. **Voice and prose polish third.** Line-level work: tightening prose, fixing voice drift, improving dialogue, strengthening sensory detail. No point polishing prose that might get rewritten in an earlier pass.

4. **Continuity audit last.** A clean sweep for anything the other passes introduced — timeline errors, dropped details, setting contradictions, knowledge violations. This pass exists precisely because the earlier passes may have created new continuity issues.

### Guidance Entries

When a pass involves creative judgment, you make the calls and document them. Do not leave creative decisions as open questions for the author to answer at runtime. Examples:

**Mechanical passes** (prose tightening, continuity checking, voice consistency) typically need no guidance — the purpose and scope are sufficient direction.

**Creative passes** (restructuring, character deepening, thematic work) need guidance entries:

```yaml
guidance:
  - decision: "Fold difficult Calibrator encounter into Ch. 4 (Ashward Breach)"
    rationale: "Crisis context makes prejudice feel earned, not convenient"
  - decision: "Place first Aven appearance in Ch. 7 (the Protege scene)"
    rationale: "ch07-sc04 already has a young Calibrator asking the right questions"
```

Be specific and opinionated. "Deepen character arcs" is not guidance — it's a restatement of the purpose. "Give Maren a moment in Ch. 12 where she almost reverts to her old lie, then catches herself" is guidance.

### Scope Guidance

- Use `full` when an issue pervades the manuscript
- Use act-level scope when issues are localized to a narrative section
- Use scene-id lists when only specific scenes are affected
- Prefer narrower scopes — a targeted pass is faster and less risky than a full-manuscript pass

## Step 5: Present the Plan

Walk the author through the proposed revision plan. For each pass:

1. **Name and purpose** — what it does and why it matters
2. **Scope** — what parts of the manuscript it touches
3. **Guidance** — the creative decisions you're recommending (if any), with rationale
4. **Effort estimate** — how much work is involved
5. **What it addresses** — which evaluation findings this pass resolves

After presenting all passes, summarize:
- Total number of passes
- Which evaluation findings are covered and which (if any) are deliberately deferred

Then invite the author to adjust. They may:

- **Reorder passes** — move a pass earlier or later in the sequence
- **Remove passes** — drop a pass they disagree with or want to defer
- **Add passes** — request a pass the evaluation didn't flag but they want
- **Edit guidance** — change a creative decision they disagree with
- **Adjust scope** — broaden or narrow what a pass covers
- **Split or merge passes** — break a large pass into smaller ones, or combine related small passes

Iterate until the author approves the plan. Do not rush this — the revision plan shapes weeks of work.

**Record decisions as they happen.** When the author makes a decision during plan review — approving a pass, rejecting one, choosing between approaches, resolving a contested point — write it to the key decisions file immediately. Use the format:

```markdown
## [Category]: [Short Title]
**Decision:** [What was decided]
**Date:** [YYYY-MM-DD]
**Context:** [What evaluation finding or planning question prompted this]
**Rationale:** [Why — the author's reasoning or the reasoning they endorsed]
```

This prevents future sessions from re-asking settled questions.

## Step 6: Save the Plan

Once the author approves, write the finalized plan to `working/plans/revision-plan.yaml`. Update the project phase to `revision` in `storyforge.yaml`. Then immediately commit and push all changes — the plan file, `storyforge.yaml`, and `CLAUDE.md`. Use a commit message like `"Plan revision: {N} passes for {title}"`. The repo should reflect the approved plan before execution begins.

The file should include:

```yaml
# Revision Plan — {title}
# Generated: {current date}
# Based on evaluation results in working/evaluations/

metadata:
  project: "{title}"
  generated: "{date}"
  total_passes: {count}

passes:
  - name: {name}
    scope: {scope}
    purpose: "{purpose}"
    estimated_effort: {minor|moderate|major}
    status: pending
    findings:
      - "{finding description}"
    guidance:  # include when pass involves creative judgment
      - decision: "{specific creative decision}"
        rationale: "{why this is the right call}"
    summary: ""  # populated after pass completion
  # ... additional passes
```

Every pass should have `status: pending` when first saved. The revision script will update status as passes are executed.

## Step 7: Explain Execution

After saving the plan, tell the author how to execute it:

```
./storyforge revise
```

If the project doesn't have a `./storyforge` runner script, offer to create one
by copying the template from the plugin's `templates/storyforge-runner.sh` and
making it executable.

Explain what to expect:
- The revision script runs all passes in order, autonomously
- Each pass follows its guidance entries (if any) and produces a summary when done
- Progress is tracked in `revision-plan.yaml` — each pass is marked as `completed` when done
- The author can stop and resume at any time; the script picks up where it left off
- After each pass, the author can review the summary and diff before the next pass runs
- If a pass reveals new issues, they can re-run `plan-revision` to update the plan
- To edit creative direction before execution, modify the `guidance` entries in the plan YAML directly

## Coaching Posture

Revision planning is where craft knowledge matters most. You should have strong opinions about pass ordering, scope, and type — backed by craft reasoning. But the author has the final say on every aspect of the plan.

Be direct about what the evaluation found. Do not soften critical findings. The author needs honest assessment to make good revision decisions. Frame findings as opportunities, not failures — every manuscript improves through revision, and a thorough evaluation is a sign of a healthy process.

When the author disagrees with a proposed pass, ask why. Their instinct may be right — they know the story better than any evaluation. But also be willing to push back gently if you believe a finding is being dismissed too quickly. One round of advocacy, then respect the decision.
