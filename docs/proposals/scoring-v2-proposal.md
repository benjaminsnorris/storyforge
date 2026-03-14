# Scoring V2: Fast, Reliable, Self-Improving

## The Problem

The current scoring system is **slow** (12+ minutes for 6 scenes in grouped mode), **opaque** during execution (fixed in 0.23.3), and produces scores whose **reliability and actionability** haven't been validated. The rubrics are well-written but the LLM's interpretation of them varies between runs. There's no mechanism for the system to learn what "good" means *for this specific project*.

## Design Goals

1. **Fast**: Score a full manuscript (40-60 scenes) in under 15 minutes
2. **Reliable**: Same scene scores within ±1 point across runs
3. **Useful**: Scores produce specific, actionable revision guidance — not just numbers
4. **Self-improving**: The system gets better at scoring *this project* over time

## Current Architecture (for reference)

| Mode | Claude calls per scene | Model | ~Time per scene | Cost per scene |
|------|----------------------|-------|-----------------|----------------|
| Grouped | 4 (one per scoring group) | Sonnet | ~2 min | ~$0.12 |
| Quick | 1 (all 25 principles) | Sonnet | ~30s | ~$0.03 |
| Deep | 25 (one per principle) | Sonnet | ~8 min | ~$0.50 |

The grouped mode sends the full scene text 4 times (once per group). Deep mode sends it 25 times. Quick mode sends it once but asks too much in a single call.

---

## Proposal: Three Major Changes

### Change 1: Diagnostic-Based Scoring (the core shift)

**Instead of asking "Score this scene 1-10 on economy_and_clarity," ask 5 concrete yes/no questions.**

Current approach (vague, high-variance):
> "Score the principle 'economy_and_clarity' using deficit-first evaluation..."
> → LLM returns: 6

Proposed approach (concrete, low-variance):
> For each principle, define 3-5 **diagnostic markers** — observable, binary indicators:
>
> **economy_and_clarity diagnostics:**
> 1. Does the scene contain filler phrases ("the fact that," "it was clear that," "in order to")? (Y/N)
> 2. Are there passages where 20%+ of words could be cut without losing meaning? (Y/N)
> 3. Are emotional states labeled with adjectives rather than shown through action/sensation? (Y/N)
> 4. Does every paragraph advance the scene's purpose, or are there digressions? (Y/N)
> 5. Are there specific, concrete nouns and verbs, or mostly general/abstract language? (Y/N)
>
> → Diagnostics map to score bands:
> - 0-1 "yes" to deficit questions = 8-10 (strong/masterful)
> - 2 "yes" = 6-7 (developing-to-strong)
> - 3 "yes" = 4-5 (developing)
> - 4-5 "yes" = 1-3 (weak)
>
> → Each "yes" answer includes a **quoted passage** as evidence

**Why this is better:**

- Binary questions produce more consistent LLM responses than open-ended scoring (research: LLM-as-judge studies show 10-15% reliability improvement)
- Evidence is baked in — every deficit comes with a quote, not a vague assertion
- Diagnostics are **teachable** — authors learn what the system looks for
- Diagnostics are **tunable** — add/remove/reweight per principle based on what matters

**What needs to be built:**

- A `references/diagnostics.csv` file defining 3-5 diagnostic markers per principle (see Appendix A for draft)
- A new prompt template that asks diagnostics instead of open-ended scoring
- Scoring logic that aggregates diagnostic answers into scores

### Change 2: Two-Pass Architecture (Haiku screen → Sonnet deep dive)

**Pass 1: Haiku Diagnostic Screen (fast, cheap, all scenes)**

- Send each scene to Haiku once with ALL diagnostic markers for ALL scene-level principles
- Haiku answers each diagnostic Y/N with a brief quote
- ~25 principles × 4 diagnostics = ~100 binary questions per scene
- Haiku processes this fast: ~15-20 seconds per scene
- At 6 parallel workers: 40 scenes in ~2 minutes

**Pass 2: Sonnet Deep Evaluation (targeted, only where needed)**

- For scene-principle pairs where Haiku found 2+ deficits (score band 4-6 or below): send to Sonnet for the full deficit-first evaluation with chain-of-thought
- Sonnet confirms or adjusts the Haiku screen, adds nuanced rationale
- Typically 30-40% of scene-principle pairs need deep evaluation
- At 6 parallel workers: ~5-8 minutes for the targeted set

**Pass 3 (optional): Consistency Check**

