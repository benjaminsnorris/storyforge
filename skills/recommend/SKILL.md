---
name: recommend
description: Assess project state and recommend the single highest-value next action. Use when the author asks "what should I do next?", says "surprise me", or when another skill needs to determine the next step (forge hub guided mode, review Step 5).
---

# Storyforge Recommend

You are determining the single most valuable next action for this novel project. Read everything, assess the state, make one clear recommendation, and execute on approval.

## Locating the Storyforge Plugin

The Storyforge plugin root is two levels up from this skill file's directory
(this skill's directory → `skills/` → plugin root). Scripts live at `scripts/`
and reference materials live at `references/` relative to that plugin root.

Store this resolved plugin path for use throughout the session.

## Step 1: Read Full Project State

Read all of the following. Do not skip any — the recommendation depends on having the complete picture.

1. **`storyforge.yaml`** — phase, coaching level, genre, target word count, status
2. **`CLAUDE.md`** — recent activity, standing instructions, artifact status
3. **`working/pipeline.yaml`** — if it exists: current cycle ID, cycle status, linked evaluation/plan/review. Read the full cycle history to understand where the project is in the eval→plan→revise→review loop.
4. **Key decisions file** — check the `key_decisions` artifact path in `storyforge.yaml` (typically `reference/key-decisions.md`). If it exists, read it. Do not recommend anything that contradicts a settled decision.
5. **Scan for artifacts** — check existence (not contents) of:
   - `reference/character-bible.md`
   - `reference/world-bible.md`
   - `reference/story-architecture.md`
   - `reference/voice-guide.md`
   - `reference/timeline.md`
   - `scenes/scene-index.yaml` (read it — check if it has entries or is empty)
   - `reference/chapter-map.yaml`
6. **Scene status** — count scene files in `scenes/*.md`. Compare planned (from scene-index) vs. drafted (files exist) vs. revised (check frontmatter or pass status). Calculate current word count vs. target.
7. **Evaluation state** — check for `working/evaluations/`. If evaluations exist, read the most recent `findings.yaml` or `synthesis.md` to understand outstanding issues. Note severity counts (critical/major/minor).
8. **Revision state** — check for revision plans in `working/plans/`. If one exists for the current cycle, check pass completion status.
9. **Review state** — check for review reports in `working/reviews/`. Read the most recent if it exists.
10. **Prior recommendations** — check for `working/recommendations*.md`. Read the most recent to avoid repeating the same recommendation.

## Step 2: Apply the Decision Framework

Work through these priorities in order. Stop at the first one that applies — that is your recommendation.

### Priority 1: Phase-Driven Actions

Some phases have a single obvious next step:

- **Phase is `review`** → The revision cycle just finished. Recommend `/storyforge:review` to assess what changed and determine if the revision landed. Do not recommend other work until the review is done.
- **Phase is `complete`** → The manuscript is done. Recommend `/storyforge:produce` to set up production (chapter map, epub settings), or `./storyforge assemble` if the chapter map already exists.
- **Phase is `production`** → Assembly is underway. Check if output exists in `manuscript/output/`. If not, recommend `./storyforge assemble`. If it does, suggest reviewing the output or adjusting production settings via `/storyforge:produce`.

### Priority 2: Pipeline Cycle State

If a pipeline cycle is in progress, the next step is dictated by where the cycle is:

| Cycle status | Recommendation |
|---|---|
| `evaluating` | Evaluation is running. Wait for it to finish. |
| `planning` | Evaluation is done. Recommend `/storyforge:plan-revision` to design revision passes. |
| `revising` | Revision is running. Wait for it to finish. |
| `reviewing` | Revision is done. Recommend `/storyforge:review` to assess results. |
| `complete` | Cycle is done. Fall through to Priority 3+. |
| `pending` | Cycle just started. Check if evaluation has actually begun. |

Do not recommend starting a new activity when a cycle is mid-flight. Complete the current cycle first.

### Priority 3: Blockers

Work that prevents other work from happening:

- **Scene index is empty** → Nothing can be drafted. Recommend `/storyforge:scenes` to design the scene structure.
- **Voice guide is missing** → Drafting is blocked. Recommend `/storyforge:voice` to establish the voice.
- **No scenes drafted** but scene index exists and voice guide exists → Ready to draft. Recommend `./storyforge write` to begin drafting.

### Priority 4: Unaddressed Evaluation Findings

If an evaluation has been completed but no revision plan exists:

- Read `findings.yaml` from the most recent evaluation
- Count critical and major findings
- Recommend `/storyforge:plan-revision` with a specific mention of the finding count and top issues

If a revision cycle completed but critical findings remain unaddressed (check the most recent review report):

- Recommend running `./storyforge evaluate` for a fresh assessment, or `/storyforge:plan-revision` for a targeted follow-up cycle

### Priority 5: Artifact Gaps

Required artifacts that don't exist yet:

- **Character bible missing** → Recommend `/storyforge:develop` focused on character development. Be specific: "Build the character bible — start with your protagonist's wound/lie/need structure."
- **World bible missing** → Recommend `/storyforge:develop` focused on world-building.
- **Story architecture missing** → Recommend `/storyforge:develop` focused on story structure.

Prioritize whichever gap would most improve the next phase of work. For a project about to draft, character bible matters most. For a complex fantasy, world bible matters most.

### Priority 6: Deepening Existing Material

Artifacts exist but could be richer:

- Characters without wounds, contradictions, or relationship dynamics
- A world bible that's all geography and no texture or daily life
- A story architecture that's plot-only without thematic throughlines
- A scene index with scenes that lack clear functions or turning points
- A voice guide that hasn't been tested against actual prose samples

Recommend `/storyforge:develop` or `/storyforge:voice` or `/storyforge:scenes` with specific direction about what to deepen.

### Priority 7: Creative Exploration

The foundation is solid. Recommend creative work:

- What-if exercises and alternate approaches
- Thematic deepening
- Subplot development
- POV experiments
- Dialogue voice refinement for specific characters

Pick the exploration that would most enrich the manuscript based on what you read.

## Step 3: Present the Recommendation

### `full` coaching (default)

Present **one recommendation** with:
- What to do (specific skill or command)
- Why (1-2 sentence rationale tied to project state)
- Direction (enough specificity that the skill can execute immediately — not "work on characters" but "deepen the antagonist's motivation arc and trace how it creates conflict in the Act 2 turning points")

Then wait for the author's response.

**On approval:** Execute immediately. Invoke the recommended skill with the direction you provided. No intermediate questions — the "approve and go" contract applies.

**On rejection or redirect:** Take the author's direction without resistance. If they want something else entirely, do that. If they want a different option, present the next priority from the framework.

### `coach` coaching

Present the **top 2-3 viable options** from the decision framework, each with:
- What it is
- Why it matters
- What the trade-off is (doing this now vs. later)

Help the author reason through which is right for where they are. Ask: "Which of these feels right for where you are?" Execute their choice.

### `strict` coaching

Present **project state data only**:
- Current phase and cycle status
- Artifact status (exists / missing / incomplete)
- Scene counts and word count vs. target
- Outstanding evaluation findings (if any) with severity counts
- What the current pipeline cycle is waiting on (if applicable)

Then ask: "What do you want to work on next?" Execute whatever they say.

## Step 4: Write Recommendation Artifact (when requested)

If this skill was invoked in a context where a written recommendation is needed (e.g., end of an autonomous pipeline), write the recommendation to a file:

```markdown
# Next Steps — {title}
**After:** {what just completed}
**Cycle:** {cycle_id from pipeline.yaml, or "N/A"}
**Date:** {YYYY-MM-DD}

## Recommended Next Step
{The recommendation with rationale}

## Other Options
- {Next priority from framework, with brief rationale}
- {Another option, with brief rationale}

## Project Health
{One sentence assessment of where the manuscript stands}
```

Save to `working/recommendations-{cycle_id}.md` (or `working/recommendations.md` if no pipeline manifest).

Commit and push:
```
git add working/recommendations*.md working/pipeline.yaml
git commit -m "Recommend: next steps after {context}"
git push
```

## Important

- **Do not re-ask settled decisions.** Check the key decisions file before recommending anything that touches a previously decided topic.
- **Do not recommend against the current cycle.** If evaluation just finished and the cycle is in `planning` state, recommend plan-revision — don't suggest starting a new evaluation or drafting new scenes.
- **Be specific.** "Work on your characters" is not a recommendation. "Deepen Maren's wound/lie structure — her Act 2 choices don't yet connect to the childhood betrayal established in her backstory" is a recommendation.
- **One recommendation.** In `full` mode, pick the best one and pitch it. The author can always say no. Having one strong recommendation is more useful than a menu of five.
