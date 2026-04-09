# Publish Manifest & Chapter Map Staleness Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Eliminate assembly from the publish pipeline by publishing scene HTML directly via a JSON manifest, add chapter map staleness detection, and update the bookshelf publish script to read manifests.

**Architecture:** Storyforge generates a `publish-manifest.json` (scene markdown → HTML, grouped by chapter map). The bookshelf `publish-book.ts` gains a `--manifest` flag to read this instead of parsing assembled HTML. A freshness check in `common.py` detects when the chapter map is out of sync with scenes.csv.

**Tech Stack:** Python 3.14, pytest, TypeScript/Node (bookshelf), pandoc, Supabase

---

## File Map

| File | Action | Responsibility |
|------|--------|----------------|
| `scripts/lib/python/storyforge/common.py` | Modify | Add `check_chapter_map_freshness()` |
| `scripts/lib/python/storyforge/assembly.py` | Modify | Add `generate_publish_manifest()` |
| `scripts/lib/python/storyforge/cmd_assemble.py` | Modify | Call freshness check, warn if stale |
| `scripts/lib/python/storyforge/cmd_evaluate.py` | Modify | Call freshness check for --manuscript, read scenes via chapter map |
| `skills/publish/SKILL.md` | Modify | Update to use manifest-based publish |
| `tests/test_chapter_map_freshness.py` | Create | Freshness check tests |
| `tests/test_publish_manifest.py` | Create | Manifest generation tests |
| `~/Developer/bookshelf/scripts/publish-book.ts` | Modify | Add `--manifest` flag, read from JSON |
| `CLAUDE.md` | Modify | Document freshness check |
| `.claude-plugin/plugin.json` | Modify | Bump version to 1.7.0 |

---

### Task 1: Chapter Map Freshness Check

**Files:**
- Create: `tests/test_chapter_map_freshness.py`
- Modify: `scripts/lib/python/storyforge/common.py`

- [ ] **Step 1: Write failing tests**

