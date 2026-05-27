# Story-power scorecard rubric

Eight research-grounded craft axes for evaluating story design at the
pitch tier (logline + synopsis + theme + optional spine/architecture),
BEFORE prose is written. Answers the question: *if this story were
rendered with adequate prose, is it built to last?*

This is the third scoring layer, distinct from:
- **Craft scoring** (25 principles): prose-level, post-draft.
- **Structural validation:** mechanical CSV checks on architecture.
- **Story-power scorecard (this rubric):** narrative-design level, on
  the pitch artifacts.

## The eight axes

Each axis: 1-10 scale, with research grounding and signals.

### 1. Specificity & concreteness
Memory and stickiness research (Heath & Heath, *Made to Stick*;
Bartlett on memory reconstruction). Concrete imagery is retained;
abstractions are not.

- **High signals:** named proper nouns for roles/places/objects;
  concrete signature images that compress the world; sensory beats;
  specific stakes ("the previous archivist was erased" rather than
  "consequences will follow").
- **Low signals:** genre-shorthand abstractions ("reality fractures,"
  "the kingdom hangs in the balance"); unnamed institutions; vague
  verbs ("things change," "his world is upended").

### 2. Emotional resonance
Keith Oatley and colleagues on fiction-and-emotion; emotional
simulation as the mechanism by which fiction transfers experience.

- **High signals:** clearly identifiable emotional architecture
  (longing, dread, grief, devotion); a relationship the reader can
  ache for; emotional stakes that are *felt*, not just described.
- **Low signals:** emotion described in abstract registers
  ("conflicts arise," "their bond grows"); the synopsis reads as
  intellectual rather than felt.

### 3. Character identification
Jonathan Cohen on identification — readers stay with stories where
they can adopt the protagonist's perspective.

- **High signals:** clear protagonist with a legible ethical
  evolution; an active *want*, not just a reactive *fear*; a choice
  the reader can imagine themselves facing.
- **Low signals:** protagonist is passive or reactive; described
  entirely from outside; no interior want visible at the pitch level.

### 4. Stakes & dilemma
Narrative tension research; dramatic theory (McKee, Egri).

- **High signals:** genuinely impossible choice in which both options
  cost the protagonist something essential; stakes aligned with theme
  (the choice *is* the thematic question); mutual-destruction
  architecture.
- **Low signals:** one-sided stakes (loss to avoid, no gain to
  pursue); stakes that don't test the protagonist's values; stakes
  solvable by cleverness rather than choice.

### 5. Archetypal resonance
Brian Boyd, *On the Origin of Stories* (evolutionary literary
studies); Campbell-derived pattern recognition; Joseph Carroll on
consilient literary study.

- **High signals:** the story sits in a deep cultural groove
  (love/death/identity/transformation/sacrifice/forbidden knowledge).
  Readers recognize the shape without knowing why.
- **Low signals:** novel-without-resonance — clever premise without
  an underlying mythic shape; or so derivative that the archetype is
  the entirety.

### 6. Thematic depth
Rereadability and book-club longevity; reception studies on which
books are argued about for years.

- **High signals:** multiple thematic layers (epistemic, ethical,
  political, spiritual, aesthetic) that don't reduce to a single
  moral. *Recursive* structure where form mirrors content.
- **Low signals:** a single takeaway moral; theme is decorative
  rather than load-bearing; theme is stated rather than enacted.

### 7. Surprise & genre subversion
Patrick Colm Hogan on narrative cognition; pattern-violation as a
driver of attention and memory.

- **High signals:** the story honors a familiar genre shape and then
  inverts a load-bearing piece of it. The inversion lives at the
  level of *meaning*, not just plot.
- **Low signals:** pure genre fulfillment with no inversion; or
  shock-twist plotting where the surprise carries no thematic stake.

### 8. Moral weight
Moral foundations theory (Haidt-adjacent); narrative ethics (Wayne
Booth, *The Company We Keep*).

- **High signals:** the protagonist's choice has consequences beyond
  the personal — indicts a system, names a real ethical question,
  makes readers argue with friends.
- **Low signals:** choice is private and consequence-free; ethical
  mass is asserted rather than dramatized.

## Act-shape mode: per-act application + structural axes

When `reference/story-summary.md` has all three labeled paragraphs under
`## Act-shape`, the scorecard runs in **act-shape mode**: it re-applies
the eight pitch axes above to each act independently AND adds four
cross-act structural axes that only become meaningful at this
resolution.

### Layer 1: per-act 8-axis matrix

The same eight axes above, scored independently for Act 1, Act 2, and
Act 3. Output is a 3×8 matrix. The unit of analysis changes (one act at
a time, not the whole synopsis); the signals are the same.

**Why this is valuable:** the holistic synopsis score hides act-level
drift. If Act 2 scores 7 on emotional resonance while Acts 1 and 3
both score 9, that's a precise diagnostic ("the middle is going
intellectual") the holistic score cannot produce.

### Layer 2: four cross-act structural axes

These axes measure *relationships between acts*. They only make sense
at the act-shape resolution and carry a weight of 1.5 in
`structural-axes.csv`. No act-shape-level composite is computed today;
the per-axis scores stand on their own and feed the cross-act
diagnostic.

The 1.5x weight reflects the rubric's argument that turning-point
clarity and causal integrity are foundational in a way that would hide
damage if averaged flat. If a future revision introduces a composite
that consumes those weights, this comment is the place to point at it.

#### A. Causal integrity (1.5x)
Brian Boyd on causal coherence in narrative; Bruner on narrative
thought; reader-memory research showing causally connected events
are recalled and rated higher than sequential events.

- **Question:** Does each act *cause* the next, or are they merely sequential?
- **High signals:** Each act's closing state is the proximate cause of
  the next act's opening conditions; obstacles in later acts trace
  back to setup choices in earlier acts.
- **Low signals:** Acts could be reshuffled without breaking the
  story; transitions feel like temporal jumps rather than
  consequential turns.

#### B. Turning-point clarity (1.5x)
Lajos Egri, *The Art of Dramatic Writing*; Robert McKee on dramatic
structure; empirical work on plot-point recognition and reader
engagement.

- **Question:** Do the Act 1 turn, midpoint, and Act 2 closer actually
  *turn* — do they redirect the story rather than merely escalate it?
- **High signals:** Each turn changes the protagonist's understanding
  of their situation; the midpoint inverts what the story has been
  about; Act 2's closer compels Act 3 rather than just setting it up.
- **Low signals:** "Turns" are just increases in intensity; the
  midpoint is a stakes-raise rather than a reversal; Act 3 begins
  because the page count demands it.

#### C. Arc gradient (1.5x)
Jane Smiley, *Thirteen Ways of Looking at the Novel*; character-arc
research from the screenwriting tradition; Joseph Carroll on
protagonist transformation as load-bearing structure.

