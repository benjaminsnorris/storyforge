# Final Evaluation Mode — Design Spec

**Date:** 2026-03-27
**Status:** Approved

## Summary

Add a `--final` flag to `storyforge-evaluate` that tells evaluators this is the last evaluation before the manuscript goes to beta readers. This shifts evaluator behavior in two ways: (1) focus on issues outside readers would notice, and (2) filter out minor craft refinements that wouldn't affect the reading experience. The synthesis step adds a Beta Reader Readiness assessment with a three-tier confidence rating.

## Shared Context Block

Injected into every evaluator prompt when `--final` is passed. Placed after the `===== VOICE GUIDE =====` section, before `===== INSTRUCTIONS =====`:

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

## Per-Persona Nudges

One sentence appended to the shared context block, tailored per evaluator:

- **first-reader:** "Your perspective is the closest proxy for these beta readers — be explicit about where you'd put the book down, where you'd lose trust, and where you'd text a friend to say they have to read this."

- **developmental-editor:** "Focus on structural issues that would leave a reader feeling the story didn't hold together — dropped threads, unearned turns, pacing dead zones. Save fine-grained scene function notes for a future pass."

- **line-editor:** "Focus on prose issues that would pull a non-specialist reader out of the story — confusing sentences, jarring tense shifts, dialogue that rings false. Pattern-level tics that only another writer would notice can be flagged briefly."

- **genre-expert:** "Focus on where genre readers' expectations would be violated in ways that feel like mistakes rather than deliberate subversions. Would a reader of this genre feel they got what they came for?"

- **literary-agent:** "Assess this as if the author is about to share it with a small group before querying. What would you want fixed before anyone outside the author's circle sees it?"

- **writing-coach:** "This is the last evaluation before outside readers. Focus your guidance on what the author should protect during any final touch-ups, and flag only growth edges that are actively visible to readers — not long-term craft development."

## Synthesis: Beta Reader Readiness

A new required section added to the end of both the interactive and API-mode synthesis prompts, after "Overall Assessment":

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

- **New flag:** `--final` on `storyforge-evaluate`. Sets `FINAL_EVAL=true`.
- **`build_eval_prompt()` (~line 490):** When `FINAL_EVAL` is true, inject the shared context block + per-persona nudge after the voice guide section. Persona nudge selected via `case $evaluator` block.
- **Synthesis prompts (both interactive and API-mode):** When `FINAL_EVAL` is true, append the Beta Reader Readiness section after the Overall Assessment instructions.
- **No changes to:** evaluator persona files, scoring prompts, craft weights, CSV formats, or library code. This is purely prompt injection gated on a flag.