- For scores that changed significantly between Haiku and Sonnet (±3 points): flag for author review
- Re-score 2-3 "control scenes" (author-scored reference scenes) to detect drift

**Cost and speed comparison:**

| Approach | Calls | ~Time (40 scenes) | ~Cost |
|----------|-------|--------------------|-------|
| Current grouped | 160 Sonnet | ~25 min | ~$4.80 |
| Current quick | 40 Sonnet | ~8 min | ~$1.20 |
| Proposed 2-pass | 40 Haiku + ~60 Sonnet | ~10 min | ~$2.00 |
| Proposed 2-pass (quick) | 40 Haiku only | ~2 min | ~$0.20 |

The two-pass architecture gives deep-mode quality at near-quick-mode speed.

### Change 3: Self-Improving Markers

The diagnostic markers shouldn't be static. The system should learn what matters for *this* project.

#### 3a: Exemplar-Anchored Scoring

We already collect exemplars (passages scoring 9+ on a principle). **Inject the project's own exemplars into scoring prompts:**

```
For this project, here is what excellence looks like for "economy_and_clarity":

> "She set the cup down. Rain. The window needed washing."
> — from "the-cartographer's-grief", scored 9 in cycle 2

Score relative to this project's demonstrated capability, not an abstract ideal.
```

This grounds scoring in the author's voice and quality ceiling, not generic literary references.

#### 3b: Author Calibration Loop

