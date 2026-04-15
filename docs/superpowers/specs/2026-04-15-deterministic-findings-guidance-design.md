# Deterministic Findings in Revision Guidance

## Problem

The 6 deterministic scorers (prose_repetition, avoid_passive, avoid_adverbs, no_weather_dreams, sentence_as_thought, economy_clarity) compute detailed per-scene findings internally — specific phrases, cluster locations, hit lists — but discard them after computing a 1-5 score number. When `--scores` generates a revision plan, it only has diagnosis-level data (principle averages, worst scenes, root cause) and produces generic guidance like "fix abstract or verbose brief fields."

This means revision passes miss actionable detail. A repetition score of 2 doesn't tell hone that "chin on her paws" appears 16 times across the manuscript and should be reduced to 2-3 occurrences. A passive score of 3 doesn't tell the revision prompt that paragraph 3 has a cluster of 5 consecutive passive sentences.

## Goals

1. Persist deterministic scorer findings to CSV files during scoring
2. Feed those findings into `--scores` revision plan guidance as two layers: manuscript-wide patterns + per-scene specifics
3. Produce frequency-aware guidance (reduce, don't eliminate) rather than binary ban/allow

## Non-Goals

- Changing how scores are computed (scores stay the same, findings are a side output)
- Adding new deterministic scorers
- Persisting LLM scorer findings (those come from the API and are already saved as rationales)

## Design

### Findings File Format

Two files per scoring cycle in `working/scores/cycle-N/`:

**`repetition-findings.csv`** — manuscript-wide cross-scene phrase repetition:

```
phrase|category|severity|count|scene_ids
the edge of the|signature_phrase|high|21|claires-cold;advocate;missing-persons;two-hours;keisha-argument...
chin on her paws|signature_phrase|high|16|the-school;engineer;eleven-days;fire-ostrowski;rest-stop...
rook lifted her head|character_tell|high|14|dark-road;bench;rest-stop;collision;call...
```

Categories (from existing `repetition.py`): `simile`, `character_tell`, `blocking_tic`, `structural`, `sensory`, `signature_phrase`. Severity: `high` (4+ scenes) or `medium` (2-3 scenes).

**`scene-findings.csv`** — per-scene findings from the other 5 deterministic scorers:

```
scene_id|principle|finding|detail
waking-hank|avoid_passive|cluster|5 passive sentences in paragraph 3 (22% density)
waking-hank|avoid_adverbs|dialogue_tag|"said quietly", "whispered softly"
waking-hank|economy_clarity|filler_phrase|"the fact that", "it was clear that" (4.2/1000 words)
waking-hank|sentence_as_thought|monotone_run|7 consecutive sentences within ±3 words (stddev 3.2)
dark-room|no_weather_dreams|weather_opening|rain, wind in opening 80 words
```

The `finding` column is a short category label. The `detail` column is a human-readable string with the specific evidence.

### What Each Scorer Persists

**Repetition** (`repetition.py`): Already produces the findings list from `scan_manuscript()`. Write each finding as a row in `repetition-findings.csv`. No new analysis needed — just persist what `scan_scenes()` already returns.

**Passive voice** (`scoring_passive.py`): Currently calls `detect_passive_voice()` from `prose_analysis.py` which returns `list[dict{'match', 'position'}]`. Write one row per scene with: passive count, total sentences, density percentage, whether a cluster was detected (3+ consecutive passive sentences).

**Adverbs** (`scoring_adverbs.py`): Currently calls `detect_adverbs()` which returns `list[dict{'match', 'category', 'position'}]`. Write one row per scene per category (dialogue_tag, weak_verb, redundant) with the specific matches.

**Weather/dreams** (`scoring_weather.py`): Currently checks opening 80 words for weather, dream, and waking patterns. Write one row per scene that has a finding, with the specific pattern type and matched words.

**Rhythm** (`scoring_rhythm.py`): Currently computes stddev, monotone runs, short/long ratios. Write one row per scene with these statistics — only for scenes that triggered a marker (scored below 5).

**Economy** (`scoring_economy.py`): Composite scorer calling 4 detection functions. Write one row per scene per sub-signal that fired, with the specific matches and rate per 1000 words.

### Guidance Generation in `_generate_scores_plan`

When building a revision plan, the plan generator reads findings from the latest scoring cycle and constructs guidance in two layers:

**Layer 1: Manuscript-wide preamble** (from `repetition-findings.csv`)

Included in the `guidance` field of every upstream pass:

```
Cross-scene repetition patterns (reduce frequency, do not eliminate):
  - "the edge of the" (21x, signature phrase) — reduce to 3-4 occurrences
  - "chin on her paws" (16x, character tell) — reduce to 2-3 occurrences
  - "rook lifted her head" (14x, character tell) — reduce to 2-3 occurrences
  ...top 10 phrases
```

Target occurrence counts are derived from the original count: roughly count/5, minimum 2. This is frequency-aware — it tells the revision pass to reduce, not eliminate.

**Layer 2: Per-scene specifics** (from `scene-findings.csv`)

For each scene that appears in the plan's `targets` AND has findings, append scene-specific guidance:

```
Scene-specific findings:
  keisha-argument: passive cluster in para 3, filler phrases (4.2/1000), monotone run (7 sentences)
  waking-hank: passive cluster (22% density), adverb tics ("said quietly", "whispered softly")
```

Only included for scenes that the diagnosis flagged in `worst_items` — not every scene in the plan. Limited to top 5 findings per scene to keep guidance proportional.

For **brief-fix passes**: the per-scene guidance tells hone what to avoid when rewriting `key_actions` and other fields (e.g., "don't use 'chin on her paws' — vary Rook's physical vocabulary").

For **craft passes**: the guidance tells the revision prompt exactly what to fix in the prose (e.g., "break up the passive cluster in paragraph 3").

### Integration Points

1. **`cmd_score.py`**: After each deterministic scorer runs, write findings to the cycle directory. The `_score_repetition` function already calls `scan_manuscript()` — it just needs to persist the return value. The other `_score_*` functions call individual analysis functions — they need to collect the detail before computing the score.

2. **`cmd_revise.py`**: `_generate_scores_plan` gains a new step: `_load_findings(cycle_dir)` that reads both findings files and returns a structured dict. This dict is then passed to a new `_build_findings_guidance(findings, target_scenes)` function that produces the two-layer guidance string.

3. **The polish loop** (`_run_polish_loop`): Already calls `_generate_targeted_polish_plan` which produces guidance from diagnosis data. This should also inject findings-based guidance when available.

## Files Changed

| File | Change |
|------|--------|
| `scripts/lib/python/storyforge/cmd_score.py` | Persist findings in `_score_repetition`, `_score_passive`, `_score_adverbs`, `_score_weather`, `_score_rhythm`, `_score_economy` |
| `scripts/lib/python/storyforge/repetition.py` | Add `write_findings_csv(findings, output_path)` |
| `scripts/lib/python/storyforge/scoring_passive.py` | Return detail alongside score, or write directly |
| `scripts/lib/python/storyforge/scoring_adverbs.py` | Same |
| `scripts/lib/python/storyforge/scoring_weather.py` | Same |
| `scripts/lib/python/storyforge/scoring_rhythm.py` | Same |
| `scripts/lib/python/storyforge/scoring_economy.py` | Same |
| `scripts/lib/python/storyforge/cmd_revise.py` | Add `_load_findings`, `_build_findings_guidance`, wire into `_generate_scores_plan` and `_generate_targeted_polish_plan` |
| `tests/test_findings_persistence.py` | Tests for findings file writing |
| `tests/test_findings_guidance.py` | Tests for guidance generation from findings |