```python
# tests/test_chapter_map_freshness.py
"""Tests for chapter map freshness checking."""

import os


class TestCheckChapterMapFreshness:
    def test_fresh_when_all_scenes_in_map(self, project_dir):
        """All active scenes are in the chapter map and vice versa."""
        from storyforge.common import check_chapter_map_freshness
        is_fresh, missing, extra = check_chapter_map_freshness(project_dir)
        assert is_fresh is True
        assert missing == []
        assert extra == []

    def test_missing_scene_not_in_map(self, tmp_path):
        """Scene in scenes.csv but not in chapter-map.csv."""
        from storyforge.common import check_chapter_map_freshness
        ref = tmp_path / 'reference'
        ref.mkdir()
        (ref / 'scenes.csv').write_text(
            'id|seq|title|part|pov|location|timeline_day|time_of_day|duration|type|status|word_count|target_words\n'
            'scene-a|1|A|1|k|here|1|morning|short|action|drafted|1000|1500\n'
            'scene-b|2|B|1|k|here|1|morning|short|action|drafted|1000|1500\n'
        )
        (ref / 'chapter-map.csv').write_text(
            'chapter|title|heading|part|scenes\n'
            '1|Ch One|numbered|1|scene-a\n'
        )
        is_fresh, missing, extra = check_chapter_map_freshness(str(tmp_path))
        assert is_fresh is False
        assert 'scene-b' in missing
        assert extra == []

    def test_extra_scene_in_map_but_cut(self, tmp_path):
        """Scene in chapter-map.csv but cut from scenes.csv."""
        from storyforge.common import check_chapter_map_freshness
        ref = tmp_path / 'reference'
        ref.mkdir()
        (ref / 'scenes.csv').write_text(
            'id|seq|title|part|pov|location|timeline_day|time_of_day|duration|type|status|word_count|target_words\n'
            'scene-a|1|A|1|k|here|1|morning|short|action|drafted|1000|1500\n'
            'scene-b|2|B|1|k|here|1|morning|short|action|cut|1000|1500\n'
        )
        (ref / 'chapter-map.csv').write_text(
            'chapter|title|heading|part|scenes\n'
            '1|Ch One|numbered|1|scene-a;scene-b\n'
        )
        is_fresh, missing, extra = check_chapter_map_freshness(str(tmp_path))
        assert is_fresh is False
        assert missing == []
        assert 'scene-b' in extra

    def test_cut_scenes_excluded(self, tmp_path):
        """Scenes with status cut/merged/archived are excluded from the check."""
        from storyforge.common import check_chapter_map_freshness
        ref = tmp_path / 'reference'
        ref.mkdir()
        (ref / 'scenes.csv').write_text(
            'id|seq|title|part|pov|location|timeline_day|time_of_day|duration|type|status|word_count|target_words\n'
            'scene-a|1|A|1|k|here|1|morning|short|action|drafted|1000|1500\n'
            'scene-cut|2|Cut|1|k|here|1|morning|short|action|cut|0|0\n'
            'scene-merged|3|Merged|1|k|here|1|morning|short|action|merged|0|0\n'
        )
        (ref / 'chapter-map.csv').write_text(
            'chapter|title|heading|part|scenes\n'
            '1|Ch One|numbered|1|scene-a\n'
        )
        is_fresh, missing, extra = check_chapter_map_freshness(str(tmp_path))
        assert is_fresh is True

    def test_no_chapter_map(self, tmp_path):
        """Missing chapter map means all scenes are missing."""
        from storyforge.common import check_chapter_map_freshness
        ref = tmp_path / 'reference'
        ref.mkdir()
        (ref / 'scenes.csv').write_text(
            'id|seq|title|part|pov|location|timeline_day|time_of_day|duration|type|status|word_count|target_words\n'
            'scene-a|1|A|1|k|here|1|morning|short|action|drafted|1000|1500\n'
        )
        is_fresh, missing, extra = check_chapter_map_freshness(str(tmp_path))
        assert is_fresh is False
        assert 'scene-a' in missing

    def test_no_scenes_csv(self, tmp_path):
        """Missing scenes.csv returns fresh with empty sets."""
        from storyforge.common import check_chapter_map_freshness
        ref = tmp_path / 'reference'
        ref.mkdir()
        (ref / 'chapter-map.csv').write_text(
            'chapter|title|heading|part|scenes\n'
            '1|Ch One|numbered|1|scene-a\n'
        )
        is_fresh, missing, extra = check_chapter_map_freshness(str(tmp_path))
        assert is_fresh is False
        assert 'scene-a' in extra
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python3 -m pytest tests/test_chapter_map_freshness.py -v`
Expected: FAIL — `check_chapter_map_freshness` not found

- [ ] **Step 3: Implement `check_chapter_map_freshness()`**

Add to `scripts/lib/python/storyforge/common.py` near the other project utility functions:

```python
def check_chapter_map_freshness(project_dir: str) -> tuple[bool, list[str], list[str]]:
    """Compare scene IDs in scenes.csv against chapter-map.csv.

    Scenes with status in ('cut', 'merged', 'archived') are excluded.

    Returns:
        (is_fresh, missing_from_map, extra_in_map)
        - is_fresh: True if all active scenes are in the map and vice versa
        - missing_from_map: scene IDs in scenes.csv but not in chapter-map.csv
        - extra_in_map: scene IDs in chapter-map.csv but not in scenes.csv (active)
    """
    from storyforge.csv_cli import get_column

    scenes_csv = os.path.join(project_dir, 'reference', 'scenes.csv')
    chapter_map_csv = os.path.join(project_dir, 'reference', 'chapter-map.csv')

    # Get active scene IDs from scenes.csv
    active_ids = set()
    excluded_statuses = {'cut', 'merged', 'archived'}
    if os.path.isfile(scenes_csv):
        all_ids = get_column(scenes_csv, 'id')
        all_statuses = get_column(scenes_csv, 'status')
        for sid, status in zip(all_ids, all_statuses):
            if sid and status.strip().lower() not in excluded_statuses:
                active_ids.add(sid.strip())

    # Get scene IDs from chapter-map.csv
    map_ids = set()
    if os.path.isfile(chapter_map_csv):
        scenes_col = get_column(chapter_map_csv, 'scenes')
        for cell in scenes_col:
            for sid in cell.split(';'):
                sid = sid.strip()
                if sid:
                    map_ids.add(sid)

    missing_from_map = sorted(active_ids - map_ids)
    extra_in_map = sorted(map_ids - active_ids)
    is_fresh = len(missing_from_map) == 0 and len(extra_in_map) == 0

    return is_fresh, missing_from_map, extra_in_map
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `python3 -m pytest tests/test_chapter_map_freshness.py -v`
Expected: All PASS

- [ ] **Step 5: Run full test suite**

Run: `python3 -m pytest tests/ -q`
Expected: All pass

- [ ] **Step 6: Commit**

```bash
git add tests/test_chapter_map_freshness.py scripts/lib/python/storyforge/common.py
git commit -m "Add chapter map freshness check"
git push
```

---

### Task 2: Publish Manifest Generation

**Files:**
- Create: `tests/test_publish_manifest.py`
- Modify: `scripts/lib/python/storyforge/assembly.py`

- [ ] **Step 1: Write failing tests**

```python
# tests/test_publish_manifest.py
"""Tests for publish manifest generation."""

