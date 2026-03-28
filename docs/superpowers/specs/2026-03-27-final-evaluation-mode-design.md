# Final Evaluation Mode — Design Spec

**Date:** 2026-03-27
**Status:** Approved (v2 — expanded with cold-read evaluators and two-pass synthesis)

## Summary

Two related changes to `storyforge-evaluate`:

1. **Cold-read evaluators:** Remove all reference files (key-decisions, voice guide, story architecture, character bible) from evaluator prompts. Evaluators read only the manuscript text — the book must stand on its own.

2. **Two-pass synthesis:** Split synthesis into two passes:
   - **Pass 1 — Reconciliation:** Pure synthesis of evaluator reports. No reference files. "What did the panel actually say?"
   - **Pass 2 — Assessment:** Reads the reconciliation + reference files (voice guide, story architecture, key decisions). Assesses execution against intent. "Did we succeed at what we set out to do?"

3. **`--final` flag:** Adds a shared context block + per-persona nudge to evaluator prompts, and a Beta Reader Readiness section to the assessment pass.

## Change 1: Cold-Read Evaluators

Remove from `build_eval_prompt()`:
- The reference file loop that builds `ref_files` and `ref_inline`
- The `===== REFERENCE FILES =====` section in API mode
- The "Also read these reference files" instruction in interactive mode
- The `IMPORTANT: If key-decisions.md exists...` paragraph

Evaluators receive only: project context (title, genre, logline, scope), their persona, the voice guide section, and the manuscript text.

**Note:** The voice guide section stays in the evaluator prompt. It tells evaluators what voice the author is going for — this is analogous to a cover letter or style note that would accompany a manuscript submission. It does not reveal plot decisions or structural intentions.

**On reflection:** Actually, remove the voice guide too. The voice guide describes internal intentions about prose style. A real reader, agent, or coach would experience the voice and react to it without being told what it's supposed to be. If the voice guide is working, evaluators will describe what they experience. If it's not working, they'll describe that too — and the assessment pass can compare their experience against the voice guide.

Remove from `build_eval_prompt()`:
- The `===== VOICE GUIDE =====` section entirely

## Change 2: Two-Pass Synthesis

### Pass 1 — Reconciliation

**Input:** All evaluator reports. No reference files.

**Role:** "You are reconciling the evaluation reports from a multi-agent review panel."

**Output file:** `synthesis.md` (same location as today: `working/evaluations/eval-{timestamp}/synthesis.md`)

**Sections:**
- **Consensus Findings** — Issues or strengths identified by 3+ evaluators
- **Contested Points** — Areas where evaluators disagree
- **Prioritized Action Items** — Numbered list, ordered by impact
- **Strengths to Protect** — Elements to preserve in revision
- **Overall Assessment** — 2-3 paragraphs on where the manuscript stands

**Output file:** `findings.yaml` (same location, same format as today)

This is essentially the current synthesis prompt, minus the reference files and key-decisions filtering.

### Pass 2 — Assessment

**Input:** The reconciliation output (synthesis.md) + reference files (voice guide, story architecture, key decisions).

**Role:** "You are assessing the manuscript's execution against the author's stated intentions."

**Output file:** `assessment.md` (same eval directory: `working/evaluations/eval-{timestamp}/assessment.md`)

**Sections:**

- **Voice Guide Alignment** — Did the prose deliver the voice described in the voice guide? Where did evaluators feel it working, where did they feel it breaking?
- **Story Architecture Alignment** — Did the structural intentions land? Did the arcs, turning points, and thematic throughlines register with the panel?
- **Key Decisions Audit** — Which deliberate choices read as intentional to the panel? Which read as mistakes? For the ones that read as mistakes — is it an execution problem or just the inherent friction of a subversion?
- **Revised Priorities** — In light of the author's intentions, which findings from the reconciliation are the most important to address? Which can be set aside because they conflict with deliberate choices that are landing well enough?

The assessment pass only runs if at least one reference file exists. If no reference files are present, skip it — the reconciliation stands alone.

## Change 3: `--final` Flag

### Shared Context Block

Injected into every evaluator prompt when `--final` is passed. Placed after the persona section:

```
===== EVALUATION CONTEXT =====

This is a final evaluation. The author plans to send this manuscript to beta
readers after this cycle. Evaluate with that lens:

- Focus on issues that outside readers would notice, stumble on, or be
  confused by.
- Minor craft refinements that wouldn't affect a reader's experience should
  be noted briefly but should not dominate your report or be prioritized
  highly.
- Assess whether this manuscript is ready for outside eyes. What would
  embarrass the book in front of readers who don't know the author?
```

### Per-Persona Nudges

One sentence appended to the shared context block, tailored per evaluator:

- **first-reader:** "Your perspective is the closest proxy for these beta readers — be explicit about where you'd put the book down, where you'd lose trust, and where you'd text a friend to say they have to read this."
- **developmental-editor:** "Focus on structural issues that would leave a reader feeling the story didn't hold together — dropped threads, unearned turns, pacing dead zones. Save fine-grained scene function notes for a future pass."
- **line-editor:** "Focus on prose issues that would pull a non-specialist reader out of the story — confusing sentences, jarring tense shifts, dialogue that rings false. Pattern-level tics that only another writer would notice can be flagged briefly."
- **genre-expert:** "Focus on where genre readers' expectations would be violated in ways that feel like mistakes rather than deliberate subversions. Would a reader of this genre feel they got what they came for?"
- **literary-agent:** "Assess this as if the author is about to share it with a small group before querying. What would you want fixed before anyone outside the author's circle sees it?"
- **writing-coach:** "This is the last evaluation before outside readers. Focus your guidance on what the author should protect during any final touch-ups, and flag only growth edges that are actively visible to readers — not long-term craft development."

### Beta Reader Readiness (in Assessment Pass)

When `--final` is set, the assessment pass adds a final section:

```
## Beta Reader Readiness

Assess whether this manuscript is ready for beta readers. Use one of these
three ratings:

**Ready with high confidence** — The manuscript is solid. Beta readers will
engage with the story on its own terms. Any remaining issues are minor and
won't undermine the reading experience.

**Ready with reservations** — The manuscript can go to beta readers, but
certain issues may surface in their feedback. List what those issues are
and what the author should expect to hear.

**Not ready** — There are issues that should be addressed before outside
readers see this. List the specific blockers and why they matter.

Whichever rating you choose, explain your reasoning in 2-3 paragraphs.
Ground it in the evaluator reports — this should feel like a synthesis
judgment, not a new opinion.
```

## Implementation Surface

- **`build_eval_prompt()`:** Remove reference file loop, voice guide section, and key-decisions note. Evaluators get only: project context, persona, final eval block (if `--final`), manuscript, and instructions.
- **Current synthesis:** Becomes Pass 1. Remove reference file list/inline from both interactive and API prompts. Remove key-decisions filtering instruction. Output: `synthesis.md` + `findings.yaml`.
- **New Pass 2:** Add after Pass 1. Reads synthesis.md + reference files. Produces `assessment.md`. Only runs if reference files exist. When `--final`, includes Beta Reader Readiness section.
- **`SYNTH_READINESS` variable:** Moves from Pass 1 to Pass 2.
- **Dry-run output:** Add Pass 2 placeholder to dry-run section.
- **No changes to:** evaluator persona files, scoring prompts, craft weights, CSV formats, or library code.
