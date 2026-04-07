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
3. `reference/scene-intent.csv` — check column depth (function only = spine; has value_shift = architecture; has characters = mapped)
4. `reference/scene-briefs.csv` — check if it exists and has non-empty rows
5. `reference/story-architecture.md` — does it exist?
6. `reference/character-bible.md` — does it exist?

## Registry Awareness

Read all registry files in `reference/` to know the canonical IDs for normalized fields:

- `reference/characters.csv` — canonical character IDs
- `reference/locations.csv` — canonical location IDs
- `reference/values.csv` — canonical value IDs
- `reference/knowledge.csv` — canonical knowledge fact IDs
- `reference/motif-taxonomy.csv` — canonical motif IDs
- `reference/mice-threads.csv` — canonical MICE thread IDs

**When writing any CSV field value, use canonical IDs from these registries:**

| CSV field(s) | Registry |
|---|---|
| `pov`, `characters`, `on_stage` | characters.csv |
| `location` | locations.csv |
| `value_at_stake` | values.csv |
| `knowledge_in`, `knowledge_out` | knowledge.csv |
| `motifs` | motif-taxonomy.csv |
| `mice_threads` | mice-threads.csv (format: `+type:id` or `-type:id`) |

**When the author introduces a new character, location, value, knowledge fact, motif, or MICE thread that does not exist in a registry:** add it to the appropriate registry CSV first, then use the new ID in scene data.

## Step 2: Determine Current Stage

Based on the project state, identify where the author is:

| Phase in YAML | scenes.csv rows | Intent depth | Briefs | Validation | Current stage |
|---------------|----------------|--------------|--------|------------|---------------|
| spine | 0 | — | — | — | Needs spine |
| spine | 5-10 | function only | — | — | Spine done, ready for architecture |
| architecture | 15-25 | has value_shift | — | — | Architecture done, ready for map |
| scene-map | 40-60 | has characters, on_stage | — | — | Map done, ready for briefs |
| briefs | 40-60 | full | has goal/conflict/outcome | — | Briefs done, ready for drafting |
| drafting+ | status=drafted | populated but gaps | populated | failures > 0 | **Gap-fill mode** |
| drafting+ | — | — | — | passes | Past elaboration — redirect to forge |

## Step 3: Determine Mode

Based on the author's request, determine the mode:

### Specific requests (always honored, bypass auto-advance):

- **"Start a new novel"** / **"Let's begin"** → Start at spine. Ask for the seed (logline, genre, characters, themes, constraints). Whatever they give you is the seed.
- **"Work on the spine/architecture/map/briefs"** → Go to that specific stage.
- **"Develop the voice"** / **"Voice guide"** / **"Style"** → Voice development (see Voice Stage below). Typically happens after architecture and before briefs.
- **"Deepen characters"** / **"Work on [character name]"** → Character development. During elaboration, this deepens the character bible entries. The spine creates seed entries; this mode enriches them with wound/lie/need structure, voice fingerprints, and relationship dynamics.
- **"Build the world"** / **"World building"** → World bible development. During elaboration, world building supports the architecture and scene map stages.
- **"Story architecture"** / **"Theme"** / **"Structure"** → Story architecture refinement. The spine creates the initial architecture; this mode deepens thematic throughlines, conflict structure, and arc planning.
- **"Fix pacing"** / **"Pacing shape"** / **"Second half doesn't escalate"** → Pacing review (see Pacing Review below).
- **"Fix outcomes"** / **"Scene function variety"** / **"Too many yes-but"** → Outcome review (see Outcome Review below).
- **"Validate"** → Run validation on the current state.
- **Status question** → Report current stage, scene count, validation state.

### Auto-advance (unspecified requests — "elaborate", "what's next", "keep going"):

When the author doesn't specify a mode, detect the current stage from Step 2 and act based on coaching level:

| Detected State | Action |
|---|---|
| No scenes.csv (or 0 rows) | Start spine |
| Spine done (5-10 rows, function only) | Run architecture |
| Architecture done (has value_shift) | Run scene map |
| Map done (has characters, on_stage) | Run briefs |
| Briefs done, validation passes | Announce ready for drafting, redirect to forge |
| Drafted with validation failures > 0 | Run gap-fill |
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
> cd [project_dir] && [plugin_path]/scripts/storyforge-elaborate --stage [stage]
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

### Spine Stage (Interactive)

1. Gather the seed from the author (or read from logline)
2. Propose the story architecture: premise, theme, three-level conflict, ending
3. Propose protagonist with wound/lie/need/want
4. Propose 5-10 spine events as a numbered list
5. Once approved, write to:
   - `reference/story-architecture.md`
   - `reference/character-bible.md`
   - `reference/scenes.csv` (id, seq, title, status=spine)
   - `reference/scene-intent.csv` (id, function)
6. Commit: `git add -A && git commit -m "Elaborate: spine" && git push`

### Architecture Stage (Interactive)

