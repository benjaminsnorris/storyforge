"""Graphic-novel elaboration-stage prompts.

Mirrors prompts_elaborate.py for graphic-novel-mode projects. v1 covers:
  - scene-map (asks target_pages instead of target_words)
  - briefs (populates the five graphic-novel-specific brief columns alongside
    the standard brief fields)

Voice-stage extensions (caption_voice, lettering_style) live in the existing
prompts_elaborate.py voice prompt as conditional sections — they're small
additions, not a full prompt rewrite.
"""

SCENE_MAP_GN_PREAMBLE = """\
You are mapping the scene index for a graphic novel project.

For each scene, you will set:
  - target_pages — how many pages this scene occupies (comics are paced
    in pages, not word counts)
  - location, pov, timeline_day, time_of_day, type
  - characters, on_stage, mice_threads

Page-count heuristics (contemporary GN tradition; see
references/gn-layout-vocabulary.md "Scene-pace heuristics" for the
full table):
  - 1 page: single quiet beat (reaction, gesture, recognition)
  - 2-3 pages: short dialogue or action exchange
  - 4-6 pages: standard scene (setup, conflict, partial resolution)
  - 8-12 pages: set-piece scene (extended action, major confrontation)
  - 12-20 pages: decompressed climax (rare; only for the largest beats)
A scene's target_pages should match its dramatic scope. If you set
≥8 pages, the scene must genuinely be a set piece — otherwise
compress.
"""

BRIEFS_GN_PREAMBLE = """\
You are writing scene briefs for a graphic novel.

Every standard brief column applies (goal, conflict, outcome, crisis,
decision, knowledge_in, knowledge_out, key_actions, key_dialogue,
emotions, motifs, subtext, continuity_deps, physical_state_in,
physical_state_out). All have the same meaning as in prose: they describe
the scene's narrative contract.

Additionally, populate these graphic-novel columns:

  - page_layout: high-level rhythm intent for the scene, e.g.,
    "9-panel grid", "splash p3, 6-panel grid after", "double-spread climax p4-5"

  - panel_breakdown: per-page panel structure, e.g.,
    "p1:splash; p2:6-grid; p3:splash+3"
    Use semicolon-separated entries, one per page. Page tokens: splash,
    N-grid (e.g. 6-grid, 9-grid), double-spread, tier, irregular.

    Each token names a recognizable page form with a recognizable
    narrative effect — see references/gn-layout-vocabulary.md
    "Layout tokens" for the full vocabulary. Quick reference:
      - splash: one panel filling the page; biggest beat in the scene
      - double-spread: image across two pages; biggest beat in the
        manuscript (use sparingly — usually 0-2 per chapter)
      - 9-grid: Watchmen discipline; equal-weight panels; slow attention
      - 6-grid: standard contemporary grid; dialogue / mid-density action
      - tier: single horizontal row (2-4 panels); filmic motion
      - irregular: artist-designed page; reserve for moments breaking
        the grid

    Splash logic: every splash in a scene flattens the next splash's
    emphasis. Most scenes need zero splashes; one splash is plenty
    for most set pieces; two splashes in a 4-page scene is usually
    one too many.

  - visual_keywords: visual beats that must appear in the panel art,
    semicolon-separated, e.g., "blank parchment close; trembling hand;
    shadow under door". These are story beats the artist must include.

  - page_turn_beats: which beats must land on a page turn (recto-to-verso
    reveal). Semicolon-separated descriptions, each anchored to a panel
    in panel_breakdown. Used by the script-validation pass.

    The page-turn is comics' most-load-bearing tool: the reader sees
    a spread (verso + recto) at once, then turns to a new spread.
    Anything on the next verso (left page after turning) is a reveal.
    Strongest uses: cliffhanger setup on the prior recto, payoff
    splash on the new verso. NEVER mark a page-turn beat on page 1
    — there's no preceding page to turn from.

  - caption_strategy: narration style for this scene. Values:
    "minimal", "journal voiceover", "omniscient narration", "none",
    or a custom short phrase.

Panel-to-panel transitions: when composing key_actions across panels,
think in McCloud's six transition types (moment / action / subject /
scene / aspect / non-sequitur — see references/gn-layout-vocabulary.md
"Panel-to-panel transitions"). Action-to-action drives plot; moment-
to-moment carries emotion; aspect-to-aspect sets atmosphere; scene-
to-scene compresses. Match the transition to the beat.
"""


def build_scene_map_prompt(project_dir, scenes_csv_content, architecture_doc):
    """Build the scene-map elaboration prompt for graphic-novel mode.

    Args:
        project_dir: Path to the book project (reserved for future use,
                     e.g. reading storyforge.yaml project context).
        scenes_csv_content: Current scenes CSV as a string.
        architecture_doc: Story architecture document as a string.

    Returns:
        Prompt string for Claude.
    """
    return f"""{SCENE_MAP_GN_PREAMBLE}

# Story architecture

{architecture_doc}

# Current scene index

```
{scenes_csv_content}
```

### Output Format

Return the updated scene index inside a fenced block tagged `scenes-csv`,
populating target_pages for each scene:

```scenes-csv
id|seq|title|part|pov|location|timeline_day|time_of_day|duration|type|status|word_count|target_words|target_pages|panel_count|page_count
(all scenes — status is "mapped" for new/updated scenes)
```
"""


def build_briefs_prompt(project_dir, scene_id, scene_row, intent_row, existing_brief_row):
    """Build the brief-stage elaboration prompt for one scene (graphic-novel mode).

    Unlike the prose build_briefs_prompt (which operates on all scenes at once
    via CSV files on disk), this function operates on a single scene and takes
    pre-loaded row dicts. This matches the per-scene parallel execution pattern
    used by cmd_elaborate for GN mode.

    Args:
        project_dir: Path to the book project (reserved for future context use).
        scene_id: The scene ID to brief.
        scene_row: Dict of scenes.csv columns for this scene.
        intent_row: Dict of scene-intent.csv columns for this scene.
        existing_brief_row: Dict of scene-briefs.csv columns for this scene
                            (may be empty if no brief exists yet).

    Returns:
        Prompt string for Claude.
    """
    scene_summary = (
        f"id: {scene_row.get('id', '')}\n"
        f"title: {scene_row.get('title', '')}\n"
        f"target_pages: {scene_row.get('target_pages', '')}\n"
        f"type: {scene_row.get('type', '')}\n"
        f"pov: {scene_row.get('pov', '')}\n"
        f"location: {scene_row.get('location', '')}\n"
    )
    intent_summary = "\n".join(f"{k}: {v}" for k, v in intent_row.items())
    existing = "\n".join(f"{k}: {v}" for k, v in existing_brief_row.items() if v)

    return f"""{BRIEFS_GN_PREAMBLE}

# Scene to brief

{scene_summary}

# Scene intent

{intent_summary}

# Existing brief (if any)

{existing or '(none)'}

Return the brief as a single pipe-delimited row matching the scene-briefs.csv
header. Populate every column you can; leave only truly unknown fields blank.
"""
