# `storyforge status` — deterministic next-step verdict + forge/elaborate routing

**Issue:** #267 — forge/elaborate don't surface story-power scorecard or
prose-tier scoring (logline/synopsis/act-shape).

**Date:** 2026-07-15

## Problem

The story-power scorecard (`score --story-power`), prose-tier floor checks
(`score --level 0/1/2`), and `score --compare` all exist and work, and
`story-summary.md` is structured logline → synopsis → act-shape → theme.
But the two skills that drive new-project development don't route to any of
it:

- `elaborate` starts the pipeline at **spine** — no prose-tier stage; "Validate
  and Report" (Step 5) mentions only `validate`/`--structural`.
- `forge` references `--level N` only for structural tiers 3–5 and
  `propose-summaries`; no `--story-power`, no prose-tier levels 0/1/2, no
  `--compare`.

**Impact.** An author (or agent) following the documented flow builds the
spine without ever scoring/solidifying the pitch tier — the exact loop the
scorecard was built for. This was reported from a real session where the
assistant concluded, from `forge`/`elaborate` alone, that no logline/summary
scoring tool existed.

The root cause is that project state and tool-routing live only as **prose**
in SKILL.md, which agents can misread. The deterministic checks that *could*
answer "where am I / what's next" already exist (`score --drift` composes
them) but stop at printing pass/fail tables — they never synthesize a single
routable verdict.

## Goal

Add a deterministic, no-LLM, read-only command — `storyforge status` — that
synthesizes the existing checks into **one verdict**: current position on the
elaboration ladder, what's incomplete or mismatched at that rung, and the
single recommended next action. Wire `forge` and `elaborate` to invoke it and
route on it, and close the specific prose-routing gaps #267 names.

Non-goals: no new *checks* (status only synthesizes existing ones), no LLM
calls, no writes to project state.

## The ladder model

`status` walks the elaboration ladder in order and finds the **first
incomplete rung** — that rung is the project's current position.

```
L0 logline → L1 synopsis → L2 act-shape          (pitch / prose tier)
L3 spine → L4 architecture → L5 scene-map → L6 briefs   (structural tier)
→ draft → evaluate/polish                        (from scene status)
```

Each rung's state is exactly one of:

- `solid` — the artifact exists and its floor check passes (no non-accepted
  failures)
- `thin` — the artifact exists but a floor check fails
- `not_started` — the underlying artifact does not exist yet

Rung state is derived **only** from the floor check (`scoring_levels`). This
is deliberate: coverage checks look *downstream* (act-shape→spine,
spine→architecture, architecture→scenes), so folding them into a rung's own
solidity would wrongly keep act-shape `thin` until the spine exists. Coverage
and consistency mismatches are surfaced separately as **blockers** (see The
verdict), counted only for rungs that are present.

Inputs:

- floor (rung state): `scoring_levels.score_all_levels` (L0–L6)
- registry consistency (blockers): `scoring_consistency.score_consistency_all_levels` (L3–L6)
- cross-tier coverage/mismatch (blockers): `scoring_coverage.score_coverage_all_levels` (L2–L4)

Draft and evaluate/polish state come from the scene `status` column in
`reference/scenes.csv` (e.g. all scenes `drafted` → past the draft rung).

## The verdict

From the ladder walk, `status` computes:

