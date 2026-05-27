# Graphic novel layout vocabulary

Canonical page-layout and panel-transition craft for graphic-novel-mode
projects. The prompts in `prompts_elaborate_gn.py` and `prompts_gn.py`
cite this document; the validators in `script_format.py` enforce its
deterministic anti-patterns. Authors and AI collaborators should both
work from this vocabulary.

This document is descriptive (it names craft that exists in published
graphic novels), not prescriptive (no choice here is mandatory). Its
purpose is to give the model — and the author — a shared, specific
vocabulary so layout decisions can be discussed and validated rather
than guessed at.

## Layout tokens

The `panel_breakdown` brief field uses these tokens for per-page page
structure. Each names a recognizable page form with a recognizable
narrative effect.

### `splash`

One panel filling the page. The most-prominent visual emphasis a single
page can produce.

- **Earns its space when:** the moment is genuinely the biggest beat in
  the scene — a first appearance, a revelation, a climactic image, a
  setting establishment that needs to *land*. Kirby's splash logic: a
  splash is a punctuation mark on the manuscript's scale; using one
  flattens every following panel's emphasis until the next splash.
- **Wastes its space when:** the beat is ordinary but the artist wanted
  to draw it big; a splash on every other page produces no emphasis at
  all (it becomes the new baseline).
- **Page-turn interaction:** splashes on the verso (right page) are the
  most-load-bearing reveal slot in comics. A splash arriving as a
  page-turn surprise is the strongest tool the medium has.

### `double-spread`

A single image across two facing pages (verso + recto). Twice the
visual mass of a splash, but only available at specific page positions
(must start on a verso page for the spread to read as a single image).

- **Earns its space when:** the moment needs the most prominent
  treatment available; setting establishments at scene starts; climaxes;
  scope-establishing shots that single splashes can't contain.
- **Wastes its space when:** used for moments smaller than the biggest
  in the manuscript; competes with adjacent splashes and exhausts the
  reader's tolerance for "huge moments."
- **Page-turn interaction:** the page-turn *into* a double-spread is
  the most dramatic reveal in comics. Watchmen #12's opening, Saga's
  jumps in scale, From Hell's establishing shots — all turn-into-spread.
- **Pacing cost:** spreads compress the scene's apparent panel count by
  one (a 4-page scene that includes a spread effectively has 3
  "pages-worth" of panel sequencing).

### `9-grid` (the Watchmen grid)

Three rows of three panels, regular spacing. The most disciplined
layout in the medium.

- **Narrative effect:** rigid, time-marking, observational. Each panel
  carries equal weight unless deliberately broken; breaking the grid
  *means* something because every other panel followed it.
- **Established by:** Moore + Gibbons on Watchmen (1986); revived by
  Frank Quitely on All-Star Superman; used by Tom King and contemporary
  literary-tier writers when they want the reader to *notice* the form.
- **Earns its space when:** the scene needs sustained, equal-weight
  attention to multiple beats (dialogue scenes, slow-burning suspense,
  pattern-recognition moments where the reader should compare panels);
  the manuscript can afford the panel count (9 panels is dense).
- **Wastes its space when:** action sequences (the equal sizing kills
  motion); short scenes (overkill for 2-3 beats); when adjacent pages
  use radically different grids (the form's discipline is only legible
  in stretches).

### `6-grid`

Two rows of three panels (or three rows of two — both read as 6-grid
in this vocabulary; orientation is decided by the artist). Less
disciplined than 9-grid; more flexible than splash-heavy layouts.

- **Narrative effect:** the "standard" grid for most contemporary
  comics. Enough panels to do scene-internal work; few enough that any
  one panel can carry more weight than its neighbors when sized larger.
- **Earns its space when:** dialogue-driven scenes, mid-density action,
  transitional pages; "the default that doesn't draw attention to
  itself."

### `N-grid` (general N-panel grid)

A regular grid of any panel count between 4 and 12. The token captures
the panel count; the row/column orientation is the artist's call.

- **4-grid:** declarative, slow; each panel substantial. Common in
  literary GN (Bechdel, Tomine, Satrapi).
- **5-grid / 7-grid / 8-grid:** less common; usually appear when the
  artist wants to break a 6- or 9-grid's rhythm without going to
  irregular.
- **12+ panels:** see *anti-patterns* below. 12 is the upper end of
  legibility; 16+ is almost always wrong.

### `tier`

A single horizontal row of panels across the full page width.
Conventionally 3 panels, occasionally 2 or 4.

- **Narrative effect:** "filmic" — emphasizes left-to-right motion
  (or right-to-left in manga); compresses time across the row;
  good for chase / pursuit / dialogue volley / brief montage.
