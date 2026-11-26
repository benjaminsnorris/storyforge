# The build issues and their order

The 18 issues from the [checker review](README.md), with what can run in parallel.

**Up to six can start at once**, one per lane below. Inside a lane the issues share files, so they go one after another. The lanes are my reading of which files each issue touches; none has been built yet.

## Lanes

| Lane | Issues, in order | Files they share |
|---|---|---|
| A. Typed state | #732 → #733 → #748 | `continuity.py`, `typed_state.py`, `tests/test_continuity.py` |
| B. Fix loop | #734 → #735 → #736 → #737 | `gate.py`, `extract.py` |
| C. Question checker | #739 + #740 + #746, as one PR or back to back | `questions.py`, `ledger.py` |
| D. Open checker | #741 → #738 → #749 | `checker.py`, `cassette.py`, then `gate.py` |
| E. Source | #742 → #747, and #745 | `gate_source.py`, `prompts_source.py`, `source.py` |
| F. Evals | #744 | `evals/` only |

Two issues cross lanes:

- **#738 (tandem)** touches `gate.py` and the question layer. Start it after #741, and after lanes B and C have merged.
- **#743 (extraction thinking)** waits for #736. The Haiku test is back (report G): keep Sonnet.

Every PR bumps the version in `.claude-plugin/plugin.json`, so parallel branches will each need a rebase of that one line before merging.

## Waves

**Wave 1: six in parallel, no spend to build**

| Issue | What | Spend to verify |
|---|---|---|
| #732 | Possession: scope a bare item to its holder | none |
| #734 | Extraction guards (the session halt) | none |
| #739, #740, #746 | Question order, promise questions, namesake guard | one `gate-set-questions` top-up |
| #741 | Open checker caching | none if the cassette key is normalised |
| #742 | Source check: same-scene findings, never drop a fact, errata | under $1 |
| #744 | Typed-state eval suite | none |

#744 is worth starting first: it measures #732 and #733 before and after.

**Wave 2: as each lane frees up**

| Issue | What | After | Spend to verify |
|---|---|---|---|
| #733 | Injury decay; dead-character check by id | #732 | about $1 |
| #735 | Hold-back bug | #734 | none |
| #736 | Carry facts across fix rounds | #735 | none |
| #737 | "Never worse" on edited text only | #736 | none |
| #745 | Deaths by code | #733 (same check) | none |
| #747 | Entering state from the source ledger | #742 | none; judge on a few scenes |

**Wave 3**

| Issue | What | After | Spend to verify |
|---|---|---|---|
| #738 | Tandem, open checker on the first run only | #741, lanes B and C | cents |
| #748 | Extraction names an item's owner | #732, #733 | about $1.50 |
| #743 | Extraction thinking off (Sonnet stays) | #736 | about $2 |
| #749 | A claim in speech is not narration | #738 | a `gate-set` and E3 top-up |

Each spend figure is an agent's estimate and needs Ben's go-ahead.

## Before a redraft

The smallest set that should be merged before *Wrath Like Smoke* is drafted again:

- **#732, #733:** the checks that made 64 false findings.
- **#734, #735, #737:** the halt, the dropped facts, the discarded fix.
- **#740:** false promise findings led fixes to write real errors.
- **#742:** so Homer's own oddities reach an author list and no fact is dropped.

#736 and #741 save money on that run but don't change what it writes. #738 decides which checker the run uses; without it, the choice is still one or the other.

Then a pilot before the full run: re-gate about six existing scenes' pre-fix prose with the fixed gate (about $5) and confirm the false stops are gone.

## Decided on 2026-11-26

These were open questions in the review and are now settled (homer PR 5, iliad-adult PR 24):

- **Homer's own inconsistencies:** divine repairs kept, with the license on the page; physical slips inside a scene smoothed; conflicting accounts in speech kept.
- **Homer over Butler:** Homer wins; a fact is never dropped because it disagrees with the translation alone. Known slips are in `../homer/errata/iliad.csv`.
