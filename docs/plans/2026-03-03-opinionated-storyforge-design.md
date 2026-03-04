# Opinionated Storyforge — Design

**Date:** 2026-03-03
**Scope:** End-to-end philosophy change across Storyforge plugin

## Core Principle

Storyforge is a confident collaborator. It makes creative decisions, executes them, and produces work for the author to review. The author steers by editing guidance before execution, or by redirecting after reviewing output.

**The author decides where to work. Storyforge decides how.**

## The Two-Layer Model

### Routing Layer (Hub)

The forge hub recommends what to work on next. One recommendation, one rationale. The author approves, redirects, or says "surprise me." This layer stays conversational — it's the moment where author and tool align on direction.

### Execution Layer (Skills + Scripts)

Once the author approves a direction, Storyforge executes with full creative authority. No sub-questions. No "what aspect do you want to explore?" No breaking the task into choices. Storyforge makes the creative calls, documents them, and produces work.

This applies to:
- Interactive skills (develop, scenes, voice) — execute immediately on invocation with direction
- Revision passes — all run autonomously, creative decisions documented as guidance
- The write script — already autonomous, unchanged

## Changes by Component

### 1. Revision Plan Schema (`working/plans/revision-plan.yaml`)

**Remove:** `type: interactive | autonomous` field.

**Add:** `guidance` list on passes that involve creative judgment. Each entry:
```yaml
guidance:
  - decision: "Fold difficult Calibrator encounter into Ch. 4"
    rationale: "Crisis context makes prejudice feel earned, not convenient"
```

**Add:** `summary` field populated after pass completion:
```yaml
summary: |
  Modified 4 scenes. Folded Calibrator encounter into Ch. 4 as planned.
  Placed Aven in Ch. 7 Protege scene. Added 3 tonal variation moments
  (Elias-Tessa Ch. 14 exchange, Maret Ch. 19 deadpan, Soraya Ch. 18 aside).
  Net word change: +1,200.
```

### 2. Revise Script (`scripts/storyforge-revise`)

**Remove:** The interactive fork — the `if type == interactive; break` logic that pauses execution and tells the author to go use a skill manually.

**All passes follow the same execution path:**
1. Read pass metadata (name, purpose, scope, guidance, subtasks)
2. Build revision prompt — inject guidance entries as creative direction
3. Invoke Claude autonomously
4. Claude produces summary of what was done
5. Script writes summary to YAML
6. Verify changes, commit, update status
7. Move to next pass

### 3. Revision Prompt Builder (`lib/revision-passes.sh`)

**Add:** New section in `build_revision_prompt()` that formats guidance entries:

```
## Creative Direction

The following decisions have been made for this pass. Execute on them directly:

- Fold difficult Calibrator encounter into Ch. 4 (Ashward Breach).
  Rationale: Crisis context makes prejudice feel earned, not convenient.

- Place first Aven appearance in Ch. 7 (the Protege scene).
  Rationale: ch07-sc04 already has a young Calibrator asking the right questions.
```

**Add:** Instruction to produce a brief post-pass summary covering: files modified, guidance followed, deviations from guidance (if any), and net word count change.

### 4. Plan-Revision Skill (`skills/plan-revision/`)

**Remove:** The interactive/autonomous decision matrix. No more "when in doubt, make it interactive."

**Replace with:** "When a pass involves creative judgment, make the calls yourself and document them as guidance entries with rationale. The author reviews the plan before execution and can edit any guidance entry they disagree with."

The skill still walks the author through the plan before saving — that's a natural review point. But it presents guidance as its own recommendations, not open questions.

### 5. Forge Hub (`skills/forge/`)

**Keep:** The recommendation step. Hub assesses project state, picks highest-value work, presents one recommendation with rationale.

**Change:** The "approve and go" contract tightens. On approval, the hub invokes the appropriate skill and that skill executes immediately. No intermediate pitch, no sub-questions.

Current: Author approves → skill asks "what aspect?" → author answers → skill works
New: Author approves → skill works

### 6. Interactive Skills (develop, scenes, voice)

**When invoked with specific direction:** Execute the direction. Make creative sub-decisions autonomously.

**When invoked without direction (via hub routing):** The hub already provided direction. Execute it.

**No more:** "What aspect of this character do you want to explore?" or "Which scenes should we focus on?" Storyforge picks the most impactful approach and does it. Author reviews output and redirects if needed.

### 7. Post-Pass Summaries

After any significant autonomous work (revision pass, skill execution in response to hub routing), Storyforge produces a brief summary:
- What was done
- Which guidance entries were followed
- Any deviations and why
- Files modified
- Net word count change (for revision passes)

This gives the author a review artifact without requiring them to read every diff.

## What Doesn't Change

- Evaluation pipeline (already autonomous)
- Write pipeline (already autonomous)
- Voice guide, scene index, and reference document formats
- The craft engine and voice rules
- Git commit/push behavior in the revise script
- The YAML as durable state machine for progress tracking

## Author Levers

The author's control points:

| When | Lever | Example |
|------|-------|---------|
| Before execution | Edit `guidance` in revision-plan.yaml | Change where Aven first appears |
| Before execution | Give specific direction to a skill | "Deepen Soraya, focus on the archive scene" |
| At the hub | Redirect the recommendation | "Not that — work on voice instead" |
| After execution | Review summary + diff | "The Calibrator encounter doesn't work, try folding it into Ch. 5 instead" |
| Anytime | Interrupt conversation | "Stop — go a different direction" |

## Migration

For the current Governor project:
1. Update `working/plans/revision-plan.yaml` — remove `type` fields, add `guidance` entries to the content-development pass (currently `type: interactive`)
2. The four autonomous passes already have `guidance` or `targets` fields — rename to use the `guidance` schema consistently
3. Re-run `./storyforge revise` — all passes execute without pausing
