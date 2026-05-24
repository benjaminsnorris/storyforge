# Cascade mechanics between elaboration levels

Research design doc for issue [#226](https://github.com/benjaminsnorris/storyforge/issues/226), under the umbrella [#224](https://github.com/benjaminsnorris/storyforge/issues/224).

Companion to [the levels-and-shapes doc](2026-05-24-elaboration-levels-design.md) — read that first. Refers to its level numbering throughout.

Status: **draft**, expects iteration. Implementation out of scope.

---

## TL;DR

Three motions, not one.

- **Forward** — the default: elaborate a level into the next level down. Today's pipeline.
- **Upward** — a late-stage discovery propagates up: a brief reveals the protagonist actually wants X, the synopsis is no longer accurate.
- **Lateral** — re-propagate a change down only into affected branches, not the whole tree.

A new `storyforge cascade` command handles all three. It is **detection-deterministic, resolution-creative**: the system identifies what's out of sync and what's affected; the author (often via Claude in a session) decides what to do about it. Conflict surface aligns with `sync`'s existing conflict report format.

The most important design choice in this doc is **cost visibility**: before any cascade fires, the system surfaces the *blast radius* (how many lower-level units could be affected) so the author can decide whether to take the change at all.

---

## Why three motions

The existing `elaborate` pipeline is forward-only. You can rerun any stage, but the system has no idea which downstream artifacts are now stale. The author either manually re-elaborates everything below the change (expensive) or accepts silent drift (eventually fatal).

The three motions correspond to three real authoring situations:

1. **Forward (default).** The author has finished iterating at level N and is ready to elaborate into N+1. The cascade has nothing to do here — it's just the existing elaborate flow. Forward is the only motion that *generates new content*; the other two propagate or surface drift on content that exists.

2. **Upward.** The author makes a change at some level N (often from a discovery while working at a lower level). Higher levels may now be wrong. Example: while writing the briefs for Act 2, the author realizes the protagonist's want is actually about belonging, not achievement. The synopsis and logline no longer fit. The act-shape's middle paragraph is wrong. The system should *flag* these as affected and the author should resolve.

3. **Lateral.** The author makes a change at level N and the change needs to flow down — but only into the branches that touched the changed content. Example: the inciting incident moves from "the wife dies" to "the wife leaves." Spine event 2 changes; architecture scenes 4–7 (which dealt with the consequence) need re-examination; scenes 12–14 (which deal with later consequences) may also need updates; everything else is untouched.

Forward and lateral can blur — both move downward. The distinction is that *forward* generates new content where none existed, while *lateral* updates existing content whose upstream input has shifted. Treat them separately in the design because the author's intent differs (creating vs. reconciling).

---

## The cascade as graph traversal

Think of the project as a graph:

- **Nodes** are level artifacts (logline, synopsis, act-shape, each spine event, each scene at architecture/map/briefs/draft level).
- **Vertical edges** connect each node to its parent(s) at the level above and its children at the level below.
- **Horizontal edges** are derivation relationships among nodes at the same level (e.g., a scene at brief level depends on continuity_deps from prior scenes — already tracked in scene-briefs.csv).
- **Cross-cutting edges** connect every node to the bibles and registries it references.

A cascade is a graph walk: starting from a changed node, identify the neighborhood that may be affected, surface it.

**Vertical edges are the load-bearing ones for cascade.** Horizontal edges are already handled by `hone` and the brief continuity_deps machinery. Cross-cutting edges are mostly scoring concerns (#227), not cascade.

---

## Detection: how the system finds drift

Drift detection is deterministic where possible, LLM-driven where necessary.

### Deterministic detection

Several drift cases can be flagged without an LLM:

| Detection | Where | How |
|---|---|---|
| A spine event has no descendant scenes | Spine → Architecture/Map | No `scenes.csv` row maps to spine event N |
| An architecture scene has no entry in scene-intent.csv | Architecture → Map | Row missing |
| A brief references a `value_at_stake` not in `values.csv` | Briefs ↔ Registries | Set difference |
| A scene's `pov` character is not in `characters.csv` | Map ↔ Registries | Set difference |
| A draft scene's word count is 0 (untouched) | Briefs → Draft | `word_count` column check |
| A prose-tier section's `_updated` timestamp is older than a downstream level's | Logline → Synopsis, etc. | Frontmatter date compare |
| The MD file for a scene exists on disk but `status` is `briefed` | Status drift | File presence vs. status |

These are coverage and freshness checks. They produce hard "X is missing / out of date / inconsistent" signals.

### LLM-driven detection

Some drift can only be detected by reading both sides:

- "Does this synopsis still describe what the spine says happens?" — semantic comparison.
- "Does scene 14's brief honor the emotional arc that scene-intent says it has?" — semantic comparison.
- "Does the logline still fit the story?" — broad semantic comparison.

These are expensive and noisy. They should run **on demand** (when the author asks "is this still aligned?") rather than continuously. The cascade command can offer them as a flag (`--semantic`) but the default should be the cheap deterministic pass.

### A drift report

The output of detection is a structured drift report, written to `working/cascade-drift.md` (analogous to `working/sync-conflict.md`). Shape:

```markdown
# Cascade drift report

Generated at 2026-05-24T10:00:00Z against HEAD.

## Stale upward (downstream level changed, upstream may be wrong)

- **Synopsis** was last updated 2026-05-10. Spine events 3 and 7 were
  modified at 2026-05-23. Possible drift: synopsis may no longer reflect
  the current spine.
  - Affected unit: `reference/story-summary.md § Synopsis`
  - Suggested motion: upward refactor

## Stale downward (upstream changed, downstream may be wrong)

- **Spine event 4** ("inciting incident: the wife leaves") was updated
  at 2026-05-20. Architecture scenes 5–8 reference this event but were
  last updated 2026-05-12. Possible drift.
  - Affected units: scenes act1-sc05 through act1-sc08
  - Suggested motion: lateral re-propagation
  - Blast radius: 4 architecture scenes, 4 map scenes, 4 briefs, 4 drafts (if drafted)

## Coverage gaps (deterministic)

- Spine event 7 ("midpoint reversal") has no descendant scenes in
  architecture. Forward elaboration needed.

## Registry consistency (deterministic)

- Scene act2-sc12 references value_at_stake "honor" but `values.csv`
  has no such entry. Either add to registry or change the scene-intent value.

## Suggested next actions

- Upward: review the synopsis against the current spine.
- Lateral: reconcile architecture scenes 5–8 against the updated spine event 4.
- Forward: extend spine event 7 into architecture scenes.
- Hygiene: resolve the values.csv registry mismatch.
```

The report is human-readable and machine-parseable (one section per drift category, one bullet per affected unit).

---

## Resolution: how the system applies changes

The system **does not author content**. It identifies what needs work and what depends on what. The author does the creative work — either directly (editing files) or via Claude in a session ("here's the drift report, walk me through each item").

### The three motion patterns

#### Forward

Already exists as today's pipeline. Cascade adds nothing new for the forward motion except surfacing it as the natural next step in the drift report ("spine event 7 has no children — forward elaborate?").

#### Upward refactor

Triggered when a lower-level change implies an upper level is now stale. The cascade:

1. Identifies the affected upstream nodes from the drift report.
2. Renders side-by-side: current upstream content vs. a summary of what the lower-level changes are saying.
3. Prompts the author (or Claude-in-session) to update the upstream.
4. After update, the new upstream may itself imply *further* upstream changes — the cascade recurses upward through the drift report.

Upward never updates content automatically. It always asks.

#### Lateral re-propagation

Triggered when an upstream node has been edited and downstream branches need to be reconciled. The cascade:

1. Identifies the affected downstream nodes (the *branches* under the changed node).
2. For each affected branch:
   - If the branch is at a level the author hasn't iterated yet, re-elaborate forward from the changed upstream (regenerate the brief, draft, etc.).
   - If the branch has author work in it, *do not* regenerate — surface a conflict and ask the author to reconcile.
3. Tracks which branches have been reconciled and which still need attention.

The key constraint: **lateral re-propagation never silently overwrites author work**. If a brief exists, the cascade asks; if no brief exists, it re-elaborates.

### Conflict format

When resolution requires the author's call, the cascade writes a conflict to `working/cascade-conflict.md` with the same shape as `sync-conflict.md`: the two sides shown explicitly, with notes on how to resolve, plus a structured machine-readable section for tools (e.g., a future `cascade resolve` command).

Same conventions as `sync`:
- Author commits the resolution; the cascade re-runs and verifies.
- The hook (or `cascade --check`) refuses commits that leave drift unresolved (configurable per project).

---

## Triggers: when does cascade run

Three places:

1. **On demand: `storyforge cascade`** — primary path. The author runs it when they want to check or apply cascade.
2. **As part of `sync`** — `storyforge sync` already runs on every commit (via the pre-commit hook). Cascade detection can be wired in as a lightweight check that surfaces drift without blocking commits unless explicitly configured.
3. **Score-triggered** — when scoring (#227) detects a level's fidelity score has dropped, the score report can suggest running cascade. Not automatic.

The default cadence is: deterministic detection runs cheap and often (in the hook); LLM-driven detection runs rarely and on author command (`storyforge cascade --semantic`).

---

## CLI surface

A single command with subcommands and flags:

```
storyforge cascade [--check] [--semantic] [--from LEVEL] [--to LEVEL] [--scenes IDS]

storyforge cascade
  → Run deterministic detection, write drift report, exit 0 (no work performed)

storyforge cascade --check
  → Same as above but exit 1 if drift is present (for hooks/CI)

storyforge cascade --semantic
  → Run deterministic + LLM detection. Slow, costs money, more thorough.

storyforge cascade --from spine --to architecture
  → Focus detection on a specific boundary

storyforge cascade --scenes act1-sc05,act1-sc06
  → Focus detection on specific scenes' branches

storyforge cascade apply --to-branch act1-sc05
  → (Future) Apply a lateral re-propagation to a specific branch (regenerate
    its brief and draft from the current upstream, if no author work is present)
```

The `apply` subcommand is future work; v1 is detection only.

---

## Relationship to existing commands

| Command | Scope | New role |
|---|---|---|
| `storyforge sync` | Horizontal: CSVs ↔ MD | Unchanged. May invoke cascade detection as a lightweight check. |
| `storyforge revise` | Per-scene prose revision | Unchanged. Cascade doesn't touch prose-level revision. |
| `storyforge elaborate` | Forward elaboration | Becomes one of three cascade motions (the forward one). |
| `storyforge hone` | Registry consistency, brief quality | Already implements registry consistency at brief level. Cascade extends this pattern across levels. |
| `storyforge cascade` | Vertical: drift across levels | New. Detects + reports; doesn't author. |

The relationship between `sync` and `cascade` worth special note: they share the **conflict report format**, the **fail-closed hook integration**, and the **detection-deterministic, resolution-creative** philosophy. But sync resolves at the same level (CSV ↔ MD are different views of the same data); cascade resolves across levels (different content at different altitudes).

---

## Cost visibility

The single most important design constraint, and the one that makes cascade tractable instead of overwhelming.

Every drift item in the report carries a **blast radius**: the number of downstream units that *could* be affected. The author sees the cost before taking the change.

Example display:

```
- **Spine event 4** modified at 2026-05-20. Reconciliation cost:
    4 architecture scenes
    4 map scenes
    4 briefs (3 drafted)
    estimated tokens for full semantic re-check: ~12,000 input / ~3,000 output
    estimated wall time: ~5 min
```

This lets the author make the call: "yes, the change is worth the reconciliation cost" or "no, defer this and live with the drift until a polish pass."

Cost visibility also informs the system's behavior:

- Low blast radius (1–3 units) → cascade can suggest "I'll auto-apply this, ok?" with high default trust.
- Medium (4–15 units) → cascade surfaces, author reviews, applies one at a time.
- High (>15 units) → cascade refuses to auto-apply; author must work through each branch deliberately.

The thresholds are heuristics, configurable per project (in `storyforge.yaml`).

---

## Edge cases

### Conflict between upward and lateral

The author makes a change at the briefs level. Cascade detects:
- Upward drift: the synopsis no longer reflects this brief change.
- Lateral drift: the draft for this scene is now stale.

Which goes first?

**Upward first.** If the synopsis is wrong, *every* downstream level is potentially wrong, including the draft we were about to re-propagate. Resolve up first, then re-propagate.

Encode this in the cascade ordering: upward motions before lateral motions in the report.

### A change at multiple levels simultaneously

The author edits the synopsis AND a brief in the same session. Both upward and lateral cascades are now potentially relevant. What's the model?

The simplest model: **cascade processes one motion type at a time** in the order above (upward → lateral → forward). The drift report after the synopsis edit shows the lateral consequences; after those are reconciled, the next cascade run shows the new state.

This is slow but legible. Future optimization: a `cascade --plan` that shows the full multi-step reconciliation graph before any work.

### What if the author wants to *abandon* a level

E.g., the author decides the act-shape is wrong and wants to delete it (revert to having only the logline and synopsis). The cascade should detect: every downstream level depended on the act-shape, but the act-shape is gone. Treat it as a special case of upward drift — the upstream node was deleted, downstream nodes are orphaned.

Implementation note: don't delete the file; mark the section empty. Detection then triggers naturally.

---

## What's deliberately not in this doc

- **Scoring** — every drift detection here uses thresholds, but the *quality scores* underneath those thresholds belong in [#227](https://github.com/benjaminsnorris/storyforge/issues/227).
- **The exact LLM prompts** for semantic detection. Implementation, after scoring lands.
- **A formal proof that the graph is acyclic.** It is (levels go strictly downward, registries are leaves), but the doc doesn't prove it formally.
- **Performance optimizations.** First version runs everything every time; iteration on caching/incremental detection comes after real usage.

---

## Open questions

1. **Should the pre-commit hook block on cascade drift by default?** The argument for: drift is bad, surface it now. The argument against: drift is sometimes intentional (the author knows the synopsis is stale and will fix it after a few more scenes). My instinct: surface as warning by default, configurable to block per project.

2. **Should cascade `--apply` ever auto-apply changes without asking?** I lean no, even for trivial cases. The whole point of the cascade is that the author owns the creative resolution. Auto-apply could be useful for "the registry says X but the brief says Y, X is the registry source of truth, normalize Y" cases — but those should probably stay in `hone`, not bleed into cascade.

3. **How does cascade interact with the GN-mode revise pass?** GN revise rewrites a draft based on score findings. If revise changes the draft, that's downstream content changing — cascade should detect that the draft's brief may no longer match. But the right policy may be "drafts can drift from briefs" because the draft is the final artifact. Open.

4. **Multi-branch projects (a `revise` branch + an `elaborate` branch concurrently).** Cascade is currently scoped to a single working tree. Cross-branch reconciliation is out of scope but worth flagging.

5. **Does cascade emit machine-readable artifacts that future tools (e.g., a dashboard) can consume?** Probably yes — same shape as the scoring summary CSVs. Don't design this until the dashboard story is clearer.

---

## Acceptance criteria for the design

This doc is "done" when:

- The three motions are unambiguous and the boundary between forward and lateral is clear.
- The drift report format is concrete enough that a future implementer can build the detection code.
- The CLI surface answers "what command do I run when X happens?" for every X.
- Cost visibility is a first-class concept, not an afterthought.
- The relationship with `sync`, `revise`, `elaborate`, and `hone` is unambiguous.
- Open questions are listed; nothing is silently undecided.

(Self-assessment: all six pass at the draft level. Items 2 and 4 in "Open questions" want author input before implementation.)
