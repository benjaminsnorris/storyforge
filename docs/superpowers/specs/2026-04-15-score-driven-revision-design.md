# Score-Driven Revision with Staleness Detection

## Problem

The revise pipeline treats evaluation findings (from `cmd_evaluate.py`) and scoring data (from `cmd_score.py`) with equal weight, but evaluations can become stale after significant manuscript changes. When multiple polish loops, brief rewrites, and redrafts have occurred since the last evaluation, the eval findings describe prose that no longer exists. This leads to revision plans anchored on outdated structural recommendations.

Additionally, when a revision plan contains multiple upstream passes (brief/intent fixes) targeting overlapping scenes, each pass redrafts its scenes immediately — wasting expensive Opus calls when a later pass will modify the same scene's CSV data and require yet another redraft.

## Goals

1. Detect when evaluation findings are stale relative to current manuscript state
2. Provide a purely score-driven revision mode (`--scores`) that works from diagnosis data alone
3. Adapt the interactive revise skill to downweight stale evaluations automatically
4. Defer scene redrafting until all upstream CSV fixes are complete

## Non-Goals

- Re-running evaluations automatically (that's the author's decision)
- Changing how scoring or diagnosis works
- Modifying the evaluation pipeline itself (beyond adding a word count snapshot)

## Design

### Component 1: Word Count Snapshots at Evaluation Time

**Where:** `cmd_evaluate.py`, at the end of a successful evaluation run.

**What:** Write `working/evaluations/eval-{date}/word-counts.csv` — a pipe-delimited file:

```
id|word_count
before|2847
seeing|3102
sleepless|2560
```

One row per scene, copied from the current `scenes.csv` `word_count` column. This is a snapshot of what the evaluation actually assessed.

**Cost:** Zero API calls, ~1ms. The file is tiny.

### Component 2: Staleness Detection Function

**Where:** New function `check_eval_staleness(project_dir)` in `scoring.py` (alongside existing diagnosis logic).

**Returns:**

```python
{
    'stale': bool,
    'reasons': list[str],
    'eval_dir': str | None,
    'eval_date': str | None,
    'word_delta_pct': float,
    'score_runs_since': int,
}
```

**Algorithm:**

1. **Find latest evaluation:** Scan `working/evaluations/` for `eval-*` directories, sort by date suffix, take the most recent. If none exists, return `stale=True` with reason `'no evaluation found'`.

2. **Count full scoring runs since eval:** Scan `working/scores/cycle-*` directories. A cycle counts as a "full LLM scoring run" if it contains files beyond what deterministic-only scoring produces (deterministic scoring only creates `scene-scores.csv` and `diagnosis.csv` from the 6 deterministic scorers; full LLM scoring also creates per-evaluator output files or a marker). Count cycles whose date (from directory name or file mtime) post-dates the evaluation. **Stale if >= 2 full scoring runs since eval.**

3. **Compute word delta:** Read the eval's `word-counts.csv` snapshot. For each scene, compute `abs(current_word_count - snapshot_word_count)`. Sum all deltas and divide by the sum of snapshot word counts to get a percentage. **Stale if >= 20% cumulative word delta.**

4. **Fallback for old evals without snapshots:** If `word-counts.csv` doesn't exist in the eval directory, fall back to `git diff --stat` on `scenes/` since the eval date. Parse insertions + deletions as a proxy for change magnitude. This is less precise (line-level, not word-level) but serviceable for legacy evals.

5. **Either signal triggers staleness.** Both signals are reported in `reasons` so the skill can explain why.

### Component 3: Score-Driven Revision Mode (`--scores`)

**Where:** New flag in `cmd_revise.py`, mutually exclusive with `--polish`, `--naturalness`, `--structural`.

**What it does:**

1. Read `working/scores/latest/diagnosis.csv`
2. Separate high/medium priority items by `root_cause`:
   - `root_cause: brief` — scenes needing upstream CSV fixes
   - `root_cause: craft` — scenes needing prose-level polish
3. For brief-root-cause items: cross-reference `worst_items` across all affected principles. Rank scenes by how many weak principles they appear in (chronic underperformers first).
4. Generate a revision plan:
   - One or more `fix_location: brief` passes targeting the worst scenes (grouped into manageable batches)
   - A `fix_location: craft` targeted polish pass for craft-root-cause items
5. Execute the plan using existing infrastructure (hone for brief fixes, revision prompts for craft)

**Relationship to other modes:**
- `--scores` generates a complete upstream + craft plan from scoring data
- `--polish --loop` does craft-only convergence (with some upstream detection built in)
- `--scores` followed by `--polish --loop` would be a full score-driven pipeline
- If `--scores` finds no upstream issues, it falls through to a targeted craft plan (similar to `--polish` but with principle-specific targeting from diagnosis)

