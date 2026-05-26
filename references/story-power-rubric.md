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
