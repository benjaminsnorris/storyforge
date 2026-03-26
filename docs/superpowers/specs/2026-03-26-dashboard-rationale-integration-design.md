# Dashboard Rationale Integration

Enhance the visualization dashboard to surface all score rationales and add new visualizations for act, character, and genre scores.

## Problem

The scoring pipeline produces rich rationale prose alongside every numeric score — scene-level (25 principles per scene), act-level (9 frameworks per act), character-level (4 principles per character), genre-level (4 principles), and narrative-level (7 frameworks). None of this rationale data is currently visible in the dashboard. Additionally, act scores, character scores, and genre scores have no visualization at all. The narrative radar has a clipping bug that truncates labels.

## Design

### Data Loading

Add 7 new data sources to `visualize.py`'s `load_dashboard_data()`:

| JS Constant | CSV Path | Key Column |
|---|---|---|
| `SCENE_RATIONALES` | `working/scores/latest/scene-rationale.csv` | `id` |
| `ACT_SCORES` | `working/scores/latest/act-scores.csv` | `id` |
| `ACT_RATIONALES` | `working/scores/latest/act-rationale.csv` | `id` |
| `CHARACTER_SCORES` | `working/scores/latest/character-scores.csv` | `character` |
| `CHARACTER_RATIONALES` | `working/scores/latest/character-rationale.csv` | `character` |
| `GENRE_SCORES` | `working/scores/latest/genre-scores.csv` | (single row) |
| `GENRE_RATIONALES` | `working/scores/latest/genre-rationale.csv` | (single row) |
| `NARRATIVE_RATIONALES` | `working/scores/latest/narrative-rationale.csv` | `principle` |

All use the existing `csv_to_records()` function. Files that don't exist return empty arrays. Injected as JS constants in the data injection block alongside existing constants.

### Rationale Drawer

A shared UI component for displaying rationale text, used by all visualizations.

**HTML structure:** Each visualization section gets its own `<div class="rationale-drawer">` directly below it, initially hidden. Contains a header (title + close button) and a scrollable content area.

**Behavior:**
- `openRationaleDrawer(sectionId, title, content)` — finds the drawer within the given section, populates title and content, slides open via CSS transition.
- `closeRationaleDrawer(sectionId)` — slides closed.
- Multiple drawers can be open simultaneously, allowing cross-visualization comparison.
- Each drawer has its own close button. Escape closes the most recently opened one.

**Styling:**
- Full-width within the section container.
- Max-height ~40vh with overflow scroll.
- Same theme variables (light/dark mode).
- Subtle top border connecting it visually to the visualization above.
- Rationale text rendered as readable paragraphs — no special parsing needed, just `<p>` tags.

### New Visualizations

All new visualizations follow the existing IIFE pattern. Each section is hidden by default and shown only when its data exists.

**Genre Scores — Single Row of Horizontal Bars**
- 4 horizontal bars: trope_awareness, archetype_vs_cliche, genre_contract, subversion_awareness.
- Bars colored by score value (1-5, same color scale as the craft heatmap).
- Human-readable labels (e.g., "Trope Awareness", "Genre Contract").
- Click any bar → section's rationale drawer opens with that principle's rationale.

**Character Scores — Grouped Horizontal Bar Chart**
- One group per character.
- Within each group, 4 bars: want_need, wound_lie, flaws_as_strengths, voice_as_character.
- Same color scale and click-to-drawer behavior.

**Act Scores — Grouped Horizontal Bar Chart**
- One group per act (act-1, act-2, etc.).
- Within each group, 9 horizontal bars for the narrative framework principles (campbells_monomyth, three_act, save_the_cat, truby_22, harmon_circle, kishotenketsu, freytag, character_web, character_as_theme).
- Same color scale and click-to-drawer behavior.

**Dashboard ordering:** Existing scene visualizations → craft heatmap → genre scores → character scores → act scores → narrative radar (fixed).

### Existing Visualization Updates

**Narrative Radar — Bug Fix**
- Increase SVG viewBox width with additional left/right padding so labels like "Kishotenketsu" and "Freytag's Pyramid" render fully without clipping.
- Add click handler on score dots: clicking a dot opens the section's rationale drawer with that framework's narrative rationale.

**Craft Heatmap — Rationale Integration**
- Add click handler on individual cells: clicking a cell opens the section's rationale drawer with that scene+principle's rationale from `SCENE_RATIONALES`.
- Add `cursor: pointer` on cells to indicate clickability.

**Detail Panel — View Rationales Link**
- Below the craft scores grid, add a "View rationales" link.
- Clicking it opens the rationale drawer for the heatmap section, showing all 25 rationales for that scene, grouped by section (using craft-weights data for grouping).

### Files Modified

| File | Change |
|---|---|
| `scripts/lib/python/storyforge/visualize.py` | Add 7 new data sources to `load_dashboard_data()` |
| `scripts/storyforge-visualize` | Add JS constants injection, rationale drawer HTML/CSS/JS, 3 new visualization IIFEs, update narrative radar, update craft heatmap, update detail panel |

### Graceful Degradation

All rationale and new score features degrade gracefully:
- No rationale data → drawer click handlers are no-ops, no "View rationales" link shown.
- No act/character/genre score data → those sections stay hidden (same pattern as existing craft heatmap and narrative radar).
- Partial data (scores exist but rationales don't) → visualizations render normally, click-for-rationale simply doesn't appear.