1. Read the spine scenes and story architecture
2. Expand to 15-25 scenes: add supporting scenes, transitions, subplot introductions
3. Assign parts, POV, scene types (action/sequel), value shifts, turning points
   - **Use canonical IDs from registries** for pov, characters, locations, value_at_stake. Add new registry entries for any new characters/locations/values introduced at this stage.
4. Deepen character bible with supporting characters
5. Create world bible if needed
6. Write updates to all CSV files and reference docs
7. Run validation — fix any issues before committing
8. Commit: `git add -A && git commit -m "Elaborate: architecture" && git push`

### Scene Map Stage (Interactive)

1. Read architecture scenes and reference materials
2. Expand to 40-60 scenes: fill gaps, add transitions
3. Assign locations, timeline, characters, MICE threads — **all registry-backed fields must use canonical IDs** (characters, locations, values, mice_threads). Add new registry entries for anything introduced at this stage.
4. Write updates
5. Run validation — MICE nesting, timeline, character references
6. Commit: `git add -A && git commit -m "Elaborate: scene map" && git push`

### Briefs Stage (Interactive)

1. Read full scene map and all reference materials
2. For each scene, define: goal, conflict, outcome, crisis, decision, knowledge_in, knowledge_out, key_actions, key_dialogue, emotions, motifs, continuity_deps
   - **Use canonical IDs from registries** for knowledge_in, knowledge_out (knowledge.csv), motifs (motif-taxonomy.csv). Add new registry entries for any new knowledge facts or motifs introduced at this stage.
3. **Knowledge wording must be exact** — knowledge_out from scene N becomes knowledge_in for later scenes, matched literally. Use registry IDs rather than free-text to ensure exact matching.
4. Maximize scenes with no continuity_deps (these can be drafted in parallel)
5. Write updates
6. Run validation — knowledge flow, completeness, DAG check
7. Commit: `git add -A && git commit -m "Elaborate: briefs" && git push`

### Voice Stage (Interactive)

Voice development typically happens after architecture (you know your POV characters and scene types) and before briefs (the briefs need voice rules). Can also run standalone at any point.

1. Read existing reference materials (character bible for voice fingerprints, story architecture for tone)
2. If voice guide doesn't exist: explore the author's influences, genre voice expectations, POV rules, prose register. Build `reference/voice-guide.md` through conversation.
3. If voice guide exists: refine it. Test against sample scenes. Develop POV-specific rules. Identify areas where voice drifts.
4. For each POV character, define: their unique speech patterns, what metaphors they reach for, what they notice first, what they never say, their sentence rhythm.
5. Commit: `git add -A && git commit -m "Elaborate: voice guide" && git push`

Voice work in coach mode: ask questions about what the author hears in their head — tone, rhythm, register. Don't propose voice; help the author discover it.

Voice work in strict mode: collect the author's voice preferences, format into the voice guide structure, provide the template.

### Gap-Fill Stage (Interactive)

This mode activates when post-extraction data has validation gaps. Run `analyze_gaps()` from `elaborate.py` to categorize failures.

1. Present the gap summary to the author:
   - List each gap group with count of scenes and missing fields
   - Note any structural issues (MICE nesting, timeline order, knowledge wording)
2. Adapt to coaching level:
   - **Full:** "I found N gap types across M scenes. I'll fill them all — starting with the parallel batches."
   - **Coach:** "Here are the gaps I found. Which would you like me to work on?" (present each group as a choice)
   - **Strict:** "Validation report: X scenes missing `type`, Y missing `timeline_day`..." (data only)
3. Offer the standard two execution options:

> **Option A: Run it here**
> I'll work through the gaps in this conversation, filling fields by reading the prose.
>
> **Option B: Run it autonomously**
> Copy this command and run it in a separate terminal:
> ```bash
> cd [project_dir] && [plugin_path]/scripts/storyforge-elaborate --stage gap-fill
> ```
> This creates a branch, fills gaps via batch API, validates, and opens a PR.

If Option A, work through each gap group interactively:
- For each scene with missing fields, read the prose excerpt and propose values
- Apply updates using `update_scene()` from `elaborate.py`
- After all groups, re-run validation
- If gaps remain, offer to continue

4. Commit: `git add -A && git commit -m "Elaborate: gap-fill" && git push`

### Character Development (Interactive)

Character work can happen at any elaboration stage. The spine creates seed entries (protagonist wound/lie/need/want, antagonist force). This mode deepens them.

For each character:
1. **Wound** — the formative damage that shaped their worldview. "What's the worst thing that happened to them before the story starts?"
2. **Lie** — the false belief resulting from the wound. The operating system governing their decisions.
3. **Need** — what they actually require for wholeness (usually opposite of their Want).
4. **Want** — the conscious, concrete goal they pursue because of the Lie.
5. **Voice fingerprint** — how they speak, what they notice, their sentence rhythm.
6. **Relationships** — dynamic with every other major character. What each relationship tests.