import json
import os


class TestGeneratePublishManifest:
    def test_generates_valid_json(self, project_dir):
        """Manifest is valid JSON with expected structure."""
        from storyforge.assembly import generate_publish_manifest
        # Create scene files for the fixture scenes
        scenes_dir = os.path.join(project_dir, 'scenes')
        os.makedirs(scenes_dir, exist_ok=True)
        for sid in ('act1-sc01', 'act1-sc02', 'act2-sc01'):
            with open(os.path.join(scenes_dir, f'{sid}.md'), 'w') as f:
                f.write(f'The prose for scene {sid}. Some words here to count.\n')

        path = generate_publish_manifest(project_dir)
        assert os.path.isfile(path)
        with open(path) as f:
            manifest = json.load(f)

        assert 'title' in manifest
        assert 'author' in manifest
        assert 'slug' in manifest
        assert 'chapters' in manifest
        assert 'generated_at' in manifest

    def test_chapters_match_chapter_map(self, project_dir):
        """Chapters in manifest match chapter-map.csv ordering."""
        from storyforge.assembly import generate_publish_manifest
        scenes_dir = os.path.join(project_dir, 'scenes')
        os.makedirs(scenes_dir, exist_ok=True)
        for sid in ('act1-sc01', 'act1-sc02', 'act2-sc01'):
            with open(os.path.join(scenes_dir, f'{sid}.md'), 'w') as f:
                f.write(f'Prose for {sid}.\n')

        path = generate_publish_manifest(project_dir)
        with open(path) as f:
            manifest = json.load(f)

        assert len(manifest['chapters']) == 2
        ch1 = manifest['chapters'][0]
        assert ch1['number'] == 1
        assert ch1['title'] == 'The Finest Cartographer'
        assert len(ch1['scenes']) == 2
        assert ch1['scenes'][0]['slug'] == 'act1-sc01'
        assert ch1['scenes'][1]['slug'] == 'act1-sc02'

        ch2 = manifest['chapters'][1]
        assert ch2['number'] == 2
        assert len(ch2['scenes']) == 1

    def test_scenes_have_html_content(self, project_dir):
        """Scene content is converted to HTML."""
        from storyforge.assembly import generate_publish_manifest
        scenes_dir = os.path.join(project_dir, 'scenes')
        os.makedirs(scenes_dir, exist_ok=True)
        with open(os.path.join(scenes_dir, 'act1-sc01.md'), 'w') as f:
            f.write('The morning light fell across the map table.\n')
        with open(os.path.join(scenes_dir, 'act1-sc02.md'), 'w') as f:
            f.write('Second scene.\n')
        with open(os.path.join(scenes_dir, 'act2-sc01.md'), 'w') as f:
            f.write('Third scene.\n')

        path = generate_publish_manifest(project_dir)
        with open(path) as f:
            manifest = json.load(f)

        scene = manifest['chapters'][0]['scenes'][0]
        assert '<p>' in scene['content_html']
        assert 'morning light' in scene['content_html']

    def test_word_counts_computed(self, project_dir):
        """Each scene has a word_count."""
        from storyforge.assembly import generate_publish_manifest
        scenes_dir = os.path.join(project_dir, 'scenes')
        os.makedirs(scenes_dir, exist_ok=True)
        with open(os.path.join(scenes_dir, 'act1-sc01.md'), 'w') as f:
            f.write('One two three four five.\n')
        for sid in ('act1-sc02', 'act2-sc01'):
            with open(os.path.join(scenes_dir, f'{sid}.md'), 'w') as f:
                f.write('Word.\n')

        path = generate_publish_manifest(project_dir)
        with open(path) as f:
            manifest = json.load(f)

        scene = manifest['chapters'][0]['scenes'][0]
        assert scene['word_count'] == 5

    def test_sort_order_sequential(self, project_dir):
        """Scenes have sequential sort_order within each chapter."""
        from storyforge.assembly import generate_publish_manifest
        scenes_dir = os.path.join(project_dir, 'scenes')
        os.makedirs(scenes_dir, exist_ok=True)
        for sid in ('act1-sc01', 'act1-sc02', 'act2-sc01'):
            with open(os.path.join(scenes_dir, f'{sid}.md'), 'w') as f:
                f.write('Prose.\n')

        path = generate_publish_manifest(project_dir)
        with open(path) as f:
            manifest = json.load(f)

        ch1_scenes = manifest['chapters'][0]['scenes']
        assert ch1_scenes[0]['sort_order'] == 1
        assert ch1_scenes[1]['sort_order'] == 2

    def test_manifest_path(self, project_dir):
        """Manifest is written to working/publish-manifest.json."""
        from storyforge.assembly import generate_publish_manifest
        scenes_dir = os.path.join(project_dir, 'scenes')
        os.makedirs(scenes_dir, exist_ok=True)
        for sid in ('act1-sc01', 'act1-sc02', 'act2-sc01'):
            with open(os.path.join(scenes_dir, f'{sid}.md'), 'w') as f:
                f.write('Prose.\n')

        path = generate_publish_manifest(project_dir)
        assert path == os.path.join(project_dir, 'working', 'publish-manifest.json')

    def test_stale_chapter_map_raises(self, tmp_path):
        """Stale chapter map raises ValueError."""
        from storyforge.assembly import generate_publish_manifest
        ref = tmp_path / 'reference'
        ref.mkdir()
        (ref / 'scenes.csv').write_text(
            'id|seq|title|part|pov|location|timeline_day|time_of_day|duration|type|status|word_count|target_words\n'
            'scene-a|1|A|1|k|here|1|morning|short|action|drafted|1000|1500\n'
            'scene-b|2|B|1|k|here|1|morning|short|action|drafted|1000|1500\n'
        )
        (ref / 'chapter-map.csv').write_text(
            'chapter|title|heading|part|scenes\n'
            '1|Ch|numbered|1|scene-a\n'
        )
        (tmp_path / 'storyforge.yaml').write_text('project:\n  title: Test\n  author: Me\n')
        import pytest
        with pytest.raises(ValueError, match='stale'):
            generate_publish_manifest(str(tmp_path))
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python3 -m pytest tests/test_publish_manifest.py -v`
Expected: FAIL — `generate_publish_manifest` not found

- [ ] **Step 3: Implement `generate_publish_manifest()`**

Add to `scripts/lib/python/storyforge/assembly.py`:

```python
def generate_publish_manifest(project_dir: str, cover_path: str | None = None) -> str:
    """Generate a JSON publish manifest from scene files and chapter map.

    Converts each scene's markdown to HTML, groups by chapter from
    chapter-map.csv, and writes working/publish-manifest.json.

    Args:
        project_dir: Root directory of the project.
        cover_path: Optional path to cover image (relative to project_dir).

    Returns:
        Path to the generated manifest file.

    Raises:
        ValueError: If the chapter map is stale.
    """
    from storyforge.common import check_chapter_map_freshness, read_yaml_field

    # Check freshness
    is_fresh, missing, extra = check_chapter_map_freshness(project_dir)
    if not is_fresh:
        parts = []
        if missing:
            parts.append(f'scenes not in chapter map: {", ".join(missing)}')
        if extra:
            parts.append(f'chapter map references removed scenes: {", ".join(extra)}')
        raise ValueError(f'Chapter map is stale — {"; ".join(parts)}')

    title = read_yaml_field('project.title', project_dir) or 'Untitled'
    author = read_yaml_field('project.author', project_dir) or 'Unknown'
    slug = re.sub(r'[^a-z0-9]+', '-', title.lower()).strip('-')

    scenes_dir = os.path.join(project_dir, 'scenes')
    total_chapters = count_chapters(project_dir)

    chapters = []
    for ch_num in range(1, total_chapters + 1):
        ch_title = read_chapter_field(ch_num, project_dir, 'title')
        scene_ids = get_chapter_scenes(ch_num, project_dir)

        scenes = []
        for sort_idx, scene_id in enumerate(scene_ids, 1):
            scene_file = os.path.join(scenes_dir, f'{scene_id}.md')
            if not os.path.isfile(scene_file):
                continue

            with open(scene_file) as f:
                md = f.read()

            # Strip YAML frontmatter if present
            if md.startswith('---'):
                end = md.find('---', 3)
                if end != -1:
                    md = md[end + 3:].strip()

            html = _md_to_html(md)
            word_count = len(md.split())

            scenes.append({
                'slug': scene_id,
                'content_html': html.strip(),
                'word_count': word_count,
                'sort_order': sort_idx,
            })

        chapters.append({
            'number': ch_num,
            'title': ch_title,
            'scenes': scenes,
        })

    manifest = {
        'title': title,
        'author': author,
        'slug': slug,
        'cover_path': cover_path or '',
        'generated_at': datetime.utcnow().isoformat() + 'Z',
        'chapters': chapters,
    }

    import json
    output_path = os.path.join(project_dir, 'working', 'publish-manifest.json')
    os.makedirs(os.path.dirname(output_path), exist_ok=True)
    with open(output_path, 'w') as f:
        json.dump(manifest, f, indent=2, ensure_ascii=False)

    return output_path
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `python3 -m pytest tests/test_publish_manifest.py -v`
Expected: All PASS