- **Question:** Does the protagonist change *measurably across acts*,
  not just start to end?
- **High signals:** Each act ends with the protagonist in a state
  distinct from the previous act's end-state; their values,
  knowledge, or relational stance moves between acts; the change
  forms a gradient, not a single delta.
- **Low signals:** Protagonist's interior state is essentially
  constant through Act 2; or the change is a single jump rather
  than a curve.

#### D. Promise & payoff (1.5x)
Stanley Fish on reader satisfaction; Chekhov's gun as empirical
reader-response observation; theatrical and screenwriting traditions
on planted/paid elements.

- **Question:** Are Act 1 setups redeemed in Act 3?
- **High signals:** Specific elements introduced in Act 1 (objects,
  lines, motifs, secondary characters) acquire new meaning or cost
  in Act 3; the closing image refers to the opening; promises the
  reader noticed get answers.
- **Low signals:** Act 1 introduces things that disappear; Act 3
  introduces resolutions out of nowhere; the closing image is
  unrelated to the opening.

### Independence vs. coupling

The structural axes (Layer 2) are scored **independently** of the
per-act matrix (Layer 1). A weak turning-point clarity score
*explains* a Layer 1 drop in stakes for that act, but does not
mechanically drag it down. Keeping them independent preserves
diagnostic precision — the structural score names the cause; the
matrix shows where the damage lands.

### Act-shape mode output

**`full` coaching** (LLM scores; CSVs land on disk):

```
working/scores/story-power/{timestamp}/
├── scorecard.csv          # pitch-mode 8-axis scores
├── per-act-matrix.csv     # 3 acts × 8 axes (act-shape only)
├── structural-axes.csv    # 4 structural axes (act-shape only)
└── diagnostic.md          # cross-axis + cross-act root causes
```

**`coach` coaching** (LLM scores; the per-act matrix and structural
sections are appended to the brief rather than written as separate
CSVs):

```
working/scores/story-power/{timestamp}/
└── coaching-brief.md      # pitch axes + per-act matrix + structural
                           # axes + cross-act diagnostic, all inline
```

**`strict` coaching** (no LLM; the self-scoring checklist gets the
per-act + structural blanks when act-shape is populated):

```
working/scores/story-power/{timestamp}/
└── self-scoring-checklist.md  # 8 pitch axes + 24 per-act blanks +
                               # 4 structural axes
```

## Spine mode: per-event matrix + whole-spine axes

When `reference/spine.csv` exists, the scorecard also runs in
**spine mode**. The spine is an event list — its job is to make the
backbone of the story legible at a glance. Most of the eight pitch
axes (emotional resonance, character identification, surprise) cannot
be assessed from a single event summary; spine mode therefore uses
its own axes.

Spine mode is **independent of act-shape mode**. Both can run in
either order on the same artifacts; the spine's findings can drive
architecture revisions without requiring act-shape to be present. The
one act-shape coupling is the `spine_act_shape_alignment` Layer 2
axis, which scores N/A (and the LLM is instructed to mark it so) when
act-shape is empty.

### Layer 1: per-event 3-axis matrix

Three axes scored per spine event (8 events × 3 axes = 24 cells for
a typical spine).

#### A. Function / summary alignment (1.0x)
Dramatic-structure theory (Egri, McKee) — each structural function is
a specific job (inciting incident, midpoint reversal, climax setup)
that the event either does or doesn't deliver.

- **Question:** Does the event's `summary` actually deliver on what
  its `function` claims?
- **High signals:** Function says "Act 1 turning point" and the
  summary names a specific reversal of the protagonist's situation;
  function says "midpoint reversal" and the summary inverts the
  story's premise; function says "climax" and the summary delivers
  the impossible choice.
- **Low signals:** Function says "turning point" but summary
  describes more rising action; function and summary describe
  different events.

#### B. Concreteness (1.0x)
Same memory/stickiness research as the pitch axis (Heath &amp; Heath;
Bartlett). Spine summaries should pick out specific beats, not gesture
at categories of beat.

- **Question:** Is the summary a *specific beat* or a *vague gesture*?
- **High signals:** Named places/objects/actions; specific cognitive
  shifts; verbs that pick out a particular moment.
- **Low signals:** Genre-shorthand verbs ("things escalate"); unnamed
  threats; conceptual claims that could describe many possible events.
- **Function-appropriate floor:** Some events are inherently
  conceptual. A midpoint reversal that's an epistemological inversion
  will be more abstract than a meeting event. The scoring prompt
  weights concreteness expectations by function class:
  - **Concrete-event functions** (inciting incident, Act 1 turn,
    Act 2 turn, climax setup, climax, resolution, denouement) —
    expect concreteness ≥ 8 for a strong score.
  - **Conceptual-shift functions** (midpoint reversal, revelation,
    discovery, recognition) — expect concreteness ≥ 7; a 7 here is
    at-ceiling for the function rather than a defect.

#### C. Causal handoff (1.5x)
Brian Boyd on causal coherence; Bruner's narrative-thought work;
reader memory research showing causally connected events are recalled
more reliably than sequential ones. **This axis is unique to spine
mode.** The pitch (synopsis) and act-shape (narrative paragraphs)
inherit causal feel from prose flow; a spine, being an event list,
must make causation explicit — and this is exactly where defects
hide that no other rubric layer catches.

- **Question:** Does this event's outcome cause the next event's setup?
- **High signals:** The summary ends on a clause that *names the
  cause* of the next event's opening conditions; the reader does not
  have to invent the bridge.
- **Low signals:** The summary describes the event in isolation;
  transitions feel like temporal jumps; the next event's setup appears
  "imported" rather than caused.
- **N/A for the final event** in the spine (no next event).
- **Act-bridge handoffs** (the last event of one act → the first event
  of the next) are flagged prominently in the diagnostic; they are
  load-bearing and worth weighting more in revision decisions even
  when the score itself is not re-weighted.

The 1.5x weight reflects this axis's load-bearing role at the spine
resolution — defects here translate directly to "the story doesn't
hang together" without any single event seeming weak.

### Layer 2: five whole-spine axes

Scored once over the spine as a whole, not per event.

#### D. Function coverage (1.5x)
Are all required structural beats present, in the right acts?

- **3-act expectation:** Act 1 (inciting + turning point) → Act 2
  (rising action + midpoint + turning point) → Act 3 (climax setup +
  climax + resolution).
- **4- or 5-act structures:** infer required functions from the
  project's stated act structure.
- **High signals:** Every required function present; events are in
  the right acts.
- **Low signals:** Missing midpoint; climax in wrong act; multiple
  events sharing the same function without justification.

