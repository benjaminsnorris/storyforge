# The books, ready for a rewrite? (2026-11-02)

Checked overnight on each book's `origin/main`, read-only and with no model calls: `storyforge validate`, `storyforge hone --diagnose`, the ledger's contents, and a new check for names in the briefs that appear nowhere in the book (`brief_names`, below). ashes, the graphic novel with one drafted scene, isn't in the table.

## Summary

| Book | Scenes | Blocking in validate | Ledger | Brief names found nowhere in the book | hone: brief issues / clean scenes |
|---|---|---|---|---|---|
| governor | 99 | acts in `part` | registry only (172) | 3: Halke (ashward-breach); Dael, Solen (mothers-and-honest-infrastructure) | 320 / 42 of 99 |
| lantern-folk | 15 | acts in `part` | registry only (15) | none real ("Remembering") | 54 / 2 of 15 |
| meridian-line | 69 | acts in `part` | registry only (172) | none real (places: "Charlotte County", "the Franklins") | 193 / 32 of 69 |
| **shared-dark** | 102 | acts in `part` | **commitments (1,249)** + registry | **about 100 real names, in 43 scenes across all 5 parts** | 376 / 25 of 102 |
| slipform | 63 | acts in `part`; **seq shared**: 100 (delivery, quiet-block), 310 (croy-bridge, dumb-thing), 370 (pattern, what-we-found) | registry only (33) | 1 (Maren, in `air`) | 342 / 12 of 63 |
| thornwall | 62 | acts in `part`; **seq 58 shared** (last-morning, weight-of-burning) | registry only (135) | 2: Carrack (breaking-camp), Dechlan (ivra-seals-archive), in no prose or reference file | 240 / 15 of 62 |
| understory | 58 | acts in `part`; **seq 12 shared** (cost, kavi-recipe); **kavi-recipe has no intent or brief row** (and no pov in scenes.csv) | registry only (52) | none real ("Ave") | 270 / 2 of 58 |

## What each finding means for a rewrite

- **Acts in `part` (every book).** validate blocks until `storyforge cleanup` moves them into `act`. This is mechanical and free, but run `cleanup --dry-run` first: cleanup does more than this one move.
- **Shared seq (slipform, thornwall, understory).** Two scenes with one seq have no reading order. validate blocks on it (`duplicate-seq`), but `write`, `revise` and `check` don't: `ledger.exit_if_unordered` catches only a missing or non-numeric seq, and `scene_order` puts the two in id order without a word. Which comes first is the author's call; decide it before rewriting. (Follow-up: `exit_if_unordered` should stop on a shared seq too. Not done overnight: `scene_order` serves the gate and the evals, and E8's thornwall trees have that duplicate.)
- **understory `kavi-recipe`.** It's drafted, but it has no row in scene-intent.csv or scene-briefs.csv (and no pov), so a rewrite has nothing to draft from. Add its rows with elaborate, or re-extract them from the prose.
- **Registry-only ledgers (six books).** The gate and the drafting prompt's Established Facts know only the registry facts until extract phase 4 runs. On shared-dark that was 204 Sonnet calls for $10.46 (the books are 15 to 99 scenes).
- **shared-dark's briefs are not safe to draft from.** This is the corruption the status doc dates to ac569274 (revise's upstream brief fix rewrote Act 1's briefs, naming people the book never mentions). It's still there, and it's in every part, not only Act 1. Many of the names are from or evoke the TV show *Chicago P.D.* (Olinsky, Ruzek, Dawson, "Voight", and Kedzie, a Chicago avenue), beside Brennan, Erin, Debra, Kossuth, Harwick, Loomis and others, in `watching-ostrowski`, `drive`, `two-hours`, `shell-company`, `the-school`, `keisha-argument` and 37 more. A rewrite takes its facts from the brief, so it would write these people into the book; the gate might catch some, but only against what the book already says. (Hank Voigt is the book's own character, in characters.csv and the prose: the show's "Voight" is the stray, not him.) **shared-dark is the wrong book to pilot on until its briefs are repaired.**
- **hone's brief issues** (overspecified beats, abstract language) are style heuristics, not errors. None of them blocks a rewrite.

## Recommendation

1. **Pilot on thornwall or meridian-line, not shared-dark.** meridian-line's briefs are clean; thornwall's have two stray names (Carrack, Dechlan) to check first. thornwall needs its seq 58 decided first, and it's an E8 book, so its errors are well known. meridian-line needs only the act move. Steps: `cleanup` (acts), extract phase 4, then rewrite Act 1 and look at the gate's stops and the cost.
2. **Repair shared-dark's briefs before rewriting it.** Re-extract the briefs from the prose (`extract --phase 3 --force`, on a branch; it also re-runs the knowledge and physical-state passes, which write the ledger beside the 1,249 commitments, so check the ledger diff). That makes the briefs say what the book says, and the rewrite then improves the prose without importing strangers. Afterwards, compare the briefs against the plan you meant (the spine and architecture), because re-extraction keeps the prose's errors too. The other way is `hone --domain briefs` with the name list as findings, scene by scene. Either is a paid run, so it waits for your go-ahead.
3. **Decide the shared seqs** (slipform 3, thornwall 1, understory 1) and **add understory's `kavi-recipe` intent and brief rows.**
4. Then each book in turn: cleanup, phase 4, rewrite.

## The name check

The check scans each brief's goal, conflict, outcome, crisis, decision, key actions and dialogue, knowledge, physical states and subtext. It lists capitalized words, not at a sentence start, that appear in no scene's prose and in no characters.csv or locations.csv name or alias. It over-reports a little: "Internal Affairs", drug names and institutions show up too. The script was a one-off in the session's scratchpad, not part of Storyforge. A `hone` or `validate` check of this shape would catch the next brief drift as it happens; that's worth a follow-up issue.