- [ ] **Step 5: Run full test suite**

Run: `python3 -m pytest tests/ -q`
Expected: All pass

- [ ] **Step 6: Commit**

```bash
git add tests/test_publish_manifest.py scripts/lib/python/storyforge/assembly.py
git commit -m "Add publish manifest generation from scenes and chapter map"
git push
```

---

### Task 3: Wire Freshness Check into cmd_assemble and cmd_evaluate

**Files:**
- Modify: `scripts/lib/python/storyforge/cmd_assemble.py`
- Modify: `scripts/lib/python/storyforge/cmd_evaluate.py`

- [ ] **Step 1: Add freshness warning to cmd_assemble.py**

Find where assembly begins in `cmd_assemble.py` (after project_dir is resolved, before chapters are processed). Add:

```python
    from storyforge.common import check_chapter_map_freshness
    is_fresh, missing, extra = check_chapter_map_freshness(project_dir)
    if not is_fresh:
        log('WARNING: Chapter map may be out of date')
        if missing:
            log(f'  Scenes not in chapter map: {", ".join(missing)}')
        if extra:
            log(f'  Chapter map references removed/cut scenes: {", ".join(extra)}')
        log('  Run the produce skill to update the chapter map before assembling.')
```

- [ ] **Step 2: Add freshness check to cmd_evaluate.py --manuscript mode**

