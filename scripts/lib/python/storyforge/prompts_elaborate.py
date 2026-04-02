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
        ('continuity-tracker.md', 'Continuity Tracker'),
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

def build_architecture_prompt(project_dir: str, plugin_dir: str) -> str:
    """Build the prompt for the architecture stage."""
    context = _project_context(project_dir)
    refs = _existing_refs(project_dir)
    ref_dir = os.path.join(project_dir, 'reference')
    scenes = _read_csv_contents(os.path.join(ref_dir, 'scenes.csv'))
    intent = _read_csv_contents(os.path.join(ref_dir, 'scene-intent.csv'))

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

## Instructions

Expand the spine (5-10 events) into 15-25 scenes. For each scene:

1. Keep all existing spine scenes (you may adjust titles and functions)
2. Add supporting scenes: character development, subplot introduction, transitions, world-building
3. Assign every scene to a part/act
4. Assign POV characters
5. Classify each as action or sequel (Swain's scene/sequel pattern)
6. Define the value at stake and its polarity shift (McKee)
7. Identify the turning point type (action or revelation — vary these)
8. Assign story threads

### Output Format

Update the scenes CSV with new columns filled:

```scenes-csv
id|seq|title|part|pov|status
(all scenes — existing spine scenes updated, new scenes added, status is "architecture")
```

Update the intent CSV with new columns:

```intent-csv
id|function|scene_type|emotional_arc|value_at_stake|value_shift|turning_point|threads
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

def build_map_prompt(project_dir: str, plugin_dir: str) -> str:
    """Build the prompt for the scene map stage."""
    context = _project_context(project_dir)
    refs = _existing_refs(project_dir)
    ref_dir = os.path.join(project_dir, 'reference')
    scenes = _read_csv_contents(os.path.join(ref_dir, 'scenes.csv'))
    intent = _read_csv_contents(os.path.join(ref_dir, 'scene-intent.csv'))

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

## Instructions

Expand the architecture into the full scene count (40-60 scenes). For each scene:

1. Keep all existing scenes (adjust as needed)
2. Fill in gaps: transitions, subplot scenes, breathing room
3. Assign locations, timeline days, time of day, duration
4. List all characters present (on_stage) and referenced (characters)
5. Track MICE thread opens (+) and closes (-) in FILO order

### Output Format

```scenes-csv
id|seq|title|part|pov|location|timeline_day|time_of_day|duration|status
(all scenes — status is "mapped" for new/updated scenes)
```

```intent-csv
id|function|scene_type|emotional_arc|value_at_stake|value_shift|turning_point|threads|characters|on_stage|mice_threads
(all scenes)
```

### Rules

- Timeline must be consistent: no backward jumps without explicit justification
- Every character referenced must exist in the character bible
- MICE threads must nest in FILO order (first opened = last closed)
- No thread dormant for more than 8-10 scenes without acknowledgment
- Every scene must have at least one on-stage character
- Location names must be consistent (same place = same name)
- Total target_words should sum to within 10% of the manuscript target ({read_yaml_field(os.path.join(project_dir, 'storyforge.yaml'), 'project.target_words') or 'not set'})
"""


# ============================================================================
# Stage 4: Briefs
# ============================================================================

def build_briefs_prompt(project_dir: str, plugin_dir: str,
                        scene_ids: list[str] | None = None) -> str:
    """Build the prompt for the briefs stage.

    Args:
        project_dir: Path to the book project.
        plugin_dir: Path to the Storyforge plugin root.
        scene_ids: If provided, only build briefs for these scenes.
                   If None, builds for all mapped scenes without briefs.
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

## Instructions

For each scene that needs a brief, define the complete drafting contract:

- **goal**: The POV character's concrete objective entering the scene (Swain)
- **conflict**: What specifically opposes the goal
- **outcome**: How the scene ends — yes / no / yes-but / no-and (Weiland)
- **crisis**: The dilemma — best bad choice or irreconcilable goods (Story Grid)
- **decision**: What the character actively chooses
- **knowledge_in**: Semicolon-separated facts the POV character knows entering. Use EXACT wording that matches prior scenes' knowledge_out.
- **knowledge_out**: Semicolon-separated facts the POV character knows leaving. These become available for later scenes' knowledge_in.
- **key_actions**: Semicolon-separated concrete things that happen
- **key_dialogue**: Specific lines or exchanges that must appear in the prose
- **emotions**: Semicolon-separated emotional beats in sequence
- **motifs**: Semicolon-separated recurring images/symbols deployed
- **continuity_deps**: Semicolon-separated scene IDs this scene depends on (for parallel drafting)
- **has_overflow**: false (unless you indicate a scene needs extended brief)

### Output Format

```briefs-csv
id|goal|conflict|outcome|crisis|decision|knowledge_in|knowledge_out|key_actions|key_dialogue|emotions|motifs|continuity_deps|has_overflow
(one row per scene being briefed)
```

Also update scenes.csv status to "briefed" for all briefed scenes:

```scenes-csv-update
id|status
(one row per scene, status = briefed)
```

### Rules

- knowledge_in must use EXACT wording from prior scenes' knowledge_out — validation will check this
- continuity_deps should list the minimum set of scenes whose knowledge_out this scene needs
- Every scene must have goal/conflict/outcome filled
- Key dialogue should sound like the character, not the author
- Scenes with no continuity_deps can be drafted in parallel — maximize these
- The crisis must be a genuine dilemma (two bad choices or two good choices that conflict), not "do the obvious thing or don't"
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