#### E. Escalation curve (1.5x)
- **Question:** Do stakes visibly rise across events?
- **High signals:** Each event's stakes are visibly higher than the
  previous; midpoint changes the *nature* of the threat (not just
  intensity); Act 3 carries the highest stakes.
- **Low signals:** Middle plateau; climax stakes similar to Act 2's;
  resolution event with stakes equal to or lower than the climax setup.

#### F. Arc visibility (1.0x)
- **Question:** Can the protagonist's change be traced across events?
- **High signals:** Each event implies (or names) a state-change in
  the protagonist; the protagonist's *want* is visible in at least
  one summary; the resolution's protagonist is recognizably different
  from the inciting-incident's.
- **Low signals:** Spine reads as plot-only; protagonist appears as
  a passive grammatical subject; no event names the want.

#### G. Thematic distribution (1.0x)
- **Question:** Does the theme operate across multiple events, or
  only at the climax?
- **High signals:** Theme is enacted across 3+ events; the practice
  / belief / question the theme names appears in event summaries
  beyond the climax.
- **Low signals:** Theme is climax-localized; spine reads as plot
  scaffolding with thematic intent grafted onto the resolution.

#### H. Spine ↔ act-shape alignment (1.0x)
- **Question:** If an act-shape exists, do spine events map cleanly
  to act-shape paragraphs?
- **High signals:** Every spine event has a clear correspondence in
  an act-shape paragraph; every act-shape beat has a spine event; no
  orphans on either side.
- **Low signals:** Spine events that don't appear in the act-shape;
  act-shape beats with no spine event; multiple spine events crammed
  into one act-shape paragraph with no clear breakdown.
- **N/A when act-shape is empty** — skip cleanly rather than penalize.

### Weak-handoff threshold

Causal-handoff scores **below 8** are flagged as weak in the
diagnostic. The threshold reflects that 7 is "strong with specific
gaps" — at the spine resolution where causal handoff is the
load-bearing axis, "strong with specific gaps" is a revision target,
not an acceptance.

### Diagnostic-as-action

Spine mode's diagnostic must propose **specific clause-level fixes**,
not just identify weak axes. For the highest-leverage weak handoff,
the LLM proposes a one-clause bridge the author could add to the
upstream event's summary. The Ashes example below shows the pattern:
a 5-15 word addition lifted the causal handoff average from 7.4 to
8.4 across the spine.

### Spine mode output

**`full` coaching:**

```
working/scores/story-power/{timestamp}/
├── scorecard.csv             # pitch-mode 8-axis scores
├── per-event-matrix.csv      # spine events × 3 axes (spine only)
├── whole-spine-axes.csv      # 5 spine axes (spine only)
└── diagnostic.md             # cross-axis + cross-event + spine
                              # weak-handoff list + proposed fix
```

**`coach` coaching:** spine sections append to `coaching-brief.md`.
**`strict` coaching:** extends `self-scoring-checklist.md` with
per-event blanks + 5 whole-spine axis blanks.

### Ashes-in-the-Archive worked example

Real scoring from the Ashes spine (illustrative — your numbers will
reflect your project, not this one).

**Initial scoring (pre-fix).** Per-event Layer 1 matrix:

| Event | Alignment | Concreteness | Causal handoff |
|---|---|---|---|
| ev-portrait-refuses | 9 | 8 | 7 |
| ev-erased-archivist | 9 | 9 | 8 |
| ev-failed-portraits | 8 | 8 | **6** |
| ev-archive-finalizes | 9 | 7 | 8 |
| ev-archive-moves | 9 | 7 | 7 |
| ev-deepest-chamber | 9 | 9 | 7 |
| ev-vault-refusal | 10 | 9 | 9 |
| ev-fracture | 9 | 7 | n/a |
| **Per-axis avg** | **9.0** | **8.0** | **7.4** |

Whole-spine Layer 2: function coverage 9, escalation 9, arc
visibility 8, thematic distribution 9, act-shape alignment 9.
Average 8.8.

**Diagnostic surfaced:** causal handoff (7.4) is the weakest axis.
Four transitions below the 8-threshold (the three at 7, plus the one
at 6). Highest-leverage move: add a one-clause causal bridge to
ev-failed-portraits.

**Post-fix scoring** after three short (5-15 word) bridges:

| | Was | Now |
|---|---|---|
| Alignment avg | 9.0 | 9.0 |
| Concreteness avg | 8.0 | 8.1 |
| Causal handoff avg | **7.4** | **8.4** |

The diagnostic prediction held exactly: the targeted axis lifted ~1
point on minimal effort, with a side-effect bump in concreteness on
one event.

## Architecture mode: per-scene matrix + whole-architecture axes

When `reference/architecture.csv` exists, the scorecard runs in
**architecture mode**. The architecture is the only artifact in the
project with **structured fields per row** beyond a prose summary:
`action_sequel`, `emotional_arc`, `value_at_stake`, `value_shift`,
`turning_point`. These are structured craft data that no other layer
has, and no other scoring mode can check.

Architecture mode is **independent of pitch, act-shape, and spine
modes**. All four can run on the same project in any order. The
coupling that matters is *upstream* — the per-scene `spine_event`
column references `spine.csv:id`, and the architecture should align
with the act-shape (the spine_act_shape_alignment axis in spine mode
checks the inverse).

### Layer 1: per-scene 2-axis matrix

Two axes scored per architecture scene (15 scenes × 2 axes = 30 cells
for a mid-novel architecture).

#### A. Spine-event service (1.0x)
Dramatic-structure theory; scene-function research (McKee, Snyder).

- **Question:** Does this scene's summary deliver on what its assigned
  `spine_event` needs at this beat?
- **High signals:** The scene clearly advances the spine event; the
  summary names the specific beat the event requires; if removed, the
  spine event would be under-served.
- **Low signals:** Scene is tangential to its assigned event; the same
  scene could serve a different event better; the scene is doing
  relational or thematic work that doesn't map onto the assigned spine
  event's function.

#### B. Field coherence (1.5x)
Internal-consistency principles from structured-information theory;
craft tradition on scene-element alignment.

- **Question:** Do the scene's structured fields (`action_sequel`,
  `emotional_arc`, `value_at_stake`, `value_shift`, `turning_point`)
  cohere with each other and with the summary?
- **High signals:** All fields tell the same story — the emotional
  arc matches the value shift, the turning point matches the
  action/sequel mode, the summary delivers what the fields claim.
- **Low signals:** Field contradicts summary (`turning_point:
  revelation` but the summary describes pure action with no
  realization); fields contradict each other (`value_shift: +/+` with
  a `friction to rupture` emotional arc); summary has been expanded
  with new beats but the supporting fields didn't update to match.