Update `reference/character-bible.md` and commit after each character.

### World Building (Interactive)

World building supports the architecture and scene map stages. Build what the story needs, not an encyclopedia.

Focus on: what creates pressure on characters? What constrains their choices? What makes the setting specific rather than generic?

Update `reference/world-bible.md` (and `reference/systems-bible.md` if the world has a formal system like magic or technology).

### Pacing Review (Interactive)

This mode activates when structural scoring shows Pacing Shape below target — typically "second half tension does not exceed first half." This is a creative decision, not a data fix.

1. **Show the data.** Read `reference/scene-intent.csv` and present the value_shift distribution by act/part:
   - Count shifts by type per part: `++`, `+/-`, `-/-`, `-/--`, etc.
   - Show which part has the most negative/dramatic shifts
   - Highlight where the second half has fewer negative shifts than the first

2. **Explain what it means.** Pacing shape measures whether tension escalates through the novel. A novel where the first half has harder shifts than the second feels like it peaks early and coasts. The target is for the second half to have more tension than the first — not necessarily monotonic escalation, but the overall pressure should increase.

3. **Ask the author.** Present 2-3 specific scenes in the second half that currently have mild shifts (`+/+`, `+/-`) and ask: "Should any of these scenes hit harder? A `+/-` could become `-/-` if the victory comes with a real cost. A `+/+` could become `+/-` if the win isn't as clean as it seems."

4. **Apply changes.** For each scene the author wants to change, update `value_shift` in scene-intent.csv. Also update `outcome` in scene-briefs.csv if the shift change implies a different outcome (e.g., `yes` → `yes-but`).

5. **Verify.** Re-run `storyforge validate --structural` to see if the pacing score improved.

**Coaching level adaptation:**
- **Full:** Propose specific shift changes with reasoning. "Scene 38 (betrayal) is `+/-` — the betrayal is discovered but Zara still has her crew. If this became `-/--` — she loses Naji AND the crew fractures — the second half gets harder."
- **Coach:** Show the distribution, ask the author which scenes feel too easy. Don't propose specific changes.
- **Strict:** Show the raw shift counts per part. No interpretation.

### Outcome Review (Interactive)

This mode activates when Scene Function Variety is below target — typically one outcome type dominates (often `yes-but`).

1. **Show the data.** Count outcomes across all scenes:
   - `yes`: X scenes
   - `yes-but`: Y scenes
   - `no`: Z scenes
   - `no-and`: W scenes
   - Show the percentage and whether any type is >40% of total

2. **Explain what it means.** Outcome variety creates emotional rhythm. A novel where 45% of scenes end `yes-but` feels like the same emotional beat repeating — the character wins but it costs something, over and over. Readers stop feeling the cost. Mixing in more `no` (flat failure) and `no-and` (failure that makes things worse) creates contrast that makes the `yes-but` scenes land harder.

3. **Ask the author.** Show scenes where the dominant outcome could change. Focus on scenes where the current outcome feels like the easiest choice:
   - "This scene's goal is 'convince the council.' The outcome is `yes-but`. What if it were `no` — the council refuses, full stop? That forces a harder decision in the next scene."
   - "This scene ends `yes-but` — what's the 'but'? If the cost is mild, maybe this should be a clean `yes` (rare, earned) or a `no` (harder stakes)."

4. **Apply changes.** Update `outcome` in scene-briefs.csv. If the outcome changes, the brief's crisis/decision may also need adjustment — offer to update those too.

5. **Verify.** Re-run scoring to confirm improvement.

**Coaching level adaptation:**
- **Full:** Propose 3-5 specific outcome changes with dramatic reasoning.
- **Coach:** Show the distribution, ask which scenes feel emotionally repetitive.
- **Strict:** Show counts and percentages only.

## Step 5: Validate and Report

After any stage completes, run validation:

```bash
cd [project_dir] && [plugin_path]/scripts/storyforge-validate
```

After briefs are complete (before drafting), also run structural scoring:

```bash
cd [project_dir] && [plugin_path]/scripts/storyforge-validate --structural
```

This scores 8 dimensions of story quality from CSV data (deterministic, free, instant):
- Arc completeness, thematic concentration, pacing shape, character presence
- MICE thread health, knowledge chain integrity, scene function variety, structural completeness

If any dimension is below target, review the diagnosis (which includes craft-grounded explanations and specific CSV changes) and address findings before drafting. Structural fixes are much cheaper than prose rewrites.

If registries are missing or thematic concentration is low, recommend reconciliation:
```bash
cd [project_dir] && [plugin_path]/scripts/storyforge-reconcile
```

Report results to the author. Blocking validation failures must be fixed before advancing. Structural scoring findings are advisory but strongly recommended before drafting.

## Step 6: Commit After Every Deliverable

Every stage output gets committed immediately:

```bash
git add -A && git commit -m "Elaborate: [stage name]" && git push
```

Do not batch multiple stages into one commit.
