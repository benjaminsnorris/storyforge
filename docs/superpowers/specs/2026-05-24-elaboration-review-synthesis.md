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
2. **Who records the verdict depends on coaching level:**
   - **full** (default): the LLM looks at the content history on both sides, proposes a verdict (`correct=upstream` / `correct=downstream` / `both are right` / `needs work`) with a one-line rationale, and the proposal is always called out in the cascade review so the author can override.
   - **coach**: the LLM proposes; the author confirms or overrides before the verdict is recorded.
   - **strict**: only the author records verdicts. The LLM still produces the diff but never the verdict.
3. The verdict persists across runs in `working/scoring-verdicts.csv` (scene/unit + boundary + verdict + rationale + actor + timestamp). `actor` records whether the LLM proposed or the author authored.
4. The system does not re-flag a boundary where a verdict is recorded unless one side has materially changed since the verdict (content-hash delta, not just mtime).

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

### Add an explicit thematic axis — with per-scene tracking

The story-craft reviewer was right: no rubric across eight levels asks "is this story about something?" Motifs in the existing registry are concrete *vehicles* for theme, not theme itself.

**Revision: two additions.**

1. **Add `## Theme` as a fourth section in `reference/story-summary.md`** — alongside Logline, Synopsis, Act-shape. Two-to-four sentences naming what the story argues. The argument is internal-use only (not pitch material) and explicit.

2. **Add `reference/themes.csv` registry** — abstract concerns the story is about. Same pattern as `mice-threads.csv` / `values.csv`:

```
id|name|tier|description
legibility|Legibility|primary|What is and isn't legible, to whom.
recovery|Recovery|primary|What can be brought back from loss.
erasure|Erasure|secondary|What gets erased and what survives.
```

And **add a `theme_threads` column to `scene-intent.csv`** — semicolon-delimited list of theme IDs that each scene engages. Mirrors `mice_threads`.

Scoring axes on the theme dimension:
- *Theme section presence* — deterministic. Empty `## Theme` → finding.
- *Themes registry presence* — deterministic. Empty themes.csv → finding (after Theme section is written).
- *Per-theme coverage* — deterministic. For each registered theme, what fraction of scenes engage it? Flags themes with too few scene engagements (decorative themes that never land) or too many (one theme drowning out the others).
- *Theme distribution* — deterministic. Where in the story does each theme light up? Flags themes that vanish for entire acts.
- *Per-scene engagement validity* — LLM, on-demand. Does this scene actually engage the themes its `theme_threads` claims, or is it tagged-but-not-engaged?

**Themes vs motifs.** They stay as separate registries. Themes are abstract concerns ("what does it mean to remember?"); motifs are concrete recurring elements ("the wire spectacles," "the lamp glow on paper"). The relationship is many-to-many: a theme can be carried by several motifs; a motif can serve several themes. Conflating them would lose information — `legibility` is a theme but not a motif; `wire spectacles` is a motif that might serve `legibility` as one of its themes. Per-scene tracking lives in two columns: `theme_threads` on scene-intent.csv (which abstract concerns this scene engages) and `motifs` on scene-briefs.csv (which concrete recurring elements appear in this scene). The motif registry stays as-is.

### Genre / structure assumptions

The originals encoded three-act, Swain action/sequel, McKee value shifts, and Weiland brief contracts as universal rules. The reviews proposed a `project.structure: custom` escape hatch for non-three-act stories.

**Revision:** drop the `custom` option for v1. Author judgment (PR review): too much work for too little value at this stage. v1 assumes three-act throughout. Non-three-act stories can use whatever scoring axes apply to them and ignore the rest via the score-overrides mechanism. If specific bundled checks (kishōtenketsu, mosaic) emerge as a real need, they're added in a follow-up.

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

### Structural-anchor tier: discrete artifacts, two new columns

The original docs treated the spine and architecture levels as `status` flags on the shared `scenes.csv`. Author pushback (PR review): the levels aren't just "same rows with more columns" — they have **different row counts**. The spine is 5–10 events; architecture is 15–25 anchor scenes; the scene map is 40–60 scenes. Each tier transition expands the row count by elaborating each upstream unit into multiple downstream units.

**Revision: the structural tier splits into discrete artifacts.**

| Tier | Artifact(s) | Row count |
|---|---|---|
| Structural anchors | `reference/spine.csv` | 5–10 |
| Structural anchors | `reference/architecture.csv` | 15–25, each with `spine_event` → spine.csv |
| Manuscript | `reference/scenes.csv` + companions | 40–60, each with optional `architecture_scene` → architecture.csv |

Two new reference columns make the level boundaries explicit:

- `spine_event` on `architecture.csv` — every architecture row names its parent spine event. Required.
- `architecture_scene` on `scenes.csv` — every map scene either *is* an architecture anchor (`architecture_scene = own_id`) or sits adjacent to one (`architecture_scene = nearest_anchor_id`) or is purely interstitial (`architecture_scene = ''`). Optional.