The 1.5x weight reflects this axis's unique-and-load-bearing role
at the architecture resolution. **No other artifact has structured
fields**, so no other scoring mode can detect summary↔field drift.
A handful of field-coherence patterns are deterministic regex/keyword
matches (turning-point named as recognition without a recognition
verb in the summary; action_sequel='action' with no concrete action
verbs; net-positive value_shift with rupture/loss language in the
emotional_arc). The deterministic pre-pass catches those; the LLM
refines and contextualizes the rest.

### Layer 2: five whole-architecture axes

#### C. Action/sequel rhythm (1.5x — register-aware)
Dwight Swain, *Techniques of the Selling Writer*; McKee on pacing.

- **Question:** Is the `action_sequel` distribution varied and
  intentional, or monotonous?
- **High signals:** Action and sequel scenes alternate with deliberate
  variation; ratio matches the project's declared register.
- **Low signals:** Long runs of one type; ratio mismatched with the
  declared register.
- **Register awareness:** A 70/30 action-to-sequel ratio is correct
  for a thriller but defective for a decompressed atmospheric story.
  The scoring prompt is given the project's `project.register` value
  from `storyforge.yaml` and scores against that register's expected
  ratio band. Defaults to `balanced` (40-60% action acceptable) when
  no register is declared.

#### D. Spine coverage balance (1.0x)
- **Question:** Does each spine event have proportionate scene coverage?
- **High signals:** Climax / midpoint events have enough scenes to
  deliver their work; setup-heavy or payoff-heavy distributions are
  appropriate to the declared register.
- **Low signals:** A single scene loaded with too many beats to
  deliver one spine event; a spine event over-served at the cost of
  late-act compression.

#### E. Cumulative arc gradient (1.0x)
Character-arc research (Smiley, Carroll), applied scene-by-scene.

- **Question:** Can the protagonist's change be traced *scene by
  scene*, or are there flat zones or repeated arcs?
- **High signals:** `emotional_arc` values shift meaningfully across
  scenes; no consecutive scenes share the same arc unless intentional.
- **Low signals:** The same `emotional_arc` repeats three or more
  times (e.g., "investigation to recognition" appearing across the
  discovery scenes); flat plateaus in the middle of the architecture.

#### F. Scene-level causal chain (1.5x)
Same Boyd/Bruner causal-coherence research as spine mode, applied
at finer resolution.

- **Question:** Does each scene cause the next? Or do scenes feel
  like a sequenced list?
- **High signals:** Scene N's outcome is the proximate cause of scene
  N+1's opening conditions; spine-level bridges are *delivered* by
  actual scenes, not just implied.
- **Low signals:** Adjacent scenes feel like jump-cuts; the spine has
  causal bridges that no architecture scene enacts.

#### G. Promise & payoff (1.0x)
- **Question:** Are Act 1 scene-level setups (objects, lines, motifs)
  paid off in Act 3 scenes?
- **High signals:** Specific Act 1 scene elements recur with new
  meaning in Act 3; closing image refers to opening image.
- **Low signals:** Act 1 scenes plant elements that disappear; Act 3
  scenes introduce resolutions out of nowhere.

### Diagnostic-as-action

Architecture mode's diagnostic must propose **specific field-level
updates AND scene insertions**, not just identify weak axes.

- **Field-update proposals:** for scenes with low field coherence,
  the diagnostic names the specific field and the proposed new value
  (e.g., "a07 emotional_arc → 'search to recognition and recurrence'").
- **Scene-insertion proposals:** for spine bridges that no
  architecture scene enacts, the diagnostic proposes a new sequel
  scene with a full definition: id, spine_event, action_sequel,
  emotional_arc, value_at_stake, value_shift, turning_point, and a
  one-sentence summary.

### Architecture mode output

**`full` coaching:**

```
working/scores/story-power/{timestamp}/
├── scorecard.csv                 # pitch-mode 8-axis scores
├── per-scene-matrix.csv          # 2 axes × N scenes (architecture only)
├── whole-architecture-axes.csv   # 5 architecture axes (only)
└── diagnostic.md                 # cross-axis + cross-scene + field-update
                                  # and scene-insertion proposals
```

**`coach` coaching:** architecture sections append to
`coaching-brief.md`.
**`strict` coaching:** extends `self-scoring-checklist.md` with
per-scene blanks (id + 2 axes) + 5 whole-architecture axis blanks.

### Worked example: Ashes-in-the-Archive (illustrative)

Real scoring from a 15-scene architecture before-and-after field
updates plus one scene insertion (numbers are one reviewer's read,
not a target).

Per-scene Layer 1 averages: service 9.0, **field coherence 8.1**
(three scenes — a07, a19, a21 — at 7).

Whole-architecture Layer 2:
- Action/sequel rhythm: 7 (11 action / 4 sequel = 73% action — too
  heavy for a project declared as `atmospheric`)
- Spine coverage balance: 8
- Cumulative arc gradient: 8
- Scene-level causal chain: 7 (one weak handoff a10 → a15)
- Promise & payoff: 9

**Two targeted moves the diagnostic proposed:**
- Update `emotional_arc` on a07/a19/a21 to match their expanded
  summaries (each field had drifted during spine→architecture
  propagation).
- Add a new sequel scene `a12-tracing-the-pattern` between a10 and
  a15 to deliver the spine's bridge.

**Post-fix:** coherence 8.1 → 8.3; causal chain 7 → 9; action/sequel
rhythm 7 → 8 (11:5 = 69% action). The new scene lifted *two* Layer 2
axes simultaneously (causal chain + action/sequel rhythm) — a single
high-leverage move addressing both the spine bridge and the register
imbalance.

The takeaway for the rubric: field coherence is the axis no other
mode catches, and a single well-chosen scene insertion can lift
multiple Layer 2 axes when it both serves a spine bridge and corrects
a rhythm imbalance.

## Scene-map mode: per-scene matrix + whole-map axes

When `reference/scenes.csv` exists, the scorecard runs in **scene-map
mode**. The scene map is the manuscript's full sequence — every scene
including interstitials that don't appear in `architecture.csv`. Each
row carries continuity metadata (pov, location, timeline_day,
time_of_day, type, word_count, target_words, architecture_scene)
that no upstream artifact has.

Scene-map mode is **independent of the other modes**. All five can
run on the same project. The coupling that matters is upstream — the
per-row `architecture_scene` column references `architecture.csv:id`
when present, and the scene map should *cover* every architecture
anchor with at least one mapped scene.

### Layer 1: per-scene 2-axis matrix

Two axes scored per scene-map row (the load shifts to Layer 2 because
many scene-map rows are interstitials with thin per-row signal).

#### A. Architecture coverage (1.0x)
- **Question (mapped scenes):** Does this scene's summary deliver
  something the linked `architecture_scene` requires at this beat?
