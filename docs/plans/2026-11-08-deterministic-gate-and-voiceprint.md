# A deterministic gate, a voiceprint, long writing sessions, a shorter ladder, and cheaper evals

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
on was blocking: "Apollo stood up" when he had never sat, a spear still in
a hand that then grips two ankles, a sun setting behind a mountain the
dawn rises over. **These are real errors.** The fix agents judged nearly all
70 of them genuine and fixed them. Think of the book as a film: the
narration has to know where everyone is, what they hold and which way they
face, or a description contradicts itself. A careful reader notices and is
thrown out of the story, and most readers feel it as a vague
dissatisfaction even when they can't say why. The problem was the method,
not the category. Each error was found after the fact, by a large model
reading the whole scene twice, at about a dollar a scene, and then the
scene was patched one clause at a time. The **sequential stop** made it
worse. Any failing scene holds every later scene
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
3. **Continuity is a film set.** Where everyone is, their posture, what
   they hold and wear, and which way they face are tracked as state, the
   way a script supervisor tracks a shoot. They're prevented while writing
   and checked by code after, not hunted for by a reader model. Craft
   *frameworks* are advisory; continuity *errors* block.
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

### A4. Blocking: a stage sheet, like a film's continuity

Blocking errors (who stands, who sits, which hand holds what, who is in
front, what's worn, where the light is) are what make a scene feel
untrustworthy, and they stay errors that block. What changes is how
they're caught: prevention first, then cheap checks.

**The stage sheet.** For each scene, a running record of the stage, beat by
beat:

| field | example |
|---|---|
| present | Priam, Idaeus, Hermes |
| posture | Priam: seated in the car; Hermes: on foot |
| hands | Priam: L reins, R empty; Hermes: R wand |
| position | the wagon ahead, the car behind; Hermes at the mules' heads |
| facing / sightline | Priam facing the gate; Cassandra too far to see her face |
| worn / carried | Achilles: no cloak; the thongs in the car |
| light / place | dawn behind Ida (east); the yard, out of sight of the shore |

1. **Prevention: the writer keeps the sheet.** In a session (Part C), the
   writer starts each scene with the sheet carried over from the last one
   and the scene's opening state. When it moves a body, it updates the
   sheet in a side channel (a short structured note after each scene, not
   in the prose). Most of Wrath's 70 errors were the drafter losing track,
   and a written sheet is what a careful human writer or a film's
   continuity supervisor uses.
2. **Extraction: the stage as events.** After drafting, the extractor
   labels each physical action as a transition on the sheet:
   `posture: seated -> standing`, `hands.R: spear -> empty (drove it into
   the ground)`, `position: Hermes ground -> ground`. A fixed schema, with
   every event quoted and the quote verified.
3. **Code checks the transitions, for free.** A transition from a state
   the sheet doesn't hold is an error: standing up when standing, gripping
   with a full hand, taking a cloak off that was never on, seeing a face
   past sight range, a shadow that points toward the sun. A small table of
   world facts (directions, light, distances) covers the sky and
   geography cases.
4. **A narrow yes/no for the rest.** Where an action can't be typed ("he
   could see the jaw under her hand"), a small model gets one question
   against the sheet at that beat, asked twice and kept only if both
   answers agree.

**Fixing.** A blocking error is always local to its scene. It goes back to
the writer of the stretch as a note with the sheet at that beat ("Priam is
in the car, which is behind the wagon; 'the box behind him' can't be
reached"), not to a separate fix agent. A blocking error stops *its*
scene from being marked done; it doesn't hold later scenes (A5).

`blocking.py` (#626), the whole-scene line-editor read, stays as a fallback
behind a flag until the sheet's recall on gawain's 35 and Wrath's 70 known
errors matches it. Those 105 cases are a ready-made labelled set.

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

**A voiceprint belongs to an author, not a book.** It's made once per
author, in the author's own repo, and every book points to it. It works
the way `series.canon` points a book at `../homer`: read in place, never
copied into the book.

### B0. The author voice repo

A dedicated repo per author (for Ben, say `ben-voice`), created with
`storyforge voice init`:

```
<author-voice>/
  voice.yaml          # author name, corpus sources, sections in or out
  corpus/             # the author's writing, as imported (B1)
  fingerprint.json    # B2, computed
  description.md      # B3, corrected by the author
  exemplars/          # B4, chosen by the author, tagged by job
  fiction/            # B5 anchors, one folder per narrator stance tried
```

A book's `storyforge.yaml` names it:

```yaml
voice:
  author: ../ben-voice          # the author voice repo, read in place
  narrator: fiction/close-third # optional: which fiction anchor this book uses
```

The book keeps only what's particular to it in
`reference/voice/book.md`: the narrator's stance, the period register
(the *Iliad*'s bronze-age vocabulary), and any book-level exemplars. The
author's voice is the constant, and the book adjusts the narrator.

The corpus stays in the author repo. Storyforge reads it and sends it
nowhere except the model calls listed in this part. The repo can be
private.

### B1. Import a corpus

`storyforge voice import <folder|urls|feed>`, run in the author repo,
takes the author's own writing: Markdown, HTML, a site's RSS, or exported
posts. It strips boilerplate, keeps each piece's date and kind (essay,
fiction, notes, link post), and stores it under `corpus/`. `voice.yaml`
says which kinds count. Short pieces and link posts carry less voice and
are out by default.

### B2. The fingerprint (code, free)

Measured over the corpus, stored in the author repo as `fingerprint.json`:

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
"no". The corrected version is the author repo's `description.md`. This is
the part people can't do for themselves, and it's cheap.

### B4. The exemplar bank

The author repo's `exemplars/`: 20 to 40 passages from the corpus, each 100
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

### B7. A public-domain reference voiceprint, with tests

Storyforge itself ships one complete voiceprint, built from a
public-domain author, under `references/voiceprints/<author>/`, in the
same layout as an author repo. It does two jobs: it's the worked example
a new author can look at, and it's the fixture the tests run against. If
Storyforge can find a known author's voice accurately, there's reason to
trust it on a living author's corpus.

**Which author.** It needs at least two substantial works, so one can be
held out. It should be written in English, so the voice is the author's
and not a translator's. The evals repo already has extracted texts, but a
voiceprint needs only raw text, which Project Gutenberg supplies, so
extraction isn't an advantage.

- *Recommend:* **Edith Wharton.** *The Age of Innocence* is already in
  the evals, and *The House of Mirth* is the held-out book. She has a
  distinct, measurable voice (long periodic sentences, social irony, a
  Latinate vocabulary), and it's novel-length fiction, which is what the
  tool has to serve. Austen (*Pride and Prejudice*, plus *Emma* or
  *Persuasion*) is the alternative, with an even better-studied voice.
- *Jules Verne* works as a second fixture, but for a different test.
  *Around the World in Eighty Days* and *Five Weeks in a Balloon* are in
  English translation, by different translators (to confirm from the
  Gutenberg headers). A good voiceprint should report that the two
  corpora don't share a voice, and that what it measures is the
  translator's. That's a useful test, because a real author's corpus can
  mix voices too: ghostwritten posts, a decade of drift, quoted material.

**The tests.** Most are free and deterministic. They run on every commit.

1. **Attribution (free).** Fingerprint the reference author from one
   book. Cut held-out chunks of about 2,000 words from the other book and
   from six to eight other public-domain authors (the evals' Austen,
   Dickens, Eliot, Fitzgerald, Fisher, Marks, Brunton). The fingerprint has
   to rank the held-out book's chunks closest to the author, at a fixed
   accuracy floor. This is classic stylometric authorship attribution, and
   it's the core evidence the fingerprint measures a voice.
2. **Stability (free).** Fingerprints from two halves of the corpus agree
   within a set tolerance. Fingerprints from 10k, 25k and 50k words show
   how much corpus is enough. That number becomes `voice import`'s
   minimum-corpus warning.
3. **Mixed voices (free).** The Verne pair, plus a corpus seeded with
   20% of another author's chunks: the tool reports low consistency and
   names the outlying pieces, rather than averaging them in.
4. **The description (recorded once, then frozen).** The B3 description of
   the reference author is checked against a fixed list of claims a
   critic would make or reject (for Wharton: irony at her characters'
   expense, yes; plain short sentences, no). It's recorded once, replayed
   free, and re-recorded only when the description prompt changes on
   purpose.
5. **The exemplar shortlist (free).** The B4 shortlist's passages sit
   inside the fingerprint's typical range, and they span the jobs (not
   twenty descriptions of rooms).
6. **Writing in the voice (frozen, three runs when run).** A scene written
   with the reference exemplars scores closer to the author on the meter
   than to the other authors, and a judge picks the author from four
   candidates. It's the expensive test, so it follows Part E's rules: frozen
   inputs, run only for a decision, three runs.

Building the reference voiceprint is also the first real run of B1 to B4,
so the prototype on Ben's corpus follows it, with the tool already
checked.

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
- the stage sheet carried over from the last scene (A4), which the writer
  updates after each scene.

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

## Part D: the elaboration ladder

The ladder goes logline, then synopsis and act shape (the prose tier), then
spine, architecture, scene map, briefs and draft. Each stage is checked
before the next one starts, and building in stages is sound for **what
happens**. Wrath shows the problems are at three points on the ladder: where
it stops, where voice comes in, and what the checks between stages reward.

### D1. What stays

- **The ladder through the scene map:** logline, synopsis, spine,
  architecture, scenes with POV, place, time and cast. This is story logic,
  and it's where Storyforge is strongest.
- **The structural checks that catch errors:** coverage, the knowledge chain,
  POV and timeline, the source map's coverage, series canon. With the ledger
  (Part A) they're the product's core.

### D2. Facts: planned and discovered

Part D is about one ladder for every book. An original story climbs every
rung; an adaptation's source fills some rungs, and the author starts higher
(D8). Either way, the question is when the story's facts get settled. They
come in two kinds, settled at different times.

**Load-bearing facts are settled before drafting, by the ladder.** These are
the facts the plot depends on, and each rung adds a layer:

| rung | facts it settles |
|---|---|
| logline / synopsis | the premise, the ending, the central secret or question |
| spine | the major events and what causes what |
| architecture | the turning points, and **who learns what, when** (the order of reveals) |
| world and characters | the rules (magic, law, technology), histories, relationships, kinship, what each character wants and what they hide |
| scene map | each scene's POV, place, day and time, who is present, and the knowledge and physical state in and out |

All of it lands in the ledger as binding facts with origin `plan`, before
any prose. That's the mechanical layer Storyforge should be best at. Part
A's deterministic checks hold the draft to it.

**Texture facts are discovered while drafting.** Patroclus's scar, the dog
at Antenor's gate, a herald's bad knee. The writer invents them on the
page. Extraction records them with origin `prose`, and from then on
they're binding for every later scene. The ledger already distinguishes
origins (`author`, `plan`, `prose`). The stage sheet (A4) is the same idea
at the scale of a scene.

**When the plan is done: the two-writers test.** Could two different
writers draft from the plan and produce books that agree on every plot
point, while their sentences, gestures and images differ? If so, the
load-bearing facts are settled, and the rest belongs to the writer. A stage
can be checked against this: an unsettled reveal order, a relationship left
ambiguous, or a rule of the world with no answer is a gap the ladder still
owes.

**Facts, yes; staging, no.** This is the line D3 draws for briefs. A brief
keeps every fact the scene must honour or establish. It drops the staging:
how the scene is played, what is said, what it means.

**Bibles as facts, not essays.** The character, world and systems bibles
are model-written essays today (`REFERENCE_DOCS` in the checker), and they
leak the model's phrasing into drafts the same way briefs do. Proposed:

- What's true about the world and the people becomes **rows**, in the
  registries (`characters.csv`, `locations.csv`, ...) and the ledger
  (`commitments.csv`, type `trait`, `relationship`, `world`, origin
  `plan`).
- What a character sounds like becomes **a few lines of them speaking**
  (from voice samples, Part B), not a paragraph describing their speech.
- A short prose note stays only for what really resists rows (a culture's
  feel, a history's shape), written as terse notes (D4).

### D3. Briefs stop at "what happens"

Today's brief (`scene-briefs.csv`) carries `goal`, `conflict`, `outcome`,
`crisis`, `decision`, `key_actions`, `key_dialogue`, `emotions`, `motifs`
and `subtext`. Intent (`scene-intent.csv`) adds `value_shift`,
`turning_point`, `emotional_arc`, `mice_threads` and `theme_threads`. By the
time drafting starts, the scene has been written in outline, and the drafter
fills in a spec. That is the "constructed" feeling at its source. Writers who
outline heavily still find the gesture, the line and the image while they
draft.

Proposed: the brief keeps **events, the turn, POV, and what must be true at
the end** (knowledge and physical state out, which feed the ledger). The rest
becomes optional notes the author can add by hand, never generated by
default. `key_dialogue`, `subtext`, `emotions` and `motifs` are the first to
go. A line the author wants verbatim (a source line in a faithful
adaptation, say) is marked as such, and it's the only scripted text a draft
must carry.

### D4. The plan is written in the drafter's voice

Every elaborated field is model prose, and the prose inherits it. On Wrath, a
brief's subtext ("let the list grow, and never call it pride") turned into
the aphoristic closing lines Ben singled out. The drafter reads Claude's
sentences and writes more like them. Leaner briefs (D3) reduce this. Writing
what remains as **terse notes**, not polished sentences, reduces it more:
"Agamemnon counts the gifts on the sceptre studs; Briseis is the sixth stud,"
not a paragraph about what the moment means. The elaboration prompts should
ask for notes and forbid interpretation.

### D5. Voice moves up the ladder

The voice stage comes after briefs today (`status` raises a `voice` blocker
once briefs are done), and it produces a rule list. Voice is structural, not
paint. Who tells the story, and from what distance, decides which scenes
exist and whose eyes they're in. Wrath had a POV fixed for every scene in
the map before any voice was found.

Proposed: **voice comes right after the synopsis**, before spine and
architecture deepen, and it's found by samples (Part B). The narrator's
stance it settles feeds the map: whether a narrator holds scenes, how many
POVs, and close versus distant. Then a second, short voice check after the
map confirms the voice holds across the POV mix.

### D6. Checks catch errors, and craft frameworks advise

`validate` and the stage checks test value shift per scene, MICE nesting,
scene type and function, and fidelity to the brief. Each idea is reasonable.
Applied as a pass/fail check at every stage, together they press every book
toward one shape: each scene a closed unit with a turn and a landing. That's
the ending-template problem (Wrath's voice guide had to grow a rule to vary
the closes).

Proposed: anything that tests **conformity to a craft framework** (value
shifts, MICE order, scene function balance, emotional arc shape) becomes
advisory, shown as a diagnostic the author can use. Blocking stays for
**errors**: a broken knowledge chain, a missing source event, a timeline
that can't happen, a canon violation.

### D7. The drafting unit gets bigger

Drafting scene by scene makes each scene self-contained, with its own
opening and landing. Chapters run into each other. Part C's sessions draft a
stretch in one context. The ladder's last stage becomes the **act or
chapter run**, not the scene.

### D8. Adaptations: the same ladder, entered higher

An adaptation isn't a separate pipeline. It's a shortcut onto the same
ladder: the source supplies the load-bearing facts for the upper rungs
(D2), so the author starts lower down the table, at the scene map.

Wrath shows what goes wrong without the shortcut. It set out to build on a
proven story so the effort could go into voice and prose. Storyforge ran
every rung anyway: it re-derived a spine and architecture the *Iliad*
already supplies, generated prose-shaped briefs for 91 scenes, then checked
fidelity to Butler's beats. The faithful-mode checks were part of why
speeches got re-performed instead of dramatised.

For a book with a `source:` block:

| rung | original story | adaptation |
|---|---|---|
| logline, synopsis, spine, architecture | the author builds them | **given by the source** (the source map), plus **interpretation decisions**: what this version is about, whose eyes, what's cut, what's invented, where it ends, and the mode |
| world and characters | the author builds them | given by the source and canon; the author adds what the source leaves open (in a faithful mode, sparingly) |
| voice | by samples (Part B) | by samples, on a scene from the source |
| scene map | built | source events grouped into scenes with POV and the turn; invented scenes get a line of why |
| drafting | sessions (Part C) | sessions |

The interpretation decisions are the author's few pages in `key-decisions.md`.
They do for an adaptation what the spine and architecture do for an original:
they settle the facts the version depends on that the source doesn't.

Checks are the same as for any book: continuity (Part A), plus **coverage**
from the source map, meaning whether any source event was dropped without a
recorded decision. Fidelity means the events happen. It doesn't mean the
source's staging or speech order is replayed.

### D9. Roughly what changes

About half the current approach stays as it is: the ladder through the
scene map, the ledger and the error checks. About a quarter changes in
degree: shallower briefs, advisory craft checks, a cheaper gate. About a
quarter is new: voice early and by example, long drafting sessions, and the
adaptation track.

---

## Part E: evals

### E1. What the evals have cost, and what they bought

The status doc (`2026-10-28-rethink-status.md`) records about **$276 in
re-recordings over the last five rounds alone** (#491 $67.66, #596/#601
$71.13, #513/#613 $81.25, #616 $9.90, #610 $2.26), with more before that.
Its own reading of the results:

- "Every E4 claim from #480 and #482 is within noise."
- On two checker readings: "no gain in errors committed is measured."
- On the re-recorded rounds: "One run each, so read these as likely, not
  measured, improvements."

Three causes:

1. **The expensive suites test the whole pipeline end to end.** E4
   (generation) and E8 (revision safety) run drafting, extraction and the
   gate together, at $20 to $50 per suite per recording. Any prompt change
   anywhere misses the cassette, so every improvement buys a re-record.
2. **One run can't separate signal from noise.** E6 showed E4's spread is
   wider than most of the claimed gains, so the spend produced numbers
   that couldn't settle the decisions they were bought for.
3. **They measure only continuity.** No suite measures whether the prose
   is any good. That's what Ben's read of Wrath judged.

What paid off were the **cheap suites with fixed, labelled inputs**: the E2
checker cases, E3 extraction, and the re-check set. Each costs a few
dollars, and each found real things (for example #480, where the "false
alarms" were mostly real errors, and E3's extraction recall). With fixed
inputs, a change in the number is a change in the tool.

### E2. Evals under this design

- **A2's deterministic checks are code, so they get unit tests,** not
  evals: free, exact, run on every commit, with no cassettes.
- **A3's yes/no layer gets a fixed labelled question set.** It costs cents
  per run on a small model, so three runs show the spread.
- **Extraction keeps an E3-style fixed set.**
- **E4 and E8 are frozen.** No re-record on a prompt change. They run only
  when a decision depends on them, and always three runs. A suite whose
  cassette misses is marked stale, and nobody spends on it.
- **A new suite needing live generation for its inputs** records those
  inputs once and freezes them. It then evaluates against the frozen
  inputs.
- **Budget:** a monthly eval budget (proposed $25) that an agent can't go
  past without asking Ben.

New suites (numbered when built; E9 is already taken by
`extract-upper-layers.md`):

- **Blocking recall and false stops:** the stage sheet (A4) against a
  fixed set of known blocking errors, gawain's 35 (#626) and Wrath's 70
  with their fixes, plus clean scenes for false alarms. It's free to
  build: the cases and the fix agents' verdicts already exist.
- **Voice:** blind pairwise reads of the same scene, (a) from today's
  pipeline and (b) from a session with the exemplars. Ben and a second
  reader pick which "sounds written". It costs readers' time, not dollars,
  and it's the suite that measures what the product is for. The B6 meter's
  distance is tracked alongside to see whether it agrees.

- **The voiceprint's tests** (B7): attribution, stability, mixed voices
  and the exemplar shortlist are free and run on every commit. The
  description is recorded once and frozen. Writing in the voice follows
  the frozen, three-run rule.

The gate's targets carry over: the new gate has to match or beat today's
recall on the hard categories (KNO, PHY, TIM, WLD) on the frozen E4 and E8,
at a fraction of the cost.

## Phasing

1. **Gate policy (small, first):** the sequential lock goes (A5), and
   promises become advisory (A3, last bullet). Blocking still blocks,
   through today's `blocking.py` for now. These are mostly flags and gate
   rules.
2. **The stage sheet (A4):** the writer keeps it in sessions, extraction
   labels transitions, code checks them. Measure on the blocking set
   (Part E) before retiring the whole-scene read.
3. **Typed state and A2 checks:** knowledge and life-and-death first, then
   possession, place, time and injury. Measure on E4 and E8.
4. **The A3 question layer** replaces the open checker for the facts A2
   can't cover. The open checker stays behind a flag until the evals say
   it can go.
5. **The voiceprint:** first the reference voiceprint and its tests (B7),
   which also builds B1 to B4 and B6. Then Ben's author repo (B0) from his
   site corpus.
6. **B5 fiction calibration and C sessions:** pilot on one act of *Wrath
   Like Smoke* against the existing draft, then the voice suite (Part E).
7. **The ladder (Part D):** craft checks become advisory (D6) and briefs
   get lean, note-style defaults (D3, D4). Both are small and can ride
   phase 1. Bibles move to rows (D2) alongside the typed ledger in
   phase 3. Voice moves up the ladder (D5) with phase 5. The adaptation
   shortcut (D8) is piloted on Wrath's redraft, which already has its source
   map and its interpretation decisions in `key-decisions.md`.

## Ben's calls, with recommendations

**Direction**

1. **Is the product's core the mechanical layer (structure, ledger,
   continuity), with prose by one writer in sessions and voice set by
   examples?**
   *Recommend:* yes. That's where Storyforge is strong, and where Wrath
   went wrong.
2. **Does phase 1 ship alone first?** (Promises advisory, no sequential
   lock, craft checks advisory, lean briefs; blocking still blocks.)
   *Recommend:* yes. It's small and mostly policy, and it removes most of
   the cost and friction Wrath hit.

**The gate**

3. **Blocking: the stage sheet (A4) as the way it's caught?** (Decided:
   blocking errors are real errors and they block.)
   *Recommend:* yes. The writer keeps the sheet, extraction labels
   transitions, and code checks them. The whole-scene read stays until the
   sheet matches it on the 105 known cases.
4. **Broken promises: advisory unless a beat is marked `must`?**
   *Recommend:* yes. A brief is a plan, and the prose wins. Revision made 13
   of Wrath's briefs stale.
5. **Is the open checker kept as a fallback?**
   *Recommend:* behind a flag until A2 and A3 match its recall on the
   frozen E4 and E8, then removed.

**Evals**

6. **Freeze E4 and E8 (no re-record on prompt changes, run only for a
   decision, three runs when run)?**
   *Recommend:* yes, plus a monthly eval budget (about $25) an agent can't
   pass without asking.
7. **Make fixed labelled sets the default kind of eval?**
   *Recommend:* yes. When a suite needs live generation for its inputs,
   record them once and freeze them.
8. **Adopt the blocking-set and voice suites?**
   *Recommend:* yes to both. The blocking set is free from gawain's and
   Wrath's known errors. Voice is
   the one that matters most.

**The ladder and briefs**

9. **Which brief fields survive by default?**
   *Recommend:* events, the turn, POV, and the knowledge and physical state
   out. Everything else becomes optional notes the author writes.
10. **Briefs and plans written as terse notes, with interpretation
    forbidden?**
    *Recommend:* yes. It's cheap, and it cuts the main route by which the
    model's phrasing leaks into the prose.
11. **Which validate checks become advisory?**
    *Recommend:* every check of conformity to a craft framework (value
    shift, MICE order, scene function, arc shape). Errors still block.
12. **Voice right after the synopsis, or later?**
    *Recommend:* right after the synopsis, with a short second check after
    the map. It's a soft default the author can skip to do structure first.
13. **Adaptations as the same ladder entered higher (D8): the default for
    `source:` books, or a choice?**
    *Recommend:* the default. An adaptation that strays far from its source
    builds the upper rungs itself, as an original does.
14. **Bibles as facts, not essays (D2)?** (Registry and ledger rows, a few
    lines of each character speaking, terse notes only for what resists
    rows.)
    *Recommend:* yes. Same reasoning as the briefs: facts, yes; staging and
    interpretation, no.
15. **The two-writers test as the definition of a finished plan (D2)?**
    *Recommend:* yes, as the question each stage's review asks. It's
    judged by the author, with Storyforge listing the gaps it can see
    (unsettled reveals, ambiguous relationships, unanswered world rules).

**Voiceprint**

16. **One voiceprint per author, in its own repo, pointed to by each book
    (B0)?** (Decided, Ben 2026-11-08.)
17. **Which public-domain author is Storyforge's reference voiceprint
    (B7)?**
    *Recommend:* Edith Wharton (*The Age of Innocence*, with *The House of
    Mirth* held out), with Austen as the alternative. Verne's two
    translations serve as the mixed-voice fixture, not the reference.
18. **bennorris.com as the first author corpus, and which sections?**
    *Recommend:* yes, in a private `ben-voice` repo, after the reference
    voiceprint passes its tests. Essays and longer posts first. Leave out
    link posts and short notes, which carry less voice and would skew the
    fingerprint.

**Wrath Like Smoke**

19. **Redraft Wrath as the pilot for the adaptation track and sessions?**
    *Recommend:* yes, once the voice is found. Its source map and
    interpretation decisions exist, and the current draft is the comparison
    for the voice suite.
20. **Which influences and narrator stance start the voice samples?**
    *Recommend:* Ben names them. If he'd rather react first, round one is
    four contrasting stances on one scene.