The deterministic downward-coverage checks fall out of this for free: "every spine event has at least one architecture row referencing it"; "every architecture anchor has at least one map scene linked to it." Both are set-membership operations, both ship in v1.

Why this is in v1 rather than deferred: the original engineering review estimated ~400–600 LOC across 8 files because it imagined the column added on top of the existing single-CSV-with-status pattern. Splitting into discrete artifacts is a different (and cleaner) refactor — and the user wants it from the start because the artifact split is what makes "the spine" something you can refer to as a thing.

Migration for existing projects (Ashes, Meridian) is mechanical: `cmd_migrate` extracts `status=spine` rows from scenes.csv into spine.csv, copies `status=architecture` rows into architecture.csv, and populates `spine_event` references where derivable. Author confirms the spine event count.

### Hook performance budget

The pre-commit hook gets a hard limit: **<500ms on a 100-scene project**. A test enforces it. Any deterministic check that can't meet the budget is downgraded to on-demand. Without this discipline the hook gets slow, authors set `STORYFORGE_SYNC_SKIP=1`, and the data-integrity guarantee evaporates.

### What ships in v1 (the shippable cut)

The engineering review's "v1 cut" landed on roughly what I'd commit to:

**v1 includes:**
- New file `reference/story-summary.md` with sections: Logline, Synopsis, Act-shape, Theme. Template at `templates/reference/`.
- `storyforge init` writes story-summary.md pre-seeded with the project's logline, plus empty `themes.csv`, `spine.csv`, `architecture.csv` with their headers.
- One-time migration of `storyforge.yaml:project.logline` into the new file (loud, atomic, single command).
- Migration of existing `status=spine` and `status=architecture` rows from scenes.csv into their new discrete CSVs (`cmd_migrate`).
- A parser in `common.py` that reads story-summary.md's four sections (Logline / Synopsis / Act-shape / Theme).
- New columns: `spine_event` (on architecture.csv, required), `architecture_scene` (on scenes.csv, optional), `theme_threads` (on scene-intent.csv, optional).
- `storyforge score --level N` extension that emits deterministic quality + registry checks for levels 3–6 (generalizing existing `hone.py` + `structural.py` logic).
- The orphan-registry check generalized across all structural levels, including the new themes registry.
- `working/scoring-overrides.csv` and the parser for it.
- `working/scoring-verdicts.csv` and its parser (the diff+verdict persistence file).
- `STORYFORGE_DRAFTING=1` env-var bypass and `project.cascade_mode` in storyforge.yaml.
- `storyforge score --drift` — read-only drift report combining deterministic coverage + timestamps + content-hash deltas.
- Derived markdown renderings: `reference/spine.md`, `reference/architecture.md` (siblings of the existing `scenes-review.md`).

**v1 does NOT include:**
- The `storyforge cascade` command as its own surface (ships as `score --drift` first; cascade as a top-level command lands in v2/v3).
- LLM-driven semantic boundary checks (the diff+verdict mechanism is designed but the v1 doesn't run the LLM calls — runs deterministic only).
- Bible-consistency pass (the most expensive feature; designed but deferred).
- `project.structure: custom` or any non-three-act bundled checks (deferred per author decision).
- Pre-commit hook integration of new quality gates (hook stays as-is; quality gates are opt-in).

Rough effort: ~800–1000 LOC of Python (up from the original ~600 because of the structural-anchor artifact split + the migration step), one template directory addition, two new modules, modest extensions to `cmd_score.py` and `schema.py`, plus tests. Maybe three weeks of focused work given the migration. No LLM cost story to explain at v1.

### Effort beyond v1

v2 adds: LLM-driven semantic comparison at the prose-tier and structural-tier boundaries; the diff+verdict mechanism running over LLM checks (coaching-level-driven actor); bible-consistency with caching; one round of acceptance-threshold tuning based on v1 usage.

v3 adds: the proper `storyforge cascade` command surface (after `score --drift` has been used long enough to inform the design); bundled checks for non-three-act structures if a real need emerges.

---

## Open questions remaining after review

1. **~~Where does the scoring-verdicts file live?~~** *Resolved: `working/scoring-verdicts.csv`. The verdicts are part of the process, not canonical reference material.*

2. **~~Theme axis: how deep does it go?~~** *Resolved: separate themes.csv registry + `theme_threads` column on scene-intent.csv (mirrors the mice_threads pattern). Themes stay distinct from motifs.*

3. **~~`project.structure: custom` semantics.~~** *Resolved: dropped for v1. Too much work for the value; non-three-act stories use the score-overrides mechanism. Bundled checks for other structures are follow-up work if needed.*

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
