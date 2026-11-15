# Ready to draft: what *Wrath Like Smoke*'s voice work teaches, and what's left

Status: accepted with Ben's answers (2026-11-14; see Decisions). It refines
`2026-11-08-deterministic-gate-and-voiceprint.md` (Parts B and C, issues
#654, #655, #656) with what the iliad-adult voice rounds found, and lists
what Storyforge and the book still need before the redraft starts.

## What the voice rounds showed

Four blind rounds of the farewell at the Scaean Gate (iliad-adult PRs
#10–#13), then three test scenes in take 1 and take 2 (Chryses' ransom,
Sarpedon at the wall, Zeus's nod; PR #15). The result is
`reference/voice-notes.md` in iliad-adult: an anchor passage Ben finished by
hand, notes on what it does that quote it, notes on the people, a list of
checks, and two decided rules (third person, very close; mortals in present,
gods in past).

1. **The spec is passages plus notes that quote them, not rules.** Round 3
   was written from the list of things to avoid. It avoided all of them and
   read "flat and listless". The notes say how to use them: read the anchor,
   write toward it, and check the draft against the list only afterwards.
   So writing and checking need different inputs. The writer gets the
   passages and the notes on what they do. The checks run on a finished
   scene.
2. **For an author with no fiction, the voice belongs to the book.** Ben's
   author repo has no accepted description or exemplars (decision 21). The
   `voice:` block requires both, so it can't hold this voice. The real voice
   lives in the book, and with `voice-guide.md` retired, `write` now stops
   with "no voice guide". **Nothing can draft Wrath today.**
3. **Different scenes need different reference passages.** A mortal's scene
   in present tense (Chryses), a god's scene in past (Zeus), an intimate
   scene (the farewell) and a battle (Sarpedon, still unmarked). Each
   reference is 500 to 1,500 words, so all of them fit in a session's
   context. A scene's plan should name the closest one.
4. **Tense follows the POV.** Storyforge has no idea of tense per scene.
5. **Voice decides POV.** The opening moved from Agamemnon to Chryses, and
   deaths are seen by the man dying. The map fixed every POV before any voice
   existed. That is #656's argument, and Wrath's map now needs a POV pass.
6. **The old briefs carry the old problems.** Wrath's 91 briefs predate the
   lean briefs (#644). All 91 have motifs. The opening's brief has Agamemnon
   "counting the fires the way he counts everything", which is the tic Ben
   flagged in the first draft. Its `key_dialogue` scripts the speeches, and
   its POV is no longer the opening's POV.
7. **How the rounds were run is the spec for `voice sample`:**
   - one sentence per line, so marks attach to sentences;
   - unlabelled variants, with the key held outside the repo;
   - the rounds as PRs, reading every page of comments;
   - after round 2, takes that revise toward the keeps, with two versions
     that differ in one thing (tense, or whose POV) instead of five blends;
   - checking a sample before publishing it, for the patterns promised gone
     and for physical slips;
   - the author finishing the winner by hand.
8. **What's still untested:** the narrator outside intimate scenes (battle,
   summary, councils), and voices other than Hector, Andromache, Chryses,
   Zeus and Hera. Draft a few scenes and read them before running an act.

## What Storyforge needs, in order

### 1. The book's voice, without an author repo (new, small)

A book folder that drafting reads, with an author repo or without one:

```
reference/voice/
  book.md        # what the voice does, quoting the anchors; the people;
                 # decided rules (person, distance, tense by POV)
  anchors/       # the anchor and the reference scenes, one .md each, with a
                 # first line `kind: intimate | battle | god | mortal | ...`
  checks.md      # checks run on a finished scene; never in the writing prompt
```

- When `reference/voice/book.md` and at least one anchor exist, that is the
  voice, and `voice-guide.md` isn't required. `status`, `write` and `revise`
  accept it.
- The `voice:` block stays for an author repo. With one, its description and
  exemplars come first, then the book's folder (as `book.md` already does).
- `checks.md` never goes into a writing prompt. A test asserts that.

### 2. Tense per scene

- An optional `tense` column in `scenes.csv` (`present` or `past`; blank
  means the book's default, `voice.tense` in `storyforge.yaml`). The plan
  for each scene states it.
- A free check: narration (outside quotes) mostly in the other tense is a
  finding.

### 3. Long writing sessions (#655)

As the issue says, with these changes from the rounds:

- The session's context holds `book.md` and every anchor (not `checks.md`),
  the story so far word for word, a lean plan per scene (POV, tense, the
  closest anchor, events, the turn, the end state), the canon and name map,
  the key decisions, and the stage sheet.
- **Briefs written before #644 aren't scripts.** A lean plan reads only
  `events`, `outcome`, POV, the state in and out, and the author's notes.
  `key_dialogue`, `motifs`, `subtext` and the model-written goal, conflict,
  crisis and decision stay out unless the author marks them as theirs.
- After each scene: the free checks, the stage sheet and the question layer.
  Hard findings go back into the session as short notes. The open checker
  isn't the default.
- `checks.md` runs on each finished scene in two separate agents (Ben). A
  **reviewer** reads the scene against `checks.md` and flags lines, naming
  the check and quoting the line. A **reviser**, in a fresh context with
  `book.md` and the anchors (never `checks.md` as a rule list), rewrites only
  the flagged lines toward the anchors. With full coaching that runs by
  itself; with coach or strict coaching the flags go to the author and
  nothing is rewritten. The goal (Ben): agent writing at full coaching that
  matches the voice. The author's own marks (keep, cut, more like this, a
  note) go to the same reviser.
- `--dry-run` forecasts the cost. Default: stop after the first 3 scenes for
  a read before going on.

### 4. `voice sample` (#654), shaped by section 7 above

It runs a round as a PR in the book. Variants are one sentence per line and
unlabelled, and the key goes outside the repo. Round 2 onwards reads the
author's marks from the PR's comments, every page. A "take" mode revises a
sample toward its keeps, with two versions that differ in one named thing.
Before publishing, the samples are checked against `checks.md`. A winning
passage is saved to `reference/voice/anchors/`.

### 5. After the pilot

#656 (the voice stage after the synopsis, with a POV pass after the map),
#658 (adaptations enter at the map), #657 (bibles as rows), and #659 (the
blind read of the old draft against the session pilot).

## What Wrath needs before drafting (book work)

- Split `voice-notes.md` into `reference/voice/`: Parts 1–3 and 5 into
  `book.md`, the anchor and the Chryses, Zeus and Sarpedon takes into
  `anchors/`, and Part 4 into `checks.md`. Ben's text moves word for word.
- **Ben:** mark the Sarpedon pair (PR #15), so a battle has a reference.
- **Ben's call:** a POV pass on `scenes.csv` against the voice decisions
  (Chryses opens; deaths seen by the man dying; the gods' scenes). Claude
  proposes, Ben decides.
- Fill `tense` from POV (gods past, mortals present).
- The old briefs stay (Ben, 2026-11-14). The session reads only their fact
  columns.
- The two `status` items: six summaries over 50 words, and the knowledge fact
  `commitments.csv` lacks.
- Pilot: `write --session --dry-run` on Act 1, then the first 3 scenes, and
  Ben reads them before the rest of the act.

## Decisions (Ben, 2026-11-14)

1. **Old briefs:** keep them, and have the session read only the fact
   columns. No re-brief.
2. **Voice checks:** one agent identifies the problems and a separate agent
   rewrites, aiming for quality writing at full coaching.
3. **Order:** build #654 and #655 in Storyforge first. Ben then uses them on
   Wrath. The Wrath items above are his, done afterwards.