- **Question (interstitial scenes — empty `architecture_scene`):**
  Does this scene earn its space — provides a transition, a
  character beat, a world detail, a pacing breath — or is it
  load-bearing nothing?
- **High signals:** A mapped scene names the specific beat the
  architecture row promised; an interstitial does *one* thing
  cleanly (rest beat, transition signal, character interior).
- **Low signals:** Mapped scene's summary describes a beat the
  architecture row doesn't ask for; interstitial summary lists
  multiple weak purposes ("a transition + some character + some
  setup") — diffused, not deliberate.

#### B. Continuity coherence (1.5x — the unique-and-load-bearing axis)
Continuity research from screenwriting tradition (Snyder, Field) and
adjacent-shot theory in film editing — the audience holds onto pov,
location, and time across cuts; unintentional jumps cost
comprehension.

- **Question:** Does this scene's pov / location / timeline_day /
  time_of_day flow coherently from the preceding scene (and into
  the next)?
- **High signals:** POV transitions are signaled by a clear handoff
  in the prior scene's closing; timeline jumps are flagged via the
  `type` field (`flashback` / `interlude`); location changes have a
  travel beat or scene break.
- **Low signals:** Adjacent scenes share pov + location + day but
  feel like cuts; pov changes appear mid-sequence without setup;
  timeline_day goes backward and the scene type is regular.

The 1.5x weight reflects this axis's unique-and-load-bearing role:
**no other scoring mode catches adjacency.** Spine causal handoff
checks event→event causation in summaries; architecture field
coherence checks within-scene field alignment. Only scene-map mode
checks scene→scene flow on the continuity metadata.

### Layer 2: five whole-map axes

#### C. Coverage completeness (1.5x)
- **Question:** Does every `architecture.csv` scene have at least
  one mapped scene serving it?
- **High signals:** Each architecture anchor has 1-3 scene-map rows
  delivering it; the climax and resolution anchors have proportionate
  coverage.
- **Low signals:** An architecture scene has zero scene-map rows
  pointing to it (gap); one anchor has 8+ rows while neighbors have
  none (compression imbalance).

#### D. POV rotation (1.0x)
- **Question:** Is POV use intentional? Each POV shift should earn
  its cost.
- **High signals:** Single-POV manuscripts maintain consistency;
  multi-POV manuscripts establish each POV in early act 1 and rotate
  on structural beats (turning points, midpoint).
- **Low signals:** A POV appears once and never returns; POV jumps
  every other scene without a structural rationale.

#### E. Pacing distribution (1.5x)
- **Question:** Do word counts (or page counts in graphic-novel
  mode) build to a meaningful distribution against `target_words`?
- **High signals:** Scene lengths vary with function (intimate
  scenes shorter than action set-pieces); totals track the project's
  declared register's expected page count.
- **Low signals:** Every scene is the same length (no rhythm);
  totals are far from the register's expected band; one scene is
  3× the average without justification.

#### F. Timeline flow (1.0x)
- **Question:** Does timeline_day progression hold? Are flashbacks
  and time skips signposted via `type`?
- **High signals:** Linear runs are monotonic on timeline_day;
  flashbacks have `type=flashback`; time skips between scenes are
  acknowledged in adjacent summaries.
- **Low signals:** timeline_day jumps without type or summary
  reference; multiple consecutive scenes share a day but compress
  unrealistically; long gaps with no continuity bridging.

#### G. Interstitial economy (1.0x)
- **Question:** Are unmapped scenes (no `architecture_scene`)
  earning their space?
- **High signals:** Interstitials cluster around turning points (a
  rest beat after the midpoint, a transition before the climax
  setup); each does one identifiable thing.
- **Low signals:** Interstitial scenes outnumber mapped scenes by
  2:1 or more; an interstitial is doing what an architecture scene
  should be doing (and probably belongs *in* architecture).

### Diagnostic-as-action

Scene-map mode's diagnostic proposes **specific scene operations**,
not just identifies weak axes:

- **Merge operation:** scenes X and Y cover the same architecture
  beat — propose merging.
- **Split operation:** scene X has multiple distinct beats with
  different pov/turning-point — propose splitting.
- **Insert operation:** an architecture scene has no coverage —
  propose a new scene-map row.
- **Reorder operation:** continuity flows better if X and Y swap.
- **Promote operation:** an interstitial scene is doing
  architecture-level work — promote it to architecture.csv.

Each operation names the scenes by id and proposes the structural
change, leaving the prose work to the author.

### Scene-map mode output

**`full` coaching:**

```
working/scores/story-power/{timestamp}/
├── scorecard.csv                 # pitch
├── per-act-matrix.csv / structural-axes.csv     # act-shape
├── per-event-matrix.csv / whole-spine-axes.csv  # spine
├── per-scene-matrix.csv / whole-architecture-axes.csv  # architecture
├── per-scene-map-matrix.csv      # scene-map Layer 1 (NEW)
├── whole-scene-map-axes.csv      # scene-map Layer 2 (NEW)
└── diagnostic.md                 # all five tiers
```

**`coach` coaching:** scene-map sections append to
`coaching-brief.md`.
**`strict` coaching:** extends `self-scoring-checklist.md` with
per-scene-map blanks + 5 whole-map axis blanks.

### Deterministic continuity pre-pass

Three high-confidence checks the pre-pass runs against adjacent
scene pairs (parallel to architecture's field-coherence pre-pass):

1. `timeline_day` decreased from scene N-1 to scene N with
   `type != 'flashback'` (and not blank): high severity.
2. `architecture_scene` references an id not found in
   `architecture.csv`: high severity (broken cross-reference).
3. `word_count` deviates from `target_words` by ≥ 2× in either
   direction (and `target_words` non-zero): medium severity.

The LLM seeds its continuity_coherence scoring with these findings.
Higher-noise continuity cases (subtle pov-rotation, mid-act-day
compression) are left to the LLM.

## Briefs mode: per-brief matrix + whole-briefs axes

When `reference/scene-briefs.csv` exists and has at least one populated
row, the scorecard runs in **briefs mode**. A brief is the drafting
contract for one scene — the scene-engine fields (goal, conflict,
outcome, crisis, decision) plus information state (knowledge_in /
knowledge_out), execution beats (key_actions, key_dialogue, emotions),
recurring vehicles (motifs), under-the-line direction (subtext), and
the scene-graph edge (continuity_deps).

Briefs mode is **independent of the other modes**. All six can run on
the same project. The coupling that matters is upstream — `continuity_deps`
references `scenes.csv:id`, and brief rows are keyed by scene id.

### Layer 1: per-brief 2-axis matrix

Two axes scored per brief row. The asymmetric weighting (1.5x on
scene-engine integrity) reflects that this axis is the entire reason
the brief format exists; concreteness is a secondary craft floor.

#### A. Scene-engine integrity (1.5x — the load-bearing axis)
Swain's motivation-reaction unit and Weiland's scene/sequel structure
both insist that a scene is the smallest unit where a *character with
a goal* meets *specific opposition* and arrives at an *outcome* that
forces a *crisis* answered by a *decision*. Briefs that skip any link
in this chain produce scenes that feel like episodes rather than
scenes-as-engines.

- **Question:** Do `goal → conflict → outcome → crisis → decision`
  cohere as a single causal sequence for this scene?
- **High signals:** Goal names a concrete objective; conflict names
  the specific opposition (person, force, internal block); outcome
  matches the allowed enum (`yes`, `no`, `yes-but`, `no-and`) and
  follows from the goal/conflict; crisis articulates a real dilemma
  (best-bad-choice or irreconcilable goods); decision names what the
  character actively chooses in response.
- **Low signals:** Goal is abstract ("understand herself"); conflict
  is missing or vague ("internal struggle"); outcome doesn't match
  what the goal/conflict set up; crisis is restated outcome rather
  than a dilemma; decision is passive ("she lets it happen").

#### B. Concreteness (1.0x)
- **Question:** Are the brief's fields specific drafting *instructions*,
  or do they restate the scene's summary in different words?
- **High signals:** key_actions names specific beats ("Mira opens the
  ledger to page 47 before her father stops her"); key_dialogue
  carries an actual line; emotions traces a sequence ("relief → dread
  → resignation").
- **Low signals:** key_actions paraphrases the scene summary;
  key_dialogue is "Mira and her father argue"; emotions is a single
  word ("tense").

### Layer 2: five whole-briefs axes

#### C. Outcome distribution (1.5x)
- **Question:** Across all briefs, does the outcome enum vary in a
  way that builds escalation, or does the same outcome repeat in
  streaks?
- **High signals:** Outcomes spread across `yes` / `no` / `yes-but` /
  `no-and`; the `no-and` outcomes cluster around turning points;
  Act 2's midpoint has a `no-and` (Save the Cat all-is-lost).
- **Low signals:** A streak of 4+ consecutive `yes` outcomes (no
  stakes); a streak of 4+ `no` outcomes (the protagonist loses
  monotonically and stops feeling agentic); `yes-but` and `no-and`
  never appear (the story has no complications).

#### D. Knowledge-flow continuity (1.5x — the unique-and-load-bearing axis)
Briefs are the only artifact tracking per-scene knowledge state.
Architecture tracks structure; scene-map tracks continuity metadata.
Only briefs answer "when did the protagonist learn X, and from where?"

- **Question:** Does `knowledge_out` of an upstream scene cover the
  `knowledge_in` of a downstream scene that depends on it?
- **High signals:** Each scene's `knowledge_in` items appear in some
  ancestor scene's `knowledge_out`; new facts that appear mid-stream
  are introduced cleanly (knowledge_out grows by 0.5-1.5 items per
  scene); the protagonist's knowledge state is consistent across the
  manuscript.
- **Low signals:** A scene's `knowledge_in` ∋ a fact that no upstream
  `knowledge_out` provides (orphan knowledge); `knowledge_out`
  contracts across scenes (fact known then forgotten); a fact is
  re-introduced in scene K when it was already known in scene J<K.

The 1.5x weight reflects this axis's unique role: **no other scoring
mode catches knowledge orphans.** Field coherence checks scene-row
fields; scene-map checks continuity metadata; only briefs can check
fact provenance across the scene graph.

#### E. Crisis density (1.0x)
- **Question:** How often do briefs articulate a real *crisis* — a
  dilemma the POV character must choose through? Crisis is the
  most-skipped scene-engine field.
- **High signals:** ≥60% of briefs have a non-empty crisis field that
  names a true dilemma (best-bad-choice or irreconcilable goods);
  Act-structure crisis points (Act 1 climax, midpoint, Act 2 climax)
  have the strongest dilemmas.
- **Low signals:** <20% of briefs have a populated crisis field; the
  crisis field paraphrases the conflict ("the conflict gets harder");
  no crisis field invokes a value trade-off.

#### F. Subtext presence (1.0x)
- **Question:** How often is subtext articulated — "character says X
  but means Y; do not state Y directly"?
- **High signals:** ≥50% of dialogue-heavy briefs have a populated
  subtext field giving drafting direction; subtext recurs across
  scenes featuring the same character pair (an established subtext
  channel); subtext invokes the theme.
- **Low signals:** Subtext field is empty across most briefs; subtext
  is just a restatement of what the character is feeling; the same
  subtext line is reused across multiple briefs.

#### G. Motif recurrence (1.0x)
- **Question:** Do motifs (recurring images / symbols) appear across
  multiple briefs, or are most motifs one-shots?
- **High signals:** Most motifs declared in briefs appear in ≥3
  briefs; high-load motifs (the title image, the central object)
  appear in ≥5 briefs distributed across acts; motif arcs build
  (introduce → echo → recontextualize → resolve).
- **Low signals:** ≥50% of motifs declared in any brief appear in
  only one brief (singletons); motifs cluster in Act 1 and disappear;
  the title motif appears only at the open and close.

### Diagnostic-as-action

Briefs mode's diagnostic proposes **specific field updates**, not just
identifies weak axes:

- **Crisis field updates:** for briefs missing a real dilemma, propose
  concrete crisis text grounded in the goal/conflict.
- **Knowledge field updates:** for orphan-knowledge findings, propose
  adding the missing fact to an upstream `knowledge_out` *or* removing
  it from the downstream `knowledge_in`.
- **Subtext field updates:** for dialogue-heavy briefs missing subtext,
  propose a one-line subtext directive ("character says X but means
  Y; do not state Y directly").
- **Outcome distribution:** for streaks, propose flipping a brief's
  outcome from `yes` to `yes-but` to break the streak.

Each proposal names the scene id, the field, the proposed new value,
and (when available) the current value plus rationale.

### Briefs mode output

**`full` coaching:**

```
working/scores/story-power/{timestamp}/
├── scorecard.csv                 # pitch
├── per-act-matrix.csv / structural-axes.csv     # act-shape
├── per-event-matrix.csv / whole-spine-axes.csv  # spine
├── per-scene-matrix.csv / whole-architecture-axes.csv  # architecture
├── per-scene-map-matrix.csv / whole-scene-map-axes.csv # scene-map
├── per-brief-matrix.csv          # briefs Layer 1 (NEW)
├── whole-briefs-axes.csv         # briefs Layer 2 (NEW)
└── diagnostic.md                 # all six tiers
```

**`coach` coaching:** briefs sections append to `coaching-brief.md`.
**`strict` coaching:** extends `self-scoring-checklist.md` with
per-brief blanks + 5 whole-briefs axis blanks.

### Deterministic brief pre-pass

Five high-confidence checks the pre-pass runs against the briefs
corpus (parallel to scene-map's continuity pre-pass):

1. **Missing required field:** any of `goal`, `conflict`, `outcome`,
   `crisis`, `decision` is empty: high severity per missing field.
2. **Invalid outcome:** `outcome` is non-empty but not in
   `{yes, no, yes-but, no-and}`: high severity.
3. **Knowledge orphan:** a scene's `knowledge_in` ∋ a fact that no
   upstream brief's `knowledge_out` provides (walking the
   `continuity_deps` graph transitively when present, falling back
   to seq order otherwise): medium severity.
4. **Outcome streak:** 4+ consecutive briefs (by `scenes.csv` seq)
   with the same outcome enum: medium severity (low if the streak
   is `yes-but` — it's an escalation pattern, not stagnation).
5. **Motif singleton:** a motif declared in any brief appears in
   exactly one brief: low severity.

The LLM seeds its scene_engine_integrity, knowledge_flow_continuity,
and outcome_distribution scoring with these findings. Higher-noise
cases (subtext quality, crisis dilemma rigor) are left to the LLM.

## Cross-tier synthesis: patterns across tiers

When two or more story-power tiers ran successfully, the **cross-tier
meta-diagnostic** runs. It synthesizes patterns the individual tiers
cannot see — when two or more tiers flag related weaknesses, that's
a single underlying defect surfacing at multiple resolutions, and
the high-leverage move usually lives at the cross-tier level rather
than in any one tier.

Cross-tier synthesis is **not a new scoring layer.** It produces no
new axes and no new numeric scores. Its output is two things: a list
of deterministic patterns (the pre-pass found these), and an LLM
synthesis with concrete proposals (one paragraph naming the root
pattern + one high-leverage move + which downstream tier proposals
the move consolidates).

Cross-tier synthesis runs **independently of all other modes** — it
fires whenever at least two of {pitch, act-shape, spine,
architecture, scene-map, briefs} produced output.

**Cost-discipline gate:** the LLM synthesis call is skipped when
the deterministic pre-pass found zero patterns AND fewer than three
tiers ran. With nothing structurally interesting to synthesize and
only two tier outputs to compare, the LLM has insufficient
substrate; the deterministic patterns alone are the load-bearing
signal and the cost of the LLM call (~8K tokens) isn't worth the
return. On strict-mode runs, the LLM call is skipped unconditionally
— strict mode doesn't produce the markdown files the synthesis
would append to, so the cost would be wasted.

### Deterministic pre-pass patterns

Four high-confidence patterns the pre-pass detects from the
in-memory tier outputs:

1. **Lowest-axis recurrence.** When two or more tiers'
   `diagnostic['lowest_axis']` names share a common token
   (`concreteness`, `causal`, `coherence`, `arc`, `coverage`), the
   project's weakest dimension recurs at multiple resolutions. The
   author should suspect a single underlying defect rather than
   five independent symptoms. **Severity:** medium when 2 tiers
   share a token, high when ≥3.

2. **Scene-id overlap in proposals.** When multiple tiers'
   proposed-fixes lists (architecture's `proposed_field_updates`
   and `proposed_scene_insertions`, scene-map's
   `proposed_operations`, briefs's `proposed_brief_updates`)
   target the same `scene_id`, that scene is a multi-tier
   leverage point. Fixing it once may close findings at multiple
   resolutions. **Severity:** medium when a scene_id appears in
   2 tiers, high when ≥3.

3. **Field-coherence cascade.** When the architecture tier's
   `field_findings` AND the briefs tier's `brief_findings` AND/or
   the scene-map tier's `continuity_findings` all flag the same
   `scene_id`, that scene's defects span multiple structural
   layers. Fixing the upstream tier's row usually resolves the
   downstream tier's symptom. **Severity:** medium when 2 tiers
   flag the same id, high when ≥3.

4. **Project-level disposition.** When ≥4 of the six tiers score
   below their respective "strong" threshold (below 7 on the
   weighted composite for pitch, below 7 on the unweighted mean of
   the tier's whole-axis scores for the others), the project's
   structural-craft layer is underweight overall. The high-leverage
   move is to return to elaboration before continuing to drafting.
   **Severity:** high (project-wide).

These patterns are the load-bearing surface. They are detected
deterministically (no LLM call required) and always populate the
extension's `deterministic_patterns` field, even when the LLM
synthesis call fails.

### LLM synthesis

The pre-pass output is then handed to the LLM along with each
present tier's diagnostic (compact summary). The LLM produces:

- A one-paragraph **synthesis** naming the root pattern across
  tiers
- An optional **project_disposition** (e.g. "the structural-craft
  layer is consistently underweight; consider returning to
  elaboration before continuing to drafting")
- One **high_leverage_move** — the single action that would lift
  the most ground across tiers
- A list of **proposals**, each with a `target` (`scene:s10`,
  `spine_event:ev-3`, `tier:architecture`), a one-sentence
  `move`, optional `rationale` / `expected_lift` (e.g. "lifts
  act-shape emotional_resonance 6→8 and architecture
  field_coherence 7→9"), and optional `consolidates_tiers`
  naming which downstream tier proposals this move supersedes

### Cross-tier output

**`full` coaching:**

```
working/scores/story-power/{timestamp}/
├── scorecard.csv                              # pitch
├── per-act-matrix.csv / structural-axes.csv     # act-shape
├── per-event-matrix.csv / whole-spine-axes.csv  # spine
├── per-scene-matrix.csv / whole-architecture-axes.csv  # architecture
├── per-scene-map-matrix.csv / whole-scene-map-axes.csv # scene-map
├── per-brief-matrix.csv / whole-briefs-axes.csv # briefs
└── diagnostic.md                              # all six tiers + cross-tier synthesis at the END
```

**`coach` coaching:** Cross-tier section in `coaching-brief.md`,
framed as questions (the author decides).
**`strict` coaching:** Cross-tier patterns in
`self-scoring-checklist.md` as deterministic data only — no LLM
synthesis, no proposals.

### Diagnostic-as-action

The cross-tier diagnostic proposes **specific moves** with concrete
targets, not just identifies the patterns. Each proposal names:

- **Target** — a typed locus (`scene:s10`, `spine_event:ev-3`,
  `tier:briefs`)
- **Move** — one sentence: what to do
- **Expected lift** — which axes should rise, by how much
- **Consolidates** — which existing tier proposals this supersedes
  so the author knows what NOT to do downstream

A useful cross-tier diagnostic might read (illustrative): *"Three
tiers flagged Act 2 weakness — act-shape emotional_resonance
dropped 9 → 6, architecture scene_causal_chain held at 7, scene-map
continuity_coherence dipped at the s10 → s15 region. The single
root cause is most likely the spine's midpoint event being
underspecified; downstream tiers are reporting the cascade. Move:
return to spine.csv:ev-3 and tighten its function + summary. This
consolidates 6 of the 9 proposed-fixes across architecture / scene-
map / briefs in that region — defer those until the spine fix
ships."*

## Scoring bands

- **1-3:** Axis is essentially absent or actively damaged.
- **4-6:** Present but inert — named but not load-bearing.
- **7-8:** Strong; one or two specific gaps remain.
- **9:** Top-tier execution at the pitch level; minor refinement only.
- **10:** Reserve for prose-verified excellence. Synopsis-stage scores
  cap at ~9 on most axes.

## Composite weighting

Four axes predict *lasting* more strongly than the others and get a
1.5x weight in the composite score; the other four are 1.0x.

| Weight | Axes |
|---|---|
| 1.5x | Stakes & dilemma; Archetypal resonance; Thematic depth; Moral weight |
| 1.0x | Specificity; Emotional resonance; Character identification; Surprise |

Composite = `sum(score * weight) / sum(weights)`. Range stays 1-10.

## Output token budget

Per-tier `max_tokens` ceilings, codified in `scoring_story_power.py`:

| Tier | Ceiling | Why |
|---|---|---|
| Pitch | 4,096 | 8 axes × bounded rationale |
| Act-shape | 8,192 | 3 acts × 8 axes + 4 structural axes |
| Spine | 8,192 | 5-10 events × 3 axes + 5 whole-spine |
| Architecture | 32,768 | Per-scene axes scale with scene count |
| Scene-map | 32,768 | Per-scene axes scale with scene count |
| Briefs | 32,768 | Per-brief axes scale with brief count |

The per-row-heavy tiers (architecture, scene-map, briefs) emit
rationale that scales with project size. On real-sized manuscripts
(25+ architecture scenes, 60+ scene-map rows, 30+ briefs), an 8K
ceiling silently truncates the response mid-JSON; the parser then
fails with a generic "unparseable" error. 32K leaves substantial
headroom and is well under the per-model output cap (Opus 4.6: 128K,
Sonnet 4.6: 64K — see `api.MODEL_MAX_OUTPUT` for the source of truth).

When the LLM truncates anyway (unusually large project, a future
rubric that grew the prompt), the unparseable error message names
truncation explicitly via `stop_reason=max_tokens` — so the cause is
visible without grep-ing the raw log.

## Diagnostic output

The scorecard ALSO produces a `diagnostic.md` that surfaces cross-axis
root causes. Two axes both scoring 7 for the same underlying reason
(e.g., "protagonist described from outside but not from inside")
get a single high-leverage move proposed — one revision that lifts
both axes.

## Delta tracking

Each run compares to the previous run in `working/scores/story-power/`
and reports per-axis movement. Authors see whether a synopsis revision
actually moved the needle.

## Worked example: *Ashes in the Archive* (illustrative)

The example below is **illustrative**, not a benchmark. The scores are
one reviewer's read of a single synopsis used to demonstrate how the
rubric and composite weighting work — they are not a ceiling or a
target to beat. Your project's scores will reflect your project, not
this one.

Gothic speculative graphic novel. A Facekeeper falls for a woman no
portrait can hold and is ordered by the Archive to finish her into
stable record — or be unmade for refusing.

| Axis | Score | Key signals |
|---|---|---|
| Specificity & concreteness | 8 | Strong proper-noun world (Facekeeper, Mirelle Ash, the Archive); concrete signature images ("failed portraits crowding out the woman in his memory"). Drifts abstract at "quiet violences" and "in places." |
| Emotional resonance | 7 | Architectural emotion is rich; Mirelle is positioned more than felt at synopsis level. |
| Character identification | 7 | Clear ethical evolution; legible choice. Protagonist still described from outside — no interior want or fear visible. |
| Stakes & dilemma | 9 | Both options destroy a person; choice embodies theme. Gold-standard mutual-destruction architecture. |
| Archetypal resonance | 9 | Orpheus, Pygmalion-inverted, Faust, the iconoclast-vs-icon, the keeper-as-heretic. Deep groove. |
| Thematic depth | 9 | Five layers (epistemic, ethical, political, spiritual, aesthetic); recursive (portraiture-as-violence mirrors form). |
| Surprise / subversion | 8 | Inverts the procedural-mystery move — protagonist saves her not by solving her but by refusing to. |
| Moral weight | 9 | Choice indicts civilization itself, not just an institution. |

Composite (weighted): `(8 + 7 + 7 + 9*1.5 + 9*1.5 + 9*1.5 + 8 + 9*1.5) / 10 = 8.40`.

**Diagnostic for Ashes:** the two lower scores (emotional resonance,
character identification, both 7) shared a single root cause —
*protagonist rendered as practitioner but not as interior person*.
The diagnostic identified one move that would lift both 7s to 8s:
plant a single interior sensory line in the synopsis (e.g., "he can
still draw her face from memory, but every day a piece of the curve
of her mouth gets slightly more uncertain"). One sentence; two axes
lifted.

### Act-shape extension (illustrative)

Hypothetical scores when the same project is scored in act-shape
mode — illustrative numbers to show how Layer 2 surfaces structural
problems Layer 1 cannot.

Per-act 8-axis matrix (selected rows):

| Axis | Act 1 | Act 2 | Act 3 |
|---|---|---|---|
| Emotional resonance | 9 | 6 | 9 |
| Stakes & dilemma | 9 | 7 | 9 |
| Character identification | 8 | 7 | 8 |

Layer 2 structural axes:

| Axis | Score | Key signals |
|---|---|---|
| Causal integrity | 8 | Act 1's portrait commission causes Act 2's discovery; Act 2's discovery compels Act 3's choice. Strong chain. |
| Turning-point clarity | 7 | Act 1 turn (commission accepted) is sharp; midpoint (the failed portrait) is more of a stakes-raise than a reversal of what the story is about. |
| Arc gradient | 8 | Act 1 → Act 2 shifts Mirelle from subject to person; Act 2 → Act 3 shifts protagonist from practitioner to heretic. Two distinct deltas. |
| Promise & payoff | 9 | Opening portrait is paid off by the refusal to finish her; failed earlier portraits acquire elegiac weight in the closing image. |

**Cross-act diagnostic:** emotional resonance and stakes both drop in
Act 2 (9 → 6, 9 → 7). This co-locates with the turning-point clarity
score of 7. The single high-leverage move: convert the midpoint from
a stakes-raise to a reversal — let the failed portrait *teach*
something about what record can and cannot hold, so the protagonist
ends Act 2 understanding the story differently than they began it.
One structural change; three axes lifted across two layers.
