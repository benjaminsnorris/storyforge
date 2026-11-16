---
name: elaborate
description: Progressive elaboration pipeline — build a novel from seed through validated briefs. Covers all creative development (character, world, architecture, voice, scene design). Use when the author wants to build or deepen their novel's structure, work on characters or world, develop voice, or advance to the next elaboration stage.
---

# Storyforge Elaborate

You are guiding an author through the elaboration pipeline — a progressive deepening process that builds structural integrity before any prose is written. Each stage adds detail to a unified scene data model, with validation gates between stages.

This skill covers all creative development work: character development, world building, story architecture, voice and style, and scene-level design. In the elaboration pipeline, these are integrated into the stages rather than handled as separate workflows.

## Locating the Storyforge Plugin

The Storyforge plugin root is two levels up from this skill file's directory (this skill's directory -> `skills/` -> plugin root).

Store this resolved plugin path for use throughout the session.

## Step 1: Read Project State

Read the following files to understand where the project stands:

1. `storyforge.yaml` — check the `phase` field to determine current stage
2. `reference/scenes.csv` — check if it exists and how many rows (0 = no spine yet)
3. `reference/scene-intent.csv` — check column depth (function only = spine; `reference/architecture.csv` has rows, or value_shift is filled = architecture: value_shift is a craft-framework column and may be empty on purpose, #643; has characters = mapped)
4. `reference/scene-briefs.csv` — check if it exists and has non-empty rows
5. `reference/story-architecture.md` — does it exist?
6. The bibles (#657): run `./storyforge bibles` (no cost). It says whether each essay (`character-bible.md`, `world-bible.md`, `systems-bible.md`) is still an essay, retired to `reference/archive/`, an unfilled template, or none; how many trait, relationship and world facts the plan has, and its planned knowledge facts; the voices and notes; and the plan's gaps (the two-writers test). In a prose book, an essay still in `reference/` is read-only reference: Storyforge reads it (beside any rows of its kind: drafting, the checker, hone and scoring read both) but its stages no longer write to it. Offer to convert it (see **Bibles as Rows** below)

## Adaptations (a `source:` block)

When `storyforge.yaml` has a `source:` block, this novel adapts another Storyforge project (a retelling, an expansion, a rewrite). Before any stage:

1. Check `reference/source/<slug>/` exists for each source. If not, the source isn't imported: offer `storyforge source import` (deterministic, no cost). It copies the source's CSVs, bibles and prose there with the name map applied and writes `source-bible.md`, and seeds the project's empty `characters.csv`, `locations.csv` and `values.csv` from the source's (a registry with rows is never touched; a source with a `range:` gives only the cast, places and values its adapted scenes use). Never edit `reference/source/`; re-run the import. Fill the seeded cast's `pronouns` and `death_scene` as the novel needs.
2. Read `reference/source/<slug>/source-bible.md`, `source.mode` (`faithful`: every source scene is adapted or cut with a reason, or validate blocks, and revise fixes source drift; `free`: a source scene left out or cut without a reason is advisory, and drift is reported but not fixed) and the version rules `source.rules` names (usually a section of `reference/key-decisions.md`).
3. Spine: select and reframe the source's events; don't invent the spine. Architecture: start from the source's cast and POV distribution. Map: write `reference/source-map.csv` (`scene_id|source_scenes|treatment|note`) accounting for every source scene; treatments `dramatize`, `compress`, `expand`, `pov-shift`, `reorder`, `invent`, `cut` (a `cut` row has an empty `scene_id` and a reason in `note`). Briefs: write each brief looking at its source scenes' briefs and prose (`reference/source/<slug>/scenes/`); the source prose keeps the translator's names, so write the name map's names.
4. `storyforge validate` reports coverage ("Source odyssey: 170 scenes, 162 mapped, ..."); `storyforge score --source-fidelity briefs` checks the briefs against the source before any prose, tagging each departure `deliberate` (the treatment, note or a version rule allows it), `moved` (to or from the neighbouring book scene), `staging` (connective invention that changes no event, fact or outcome, never on outcome or knowledge_out; in `free` mode, or in `faithful` mode where a version rule or the scene's note allows it) or `drift`. Only drift counts against the scene.
5. A source with a `range:` (`chapters 1-4` or `scenes first-id..last-id` on its `projects` entry) is adapted only within that span: "every source scene" above means every scene in the span ("Source odyssey: 24 of 170 scenes adapted (chapters 1-4), ..."). The rest of the source is context in the source bible (marked before / the adapted span / after); give it no map rows. To adapt a scene outside the span, widen the range and re-run `storyforge source import`.

Without a `source:` block none of this applies.

## Registry Awareness

Read all registry files in `reference/` to know the canonical IDs for normalized fields:

- `reference/characters.csv` — canonical character IDs
- `reference/locations.csv` — canonical location IDs
- `reference/values.csv` — canonical value IDs
- `reference/commitments.csv` — the commitments ledger: canonical knowledge fact IDs (`type` `knowledge`) and physical state IDs (`type` `physical`)
- `reference/motif-taxonomy.csv` — canonical motif IDs, for motifs recorded after drafting (no stage places motifs in a brief, #644)
- `reference/mice-threads.csv` — canonical MICE thread IDs

**When writing any CSV field value, use canonical IDs from these registries:**

| CSV field(s) | Registry |
|---|---|
| `pov`, `characters`, `on_stage` | characters.csv (`pov` may also be the reserved `narrator`) |
| `location` | locations.csv |
| `value_at_stake` | values.csv |
| `knowledge_in`, `knowledge_out` | commitments.csv, `type` `knowledge` |
| `physical_state_in`, `physical_state_out` | commitments.csv, `type` `physical` |
| `motifs` | motif-taxonomy.csv |
| `mice_threads` | mice-threads.csv (`+id` where the thread opens, `-id` where it closes, bare `id` where a scene mentions it; `type:id` when two threads share a name) |

**When the author introduces a new character, location, value, knowledge fact, motif, or MICE thread that does not exist in a registry:** add it to the appropriate registry CSV first, then use the new ID in scene data. A new character's row gets its `pronouns` (`he`, `she`, `they`, `it`, or a slash form such as `she/her`) when the author has said or the story makes them plain; otherwise leave the cell empty for the author (validate names it), never guess.

**The narrator as POV.** A scene the book's narrator tells, through no one character's eyes (an epic's omniscient voice, a frame narrator), has `pov` `narrator`. It is reserved: never add it to characters.csv, and it never needs to be in `on_stage`. A narrator who is a person (a first-person teller, named or not) is a character with an id like any other, never `narrator`. Whether the narrator may hold scenes is the author's call, on a line of `reference/key-decisions.md`: `narrator_pov: allowed` (the default), `limited N` (validate flags more than N narrator scenes) or `off` (validate and the scene-map floor check flag every narrator scene). Ask the author when the book has narrated scenes and key-decisions.md doesn't say.

## Scene IDs

A scene id is a 3-5 word lowercase hyphenated slug naming the scene's core event (e.g., `gatsby-reunites-with-daisy`). It is permanent:

- **Never positional.** No `act1-sc03`, `scene-12`, `ch3-2`. Position belongs in `seq` (reading order), `act` (structure) and `part` (book divisions), which exist so they can change.
- **Never renamed.** Not when a scene moves, not when its title changes. Every reference (`continuity_deps`, knowledge `origin`, physical-state `acquired`/`resolves`, chapter maps) points at the id.
- **Reason about order from `seq`, not the id.** When considering whether a scene belongs elsewhere, judge it by what happens in it; the id should not anchor you to where it started.

`storyforge validate` reports ids that break this rule (advisory).

## Step 2: Determine Current Stage

Based on the project state, identify where the author is:

| Phase in YAML | scenes.csv rows | Intent depth | Briefs | Validation | Current stage |
|---------------|----------------|--------------|--------|------------|---------------|
| any | 0 | — | — | `storyforge status` next.stage ∈ {logline, synopsis, act-shape} (story-summary.md missing or thin) | Needs prose tier / Start at Stage 0 |
| any | any | — | — | `storyforge status` next.stage `voice`, action "Find the voice" (prose tier solid, no voice yet, `voice_stage` not `later`) | Needs the voice: Voice Stage, before the spine (#656) |
| spine | 0 | — | — | — | Needs spine |
| spine | 5-10 | function only | — | — | Spine done, ready for architecture |
| architecture | 15-25 | architecture.csv has rows (value_shift and the other craft columns are optional, #643) | — | — | Architecture done, ready for map |
| scene-map | target_words/2000 to target_words/1500 | has characters, on_stage | — | — | Map done, ready for briefs (after the voice check, when `status` asks for it) |
| briefs | same as map | full | has outcome and key_actions (goal, conflict, crisis, decision are the author's optional notes, plan decision 9) | — | Briefs done, ready for drafting |
| drafting+ | status=drafted | populated but gaps | populated | blocking failures > 0 (`passed` False) | **Gap-fill mode** |
| drafting+ | — | — | — | passes | Past elaboration — redirect to forge |

## Step 3: Determine Mode

Based on the author's request, determine the mode:

### Specific requests (always honored, bypass auto-advance):

- **"Start a new novel"** / **"Let's begin"** → Start at Stage 0, the pitch/prose tier. Ask for the seed (logline, genre, characters, themes, constraints) and develop it through `reference/story-summary.md`: logline → synopsis → act-shape, gating each with `storyforge score --level 0|1|2` and pressure-testing the whole pitch with `storyforge score --story-power`. Only build the spine once `storyforge status` shows the prose tier rungs `solid`.
- **"Work on the spine/architecture/map/briefs"** → Go to that specific stage.
- **"Develop the voice"** / **"Find the voice"** / **"Voice guide"** / **"Style"** → Voice development (see Voice Stage below). By default it comes right after the synopsis and act shape, before the spine, with a short check after the map.
- **"Structure first"** / **"Skip the voice for now"** → put `voice_stage: later` on a line of `reference/key-decisions.md` and go on to the spine. The voice is then found before drafting (see "Where the voice stage sits").
- **"Deepen characters"** / **"Work on [character name]"** → Character development. During elaboration, this deepens the characters' facts (rows, **Bibles as Rows**). The spine seeds them; this mode adds wound/lie/need/want, lines of each character speaking, and the relationships.
- **"Build the world"** / **"World building"** → The world's rules as rows (**Bibles as Rows**). During elaboration, world building supports the architecture and scene map stages.
- **"Story architecture"** / **"Theme"** / **"Structure"** → Story architecture refinement. The spine creates the initial architecture; this mode deepens thematic throughlines, conflict structure, and arc planning.
- **"Fix pacing"** / **"Pacing shape"** / **"Second half doesn't escalate"** → Pacing review (see Pacing Review below).
- **"Fix outcomes"** / **"Scene function variety"** / **"Too many yes-but"** → Outcome review (see Outcome Review below).
- **"Validate"** → Run validation on the current state.
- **Status question** → Report current stage, scene count, validation state.

### Auto-advance (unspecified requests — "elaborate", "what's next", "keep going"):

When the author doesn't specify a mode, detect the current stage from Step 2 and act based on coaching level:

| Detected State | Action |
|---|---|
| `storyforge status` next.stage ∈ {logline, synopsis, act-shape} (story-summary.md missing or thin) | Needs prose tier / Start at Stage 0 |
| `storyforge status` next.stage `voice` with action "Find the voice" before drafting (the prose tier is solid and the book has no voice yet; `then` names the rung after it) | Run the Voice Stage, then the rung `then` names. Say once that the author can do structure first (`voice_stage: later`) |
| No scenes.csv (or 0 rows) | Start spine |
| Spine done (5-10 rows, function only) | Run architecture |
| Architecture done (architecture.csv has rows; value_shift is optional, #643) | Run scene map |
| `storyforge status` next.stage `voice` with action "Check the voice against the map" (the map is done; `book.md` says nothing of a POV the map uses) | Run the voice check after the map (Voice Stage, below) |
| Map done (has characters, on_stage) | Run briefs |
| Briefs done, `storyforge status` has a `voice` blocker (next.stage `voice`, or then.stage `voice` behind a gate `check`: `reference/voice/book.md` missing, init's template or empty, no anchor, or a file unreadable, with no author voice repo; the voice was put off with `voice_stage: later`, or never found) | Run the Voice Stage |
| Briefs done, validation passes | Announce ready for drafting, redirect to forge (drafting is a writing session: `storyforge write --session --act 1 --dry-run`, then the real run, which stops after 3 scenes for the author's read) |
| Drafted with blocking validation failures (`passed` False; advisory findings alone never count, #643) | Run gap-fill |
| Everything passes | Redirect to forge |

**Coaching level determines posture:**

**Full mode:** Announce the action and do it immediately.
- "No spine yet — let's build one. What's your logline or seed idea?"
- "Your scenes are at architecture stage. I'll expand to the full scene map now."
- "Post-extraction data has 47 gaps. I'll fill them — starting with the parallel batches."

**Coach mode:** Present the recommendation and wait for approval.
- "Your scenes are at architecture stage. The next step is expanding to a full scene map — locations, timeline, characters, MICE threads. Ready to go?"
- "I found 47 structural gaps in your extracted data. Want me to fill them?"

**Strict mode:** Report state data only. Author decides.
- "Current state: 22 scenes at architecture depth. 0 mapped. Next stage: scene-map. Run `./storyforge elaborate --stage map` or work through it here."
- "Validation: 47 failures across 5 gap groups. Run `./storyforge elaborate --stage gap-fill` to fill automatically."

After the author approves (or immediately in full mode), proceed to Step 4 to execute the appropriate stage.

## Step 4: Execute the Stage

### Coaching Level Behavior

Read the coaching level from `storyforge.yaml` (`project.coaching_level`) or environment.

**Full mode (default):**
- You do the creative work. Propose the spine, build the architecture, map scenes, write briefs.
- Present results for author review at each stage boundary.
- If the author says "keep going" or "looks good," advance to the next stage.

**Coach mode:**
- Present options and ask questions at each stage.
- For spine: "Here are three possible spines — which direction resonates?"
- For architecture: "I see two ways to structure Act 2 — which feels right?"
- Author makes all creative decisions; you structure and organize them.

**Strict mode:**
- Ask structural questions only. Don't propose creative content.
- "What are the 5-10 events that must happen in this story?"
- "Who is the POV character for this scene and why?"
- You handle all CSV formatting, validation, and file management.
- **Validate is your key offering** — run it after the author fills in each stage.

### Running Each Stage

For each stage, offer two options:

> **Option A: Run it here**
> I'll work through the stage in this conversation. We can discuss and iterate.
>
> **Option B: Run it autonomously**
> Copy this command and run it in a separate terminal:
> ```bash
> cd [project_dir] && [plugin_path]/storyforge elaborate --stage [stage]
> ```
> This creates a branch, runs the stage, validates, and opens a PR.

Wait for the author's choice. If they choose Option A, work through the stage interactively:

1. Build the stage's output (CSV rows + reference materials)
2. Present a summary to the author
3. Apply the updates to the CSV files and reference docs
4. Run validation
5. Report results
6. Commit and push

If they choose Option B, provide the full command and end.

### Stage 0 — Pitch / Prose Tier (Interactive)

Before building the spine, solidify the pitch in `reference/story-summary.md`:
logline → synopsis → act-shape, in that order. This is the loop the
story-power scorecard was built for — skipping it means building structure on
an unvalidated premise.

For each section, in order:
1. Develop or refine the section with the author (logline first, then
   synopsis, then act-shape).
2. Run `storyforge score --level 0|1|2` — the deterministic floor check
   (length, presence, shape) for that section.
3. Run `storyforge score --story-power` — the 8-axis pitch-tier scorecard;
   pressure-tests specificity, emotional resonance, stakes, and the rest of
   the pitch's craft.
4. When exploring alternatives, run `storyforge score --compare <a> <b> --level N`
   to compare candidate loglines or synopses side by side.
5. Write the section to `reference/story-summary.md`. Its `_updated`
   frontmatter timestamp feeds cascade drift detection, so let the write
   update it rather than hand-editing the timestamp.
6. Commit: `git add -A -- . && git commit -m "Elaborate: prose tier" && git push`

Advance only when the prose tier reads `solid` in `storyforge status` and
the story-power scorecard is acceptable to the author. Then comes the
Voice Stage (below), before the spine, unless the book already has its
voice or the author chooses structure first (`voice_stage: later`).

### Spine Stage (Interactive)

1. Gather the seed from the author (or read from logline)
2. Propose the story architecture: premise, theme, three-level conflict, ending
3. Propose protagonist with wound/lie/need/want
4. Propose 5-10 spine events as a numbered list
5. Once approved, write to:
   - `reference/story-architecture.md`
   - the protagonist's and antagonist's facts as rows (want, need, wound, lie, role, any fact the plot depends on), two or three lines of each speaking, and terse notes only if needed: see **Bibles as Rows** (a graphic novel still writes `reference/character-bible.md`)
   - `reference/scenes.csv` (id, seq, title, status=spine)
   - `reference/scene-intent.csv` (id, function)
   - `reference/spine.csv` (`id|seq|title|summary|function|act`): the same spine scenes, with a summary of at most 35 words and the act. The status ladder and `score --level 3` read it
6. Commit: `git add -A -- . && git commit -m "Elaborate: spine" && git push`

### Architecture Stage (Interactive)

1. Read the spine scenes and story architecture
2. Expand to 15-25 scenes: add supporting scenes, transitions, subplot introductions
3. Assign acts and POV. The POVs follow the narrator stance in `reference/voice/book.md` (`## Decided`) and `narrator_pov` in key-decisions.md: whether a narrator holds scenes, how many POV characters, how close. Scene type (action/sequel), value shift and turning point are notes where they fit (#643, #644): leave one empty for a scene that doesn't turn or shift, and don't vary them to satisfy a rule
   - **Use canonical IDs from registries** for pov, characters, locations, value_at_stake. Add new registry entries for any new characters/locations/values introduced at this stage.
4. Add the supporting characters' facts, the relationships between the cast, and the world's rules as rows (**Bibles as Rows**; a graphic novel deepens its essays)
5. Check the gaps: `./storyforge validate` lists them as `plan-gaps` (advisory). Settle the ones the plan owes before the map
6. Write updates to all CSV files and reference docs, including `reference/architecture.csv` (`id|seq|title|summary|act|pov|spine_event|action_sequel|emotional_arc|value_at_stake|value_shift|turning_point`, one row per architecture scene, `spine_event` naming the spine scene it serves) and each of those scenes' `architecture_scene` in scenes.csv (its own id). The status ladder and `score --level 4` read it
7. Run validation — fix any issues before committing
8. Commit: `git add -A -- . && git commit -m "Elaborate: architecture" && git push`

### Scene Map Stage (Interactive)

1. Read architecture scenes and reference materials
2. Compute target scene count from `project.target_words`: `target_words / 2000` (lower) to `target_words / 1500` (upper), minimum 40. For an 80k novel this is 40-53; for 100k it's 50-67. A scene count the author recorded in key-decisions.md wins over this estimate. **Prefer more, shorter scenes** (1500-2000 words each) — Claude follows brief constraints more reliably in focused scenes, and scoring/revision are more precise on smaller units.
3. Expand to that range: fill gaps, add transitions, subplot scenes, breathing room
4. Give every scene a POV the voice's narrator stance allows (`reference/voice/book.md`, `## Decided`; `narrator_pov` in key-decisions.md). Voice decides POV: on *Wrath Like Smoke* the found voice moved the opening to another character's eyes and had deaths seen by the man dying.
5. Assign locations, timeline, characters, MICE threads — **all registry-backed fields must use canonical IDs** (characters, locations, values, mice_threads). Add new registry entries for anything introduced at this stage.
   - Set `architecture_scene` on every scene: its own id for an architecture scene, the anchor's id for a scene split off one (`score --all-boundaries` gathers an anchor's map scenes by it). Leave it empty only for a new scene that serves no architecture scene.
   - An enum cell holds only its value (`turning_point` `action`, never `action: she strikes`; `time_of_day` one of morning, afternoon, evening, night, dawn, dusk or unstated). The CLI stage splits a `value: description` cell and keeps the description in `function`.
6. Write updates
7. Run validation — timeline, character references (MICE nesting is advisory)
8. Commit: `git add -A -- . && git commit -m "Elaborate: scene map" && git push`
9. Then the short voice check (Voice Stage, "The check after the map"), when the book has its voice

### Graphic-novel mode

In graphic-novel mode, the scene-map stage asks for `target_pages` per scene instead of `target_words`. Page-count guidance:
- Short scene (single beat): 1-2 pages
- Standard scene: 2-4 pages
- Set piece / chapter centerpiece: 5-8+ pages
- Full graphic-novel target: 100-200 pages typical for one volume

### Briefs Stage (Interactive)

1. Read full scene map and all reference materials
2. For each scene, write its **facts**: outcome, key_actions (the events in order, the turn included when the scene has one), knowledge_in, knowledge_out, physical_state_in, physical_state_out, continuity_deps. About 3 to 6 events: never more than 6, and no more than 2.5 for each 1,000 target words (`elaborate.brief_event_limit`, the limit hone flags past), the whole key_actions cell under 200 characters.
   - **Facts, not staging (#644).** A brief says what happens, not how it's played, what's said or what it means. Never write `goal`, `conflict`, `crisis`, `decision`, `key_dialogue`, `subtext`, `emotions`, `motifs` or `motif_details` (prose books; in graphic-novel mode `key_dialogue` is the balloon text, see below): they're the author's optional notes, filled by hand, and the author's own are left as they are. Don't place motifs: a motif is noticed in the draft and recorded after.
   - **Terse notes, no interpretation.** "Agamemnon counts the gifts on the sceptre studs; Briseis is the sixth stud", not a paragraph about what the moment means. No polished or quotable sentences: the drafter reads the brief and writes more like it. The same goes for every stage's scene rows; the story architecture and the bibles are where a theme, a need or a lie belongs, still as short notes.
   - **outcome and key_actions are required** (the brief's facts; validate blocks a briefed scene without them). Judge the outcome by whether the scene goes the POV character's way (what they're trying to do or hoping for); it needs no goal.
   - **Use canonical IDs from registries** for knowledge_in, knowledge_out (the ledger's knowledge facts in commitments.csv). Add new registry entries for any new knowledge facts introduced at this stage: a new fact is a row of `reference/commitments.csv`, the commitments ledger, with `type` `knowledge`: `id`, the `scene_id` that establishes it (blank for backstory), the fact as one sentence in `statement`, `origin` `author` (or `plan` for a brief), `status` `binding`, `mutable` `state`; leave the other columns empty.
   - **Label every scripted line's speaker (prose books only)** in a line the author writes or one already there: `Name: "line"` in `key_dialogue` (and on a quoted line in `key_actions`), the label starting with the character's name, id or an alias exactly as characters.csv writes it (nothing added before it, no possessive), one character per label, repeated after each `;`. The gate checks a speech tag that splits a labelled line against that speaker (see `references/scene-column-guide.md`). Not in a graphic novel: its `key_dialogue` must appear verbatim in the panel script, and a label would fail that check.
   - **`must:` beats are the author's.** A `key_actions` or `key_dialogue` item that starts with `must:` is a beat the author requires: the gate stops a scene that breaks it (other broken promises are only advisory), and its quoted words must be in the prose word for word. Never cut, merge, reword or unmark one, and never add `must:` yourself; offer it to the author when they want the gate to require a beat. See `references/scene-schema.md`.
3. **Knowledge wording must be exact** — knowledge_out from scene N becomes knowledge_in for later scenes, matched literally. Use registry IDs rather than free-text to ensure exact matching.
4. Maximize scenes with no continuity_deps (these can be drafted in parallel)
   - **These columns also decide what drafting holds back.** When a scene fails the gate, `write` still drafts the later scenes that don't depend on it, and holds back those that do. For a scene not drafted yet, its brief is how it knows: `continuity_deps` naming the failed scene, or `knowledge_in`/`physical_state_in` naming a fact the failed scene's brief adds. A scene whose `continuity_deps`, `knowledge_in` and `physical_state_in` are all blank can't be told apart, so it waits behind every earlier failure. Fill them, and drafting can go on past a failure.
5. Write updates
6. Run validation — knowledge flow, completeness, DAG check
7. Commit: `git add -A -- . && git commit -m "Elaborate: briefs" && git push`

`storyforge elaborate --stage briefs` registers the briefs' new knowledge and physical-state ids in `commitments.csv` itself, by the reconciliation `storyforge hone --domain knowledge,physical-states` runs (a physical state's `resolves` is the scene where the briefs' chain ends it). Those rows are `introduced_by` `briefs` with status `planned`: plan, not fact, so the gate never holds the prose to them; the gate makes one `binding` when the prose establishes it. A re-run keeps them in step: a fact no active brief names is removed, and one moves to the scene that now sets it up. A row you have edited since is yours and is left alone. When you write briefs by hand, run that hone command after; if the stage reports that ids are not all in the ledger, run it too.

### Graphic-novel mode

Graphic-novel briefs populate five additional columns alongside the standard ones:
- `page_layout` — high-level rhythm intent (e.g., "9-panel grid", "splash p3")
- `panel_breakdown` — per-page structure (e.g., "p1:splash; p2:6-grid")
- `visual_keywords` — visual beats that must appear, semicolon-separated
- `page_turn_beats` — beats that must land on a page turn
- `caption_strategy` — narration style for this scene

All standard brief columns still apply with full meaning. `key_actions` reads as a panel-beat list; `key_dialogue` becomes the word-balloon contract; `continuity_deps` covers visual continuity too.

### Page architecture (graphic-novel only)

**Stage:** `--stage page-architecture` (or `--page-architecture`)
**Purpose:** Capture page-level authoring context — panel hierarchy, eye flow, pacing intent — before authoring the image prompt. (This is commentary for the artist and the page prompt, not a render directive.)
**Output:** a single `## Page architecture` section (Intent / Panel hierarchy / Layout) in each page file under `pages/`.
**Preconditions:** scene brief has `panel_breakdown`; `reference/canon/panel-registers.md` and `reference/canon/page-rhythm-rules.md` are populated (not TODO).

**Flags:**
- `--page <page_id>` — single page only
- `--scene <scene_id>` — every page of one scene
- `--force` — overwrite the existing section
- `--dry-run` — print one prompt, no API calls

**Coaching modes:**
- **full** — LLM drafts the section directly into the page file
- **coach** — writes a markdown brief to `working/coaching/page-architecture-<page_id>.md` asking the right questions; no mutation of the page file
- **strict** — stamps a deterministic TODO template into the page file; no API call

**When to run:** after `briefs` in graphic-novel projects, before the `prompts` stage.

### Image-generation prompts (graphic-novel only)

**Stage:** `--stage prompts`
**Purpose:** Author the whole-page image-generation prompt for GPT Image 2 (ChatGPT Images 2.0), validated in Ashes PR #9.
**Output:** a `## Image-generation workflow` section in each page file — an approach note, a labeled reference-image list, and a single **page prompt** in OpenAI's 5-section template (Scene / Subject / Important details / Use case / Constraints) with one concrete beat per panel.
**Preconditions:** scene brief has `panel_breakdown`; the page has a populated `## Page architecture` (run `--stage page-architecture` first) and a populated `## Panel script` (draft the page with `storyforge write` first). Canon *informs* the prompt but does not gate it.

**Flags:**
- `--page <page_id>` — single page only
- `--scene <scene_id>` — every page of one scene
- `--force` — overwrite the existing workflow section
- `--dry-run` — print one prompt, no API calls

**Coaching modes:**
- **full** — the LLM drafts the page-prompt body; the handler wraps it with the approach note + reference list and splices it in
- **coach** — writes a brief to `working/coaching/prompts-<page_id>.md` with the GPT Image 2 rules and the inputs; no page mutation
- **strict** — stamps a deterministic 5-section TODO scaffold; no API call

**When to run:** after `page-architecture` AND after the page is drafted (`## Panel script` populated).

**Five GPT Image 2 principles** the prompt obeys:
1. One prompt renders the **whole page** — no per-panel or composition pass.
2. **Reference images carry style + character likeness** — keep prose short (~250-400 words); fix drift by adjusting references, not by adding prose.
3. OpenAI's **5-section template**; structure matters more than brevity.
4. The **character anchor is the IDENTICAL string** in every panel that shows that character — not paraphrased.
5. **Positive framing** replaces negation — state what IS present (negated keywords leak into the image).

**Two quirk defaults baked in (issue #263):**
- **Portrait orientation** is emitted in both the Use case and Constraints by default — GPT Image 2 drifts to landscape otherwise. Set `page_aspect: portrait | landscape | square` (default portrait) in the page frontmatter to opt out for a spread or special page; a non-portrait value should carry a trailing `# justification` comment or `cleanup` will flag it. (Orientation is the one place the prompt uses explicit negation — "do not render as landscape or square" — distinct from the content positive-framing rule.)
- **Panel differentiation** — when the panel script has ≥2 close-ups of the same subject, the prompt automatically emits a differentiation directive (subject-in-isolation / act-of-interaction at the contact point / different scale or angle) so the renders don't converge into one image. `cleanup` warns if a page prompt has same-subject close-ups but no differentiation language.

Reference images upload alongside the prompt, labeled by role: **Image 1** character reference, **Image 2** paper-tone reference, **Image 3+** prior rendered pages. List them in the page frontmatter's `references_required`.

### Voice Stage (Interactive)

The voice is found, not written. It lives in `reference/voice/` (`references/voice-folder.md`):

- `anchors/*.md` — passages the author chose or finished by hand. They are the voice spec.
- `book.md` — what the voice does, said by quoting the anchors; the people; decided rules (person, distance, tense by POV); for a retelling, `## Register exemptions`.
- `checks.md` — problems to look for in a finished scene, taken from the author's own marks. Review only: never put it, or a list like it, into a writing prompt. A writing session (`storyforge write --session`) runs it on each finished scene: a reviewer flags lines against it, and a separate reviser that never sees it rewrites those lines toward the anchors. With no checks in it, no scene gets that review. In *Wrath Like Smoke*'s rounds a sample written from a list of things to avoid avoided all of them and read flat.

**Where the voice stage sits (#656).** Voice is structural, not paint: who tells the story, and from what distance, decides which scenes exist and whose eyes they're in. So by default the voice comes right after the synopsis and act shape, before the spine and architecture deepen, and a short second check follows the map:

1. **First, after the act shape.** Once the prose tier is solid, `storyforge status` names `voice` as `next` ("Find the voice") while the book has none, with the spine (or whichever rung comes next) as `then`. Find the voice by sample rounds (below). There are no scenes yet, so round 1 writes a moment: `storyforge voice sample --moment "Hector says goodbye to Andromache at the Scaean Gate"`. Pick a moment from the synopsis the author can already see.
2. **Settle the narrator stance** the samples found, because the map is built from it: whether a narrator holds scenes, how many POV characters, how close or distant, the tense (by POV if it differs). Write it in `book.md` under `## Decided` and the people under `## People`, and put `narrator_pov: allowed | limited N | off` on a line of `reference/key-decisions.md` (validate checks the map against it). The architecture and map stages assign POVs that follow it; the CLI stages' prompts carry a rule saying so whenever `book.md` has the author's text.
3. **The check after the map.** Once the map is solid, `status` names `voice` as `next` again ("Check the voice against the map") when `book.md` says nothing of a POV the map uses, before any brief is written or scene drafted. A POV is named by its full name, id or a characters.csv alias, as written (case counts), never by a first name alone: add a first name as an alias if `book.md` uses it. A narrator POV is named by "narrator", not by "no narrator". `./storyforge elaborate --stage voice` names the same POVs once the map is solid, or says they're all named. Check that the voice holds across the POV mix: say in `book.md` how each named POV's scenes are told (who, how close, the tense), and if a POV the voice can't carry crept in, change the map instead. If the found voice moved a POV (an opening seen by someone else, deaths seen by the man dying), offer a POV pass on `scenes.csv`: Claude proposes, the author decides. Once a brief is written or a scene drafted, and always with `voice_stage: later`, an uncovered POV is a NOTE in `status`, not a stop.
4. **Skipping it is the author's call.** It's a soft default. An author who wants to build the structure first puts `voice_stage: later` on a line of `reference/key-decisions.md` (`voice_stage: first` or no line is the default); `status` then shows the voice after the briefs, as before. Drafting needs the voice either way.

Drafting needs it: until `book.md` has the author's text and there is at least one anchor (or the book's `voice:` block names an author voice repo), `storyforge status` has a `voice` blocker and names `voice` as the stage before drafting, and `storyforge write` refuses to draft at full coaching. `./storyforge elaborate --stage voice` calls no model for a prose book: it sets up the folder's missing files from the templates (never over one that's there), commits, says what's still missing, and with the voice ready runs the check after the map. It advances no phase. No model writes the voice: the old rule-list voice guide is gone, and what the voice stage leaves is `book.md` (what the voice does, quoting the anchors), the anchors, and `checks.md` (the short list of things to avoid, for review only).

A book with a `voice:` block in `storyforge.yaml` (an author voice repo, `references/storyforge-yaml-schema.md`) is ready with the repo alone; the writing prompt carries the repo's description and exemplars first, then this folder. Start the rounds from the repo's description and exemplars (read them first; they're the author's voice, and the book's narrator is a choice within it). The book's narrator stance, POV rules, people and tense still belong in `book.md`.

If the book still has `reference/voice-guide.md`, `voice-profile.csv`, `persistent-prompt.md`, `prose-exemplars.md` or `exemplars/`, nothing reads them any more (`status` prints a NOTE; `cleanup` reports `old_voice_file`). Offer to move what the author wants to keep into `book.md` or an anchor, word for word. Never delete them without the author's say.

Every CLI stage sets `exists: true` and `updated` on the `storyforge.yaml` artifacts it writes (story architecture, bibles, scene index).

**Running sample rounds.** At full coaching, `storyforge voice sample` runs them as PRs (`references/voice-folder.md`, "Finding anchors", has the flags):

1. Read what the book has: the characters' facts and voices (`./storyforge bibles`, or the essay if not yet converted; before the spine there may be none yet), story architecture, key decisions, any existing `reference/voice/` files, and anything the author points to as a model (their own earlier prose, a writer they admire). Settle with the author which writers to blend (`--influences`) and what the versions should vary (`--vary`; default narrator stance, distance, tense).
2. Pick one scene that matters and that the author will know well; it must be in `scenes.csv`. Before the map there is none: give a moment instead, in a sentence or two (`--moment "..."`; the round gets those words and the synopsis, and later rounds carry the moment as they carry a scene). Run `storyforge voice sample --scene <id>` (or `--moment "..."`; `--dry-run` first; its cost line is a rough guess, not a forecast). It writes the samples unlabelled and shuffled, one sentence per line, in `working/voice-samples/round-<n>.md`, checks each one before the author sees it (the blocking read for physical slips, the voice review when `checks.md` has checks, a reviser fixing only the flagged lines), and commits it on a new branch with its own PR (off `main`, or off the last round's branch); the PR's description says what the checks found, fixed and left out. A reply short of the versions asked for is an error: run it again. The key (which sample tried what) stays outside the repo, under `~/.storyforge/voice-sample-keys/`, and no command shows it: the author marks blind, so don't guess at it for them.
3. Ask the author to mark sentences in the PR's Files changed: keep, cut, "more like this", a reason, a `suggestion` with their own wording (an empty one cuts the line), a comment on a sample's heading for the whole sample, and general reactions. Only the PR author's comments count, and they must **submit the review**: comments in an unsubmitted review can't be read.
4. Run `storyforge voice sample --from-pr <N>` for the next round, written toward the keeps, not away from the cuts; the scene, influences and vary list carry over unless given. If the author edited the round file on GitHub (or committed a suggestion), pull the branch first: it refuses a local copy that differs from the PR's head. A PR with none of the author's marks is refused unless `--allow-unmarked`; the NOTEs say which comments were left out (others', earlier ones, ones on lines since changed, replies in a thread without a suggestion). After the second round, a take teaches more than five blends: `--from-pr <N> --take <label> --versions "present tense;past tense"` (or two points of view); each version is headed by its name, so a later `--take` or `--promote --sample "present tense"` names it.
5. When a sample is close, the author finishes it by hand in the round file. Then `storyforge voice sample --promote working/voice-samples/round-<n>.md --sample <label> --name <name>` with `--kind`, `--tense` and `--pov` when they help saves it as `reference/voice/anchors/<name>.md` and commits it on a branch (never `main`); pull first if they finished it on GitHub. An empty sample is refused. Add anchors for other kinds of scene the book needs (a battle reads differently from a farewell).
6. Without `gh`, run a round by hand the same way: samples on a branch, unlabelled, one sentence per line, checked for physical slips first, the key kept out of the repo, every page of the PR's comments read.
7. Write `book.md` from the anchors: each thing the voice does, with the quoted line that does it. Put the people (each POV character, and the narrator when scenes have `pov` `narrator` or key-decisions.md says `narrator_pov: limited N`: who they are and how close they stand; an adaptation's narrator is the novel's, not the translator's) and the decided rules under their headings, the narrator stance among them (step 2 of "Where the voice stage sits"). Turn the author's cut marks into `checks.md`, each check with the example it came from.
8. If tense follows POV and the map exists, fill `scenes.csv`'s `tense` column (`present` or `past`).
9. Commit: `git add -A -- . && git commit -m "Voice: <what changed>" && git push`

Voice work in coach mode: Claude writes no samples and doesn't run `voice sample` (it writes prose); if the author chooses to run it themselves, that's their call, and Claude can still read the marks with them. The author writes their own samples; they can still put them on a branch one sentence per line, open a PR, and save the winner in `anchors/` by hand. Ask what the author hears: tone, rhythm, distance, which passages by others feel close. Help the author pick or write their own anchor, then help them describe it in `book.md` by pointing at its lines, and turn their marks into `checks.md`.

Voice work in strict mode: no prose and no creative proposals from Claude, so Claude doesn't run `voice sample` (running it is the author's choice); the author writes the samples. Set up the folder (`elaborate --stage voice`), explain the anchor header format and the `book.md` sections, file the author's own passages and words into the right places, and fill the `tense` column from their decisions.

### Graphic-novel mode

Graphic novels don't use `reference/voice/`. Their voice stage is unchanged: `./storyforge elaborate --stage voice` writes `reference/voice-guide.md` and `reference/voice-profile.csv`, and the script reads them. Interactively, build the voice guide (per-character speech register, caption voice) with the author, then the profile below. The `_project` row of `voice-profile.csv` carries two graphic-novel fields:
- `caption_voice` — narration style: `journal-voiceover`, `omniscient`, `first-person`, `none`
- `lettering_style` — visual treatment hint: `loose-natural`, `typeset`, `hand-lettered-feel`

#### Voice Profile (graphic novels only)

`reference/voice-profile.csv` is a structured companion to a graphic novel's voice guide, with machine-parseable voice constraints the script prompts read. A prose book doesn't have one.

Format (pipe-delimited CSV):

| Column | Description |
|--------|-------------|
| `character` | Character ID from characters.csv, or `_project` for project-level fields |
| `preferred_words` | Semicolon-delimited words central to this voice (character rows only) |
| `banned_words` | Words that break this book's voice (project row only) |
| `metaphor_families` | Domains to source metaphors from (character rows only) |
| `rhythm_preference` | Sentence rhythm description (character rows only) |
| `register` | Prose register, e.g. "literary;restrained;precise" (project row only) |
| `dialogue_style` | How this character speaks (character rows only) |
| `caption_voice`, `lettering_style` | See above (project row only) |

Rules:
- The `_project` row holds book-wide constraints: `banned_words`, `register`, `caption_voice`, `lettering_style`. Leave character-specific fields empty.
- Each POV character gets one row with: `preferred_words` (10-20 words), `metaphor_families`, `rhythm_preference`, `dialogue_style`. Leave project-level fields empty.
- Character IDs must match the `id` column in `reference/characters.csv`.

Example:
```
character|preferred_words|banned_words|metaphor_families|rhythm_preference|register|dialogue_style
_project||journey;beacon;resonate;embrace|||literary;restrained;precise|
dorren-hayle|calibrated;systematic;categorical|...|cartography;measurement|short declarative for realization||clipped;formal
tessa-merrin|gritty;rough;worn;cracked|...|textile decay;weather|longer sensory runs||casual;irreverent
```

### Gap-Fill Stage (Interactive)

This mode activates when post-extraction data has validation gaps. Run `analyze_gaps()` from `elaborate.py` to categorize failures.

1. Present the gap summary to the author:
   - List each gap group with count of scenes and missing fields
   - Note any structural issues (MICE nesting, timeline order, knowledge wording)
2. Adapt to coaching level:
   - **Full:** "I found N gap types across M scenes. I'll fill the required ones — starting with the parallel batches." Present the craft-framework groups (`elaborate.CRAFT_FRAMEWORK_COLUMNS`: value_shift, turning_point, …) as optional and ask before filling them, even at full (#643: a scene needn't fit a framework).
   - **Coach:** "Here are the gaps I found. Which would you like me to work on?" (present each group as a choice)
   - **Strict:** "Validation report: X scenes missing `type`, Y missing `timeline_day`..." (data only)
3. Offer the standard two execution options:

> **Option A: Run it here**
> I'll work through the gaps in this conversation, filling fields by reading the prose.
>
> **Option B: Run it autonomously**
> Copy this command and run it in a separate terminal:
> ```bash
> cd [project_dir] && [plugin_path]/storyforge elaborate --stage gap-fill
> ```
> This creates a branch, fills gaps via batch API, validates, and opens a PR.

If Option A, work through each gap group interactively:
- For each scene with missing fields, read the prose excerpt and propose values
- Apply updates using `update_scene()` from `elaborate.py`
- After all groups, re-run validation
- If gaps remain, offer to continue

4. Commit: `git add -A -- . && git commit -m "Elaborate: gap-fill" && git push`

### Character Development (Interactive)

Character work can happen at any elaboration stage. The spine creates seed entries (protagonist wound/lie/need/want, antagonist force). This mode deepens them.

For each character:
1. **Wound** — the formative damage that shaped their worldview. "What's the worst thing that happened to them before the story starts?"
2. **Lie** — the false belief resulting from the wound. The operating system governing their decisions.
3. **Need** — what they actually require for wholeness (usually opposite of their Want).
4. **Want** — the conscious, concrete goal they pursue because of the Lie.
5. **Voice fingerprint** — how they speak, what they notice, their sentence rhythm.
6. **Relationships** — dynamic with every other major character. What each relationship tests.

Write what's settled as rows (**Bibles as Rows**): wound, lie, need and want as `trait` facts, each relationship as a `relationship` fact naming both people, the voice as two or three lines of them speaking (never a description of how they talk). Commit after each character. (A graphic novel updates `reference/character-bible.md`, whose Visual sections its script reads.)

### World Building (Interactive)

World building supports the architecture and scene map stages. Build what the story needs, not an encyclopedia.

Focus on: what creates pressure on characters? What constrains their choices? What makes the setting specific rather than generic?

Write each rule as a `world` fact (**Bibles as Rows**); keep `reference/bible-notes.md` for what really resists rows (a culture's feel, a history's shape), as terse lines. A rule not decided yet is a row ending in `?`: it stays on the gap list until it's answered. (A graphic novel updates `reference/world-bible.md` and `reference/systems-bible.md`.)

### Bibles as Rows (#657)

What's true about the people and the world is facts, not essays: the essays' phrasing leaked into drafts. In a prose book:

- **Facts** go in the ledger as plan facts. Write them to a pipe-delimited file (`type|subject|statement|known_by|category`, optional `scene_id`, `id`) and run `./storyforge bibles import FILE` (no cost; it commits; every file is checked before anything is written, so a row with a stray `|` or an unknown column writes nothing). `type` is `trait` (one person), `relationship` (names both people), `world` (a rule; subject empty or a place id) or `knowledge` (a secret: `known_by` who knows it from the start, `category` `secret` or `reveal`; only a knowledge fact can be a secret, and drafting doesn't see it before the scene that reveals it: the one whose brief's `knowledge_out` names it, or its `scene_id`). Statements are a few plain words, no interpretation. Leave `scene_id` empty for what's true from the start; name the scene for what becomes true there. Never edit `commitments.csv` by hand for this.
- **Voices**: two or three lines each in a `character|line` file, `./storyforge bibles import --voices FILE`.
- **Notes**: only what resists rows, `./storyforge bibles import --notes FILE` (appends the lines `reference/bible-notes.md` doesn't already have, so a re-run adds nothing).

**Converting an existing essay.** Read the essay with the author and turn each settled fact into a row, each voice description into lines of the character speaking (ask the author, or draft a few and let them choose), and what's left into terse notes. Don't carry over interpretation. Show the rows before importing, and import them with `--essay character-bible.md` (or `world-bible.md`, `systems-bible.md`): that marks them as this essay's conversion. Then `./storyforge bibles retire character-bible.md` moves the essay to `reference/archive/`, where Storyforge stops reading it and the author keeps it, and sets its `storyforge.yaml` artifact to `exists: false`. It's refused until the essay has a conversion (facts an elaborate stage wrote don't count) and, for the character bible, until every character one of its `##` headings names has at least one fact; it prints the facts per character and the headings it couldn't match. `--force` overrides, and the two-writers test then notes a retired essay with nothing standing in for it. Convert and retire one essay at a time; an unconverted essay keeps working as before.

**The two-writers test.** Could two writers draft from the plan and agree on every plot point? `./storyforge bibles` and `./storyforge validate` list the gaps code can see: a reveal no scene delivers (a secret no brief's `knowledge_out` names), a relationship hedged or naming only one side, a world rule that's still a question, a question in the notes. Take them to the author at each stage review; they're advisory, and the author may leave one open on purpose.

### Pacing Review (Interactive)

This mode activates when structural scoring shows Pacing Shape below target — typically "second half tension does not exceed first half." This is a creative decision, not a data fix.

1. **Show the data.** Read `reference/scene-intent.csv` and present the value_shift distribution by act (`act` column):
   - Count shifts by type per act: `++`, `+/-`, `-/-`, `-/--`, etc.
   - Show which act has the most negative/dramatic shifts
   - Highlight where the second half has fewer negative shifts than the first

2. **Explain what it means.** Pacing shape measures whether tension escalates through the novel. A novel where the first half has harder shifts than the second feels like it peaks early and coasts. The target is for the second half to have more tension than the first — not necessarily monotonic escalation, but the overall pressure should increase.

3. **Ask the author.** Present 2-3 specific scenes in the second half that currently have mild shifts (`+/+`, `+/-`) and ask: "Should any of these scenes hit harder? A `+/-` could become `-/-` if the victory comes with a real cost. A `+/+` could become `+/-` if the win isn't as clean as it seems."

4. **Apply changes.** For each scene the author wants to change, update `value_shift` in scene-intent.csv. Also update `outcome` in scene-briefs.csv if the shift change implies a different outcome (e.g., `yes` → `yes-but`).

5. **Verify.** Re-run `storyforge validate --structural` to see if the pacing score improved.

**Coaching level adaptation:**
- **Full:** Propose specific shift changes with reasoning. "Scene 38 (betrayal) is `+/-` — the betrayal is discovered but Zara still has her crew. If this became `-/--` — she loses Naji AND the crew fractures — the second half gets harder."
- **Coach:** Show the distribution, ask the author which scenes feel too easy. Don't propose specific changes.
- **Strict:** Show the raw shift counts per act. No interpretation.

### Outcome Review (Interactive)

This mode activates when Scene Function Variety is below target — typically one outcome type dominates (often `yes-but`).

1. **Show the data.** Count outcomes across all scenes:
   - `yes`: X scenes
   - `yes-but`: Y scenes
   - `no`: Z scenes
   - `no-and`: W scenes
   - `no-but`: V scenes
   - Show the percentage and whether any type is >40% of total

2. **Explain what it means.** Outcome variety creates emotional rhythm. A novel where 45% of scenes end `yes-but` feels like the same emotional beat repeating — the character wins but it costs something, over and over. Readers stop feeling the cost. Mixing in more `no` (flat failure) and `no-and` (failure that makes things worse) creates contrast that makes the `yes-but` scenes land harder. `no-but` (failure in which something genuinely goes their way) marks a turning tide; if several `no-but` gains get cancelled a few scenes later, that's Weiland's false progress — busy, not moving (see structural-craft.md §2).

3. **Ask the author.** Show scenes where the dominant outcome could change. Focus on scenes where the current outcome feels like the easiest choice:
   - "In this scene Mara tries to convince the council. The outcome is `yes-but`. What if it were `no` — the council refuses, full stop? That forces a harder decision in the next scene."
   - "This scene ends `yes-but` — what's the 'but'? If the cost is mild, maybe this should be a clean `yes` (rare, earned) or a `no` (harder stakes)."

4. **Apply changes.** Update `outcome` in scene-briefs.csv. If the outcome changes, its key_actions may need the matching event; if the author wrote a crisis or decision note, point out where it no longer fits (it's theirs to change).

5. **Verify.** Re-run scoring to confirm improvement.

**In a `faithful` adaptation** (`source:` block, `mode: faithful`), the source fixes most outcomes, and a relabelled one is drift that `score --source-fidelity` will flag. Before step 1, read `reference/source-map.csv`:
- A scene **keeps the source's outcome** when it is the last scene (by `seq`) whose `source_scenes` ends on a given source scene: every single-source scene, and the last part of a source scene split in several. Structural scoring's Function Variety leaves these out: outcome variety and the dominant-outcome finding count only the scenes the source leaves open, so the source's own mix is never marked down.
- Only the others are open: invented scenes (`treatment` `invent`) and the earlier parts of a split source scene. Propose changes to those alone, and give a split scene's earlier part a map `note` when its outcome is its own.
- The source's mix is the target, not "no type over 40%". Show the distribution as fixed and open counts, and say so when the source itself leans one way (Gawain ends 50% `yes-but`, which is the poem: every win costs him).

**Coaching level adaptation:**
- **Full:** Propose 3-5 specific outcome changes with dramatic reasoning.
- **Coach:** Show the distribution, ask which scenes feel emotionally repetitive.
- **Strict:** Show counts and percentages only.

## Step 5: Validate and Report

After any stage completes, run validation:

```bash
cd [project_dir] && [plugin_path]/storyforge validate
```

After briefs are complete (before drafting), also run structural scoring:

```bash
cd [project_dir] && [plugin_path]/storyforge validate --structural
```

This scores 8 dimensions of story quality from CSV data (deterministic, free, instant):
- Arc completeness, thematic concentration, pacing shape, character presence
- MICE thread health, knowledge chain integrity, scene function variety, structural completeness

If a dimension is below target, show the author the diagnosis (which includes craft-grounded explanations and specific CSV changes). It is a diagnostic, not a gate: pacing shape, function variety, arc shape and MICE health measure a book against craft frameworks, and a book may depart from them on purpose. Offer the changes; the author decides.

If registries are missing or thematic concentration is low, recommend reconciliation:
```bash
cd [project_dir] && [plugin_path]/storyforge reconcile
```

Also confirm the pitch tier still holds under the added structure:
- `storyforge score --story-power` — re-run the pitch-tier scorecard to
  confirm the structure still serves the premise after elaboration.
- `storyforge status` — confirm the ladder shows the expected rung as
  `solid` and surfaces no blockers before advancing.

Report results to the author. Validate prints two groups: blocking errors (missing required columns, duplicate seqs or ids, orphaned rows, schema and canon errors, a broken told_by chain, a faithful adaptation's coverage gaps) must be fixed before advancing; advisory diagnostics never hold a stage. **Every craft-framework check is advisory** (#643): an empty value_shift, turning_point, action_sequel, emotional_arc or value_at_stake (a brief's goal, conflict, crisis and decision are the author's notes, never reported), MICE nesting, flat polarity, scene-type and turning-point runs, the action/sequel balance. Mention them as observations the author can use; never press a scene toward a turn and a landing it doesn't want. Structural scoring findings are advisory too.

## Step 6: Ensure Feature Branch

Before making any changes, check the current branch:
```bash
git rev-parse --abbrev-ref HEAD
```
- If on `main` or `master`: create a feature branch first:
  ```bash
  git checkout -b "storyforge/elaborate-$(date '+%Y%m%d-%H%M')"
  ```
- If on any other branch: stay on it — do not create a new branch.

## Step 7: Commit After Every Deliverable

Every stage output gets committed immediately:

```bash
git add -A -- . && git commit -m "Elaborate: [stage name]" && git push
```

Do not batch multiple stages into one commit.
