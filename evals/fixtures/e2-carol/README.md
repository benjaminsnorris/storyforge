# E2 fixtures: A Christmas Carol

Labelled errors for the detection benchmark (`evals/suites/e2_carol.py`, the
`e2` module explains the format and the scoring).

## `book/`

The project from the first Phase 0 extraction of *A Christmas Carol* (public
domain), copied from the storyforge-evals repo at `d5d51b5`
(`projects/christmas-carol/`). It holds:

- `scenes/`: the 40 scenes, split by `scenes-setup` on Storyforge `7a7a966`;
- `reference/`: the CSVs extracted from the clean text (the ledger);
- `working/timeline-cues.csv`: the time cues from the timeline pass.

This is evaluation data, with the extraction's own errors left in (run 1 puts
every Christmas Day scene on day 1; see `gold/christmas-carol/README.md` in the
evals repo). Don't fix it by hand: a control run of the unedited scene is
how the suite separates that noise from a detection.

## `injections.json`

36 one-sentence edits, each contradicting facts the text establishes:

| Code | Cases |
|---|---|
| PHY | 6 |
| TRT | 6 |
| TIM | 5 |
| REL | 5 |
| KNO | 5 |
| PRM | 5 |
| WLD | 2 |
| VOI | 2 |

Every `established` span quotes the scene that sets up the fact. Most come
from the gold commitments, hand-labelled blind for E3 (`commitment` gives the
id in `gold/christmas-carol/commitments.csv`). The edits keep Dickens's voice,
except the two VOI cases, which break it on purpose. No edit touches the
book's deliberate tensions (T1–T8 in the gold README), so the suite never asks
a detector to flag something the author meant.

## Baseline (Storyforge 1.71.1, `drift-check`)

The only check Storyforge runs after an edit is the timeline drift check, so
that is the baseline detector. Scored, it reaches recall 0.06 (2 of 36) and
precision 1.0, but **neither hit is a real detection**:

- Both hits are the same flag on `belle-family-happy-without-scrooge`:
  `flashback_not_earlier`, "its day (1) is not before the previous scene's (1)".
  The two cases are `e2-carol-002` ("dead these three years") and
  `e2-carol-018` ("his brother").
- The flag comes from the ledger's own error: run 1 left the Stave II
  flashbacks on day 1.
- It appears only because re-reading the edited scene's cues happened to give
  the relation "earlier", and the control's re-read didn't. The edit itself
  plays no part.

So the true baseline is 0 of 36. The scorer can tell where a flag lands, but
not what it is about. Read any hit by the drift check with that in mind.
Judging what a flag is about needs a detector that names the facts it
compares, which is what the plan's ledger checker would do.
