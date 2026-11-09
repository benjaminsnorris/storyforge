# Scene Data Schema

Scenes are the atomic unit of a Storyforge project. Scene files are **pure prose** (no YAML frontmatter) — the filename is the scene ID. All metadata lives in pipe-delimited CSV files in `reference/`.

## Data Model

Scene data is split across three CSV files, each with a clear purpose:

- **`reference/scenes.csv`** — structural identity and position (POV, location, timeline, status, word counts)
- **`reference/scene-intent.csv`** — narrative dynamics and tracking (function, value shifts, characters, MICE threads)
- **`reference/scene-briefs.csv`** — drafting contracts: the scene's facts (outcome, key actions, knowledge and physical states), plus the author's optional notes (goal, conflict, crisis, decision, key dialogue...)

All three files use pipe (`|`) as the field delimiter, semicolon (`;`) for array values within a column, and `id` as the join key. The first row is always the header. The `id` column in intent and briefs matches scenes.csv.

### Python Helpers

The `storyforge.elaborate` module provides a unified interface over all three files:

```python
from storyforge.elaborate import get_scene, get_scenes, update_scene, add_scenes

scene = get_scene('hidden-canyon', 'reference/')           # All columns merged
scenes = get_scenes('reference/', columns=['id', 'pov', 'value_shift'])  # Selective
scenes = get_scenes('reference/', filters={'pov': 'Lena Callis'})       # Filtered
update_scene('hidden-canyon', 'reference/', {'status': 'drafted', 'word_count': '2400'})
```

### Legacy Format

Projects created before v0.40.0 used a two-file model with fewer columns. Run `./storyforge extract` to populate the three-file model from existing prose. The write and score scripts auto-detect which model is in use.

## Column Reference

**Source of truth:** `scripts/lib/python/storyforge/schema.py` — the `COLUMN_SCHEMA` dict defines every column's constraint type, allowed values, registry mappings, pipeline stage, and description. The tables below are generated from that schema. To regenerate:

```python
from storyforge.schema import dump_schema_markdown
print(dump_schema_markdown())
```

### Constraint Types

| Type | Validation | Normalization |
|------|-----------|---------------|
| `enum` | Value must be in a fixed set | N/A — values are already canonical |
| `registry` | Each value must exist as id, name, or alias in a registry CSV | Resolved to canonical id via alias map |
| `mice` | Each entry is `+name` (open), `-name` (close) or a bare `name` (mention), optionally `type:name`; valid type; the name (id, name or alias, any case; `type:name` first) names exactly one registered thread; no `[note]` | Name resolved via alias map, type dropped |
| `integer` | Must parse as int | N/A |
| `boolean` | Must be `true`, `false`, or empty | N/A |
| `free_text` | No constraint | N/A |
| `scene_ids` | Each semicolon-separated value must exist as an id in scenes.csv | N/A |

### Registry Files

| Registry | Columns | Used by |
|----------|---------|---------|
| `characters.csv` | id, name, aliases, role | pov, characters, on_stage |
| `locations.csv` | id, name, aliases | location |
| `values.csv` | id, name, aliases | value_at_stake |
| `motif-taxonomy.csv` | id, name, aliases, tier | motifs |
| `mice-threads.csv` | id, name, type, aliases | mice_threads |

### scenes.csv — structural identity