In `cmd_evaluate.py`, in the `_build_file_list` function (around line 209), where `filter_mode in ('manuscript', 'chapter')` is checked, add a freshness check before proceeding:

```python
    if filter_mode in ('manuscript', 'chapter'):
        # Check chapter map freshness
        from storyforge.common import check_chapter_map_freshness
        is_fresh, missing, extra = check_chapter_map_freshness(project_dir)
        if not is_fresh:
            parts = []
            if missing:
                parts.append(f'scenes not in chapter map: {", ".join(missing[:5])}')
            if extra:
                parts.append(f'chapter map references removed scenes: {", ".join(extra[:5])}')
            log(f'ERROR: Chapter map is stale — {"; ".join(parts)}')
            log('Update the chapter map before evaluating the manuscript.')
            sys.exit(1)
```

- [ ] **Step 3: Run full test suite**

Run: `python3 -m pytest tests/ -q`
Expected: All pass (no existing tests exercise these code paths with stale maps)

- [ ] **Step 4: Commit**

```bash
git add scripts/lib/python/storyforge/cmd_assemble.py scripts/lib/python/storyforge/cmd_evaluate.py
git commit -m "Wire chapter map freshness checks into assemble and evaluate"
git push
```

---

### Task 4: Update Bookshelf publish-book.ts with --manifest Mode

