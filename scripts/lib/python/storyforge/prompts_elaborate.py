"""Prompt builders for elaboration pipeline stages.

Each function reads current project state and produces a Claude prompt
for one elaboration stage. Prompts instruct Claude to output structured
data (pipe-delimited CSV rows in fenced code blocks) plus markdown
content for reference documents.
"""

import os
from .prompts import read_yaml_field


def _read_file(path: str) -> str:
    """Read a file's contents, or return empty string if missing."""
    if not os.path.isfile(path):
        return ''
    with open(path, encoding='utf-8') as f:
        return f.read()


def _read_csv_contents(path: str) -> str:
    """Read CSV contents for inclusion in prompts."""
    content = _read_file(path)
    return content.strip() if content else '(empty)'


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

    return f"""## Project

**Title:** {title}
**Genre:** {genre_str}
**Logline:** {logline}
**Target word count:** {target}"""


def _existing_refs(project_dir: str) -> str:
    """Include any existing reference materials."""
    sections = []
    ref_dir = os.path.join(project_dir, 'reference')

    for name, label in [
        ('story-architecture.md', 'Story Architecture'),
        ('character-bible.md', 'Character Bible'),
        ('world-bible.md', 'World Bible'),
        ('voice-guide.md', 'Voice Guide'),
        ('key-decisions.md', 'Key Decisions'),
    ]:
        content = _read_file(os.path.join(ref_dir, name))
        if content.strip():
            sections.append(f"### {label}\n\n{content.strip()}")

    return '\n\n'.join(sections) if sections else '(no reference materials yet)'


def _craft_principles(project_dir: str, plugin_dir: str) -> str:
    """Load craft engine excerpt for prompts."""
    # Try plugin references first, then project
    for base in [plugin_dir, project_dir]:
        path = os.path.join(base, 'references', 'craft-engine.md')
        content = _read_file(path)
        if content:
            # Extract sections 2-5 (Scene Craft through Rules)
            lines = content.split('\n')
            capture = False
            captured = []
            for line in lines:
                if line.startswith('## 2'):
                    capture = True
                if line.startswith('## 6') or line.startswith('## 7'):
                    capture = False
                if capture:
                    captured.append(line)
            if captured:
                return '\n'.join(captured)
            return content[:3000]  # fallback: first 3000 chars
    return ''


# ============================================================================
# Stage 1: Spine
# ============================================================================

def build_spine_prompt(project_dir: str, plugin_dir: str, seed: str = '') -> str:
    """Build the prompt for the spine stage.

    Args:
        project_dir: Path to the book project.
        plugin_dir: Path to the Storyforge plugin root.
        seed: Author-provided seed text (logline, concepts, constraints).
              If empty, reads from storyforge.yaml logline.
    """
    context = _project_context(project_dir)
    refs = _existing_refs(project_dir)

    yaml_path = os.path.join(project_dir, 'storyforge.yaml')
    if not seed:
        seed = read_yaml_field(yaml_path, 'project.logline') or ''

    return f"""You are building the spine of a novel — the 5-10 irreducible story events that must happen.

{context}

## Author's Seed

{seed if seed else '(Use the logline above as the seed.)'}

## Existing Reference Materials

{refs}

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
id|seq|title|status
(one row per spine event — id is a descriptive slug, seq is reading order, status is always "spine")
```

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
"""


# ============================================================================
# Stage 2: Architecture
# ============================================================================

def build_architecture_prompt(project_dir: str, plugin_dir: str,
                              registries_text: str = '') -> str:
    """Build the prompt for the architecture stage."""
    context = _project_context(project_dir)
    refs = _existing_refs(project_dir)
    ref_dir = os.path.join(project_dir, 'reference')
    scenes = _read_csv_contents(os.path.join(ref_dir, 'scenes.csv'))
    intent = _read_csv_contents(os.path.join(ref_dir, 'scene-intent.csv'))

    registries_section = f'\n\n{registries_text}\n' if registries_text else ''

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

## Reference Materials

{refs}
{registries_section}
## Instructions

Expand the spine (5-10 events) into 15-25 scenes. For each scene:

1. Keep all existing spine scenes (you may adjust titles and functions)
2. Add supporting scenes: character development, subplot introduction, transitions, world-building
3. Assign every scene to a part/act
4. Assign POV characters
5. Classify each as action or sequel (Swain's scene/sequel pattern)
6. Define the value at stake and its polarity shift (McKee)
7. Identify the turning point type (action or revelation — vary these)
### Output Format

Update the scenes CSV with new columns filled:

```scenes-csv
id|seq|title|part|pov|status
(all scenes — existing spine scenes updated, new scenes added, status is "architecture")
```

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

- No flat polarity stretches: 3+ consecutive scenes with no value shift (+/+) is a red flag
- Vary scene types: no 4+ consecutive action or sequel scenes
- Vary turning point types: no 4+ consecutive action or revelation turning points
- Every thread introduced must have a planned resolution
- Parts should hit roughly: first act ~25%, midpoint ~50%, climax ~75-85%
- Character arcs need structural progression: lie reinforced → challenged → confronted → truth/refusal
"""


# ============================================================================
# Stage 3: Scene Map
# ============================================================================

def build_map_prompt(project_dir: str, plugin_dir: str,
                     registries_text: str = '') -> str:
    """Build the prompt for the scene map stage."""
    context = _project_context(project_dir)
    refs = _existing_refs(project_dir)
    ref_dir = os.path.join(project_dir, 'reference')
    scenes = _read_csv_contents(os.path.join(ref_dir, 'scenes.csv'))
    intent = _read_csv_contents(os.path.join(ref_dir, 'scene-intent.csv'))

    registries_section = f'\n\n{registries_text}\n' if registries_text else ''

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

## Reference Materials

{refs}
{registries_section}
## Instructions

Expand the architecture into the full scene count (40-60 scenes). For each scene:

1. Keep all existing scenes (adjust as needed)
2. Fill in gaps: transitions, subplot scenes, breathing room
3. Assign locations, timeline days, time of day, duration
4. List all characters present (on_stage) and referenced (characters)
5. Track MICE thread opens (+) and closes (-) — FILO within each type, parallel across types

### Output Format

```scenes-csv
id|seq|title|part|pov|location|timeline_day|time_of_day|duration|status
(all scenes — status is "mapped" for new/updated scenes)
```

```intent-csv
id|function|action_sequel|emotional_arc|value_at_stake|value_shift|turning_point|characters|on_stage|mice_threads
(all scenes)
```

### Rules

- Timeline must be consistent: no backward jumps without explicit justification
- Every character referenced must exist in the character bible
- MICE threads: same-type threads nest in FILO order; different types (milieu, inquiry, character, event) run in parallel
- No thread dormant for more than 8-10 scenes without acknowledgment
- Every scene must have at least one on-stage character
- Location names must be consistent (same place = same name)
- Total target_words should sum to within 10% of the manuscript target ({read_yaml_field(os.path.join(project_dir, 'storyforge.yaml'), 'project.target_words') or 'not set'})
"""


# ============================================================================
# Stage 4: Briefs
# ============================================================================

def build_briefs_prompt(project_dir: str, plugin_dir: str,
                        scene_ids: list[str] | None = None,
                        registries_text: str = '') -> str:
    """Build the prompt for the briefs stage.

    Args:
        project_dir: Path to the book project.
        plugin_dir: Path to the Storyforge plugin root.
        scene_ids: If provided, only build briefs for these scenes.
                   If None, builds for all mapped scenes without briefs.
        registries_text: Optional formatted registry contents for prompt injection.
    """
    context = _project_context(project_dir)
    refs = _existing_refs(project_dir)
    ref_dir = os.path.join(project_dir, 'reference')
    scenes = _read_csv_contents(os.path.join(ref_dir, 'scenes.csv'))
    intent = _read_csv_contents(os.path.join(ref_dir, 'scene-intent.csv'))
    briefs = _read_csv_contents(os.path.join(ref_dir, 'scene-briefs.csv'))
    craft = _craft_principles(project_dir, plugin_dir)

    scope_note = ""
    if scene_ids:
        scope_note = f"\n**Scope:** Only write briefs for these scenes: {', '.join(scene_ids)}\n"

    registries_section = f'\n\n{registries_text}\n' if registries_text else ''

    return f"""You are writing the drafting contracts for a novel — the scene-level briefs that define exactly what happens in each scene, in enough detail that scenes can be drafted independently and still cohere.

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

## Reference Materials

{refs}

## Craft Principles

{craft if craft else '(craft engine not available)'}
{registries_section}
## Instructions

For each scene that needs a brief, define the complete drafting contract:

- **goal**: The POV character's concrete objective entering the scene (Swain)
- **conflict**: What specifically opposes the goal
- **outcome**: How the scene ends — yes / no / yes-but / no-and (Weiland)
- **crisis**: The dilemma — best bad choice or irreconcilable goods (Story Grid)
- **decision**: What the character actively chooses
- **knowledge_in**: Semicolon-separated STRUCTURALLY USEFUL facts the POV character knows entering. Use EXACT wording that matches prior scenes' knowledge_out. Only include facts that gate this scene's decisions — identity reveals, motive/intent reveals, capability/constraints, state changes, stakes/threats, relationship shifts. Omit ordinary plot details.
- **knowledge_out**: knowledge_in plus 0-2 NEW structurally useful facts learned during this scene. A fact is useful only if a character who knows it would make a different decision than one who doesn't, or a future scene requires it. Most scenes add 0-1 new facts.
- **physical_state_in**: Semicolon-separated state IDs that on-stage characters carry INTO this scene. Use EXACT IDs from prior scenes' physical_state_out. Only track states that affect capability, appearance, or equipment — injuries, items gained/lost, abilities changed, visible changes, fatigue. Not temporary emotions or scene-local conditions.
- **physical_state_out**: physical_state_in plus 0-2 NEW states acquired during this scene, minus any states that resolve during this scene.
- **key_actions**: Semicolon-separated concrete things that happen
- **key_dialogue**: Specific lines or exchanges that must appear in the prose
- **emotions**: Semicolon-separated emotional beats in sequence
- **motifs**: Semicolon-separated recurring images/symbols deployed
- **subtext**: ONE sentence, max 150 characters. The gap between what a character says/does and what they mean. Format: "X says A but means B; don't state B" or "The tension is Z; show through [behavior], never name it." NOT a paragraph. NOT multiple clauses chained with semicolons. If no meaningful subtext, leave empty.
- **continuity_deps**: Semicolon-separated scene IDs this scene depends on (for parallel drafting)
- **has_overflow**: false (unless you indicate a scene needs extended brief)

### Output Format

```briefs-csv
id|goal|conflict|outcome|crisis|decision|knowledge_in|knowledge_out|key_actions|key_dialogue|emotions|motifs|subtext|continuity_deps|has_overflow|physical_state_in|physical_state_out
(one row per scene being briefed)
```

Also update scenes.csv status to "briefed" for all briefed scenes:

```scenes-csv-update
id|status
(one row per scene, status = briefed)
```

### Rules

- knowledge_in must use EXACT wording from prior scenes' knowledge_out — validation will check this
- Target 0-2 new knowledge facts per scene. Most scenes should add 0-1. A full novel should have 50-120 total facts, not 500+
- continuity_deps should list the minimum set of scenes whose knowledge_out this scene needs
- physical_state_in must reference IDs established in prior scenes' physical_state_out
- Target 0-2 state changes per scene. A full novel should have 15-40 total state entries.
- States persist until explicitly resolved — do not silently drop them
- continuity_deps should also list scenes whose physical_state_out this scene needs
- Every scene must have goal/conflict/outcome filled
- Key dialogue should sound like the character, not the author
- Scenes with no continuity_deps can be drafted in parallel — maximize these
- The crisis must be a genuine dilemma (two bad choices or two good choices that conflict), not "do the obvious thing or don't"
"""


# ============================================================================
# Stage 5: Voice
# ============================================================================

def build_voice_prompt(project_dir: str, plugin_dir: str) -> str:
    """Build the prompt for the voice stage.

    Produces reference/voice-guide.md and reference/voice-profile.csv.

    Args:
        project_dir: Path to the book project.
        plugin_dir: Path to the Storyforge plugin root.
    """
    context = _project_context(project_dir)
    refs = _existing_refs(project_dir)
    ref_dir = os.path.join(project_dir, 'reference')
    characters_csv = _read_csv_contents(os.path.join(ref_dir, 'characters.csv'))

    return f"""You are developing the voice of a novel — the prose register, per-character voice fingerprints, and style rules that every scene must embody.

{context}

## Reference Materials

{refs}

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
        'morning, afternoon, evening, night, dawn, dusk.'
    ),
    'duration': (
        'Estimate the in-story duration of this scene (e.g., "2 hours", "30 minutes", "15 minutes").'
    ),
    'part': (
        'Determine which act/part this scene belongs to (integer, e.g., 1, 2, 3).'
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
        'List MICE thread operations: +name to open, -name to close (type is resolved from registry). '
        'Types: milieu, inquiry, character, event. '
        'Semicolon-separated (e.g., "+inquiry:who-killed-X;-milieu:the-castle").'
    ),
    'location': (
        'Identify the primary location where this scene takes place. '
        'Use a canonical name consistent with other scenes.'
    ),
    'timeline_day': (
        'Determine what day number this scene takes place on (integer, starting from 1). '
        'Consider the surrounding scenes for context.'
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
    prose = _read_file(prose_path)
    if prose:
        words = prose.split()
        if len(words) > 500:
            prose = ' '.join(words[:500]) + '\n[... truncated ...]'

    # Build field instructions
    field_instructions = []
    for field in missing_fields:
        instruction = _FIELD_INSTRUCTIONS.get(field, f'Provide a value for {field}.')
        field_instructions.append(f'- **{field}**: {instruction}')

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
    prose = _read_file(prose_path)
    if prose:
        words = prose.split()
        if len(words) > 500:
            prose = ' '.join(words[:500]) + '\n[... truncated ...]'

    current_kin = scene_data.get('knowledge_in', '') if scene_data else ''
    current_kout = scene_data.get('knowledge_out', '') if scene_data else ''

    sorted_knowledge = sorted(available_knowledge) if available_knowledge else ['(none yet — this is the first scene)']

    return f"""You are fixing the knowledge chain for a scene in a novel. The knowledge_in field must use EXACT wording from prior scenes' knowledge_out.

## Scene: {scene_id}

### Prose Excerpt
{prose if prose else '(no prose available)'}

### Current Values (may have wording mismatches)
- knowledge_in: {current_kin}
- knowledge_out: {current_kout}

### Available Knowledge (exact wording from all prior scenes' knowledge_out)
{chr(10).join(f'- {k}' for k in sorted_knowledge)}

## Instructions

1. Rewrite knowledge_in using ONLY facts from the available knowledge list above, using their EXACT wording. Drop any facts not in the list. Add any facts from the list that this POV character would know entering this scene.
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
    prose = _read_file(prose_path)
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
