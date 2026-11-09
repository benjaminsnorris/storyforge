"""Prompt builders for elaboration pipeline stages.

Each function reads current project state and produces a Claude prompt
for one elaboration stage. Prompts instruct Claude to output structured
data (pipe-delimited CSV rows in fenced code blocks) plus markdown
content for reference documents.
"""

import os
from .illustrations import read_scene_prose
from .prompts import read_yaml_field
from .scenes import SCENE_ID_RULE

#: How every elaboration stage writes its scene rows (#644, plan D4): terse
#: notes of what happens and what is true, never interpretation. Scoped to
#: the CSV rows: the architecture and bible documents exist to name a theme,
#: a need or a lie (its review CR-2), so they are exempt from "no
#: interpretation", not from terseness. Every
#: elaborated field is model prose the drafter reads, and the drafter writes
#: more like what it reads: on *Wrath Like Smoke* a brief's subtext ("let the
#: list grow, and never call it pride") became the aphoristic closing lines
#: the author singled out.
NOTES_RULE = ('Write every scene row\'s cells (the CSV blocks) as terse notes of what happens '
              'and what is true: who does what, to whom, with what ("Agamemnon counts the '
              'gifts on the sceptre studs; Briseis is the sixth stud"), not a paragraph about '
              'what the moment means. No interpretation in a scene row: never say what a '
              'moment means or reveals, what a character feels underneath, or what the reader '
              'should take from it, and no polished or quotable sentences. The drafter finds '
              'the words; these notes give only the facts. The story architecture and the '
              'character and world bibles are where a theme, a want, a need, a wound or a lie '
              'belongs: write those plainly, as short notes too.')

#: The craft-framework columns as notes, not requirements (#643, #644): what
#: the architecture and map prompts say about them
_CRAFT_NOTES = ('action_sequel, emotional_arc, value_at_stake, value_shift and '
                'turning_point are craft-framework notes, not requirements: fill one when the '
                'scene plainly has it, and leave the cell empty when it doesn\'t. Not every scene '
                'turns or shifts a value, and validate reports flat stretches and runs of one '
                'scene type or turning point as diagnostics, not errors.')


def _read_file(path: str) -> str:
    """Read a file's contents, or return empty string if missing."""
    if not os.path.isfile(path):
        return ''
    with open(path, encoding='utf-8') as f:
        return f.read()


def _read_file_contents(path: str) -> str:
    """Read a file's contents for inclusion in prompts.

    Returns the file contents stripped of surrounding whitespace, or
    ``'(empty)'`` when the file is missing or empty. Works for any text
    file — CSVs, markdown, plain text.
    """
    content = _read_file(path)
    return content.strip() if content else '(empty)'


# Backwards-compatible alias (was named _read_csv_contents before but also
# used to read markdown). Prefer _read_file_contents in new code.
_read_csv_contents = _read_file_contents


def _project_context(project_dir: str) -> str:
    """Build the common project context block for all stage prompts."""
    yaml_path = os.path.join(project_dir, 'storyforge.yaml')
    title = read_yaml_field(yaml_path, 'project.title') or 'Untitled'
    genre = read_yaml_field(yaml_path, 'project.genre') or ''
    subgenre = read_yaml_field(yaml_path, 'project.subgenre') or ''
    logline = read_yaml_field(yaml_path, 'project.logline') or ''
    target = read_yaml_field(yaml_path, 'project.target_words') or ''

    genre_str = genre
    if subgenre:
        genre_str = f"{genre} / {subgenre}"

    from .narrator import prompt_line
    narrator = prompt_line(project_dir)
    narrator = f"\n**{narrator.replace(':', ':**', 1)}" if narrator else ''
    return f"""## Project

**Title:** {title}
**Genre:** {genre_str}
**Logline:** {logline}
**Target word count:** {target}{narrator}"""


# The reference docs the stage prompts carry, in order. The shared system
# context (common.build_shared_context) already carries the bibles and voice
# guide, so a prompt built with system_context leaves those out, and only
# those: the story summary, architecture and key decisions are in no system
# block, and a stage that skipped them would build on decisions it never saw.
_REFERENCE_DOCS = [
    ('story-summary.md', 'Story Summary', False),
    ('story-architecture.md', 'Story Architecture', False),
    ('character-bible.md', 'Character Bible', True),
    ('world-bible.md', 'World Bible', True),
    ('voice-guide.md', 'Voice Guide', True),
    ('key-decisions.md', 'Key Decisions', False),
]


def reference_doc(project_dir: str, name: str) -> str:
    """`reference/<name>`'s text for a prompt, stripped: '' when the file is
    missing, empty or still its template (F-130). `common.reference_text`
    by project, shared with drafting (`prompts`, #596).

    Raises:
        common.ReferenceDocError: the file exists but can't be read.
    """
    from .common import reference_text
    return reference_text(os.path.join(project_dir, 'reference', name))


def _existing_refs(project_dir: str, shared: bool = False) -> str:
    """Include any existing reference materials.

    With `shared`, the prompt goes with the shared system context, so the
    docs that context carries (the bibles, the voice guide, the source
    bibles, the series canon) are left out and the rest are kept. A doc still holding its
    template text is skipped (F-130)."""
    sections = []
    for name, label, in_shared in _REFERENCE_DOCS:
        if shared and in_shared:
            continue
        content = reference_doc(project_dir, name)
        if content:
            sections.append(f"### {label}\n\n{content}")

    if shared:
        return '\n\n'.join(sections)

    # An adaptation's source bibles (#477); none without a `source:` block
    from .prompts_source import bibles_text
    for label, content in bibles_text(project_dir):
        sections.append(f"### {label}\n\n{content}")

    # A series' shared canon (`series.canon`); the shared context carries it too
    from .series import canon_text
    for label, content in canon_text(project_dir):
        sections.append(f"### {label}\n\n{content}")

    return '\n\n'.join(sections) if sections else '(no reference materials yet)'


