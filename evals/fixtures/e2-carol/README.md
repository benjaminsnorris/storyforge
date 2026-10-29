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

37 one-sentence edits, each contradicting facts the text establishes, plus 8
benign edits that contradict nothing:

| Code | Cases |
|---|---|
| PHY | 6 |
| TRT | 6 |
| TIM | 5 |
| REL | 5 |
| KNO | 5 |
| PRM | 5 |
| WLD | 3 |
| VOI | 2 |
| benign | 8 |

Every `established` span quotes the text that sets up the fact, and the quote
is still in the book after the edit. Many come from the gold commitments,
hand-labelled blind for E3 (`commitment` gives the id in
`gold/christmas-carol/commitments.csv`); where a commitment's quote doesn't
carry the fact itself, the span quotes the sentence that does. The edits keep
Dickens's voice, except the two VOI cases, which break it on purpose. No edit
touches the book's deliberate tensions (T1–T8 in the gold README), so the
suite never asks a detector to flag something the author meant.

The benign edits are small rewordings ("edged" for "got", "this very
afternoon" for "this afternoon"). Any flag on one is a false positive, so a
detector that merely notices which scene changed can't pass.

## Scoring

- **Detection:** a new flag (not raised on the unedited control) that lands
  on the case's scenes *and* names the case's code. The gates use this
  code-matched recall; location alone is reported as `recall`.
- **Precision:** true flags over all distinct flags, counting control flags,
  wrong-code flags and flags on benign edits as false. With fewer than 5
  distinct flags the gate counts precision as 0, since a ratio over 2 flags
  says nothing.
- A scorer can tell where a flag lands and what code it carries, not what it
  is about. A detector that names the facts it compares (the plan's ledger
  checker) would let the scorer require that too.

## Baseline (Storyforge 1.73.0, `drift-check`)

The only check Storyforge runs after an edit is the timeline drift check, so
that is the baseline detector. It raised no flags at all: recall 0 of 37 on
every code, and none of the 8 benign edits flagged either.

An earlier recording (before the review fixes) did raise one flag, on
`belle-family-happy-without-scrooge`: `flashback_not_earlier`, from the
ledger's own error (run 1 left the Stave II flashbacks on day 1). It appeared
because re-reading the edited scene's cues happened to give the relation
"earlier" where the control's re-read didn't, which is noise in the cue read,
not a detection. Expect such flags from this detector from run to run.