When the author provides their own scores (via the score skill's author scoring mode):

1. **Compute per-principle bias**: System scores economy_and_clarity 1.5 points higher than author on average
2. **Apply bias correction**: Subtract 1.5 from future system scores for that principle
3. **Track correction stability**: If bias stays consistent across 3+ cycles, it's a real calibration gap; if it drifts, flag for re-calibration

#### 3c: Diagnostic Marker Evolution

After each scoring cycle:

1. **Identify low-discrimination markers**: Diagnostics where the answer is the same for 90%+ of scenes are not useful (they don't differentiate quality). Flag these for replacement.
2. **Identify high-variance markers**: Diagnostics where Haiku and Sonnet disagree 40%+ of the time are ambiguous. Rewrite them for clarity.
3. **Author marker proposals**: When author scoring diverges from system scoring consistently on a principle, generate proposed new diagnostics targeting the specific quality gap. Present to author for approval.
4. **Validated patterns promote to defaults**: When a custom diagnostic marker improves scoring reliability across 3+ cycles (measured by author-system alignment), promote it to the default marker set.

#### 3d: Control Scene Calibration

Authors designate 2-3 scenes as **calibration controls** — scenes they've scored definitively. At the start of each scoring cycle:

1. Re-score control scenes
2. Compare to established scores
3. If delta > 1.5 on any principle, flag as drift and pause for recalibration
4. This catches model version changes, prompt drift, and rubric interpretation shift

---

## Building the Diagnostic Markers

This is the most important piece. Each principle needs 3-5 markers that are:

- **Observable**: Can be verified by quoting text
- **Binary**: Yes or no (with brief evidence)
- **Discriminating**: Different scenes will get different answers
- **Stable**: Same scene gets the same answer across runs

### Option A: Author-Guided Marker Workshop (recommended)

Interactive skill session where Claude and the author collaboratively define markers:

1. Claude proposes 5-7 candidate markers per principle based on the craft engine and rubrics
2. Author reviews, adjusts, adds markers that match their editorial instinct
3. Test markers against 3-5 scenes the author knows well
4. Refine until markers match author's mental model
5. Save to `references/diagnostics.csv`

**Pros**: Markers reflect the author's actual quality bar. High buy-in.
**Cons**: Takes 1-2 hours of author time. Requires author to articulate their standards.

### Option B: Auto-Generated from Rubrics + Exemplars

Autonomous script that generates markers:

1. For each principle, read the rubric's score band definitions
2. Extract the concrete indicators from each band (e.g., "filler phrases," "labeled emotions")
3. Frame each indicator as a binary diagnostic question
4. Validate against existing exemplars (high-scoring scenes should pass; low-scoring should fail)
5. Save to `references/diagnostics.csv`

**Pros**: Fast, no author time. Can run immediately.
**Cons**: May not match author's priorities. Needs author review before use.

### Option C: Hybrid (recommended starting point)

1. Auto-generate markers from rubrics (Option B) as a starting set
2. Run a calibration scoring cycle using the generated markers
3. Present results to author in a review session (Option A style)
4. Author tunes markers based on whether scores feel right
5. System learns from author feedback (Change 3)

---

## Diagnostics File Format

```csv
principle|marker_id|question|deficit_if|weight|evidence_required
economy_and_clarity|ec-1|Does the scene contain filler phrases ("the fact that," "it was clear that," "in order to")?|yes|1|quote the filler phrases found
economy_and_clarity|ec-2|Are there passages where 20%+ of words could be cut without losing meaning?|yes|2|quote one passage and show the tightened version
economy_and_clarity|ec-3|Are emotional states labeled with adjectives rather than shown through action/sensation?|yes|1|quote the labeled emotions
economy_and_clarity|ec-4|Does every paragraph advance the scene's purpose?|no|1|quote the digressive paragraph(s)
economy_and_clarity|ec-5|Does the scene use specific, concrete nouns and verbs over general/abstract language?|no|1|quote 2-3 examples of vague language
```

Fields:
- `principle`: Which principle this marker belongs to
- `marker_id`: Unique ID for the marker
- `question`: The binary diagnostic question
- `deficit_if`: The answer that indicates a deficit (`yes` or `no`)
- `weight`: How much this marker matters (1 = standard, 2 = double-weight for critical markers)
- `evidence_required`: What the evaluator must quote to support its answer

### Score Aggregation Formula

For each scene-principle pair:

```
deficit_score = sum(marker_weight for markers where answer == deficit_if)
max_score = sum(all marker_weights)
raw_ratio = deficit_score / max_score

# Map to 1-10 scale (inverted — fewer deficits = higher score)
score = round(10 - (raw_ratio * 9))

# Clamp to 1-10
score = max(1, min(10, score))
```

With 5 markers of weight 1 each:
- 0 deficits → 10
- 1 deficit → 8
- 2 deficits → 6
- 3 deficits → 5
- 4 deficits → 3
- 5 deficits → 1

Weighted markers shift the curve — a weight-2 marker finding a deficit drops the score more than a weight-1 marker.

---

## Implementation Plan

### Phase 1: Diagnostics Foundation (the biggest value)

1. Define `references/diagnostics.csv` format and schema
2. Auto-generate initial markers from existing rubrics (Option B/C)
3. Build new Haiku diagnostic prompt template (`scripts/prompts/scoring/diagnostics.md`)
4. Build diagnostic answer parser in `scripts/lib/scoring.sh`
5. Build score aggregation from diagnostics
6. Add `--diagnostics` mode to `storyforge-score` (alongside existing grouped/quick/deep)
7. Add marker workshop mode to score skill (Option A for author tuning)

### Phase 2: Two-Pass Architecture

1. Implement Pass 1 (Haiku diagnostic screen) as the default for `--diagnostics` mode
2. Implement Pass 2 (Sonnet deep dive) for flagged scene-principle pairs
3. Add `--haiku-only` flag for fast-and-cheap scoring (Pass 1 only)
4. Implement consistency check between passes
5. Update progress output for two-pass flow

### Phase 3: Self-Improving Loop

1. Wire exemplar injection into scoring prompts
2. Implement author bias correction (apply computed deltas as offsets)
3. Add control scene designation and calibration check
4. Build marker discrimination analysis (flag useless markers)
5. Build marker variance analysis (flag ambiguous markers)
6. Add marker evolution proposals to the improvement cycle

### Phase 4: Reporting & Integration

1. Update HTML report to show diagnostic details (not just scores)
2. Update dashboard visualization for diagnostic-based scores
3. Update review skill to use diagnostic evidence in revision planning
4. Update plan-revision skill to reference specific diagnostic failures

---

## Appendix A: Draft Diagnostic Markers (Scene Craft)

These are illustrative — the full set would cover all 25 scene-level principles.

### enter_late_leave_early

| ID | Question | Deficit if | Weight |
|----|----------|-----------|--------|
| elle-1 | Does the scene open with setup/preamble before the first moment of tension or action? | yes | 2 |
| elle-2 | Does the scene continue past its natural turning point into reflection or aftermath? | yes | 2 |
| elle-3 | Could the first paragraph be cut without losing essential information? | yes | 1 |
| elle-4 | Does the scene's final paragraph add meaning beyond the turn? | no | 1 |

### every_scene_must_turn

| ID | Question | Deficit if | Weight |
|----|----------|-----------|--------|
| esmt-1 | Can you state the scene's central question in one sentence? | no | 2 |
| esmt-2 | Does at least one value (relationship, knowledge, status, power) change between the scene's opening and closing state? | no | 2 |
| esmt-3 | Is the change earned by the scene's internal logic (not arriving from outside)? | no | 1 |
| esmt-4 | Would removing this scene create a gap in the narrative? | no | 1 |
| esmt-5 | Can you point to the exact moment where the scene turns? | no | 1 |

### scene_emotion_vs_character

| ID | Question | Deficit if | Weight |
|----|----------|-----------|--------|
| sevc-1 | Is there a gap between what the character feels and what the reader feels? (irony, suspense, dramatic tension) | no | 2 |
| sevc-2 | Does the scene create emotion through situation and subtext rather than telling the reader how to feel? | no | 2 |
| sevc-3 | Are emotional beats paced, or do they arrive in a single dump? | no | 1 |

### thread_management

| ID | Question | Deficit if | Weight |
|----|----------|-----------|--------|
| tm-1 | Does the scene advance or develop at least one ongoing story thread? | no | 2 |
| tm-2 | Are threads connected to their last appearance via sensory or emotional anchors? | no | 1 |
| tm-3 | Are there more than 3 threads competing for attention in this scene? | yes | 1 |
| tm-4 | Is any thread introduced and then dropped without development? | yes | 1 |

### economy_and_clarity

| ID | Question | Deficit if | Weight |
|----|----------|-----------|--------|
| ec-1 | Does the scene contain filler phrases ("the fact that," "it was clear that," "in order to," "began to")? | yes | 1 |
| ec-2 | Are there passages where 20%+ of words could be cut without losing meaning? | yes | 2 |
| ec-3 | Are emotional states labeled with adjectives rather than shown through action? | yes | 1 |
| ec-4 | Does every paragraph advance the scene's purpose? | no | 1 |
| ec-5 | Does the scene prefer specific, concrete language over general/abstract? | no | 1 |

---

## Appendix B: Haiku Diagnostic Prompt Structure (draft)

```markdown
You are a manuscript diagnostic scanner. For each diagnostic question below,
answer YES or NO, then quote the relevant passage as evidence. Be precise and
concise — this is a screening pass, not a full evaluation.

## Scene
**Title:** {{SCENE_TITLE}}
**POV:** {{SCENE_POV}}

{{SCENE_TEXT}}

## Diagnostics

Answer each question with:
- YES or NO
- A brief quote from the scene (1-3 sentences) as evidence
- If the answer indicates no deficit, write "CLEAN" instead of a quote

Format your response as:

DIAGNOSTICS:
marker_id|answer|evidence
elle-1|YES|"Sarah woke to the sound of rain. She showered, dressed, and drove to the office where..."
elle-2|NO|CLEAN
esmt-1|YES|"The scene's question: Will Sarah confront her mother about the letter?"
...
```

## Appendix C: Power Mean for Score Aggregation (optional enhancement)

Instead of arithmetic mean for combining principle scores into scene averages, use the **power mean** with p=0.5 (Holder mean). This penalizes low outlier scores more heavily:

```
power_mean = (sum(score_i^p) / n) ^ (1/p)
```

With p=0.5:
- Scores [8, 8, 8, 8, 2] → arithmetic mean: 6.8 → power mean: 5.8
- Scores [6, 6, 6, 6, 6] → arithmetic mean: 6.0 → power mean: 6.0
- Scores [10, 10, 10, 10, 2] → arithmetic mean: 8.4 → power mean: 7.0

This matches editorial intuition: one badly broken element damages a scene more than one excellent element elevates it. The author's weakest principles matter most.

---

## Open Questions for Author Input

1. **Which approach for building initial markers?** Option A (author workshop, 1-2 hours), Option B (auto-generated, fast), or Option C (hybrid)?

2. **Should we keep the existing scoring modes?** The diagnostic approach could replace grouped/quick/deep entirely, or coexist as a fourth mode (`--diagnostics`) during transition.

3. **How many diagnostic markers per principle?** 3-5 is the sweet spot per the research, but some principles (like prose craft) might warrant more. Should all principles have the same number?

4. **Author calibration priority**: How important is author scoring? If you plan to score your own scenes regularly, the bias correction loop becomes very powerful. If not, we should invest more in the auto-calibration mechanisms.

5. **Control scenes**: Are there 2-3 scenes you'd be willing to score definitively as calibration anchors?

6. **Power mean or arithmetic mean** for combining scores? Power mean is more editorial (penalizes worst scores harder), but arithmetic is simpler and more intuitive.

7. **Marker evolution frequency**: Should markers be reviewed every cycle, every 3 cycles, or only when the author requests it?
