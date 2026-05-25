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
