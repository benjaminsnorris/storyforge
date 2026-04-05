# Roundtrip Test: Thornwall (59 scenes, epic fantasy)

## Test Date: 2026-04-04

## The Workflow

1. Baseline structural score: **0.57**
2. Reconcile values (57 → 12 thematic tensions): +0.04
3. Reconcile outcomes (31 elaborated → enum): minor
4. Reconcile characters (Kael/kael/Kael Davreth → kael): +0.04
5. Reconcile locations (54 variants → 11 canonical): +0.02
6. Final structural score: **0.64** (+0.07 overall, +12% improvement)
7. Redraft 3 scenes from CSV data using Opus
8. Compare originals vs redrafts

## Score Movement

| Dimension | Before | After | Delta |
|-----------|--------|-------|-------|
| Arc Completeness | 0.66 | 0.73 | +0.07 |
| Thematic Concentration | 0.00 | 0.31 | +0.31 |
| Pacing Shape | 0.39 | 0.38 | -0.01 |
| Character Presence | 0.74 | 0.85 | +0.12 |
| MICE Thread Health | 0.62 | 0.62 | 0.00 |
| Knowledge Chain | 0.91 | 0.91 | 0.00 |
| Scene Function Variety | 0.73 | 0.70 | -0.04 |
| Structural Completeness | 0.98 | 0.98 | 0.00 |
| **Overall** | **0.57** | **0.64** | **+0.07** |

Reconciliation alone (no manual edits) moved the score +12%. The biggest gains came from value consolidation (+0.31 thematic) and character normalization (+0.12 presence, +0.07 arcs). These were purely automated fixes — no author judgment required.

## Redraft Comparison

Three scenes redrafted from CSVs only (no original prose shown to the model):

### Scene 1: Road to Thornwall (seq 5, Sera, 2036→2256 words)

**Beat fidelity:** High. All major beats preserved — the punishing road, the mare, Sera's backstory, the shell of precision, the perception-opening, riding toward the Hold.

**What was lost:** The original's distinctive parenthetical voice rhythm. Specific character details (Desta changed from neighbor/friend to ex-partner — a factual invention). The original's economy and restraint.

**What improved:** The perception-opening is more physically realized. The field journal entry adds concrete methodology.

### Scene 2: Lone Rider (seq 30, Kael, 602→1233 words)

**Beat fidelity:** High, and the redraft actually added beats the original was missing. The Declaration of Conscience sequence (all five signing, Torren's "Is it true?") was in the brief but absent from the 602-word original.

**What was lost:** The original's extreme economy (42 lines, every sentence load-bearing). A brilliant institutional voice detail (Corvin's note about "separate processes"). The original's stage-direction-like restraint.

**What improved:** Brief-specified beats that the original hadn't implemented are now present. Character interiority for Kael adds depth.

### Scene 3: Fissure Closes (seq 49, Sera, 1932→2043 words)

**Beat fidelity:** High for the core sequence (crystal meeting, singing transformation, Torren's line, weeping, ascent). But the courtyard coda — Sera and Kael's conversation about Verath, the other Holds, "Come with me" / "I'll come" — is entirely missing.

**What was lost:** The entire emotional/thematic resolution of the scene. Bren's ground-feeling moment. Sera's letter to Corvin.

**What improved:** More concrete scientific notation breakdown during the healing. Better physical pacing of the crystal convergence.

## Findings

### What works

1. **Story beats carry through reliably.** The CSV model (goal/conflict/outcome/crisis/decision + key_actions/key_dialogue) captures enough to reproduce the essential plot of each scene.
2. **Key dialogue preservation is strong.** Verbatim lines from the brief appear in the redrafts.
3. **Motif tracking works.** Shell metaphors, institutional language patterns, and sensory details specified in the brief appear correctly.
4. **The redraft can ADD missing beats.** Lone-rider's Declaration sequence was in the brief but missing from the original — the pipeline correctly produced it.

### What doesn't work yet

1. **Voice compression.** The biggest issue. The original uses fragments, colons, parentheticals, and restraint as signature moves. Redrafts default to conventional prose rhythms. The voice guide exists but the drafting prompt doesn't enforce it strongly enough.

2. **Relationship/backstory invention.** Desta's relationship was rewritten from the data — the extraction or the redraft invented details not in the CSV. The pipeline needs guardrails against fabrication.

3. **Scene truncation.** Fissure-closes dropped its courtyard coda, which is the scene's emotional resolution. Key dialogue specified in the brief was omitted. The drafting prompt may hit token limits before completing.

4. **Economy vs expansion.** The originals trust readers more. The redrafts explain. Lone-rider went from 602 to 1233 words — doubling length by adding interiority that the original achieved through implication.

## Issues to File

1. **Drafting prompt needs voice enforcement** — the voice guide is read but not strictly followed. The prompt should include specific examples of the author's sentence-level patterns.
2. **Backstory guardrails** — the redraft should not invent character relationships or history not in the CSV data.
3. **Scene completion** — the redraft must hit ALL key_dialogue entries in the brief before stopping. Current behavior truncates.
4. **Economy control** — add a target_words signal to the drafting prompt and penalize expansion beyond it.
5. **Pacing score calibration** — the tension model is too coarse (all +/- no-and scenes score identically), making climax detection unreliable.
6. **Thematic concentration scoring threshold** — HHI normalization is too aggressive; 12 well-distributed values scores 0.31 when it should be 0.6+.

## Verdict

**The roundtrip is viable.** The extraction + reconciliation + structural scoring pipeline works: it takes a 59-scene novel, normalizes 57 fragmented values to 12 core themes, consolidates character variants, and produces a meaningful structural score that improves measurably with each fix.

**The redraft needs work.** The CSV model captures enough story information to reproduce scenes with correct beats, but the prose quality gap between original and redraft is significant — primarily in voice and economy. This is a prompt engineering problem, not an architecture problem. The data model is sound.

**The scoring needs calibration.** Thematic concentration and pacing scoring have threshold issues that undercount quality. These are quick fixes to the normalization constants.