# ============================================================================
# Stage 1: Spine
# ============================================================================

def build_spine_prompt(project_dir: str, plugin_dir: str, seed: str = '',
                       system_context: bool = False) -> str:
    """Build the prompt for the spine stage.

    Args:
        project_dir: Path to the book project.
        plugin_dir: Path to the Storyforge plugin root.
        seed: Author-provided seed text (logline, concepts, constraints).
              If empty, reads from storyforge.yaml logline.
        system_context: If True, leave out the reference docs the shared system
            context carries (see _existing_refs).
    """
    context = _project_context(project_dir)
    refs = _existing_refs(project_dir, shared=system_context)

    yaml_path = os.path.join(project_dir, 'storyforge.yaml')
    if not seed:
        seed = read_yaml_field(yaml_path, 'project.logline') or ''

    refs_section = f'\n## Existing Reference Materials\n\n{refs}\n' if refs else ''
    from .prompts_source import spine_section
    src = spine_section(project_dir)
    refs_section += f'\n{src}\n' if src else ''

    return f"""You are building the spine of a novel — the 5-10 irreducible story events that must happen.

{context}

## Author's Seed

{seed if seed else '(Use the logline above as the seed.)'}
{refs_section}
## Instructions

Produce the following deliverables:

### 1. Story Architecture

Write a complete story architecture document with:
- **Premise**: One sentence — character + conflict + stakes
- **Theme**: The question the story explores (phrased as a question, not a statement)
- **External conflict**: The tangible, visible struggle
- **Internal conflict**: The protagonist's inner battle (Lie vs. Need)
- **Thematic conflict**: How the theme manifests in character clash
- **Ending**: How all three conflict levels resolve

Output this in a fenced block labeled `story-architecture`:

```story-architecture
(your story architecture markdown here)
```

### 2. Character Bible Seeds

Write seed entries for the protagonist and antagonist force. Each character needs:
- Name and role
- Want (conscious, concrete goal)
- Need (unconscious requirement, usually opposite of Want)
- Wound (formative damage that shaped worldview)
- Lie (false belief resulting from wound)
- Flaw/strength duality

Output in a fenced block labeled `character-bible`:

```character-bible
(your character bible markdown here)
```

### 3. Spine Scenes

Identify 5-10 irreducible story events. For each, provide a row in pipe-delimited CSV format.

Output in a fenced block labeled `scenes-csv`:

```scenes-csv
id|seq|title|summary|act|status
(one row per spine event — seq is reading order, status is always "spine")
```

- `summary`: what happens in the event, in at most 35 words
- `act`: the structural act it falls in (1, 2, 3, ...); follow the story summary's act-shape when there is one

These rows are also the book's spine (`reference/spine.csv`).

Scene ids: {SCENE_ID_RULE}

And the intent for each scene:

```intent-csv
id|function
(one row per spine event — function is WHY this scene must exist, stated as a testable claim)
```

### Rules

- Every spine event must connect causally to the next (but/therefore, not and-then)
- The protagonist's wound/lie must produce a want that drives the external conflict
- The ending must resolve all three conflict levels
- Scene functions must be testable — "Establish the world" is vague; "Reveal that the mine has been salted through a surveying error" is testable
- If the author provided character concepts or world details in the seed, honor them
- {NOTES_RULE}
"""


# ============================================================================
# Stage 2: Architecture
# ============================================================================

def build_architecture_prompt(project_dir: str, plugin_dir: str,
                              registries_text: str = '',
                              system_context: bool = False) -> str:
    """Build the prompt for the architecture stage."""
    context = _project_context(project_dir)
    refs = _existing_refs(project_dir, shared=system_context)
    ref_dir = os.path.join(project_dir, 'reference')
    scenes = _read_csv_contents(os.path.join(ref_dir, 'scenes.csv'))
    intent = _read_csv_contents(os.path.join(ref_dir, 'scene-intent.csv'))

    registries_section = f'\n\n{registries_text}\n' if registries_text else ''
    refs_section = f'\n## Reference Materials\n\n{refs}\n' if refs else ''
    from .prompts_source import architecture_section
    src = architecture_section(project_dir)
    registries_section += f'\n{src}\n' if src else ''

    return f"""You are building the architecture of a novel — expanding the spine into a full structural plan.

{context}

## Current Spine

### scenes.csv
```
{scenes}
```

### scene-intent.csv
```
{intent}
```
{refs_section}{registries_section}
## Instructions

Expand the spine (5-10 events) into 15-25 scenes. For each scene:

1. Keep all existing spine scenes (you may adjust titles and functions)
2. Add supporting scenes: character development, subplot introduction, transitions, world-building
3. Assign every scene to a structural act (`act` — 1, 2, 3, ...)
4. Assign POV characters
5. Where it fits the scene, note it as action or sequel (Swain's scene/sequel pattern), the value at stake and its polarity shift (McKee), and the turning point type (action or revelation). These are notes: leave a cell empty for a scene that doesn't fit

### Output Format

Update the scenes CSV with new columns filled:

```scenes-csv
id|seq|title|summary|act|pov|spine_event|status
(all scenes — existing spine scenes updated, new scenes added, status is "architecture")
```

- `summary`: what happens in the scene, in at most 50 words
- `spine_event`: the id of the spine scene this scene serves (a spine scene gives its own id)

These rows are also the book's architecture (`reference/architecture.csv`).

Scene ids: {SCENE_ID_RULE} Keep every existing scene's id exactly as it is; to move a scene, change its seq.

Update the intent CSV with new columns:

```intent-csv
id|function|action_sequel|emotional_arc|value_at_stake|value_shift|turning_point
(all scenes)
```

If you need to deepen the character bible with supporting characters, output:

```character-bible
(additional character entries in the same format as existing)
```

If the world needs a bible, output:

```world-bible
(world bible markdown)
```

### Rules

- {_CRAFT_NOTES}
- An enum cell holds only its value: `action_sequel` is action or sequel, `turning_point` is action or revelation, never "action: she strikes" (what turns the scene goes in `function`)
- Every thread introduced must have a planned resolution
- Acts should hit roughly: first act ~25%, midpoint ~50%, climax ~75-85%
- Character arcs need structural progression: lie reinforced → challenged → confronted → truth/refusal
- {NOTES_RULE}
"""


