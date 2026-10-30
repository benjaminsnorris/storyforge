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
