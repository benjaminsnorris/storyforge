# Publish Manifest & Chapter Map Staleness Detection

**Date:** 2026-04-08
**Status:** Approved
**Fixes:** #148

## Problem

The current publish pipeline assembles chapters as HTML files, then the bookshelf publish script parses them back apart to extract scenes. This introduces three classes of bugs (issue #148):
1. Non-zero-padded filenames break alphabetical sort at 10+ chapters
2. Scene content lacks `<section data-scene>` attributes the publish script expects
3. Output directory paths don't match between assembly and publish

Additionally, the chapter map can go stale when scenes are added, removed, or reordered during revision — and nothing detects this before publish or evaluation.

## Solution

Eliminate the assembly step from the publish pipeline entirely. Storyforge converts scene markdown to HTML and writes a JSON manifest that the bookshelf publish script reads directly. Add chapter map freshness checking.

## Design

### 1. Chapter Map Freshness Check

New function in `common.py`:

```python
def check_chapter_map_freshness(project_dir):
    """Compare scene IDs in scenes.csv against chapter-map.csv.

    Returns:
        (is_fresh, missing_from_map, extra_in_map)
        - is_fresh: True if all active scenes are in the map and vice versa
        - missing_from_map: scene IDs in scenes.csv but not in chapter-map.csv
        - extra_in_map: scene IDs in chapter-map.csv but not in scenes.csv
    """
```

- Reads scene IDs from `scenes.csv`, excluding `status` in `('cut', 'merged', 'archived')`
- Reads scene IDs from `chapter-map.csv` by parsing the `scenes` column (semicolon-separated)
- Returns the diff

Called by:
- `storyforge publish` — **hard stop** if stale
- `storyforge assemble` — **warning** if stale
- `storyforge evaluate --manuscript` — **hard stop** if stale

### 2. Publish Manifest Generation

New function in `assembly.py` (or a new `publish.py` module):

```python
def generate_publish_manifest(project_dir, cover_path=None):
    """Generate a JSON publish manifest from scene files and chapter map.

    Converts each scene's markdown to HTML, groups by chapter from
    chapter-map.csv, and writes working/publish-manifest.json.

    Returns:
        Path to the manifest file.
    """
```

Flow:
1. Check chapter map freshness — abort if stale
2. Read `storyforge.yaml` for title, author, slug
3. Read `chapter-map.csv` for chapter structure
4. For each chapter, for each scene:
   - Read `scenes/{scene_id}.md`
   - Convert markdown to HTML via `_md_to_html()` (existing function in assembly.py)
   - Compute word count from the prose
5. Write `working/publish-manifest.json`:

```json
{
  "title": "The Rend",
  "author": "Ben Norris",
  "slug": "the-rend",
  "cover_path": "assets/cover.jpg",
  "generated_at": "2026-04-08T17:30:00Z",
  "chapters": [
    {
      "number": 1,
      "title": "The Finest Cartographer",
      "scenes": [
        {
          "slug": "act1-sc01",
          "content_html": "<p>The morning light...</p>",
          "word_count": 2340,
          "sort_order": 1
        }
      ]
    }
  ]
}
```

### 3. Updated `cmd_publish.py` (or publish skill delegation)

The `storyforge publish` command:
1. Calls `check_chapter_map_freshness()` — hard stop if stale
2. Calls `generate_publish_manifest()` to create the manifest
3. Invokes the bookshelf publish script:
   ```bash
   npx tsx scripts/publish-book.ts --manifest <manifest_path>
   ```
4. Copies dashboard if it exists

### 4. Updated Bookshelf `publish-book.ts`

New `--manifest <path>` flag. When provided:
- Reads JSON manifest instead of scanning chapter HTML files
- Extracts book metadata from the manifest (title, author, slug)
- Upserts chapters and scenes from the manifest data
- Scenes already have `slug`, `content_html`, `word_count`, `sort_order`
- Re-anchoring logic stays the same — it compares old content_html to new content_html
- Cleanup of removed chapters/scenes stays the same
- Cover handling stays the same (reads `cover_path` from manifest)

The existing HTML-parsing mode stays for backwards compatibility but is no longer the primary path.

### 5. Evaluate --manuscript Update

When `--manuscript` is used:
- Call `check_chapter_map_freshness()` — hard stop if stale
- Read scenes in chapter order from chapter-map.csv instead of reading assembled chapter files
- This means evaluate --manuscript no longer requires assembly

## Files Changed

### Storyforge

| File | Change |
|------|--------|
| `scripts/lib/python/storyforge/common.py` | Add `check_chapter_map_freshness()` |
| `scripts/lib/python/storyforge/assembly.py` | Add `generate_publish_manifest()` |
| `scripts/lib/python/storyforge/cmd_assemble.py` | Call freshness check, warn if stale |
| `scripts/lib/python/storyforge/cmd_evaluate.py` | Call freshness check for --manuscript, read scenes via chapter map |
| `skills/publish/SKILL.md` | Update to use manifest-based publish |
| `tests/test_chapter_map_freshness.py` | New: freshness check tests |
| `tests/test_publish_manifest.py` | New: manifest generation tests |

### Bookshelf

| File | Change |
|------|--------|
| `scripts/publish-book.ts` | Add `--manifest` flag, read from JSON manifest |

## Testing

### Freshness check tests
- Scenes match chapter map → is_fresh=True
- Scene added but not in map → missing_from_map includes it
- Scene in map but cut from scenes.csv → extra_in_map includes it
- Empty chapter map → all scenes missing
- Scene with status=cut excluded from check

### Manifest generation tests
- Generates valid JSON with correct structure
- Scenes converted to HTML (contains `<p>` tags)
- Word counts computed
- Chapter ordering matches chapter-map.csv
- Aborts if chapter map is stale

## Migration

- No database migration needed — the Supabase schema (books/chapters/scenes) is unchanged
- The manifest is a new intermediate format; old publish flow still works via the existing HTML-parsing path
- Existing bookshelf deployments continue to work — `--manifest` is additive