- **Earns its space when:** a single beat is happening in three
  visual steps; a montage page (several tiers stacked, each a tiny
  scene); transition between locations or moments.
- **Tier-with-non-3-panel:** acceptable but unusual. A 2-panel tier
  is a "before/after" beat; a 4-panel tier compresses time tightly
  but risks each panel feeling cramped.

### `irregular`

Any page that doesn't fit the above. The artist designs the page
shape from the beat content rather than fitting beats into a grid.

- **Earns its space when:** the page needs visual rhythm the grid
  doesn't provide — overlapping panels, organic shapes, panels at
  diagonals, panels of vastly different sizes; emotional intensity
  scenes (Bill Sienkiewicz's Elektra: Assassin, JH Williams III's
  Promethea); action breaking out of containment.
- **Wastes its space when:** used as a default; produces busyness
  rather than emphasis when every page is irregular.

## Panel-to-panel transitions

Scott McCloud's six transitions, named in `Understanding Comics`
(1993). Each describes the relationship between consecutive panels —
*what's been left out in the gutter*. The brief's `key_actions` or
`panel_breakdown` doesn't need to name transitions explicitly, but
the model should understand them when composing panel sequences.

### Moment-to-moment

Consecutive panels show the same subject at consecutive moments in
time — small temporal steps (a fraction of a second to a few
seconds).

- **Effect:** time-slowing; observational; gives weight to a small
  beat. Reaction shots, sustained gestures, slowly-changing emotion.
- **Example:** Watchmen's pirate ship sequences; Asterios Polyp's
  domestic moments; manga's pause-on-a-face panels.
- **Best at:** emotional weight, dread, anticipation, intimacy.

### Action-to-action

Same subject, larger time steps — the subject visibly performs an
action across panels.

- **Effect:** filmic; "doing" rather than "being"; the spine of most
  action sequences.
- **Example:** any chase / fight / movement scene.
- **Best at:** propulsion, kinetic energy, plot motion.

### Subject-to-subject

Different subjects within the same scene, same time period.

- **Effect:** scene-internal coverage; expansion of the moment to
  multiple participants. Often used in dialogue (speaker A → speaker
  B → reaction shot of C).
- **Best at:** group scenes, conversation, complex moments with
  multiple stakes.

### Scene-to-scene

Different scenes — significant time and/or location jump.

- **Effect:** acts as a transition / cut; demands the reader infer
  what happened in the gutter. Used at scene breaks within a page or
  across page turns.
- **Best at:** compression, narrative pace, scene management.
- **Caution:** too many scene-to-scene transitions on a single page
  produce confusion; the reader loses scene-internal grounding.

### Aspect-to-aspect

Panels each show a different *aspect* of the same scene — atmosphere,
detail, mood. No subject continuity, no time advancement.

- **Effect:** mood-establishing; lyrical; almost spatial rather than
  temporal. Strongly associated with manga (where it's a foundational
  technique) and contemporary indie comics.
- **Example:** Jiro Taniguchi's slow walks through neighborhoods;
  Adrian Tomine's establishing pages; Watchmen's New York chapter
  opens.
- **Best at:** atmosphere, contemplation, dream-like sequences.

### Non-sequitur

Panels with no apparent logical relationship — the reader is forced
to construct meaning from the juxtaposition itself.

- **Effect:** experimental; usually deliberate disorientation;
  sometimes used at scene boundaries to mark a hard break.
- **Cautionary:** rarely the right answer outside experimental work.
  Most "non-sequitur" panels are actually scene-to-scene or
  aspect-to-aspect handled poorly.

## Page-turn discipline

The page-turn is the medium's most-load-bearing tool. Print comics are
read in two-page spreads (verso + recto). The reader sees both pages
*at once* and then turns to see the next spread. Anything on the
verso of a new spread is a *reveal* — the reader didn't see it until
the moment they turned.

### Page-turn beats

A beat marked in `page_turn_beats` should land on a verso panel
(specifically the first panel after a page-turn) for the reveal
mechanic to work.

- **Cliffhanger reveals:** the strongest page-turn use — end the recto
  on tension, open the new verso with the answer / consequence.
- **Splash reveals:** a single splash arriving as the first panel after
  a page-turn is the most-prominent moment the medium can produce.
- **Setup-then-payoff across the turn:** the recto sets up; the verso
  pays off.

### Anti-pattern: page-turn marker on page 1