- **phase** — the current rung (first incomplete), cross-checked against
  `storyforge.yaml:phase`. A mismatch between the walked position and the
  declared phase is itself a reported finding (e.g. "phase says
  `architecture` but spine L3 is thin").
- **next** — the recommended step for the current rung, as a structured
  object `{stage, action, command, reason}`. `stage` is a **stable enum**
  (`logline|synopsis|act-shape|spine|architecture|scene-map|briefs|
  story-power|draft|evaluate`) that forge routes on — robust against prose
  drift, which is the core of #267. Note `story-power` only ever appears as a
  `then.stage` (it is a recommended follow-up during the prose tier, never a
  ladder rung), so `next.stage` never takes that value. `action` is the human
  phrasing; `command` is always a concrete shell command — for prose-tier
  rungs it is the deterministic floor check (`storyforge score --level N`)
  while the section itself is developed via the elaborate skill. Static
  mapping from rung → step:
  - L0/L1/L2 thin → `elaborate --stage <prose stage>` (then a
    `score --story-power` read; `--compare` when exploring candidates)
  - L3–L6 thin → `elaborate --stage <spine|architecture|scene-map|briefs>`
  - L6 solid, no draft → `write`
  - draft complete → `evaluate` / `revise --polish`
- **then** — the following rung's action, for lookahead.
- **blockers** — mismatches (coverage/consistency failures, phase/yaml
  disagreement) that should be resolved before advancing.

The deterministic verdict *recommends* the LLM tools (`score --story-power`,
`--compare`, `--boundary`) as next **actions** where the rung calls for them,
but never runs them — so `status` stays instant and cost-free.

## Output contract

Two modes:

**Human default** — a compact tree:

```
PHASE: architecture  (matches storyforge.yaml)
LADDER:
  L0 logline    ✓ solid
  L1 synopsis   ✓ solid
  L2 act-shape  ✓ solid
  L3 spine      ✓ solid
  L4 architect. ✗ thin — 2 rows missing summary
  L5 scene-map  — not started
  L6 briefs     — not started
NEXT:  elaborate --stage architecture
THEN:  score --story-power
BLOCKERS: none
```

**`--json`** — the structured verdict forge parses and routes on (no fragile
prose-scraping):

```json
{
  "phase": "architecture",
  "phase_matches_yaml": true,
  "ladder": [
    {"level": 0, "name": "logline", "state": "solid", "detail": ""},
    {"level": 4, "name": "architecture", "state": "thin",
     "detail": "2 rows missing summary"}
  ],
  "next": {"stage": "architecture", "action": "Develop the architecture",
           "command": "storyforge elaborate --stage architecture", "reason": "..."},
  "then": {"stage": "scene-map", "action": "Develop the scene map",
           "command": "storyforge elaborate --stage map", "reason": "..."},
  "blockers": [{"source": "coverage", "level": 4,
                "detail": "2 architecture rows have no scene"}]
}
```

`status` is **coaching-neutral** — pure data plus a recommended command
string. The `forge` skill adapts phrasing and posture per coaching level
(full/coach/strict); the command does not. This keeps the command simple and
keeps posture where it already lives.

`status` is medium-aware: floor scorers already take `medium`; the ladder and
recommended actions are the same shape for novel and graphic-novel, with
medium threaded through to the underlying scorers.

## Components & files

- **`scripts/lib/python/storyforge/status.py`** (new domain module) — pure
  compose/verdict logic: `build_status(project_dir, medium) -> dict` returning
  the verdict dict above. No I/O beyond reading project files via existing
  helpers. This is the unit-tested surface.
- **`scripts/lib/python/storyforge/cmd_status.py`** (new command module) —
  thin `parse_args`/`main`; flags `--json`, `--dry-run`; renders the human
  tree or dumps JSON. Follows the standard command-module pattern.
- **`scripts/lib/python/storyforge/__main__.py`** — add `status` dispatch
  entry.
- **`skills/forge/SKILL.md`** — guided and directed modes call
  `storyforge status --json` first and route on it; add the missing prose-tier
  rung, `--story-power`, and `--compare` to the routing.
- **`skills/elaborate/SKILL.md`** — add the explicit pre-spine prose-tier
  stage (logline → synopsis → act-shape, each gated by a `--level` floor + a
  `--story-power` read, `--compare` for candidate exploration); add
  `--story-power` to Step 5 (Validate and Report).
- **CLAUDE.md** — add `storyforge status` to the command table.
- **Memory** — note the new command and its routing role.

## Testing

`status.py` is pure over fixtures, so `tests/commands/test_status.py` covers:

- empty project → PHASE=pitch, NEXT=logline
- each rung thin / missing / mismatched → correct `next` + populated `blockers`
- phase/yaml mismatch → reported as `phase_matches_yaml: false` + a blocker
- L6 solid, no drafted scenes → NEXT=write; all scenes drafted → NEXT=evaluate
- `--json` output validates against the documented schema (stable keys)
- graphic-novel medium parity: same ladder shape, medium threaded through

Version bump in `.claude-plugin/plugin.json` (minor — new feature).

## Dependencies

None. All underlying scorers and project-state helpers already exist. This is
a synthesis + wiring change.