**Files:**
- Modify: `~/Developer/bookshelf/scripts/publish-book.ts`

- [ ] **Step 1: Add manifest reading to publish-book.ts**

At the top of the `main()` function (after `const args = process.argv.slice(2)`), add manifest flag detection:

```typescript
  const manifestFlag = args.find(a => a === '--manifest')
  const manifestIndex = args.indexOf('--manifest')
  const manifestPath = manifestIndex >= 0 ? resolve(args[manifestIndex + 1]) : null
```

After the existing `bookPath` setup and metadata reading, add an alternative path when `--manifest` is provided:

```typescript
  let bookTitle: string
  let bookAuthor: string
  let slug: string
  let chapterData: { number: number; title: string; scenes: { slug: string; content_html: string; word_count: number; sort_order: number }[] }[]
  let coverSourcePath: string | null = null

  if (manifestPath) {
    // ---- Manifest mode: read JSON directly ----
    if (!existsSync(manifestPath)) {
      console.error(`Manifest not found at ${manifestPath}`)
      process.exit(1)
    }
    const manifest = JSON.parse(readFileSync(manifestPath, 'utf-8'))
    bookTitle = manifest.title || 'Untitled'
    bookAuthor = manifest.author || 'Unknown'
    slug = manifest.slug || slugify(bookTitle)
    chapterData = manifest.chapters || []

    if (manifest.cover_path && bookPath) {
      const candidatePath = join(bookPath, manifest.cover_path)
      if (existsSync(candidatePath)) coverSourcePath = candidatePath
    }

    console.log(`Publishing "${bookTitle}" by ${bookAuthor} (slug: ${slug}) from manifest`)
    console.log(`  ${chapterData.length} chapters, ${chapterData.reduce((sum, ch) => sum + ch.scenes.length, 0)} scenes`)
  } else {
    // ---- Legacy mode: parse HTML chapter files ----
    // ... existing code (metadataPath, webChaptersPath, etc.) ...
  }
```

Then refactor the chapter/scene processing loop. Currently it reads HTML files and calls `extractMainContent()`. In manifest mode, the data is already structured:

```typescript
  // In the Phase 2 loop, replace the HTML-reading block with:
  for (const chapter of chapterData) {
    const chapterNumber = chapter.number
    const title = chapter.title
    const scenes = chapter.scenes.map((s, i) => ({
      number: i + 1,
      slug: s.slug,
      html: s.content_html,
    }))

    // ... rest of existing upsert logic (unchanged) ...
  }
```

For legacy mode, build `chapterData` from the existing HTML parsing:

```typescript
  } else {
    // Legacy mode
    const metadata = parseYamlFrontmatter(readFileSync(metadataPath, 'utf-8'))
    bookTitle = metadata.title || 'Untitled'
    bookAuthor = metadata.author || 'Unknown'
    slug = slugify(bookTitle)

    const chapterFiles = readdirSync(webChaptersPath)
      .filter(f => f.match(/^chapter-\d+\.html$/))
      .sort((a, b) => {
        const numA = parseInt(a.match(/\d+/)![0])
        const numB = parseInt(b.match(/\d+/)![0])
        return numA - numB
      })

    chapterData = chapterFiles.map((file, i) => {
      const html = readFileSync(join(webChaptersPath, file), 'utf-8')
      const { title, scenes } = extractMainContent(html)
      return {
        number: i + 1,
        title,
        scenes: scenes.map((s, j) => ({
          slug: s.slug,
          content_html: s.html,
          word_count: countWords(s.html),
          sort_order: j + 1,
        })),
      }
    })

    // Also fix the legacy sort bug while we're here (numeric instead of alpha)
    console.log(`Publishing "${bookTitle}" by ${bookAuthor} (slug: ${slug})`)
    console.log(`  ${chapterData.length} chapters`)
  }
```

This also fixes issue #148 point 1 (sort bug) in the legacy path by using numeric sort.

- [ ] **Step 2: Unify the processing loop**

Replace the existing `for (let i = 0; i < chapterFiles.length; i++)` loop with:

