# Source

Copied from benjaminsnorris/storyforge-evals at `40fb1bd` on 2026-10-28:

- `run1/reference/` ← `projects/christmas-carol/reference/` (extraction run 1)
- `run2/reference/` ← `runs/christmas-carol/run2/reference/` (extraction run 2)
- `flags.csv` ← `gold/christmas-carol/e7-flags.csv` (68 flags; `ben_verdict` is the author's verdict).
  Since F-122, validate gives one timeline-order flag per run of scenes set
  before the present, so run2's two six-scene runs (groups B and C) are one
  row each, with the same verdict: 58 rows

The verdict meanings are in that repo's `gold/christmas-carol/README.md`: `real`
(the text is inconsistent), `deliberate` (a device, e.g. the Ghost of Christmas
Past's flashbacks), `extraction-error` (the book is fine; the flag catches a
mistake in the extracted data), `false-positive` (the check is wrong).
A Christmas Carol (1843) is public domain.
