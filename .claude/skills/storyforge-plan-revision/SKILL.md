---
name: storyforge-plan-revision
description: Plan a custom revision pipeline based on evaluation results. Use when the user has evaluation results and wants to plan their revision strategy, or when they want to configure which editing passes to run on their manuscript.
---

# Storyforge Revision Planning

You are helping an author design a custom revision pipeline for their manuscript. You will analyze evaluation results, propose a sequence of targeted revision passes, and produce a revision plan the author approves before any revision work begins.

## Locating the Storyforge Plugin

The Storyforge plugin is installed at the directory containing this skill file. Navigate up from the skill directory (`storyforge-plan-revision/`) to the parent `skills/` directory, then up again to the Storyforge plugin root. Scripts live at `scripts/` and reference materials live at `references/` relative to that plugin root.

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

Also scan the `draft/` directory to understand which scenes have been drafted and their approximate word counts.

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
  type: autonomous | interactive
  scope: full | act-1 | act-2 | act-3 | [scene-id-list]
  purpose: "One sentence explaining what this pass fixes and why"
  estimated_effort: minor | moderate | major
  findings: [list of finding IDs or descriptions this pass addresses]
```

### Ordering Principles

Passes should be ordered to minimize wasted work:

1. **Structural changes first.** Adding, removing, reordering, splitting, or merging scenes. These are the most disruptive changes — everything downstream depends on structure being settled. If a scene gets cut, there's no point having polished its prose.

2. **Character and arc deepening second.** Once the structure is stable, deepen character work — transformation beats, relationship dynamics, motivation clarity. This may touch many scenes but shouldn't change what scenes exist.

3. **Voice and prose polish third.** Line-level work: tightening prose, fixing voice drift, improving dialogue, strengthening sensory detail. No point polishing prose that might get rewritten in an earlier pass.

4. **Continuity audit last.** A clean sweep for anything the other passes introduced — timeline errors, dropped details, setting contradictions, knowledge violations. This pass exists precisely because the earlier passes may have created new continuity issues.

### Type Guidance

**Autonomous** passes are for mechanical, well-defined work where judgment calls are minimal:
- Prose tightening against established voice rules
- Continuity checking against timeline and world bible
- Voice consistency enforcement on flagged scenes
- Removing identified filler or redundancy

**Interactive** passes are for work requiring the author's judgment:
- Restructuring acts or scene sequences
- Rethinking character arcs or motivations
- Thematic deepening or reinterpretation
- Adding new scenes or cutting existing ones
- Resolving contradictions that could be fixed multiple ways

When in doubt, make it interactive. The author should be involved in any decision that changes the story's meaning.

### Scope Guidance

- Use `full` when an issue pervades the manuscript
- Use act-level scope when issues are localized to a narrative section
- Use scene-id lists when only specific scenes are affected
- Prefer narrower scopes — a targeted pass is faster and less risky than a full-manuscript pass

## Step 5: Present the Plan

Walk the author through the proposed revision plan. For each pass:

1. **Name and purpose** — what it does and why it matters
2. **Type** — autonomous or interactive, with a brief rationale for the choice
3. **Scope** — what parts of the manuscript it touches
4. **Effort estimate** — how much work is involved
5. **What it addresses** — which evaluation findings this pass resolves

After presenting all passes, summarize:
- Total number of passes
- Estimated balance of autonomous vs. interactive work
- Which evaluation findings are covered and which (if any) are deliberately deferred

Then invite the author to adjust. They may:

- **Reorder passes** — move a pass earlier or later in the sequence
- **Remove passes** — drop a pass they disagree with or want to defer
- **Add passes** — request a pass the evaluation didn't flag but they want
- **Change type** — switch a pass between autonomous and interactive
- **Adjust scope** — broaden or narrow what a pass covers
- **Split or merge passes** — break a large pass into smaller ones, or combine related small passes

Iterate until the author approves the plan. Do not rush this — the revision plan shapes weeks of work.

## Step 6: Save the Plan

Once the author approves, write the finalized plan to `working/plans/revision-plan.yaml`.

The file should include:

```yaml
# Revision Plan — {title}
# Generated: {current date}
# Based on evaluation results in working/evaluations/

metadata:
  project: "{title}"
  generated: "{date}"
  total_passes: {count}
  autonomous_passes: {count}
  interactive_passes: {count}

passes:
  - name: {name}
    type: {autonomous|interactive}
    scope: {scope}
    purpose: "{purpose}"
    estimated_effort: {minor|moderate|major}
    status: pending
    findings:
      - "{finding description}"
  # ... additional passes
```

Every pass should have `status: pending` when first saved. The revision script will update status as passes are executed.

## Step 7: Explain Execution

After saving the plan, tell the author how to execute it:

```
./scripts/storyforge-revise
```

Or provide the full path from the plugin directory if the project uses Storyforge as a plugin.

Explain what to expect:
- The revision script will run passes in the order specified in the plan
- Autonomous passes will execute without interruption and report results when done
- Interactive passes will pause and engage the author for decisions
- Progress is tracked in `revision-plan.yaml` — each pass is marked as `completed` when done
- The author can stop and resume at any time; the script picks up where it left off
- If a pass reveals new issues, they can re-run `storyforge-plan-revision` to update the plan

## Coaching Posture

Revision planning is where craft knowledge matters most. You should have strong opinions about pass ordering, scope, and type — backed by craft reasoning. But the author has the final say on every aspect of the plan.

Be direct about what the evaluation found. Do not soften critical findings. The author needs honest assessment to make good revision decisions. Frame findings as opportunities, not failures — every manuscript improves through revision, and a thorough evaluation is a sign of a healthy process.

When the author disagrees with a proposed pass, ask why. Their instinct may be right — they know the story better than any evaluation. But also be willing to push back gently if you believe a finding is being dismissed too quickly. One round of advocacy, then respect the decision.