```typescript
  for (const chapter of chapterData) {
    const chapterNumber = chapter.number
    console.log(`  Chapter ${chapterNumber}: "${chapter.title}" (${chapter.scenes.length} scenes)`)

    // Upsert chapter (existing code, unchanged)
    const existingChapter = existingChapterByNumber.get(chapterNumber)
    let chapterId: string
    // ... same upsert logic ...

    // Upsert scenes
    for (const scene of chapter.scenes) {
      const wordCount = scene.word_count || countWords(scene.content_html)
      totalWords += wordCount

      const sceneKey = `${chapterId}:${scene.slug}`
      const existingScene = existingSceneMap.get(sceneKey)

      // ... same upsert/re-anchor logic (uses scene.content_html instead of scene.html) ...
    }

    totalScenes += chapter.scenes.length
  }
```

- [ ] **Step 3: Update summary output**

Change the summary to use `chapterData.length` instead of `chapterFiles.length`:

```typescript
  console.log(`\nDone! Published:`)
  console.log(`  ${chapterData.length} chapters`)
  console.log(`  ${totalScenes} scenes`)
```

- [ ] **Step 4: Test manually**

Generate a manifest from rend and test the new path:

```bash
cd ~/Developer/storyforge && PYTHONPATH=scripts/lib/python python3 -c "
from storyforge.assembly import generate_publish_manifest
path = generate_publish_manifest(os.path.expanduser('~/Developer/rend'))
print(f'Manifest: {path}')
import json
with open(path) as f:
    m = json.load(f)
print(f'Chapters: {len(m[\"chapters\"])}, Scenes: {sum(len(c[\"scenes\"]) for c in m[\"chapters\"])}')
"
```

Then test the bookshelf script:

```bash
cd ~/Developer/bookshelf && npx tsx scripts/publish-book.ts ~/Developer/rend --manifest ~/Developer/rend/working/publish-manifest.json
```

- [ ] **Step 5: Commit bookshelf changes**

```bash
cd ~/Developer/bookshelf && git add scripts/publish-book.ts && git commit -m "Add --manifest flag for direct scene publishing (fixes storyforge#148)" && git push
```

- [ ] **Step 6: Commit storyforge (no code changes, just confirming integration)**

No storyforge code changes in this task — the bookshelf script is in a separate repo.

---

### Task 5: Update Publish Skill & Docs, Bump Version

**Files:**
- Modify: `skills/publish/SKILL.md`
- Modify: `CLAUDE.md`
- Modify: `.claude-plugin/plugin.json`

- [ ] **Step 1: Update publish skill**

Replace the assembly-based flow in `skills/publish/SKILL.md` with the manifest-based flow:

In Step 3, change from "Assemble Web Book" to "Generate Publish Manifest":

```markdown
## Step 3: Generate Publish Manifest

Generate the publish manifest (converts scene markdown to HTML, groups by chapter map):

```bash
cd <project_dir> && PYTHONPATH=<plugin_path>/scripts/lib/python python3 -c "
from storyforge.assembly import generate_publish_manifest
path = generate_publish_manifest('<project_dir>')
print(f'Manifest generated: {path}')
"
```

If this fails with a "stale chapter map" error, help the author update the chapter map first (invoke `produce` skill for chapter mapping).
```

In Step 5, update the publish command:

```markdown
## Step 5: Publish Content

Run the bookshelf publish script with the manifest:

```bash
cd <bookshelf_path> && npx tsx scripts/publish-book.ts <book_repo_path> --manifest <project_dir>/working/publish-manifest.json
```
```

- [ ] **Step 2: Update CLAUDE.md**

Add `check_chapter_map_freshness()` to the common.py shared module docs:

```
- `check_chapter_map_freshness(project_dir)` — returns (is_fresh, missing_from_map, extra_in_map)
```

Add `generate_publish_manifest()` to the assembly.py module docs.

- [ ] **Step 3: Bump version to 1.7.0**

In `.claude-plugin/plugin.json`, change `"version": "1.6.0"` to `"version": "1.7.0"`.

- [ ] **Step 4: Run full test suite**

Run: `python3 -m pytest tests/ -q`
Expected: All pass

- [ ] **Step 5: Commit**

```bash
git add skills/publish/SKILL.md CLAUDE.md .claude-plugin/plugin.json
git commit -m "Bump version to 1.7.0"
git push
```