# ============================================================================
# Stage 3: Scene Map
# ============================================================================

def _scene_count_range(project_dir: str) -> tuple[int, int]:
    """Compute the target scene count range from manuscript target_words.

    Scenes should average 1500-2000 words for optimal pipeline behavior:
    - Under 1200 words: too short to establish, turn, and resolve
    - Over 3000 words: Claude loses grip on brief constraints in later paragraphs
    - 1500-2000 is the sweet spot for brief adherence, scoring precision, and revision
    """
    yaml_path = os.path.join(project_dir, 'storyforge.yaml')
    raw = read_yaml_field(yaml_path, 'project.target_words')
    try:
        target = int(raw)
    except (TypeError, ValueError):
        target = 80000  # default

    # Compute range: target / 2000 (lower) to target / 1500 (upper), floor 40
    lo = max(40, target // 2000)
    hi = max(lo + 10, target // 1500)
    return lo, hi


def build_map_prompt(project_dir: str, plugin_dir: str,
                     registries_text: str = '',
                     system_context: bool = False) -> str:
    """Build the prompt for the scene map stage."""
    context = _project_context(project_dir)
    refs = _existing_refs(project_dir, shared=system_context)
    ref_dir = os.path.join(project_dir, 'reference')
    scenes = _read_csv_contents(os.path.join(ref_dir, 'scenes.csv'))
    intent = _read_csv_contents(os.path.join(ref_dir, 'scene-intent.csv'))

    registries_section = f'\n\n{registries_text}\n' if registries_text else ''
    refs_section = f'\n## Reference Materials\n\n{refs}\n' if refs else ''

    lo, hi = _scene_count_range(project_dir)
    from .prompts_source import map_section
    src = map_section(project_dir)
    registries_section += f'\n{src}\n' if src else ''

    return f"""You are mapping a novel — expanding the architecture into a complete scene-by-scene plan with locations, timeline, characters, and thread tracking.

{context}

## Current Architecture

### scenes.csv
```
{scenes}
```

### scene-intent.csv
```
{intent}
```
{refs_section}{registries_section}
## Instructions

Expand the architecture into {lo}-{hi} scenes (when Key Decisions records a scene count for the book, that count wins over this estimate). Prefer **more, shorter scenes** (1500-2000 words each) over fewer, longer ones. This is important for drafting quality — Claude follows brief constraints more reliably in focused scenes under 2500 words, and scoring/revision are more precise on smaller units.

For each scene:

1. Keep all existing scenes (adjust as needed)
2. Fill in gaps: transitions, subplot scenes, breathing room
3. Assign locations (the places the scene's action happens in, in order, semicolon-separated: usually one, several only when the action truly moves; never a route as a place), timeline days, time of day, duration
4. List all characters present (on_stage) and referenced (characters)
5. Track MICE threads: +thread where it begins, -thread where it resolves, the bare name where a scene advances an open thread. Threads may interleave

### Output Format

```scenes-csv
id|seq|title|summary|act|part|pov|location|timeline_day|time_mode|time_of_day|duration|target_words|status|architecture_scene|told_by
(all scenes — status is "mapped" for new/updated scenes)
```

- `architecture_scene`: the architecture scene each scene comes from: its own id for an architecture scene, and for a scene split off one (or added to play out part of it) that scene's id. Empty only for a new scene that serves no architecture scene
- `time_of_day`: exactly one of morning, afternoon, evening, night, dawn, dusk; or unstated when the scene gives none (never "midday" or a description)
- `summary`: what happens in the scene, in at most 50 words. Rewrite an existing scene's summary when the map splits it or moves part of it elsewhere
- `part`: the book part the scene falls in, by number (storyforge.yaml `parts:`); leave it empty for a book without parts
- `target_words`: the scene's planned length; together they come to about the target word count, and uneven lengths are fine

Scene ids: {SCENE_ID_RULE} Keep every existing scene's id exactly as it is; to move a scene, change its seq.

```intent-csv
id|function|action_sequel|emotional_arc|value_at_stake|value_shift|turning_point|characters|on_stage|mice_threads
(all scenes)
```

### Rules

- timeline_day is when a scene's action happens; a flashback keeps the earlier day it depicts (0 or negative before day 1). Flashbacks are a device, not an error: use one where the past changes what the present means
- time_mode: scene (the action plays out on its day; the default), summary (it covers a stretch of time; timeline_day is where the stretch starts), frame (narration from after the story, looking back), or vision (events a character is shown that the story doesn't treat as fixed, such as a future that may be; never the story's present)
- told_by: for an embedded tale (a story, song or report a character gives inside another scene), the id of the scene that tells it; its pov is the teller, its timeline_day the day its events happened. Empty for a scene lived on the page
- Say how each scene sits in time in its summary when it isn't simply the same day as the scene before: "the next morning", "three weeks later", "flashback to 1917". The timeline check reads this, and drafting carries it into the prose
- Every character referenced must exist in the character bible
- An enum cell holds only its value (`turning_point` is action or revelation, never "action: she strikes"; what turns the scene goes in `function`)
- MICE threads: each opens once and closes at most once; they may interleave (nesting is guidance, not a rule)
- No thread dormant for more than 8-10 scenes without acknowledgment
- Every scene must have at least one on-stage character
- Location names must be consistent (same place = same name)
- Total target_words should sum to within 10% of the manuscript target ({read_yaml_field(os.path.join(project_dir, 'storyforge.yaml'), 'project.target_words') or 'not set'})
- {_CRAFT_NOTES}
- {NOTES_RULE}
"""


# ============================================================================
# Stage 4: Briefs
# ============================================================================

#: The briefs stage's reply columns: the facts, and the craft notes the
#: author may leave empty. Never the author's notes (`AUTHOR_NOTE_COLUMNS`,
#: #644) or a graphic novel's columns (its own handler)
BRIEFS_OUTPUT_HEADER = ('id|outcome|key_actions|knowledge_in|knowledge_out|physical_state_in|'
                        'physical_state_out|goal|conflict|crisis|decision|continuity_deps|'
                        'has_overflow')


def build_briefs_prompt(project_dir: str, plugin_dir: str,
                        scene_ids: list[str] | None = None,
                        registries_text: str = '',
                        system_context: bool = False) -> str:
    """Build the prompt for the briefs stage.

    Args:
        project_dir: Path to the book project.
        plugin_dir: Path to the Storyforge plugin root.
        scene_ids: If provided, only build briefs for these scenes.
                   If None, builds for all mapped scenes without briefs.
        registries_text: Optional formatted registry contents for prompt injection.
        system_context: If True, leave out the reference docs the shared
                        system context carries (see _existing_refs).

    No craft principles (#644): a brief is the scene's facts, and the
    craft engine's scene rules (every scene must turn) are for the drafter.
    """
    context = _project_context(project_dir)
    refs = _existing_refs(project_dir, shared=system_context)
    ref_dir = os.path.join(project_dir, 'reference')
    scenes = _read_csv_contents(os.path.join(ref_dir, 'scenes.csv'))
    intent = _read_csv_contents(os.path.join(ref_dir, 'scene-intent.csv'))
    briefs = _read_csv_contents(os.path.join(ref_dir, 'scene-briefs.csv'))

    scope_note = ""
    if scene_ids:
        scope_note = f"\n**Scope:** Only write briefs for these scenes: {', '.join(scene_ids)}\n"

    registries_section = f'\n\n{registries_text}\n' if registries_text else ''
    refs_section = f'\n## Reference Materials\n\n{refs}\n' if refs else ''
    from .prompts_source import briefs_section
    src = briefs_section(project_dir, scene_ids)
    registries_section += f'\n{src}\n' if src else ''

    from .schema import OUTCOME_GUIDE   # schema imports elaborate
    from .speaker_labels import LABEL_RULE
    from .elaborate import AUTHOR_NOTE_COLUMNS
    notes = ', '.join(AUTHOR_NOTE_COLUMNS)
    return f"""You are writing the scene briefs for a novel: the facts of what happens in each scene, as terse notes, so that scenes can be drafted independently and still cohere.

A brief is a plan of events, not a script. It keeps every fact the scene must honour or establish, and it drops the staging: how the scene is played, what is said, what it means. The drafter finds the gesture, the line and the image.

{context}
{scope_note}

## Current State

### scenes.csv
```
{scenes}
```

### scene-intent.csv
```
{intent}
```

### scene-briefs.csv (existing)
```
{briefs}
```
{refs_section}{registries_section}
## Instructions

For each scene that needs a brief, write its facts:

- **outcome**: How the scene ends for the POV character — {OUTCOME_GUIDE} (Bickham's scene disasters, plus no-but from Kowal's try/fail cycles). Judge it against the goal when the scene has one; in a scene with no goal, against what the POV character is trying to do or hoping for, and never fill goal just to judge the outcome by it
- **key_actions**: Semicolon-separated events, in order: who does what. Include the turn, the event that changes the scene's situation, when the scene has one. Events, not lines: say that something is said ("Achilles refuses the gifts"), never script the words. No feelings and no meaning.
- **knowledge_in**: Semicolon-separated ids of STRUCTURALLY USEFUL facts the POV character knows entering. Facts are knowledge fact ids (kebab-case, 2-5 words); reuse an existing id for a fact already established, and give a genuinely new fact a new id. Only include facts that gate this scene's decisions — identity reveals, motive/intent reveals, capability/constraints, state changes, stakes/threats, relationship shifts. Omit ordinary plot details.
- **knowledge_out**: knowledge_in plus 0-2 NEW structurally useful facts learned during this scene. A fact is useful only if a character who knows it would make a different decision than one who doesn't, or a future scene requires it. Most scenes add 0-1 new facts.
- **physical_state_in**: Semicolon-separated state IDs that on-stage characters carry INTO this scene. Use EXACT IDs from prior scenes' physical_state_out. Only track states that affect capability, appearance, or equipment — injuries, items gained/lost, abilities changed, visible changes, fatigue. Not temporary emotions or scene-local conditions.
- **physical_state_out**: physical_state_in plus 0-2 NEW states acquired during this scene, minus any states that resolve during this scene.
- **goal**, **conflict**, **crisis**, **decision**: optional notes. Fill one only when the scene plainly has it, as a fact in a few words (goal: "buy back Hector's body"; decision: "Achilles gives up the body"), and leave it empty otherwise. Not every scene has a goal, an opponent or a dilemma.
- **continuity_deps**: Semicolon-separated scene IDs this scene depends on (for parallel drafting)
- **has_overflow**: false (unless you indicate a scene needs extended brief)

Not yours to write: {notes}. They are the author's optional notes, filled by hand, and they are not in the output. A motif is noticed in the draft and recorded after, never placed in a brief.

### Output Format

```briefs-csv
{BRIEFS_OUTPUT_HEADER}
(one row per scene being briefed)
```

Also update scenes.csv status to "briefed" for all briefed scenes:

```scenes-csv-update
id|status
(one row per scene, status = briefed)
```

### Rules

- {NOTES_RULE}
- knowledge_in uses the same fact ids as prior scenes' knowledge_out, never sentences — validation will check this
- Target 0-2 new knowledge facts per scene. Most scenes should add 0-1. A full novel should have 50-120 total facts, not 500+
- continuity_deps should list the minimum set of scenes whose knowledge_out this scene needs
- physical_state_in must reference IDs established in prior scenes' physical_state_out
- Target 0-2 state changes per scene. A full novel should have 15-40 total state entries.
- States persist until explicitly resolved — do not silently drop them
- continuity_deps should also list scenes whose physical_state_out this scene needs
- Every scene must have its outcome and key_actions filled
- Where an existing `must:` key_actions item quotes a line, keep it labelled: {LABEL_RULE}
- A key_actions item an existing brief starts with `must:` is the author's: copy it word for word, marker and all. Never add `must:` yourself
- A scene with told_by is a tale told inside that scene: brief the tale's own events, and the telling scene's brief says who tells it to whom
- Scenes with no continuity_deps can be drafted in parallel — maximize these
"""


# ============================================================================
# Stage 5: Voice
# ============================================================================

def build_voice_prompt(project_dir: str, plugin_dir: str,
                       system_context: bool = False) -> str:
    """Build the prompt for the voice stage.

    Produces reference/voice-guide.md and reference/voice-profile.csv.

    In graphic-novel mode, also asks for caption_voice and lettering_style
    to be set on the _project row of voice-profile.csv.

    Args:
        project_dir: Path to the book project.
        plugin_dir: Path to the Storyforge plugin root.
        system_context: If True, leave out the reference docs the shared system
            context carries (see _existing_refs).
    """
    from .common import get_medium
    medium = get_medium(project_dir)

    context = _project_context(project_dir)
    refs = _existing_refs(project_dir, shared=system_context)
    ref_dir = os.path.join(project_dir, 'reference')
    characters_csv = _read_csv_contents(os.path.join(ref_dir, 'characters.csv'))

    refs_section = f'\n## Reference Materials\n\n{refs}\n' if refs else ''

    medium_label = 'graphic novel' if medium == 'graphic-novel' else 'novel'

    # A book whose narrator holds scenes needs that narrator defined (#555)
    from .narrator import LIMITED, narrator_scenes, read_setting
    scenes_rows = []
    scenes_path = os.path.join(ref_dir, 'scenes.csv')
    if os.path.isfile(scenes_path):
        from .elaborate import _read_csv
        scenes_rows = _read_csv(scenes_path)
    narrated = narrator_scenes(scenes_rows)
    narrator_section = ''
    if narrated or read_setting(project_dir).mode == LIMITED:
        narrator_section = (
            '- **The narrator**: ' + (f'{len(narrated)} scene(s) have `narrator` as their '
                                      f'POV. ' if narrated else 'The narrator may hold scenes. ')
            + 'Say who the narrator is (an omniscient voice, a bard, a later teller, a '
            'character looking back) and their stance: how far they know into minds, '
            'whether they judge, foreshadow or address the reader, and how close they '
            'stand to the action. Give the narrator a voice fingerprint like a POV '
            'character\'s, and a voice-profile row with character `narrator` (the one row '
            'that is not a characters.csv id).\n')

    # An adaptation re-voices its source's speeches (#615): the guide sets the
    # register for that, and declares the few exemptions the register check
    # honours, rather than a list of period words to keep
    from . import source as _source
    from .prompts_source import REVOICE_RULE
    adaptation_section = ''
    if _source.read_config(project_dir) is not None:
        adaptation_section = (
            '- **Re-voicing the source**: This novel adapts a source, often an older '
            'translation. Say how its speeches and set pieces are re-voiced in this '
            'book\'s register. The drafting rule is: ' + REVOICE_RULE + ' Don\'t write a '
            'list of period or medieval nouns to keep: a period word is kept only where '
            'a scene makes it plain, and the default is the plain modern word.\n'
            '- **Register exemptions**: End the guide with a `## Register exemptions` '
            'section listing only the older diction this book deliberately allows, one '
            'bullet each: the exact phrase in double quotes and the reason after it '
            '(`- "by my faith" (an oath)`), or `- scene: <scene-id>` for a scene told '
            'wholly in an older voice (a frame narrator). Keep it short; leave the '
            'section empty if the book allows none. The register check skips exactly these.\n')

    return f"""You are developing the voice of a {medium_label} — the prose register, per-character voice fingerprints, and style rules that every scene must embody.

{context}
{refs_section}
## Characters

```
{characters_csv}
```

## Instructions

Produce two artifacts.

### Artifact 1: Voice Guide

Write a comprehensive voice guide as a markdown document covering:

- **Prose register**: The overall tone, sentence rhythm, and diction level
- **What this book sounds like**: 2-3 paragraphs describing the narrative voice in concrete terms — what it notices, how it moves, what it never does
- **POV character voice fingerprints**: For each POV character, define:
  - What they notice first in any scene (what their attention is drawn to)
  - Their sentence rhythm (long and winding? short declarative? varied?)
  - What metaphor domains they instinctively reach for
  - Words and phrases they would never use
  - How they speak in dialogue vs. how they narrate
- **Style rules**: Specific rules the prose must follow (e.g., "no weather openings", "interiority in present tense", "never name emotions directly")
- **Prohibited patterns**: Constructions, words, or moves that break this book's voice
{narrator_section}{adaptation_section}
Output in a fenced block labeled `voice-guide`:

```voice-guide
# Voice Guide

(your voice guide markdown here)
```

### Artifact 2: Voice Profile CSV

After writing the voice guide, produce `reference/voice-profile.csv`.

This is a pipe-delimited CSV with columns:
character|preferred_words|banned_words|metaphor_families|rhythm_preference|register|dialogue_style

Create these rows:
1. A _project row with:
   - banned_words: words that would break this book's voice (semicolon-separated)
   - register: the prose register (e.g., "literary;restrained;precise")
   - Leave preferred_words, metaphor_families, rhythm_preference, dialogue_style empty

2. One row per POV character with:
   - preferred_words: 10-20 words central to their voice (semicolon-separated)
   - metaphor_families: domains they source images from (semicolon-separated)
   - rhythm_preference: their sentence patterns (semicolon-separated descriptions)
   - dialogue_style: how they speak (semicolon-separated descriptions)
   - Leave banned_words and register empty (those are project-level)

Character IDs must match the id column in reference/characters.csv.

Output in a fenced block labeled `voice-profile-csv`:

```voice-profile-csv
character|preferred_words|banned_words|metaphor_families|rhythm_preference|register|dialogue_style
_project||<banned_words>|||<register>|
<character_id>|<preferred_words>||<metaphor_families>|<rhythm_preference>||<dialogue_style>
(one row per POV character)
```

### Rules

- The voice guide should be specific enough that a writer could use it to write a scene from scratch and sound like this book
- banned_words in the _project row are in addition to universal AI-tell words (journey, beacon, resonate, embrace, tapestry, etc.) — focus on words that are wrong for THIS book specifically
- preferred_words should be words the character actually uses, not words about them
- metaphor_families are conceptual domains (e.g., "cartography", "decay", "machinery") not specific metaphors
- rhythm_preference describes patterns (e.g., "short declarative for realization beats; longer sensory runs during observation")
- dialogue_style describes speech register and habits (e.g., "clipped;formal;avoids contractions" or "casual;irreverent;trails off")
{_gn_voice_extension() if medium == 'graphic-novel' else ''}"""


def _gn_voice_extension() -> str:
    """Return the graphic-novel–specific voice-stage instructions."""
    return """
### Graphic-Novel Voice Fields (add to _project row)

Because this is a graphic novel, set two additional fields on the `_project` row
of `voice-profile.csv`:

**caption_voice** — the narrative register used in caption boxes. Choose one of:
  - `journal-voiceover`: first-person, written-voice feel (diary, letter, field notes)
  - `omniscient`: third-person omniscient narration in captions
  - `first-person`: first-person present-tense narration
  - `none`: no caption boxes — story told entirely through dialogue and art

**lettering_style** — the visual feel of the lettering that complements the voice. Choose one of:
  - `loose-natural`: hand-lettered feel, organic, imperfect
  - `typeset`: clean, formal, print-like
  - `hand-lettered-feel`: digital font imitating hand lettering

Update the voice-profile-csv block so the _project row includes these two columns:

```voice-profile-csv
character|preferred_words|banned_words|metaphor_families|rhythm_preference|register|dialogue_style|caption_voice|lettering_style
_project||<banned_words>|||<register>||<caption_voice>|<lettering_style>
<character_id>|<preferred_words>||<metaphor_families>|<rhythm_preference>||<dialogue_style>||
(one row per POV character)
```
"""


# ============================================================================
# Response parsing
# ============================================================================

def parse_stage_response(response: str) -> dict[str, str]:
    """Parse a stage response into labeled content blocks.

    Claude outputs fenced blocks like:
        ```scenes-csv
        id|seq|...
        ```
        ```story-architecture
        # Story Architecture
        ...
        ```

    Returns a dict mapping label -> content, e.g.:
        {'scenes-csv': 'id|seq|...', 'story-architecture': '# Story...'}
    """
    blocks: dict[str, str] = {}
    lines = response.split('\n')
    current_label = None
    current_lines: list[str] = []

    for line in lines:
        if line.startswith('```') and current_label is None:
            # Opening fence
            label = line[3:].strip()
            if label:
                current_label = label
                current_lines = []
        elif line.startswith('```') and current_label is not None:
            # Closing fence
            blocks[current_label] = '\n'.join(current_lines).strip()
            current_label = None
            current_lines = []
        elif current_label is not None:
            current_lines.append(line)

    return blocks


def csv_block_to_rows(csv_text: str) -> list[dict[str, str]]:
    """Parse a pipe-delimited CSV block into a list of dicts.

    Args:
        csv_text: The raw CSV text (header + data rows, pipe-delimited).

    Returns:
        List of dicts keyed by header column names.
    """
    lines = [l.strip() for l in csv_text.strip().split('\n') if l.strip()]
    if not lines:
        return []

    header = [h.strip() for h in lines[0].split('|')]
    rows = []
    for line in lines[1:]:
        values = line.split('|')
        row = {}
        for i, col in enumerate(header):
            row[col] = values[i].strip() if i < len(values) else ''
        rows.append(row)
    return rows


# ============================================================================
# Gap-fill prompt builders
# ============================================================================

_FIELD_INSTRUCTIONS = {
    'type': (
        'Classify the scene type. Choose exactly one from: '
        'character, plot, world, action, transition, confrontation, dialogue, introspection, revelation.'
    ),
    'time_of_day': (
        'Determine the time of day. Choose exactly one from: '
        'morning, afternoon, evening, night, dawn, dusk; or unstated when '
        'the scene gives none (never a guess).'
    ),
    'duration': (
        'Estimate the in-story duration of this scene (e.g., "2 hours", "30 minutes", "15 minutes").'
    ),
    'act': (
        'Determine which structural act this scene belongs to (integer, e.g., 1, 2, 3).'
    ),
    'action_sequel': (
        'Classify as action or sequel using Swain\'s scene/sequel pattern. '
        'Action: character pursues a goal and meets conflict. '
        'Sequel: character reacts, processes, and decides next move.'
    ),
    'emotional_arc': (
        'Describe the emotional progression in the format "starting_emotion to ending_emotion" '
        '(e.g., "controlled competence to buried unease").'
    ),
    'value_at_stake': (
        'Identify the abstract value at stake. Choose from: '
        'safety, love, justice, truth, freedom, honor, life, identity, loyalty, power — '
        'or name a specific value if none fit.'
    ),
    'value_shift': (
        'Determine the polarity shift using +/- notation: '
        '+/- (positive to negative), -/+ (negative to positive), '
        '+/++ (good to better), -/-- (bad to worse), '
        '+/+ (no change, positive), -/- (no change, negative).'
    ),
    'turning_point': (
        'Identify the turning point type. Choose: action (character does something) '
        'or revelation (character learns something new).'
    ),
    'mice_threads': (
        'List MICE threads: +name only where the thread begins, -name only where it resolves, '
        'and the bare name where this scene advances a thread already open. Use the canonical '
        'name from the registry, not a type prefix (type is resolved from the registry). '
        'Semicolon-separated (e.g., "+who-killed-x;the-castle").'
    ),
    'location': (
        'List the places where this scene\'s action happens, in order, semicolon-separated '
        '(usually one; several only when the action moves on the page). Use canonical names '
        'consistent with other scenes; never a route or transition as one place.'
    ),
    'timeline_day': (
        'Determine the day this scene\'s action happens, in story chronology (integer): day 1 '
        'is the first day of the main story, and a flashback keeps the earlier day it depicts '
        '(0 or negative before day 1). Consider the surrounding scenes for context.'
    ),
    'time_mode': (
        'How the scene sits in time: scene (its action plays out on its day), summary (it '
        'covers a stretch of time), frame (narration from after the story, looking back), or '
        'vision (events a character is shown that the story doesn\'t treat as fixed, such as a '
        'future that may be; never the story\'s present).'
    ),
}


def build_gap_fill_prompt(
    scene_id: str,
    gap_group: str,
    missing_fields: list,
    project_dir: str,
    scenes_dir: str,
    registries_text: str = '',
) -> str:
    """Build a focused prompt to fill specific missing fields for one scene.

    Args:
        scene_id: The scene to fill gaps for.
        gap_group: Name of the gap group (for context in prompt).
        missing_fields: List of field names that need values.
        project_dir: Path to the book project.
        scenes_dir: Path to the scenes/ directory with prose files.

    Returns:
        Prompt string for Claude.
    """
    from .elaborate import get_scene

    ref_dir = os.path.join(project_dir, 'reference')
    scene_data = get_scene(scene_id, ref_dir)

    # Read prose excerpt (first 500 words)
    prose_path = os.path.join(scenes_dir, f'{scene_id}.md')
    prose = read_scene_prose(prose_path) if os.path.isfile(prose_path) else ''
    if prose:
        words = prose.split()
        if len(words) > 500:
            prose = ' '.join(words[:500]) + '\n[... truncated ...]'

    # Build field instructions
    field_instructions = []
    for field in missing_fields:
        instruction = _FIELD_INSTRUCTIONS.get(field, f'Provide a value for {field}.')
        field_instructions.append(f'- **{field}**: {instruction}')
    from .elaborate import CRAFT_FRAMEWORK_COLUMNS
    craft = [f for f in missing_fields if f in CRAFT_FRAMEWORK_COLUMNS]
    if craft:
        # Craft-framework notes advise (#643, #644): an empty answer is allowed
        field_instructions.append(
            f'\n{", ".join(craft)}: craft-framework notes, not requirements. Fill one only '
            f'when the scene plainly has it; otherwise leave its cell empty (nothing between '
            f'the pipes).')

    # Build existing data summary
    existing_data = []
    if scene_data:
        for key, val in scene_data.items():
            if val and key not in ('id',) and key not in missing_fields:
                existing_data.append(f'- {key}: {val}')

    registries_section = f'\n{registries_text}\n' if registries_text else ''

    return f"""You are filling missing metadata for a scene in a novel. Read the prose excerpt and existing data, then provide ONLY the missing fields.

## Scene: {scene_id}

### Existing Data
{chr(10).join(existing_data) if existing_data else '(no existing data)'}

### Prose Excerpt
{prose if prose else '(no prose available)'}
{registries_section}
## Missing Fields — Fill These

{chr(10).join(field_instructions)}

{NOTES_RULE}

## Output Format

Respond with ONLY a pipe-delimited CSV row. The header is:

id|{"|".join(missing_fields)}

Provide exactly one data row:

{scene_id}|<values>

No explanation. No markdown fencing. Just the header line and the data line.
"""


def build_knowledge_fix_prompt(
    scene_id: str,
    project_dir: str,
    scenes_dir: str,
    available_knowledge: set,
) -> str:
    """Build a prompt to fix knowledge_in/knowledge_out wording for one scene.

    Args:
        scene_id: The scene to fix.
        project_dir: Path to the book project.
        scenes_dir: Path to the scenes/ directory with prose files.
        available_knowledge: Set of exact knowledge_out strings from all prior scenes.

    Returns:
        Prompt string for Claude.
    """
    from .elaborate import get_scene

    ref_dir = os.path.join(project_dir, 'reference')
    scene_data = get_scene(scene_id, ref_dir)

    # Read prose excerpt
    prose_path = os.path.join(scenes_dir, f'{scene_id}.md')
    prose = read_scene_prose(prose_path) if os.path.isfile(prose_path) else ''
    if prose:
        words = prose.split()
        if len(words) > 500:
            prose = ' '.join(words[:500]) + '\n[... truncated ...]'

    current_kin = scene_data.get('knowledge_in', '') if scene_data else ''
    current_kout = scene_data.get('knowledge_out', '') if scene_data else ''

    sorted_knowledge = sorted(available_knowledge) if available_knowledge else ['(none yet — this is the first scene)']

    return f"""You are fixing the knowledge chain for a scene in a novel. The knowledge_in field must use the fact ids from prior scenes' knowledge_out.

## Scene: {scene_id}

### Prose Excerpt
{prose if prose else '(no prose available)'}

### Current Values (may contain sentences or ids that don't match)
- knowledge_in: {current_kin}
- knowledge_out: {current_kout}

### Available Knowledge (fact ids from all prior scenes' knowledge_out)
{chr(10).join(f'- {k}' for k in sorted_knowledge)}

## Instructions

1. Rewrite knowledge_in using ONLY fact ids from the available knowledge list above. Drop any facts not in the list. Add any facts from the list that this POV character would know entering this scene.
2. Rewrite knowledge_out as: the corrected knowledge_in PLUS any new facts learned during this scene (read the prose to determine what's new).
3. List continuity_deps: the scene IDs whose knowledge_out contributed facts to this scene's knowledge_in.

## Output Format

Respond with ONLY a pipe-delimited CSV row. The header is:

id|knowledge_in|knowledge_out|continuity_deps

Provide exactly one data row. Semicolon-separate multiple values within a field.
No explanation. No markdown fencing. Just the header line and the data line.
"""


def build_physical_state_fix_prompt(
    scene_id: str,
    project_dir: str,
    scenes_dir: str,
    available_states: set,
) -> str:
    """Build a prompt to fix physical_state_in/physical_state_out for one scene.

    Args:
        scene_id: The scene to fix.
        project_dir: Path to the book project.
        scenes_dir: Path to the scenes/ directory with prose files.
        available_states: Set of exact state IDs from all prior scenes' physical_state_out.

    Returns:
        Prompt string for Claude.
    """
    from .elaborate import get_scene

    ref_dir = os.path.join(project_dir, 'reference')
    scene_data = get_scene(scene_id, ref_dir)

    # Read prose excerpt
    prose_path = os.path.join(scenes_dir, f'{scene_id}.md')
    prose = read_scene_prose(prose_path) if os.path.isfile(prose_path) else ''
    if prose:
        words = prose.split()
        if len(words) > 500:
            prose = ' '.join(words[:500]) + '\n[... truncated ...]'

    current_psi = scene_data.get('physical_state_in', '') if scene_data else ''
    current_pso = scene_data.get('physical_state_out', '') if scene_data else ''

    on_stage = scene_data.get('on_stage', '') if scene_data else ''

    sorted_states = sorted(available_states) if available_states else ['(none yet — no prior physical states established)']

    return f"""You are fixing the physical state chain for a scene in a novel. The physical_state_in field must use EXACT IDs from prior scenes' physical_state_out.

## Scene: {scene_id}
## On-stage characters: {on_stage}

### Prose Excerpt
{prose if prose else '(no prose available)'}

### Current Values (may have mismatches)
- physical_state_in: {current_psi}
- physical_state_out: {current_pso}

### Available Physical States (exact IDs from all prior scenes' physical_state_out)
{chr(10).join(f'- {s}' for s in sorted_states)}

## Instructions

1. Rewrite physical_state_in using ONLY state IDs from the available list above that are relevant to on-stage characters in this scene.
2. Rewrite physical_state_out as: the corrected physical_state_in PLUS any new states acquired during this scene, MINUS any states that resolve during this scene.
3. Only track states that affect what characters can do, how they look, or what they have.

## Output Format

Respond with ONLY a pipe-delimited CSV row. The header is:

id|physical_state_in|physical_state_out

Provide exactly one data row. Semicolon-separate multiple values within a field.
No explanation. No markdown fencing. Just the header line and the data line.
"""
