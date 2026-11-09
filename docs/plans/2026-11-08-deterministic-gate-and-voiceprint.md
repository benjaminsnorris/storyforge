# A deterministic gate, a voiceprint, and long writing sessions

Status: proposal (2026-11-08). Nothing here is decided; every section ends in
Ben's calls. It builds on the gate-and-ledger design
(`2026-10-30-gate-ledger-design.md`) and does not replace the ledger.

## Why

*Wrath Like Smoke* (iliad-adult) is the whole *Iliad*: 91 scenes, about 144k
words. It went through elaboration, drafting, an evaluation, a four-tier
revision, and most of a gate. Ben read the opening chapters and found them
better than the first draft. But they still read as **constructed, not
written**. The voice was no different from earlier Storyforge novels, and
some phrases echo Claude's technical writing. One example: three or four
characters each count the watch-fires, and the prose presents it as a
personal trait every time. That came from a counting motif in
`motif-taxonomy.csv`, assigned across scenes by plan.

What the book cost (`working/costs/ledger.csv`):

| operation | cost |
|---|---|
| elaboration (spine to briefs) | about $20 |
| drafting (91 scenes) | $27 |
| **gate** | **$270** |
| evaluation and synthesis | about $3 |

In the last full gate run (79 scenes, 28 passed), the findings that stopped
scenes broke down like this:

| finding | count |
|---|---|
| CONTRADICTION BLK (the scene against itself: hands, posture, sightlines) | 70 |
| BROKEN-PROMISE (the brief and the prose disagree, mostly because the brief was out of date after revision) | 13 |
| EXTRACTION (a quote that couldn't be verified) | 4 |
| HALT (a fixed fact superseded) | 2 |
| CONTRADICTION KNO | 1 |
| CONTRADICTION WLD | 1 |

So the gate spent ten times the drafting budget, and most of what it stopped
on was blocking a reader would not notice. Examples: "Apollo stood up" when
he had never sat; a spear still in the hand. A handful were real (Ida on the
wrong side of the sky; a wagon's shadow pointing into the sun). The
**sequential stop** made it worse. Any failing scene holds every later scene
at `pending`, so `write` and `revise` refuse to run, and the author has to
work around the tool to make progress. Meanwhile **no step looked at voice**,
which is the thing the reader actually judged.

The conclusion: Storyforge's real strength is the mechanical layer
(structure, the source map, the ledger, knowledge and POV tracking). Its
weakness is prose made by many hands from briefs, then revised by rule lists.
This proposal moves the mechanical layer toward determinism and moves prose
toward one writer holding a voice that comes from examples.

## Principles

1. **Models read, code checks.** A model turns prose into structured facts.
   Code compares facts. Judgement is kept to the places where neither can
   do the other's job.
2. **Narrow questions, not open hunts.** "Find contradictions" invites
   findings. "Is X still true in this scene? Yes or no, and quote it"
   doesn't.
3. **Block only what a reader would notice:** deaths, knowledge, who holds
   what, time, place, names. Everything else is advisory.
4. **Voice comes from examples, not rules.** A rule list moves tics around.
   A bank of chosen passages pulls toward a voice.
5. **One writer per stretch.** Fanning drafting out to many calls averages
   the voice. Large-context models can hold an act.

---

## Part A: the gate

### A1. Extraction: prose to facts

This already exists (`extract*.py`, the ledger, `commitments.csv`). Changes:

- **Typed state, not free statements.** Alongside `statement`, each fact
  gets a small structured record the code can compare:

  | type | record |
  |---|---|
  | `alive` | `{who, state: alive/dead/wounded, since_scene}` |
  | `holds` | `{who, object, since_scene}`; an object is held by at most one person or place |
  | `at` | `{who, location, scene}` |
  | `knows` | `{who, fact_id, learned_in}` |
  | `injury` | `{who, part, side, severity, since_scene}` |
  | `wears` | `{who, item}` |
  | `when` | `{scene, day, time_of_day}`, from scenes.csv, already present |
  | `named` | `{who, name/epithet}`, the canonical name map |

  Existing types (`physical`, `knowledge`, `timeline`, `relationship`,
  `trait`, `world`) map onto these where they can. Facts that don't fit stay
  as statements, and only the question layer (A3) checks them.
- **The form is fixed.** The extractor fills a schema and nothing more,
  every fact with a quote that `quotes.quote_in` verifies. A cheaper model
  is likely enough for the form. That gets measured, not assumed (see
  Evals).
- **Facts come from the prose that was written, never from the brief.**

### A2. Deterministic checks (code, free, the same answer every run)

Run over the typed ledger in reading order:

- **Life and death:** a dead character acts, speaks or is spoken to as
  present (outside memory, dream, ghost or vision scenes, which are marked
  in scenes.csv).
- **Possession:** one object in two hands or places at once, or an object
  used after it was given away, broken or burned, unless a later fact moves
  it.
- **Knowledge:** a POV character acts on, or narrates, a `knows` fact before
  the scene where they learn it. This is a graph walk over
  `knowledge_in`/`knowledge_out` and the ledger. It's the check that
  matters most for a book like the *Iliad*.
- **Place:** a character in two places in one time slot; travel faster than
  the `world` facts allow.
- **Time:** elapsed-time phrases ("three days ago", "the ninth night") against
  the calendar. A small parser handles numbers and units, and it reports
  what it can't parse rather than guessing.
- **Injury:** the injured part used at full strength while the injury is
  current.
- **Names:** an unknown name, or one the name map rules out (Roman for
  Greek; banned forms).
- **Geography and sky:** a `world` table of directions (on this book: sea to
  the west, Ida to the east) checked against a short phrase list ("sun went
  down behind Ida"). It's crude, but it's free and it catches the errors
  that embarrass.

Each check reports with quotes, and "couldn't check" is always a finding
(the repo rule: silence means checked and clean).

### A3. Yes/no questions (a small model, where code can't decide)

For facts the code can't compare (a `trait`, a `relationship`, a promise in
the brief, a statement-only fact), Storyforge writes the questions itself,
from the ledger, for the scenes where the subject appears:

> Established in `briseis-counts-the-pyres`: "Patroclus is the one man in
> the camp who is gentle with Briseis." Scene: `briseis-led-from-the-hut`.
> Does this scene show Patroclus treating Briseis roughly or coldly?
> Answer `yes` or `no`. If yes, quote the line.

- **Who asks:** only facts whose subject appears in the scene (from
  extraction), so the question count scales with the scene, not the
  ledger.
- **Agreement:** each question is asked twice. A finding is kept only when
  both answers say `yes` and the quote verifies. The current checker takes
  the union of two open readings (`merge_readings`), which raises recall
  and multiplies false alarms. This takes the intersection of narrow ones.
- **Model:** the smallest model that holds its numbers on the evals. Each
  question costs a fraction of a cent.
- **Promises:** a brief's `key_actions` become questions in the same way
  ("Does Achilles stop the wrestling before a fall?"). A broken promise is
  advisory, not a stop, unless the author marks the beat `must`. On this
  book 13 broken promises came from briefs that revision had made stale. A
  brief is a plan, and the prose wins.

### A4. Blocking becomes advisory

`blocking.py` (#626) stays as an optional line-editor pass:
`storyforge check --blocking`, or part of a polish. Its findings never stop
a scene and never hold later scenes at `pending`. They go to the report for
the author or a polish pass to take or leave.

### A5. No sequential lock

A failed check marks *that* scene. It doesn't hold the rest of the book
hostage. `write` and `revise` warn, and list the open findings, but they
run. Dependency re-checks (`ledger.dependents`) stay, and they're free when
A2 does the checking.

### A6. Cost target

Extraction is about one cheap call per scene, plus the A3 questions, with
A2 free. The target is under 10% of the drafting cost for a full gate
pass, against about 1000% today.

---

## Part B: the voiceprint

The feature is for writers who have a voice but can't name it, and
especially for people with a large body of published writing (Ben has
years of posts on bennorris.com).

### B1. Import a corpus

`storyforge voice import <folder|urls|feed>` takes the author's own
writing: Markdown, HTML, a site's RSS, or exported posts. It strips
boilerplate, keeps the date and genre (essay, fiction, notes), and stores
it under `reference/voice/corpus/`. Storyforge reads the corpus and never
sends it anywhere except the model calls listed here.

### B2. The fingerprint (code, free)

Measured over the corpus, stored as `reference/voice/fingerprint.json`:

- the sentence-length distribution and how much it varies; paragraph
  length; how long sentences run before a full stop;
- function-word frequencies (the classic stylometric signal), punctuation
  habits (semicolons, dashes, parentheses, questions), contractions;
- reading level; Latinate versus Anglo-Saxon vocabulary; adverb and
  adjective density;
- how paragraphs and pieces open and close (first and last sentences, kept
  apart);
- recurring constructions and phrases, found by n-gram against a general
  baseline: what this writer says more often than writers do.

### B3. The described voice (a model, corrected by the author)

A model reads a large sample alongside the fingerprint and writes a short
description: what the voice does and never does, its stance toward the
reader, its humour, its rhythm. The author marks each claim "yes, me" or
"no". The corrected version is `reference/voice/description.md`. This is
the part people can't do for themselves, and it's cheap.

### B4. The exemplar bank

`reference/voice/exemplars/`: 20 to 40 passages from the corpus, each 100
to 400 words, tagged by job (description, argument, a turn, humour,
quiet, dialogue if any). The author picks them from a shortlist the model
proposes. **The writing model always has the exemplars in context.**
They're the voice spec. The rules list shrinks to the few things the
author actually forbids.

### B5. Calibrating fiction: small blind samples

A blog voice is non-fiction, and fiction needs dialogue, scene and other
minds. So before drafting:

1. Pick one scene from the book.
2. Write it four or five ways (300 to 500 words each), all held to the
   exemplars but varying the narrator's stance, distance and tense, and
   blending any named influences (the author can add books or poets to
   blend in, the way you'd brief an image).
3. The author reads them unlabelled and marks sentences: keep, cut, more
   like this.
4. Three or four rounds. The winning passage, ideally one the author has
   rewritten by hand, joins the exemplar bank as the **fiction anchor**.

`storyforge voice sample --scene <id> --variants 5` runs one round. Each
round costs a few dollars.

### B6. The meter (code, free)

`storyforge score --voice` scores any prose against the fingerprint: the
distance on each measure, the sentences furthest from the corpus, and a
list of constructions the corpus never uses but the draft does (that's
where AI tells show up). It catches drift. It can't tell good from bad,
and it is never used as an optimisation target for an automatic rewrite
loop.

---

## Part C: long writing sessions

### C1. One writer, one context

`storyforge write --session <act or scene range>` makes one long call (or a
continued conversation) that writes a whole stretch in order. In context:

- the voice: exemplars, the fiction anchor, the description, and the few
  author rules;
- the story so far, word for word, as far as the window allows (with large
  windows, most of a book);
- a light plan for the stretch: per scene, the POV, the events, the turn
  and what must be true at the end. No motifs, no beat lists, no subtext
  fields, no "key dialogue";
- the canon and name map.

The writer works scene after scene without a fresh call per scene, so the
voice carries over. Long output limits matter here. The session resumes
from the last finished scene if it's cut off.

### C2. After a session

1. A2 and A3 run (cheap). Hard findings go back into the same session as
   short notes ("Hector is dead in scene 72; scene 74 has him speak"),
   fixed by the writer that wrote the stretch.
2. The meter (B6) reports drift.
3. The author reads. Revision is by **reaction**: the author marks
   passages, and the same session revises them with the exemplars in view.
   A rule-list pass across the book is not a default.

### C3. What gets demoted

- `motif-taxonomy.csv` and motif placement in briefs. A motif is noticed in
  the draft and recorded after, never assigned ahead.
- Brief fields that script the prose (`key_dialogue`, detailed
  `key_actions`, `subtext`) become optional notes, not promises.
- `revise --polish --loop` and `--naturalness` as defaults.
- The voice guide as a rule list. It becomes the description, plus the
  exemplars, plus a short list of things to avoid.

---

## Evals: how we'd know

The existing suites stay the yardstick:

- **E4** (contradictions in passed scenes) and **E8** (reintroductions):
  the new gate has to match or beat today's recall on hard categories
  (KNO, PHY, TIM, WLD) at a fraction of the cost. Measure A2 alone, then
  A2+A3, then each with small and large extraction models.
- **New, E9 (false-stop rate):** the number of scenes stopped per 10k words
  on findings a human labels "a reader wouldn't notice". Wrath's last run
  gives a baseline: 70 of the 92 stopping findings were blocking.
- **New, E10 (voice):** blind pairwise reads of the same scene written (a)
  by today's pipeline and (b) in a session with the exemplars. The author
  and a second reader pick which "sounds written". It's subjective by
  design, and it's the thing that matters. The B6 distance is tracked
  alongside it to see if it agrees.

## Phasing

1. **Gate policy (small, first):** blocking becomes advisory (A4), the
   sequential lock goes (A5), and promises become advisory (A3, last
   bullet). These are mostly flags and gate rules, and they would have
   saved most of this book's gate spend.
2. **Typed state and A2 checks:** knowledge and life-and-death first, then
   possession, place, time and injury. Measure on E4 and E8.
3. **The A3 question layer** replaces the open checker for the facts A2
   can't cover. The open checker stays behind a flag until the evals say
   it can go.
4. **The voiceprint, B1 to B4 and B6:** a prototype on Ben's site corpus
   before it becomes a command.
5. **B5 fiction calibration and C sessions:** pilot on one act of *Wrath
   Like Smoke* against the existing draft, then E10.

## Ben's calls

- Is this the direction: the mechanical layer as the product's core, prose
  by one writer in sessions with an example-based voice?
- Blocking: advisory everywhere, or kept as a stop for some books (the
  gawain case in #626 was why it was added)?
- How much of the brief survives in C1's light plan?
- Phase 1 ships first on its own?
- The voiceprint corpus: does bennorris.com serve as the prototype corpus,
  and which sections (essays only, or everything)?
- Where the exemplar bank lives for a series (per book, or shared, like
  `series.canon`).
