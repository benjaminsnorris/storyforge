# Extract phase 4 on *A Christmas Carol* at v1.98.0

Scoring of a forced `storyforge extract --phase 4` run (v1.98.0, F-127/F-128) on a
copy of storyforge-evals' `projects/christmas-carol`, against its hand-labelled gold
(`gold/christmas-carol/commitments.csv`, 80 facts). The method copies evals-9a's
v1.96.1 scoring (`gold/christmas-carol/phase4-results.csv`, `phase4-precision.csv`
in storyforge-evals). The scoring was done by a fresh-context agent and not reviewed
by Ben.

- `phase4-results-v1.98.0.csv`: one row per gold fact: `phase4` (yes/partial/no),
  the best row, whether it is from the fact's scene, and whether a migrated row has it.
- `phase4-precision-v1.98.0.csv`: every 7th phase-4 row: commitment / incidental /
  wrong, with the issue.

The summary and how to read it are in `docs/plans/2026-10-28-rethink-status.md`
(Next steps, "Carol re-score"). Not read by any eval suite.

## The persistence check (v1.106.x, `storyforge/persistence.py`)

A forced phase 4 on the E2 *Carol* book (40 scenes, 28,440 words, ledger migrated)
with the persistence check, $2.83 for phase 4 plus about $0.75 for the check. Scored
by a fresh-context agent against the same gold, by the method above (not by Ben).

- **v1 prompt** (`persistence-v1-*`): 476 facts proposed, 359 kept (12.6 per 1,000
  words, against 16.0 at v1.98.0), 117 dropped.
  - Kept sample (every 6th, n=59): **86% commitment**, 14% incidental, 0 wrong
    (v1.98.0: 58 / 42 / 0).
  - Drops: 93 incidental (right), 24 commitments (wrong), 17 of them gold facts.
  - Ledger recall: 72 of 80 yes, 77 with partial (v1.98.0: 78). Lost to drops: C51
    (the goose dinner) and C72 (the bed-curtains); C73 was never extracted.
  - The wrong drops were events that happened ("Bob carried Tim from church", the
    goose), objects and habits a later scene calls back (the comforter, the
    curtains, the corner at the Exchange), and what visions show.
- **v2 prompt** (shipped; `persistence-v2-dropped.csv`): events, what a vision shows,
  and possessions/habits/usual places named as lasting, with examples that aren't
  from *Carol*; "drop only what is clearly incidental". Re-judged on the same
  extracted facts ($0.76): 415 kept, 61 dropped. Of v1's 24 wrong drops, 18 are now
  kept (6 still dropped: C05's fog, C31's bell, C47's snow, C53, the moor's sunset,
  C72); of its 93 right drops, 47 are still dropped. 8 new drops, all near the
  incidental line. **Estimated** kept precision about 78% (not re-labelled: the
  labelled rows carried over plus the 8 new drops). C72 is the limit of a one-scene
  question: a detail only a later callback makes matter.
