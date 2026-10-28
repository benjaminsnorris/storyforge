# A timeline pass: one calendar for the whole book

Status: design; the author answered the open questions on 2026-10-28
(see "Author's decisions"). Finding F-035 in
`benjaminsnorris/storyforge-evals`. Nothing implemented.

## Problem

`timeline_day` has to place every scene on one calendar, but no step builds
that calendar.

- **Extraction guesses it per scene.** Phase 1 asks each scene, in
  parallel and blind to every other scene, for an absolute day. On *The
  Great Gatsby* the shooting landed on day 73, Gatsby's father arrived on
  day 3 and the funeral on day 68; an earlier extraction was just as wrong
  (shooting day 22, funeral day 19). The flashback gauge reads those as
  seven flashbacks covering 54% of the book, so the gauge says nothing.
- **`storyforge timeline` exists but can't do the job.** It has the right
  shape (cues per scene, then assignment across scenes) but:
  - a scene's only relation to the one before is a gap forward
    (`same_moment` … `weeks_later`), so a flashback can't be expressed, and
    `weeks_later` loses the difference between two weeks and five years;
  - assignment accepts only positive days, though day ≤ 0 is how a scene
    before the story is recorded (F-021);
  - assignment is one call that lists every scene, which grows with the
    book (the F-026 pattern);
  - extraction never calls it, and `enrich` runs it only as an optional
    last step.
- **`cleanup_timeline`** fills an empty day by interpolating its neighbours,
  which is right only when the scene isn't a flashback.

## Design

Time is decided in two steps: what each scene says about time (per scene,
parallel), then where each scene sits on one calendar (in order, by
batches). Code holds the calendar; the model supplies judgment.

### 1. Time cues per scene

Each scene yields cues, not a day. In extraction they replace phase 1's
`TIMELINE_DAY` field (no extra calls). Phase 1 also gets the last ~300 words
of the previous scene in reading order, so "the next morning" has something
to refer to.

```
TIME_RELATION: continues | later | earlier | frame | unclear
TIME_GAP:      the stated or implied gap from the previous scene, in words
               ("an hour", "the next morning", "three weeks", "five years")
TIME_ANCHOR:   a calendar fact the text gives (a date, weekday, season,
               holiday, "the hottest day of the summer"), quoted, or none
TIME_SPAN:     how long the scene's action covers when it is a summary
               ("all that summer"), else empty
```

- `earlier` is a flashback or recollection told as a scene (Gatsby and
  Daisy in Louisville in 1917). `frame` is narration from after the story
  ("I'm inclined to reserve all judgments", Nick two years on).
- Cues are stored in `working/timeline-cues.csv` (one row per scene) so the
  assignment can be re-run without re-reading the prose.
- For a project without prose (elaborated, not yet drafted), cues come from
  the scene's summary and function instead, through the same prompt.

### 2. Calendar assignment, in order, in batches

Code walks the scenes in reading order with a running **present day**:

- `continues` and `later` with a parseable gap (`the next morning` → +1,
  `three weeks` → +21) advance the present deterministically.
- `earlier` places the scene before the present by its gap, without
  moving the present.

The model handles what code can't: vague gaps ("some time later"),
anchors that pin or contradict the running count ("Sunday" two scenes
after a "Sunday"), and scenes marked `unclear`. It sees batches of ~40
scenes, with each scene's cues and one-line summary, plus the running
present day and the anchors established so far. It answers one line per
scene:

```
scene_id | day | basis
```