| Column | Constraint | Stage | Description |
|--------|-----------|-------|-------------|
| `id` | free_text | spine | Unique, permanent scene identifier: a 3-5 word slug naming the scene's core event (e.g., gatsby-reunites-with-daisy), never its position (no act1-sc03, scene-12). Never renamed when the scene moves or its title changes; order lives in `seq`. Also the filename (scenes/{id}.md). |
| `seq` | integer | spine | Reading order. Scenes are sorted by seq. |
| `title` | free_text | spine | Scene title — evocative, used for reference. |
| `part` | integer | architecture | Book part this scene belongs to, from the manuscript's part headings; empty if the book has no parts. |
| `act` | integer | architecture | Structural act this scene belongs to (1, 2, 3, ...). Drives act-level scoring, act proportions, and --act filters. |
| `pov` | registry: characters.csv | architecture | POV character. Normalized against reference/characters.csv. `narrator` is reserved: the book's narrator tells the scene (never a characters.csv entry, never needs to be on stage); The impersonal variants ("Omniscient narrator", "omniscient", "third-person narrator", and "the narrator" when no character has that name) normalize to it; a narrator who is a person (first person, "unnamed-narrator", a registered "The Narrator") is a character and keeps their id. A `narrator_pov` line Storyforge can't read is warned about and read as `allowed`. key-decisions.md's `narrator_pov: allowed \| limited N \| off` says whether the narrator may hold scenes (default `allowed`). |
| `location` | registry: locations.csv (array) | map | Places where the scene's action happens on the page, in order: usually one; the first is where the scene opens, the last where it ends. Semicolon-separated. Never a route or transition as one place. Normalized against reference/locations.csv. |
| `timeline_day` | integer | map | Chronological position (day number within the story). |
| `time_mode` | enum: frame, scene, summary, vision | map | How the scene sits in time: scene (its action plays out on its day; the default when empty), summary (it covers a stretch of time; timeline_day is where it starts), frame (narration from after the story, looking back; never the story's present), or vision (events a character is shown that the story doesn't treat as fixed, such as A Christmas Carol's future; timeline_day is the day shown if the text fixes one; never the story's present). |
| `timeline_date` | edtf | map | The calendar date the scene's own text states, in EDTF; empty when it states none. Unknown digits are X and never filled in: `XXXX-07-04` (no year given), `1922-22` (summer 1922), `1917~` (around 1917), `1922-06/1922-09` (a stretch). |
| `told_by` | scene_ids | map | For an embedded tale (a story, song or report a character gives inside another scene, such as Odysseus's tale to the Phaeacians or a digression the narrator makes from a scene), the id of the one scene that tells it; empty for a scene lived on the page. The told scene's pov is its teller, who is in the telling scene's cast. timeline_day is when the told events happened, and time_mode is unchanged: like a flashback, a told scene is a device, never an error. |
| `time_of_day` | enum: afternoon, dawn, dusk, evening, morning, night, unstated | map | Time of day when the scene takes place; unstated when the scene's text gives none (blank means not filled in yet). |
| `duration` | free_text | map | In-story duration (e.g., "2 hours", "30 minutes"). |
| `type` | enum: action, character, confrontation, dialogue, introspection, plot, revelation, transition, world | map | Narrative purpose of the scene. |
| `status` | enum: architecture, briefed, drafted, mapped, polished, spine | all | Elaboration depth — tracks how far the scene has progressed through the pipeline. |
| `word_count` | integer | draft | Actual word count (0 until drafted). |
| `target_words` | integer | map | Target word count for the scene. |

### scene-intent.csv — narrative dynamics

| Column | Constraint | Stage | Description |
|--------|-----------|-------|-------------|
| `id` | free_text | spine | Join key — matches scenes.csv. |
| `function` | free_text | spine | Why this scene exists — must be specific and testable. |
| `action_sequel` | enum: action, sequel | architecture | Action/sequel pattern (Swain): action = goal/conflict/outcome, sequel = reaction/dilemma/decision. |
| `emotional_arc` | free_text | architecture | Emotional journey: start to end (e.g., "controlled competence to buried unease"). |
| `value_at_stake` | registry: values.csv | architecture | The abstract value being tested. Normalized against reference/values.csv (McKee). |
| `value_shift` | enum: +/+, +/++, +/-, -/+, -/-, -/-- | architecture | Polarity change (Story Grid). A scene that doesn't shift a value is a nonevent. |
| `turning_point` | enum: action, revelation | architecture | What turns the scene — action (character does something) or revelation (new information). |
| `characters` | registry: characters.csv (array) | map | Everyone on stage, plus anyone whose actions are narrated in the scene or who is discussed at length; not a name only in a patronymic, epithet, title, simile, comparison or genealogy. Normalized against reference/characters.csv. |
| `on_stage` | registry: characters.csv (array) | map | Everyone present who acts or speaks, including a god or other power acting on the scene from afar, or present in disguise (under their own id). A subset of characters. |
| `mice_threads` | mice: mice-threads.csv | map | MICE threads (Kowal): +name where the thread begins (once), -name where it resolves (at most once), bare name where a scene advances or touches an open thread. Threads may interleave; nesting is guidance, not a rule. |

### scene-briefs.csv — drafting contracts

A brief keeps the scene's **facts**, not its staging (#644): the events (`key_actions`, the turn included), the `outcome`, and the knowledge and physical state in and out. `elaborate --stage briefs` writes those as terse notes, with no interpretation: about 3 to 6 events, never more than `elaborate.MAX_BRIEF_EVENTS` (6) or 2.5 for each 1,000 target words (`brief_event_limit`), the whole key_actions cell under `KEY_ACTIONS_MAX_CHARS` (200) characters, the limits hone flags past. `goal`, `conflict`, `crisis`, `decision`, `key_dialogue`, `subtext`, `emotions`, `motifs` and `motif_details` (`elaborate.AUTHOR_NOTE_COLUMNS`; the first four since plan decision 9) are the author's optional notes in a prose book: the briefs stage never generates them (it writes only the columns it asks for, `prompts_elaborate.BRIEFS_OUTPUT_HEADER`), nothing reports one empty (validate, hone's gaps, the status floors, structural completeness and the story-power pre-pass check only the facts), no model rewrites them (revise's source-drift fix shows them and reports drift in them; its old dramatic-opposition rewrite of the four is gone; hone reports findings on them), scoring scores only the ones filled, the briefs stage keeps them as the author wrote them, and drafting and the gate read them only when filled. Extraction still records them from prose that exists. A graphic novel's briefs stage writes `key_dialogue` as the balloon text its panel script carries. A source line the author wants verbatim goes into `key_dialogue` by hand, marked `must:`. `outcome` and `key_actions` are the brief's facts (`elaborate.BRIEF_FACT_COLUMNS`), required from `briefed` on.

| Column | Constraint | Stage | Description |
|--------|-----------|-------|-------------|
| `id` | free_text | brief | Join key — matches scenes.csv. |
| `goal` | free_text | brief | Optional, the author's note: the POV character's concrete objective entering the scene (Swain), filled by hand and never generated for a prose book (plan decision 9). Extraction records it from prose. |
| `conflict` | free_text | brief | Optional, the author's note: what specifically opposes the POV character in the scene, filled by hand and never generated for a prose book (plan decision 9). Extraction records it from prose. |
| `outcome` | enum: yes, no, yes-but, no-and, no-but | brief | How the scene ends for the POV character: yes (it goes their way) / no (it goes against them) / yes-but (it goes their way, with a new complication or cost) / no-and (it goes against them, and things get worse) / no-but (it goes against them, but something genuinely goes their way). Bickham's scene disasters plus Kowal's no-but; see structural-craft.md §2. |
| `crisis` | free_text | brief | Optional, the author's note: the dilemma, a best bad choice or irreconcilable goods (Story Grid), filled by hand and never generated for a prose book (plan decision 9). Extraction records it from prose. |
| `decision` | free_text | brief | Optional, the author's note: what the character actively chooses in response to the crisis, filled by hand and never generated for a prose book (plan decision 9). Extraction records it from prose. |
| `knowledge_in` | registry: commitments.csv, type knowledge (array) | brief | Fact IDs the POV character knows entering. Normalized against the knowledge facts in reference/commitments.csv (the commitments ledger). See knowledge-guidelines.md for fact selection criteria. |
| `knowledge_out` | registry: commitments.csv, type knowledge (array) | brief | Fact IDs the POV character knows leaving. Includes knowledge_in plus new facts learned. Target 0.5-1.5 new facts per scene. See knowledge-guidelines.md. |
| `key_actions` | free_text | brief | The scene's events, in order, the turn included: who does what, never scripted lines. A brief fact, required from `briefed` on (#644). An item starting `must:` is a beat the author requires (see below). |
| `key_dialogue` | free_text | brief | Optional, the author's: lines the author wants in the scene, filled by hand and never generated for a prose book (#644; a graphic novel's briefs stage writes it as balloon text). Label each quoted line's speaker (`Name: "line"`); see scene-column-guide.md. Only an item starting `must:` is required, word for word. |
| `emotions` | free_text | brief | Optional, the author's note: emotional beats in sequence, filled by hand and never generated for a prose book (#644). Extraction records them from prose. |
| `motifs` | registry: motif-taxonomy.csv (array) | brief | Optional: recurring images/symbols the scene has. Never placed by the briefs stage (#644): a motif is noticed in the draft and recorded after (extraction, or the author). Normalized against reference/motif-taxonomy.csv. |
| `subtext` | free_text | brief | Optional, the author's note: what is happening beneath the surface, filled by hand and never generated for a prose book (#644). "Character says X but means Y; do not state Y directly." |
| `continuity_deps` | scene_ids | brief | Scene IDs this scene depends on (for parallel drafting). Each entry must exist in scenes.csv. |
| `has_overflow` | boolean | brief | Whether briefs/{id}.md exists for extended detail. |
| `physical_state_in` | registry: commitments.csv, type physical (array) | brief | Physical state IDs active when scene begins. Normalized against the physical states in reference/commitments.csv. |
| `physical_state_out` | registry: commitments.csv, type physical (array) | brief | Physical state IDs active when scene ends. Includes physical_state_in plus new, minus resolved. |
| `motif_details` | free_text | brief | Optional, the author's note: how the scene's motifs appear in it (semicolon-separated). `motifs` names them by id; this keeps what each looks like here, including images that recur nowhere else. Never generated by the briefs stage (#644); extraction records it from prose. |

**Required beats: the `must:` marker** (#642). A brief is a plan, and the prose wins: the gate reports a brief item the prose doesn't deliver (a broken promise) as `ADVISORY`, lists it in `working/gate-advisory.csv`, `storyforge status` and at the end of `write`, `revise` and `check`, and doesn't stop the scene for it. To require a beat, start its `key_actions` or `key_dialogue` item with `must:`:

```
key_actions: Achilles drags Hector's body;must: Priam kisses Achilles' hands
key_dialogue: must: Priam: "I have kissed the hands of the man who killed my son"
```

- The marker is `must`, any case, then a colon, any spacing (`must:`, `MUST :`), at the start of the item (items are `;`-separated), before any speaker label: `must: Priam: "..."`, not `Priam: must: "..."`. A `must:` anywhere else in an item, or in a field that takes no marker, marks nothing; the gate reports it, and so it does an item that is only `must:`.
- A broken `must` beat stops the scene, like a contradiction. When the brief has a `must` beat, a broken promise is advisory only when the check's words for it are plainly an unmarked item (the whole item, or four or more of its words in a row); a paraphrase or a short partial quote of a `must` beat stops the scene. In doubt, `must`.
- The quoted words in a `must` item (or a `key_dialogue` line with no quotes, with or without its label) must be in the prose word for word, or split across quotations in one paragraph by at most six words of narration outside the quotation marks (a speech tag: `"Sing," he said, "goddess"`). Code checks this, so a paraphrase, or words put inside the quotation, doesn't keep a `must` line. A scripted part under three words is too short to check this way: the gate notes it and leaves it to the check. A faithful adaptation marks the source lines it keeps verbatim this way.
- A `must` beat is the author's. Nothing Storyforge writes drops or rewords one: elaborate's briefs stage, hone's rewrites, revise's source-drift fix and a forced extract or enrich re-read put back any `must` item their reply lost or reworded, word for word, and leave out a `must:` item the reply made up (only the author marks a beat). Each such change is logged.
- Other promise fields (`outcome`, `knowledge_out`, `physical_state_out`) take no marker. A broken `outcome` promise is advisory, even when its words overlap a `must` beat. A broken `knowledge_out` or `physical_state_out` promise is advisory too, except for a binding registry fact the ledger sets up in this very scene (its `scene_id`): the prose is its only evidence and later scenes are read against it, so that one stops the scene until the prose establishes it or the fact is moved or rejected.

## Elaboration Stages

The `status` field tracks how deeply a scene has been elaborated:

| Status | What's populated | Pipeline stage |
|--------|-----------------|---------------|
| `spine` | id, seq, title, function | Stage 1: irreducible story events |
| `architecture` | + act, pov, action_sequel, emotional_arc, value_shift, turning_point | Stage 2: structure |
| `mapped` | + location, timeline_day, time_of_day, duration, type, characters, on_stage, mice_threads | Stage 3: full scene map |
| `briefed` | + outcome, key_actions, knowledge_in/out, physical_state_in/out, continuity_deps (goal, conflict, crisis, decision, key_dialogue, subtext, emotions, motifs only by the author) | Stage 4: the scenes' facts |
| `drafted` | + word_count (prose exists in scenes/{id}.md) | After drafting |
| `polished` | Prose has been through craft polish | After polish pass |

## Validation

Run `./storyforge validate` to check both structural integrity and schema compliance. It prints its structural findings in two groups: **blocking** errors, which fail validation (exit 1) and hold an elaborate stage's phase, then **advisory** diagnostics, which never do.

**Checks catch errors; craft frameworks advise** (#643). Every check of conformity to a craft framework is advisory: a scene's empty craft-framework columns (`action_sequel`, `emotional_arc`, `value_at_stake`, `value_shift`, `turning_point`; a brief's goal, conflict, crisis and decision are the author's notes, which nothing checks), MICE nesting and operations, flat polarity, scene-type and turning-point runs, and in `storyforge status` and `score --level` the architecture's action/sequel balance. These are useful notes, but a book may leave a scene without a turn or a landing on purpose. Errors still block: a required column that isn't a craft one, duplicate seqs or ids, orphaned rows, a broken `told_by` chain, schema errors, canon errors, and for a faithful adaptation its coverage gaps and unnamed cast.

**Structural checks:**
- **Identity:** Every ID in intent/briefs exists in scenes.csv
- **Completeness:** Required columns for the scene's status are populated (blocking: `required-columns-{id}`); the craft-framework ones among them are a separate advisory finding (`craft-columns-{id}`), which `elaborate --gap-fill` still fills
- **Timeline (advisory):** flashbacks and crosscuts (scenes set before the story's present) are listed and gauged, never errors
- **Knowledge flow:** knowledge_in references match prior scenes' knowledge_out
- **Thread management (advisory):** each MICE thread opens once and closes at most once; interleaving is reported, not an error; no thread dormant >8 scenes between its open and its close (a mention before the open or after the close is allowed and not counted; a close before the open is reported; `elaborate --stage mice-fill` adds bare-name mentions inside the span)
- **Pacing (advisory):** flat polarity stretches (3+ scenes), action/sequel runs and turning-point runs (4+) are reported
- **Brief names (advisory):** names in a brief's goal, conflict, outcome, crisis, decision, key actions and dialogue, knowledge, physical states and subtext that no scene's prose and no reference file uses (scene-briefs.csv and scene-intent.csv don't count: a brief rewrite that drifted writes them). A draft takes its facts from the brief, so it would write these people into the book. One finding per scene, naming each field and its names, and one for each thing it couldn't check (a missing fact column, no `id` column, an unreadable or non-UTF-8 file), so a pass means checked and clean. Reference files include subfolders (canon/, source/); a graphic novel's pages count as prose. The briefs never vouch for each other, drafted or not (a drift puts the same stray in several briefs): a real name a scene plans before it is drafted belongs in characters.csv or locations.csv. A run of capitalized words ("Danny Olinsky") is one name; possessives, plurals, words the book uses in any case (Unicode names included), weekdays, months, titles ("Detective", "Dr.") and institutional words ("Internal Affairs") pass. Only the first word of a run that opens a sentence, a beat (after `;`) or a `[note]` is excused, and only when no brief uses that word as a name (capitalized mid-sentence, or possessive where a sentence or beat opens). It still over-reports drug and brand names, so check each against the book. `validate` lists advisories on every run; elaborate and extract list them only when validation otherwise fails

**Schema checks:**
- **Enum values:** Constrained columns contain only allowed values
- **Registry references:** Character, location, value, motif, and MICE thread names resolve against their registry CSVs
- **Integers:** Numeric columns contain valid integers
- **MICE format:** Each entry is an open (`+name`), a close (`-name`) or a mention (bare `name`), optionally typed (`+type:name`) with a valid type, naming exactly one registered thread. A name, alias or bare name two threads share is reported as a registry problem (write `type:name`, or rename one) and an entry using it is ambiguous. With no registry, a slug names a thread and prose does not. Readers that skip a malformed entry say so: structural validation (`mice-unread`), MICE health (a finding), dormancy and mice-fill (WARNINGs naming scene and entry; mice-fill leaves a thread with such entries unfilled)

Use `--no-schema` to skip schema validation. Use `--json` for machine-readable output.

## Scoring

Two types of scoring reference scene data:

- **Structural scoring** (`score_structure`): Pre-draft check on brief quality (0-5 per scene). Checks the brief's facts (outcome, key_actions), value shift and knowledge flow; goal, conflict, crisis and decision are optional notes.
- **Brief fidelity scoring** (`fidelity-scores.csv`): Post-draft check — did the prose deliver what the brief promised? Scores up to 9 elements: goal, conflict, outcome, crisis, decision, key_actions, key_dialogue, emotions, knowledge. An element the brief leaves empty (an optional note) is left unscored.

## CSV Format Conventions

- **Delimiter:** `|` (pipe character)
- **Array separator:** `;` (semicolon) within a single column
- **Header row:** Always present, always the first line
- **No quoting:** Values should not contain pipe characters
- **Empty values:** Leave the field empty between delimiters
- **Encoding:** UTF-8

## Scene File Format

Scene files live in `scenes/` as **pure Markdown with no frontmatter**:

```
scenes/hidden-canyon.md → id is "hidden-canyon"
```

The file contains only prose. All metadata lives in the CSV files.

## Scene ID Convention

- **Format:** lowercase, hyphen-separated words (e.g., `hidden-canyon`, `sheriffs-ledger`)
- **Length:** 2-5 words — specific enough to identify, short enough to type
- **Content-based:** Describes what happens or the key image, not sequence position
- **No numbers:** Ordering lives in the `seq` column
- **Also the filename:** `scenes/{id}.md`

## What Is a Scene?

A scene is a single continuous pass of experience — one camera angle before the lens shifts. The moment the POV changes, or time jumps, or location shifts, that's a new scene.

Scenes are designed to be **reshuffled**. The `seq` column is a working sequence, not a permanent assignment.
