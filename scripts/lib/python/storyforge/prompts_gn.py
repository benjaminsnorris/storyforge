"""Drafting prompts for graphic-novel mode.

Builds the per-scene system prompt that teaches the model to produce a
panel-by-panel script that honors the brief's narrative and visual contract.

Script format reference:
  docs/superpowers/specs/2026-05-20-graphic-novel-mode-design.md
"""


SCRIPT_FORMAT_INSTRUCTIONS = """\
Output format — required, strict:

  # Scene: {scene-id}

  **Target pages:** {N} | **Layout intent:** {brief.page_layout}

  ---

  ## Page 1 — LAYOUT-TAG

  **Panel 1** (size hint)
  Composition prose (1-3 sentences describing what the artist draws).

  - CAPTION: *Italicized caption text.*
  - CHARACTER-NAME: Spoken dialogue.

  **Panel 2** (size hint)
  ...

  ---

  ## Page 2 — LAYOUT-TAG
  ...

Rules:
  - Every page header is `## Page N — LAYOUT` where LAYOUT is one of:
    SPLASH, 6-PANEL GRID, 9-PANEL GRID, DOUBLE-SPREAD, TIER, IRREGULAR
    (or matching the brief's panel_breakdown tokens, uppercased).
  - Every panel block starts with `**Panel N**` and an optional size hint
    in parentheses, e.g. `**Panel 1** (full bleed)`.
  - Composition is 1-3 sentences of prose describing what the artist draws
    (Marvel Full Script style: layout, foreground, mood, lighting).
  - Dialogue and captions use this fixed prefix vocabulary:
    CAPTION, {CHARACTER}, SFX, WHISPER, THOUGHT, OFF-PANEL
    where {CHARACTER} is the uppercase character name from the on_stage list.
  - Pages tagged in the brief's page_turn_beats must include the marker
    ` ⟵ PAGE-TURN REVEAL` at the end of the page header line.
  - Separate pages with a `---` divider on its own line.
  - Output exactly the number of pages specified in target_pages.
"""


def _format_brief(brief_row):
    """Render the brief contract as a readable bullet list inside the prompt."""
    lines = []
    # Narrative core first
    for key in ('goal', 'conflict', 'outcome', 'crisis', 'decision'):
        value = (brief_row.get(key) or '').strip()
        if value:
            lines.append(f"- {key}: {value}")
    # GN-specific columns
    for key in ('key_dialogue', 'key_actions', 'visual_keywords',
                'page_layout', 'panel_breakdown', 'page_turn_beats',
                'caption_strategy'):
        value = (brief_row.get(key) or '').strip()
        if value:
            lines.append(f"- {key}: {value}")
    # Supporting brief columns
    for key in ('emotions', 'motifs', 'subtext',
                'knowledge_in', 'knowledge_out',
                'continuity_deps', 'physical_state_in', 'physical_state_out'):
        value = (brief_row.get(key) or '').strip()
        if value:
            lines.append(f"- {key}: {value}")
    return '\n'.join(lines) if lines else '(no brief data)'


def build_drafting_prompt(
    project_dir,
    scene_id,
    scene_row,
    intent_row,
    brief_row,
    character_visuals,
    location_visuals,
    voice_profile_text,
):
    """Build the system prompt that asks the model to draft one GN scene.

    Args:
        project_dir: Path to the book project (reserved for future context).
        scene_id: The scene ID being drafted.
        scene_row: Dict of scenes.csv columns for this scene.
        intent_row: Dict of scene-intent.csv columns for this scene.
        brief_row: Dict of scene-briefs.csv columns for this scene.
        character_visuals: String of character visual reference notes.
        location_visuals: String of location/setting visual reference notes.
        voice_profile_text: Voice profile text (caption_voice, lettering_style, etc.)

    Returns:
        Prompt string for Claude.
    """
    target_pages = (scene_row.get('target_pages') or '?').strip()
    title = (scene_row.get('title') or scene_id).strip()
    pov = (scene_row.get('pov') or '').strip()
    location = (scene_row.get('location') or '').strip()

    intent_summary = '\n'.join(
        f"- {k}: {v}" for k, v in intent_row.items() if (v or '').strip()
    )
    brief_summary = _format_brief(brief_row)

    return f"""\
You are drafting a graphic-novel scene as a panel-by-panel script for an
artist to illustrate.

# Scene context

- id: {scene_id}
- title: {title}
- target_pages: {target_pages}  ← produce exactly this many pages
- pov: {pov}
- location: {location}

# Scene intent

{intent_summary or '(none)'}

# Scene brief — every column is a contract you must honor

{brief_summary}

Specifically:
  - Every entry in `key_dialogue` MUST appear verbatim (or near-verbatim)
    as a word-balloon or caption line in the script.
  - Every entry in `visual_keywords` (semicolon-separated) MUST appear
    in some panel's composition prose.
  - The script's per-page panel structure MUST match `panel_breakdown`
    (e.g., `p1:splash` means page 1 has exactly 1 panel — a full splash).
  - Pages tagged in `page_turn_beats` MUST carry the ⟵ PAGE-TURN REVEAL
    marker on their page header line.
  - `caption_strategy` determines how narration is used: minimal,
    journal voiceover, omniscient narration, none, or as specified.

# Character visual references

{character_visuals or '(none provided)'}

# Location visual references

{location_visuals or '(none provided)'}

# Voice profile

{voice_profile_text or '(default)'}

{SCRIPT_FORMAT_INSTRUCTIONS}

Now write the script for scene `{scene_id}`. Produce exactly {target_pages}
pages. Begin with the H1 header `# Scene: {scene_id}` and follow the format
rules above. Do not write any commentary outside the script itself.
"""