`basis` is a few words ("next morning", "anchor: July 4", "1917, five years
before"). Code applies each batch before the next and carries the present
forward, so output is bounded by the batch size and never by the book.
Every call checks for truncation, as hone does.

Days stay integers with day 1 the first day of the main story, ≤ 0 before
it (F-021). Gaps in years are approximate (365 days a year); the gauge
needs order and rough depth, not exact dates.

### 3. Checks (deterministic, reported, never blocking)

- The present goes backwards on a scene not marked `earlier` or `frame`.
- Two anchors contradict each other (two Sundays 3 days apart, a July 4
  after a "late August").
- A stated gap disagrees with the assigned days by more than a margin.

### 4. Where it runs

- **Extract:** after phase 1, before the phase 1 hone. Phase 1 writes cues;
  the pass writes `timeline_day`.
- **`storyforge timeline`** becomes this pass (cues from prose when it
  exists, else from summaries), replacing the forward-only deltas and the
  positive-only parser.
- **`cleanup_timeline`** no longer interpolates across a flashback: it
  fills an empty day only between two present-track neighbours.
- **Authored days are never overwritten silently.** In a project whose days
  were set in elaboration, the pass writes its proposal to
  `working/timeline-proposed.csv` and reports the differences; extraction
  (where nobody authored the days) writes them.

## Author's decisions

The author named three frustrations, seen in every project: extraction
gets the timeline wrong, the timeline drifts while drafting and revising,
and flashbacks and time jumps are hard to record. The design covers all
three.

### 1. `time_mode` column for frame and summary scenes

`scenes.csv` gains `time_mode`: `scene` (default; the action happens on
its day), `summary` (a passage covering a stretch: "all that summer";
`timeline_day` is where the stretch starts, `duration` its length), or
`frame` (narration from after the story, like Nick two years on). A frame
scene keeps the day it is narrated from; the flashback gauge ignores frame
scenes when deciding the present, so they never turn the book into one
long flashback.

### 2. Optional `timeline_date`, in EDTF, and never invented

`scenes.csv` gains an optional `timeline_date` holding only what the
scene's own text pins down, in the Extended Date/Time Format (EDTF, the
Library of Congress format whose features ISO 8601-2 describes):

| the text says | `timeline_date` |
|---|---|
| "the Fourth of July" (no year in the scene) | `XXXX-07-04` |
| "in the summer of 1922" | `1922-22` (EDTF season code: summer) |
| "in 1917" | `1917` |
| "around 1917" | `1917~` (approximate) |
| "it might have been October" | `XXXX-10?` (uncertain) |
| a summary "from June to September 1922" | `1922-06/1922-09` |
| "five years before" / nothing | empty: a relative gap is a cue, not a date |

Rules:

- **Unknown digits are `X`, never filled in.** A year stated once in
  Chapter I is not copied onto a later scene's `XXXX-07-04`; a report may
  show the inferred year, labelled as inferred, but the column never stores
  it.
- A weekday isn't a date: "Sunday" stays a cue (`TIME_ANCHOR`) used to
  place the scene and to check anchors against each other.
- Validation accepts the EDTF subset above (Level 2 unspecified digits,
  seasons 21-24, `?` `~` `%` qualifiers, intervals) and rejects anything
  else, so a sentence or a guessed date in natural language never gets in.
- Dates also feed the checks: two scenes whose dates and days disagree
  (`XXXX-07-04` on day 30 and `XXXX-07-06` on day 31) are reported.

### 3. Drift while drafting and revising is in scope

The checks in §3 run on drafted and revised prose, not just at
extraction:

- After `write` or `revise` changes a scene, its time cues are read again
  from the new prose (one cheap call per changed scene) and compared with
  its assigned day, its `time_mode`, its date and its neighbours ("the next
  morning" on a scene the calendar puts a week later; a scene that now
  reads as a flashback but isn't marked `earlier`). Mismatches are
  reported in the run's review; prose and CSVs are never rewritten to make
  them agree, since either may be the one that's wrong.
- `storyforge timeline --check` runs the same comparison on demand, for
  the whole book or `--scenes`, without assigning anything.
- In elaboration, the scene map asks for `time_mode` and for each
  scene's relation and gap in its summary ("the next morning", "flashback
  to 1917"), so a planned flashback is recorded as one (day ≤ 0) rather
  than looking like an error. The summary is where the timeline pass reads
  cues for a scene not yet drafted, and the drafting brief carries it into
  the prose; no separate cue columns are added to the CSVs.

## Verification

- Tests: cue parsing (each relation, gap phrases → days, anchors), the
  running-present walk (later, earlier, frame, unclear), batch application
  order with the present carried across batches, truncation leaving a batch
  unassigned, each check, and authored days going to a proposal file
  rather than being overwritten.
- *Gatsby* gold chronology: hand-place all 40 scenes from the text (summer
  1922; the 1917 Louisville flashback in Chapter VIII; the Dan Cody past in
  Chapter VI; Nick's frame) in `gold/gatsby/timeline.csv` with the line
  that justifies each day, then measure agreement. The flashback gauge
  should then name Chapter VIII's Louisville passage and Chapter VI's Cody
  backstory, and nothing spurious.
- A second book with a different time shape (*Middlemarch*'s parallel
  plots, or a novel told in retrospect), and a read-only proposal on one of
  the author's projects.
