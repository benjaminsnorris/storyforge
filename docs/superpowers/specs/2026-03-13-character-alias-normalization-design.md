# Character Alias Normalization

## Problem

When `storyforge-enrich` uses Claude to extract character names from scene prose, it gets inconsistent variants: "Maren Cole" vs "Maren", "Hank Voigt" vs "Henrik Voigt" vs "Hank". These fragment the Character Presence Grid in the dashboard and reduce the usefulness of character data in scene-intent.csv.

## Solution

A new optional artifact (`reference/characters.csv`) maps canonical character names to their aliases. Normalization happens at two points: write time (enrich) and read time (visualize), belt-and-suspenders style.

## New Artifact: `reference/characters.csv`

Pipe-delimited canonical character registry:

```
id|name|aliases|role
maren-cole|Maren Cole|Maren|protagonist
hank-voigt|Hank Voigt|Hank;Henrik Voigt;Henrik "Hank" Voigt|protagonist
rook|Rook||supporting
```

- **id**: slug, stable key
- **name**: canonical display name (used in visualizations and normalized data)
- **aliases**: semicolon-separated alternate names Claude might extract
- **role**: `protagonist`, `antagonist`, `supporting`, `minor`
- Optional artifact. Everything degrades gracefully if absent.

## New Shared Library: `scripts/lib/characters.sh`

Auto-sourced by common.sh.

### `load_character_aliases(characters_csv)`

Builds a lookup file (one `lowercase_alias|canonical_name` pair per line). Includes canonical names as self-mappings. All aliases lowercased for case-insensitive matching. Returns the temp file path via stdout.

### `normalize_characters(aliases_file, raw_characters_string)`

Takes a semicolon-separated character string, splits on `;`, looks up each name (case-insensitive) in the aliases file, replaces matches with canonical names, passes through unknowns unchanged, deduplicates (since "Maren" and "Maren Cole" might both resolve to the same canonical name), returns the normalized semicolon-separated string.

## Changes to `storyforge-enrich`

Before the main enrichment loop, load aliases if characters.csv exists:

```bash
CHARACTERS_CSV="${PROJECT_DIR}/reference/characters.csv"
ALIASES_FILE=""
if [[ -f "$CHARACTERS_CSV" ]]; then
    ALIASES_FILE=$(load_character_aliases "$CHARACTERS_CSV")
    log "Loaded character aliases from characters.csv"
fi
```

In each worker subshell, after parsing Claude's CHARACTERS response and before writing to the result file, normalize:

```bash
if [[ -n "$ALIASES_FILE" ]]; then
    characters_val=$(normalize_characters "$ALIASES_FILE" "$characters_val")
fi
```

## Changes to `storyforge-visualize`

In the Character Presence Grid JavaScript, before frequency counting:

1. If characters.csv data is available, build a JS alias map: `{lowercase_alias: canonical_name}`
2. Apply when processing `INTENTS[].characters` — normalize each name before counting
3. Also normalize POV names against the same map

The visualize script already reads CSV data into JS objects. Characters.csv is read the same way and injected as a `CHARACTERS` constant.

## Documentation Changes

### `references/scene-schema.md`

Update the `characters` field description to note: "Names should match canonical entries in `reference/characters.csv` when it exists."

### `references/storyforge-yaml-schema.md`

Add `characters` artifact entry in the artifacts block, marking it optional.

### `skills/scenes/SKILL.md`

In the enrichment section, mention that if characters.csv exists, extracted names will be normalized against it. Suggest creating it from the character bible before enrichment.

### `templates/characters.csv`

Template with header row and example, scaffolded by init.

## Design Principles

- **Optional**: if characters.csv doesn't exist, everything works as before
- **Normalization at write time AND read time**: belt and suspenders
- **Case-insensitive matching**: "maren" matches "Maren Cole"
- **Unknown names pass through**: minor characters not in the registry are preserved
- **No changes to character bible**: the CSV is the structured/queryable layer; the bible stays prose
- **Shared library**: `characters.sh` follows existing pattern (`csv.sh`, `scene-filter.sh`, `scoring.sh`)

## Tests

New `tests/test-characters.sh`:

- `load_character_aliases` builds correct lookup from fixture CSV
- `normalize_characters` resolves known aliases to canonical names
- `normalize_characters` passes through unknown names unchanged
- `normalize_characters` deduplicates after resolution
- `normalize_characters` is case-insensitive
- Graceful no-op when no aliases file