### Component 4: Deferred Redrafting

**Where:** The pass execution logic in `cmd_revise.py`, specifically in `_execute_single_pass` and the callers that iterate over plan passes.

**Problem:** Currently, each upstream pass (brief/intent fix) calls `_redraft_scenes()` at the end. When passes 1, 2, and 3 all target overlapping scenes, scenes get redrafted multiple times — each redraft takes ~1 min with Opus and is wasted if a subsequent pass modifies the same scene's CSV data.

**Solution:** Before executing passes, look ahead in the plan:

1. Identify all passes with `fix_location` in `('brief', 'intent')` — these are upstream passes.
2. Collect the union of all scenes targeted across those passes.
3. Execute each upstream pass's CSV fixes (hone delegation) **without redrafting**.
4. After all upstream passes complete, redraft the deduplicated set of scenes that had any CSV field modified.
5. Commit once after the batch redraft.
6. Then proceed to craft passes as normal.

**Implementation approach:** The main pass execution loop already iterates over plan rows. Add a "deferred redraft" mode:
- Before the loop, partition plan rows into upstream passes and craft passes
- Execute upstream passes with redrafting suppressed (a flag or separate code path in the upstream delegation logic)
- Track which scenes had CSV changes across all upstream passes
- Batch redraft the union
- Then execute craft passes normally

**Edge case:** If there's only one upstream pass, this optimization still applies (no behavioral change — it just redrafts at the same time it would have before). The optimization is most impactful with 2+ upstream passes targeting overlapping scenes.

### Component 5: Revise Skill Adaptation

**Where:** `skills/revise/SKILL.md`

**New behavior in the "Read Project State" step:**

The skill calls `check_eval_staleness()` (via a Python one-liner or by reading the function's output). Based on the result:

**Fresh eval (not stale):**
- Current behavior unchanged. Eval findings are precise and actionable. Scores supplement.
- Options presented as today: full revision, upstream + polish, polish only, naturalness.

**Stale eval:**
- Skill displays a staleness notice: "The evaluation from {date} has been superseded by significant changes ({reasons}). Recommendations below are based on current scores. Evaluation findings are shown as historical context."
- Eval findings are presented in a clearly labeled "Historical Context" section — not hidden, but not used to generate specific scene targets or structural recommendations.
- Primary recommendation shifts to `--scores` mode.
- Option list:
  1. **Score-driven revision** (`--scores`) — upstream brief fixes + targeted craft polish based on current diagnosis. Recommended.
  2. **Polish loop** (`--polish --loop`) — craft-only convergence from current scores.
  3. **Re-evaluate first** — run a fresh evaluation before planning revision.
  4. **Use evaluation anyway** — treat stale eval findings as still actionable (author override).

**No eval:**
- Score-driven and polish modes only. No eval-based options presented.

## Distinguishing Full LLM Scoring from Deterministic-Only Cycles

The staleness check needs to count full LLM scoring runs, not deterministic iterations. The simplest reliable signal: a full LLM scoring cycle produces score files for non-deterministic principles (e.g., `prose_naturalness`, `dialogue_authenticity`). A deterministic-only cycle only contains scores for the 6 deterministic principles (`prose_repetition`, `avoid_passive`, `avoid_adverbs`, `no_weather_dreams`, `sentence_as_thought`, `economy_clarity`).

The staleness checker reads `scene-scores.csv` in each cycle directory and checks whether any non-deterministic principles are present. If so, it's a full run.

## Files Changed

| File | Change |
|------|--------|
| `scripts/lib/python/storyforge/cmd_evaluate.py` | Write word count snapshot at end of eval |
| `scripts/lib/python/storyforge/scoring.py` | Add `check_eval_staleness()` function |
| `scripts/lib/python/storyforge/cmd_revise.py` | Add `--scores` flag, plan generation from diagnosis, deferred redrafting logic |
| `skills/revise/SKILL.md` | Staleness-aware recommendation flow |
| `tests/test_revise_loop.py` | Tests for `--scores` flag |
| `tests/test_scoring.py` | Tests for `check_eval_staleness()` |

## Thresholds

| Signal | Threshold | Rationale |
|--------|-----------|-----------|
| Cumulative word delta | >= 20% of manuscript | At this level, 1 in 5 words has changed — the eval assessed meaningfully different prose |
| Full scoring runs since eval | >= 2 | Two full score cycles means the manuscript has been through at least one complete score-polish-rescore cycle |
