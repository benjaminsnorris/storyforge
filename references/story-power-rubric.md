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
