# Review synthesis and design revisions

Final design doc for umbrella [#224](https://github.com/benjaminsnorris/storyforge/issues/224). Companion to the three research docs already on this branch — this one rolls in the cross-cutting feedback from a four-agent review pass and supersedes the originals where they disagree.

The originals remain useful as the *pre-review* artifact (and as detailed argument for the parts that survived); this doc is the *post-review* proposal and should drive implementation when the time comes.

Status: **proposal**, ready for author sign-off.

---

## The review, in one paragraph

Four agents read the three originals from different angles: implementation cost / feasibility, author workflow / friction, story-craft skepticism, and voice / authorial distinctiveness. They converged surprisingly hard. The praise was unanimous on a small set of design principles (blast radius / cost visibility, detection-deterministic-resolution-creative, don't-compose, choosiness). The critique was also unanimous on a different small set — each angle vocalized it differently, but every reviewer pointed at: *the design pressures the author toward compliance with a rubric the author can't override*. Multiple specific mechanisms drive that pressure, listed below.

The revisions in this doc address the consensus critique without touching the praise list.

---

## What carried through unchanged

The originals' load-bearing decisions all survive review:

- **Eight levels in two tiers** (3 prose-tier, 5 structural-tier). The closest-call boundary (synopsis ↔ act-shape) earns its keep.
- **Three motions** — forward, upward refactor, lateral re-propagation.
- **Three score families** — per-level quality, cross-level fidelity, cross-cutting consistency.
- **Don't compose scores. Show every axis.**
- **Detection-deterministic, resolution-creative.**
- **Be choosy** — explicit keep / on-demand / skip pass on every score.
- **Blast radius / cost visibility before any cascade fires.**
- **Lateral re-propagation never silently overwrites author work.**
- **LLM checks confined to on-demand, never in the commit hook.**

Don't relitigate these. They held.

---

## The big move: faithfulness as diff, not score

This is the most important change. It addresses voice, craft-skeptic concerns, and the author-override gap in a single restructure.

**The problem.** The originals proposed an "upward faithfulness" score (0.0–1.0) at each level boundary, LLM-judged. The voice reviewer named the failure mode precisely: an LLM can't tell *drift* (the lower level departed in error) from *discovery* (the lower level found something the upper level didn't know yet). A number that conflates the two will be acted on — and the action will be reconciliation toward the LLM's idea of "faithful," which is consensus prose at the level above. The system will systematically push authorial discovery back into convention.

**The change.** Replace the upward-faithfulness *score* with an upward-faithfulness *diff*. At each boundary, when triggered:

1. The system surfaces the two sides as a structured comparison — what the upstream level says about this story unit, what the downstream level is doing.
2. The author records a verdict: `correct=upstream`, `correct=downstream`, `both are right`, or `needs work`. A one-line rationale is optional but encouraged.
3. The verdict persists across runs in `working/scoring-verdicts.csv` (scene/unit + boundary + verdict + rationale + timestamp).
4. The system does not re-flag a boundary where a verdict is recorded unless one side has materially changed since the verdict.

**What this preserves.** The LLM is still doing semantic comparison — the same prompt, the same cost. We just stop emitting a number for the comparison's result.

**What this changes.** The author's judgment is a first-class output, not a workaround. The path of least resistance is to read the comparison and decide, not to make the LLM happier. Story discovery is protected from being talked back into consensus.

**Where scores still apply.**
- *Deterministic* coverage checks at structural boundaries still emit scores (these are objective: does every spine event have descendants, do all values resolve to the registry). They're cheap, the failure mode is unambiguous, and the fix is concrete.
- *Per-level quality* still emits scores for deterministic axes (length, presence of required fields, registry conformance). For LLM-judged quality axes (the prose-tier ones at levels 0–2), use the diff-and-verdict mechanism too.
- *Bible consistency* uses the diff-and-verdict mechanism. Two sources disagree — which is correct?

The two-table reporting view changes accordingly: deterministic axes get a number; LLM-judged axes get a "verdict pending / accepted / disagreed" status.

---

## Author affordances (three new mechanisms)

### 1. Score overrides

A `working/scoring-overrides.csv` file (pipe-delimited, sibling of `score-history.csv`) where the author marks any score finding as `considered_accepted` with a one-line rationale and a timestamp. The score continues to surface, but with the marker — and the cascade / quality-gate logic ignores it for refusal purposes.

```
scope|axis|finding_id|verdict|rationale|recorded_at
the-blank-page|economy_clarity|low-density|accepted|sparse is intentional here|2026-05-24
act1-sc12|brief_fidelity|missing-key-dialogue|accepted|the dialogue moved offstage on purpose|2026-05-24
```

Verdicts are scoped tightly: a verdict on `act1-sc12 / brief_fidelity / missing-key-dialogue` only suppresses that specific finding. If a different brief-fidelity finding appears for the same scene, it surfaces normally.

### 2. Drafting mode

A project-level mode that suspends cascade and pre-commit quality checks during active drafting. Two surfaces:

- `STORYFORGE_DRAFTING=1 git commit ...` for one-off bypass.
- `project.cascade_mode: live | drafting | paused` in `storyforge.yaml`. `drafting` suspends cascade in the hook; `paused` suspends both cascade and sync's quality gates entirely.

When in drafting mode, the hook still runs sync (CSV↔MD) — that's the bare-minimum integrity check — but cascade detection is silent. The author resumes by changing the mode back to `live` and running `storyforge cascade --check` explicitly.

This is the "I just want to write" override. Without it, the system trains authors to commit less often, which breaks everything else.

### 3. Acceptance thresholds with persistence

Each axis has a project-configurable acceptance threshold (defaulted loosely). An `accepted_at` field on `score-history.csv` lets the author declare "this level is done" at any score. The system stops nagging about that axis until either (a) the underlying content materially changes, or (b) the author explicitly re-opens it.

```yaml
# storyforge.yaml
scoring:
  acceptance_thresholds:
    economy_clarity: 0.7   # below this it's surfaced, above it it's just shown
    brief_fidelity: 0.6
    # ... per-axis defaults; project can override
  acceptance_strategy: loose  # loose | strict | manual
```

`loose` defaults applied automatically when scores cross threshold; `strict` requires explicit author confirmation; `manual` never auto-accepts (author marks everything individually).

---

## Cascade revisions

### Neutralize the language

"Stale upward" → "no longer in agreement." "Synopsis may no longer reflect the current spine" → "synopsis and spine are no longer aligned; reconcile direction TBD." "Drift" stays as the technical term (it's precise) but the *suggested action* phrasing becomes symmetric: not "review the synopsis against the current spine" but "reconcile synopsis with spine (either direction)."

The cascade doc's existing "Suggested next actions" framing gets removed. The drift report enumerates *what is out of alignment*, not *what should be done about it*. The author (or Claude in session) decides direction.

### Cap upward recursion

The original cascade doc had a quietly dangerous line: "the new upstream may itself imply further upstream changes — the cascade recurses upward through the drift report." A single creative insight at the brief level could drag the author through logline → synopsis → act-shape → spine reconciliation in one session.

**Revision: cascade goes up at most one level per `cascade --semantic` invocation.** If the author updates the spine after reconciling it with architecture, *then* the next cascade run can surface synopsis-spine drift. Recursive upward propagation requires an explicit `--recurse` flag or repeated runs.

This keeps the author in control of how deep a refactor goes.

### Defer the `storyforge cascade` command

The cascade command as designed is ~5 subcommands and a CLI taxonomy. Ship it incrementally:

- **v1: `storyforge score --drift`** — read-only drift report from the existing scoring machinery. No new command. Output is the structured report at `working/cascade-drift.md`.
- **v2: `storyforge cascade --semantic`** — adds LLM-driven semantic detection on top of the deterministic skeleton.
- **v3: `storyforge cascade apply ...`** — anything that *modifies* content. Out of scope until v1/v2 have been in author hands long enough to validate the surface.

### Drift detection: mtime AND content hash

The originals proposed mtime-only drift detection. The workflow reviewer caught the problem: a typo in a brief updates the mtime, the cascade flags downstream drift, the author commits a one-character fix and the hook refuses.

**Revision:** drift signal is `mtime_changed AND content_hash_differs`. Store last-seen content hashes per file in `working/.cascade-state` (gitignored). A typo touches mtime but not the hash — no drift. A meaningful edit touches both. The over-engineering objection from the original cascade doc was wrong; this is a one-file state cache, not a graph of derivations.

---

## Scoring revisions

### Add an explicit thematic axis

The story-craft reviewer was right: no rubric across eight levels asks "is this story about something?" Motif registries are vehicles for theme, not theme itself.

**Revision: add `## Theme` as a fourth section in `reference/story-summary.md`** — alongside Logline, Synopsis, Act-shape. Two-to-four sentences naming what the story argues. The argument is internal-use only (it's not pitch material) and explicit.

Scoring axes on the theme section:
- *Presence* — deterministic. Empty section → finding.
- *Engagement at lower levels* — LLM, on-demand. Do the briefs and drafts engage with this theme, or does it disappear after level 0?

This is the smallest possible addition that gives the system a place to ask the most important story question.

### Genre / structure escape hatch

The originals encoded three-act, Swain action/sequel, McKee value shifts, and Weiland brief contracts as universal rules. They're one tradition (commercial American screenwriting + popular novel craft). They don't fit kishōtenketsu, mosaic, fragmented narrative, plotless literary, picaresque, or vignette-driven work.

**Revision:** add `project.structure` field to `storyforge.yaml`:

```yaml
project:
  structure: three-act        # three-act | four-act | kishōtenketsu | mosaic | episodic | custom
```

When `structure: custom`, the structure-specific scoring checks (action/sequel alternation, three-act value-shift distribution, "events spread evenly across acts") are *disabled*. The author opts in to whatever subset they want via a `scoring.enabled_checks` list. Default for novel mode is `three-act`; default for graphic-novel is `three-act` too unless author specifies.

Other structures get bundled checks (e.g., `kishōtenketsu` enables a four-act value-shift check with a specific pattern). Bundled checks are out of scope for v1; the escape hatch (`custom`) is what ships.

### Demote the causal-chain LLM check

The original scoring doc listed "Causal chain holds (event N enables event N+1)" as a level-3 LLM check. The craft skeptic was right: postmodern, magic-realist, mosaic, and theme-driven structures intentionally violate causal chains. An LLM saying "event 3 doesn't lead to event 4" might be confused or might be right — but the cost of false positives here is high.

**Revision:** move causal-chain to an *advisory* tier in the level-3 quality report. It still runs (on demand, with `--advisory`), but its findings are labeled `advisory` and excluded from acceptance thresholds and quality gates. The author can choose to look at them.

### Bible / voice consistency: neutral framing

Originals framed bible checks as "does the prose honor the bible?" — putting the bible in the authority position. For character development this is backwards: the character *is being discovered* through writing. The check should be neutral.

**Revision:** all bible-consistency findings use the form *"Bible and prose disagree: bible says X, scene N says Y. Verdict?"* with the diff+verdict mechanism. The author records which is correct — sometimes it's the bible (update the scene), sometimes the scene (update the bible), sometimes both are right (the character has multiple facets).

### Prompt caching for bibles is mandatory, not optional

The engineering review caught the cost: a full bible-consistency pass on a 50-scene novel is ~$20-25 with prompt caching and ~$80 without. **The design now mandates `cache_control` on bible content** — bibles are stable across a scoring run, and the caching infrastructure already exists in `api.py`. The doc states the cached cost ($20-25) explicitly and recommends running this pass at most once per major milestone (pre-revise, pre-publish).

---

## Schema and engineering decisions

### Defer the `spine_event` column

The original scoring doc proposed adding a `spine_event` column to `scene-intent.csv` to make 3→4 downward coverage trivially deterministic. The engineering review showed this is ~400-600 LOC across 8 files plus a schema migration plus per-architecture-scene population logic.

**Revision: defer.** v1 uses LLM-driven mapping for 3→4 downward coverage (one call per cascade run that asks "which spine event does this architecture scene serve?"). This is cheap (~$0.05/run with caching) and good-enough at the scale a single project operates at. If v1 in author hands proves the mapping is slow or lossy, add the column in v2 with a proper migration.

### Hook performance budget

The pre-commit hook gets a hard limit: **<500ms on a 100-scene project**. A test enforces it. Any deterministic check that can't meet the budget is downgraded to on-demand. Without this discipline the hook gets slow, authors set `STORYFORGE_SYNC_SKIP=1`, and the data-integrity guarantee evaporates.

### What ships in v1 (the shippable cut)

The engineering review's "v1 cut" landed on roughly what I'd commit to:

**v1 includes:**
- New file `reference/story-summary.md` with sections: Logline, Synopsis, Act-shape, Theme. Template at `templates/reference/`.
- `storyforge init` writes the file pre-seeded with the project's logline.
- One-time migration of `storyforge.yaml:project.logline` into the new file (loud, atomic, single command).
- A parser in `common.py` that reads the four sections.
- `storyforge score --level N` extension that emits deterministic quality + registry checks for levels 3–6 (generalizing existing `hone.py` + `structural.py` logic).
- The orphan-registry check generalized across all structural levels.
- `working/scoring-overrides.csv` and the parser for it.
- `STORYFORGE_DRAFTING=1` env-var bypass.
- `storyforge score --drift` — read-only drift report combining deterministic coverage + timestamps + content-hash deltas.
- `project.structure` field with `custom` as the escape hatch.

**v1 does NOT include:**
- The `spine_event` column (deferred).
- The `storyforge cascade` command (ships as `score --drift` first).
- LLM-driven semantic boundary checks (the diff+verdict mechanism is designed but the v1 doesn't run the LLM calls — runs deterministic only).
- Bible-consistency pass (the most expensive feature; designed but deferred).
- Pre-commit hook integration of new quality gates (hook stays as-is; quality gates are opt-in).

Rough effort: ~600 LOC of Python, one template file, one new module, modest extensions to `cmd_score.py` and `schema.py`, plus tests. Two weeks of focused work, no schema migration, no new hook surface, no LLM cost story to explain at v1.

### Effort beyond v1

v2 adds: LLM-driven semantic comparison at the prose-tier boundaries; bible-consistency with caching; the diff+verdict mechanism running over LLM checks; one round of acceptance-threshold tuning based on v1 usage.

v3 adds: the proper `storyforge cascade` command surface (after `score --drift` has been used long enough to inform the design); the `spine_event` column if mapping perf is insufficient; bundled checks for non-three-act structures.

---

## Open questions remaining after review

1. **Where does the scoring-verdicts file live?** Proposed `working/scoring-verdicts.csv` for now. Alternative: `reference/scoring-verdicts.csv` (canonical, committed). Argument for `reference/`: verdicts are author-authored content, not ephemeral state. Argument for `working/`: they're tied to current content and shouldn't bloat the canonical reference set. Lean `reference/` if pressed; flag for resolution.

2. **Theme axis: how deep does it go?** v1 has Theme as a section in story-summary.md with deterministic presence + LLM engagement checks. Should there also be a `theme_engaged` boolean column on `scene-intent.csv`? Probably not in v1 — too much schema commitment for a feature that should prove itself first.

3. **`project.structure: custom` semantics.** When `custom`, which checks are disabled by default? Strict interpretation: all structure-specific checks (action/sequel, value-shift distribution, three-act partitioning) are off. Loose: only the ones the author explicitly opts out of. Lean strict — opt-in is safer than opt-out for the escape hatch.

4. **Cascade UI for the diff+verdict flow.** When a comparison is surfaced, what does the author actually see? A markdown file with the two sides + a verdict line they fill in? A slash-command in a Claude session? Both? Defer to implementation; flagged here so it doesn't get forgotten.

5. **What happens to existing scoring (the 25-principle novel scorer) under the new framing?** It's level 7 quality; surfaces unchanged. The boundary scoring for 6→7 (does draft honor brief) reuses the existing `brief_fidelity` deterministic check + the existing `revise --findings` LLM loop. No restructure needed. But: when a scene scores 0.42 on `economy_clarity`, does the diff+verdict mechanism apply, or is that a "real" deterministic score the author should just fix? The distinction matters. Lean: deterministic scores stay as numbers; LLM-judged comparisons become diff+verdict.

---

## Self-assessment

This synthesis is "done" enough to act on when:

- The five consensus critiques from review (override, drafting bypass, faithfulness-as-score, cascade-as-drift-problem, structure assumptions) all have concrete revisions. ✓
- The biggest individual critique (no thematic axis) is addressed. ✓
- The most expensive engineering surprise (`spine_event` column) is acknowledged and deferred. ✓
- The v1 cut is shippable in ~2 weeks of focused work. ✓ (per engineering review)
- The originals remain accurate as the *pre-review* design state; this doc is the *post-review* proposal. ✓

Remaining work before implementation:
- Author sign-off on the revisions (especially the faithfulness-as-diff change, the v1 cut, and the deferred `cascade` command).
- One more pass through the design specifically to check: are there any places the originals' rubrics still encode "compliance = good" by accident? The choosiness pass was good; a second pass with the explicit framing of "this measures structural integrity, not life" may catch axes that still sneak through.

(Self-assessment: comfortable with this proposal as the next step. The reviews caught real weaknesses, the revisions address them without unraveling the core design, and the v1 cut is honest about what we'd actually build first.)