Page 1 cannot be a page-turn (there's no preceding page to turn from).
A `⟵ PAGE-TURN REVEAL` marker on page 1 of the script is
deterministically wrong; the validator flags it. Move the beat to a
later page or remove the marker.

### Anti-pattern: page-turn beats with no page-turn

If `page_turn_beats` is populated but the script doesn't carry a
page-turn marker anywhere, the brief and script disagree — the
validator already flags this as `page_turn_missing`. Either populate
the marker in the script or remove the brief's beats.

### Manga / right-to-left

In manga (and any RTL reading order), the same page-turn mechanic
applies but the eye lands on the *right* page first; the verso
(now left) is the second page seen, not the reveal. Page-turn beats
in RTL projects should land on the recto (right page) of the *next*
spread.

Storyforge doesn't currently model reading order; RTL projects should
note this manually in the brief's `caption_strategy` or `subtext`
fields until a `project.reading_order` setting is added.

## Pacing principles

### Eisner's panel-as-time

From `Comics and Sequential Art` (1985): each panel is a moment frozen,
and the *gutter* between panels is the duration the reader infers.
Smaller panels read as shorter moments; larger panels (and splashes)
read as longer, weightier moments. Panel size carries narrative weight
beyond its content.

- **Implication for `panel_breakdown`:** sizing decisions are
  pacing decisions. A 9-grid page reads slower than a 6-grid page even
  when both contain the same number of dialogue exchanges, because
  the smaller panels feel like smaller time-slices.

### Kirby's splash logic

"Splash logic" is in-house vocabulary in this document — not a
named term Kirby used. The label captures the working principle
visible in Kirby's pages: Jack Kirby (Fantastic Four, New Gods,
OMAC) used splashes as visual exclamation points. A splash earns
its page when the moment is genuinely the *biggest* in the scene;
using one elsewhere diminishes every subsequent splash's effect.

- **Implication for `panel_breakdown`:** count splashes per scene.
  More than one splash in a 4-page scene is usually one too many;
  one splash in a 10-page scene is appropriate; zero splashes in a
  dialogue-heavy scene is fine.

### Watchmen-grid discipline

Alan Moore's working principle on Watchmen: the 9-grid is the
manuscript's *baseline*; any deviation has to mean something. When
every page is 9-grid for 8 pages and page 9 breaks into a splash,
the splash carries the full accumulated weight of the prior
discipline.

- **Implication for `panel_breakdown`:** rigid grids increase the
  power of grid-breaks. Irregular pages used in isolation produce
  noise; irregular pages used after a stretch of grid produce
  emphasis.

## Density and legibility limits

Two deterministic anti-patterns the validator enforces:

- **≥ 13 panels on a single page:** legibility crisis. The reader
  can no longer scan the panels comfortably; the page becomes a
  busy wall. Validator emits `panel_density_excessive` at this
  threshold.
- **`tier` declared with panel count ∉ {2, 3, 4}:** a tier
  conventionally holds 2-4 panels; a tier with 5+ panels reads as
  an N-grid mis-labeled, and a tier with 1 panel is a splash. The
  validator emits `tier_panel_count_unconventional` outside the band.

## Scene-pace heuristics

When briefing `target_pages` for a scene, these are the rough
contemporary GN bands (in 6 × 9 trade format; vary by tradition):

| Scene shape | Pages |
|---|---|
| Single quiet beat (a reaction, a gesture, a moment of recognition) | 1 page |
| Short dialogue or action exchange | 2-3 pages |
| Standard scene (setup, conflict, partial resolution) | 4-6 pages |
| Set-piece scene (extended action, major confrontation, climactic reversal) | 8-12 pages |
| Decompressed climax (Bendis-tradition; long emotional sequences) | 12-20 pages |

These are starting points. A specific project's register (literary /
action / atmospheric — see `project.register` for prose projects, same
idea applies in GN) calibrates the bands.

## References

- McCloud, Scott. *Understanding Comics: The Invisible Art*. 1993.
  (Transitions taxonomy; gutter theory.)
- Eisner, Will. *Comics and Sequential Art*. 1985. (Panel-as-time;
  page composition; visual rhythm.)
- Eisner, Will. *Graphic Storytelling and Visual Narrative*. 1996.
  (Narrative voice in comics; sequencing.)
- Moore, Alan + Gibbons, Dave. *Watchmen*. 1986–87. (9-grid discipline;
  page-turn discipline at literary tier.)
- Kirby, Jack. *Fantastic Four*, *New Gods*. 1960s–70s. (Splash logic;
  dynamic page composition.)
- McCloud, Scott. *Making Comics*. 2006. (Panel-to-panel craft; layout
  decisions in production.)
- Hatfield, Charles. *Alternative Comics: An Emerging Literature*.
  2005. (Indie GN form analysis; literary-tier conventions.)
