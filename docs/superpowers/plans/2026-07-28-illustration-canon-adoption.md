# Illustration Canon Adoption Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Move prose interior illustrations off `reference/illustration-direction.md` and onto `reference/canon/`, so both mediums share one reference tier.

**Architecture:** `reference/canon/` already exists for graphic novels: typed markdown files with YAML frontmatter whose `## Embeddable block` section holds a verbatim-reuse string. That is exactly what an illustration continuity anchor is. This phase makes canon validation medium-neutral, exposes canon anchors through a public accessor, points `--direction` and `--prompts` at canon files, and adds a one-time safety net for the hand-edit of the single existing project.

**Tech Stack:** Python 3, pytest, pipe-delimited CSV, no external dependencies.

## Global Constraints

- **Finding kinds are bare, not prefixed.** `cmd_cleanup.py:1238` does `'type': f'illus_{kind}'`. A kind added as `illus_foo` renders as `illus_illus_foo`.
- **Anchor strings are byte-identical or they are broken.** Likeness continuity depends on the string, not its meaning. Never normalize, reflow, or re-case an anchor on any read or write path.
- **No migration code.** Exactly one project has an `illustration-direction.md` and it is hand-edited. Build the safety net, not the migration.
- **`severity_of` defaults unknown kinds to `'error'`.** Every new kind must be added to `WARNING_FINDINGS` or deliberately left blocking, and `BLOCKING_FINDINGS` must stay a true partition — there is a partition test that enforces this.
- **Pipe-delimited CSV, `;` for arrays.** No quoting.
- **Commit and push after every task.** Never commit to `main`.
- Run the suite with `python3 -m pytest tests/ -q`.

## File Structure

**Modify:**
- `scripts/lib/python/storyforge/canon.py` — medium-aware frontmatter validation; public anchor accessors
- `scripts/lib/python/storyforge/cmd_cleanup.py` — run canon validation for novel projects; new remediation entry
- `scripts/lib/python/storyforge/illustrations.py` — new finding kind; retire direction-document readers
- `scripts/lib/python/storyforge/cmd_illustrate.py` — read anchors from canon; write canon stubs; diagnose safety net
- `scripts/lib/python/storyforge/prompts_illustrate.py` — canon-file templates replace the single-document template
- `skills/illustrate/SKILL.md` — mode table and anchor guidance
- `CLAUDE.md` — reference-tier documentation
- `tests/test_canon_files.py` — two tests assert the removed finding
- `tests/fixtures/test-project/reference/canon/` — new fixture canon files

**Create:**
- `tests/test_illustration_canon.py` — canon-tier behavior for prose projects

---

### Task 1: Run canon validation for novel projects

Canon validation currently skips entirely when medium is not `graphic-novel`, emitting a warning instead. Under the new model a novel project is *expected* to have canon, so the gate and its finding both go.

**Files:**
- Modify: `scripts/lib/python/storyforge/cmd_cleanup.py:1283-1300`
- Modify: `scripts/lib/python/storyforge/canon.py:61` (remove `'canon_present_in_novel_project'` from `CanonFindingKind`)
- Modify: `tests/test_canon_files.py:1014,1028`
- Test: `tests/test_illustration_canon.py`

**Interfaces:**
- Consumes: `canon.validate_canon_file(path, project_root) -> list[CanonFinding]`, `common.get_medium(project_dir) -> str`
- Produces: `report_canon_files(project_dir)` returns real findings for `medium: novel` projects instead of a single skip warning.

- [ ] **Step 1: Write the failing test**

```python
# tests/test_illustration_canon.py
import os
import pytest
from storyforge.cmd_cleanup import report_canon_files

CANON_BODY = """---
canon_id: nora
canon_type: character
canon_updated: 2026-07-28
appears_in: village-reveal
embeds_as: Character
first_appearance: village-reveal
---

## Embeddable block

Nora, 9 years old, 132 cm, dark brown hair in a short bob, grey-green eyes.

## Clauses

- Always barefoot indoors.

## Related canon

- leo

## Iteration history

- 2026-07-28 initial
"""


def _write_canon(project_dir, relpath, body=CANON_BODY):
    path = os.path.join(project_dir, 'reference', 'canon', relpath)
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, 'w', encoding='utf-8') as f:
        f.write(body)
    return path


def _set_medium(project_dir, medium):
    yaml_path = os.path.join(project_dir, 'storyforge.yaml')
    with open(yaml_path, encoding='utf-8') as f:
        text = f.read()
    if 'medium:' in text:
        lines = [
            f'  medium: {medium}' if line.strip().startswith('medium:') else line
            for line in text.splitlines()
        ]
        text = '\n'.join(lines) + '\n'
    else:
        text = text.replace('project:', f'project:\n  medium: {medium}', 1)
    with open(yaml_path, 'w', encoding='utf-8') as f:
        f.write(text)


def test_novel_project_canon_is_validated_not_skipped(project_dir):
    """A novel project with valid canon produces no findings at all."""
    _set_medium(project_dir, 'novel')
    # characters.csv must carry a matching row or canon_missing_registry_entry fires
    reg = os.path.join(project_dir, 'reference', 'characters.csv')
    os.makedirs(os.path.dirname(reg), exist_ok=True)
    with open(reg, 'w', encoding='utf-8') as f:
        f.write('id|name\nnora|Nora\n')
    _write_canon(project_dir, os.path.join('characters', 'nora.md'))

    findings = report_canon_files(project_dir)

    assert findings == [], f'expected no findings, got {findings}'


def test_novel_project_canon_errors_are_reported(project_dir):
    """A novel project with a broken canon file gets the real finding,
    not a blanket skip warning."""
    _set_medium(project_dir, 'novel')
    _write_canon(project_dir, os.path.join('characters', 'nora.md'),
                 body='no frontmatter here\n')

    kinds = {f['type'] for f in report_canon_files(project_dir)}

    assert 'canon_present_in_novel_project' not in kinds
    assert 'canon_missing_frontmatter' in kinds
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `python3 -m pytest tests/test_illustration_canon.py -v`

Expected: both FAIL. The first gets `canon_present_in_novel_project` instead of `[]`; the second asserts that kind is absent and finds it present.

- [ ] **Step 3: Remove the medium gate**

In `cmd_cleanup.py`, delete the `if get_medium(project_dir) != 'graphic-novel':` branch that emits `canon_present_in_novel_project` and returns early. Validation proceeds for every medium. Keep the `canon_dir_present` check that returns `[]` when there is no canon directory at all — a project without canon is not a finding.

```python
def report_canon_files(project_dir: str) -> list[CanonFinding]:
    """Validate reference/canon/ for any medium.

    Both mediums use canon as their reference tier: graphic novels for page
    prompts, prose books for illustration continuity anchors. A project with
    no canon directory yet is valid in-flight state, not a finding.
    """
    canon_dir_present = os.path.isdir(os.path.join(project_dir, CANON_DIR))
    if not canon_dir_present:
        return []
    # ... existing validation walk, unchanged
```

- [ ] **Step 4: Remove the finding kind and its remediation**

In `canon.py`, delete `'canon_present_in_novel_project'` from the `CanonFindingKind` Literal, along with the trailing comment that describes it as emitted by `report_canon_files`. Delete its entry from the remediation mapping in `cmd_cleanup.py` if one exists.

- [ ] **Step 5: Update the two tests that assert the removed finding**

`tests/test_canon_files.py:1014` and `:1028` assert `findings[0]['type'] == 'canon_present_in_novel_project'`. Replace both with the new expectation: a novel project's canon is validated normally. Read each test's setup first — if it builds an intentionally-broken canon file, assert the specific structural finding instead; if it builds a valid one, assert `findings == []`.

- [ ] **Step 6: Run the full suite**

Run: `python3 -m pytest tests/ -q`

Expected: PASS. If `test_canon_files.py` has other tests that relied on the skip (for example asserting a novel project produces exactly one finding), fix those too — the skip no longer exists.

- [ ] **Step 7: Commit**

```bash
git add scripts/lib/python/storyforge/canon.py \
        scripts/lib/python/storyforge/cmd_cleanup.py \
        tests/test_canon_files.py tests/test_illustration_canon.py
git commit -m "Run canon validation for novel projects, not just graphic novels

Both mediums use reference/canon/ as the reference tier now. The medium
gate skipped validation entirely for prose projects, which would leave
illustration canon files unvalidated and silent. Removes
canon_present_in_novel_project along with the gate."
git push
```

---

### Task 2: Make `embeds_as` optional for prose projects

`embeds_as` serves the inline-embed convention. Prose illustrations never inline canon into a prompt, so requiring it would make the key write-only.

**Files:**
- Modify: `scripts/lib/python/storyforge/canon.py:100-107,450-457`
- Test: `tests/test_illustration_canon.py`

**Interfaces:**
- Consumes: `common.get_medium(project_dir) -> str`
- Produces: `canon.ALWAYS_REQUIRED_FRONTMATTER_KEYS: tuple[str, ...]` and `canon.GN_ONLY_FRONTMATTER_KEYS: tuple[str, ...]`. `REQUIRED_FRONTMATTER_KEYS` remains as their concatenation so existing importers keep working.

- [ ] **Step 1: Write the failing test**

```python
# tests/test_illustration_canon.py — append

CANON_NO_EMBEDS_AS = """---
canon_id: nora
canon_type: character
canon_updated: 2026-07-28
appears_in: village-reveal
first_appearance: village-reveal
---

## Embeddable block

Nora, 9 years old, 132 cm, dark brown hair in a short bob, grey-green eyes.

## Clauses

- Always barefoot indoors.

## Related canon

- leo

## Iteration history

- 2026-07-28 initial
"""


def test_embeds_as_not_required_for_novel(project_dir):
    from storyforge.canon import validate_canon_file
    _set_medium(project_dir, 'novel')
    path = _write_canon(project_dir, os.path.join('characters', 'nora.md'),
                        body=CANON_NO_EMBEDS_AS)

    findings = validate_canon_file(path, project_dir)
    missing = [f for f in findings if f['type'] == 'canon_missing_key']

    assert missing == [], f'embeds_as should be optional for novel: {missing}'


def test_embeds_as_still_required_for_graphic_novel(project_dir):
    from storyforge.canon import validate_canon_file
    _set_medium(project_dir, 'graphic-novel')
    path = _write_canon(project_dir, os.path.join('characters', 'nora.md'),
                        body=CANON_NO_EMBEDS_AS)

    findings = validate_canon_file(path, project_dir)
    details = [f['detail'] for f in findings if f['type'] == 'canon_missing_key']

    assert any('embeds_as' in d for d in details), \
        f'embeds_as must stay required for GN: {findings}'
```

`CANON_NO_EMBEDS_AS` above is `CANON_BODY` minus the `embeds_as` line. Task 1's `CANON_BODY` deliberately **carries** `embeds_as: Character`, so Task 1 tests only what it is about — that validation runs at all for novel projects — and this task's fixture is the one that exercises the key requirement. Keep both constants; do not collapse them.

- [ ] **Step 2: Run the tests to verify they fail**

Run: `python3 -m pytest tests/test_illustration_canon.py -k embeds_as -v`

Expected: `test_embeds_as_not_required_for_novel` FAILS with a `canon_missing_key` finding for `embeds_as`. The GN test PASSES already.

- [ ] **Step 3: Split the required-key tuples**

```python
# canon.py — replace REQUIRED_FRONTMATTER_KEYS
#: Keys every canon file needs regardless of medium.
ALWAYS_REQUIRED_FRONTMATTER_KEYS = (
    'canon_id',
    'canon_type',
    'canon_updated',
    'appears_in',
    'first_appearance',
)

#: `embeds_as` serves the inline-embed convention, which only the
#: graphic-novel page pipeline uses. Requiring it of a prose project would
#: make it write-only. Its long-term fate is decided by the
#: staleness-unification issue.
GN_ONLY_FRONTMATTER_KEYS = ('embeds_as',)

#: Retained for importers that predate the split.
REQUIRED_FRONTMATTER_KEYS = (
    ALWAYS_REQUIRED_FRONTMATTER_KEYS + GN_ONLY_FRONTMATTER_KEYS
)
```

- [ ] **Step 4: Make the validation loop medium-aware**

In `validate_canon_file`, replace the `for key in REQUIRED_FRONTMATTER_KEYS:` loop header:

```python
    from storyforge.common import get_medium
    required = ALWAYS_REQUIRED_FRONTMATTER_KEYS
    if get_medium(project_root) == 'graphic-novel':
        required = required + GN_ONLY_FRONTMATTER_KEYS

    for key in required:
        if not fm.get(key):
            findings.append(_finding(
                rel,
                f'missing required frontmatter key: {key}',
                f'Add `{key}: <value>` to the frontmatter',
                'canon_missing_key',
            ))
```

- [ ] **Step 5: Run the tests**

Run: `python3 -m pytest tests/test_illustration_canon.py -v && python3 -m pytest tests/ -q`

Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add scripts/lib/python/storyforge/canon.py tests/test_illustration_canon.py
git commit -m "Make embeds_as required only for graphic-novel projects

embeds_as serves the inline-embed convention, which the prose illustration
flow never uses — requiring it would make the key write-only. Splits the
required-key tuple and keeps REQUIRED_FRONTMATTER_KEYS as the concatenation
so existing importers are unaffected."
git push
```

---

### Task 3: Public accessors for canon anchors

The packet, the prompts, and the diagnose safety net all need an entity's verbatim anchor text. Today the only reader is private and page-oriented.

**Files:**
- Modify: `scripts/lib/python/storyforge/canon.py:278` (`_embeddable_block_text`), and the private `_resolve_canon_path`
- Test: `tests/test_illustration_canon.py`

**Interfaces:**
- Consumes: `canon.parse_canon_file`, `canon.SUBDIR_TYPE`, `canon.CANON_DIR`
- Produces:
  - `canon.embeddable_block_text(canon_path: str) -> str | None` — public rename of `_embeddable_block_text`, verbatim, no normalization.
  - `canon.resolve_canon_path(project_dir: str, canon_id: str) -> str | None` — resolves a slug to a file in the canon root or any known subdirectory.
  - `canon.anchor_texts(project_dir: str) -> dict[str, str]` — every entity canon file's anchor, keyed by `canon_id`. Entity types only (`character`, `location`, `motif`); foundation/vocabulary/rules are not per-entity anchors. Files whose `## Embeddable block` is missing or placeholder are omitted.

- [ ] **Step 1: Write the failing test**

```python
# tests/test_illustration_canon.py — append

def test_anchor_texts_returns_entity_anchors_verbatim(project_dir):
    from storyforge.canon import anchor_texts
    _set_medium(project_dir, 'novel')
    _write_canon(project_dir, os.path.join('characters', 'nora.md'))

    anchors = anchor_texts(project_dir)

    assert set(anchors) == {'nora'}
    assert anchors['nora'] == (
        'Nora, 9 years old, 132 cm, dark brown hair in a short bob, '
        'grey-green eyes.'
    )


def test_anchor_texts_omits_placeholder_blocks(project_dir):
    from storyforge.canon import anchor_texts
    _set_medium(project_dir, 'novel')
    _write_canon(project_dir, os.path.join('characters', 'ghost.md'),
                 body=CANON_BODY.replace(
                     'Nora, 9 years old, 132 cm, dark brown hair in a short '
                     'bob, grey-green eyes.',
                     'TODO: describe this character',
                 ).replace('canon_id: nora', 'canon_id: ghost'))

    assert 'ghost' not in anchor_texts(project_dir)


def test_anchor_texts_excludes_non_entity_types(project_dir):
    from storyforge.canon import anchor_texts
    _set_medium(project_dir, 'novel')
    _write_canon(project_dir, 'visual-foundation.md',
                 body=CANON_BODY
                 .replace('canon_id: nora', 'canon_id: visual-foundation')
                 .replace('canon_type: character', 'canon_type: foundation'))

    assert anchor_texts(project_dir) == {}


def test_resolve_canon_path_finds_root_and_subdir(project_dir):
    from storyforge.canon import resolve_canon_path
    _set_medium(project_dir, 'novel')
    _write_canon(project_dir, os.path.join('characters', 'nora.md'))
    _write_canon(project_dir, 'visual-foundation.md',
                 body=CANON_BODY
                 .replace('canon_id: nora', 'canon_id: visual-foundation')
                 .replace('canon_type: character', 'canon_type: foundation'))

    assert resolve_canon_path(project_dir, 'nora').endswith(
        os.path.join('characters', 'nora.md'))
    assert resolve_canon_path(project_dir, 'visual-foundation').endswith(
        'visual-foundation.md')
    assert resolve_canon_path(project_dir, 'nobody') is None
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `python3 -m pytest tests/test_illustration_canon.py -k "anchor_texts or resolve_canon_path" -v`

Expected: FAIL with `ImportError: cannot import name 'anchor_texts'`.

- [ ] **Step 3: Rename the private reader and update its one call site**

```python
# canon.py — rename _embeddable_block_text
def embeddable_block_text(canon_path: str) -> str | None:
    """Return the verbatim text of a canon file's `## Embeddable block`.

    Verbatim is the whole point: an anchor works only because every prompt
    that uses it sends a byte-identical string. Never normalize here —
    normalization belongs at comparison time, in the caller.

    Returns None when the file or the section is absent.
    """
    # ... existing body, unchanged
```

Do **not** leave a `_embeddable_block_text = embeddable_block_text` alias. There is
exactly one call site, inside `check_canon_drift`; update it. An alias kept for a
single caller is dead code a reviewer will flag, and rightly.

```bash
grep -rn "_embeddable_block_text" scripts/ tests/ | grep -v worktrees
```

- [ ] **Step 4: Add the public path resolver**

`_resolve_canon_path` takes a mutable index for caching. Wrap it:

```python
def resolve_canon_path(project_dir: str, canon_id: str) -> str | None:
    """Resolve a canon_id to its file path, root or subdirectory.

    Thin public wrapper over the cached internal resolver, for callers that
    look up one id and do not hold an index.
    """
    return _resolve_canon_path(project_dir, canon_id, {})
```

- [ ] **Step 5: Add `anchor_texts`**

```python
#: Canon types that describe one entity whose look must stay fixed. The
#: foundation/vocabulary/rules types describe the book, not a thing in it,
#: so they are house style rather than per-entity anchors.
ENTITY_CANON_TYPES: frozenset[CanonType] = frozenset(
    {'character', 'location', 'motif'})


def anchor_texts(project_dir: str) -> dict[str, str]:
    """Map canon_id -> verbatim anchor text for every entity canon file.

    Skips files whose Embeddable block is missing or still placeholder text:
    a scaffold sent to an image model as though it were direction is worse
    than sending nothing, because it reads as a deliberate instruction.
    """
    canon_dir = os.path.join(project_dir, CANON_DIR)
    if not os.path.isdir(canon_dir):
        return {}

    anchors: dict[str, str] = {}
    for root, _dirs, files in os.walk(canon_dir):
        for filename in sorted(files):
            if not filename.endswith('.md'):
                continue
            path = os.path.join(root, filename)
            parsed = parse_canon_file(path)
            fm = parsed['frontmatter']
            if not isinstance(fm, dict):
                continue
            if fm.get('canon_type') not in ENTITY_CANON_TYPES:
                continue
            canon_id = (fm.get('canon_id') or '').strip()
            if not canon_id:
                continue
            body = embeddable_block_text(path)
            if body is None or _section_body_is_placeholder(body):
                continue
            anchors[canon_id] = body.strip()
    return anchors
```

Note `_TRUNCATED` is a sentinel, not a dict, which is why the `isinstance(fm, dict)` guard is there rather than a truthiness check.

- [ ] **Step 6: Run the tests**

Run: `python3 -m pytest tests/test_illustration_canon.py -v && python3 -m pytest tests/ -q`

Expected: PASS.

- [ ] **Step 7: Commit**

```bash
git add scripts/lib/python/storyforge/canon.py tests/test_illustration_canon.py
git commit -m "Add public canon anchor accessors for the illustration flow

embeddable_block_text, resolve_canon_path, and anchor_texts give the
illustration flow read access to canon anchors. anchor_texts skips
placeholder blocks — a scaffold sent to an image model reads as a
deliberate instruction, which is worse than sending nothing."
git push
```

---

### Task 4: Point `--prompts` at canon anchors

`cmd_illustrate` reads anchors from the direction document today. Switch the source, and match `canon_refs` against `canon_id` slugs.

**Files:**
- Modify: `scripts/lib/python/storyforge/cmd_illustrate.py:646-661` (`_relevant_anchors`), and the `--prompts` path around `:524-570`
- Modify: `scripts/lib/python/storyforge/prompts_illustrate.py:106` (`anchors_for_prompt`)
- Test: `tests/test_illustration_canon.py`

**Interfaces:**
- Consumes: `canon.anchor_texts(project_dir) -> dict[str, str]`
- Produces: `_relevant_anchors(anchors, row)` unchanged in signature; now matches `canon_refs` entries against canon-id slugs rather than `### Name` headings.

- [ ] **Step 1: Write the failing test**

```python
# tests/test_illustration_canon.py — append

def test_prompts_anchors_come_from_canon(project_dir):
    from storyforge.prompts_illustrate import anchors_for_prompt
    _set_medium(project_dir, 'novel')
    _write_canon(project_dir, os.path.join('characters', 'nora.md'))

    anchors = anchors_for_prompt(project_dir)

    assert anchors['nora'].startswith('Nora, 9 years old, 132 cm')


def test_relevant_anchors_matches_canon_ids(project_dir):
    from storyforge.cmd_illustrate import _relevant_anchors
    anchors = {'nora': 'Nora anchor', 'leo': 'Leo anchor',
               'great-lamp': 'Lamp anchor'}

    row = {'canon_refs': 'nora;great-lamp'}
    assert set(_relevant_anchors(anchors, row)) == {'nora', 'great-lamp'}


def test_relevant_anchors_falls_back_when_nothing_matches(project_dir):
    """An unfiltered anchor set is a smaller failure than a missing one, so a
    canon_refs value that matches no canon_id sends everything."""
    from storyforge.cmd_illustrate import _relevant_anchors
    anchors = {'nora': 'Nora anchor', 'leo': 'Leo anchor'}

    row = {'canon_refs': 'somebody-else'}
    assert set(_relevant_anchors(anchors, row)) == {'nora', 'leo'}
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `python3 -m pytest tests/test_illustration_canon.py -k "prompts_anchors or relevant_anchors" -v`

Expected: `test_prompts_anchors_come_from_canon` FAILS — `anchors_for_prompt` reads the direction document and returns `{}`. The two `_relevant_anchors` tests PASS already, since the matching logic is already case-insensitive slug comparison; keep them as regression cover.

- [ ] **Step 3: Repoint `anchors_for_prompt`**

```python
# prompts_illustrate.py
def anchors_for_prompt(project_dir: str) -> dict[str, str]:
    """Anchors available to an illustration prompt, keyed by canon_id.

    Reads reference/canon/ entity files. The strings are verbatim and must
    stay that way: likeness continuity across separately generated images
    depends on every prompt sending byte-identical text.
    """
    from storyforge import canon
    return canon.anchor_texts(project_dir)
```

- [ ] **Step 4: Run the tests**

Run: `python3 -m pytest tests/test_illustration_canon.py -v`

Expected: PASS.

- [ ] **Step 5: Redirect proposed-anchor persistence to canon files**

`append_anchor_stubs` currently appends a model-proposed anchor to the direction document. It must write a canon file stub instead. Do **not** create the registry row — `canon_missing_registry_entry` already nags for that, and inventing registry rows silently is how a typo becomes canonical.

The anchor block the model emits gains a type field, so a stub lands in the right
subdirectory. Update the request text in `build_art_direction_request` to ask for
`Name | type — description`, where type is one of `character`, `location`, `motif`.

```python
# prompts_illustrate.py — replace append_anchor_stubs

#: Canon subdirectory per proposed anchor type. A type outside this map (or
#: absent) falls back to 'character' with a WARNING rather than guessing
#: silently — a stub filed under the wrong registry tells the author to add a
#: character row for a location, which is a confusing way to learn about a
#: parse failure.
_ANCHOR_TYPE_SUBDIR: dict[str, str] = {
    'character': 'characters',
    'location': 'locations',
    'motif': 'motifs',
}
_ANCHOR_TYPE_FALLBACK = 'character'


def append_anchor_stubs(project_dir: str,
                        anchors: dict[str, tuple[str, str]]) -> list[str]:
    """Persist model-proposed anchors as canon file stubs.

    `anchors` maps display name -> (canon_type, anchor_text).

    Returns the canon_ids written. An anchor that already resolves is left
    alone: append_anchor_stubs never revises an existing anchor, because a
    rendered illustration may already depend on its exact text.

    The registry row is deliberately NOT created. canon_missing_registry_entry
    reports the gap, and an author confirming the name is cheaper than
    silently making a model's guess canonical.
    """
    import os
    from storyforge import canon
    from storyforge.common import log

    written: list[str] = []
    for name, (raw_type, text) in sorted(anchors.items()):
        canon_id = _slugify(name)
        if not canon_id:
            log(f'WARNING: proposed anchor {name!r} has no usable slug; skipped')
            continue
        if canon.resolve_canon_path(project_dir, canon_id) is not None:
            continue
        canon_type = (raw_type or '').strip().lower()
        if canon_type not in _ANCHOR_TYPE_SUBDIR:
            log(f'WARNING: proposed anchor {name!r} has type {raw_type!r}; '
                f'filing as {_ANCHOR_TYPE_FALLBACK} — move the file and its '
                f'registry row if that is wrong')
            canon_type = _ANCHOR_TYPE_FALLBACK
        subdir = _ANCHOR_TYPE_SUBDIR[canon_type]
        path = os.path.join(project_dir, canon.CANON_DIR, subdir,
                            f'{canon_id}.md')
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, 'w', encoding='utf-8') as f:
            f.write(_canon_stub(canon_id=canon_id, canon_type=canon_type,
                                anchor=text))
        written.append(canon_id)
    return written


def _slugify(name: str) -> str:
    """Lowercase kebab-case slug, matching canon's id validation."""
    import re
    return re.sub(r'[^a-z0-9]+', '-', name.strip().lower()).strip('-')


def _canon_stub(*, canon_id: str, canon_type: str, anchor: str) -> str:
    """A minimal valid canon file carrying one anchor.

    `appears_in` and `first_appearance` are left empty rather than guessed:
    a wrong first_appearance would misorder the render sequence, and
    canon_missing_key reports the omission.
    """
    return (
        '---\n'
        f'canon_id: {canon_id}\n'
        f'canon_type: {canon_type}\n'
        'canon_updated:\n'
        'appears_in:\n'
        'first_appearance:\n'
        '---\n'
        '\n'
        '## Embeddable block\n'
        '\n'
        f'{anchor}\n'
        '\n'
        '## Clauses\n'
        '\n'
        '## Related canon\n'
        '\n'
        '## Iteration history\n'
    )
```

`split_anchor_block` must parse the new `Name | type — description` shape and return
`dict[str, tuple[str, str]]`. Keep its existing tolerance for a decorated `ANCHORS`
marker and for em-dash / en-dash / colon separators. An entry with no `|` yields
`('', text)`, which routes to the fallback with a WARNING — a model that forgets the
type still gets its anchor persisted.

`_ANCHOR_LINE_RE`'s current guard against splitting hyphenated names must survive:
`Jean-Luc | character — description` has to yield name `Jean-Luc`, not `Jean`.

- [ ] **Step 6: Write the test for stub persistence**

```python
# tests/test_illustration_canon.py — append

def test_append_anchor_stubs_routes_by_type(project_dir):
    from storyforge.prompts_illustrate import append_anchor_stubs
    from storyforge.canon import anchor_texts, resolve_canon_path

    written = append_anchor_stubs(project_dir, {
        'Nora': ('character', 'A nine-year-old in a green cardigan.'),
        'Old Oak': ('location', 'A hollow oak whose roots form streets.'),
        'Great Lamp': ('motif', 'A bronze bowl with several wicks.'),
    })

    assert sorted(written) == ['great-lamp', 'nora', 'old-oak']
    assert resolve_canon_path(project_dir, 'nora').endswith(
        os.path.join('characters', 'nora.md'))
    assert resolve_canon_path(project_dir, 'old-oak').endswith(
        os.path.join('locations', 'old-oak.md'))
    assert resolve_canon_path(project_dir, 'great-lamp').endswith(
        os.path.join('motifs', 'great-lamp.md'))
    assert anchor_texts(project_dir)['great-lamp'] == (
        'A bronze bowl with several wicks.')


def test_append_anchor_stubs_unknown_type_falls_back_to_character(project_dir):
    from storyforge.prompts_illustrate import append_anchor_stubs
    from storyforge.canon import resolve_canon_path

    written = append_anchor_stubs(project_dir,
                                  {'Murkwolf': ('creature', 'Cold blue mist.')})

    assert written == ['murkwolf']
    assert resolve_canon_path(project_dir, 'murkwolf').endswith(
        os.path.join('characters', 'murkwolf.md'))


def test_append_anchor_stubs_never_revises_existing(project_dir):
    from storyforge.prompts_illustrate import append_anchor_stubs
    from storyforge.canon import anchor_texts
    _write_canon(project_dir, os.path.join('characters', 'nora.md'))
    original = anchor_texts(project_dir)['nora']

    written = append_anchor_stubs(
        project_dir, {'Nora': ('character', 'Something different.')})

    assert written == []
    assert anchor_texts(project_dir)['nora'] == original


def test_split_anchor_block_parses_type_and_keeps_hyphenated_names():
    from storyforge.prompts_illustrate import split_anchor_block

    body, anchors = split_anchor_block(
        'Prompt text here.\n\n'
        'ANCHORS\n'
        '- Jean-Luc | character — a tall man in a grey coat\n'
        '- Old Oak | location — a hollow oak\n'
        '- Untyped Thing — no type given\n'
    )

    assert body.strip() == 'Prompt text here.'
    assert anchors['Jean-Luc'] == ('character', 'a tall man in a grey coat')
    assert anchors['Old Oak'] == ('location', 'a hollow oak')
    assert anchors['Untyped Thing'] == ('', 'no type given')
```

- [ ] **Step 7: Run the suite**

Run: `python3 -m pytest tests/ -q`

Expected: PASS. Existing tests that asserted anchors were appended to the direction document will fail — update them to assert canon stubs instead, keeping their intent.

- [ ] **Step 8: Commit**

```bash
git add scripts/lib/python/storyforge/prompts_illustrate.py \
        scripts/lib/python/storyforge/cmd_illustrate.py \
        tests/test_illustration_canon.py tests/test_illustrate_cmd.py
git commit -m "Read illustration anchors from canon files, write stubs there too

anchors_for_prompt now reads reference/canon/ entity files, and a
model-proposed anchor persists as a canon stub rather than an appended
section. The registry row is deliberately not auto-created:
canon_missing_registry_entry reports the gap, and an author confirming the
name beats making a model's guess canonical."
git push
```

---

### Task 5: Add the hand-edit safety net finding

The single existing project is hand-edited. The one mistake that cannot be eyeballed and cannot be recovered from is an anchor whose string changed.

**Files:**
- Modify: `scripts/lib/python/storyforge/illustrations.py:1508,1538` (add `direction_anchor_mismatch` to the Literal and `WARNING_FINDINGS`)
- Modify: `scripts/lib/python/storyforge/illustrations.py:1556` (`validate_plan`)
- Modify: `scripts/lib/python/storyforge/cmd_cleanup.py:1183` (`_ILLUSTRATION_ACTIONS`)
- Test: `tests/test_illustration_canon.py`

**Interfaces:**
- Consumes: `canon.anchor_texts`, `illustrations.read_direction`, `illustrations.find_section`, `illustrations.ANCHORS_SECTION`, `common.normalize_for_comparison` (see note in Step 3)
- Produces: finding kind `direction_anchor_mismatch`, rendered by cleanup as `illus_direction_anchor_mismatch`, severity `warning`.

- [ ] **Step 1: Write the failing test**

```python
# tests/test_illustration_canon.py — append

DIRECTION_DOC = """# Illustration art direction

## Continuity anchors

### nora

Nora, 9 years old, 132 cm, dark brown hair in a short bob, grey-green eyes.
"""


def _write_direction(project_dir, body=DIRECTION_DOC):
    path = os.path.join(project_dir, 'reference', 'illustration-direction.md')
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, 'w', encoding='utf-8') as f:
        f.write(body)


def test_matching_anchor_produces_no_mismatch(project_dir):
    from storyforge.illustrations import validate_plan
    _set_medium(project_dir, 'novel')
    _write_canon(project_dir, os.path.join('characters', 'nora.md'))
    _write_direction(project_dir)

    kinds = {f['kind'] for f in validate_plan(project_dir)}

    assert 'direction_anchor_mismatch' not in kinds


def test_changed_anchor_is_reported(project_dir):
    from storyforge.illustrations import validate_plan
    _set_medium(project_dir, 'novel')
    _write_canon(project_dir, os.path.join('characters', 'nora.md'))
    _write_direction(project_dir, DIRECTION_DOC.replace('132 cm', '140 cm'))

    findings = [f for f in validate_plan(project_dir)
                if f['kind'] == 'direction_anchor_mismatch']

    assert len(findings) == 1
    assert findings[0]['id'] == 'nora'
    assert '140 cm' in findings[0]['detail'] or '132 cm' in findings[0]['detail']


def test_no_direction_document_means_silence(project_dir):
    """Once the old file is deleted the check goes quiet forever."""
    from storyforge.illustrations import validate_plan
    _set_medium(project_dir, 'novel')
    _write_canon(project_dir, os.path.join('characters', 'nora.md'))

    kinds = {f['kind'] for f in validate_plan(project_dir)}

    assert 'direction_anchor_mismatch' not in kinds


def test_mismatch_is_a_warning_not_blocking(project_dir):
    from storyforge.illustrations import severity_of
    assert severity_of('direction_anchor_mismatch') == 'warning'
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `python3 -m pytest tests/test_illustration_canon.py -k "anchor or mismatch" -v`

Expected: `test_changed_anchor_is_reported` FAILS (no such finding); `test_mismatch_is_a_warning_not_blocking` FAILS on the `severity_of` lookup returning `'error'` for an unknown kind.

- [ ] **Step 3: Add the kind to both the Literal and `WARNING_FINDINGS`**

Add `'direction_anchor_mismatch'` to `IllustrationFindingKind` and to `WARNING_FINDINGS`. Do **not** add it to `BLOCKING_FINDINGS` — the partition test will fail if it appears in both or neither.

The comparison must ignore cosmetic whitespace but nothing else. `common.normalize_for_comparison` is the shared normalizer; if it has not been extracted from `canon._normalize_for_drift` yet, do that extraction as part of this step — move the function to `common.py` under the new name, leave `canon._normalize_for_drift = normalize_for_comparison` as an alias, and add a test asserting the two produce identical output for a multi-line block with trailing spaces and a doubled blank line.

- [ ] **Step 4: Implement the check inside `validate_plan`**

```python
def _direction_anchor_mismatches(
        project_dir: str) -> list[IllustrationFinding]:
    """Compare canon anchors against a still-present direction document.

    A one-time safety net for the hand-edit off illustration-direction.md.
    The unrecoverable mistake is an anchor whose text changed: every
    illustration already rendered from the old string is invalidated, and
    nothing else in the pipeline would notice. Goes silent once the old
    document is deleted, which is the intended end state.
    """
    from storyforge import canon
    from storyforge.common import normalize_for_comparison

    if not os.path.isfile(direction_path(project_dir)):
        return []
    sections = read_direction(project_dir)
    anchors_body = find_section(sections, ANCHORS_SECTION)
    if not anchors_body:
        return []

    old: dict[str, str] = {}
    current_name = None
    buffer: list[str] = []
    for line in anchors_body.splitlines():
        heading = re.match(r'^###\s+(.+?)\s*$', line)
        if heading:
            if current_name is not None:
                old[current_name] = '\n'.join(buffer).strip()
            current_name = heading.group(1).strip()
            buffer = []
        elif current_name is not None:
            buffer.append(line)
    if current_name is not None:
        old[current_name] = '\n'.join(buffer).strip()

    findings: list[IllustrationFinding] = []
    new = canon.anchor_texts(project_dir)
    for name, old_text in sorted(old.items()):
        new_text = new.get(name)
        if new_text is None:
            continue
        if normalize_for_comparison(old_text) != normalize_for_comparison(new_text):
            findings.append({
                'kind': 'direction_anchor_mismatch',
                'id': name,
                'detail': (
                    f'canon anchor for `{name}` differs from the section in '
                    f'reference/illustration-direction.md — every '
                    f'illustration already rendered from the old text is '
                    f'invalidated if this change was unintentional'
                ),
            })
    return findings
```

Call it from `validate_plan` and extend the returned list. An anchor present in the direction document but absent from canon is skipped rather than reported: mid-hand-edit is normal in-flight state, and the author is the one deciding which anchors survive.

- [ ] **Step 5: Add the remediation text**

```python
# cmd_cleanup.py — _ILLUSTRATION_ACTIONS
    'direction_anchor_mismatch':
        'Confirm which text is correct. If the canon file is right, delete '
        'reference/illustration-direction.md. If the old text is right, '
        'restore it into the canon file and re-render nothing — the existing '
        'art already matches it',
```

- [ ] **Step 6: Run the suite**

Run: `python3 -m pytest tests/ -q`

Expected: PASS, including the `BLOCKING_FINDINGS` / `WARNING_FINDINGS` partition test.

- [ ] **Step 7: Commit**

```bash
git add scripts/lib/python/storyforge/illustrations.py \
        scripts/lib/python/storyforge/cmd_cleanup.py \
        scripts/lib/python/storyforge/common.py \
        scripts/lib/python/storyforge/canon.py \
        tests/test_illustration_canon.py
git commit -m "Add direction_anchor_mismatch safety net for the canon hand-edit

The one hand-edit mistake that cannot be eyeballed or recovered from is an
anchor whose string changed — every illustration already rendered from the
old text is invalidated and nothing else would notice. Warns while the old
document is present, silent once it is deleted.

Extracts normalize_for_comparison to common.py so the comparison ignores
cosmetic whitespace and nothing else."
git push
```

---

### Task 6: `--direction` writes canon files

The stage that authors the reference tier must produce canon files rather than one document, at all three coaching levels.

**Files:**
- Modify: `scripts/lib/python/storyforge/prompts_illustrate.py:759-900` (direction request and template renderers)
- Modify: `scripts/lib/python/storyforge/cmd_illustrate.py` (the `--direction` path)
- Test: `tests/test_illustration_canon.py`

**Interfaces:**
- Consumes: `canon.CANON_DIR`, `canon.CANON_TYPES`, `canon.resolve_canon_path`, `prompts_illustrate._canon_stub`
- Produces:
  - `prompts_illustrate.CANON_PLAN: tuple[tuple[str, str, str], ...]` — `(canon_id, canon_type, purpose)` for the three book-level files.
  - `prompts_illustrate.render_canon_template(*, canon_id, canon_type, purpose, coaching) -> str`
  - `cmd_illustrate.run_direction` writes one file per entry in `CANON_PLAN` plus one per continuity entity, skipping any that already resolve.

- [ ] **Step 1: Write the failing test**

```python
# tests/test_illustration_canon.py — append

def test_direction_writes_the_three_book_level_canon_files(project_dir):
    from storyforge.cmd_illustrate import run_direction
    _set_medium(project_dir, 'novel')

    run_direction(project_dir, coaching='strict', dry_run=False)

    from storyforge.canon import resolve_canon_path
    for canon_id in ('visual-foundation', 'visual-vocabulary',
                     'content-limits'):
        assert resolve_canon_path(project_dir, canon_id) is not None, canon_id


def test_direction_never_overwrites_an_existing_canon_file(project_dir):
    from storyforge.cmd_illustrate import run_direction
    from storyforge.canon import resolve_canon_path, embeddable_block_text
    _set_medium(project_dir, 'novel')
    _write_canon(project_dir, 'visual-foundation.md',
                 body=CANON_BODY
                 .replace('canon_id: nora', 'canon_id: visual-foundation')
                 .replace('canon_type: character', 'canon_type: foundation'))
    before = embeddable_block_text(
        resolve_canon_path(project_dir, 'visual-foundation'))

    run_direction(project_dir, coaching='strict', dry_run=False)

    after = embeddable_block_text(
        resolve_canon_path(project_dir, 'visual-foundation'))
    assert after == before


def test_direction_strict_makes_no_api_call(project_dir, monkeypatch):
    from storyforge import api
    from storyforge.cmd_illustrate import run_direction
    _set_medium(project_dir, 'novel')

    def _boom(*args, **kwargs):
        raise AssertionError('strict coaching must not call the API')

    monkeypatch.setattr(api, 'invoke_api', _boom)
    run_direction(project_dir, coaching='strict', dry_run=False)
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `python3 -m pytest tests/test_illustration_canon.py -k direction_writes -v`

Expected: FAIL — `run_direction` writes `reference/illustration-direction.md`, so `resolve_canon_path` returns `None`.

- [ ] **Step 3: Declare the book-level canon plan**

```python
# prompts_illustrate.py
#: The three book-level canon files an illustrated prose book needs, mapped
#: from the direction document's sections. Continuity anchors are not here —
#: they are one file per entity, discovered from the plan's canon_refs and
#: the character/location registries.
CANON_PLAN: tuple[tuple[str, str, str], ...] = (
    ('visual-foundation', 'foundation',
     'Medium, rendering style, audience, and what every image must deliver. '
     'One or two sentences beat three paragraphs of adjectives.'),
    ('visual-vocabulary', 'vocabulary',
     'The rules that repeat: palette split by faction or mood, camera '
     'height, depth of field, how materials render, the standing no-text '
     'rule.'),
    ('content-limits', 'rules',
     'What the art must never do. Intensity ceilings, imagery to stay away '
     'from, anything the audience age rules out. State these as limits.'),
)
```

- [ ] **Step 4: Add the template renderer**

```python
def render_canon_template(*, canon_id: str, canon_type: str, purpose: str,
                          coaching: str) -> str:
    """Render an unfilled canon file for the author or the model to complete.

    The Embeddable block carries a TODO line deliberately: canon.anchor_texts
    and is_canon_block_populated both treat placeholder text as unpopulated,
    so an unfinished file is reported rather than silently shipped into a
    prompt as though it were direction.
    """
    if coaching == 'coach':
        block = f'TODO — {purpose}\n\nWhat would you say here, in one or two ' \
                f'sentences?\n'
    else:
        block = f'TODO — {purpose}\n'
    return (
        '---\n'
        f'canon_id: {canon_id}\n'
        f'canon_type: {canon_type}\n'
        'canon_updated:\n'
        'appears_in:\n'
        'first_appearance:\n'
        '---\n'
        '\n'
        '## Embeddable block\n'
        '\n'
        f'{block}'
        '\n'
        '## Clauses\n'
        '\n'
        '## Related canon\n'
        '\n'
        '## Iteration history\n'
    )
```

- [ ] **Step 5: Rewrite the `--direction` path**

`run_direction` writes one file per `CANON_PLAN` entry, skipping any id that already resolves. Under `full` coaching it then calls the API once to fill the three Embeddable blocks and writes the returned text in; under `coach` and `strict` it leaves the templates unfilled and makes no API call. Preserve the existing report of empty or placeholder sections — it now iterates canon files instead of document sections.

- [ ] **Step 6: Run the tests**

Run: `python3 -m pytest tests/test_illustration_canon.py -v && python3 -m pytest tests/ -q`

Expected: PASS. Existing `--direction` tests asserting the document's contents need rewriting against canon files; keep each test's intent.

- [ ] **Step 7: Commit**

```bash
git add scripts/lib/python/storyforge/prompts_illustrate.py \
        scripts/lib/python/storyforge/cmd_illustrate.py \
        tests/test_illustration_canon.py tests/test_illustrate_cmd.py
git commit -m "Write the reference tier as canon files instead of one document

--direction now writes visual-foundation, visual-vocabulary, and
content-limits canon files, plus per-entity anchor files, and never
overwrites one that already exists. Templates carry a TODO line so
anchor_texts treats them as unpopulated rather than shipping a scaffold
into a prompt as though it were direction."
git push
```

---

### Task 7: Retire the direction-document readers

With canon as the reference tier, the document readers are dead except for the safety net.

**Files:**
- Modify: `scripts/lib/python/storyforge/illustrations.py:164-280` — `DIRECTION_SECTIONS`, `has_direction`, `missing_direction_sections`, `read_continuity_anchors`, `anchors_section_headings`
- Modify: `scripts/lib/python/storyforge/cmd_illustrate.py` — mode detection and `--diagnose`
- Test: `tests/test_illustration_canon.py`

**Interfaces:**
- Consumes: `canon.anchor_texts`, `canon.resolve_canon_path`, `prompts_illustrate.CANON_PLAN`
- Produces:
  - `illustrations.has_reference_tier(project_dir) -> bool` — True when all three `CANON_PLAN` ids resolve.
  - `illustrations.missing_reference_sections(project_dir) -> list[str]` — canon ids absent or still placeholder.
  - `read_direction`, `find_section`, `direction_path`, `ANCHORS_SECTION` stay, used only by `_direction_anchor_mismatches`. `read_continuity_anchors` and `missing_direction_sections` are deleted.

- [ ] **Step 1: Write the failing test**

```python
# tests/test_illustration_canon.py — append

def test_has_reference_tier_requires_all_three(project_dir):
    from storyforge.illustrations import has_reference_tier
    _set_medium(project_dir, 'novel')
    assert has_reference_tier(project_dir) is False

    for canon_id, canon_type in (('visual-foundation', 'foundation'),
                                 ('visual-vocabulary', 'vocabulary'),
                                 ('content-limits', 'rules')):
        _write_canon(project_dir, f'{canon_id}.md',
                     body=CANON_BODY
                     .replace('canon_id: nora', f'canon_id: {canon_id}')
                     .replace('canon_type: character',
                              f'canon_type: {canon_type}'))

    assert has_reference_tier(project_dir) is True


def test_missing_reference_sections_reports_placeholders(project_dir):
    from storyforge.illustrations import missing_reference_sections
    _set_medium(project_dir, 'novel')
    _write_canon(project_dir, 'visual-foundation.md',
                 body=CANON_BODY
                 .replace('canon_id: nora', 'canon_id: visual-foundation')
                 .replace('canon_type: character', 'canon_type: foundation')
                 .replace('Nora, 9 years old, 132 cm, dark brown hair in a '
                          'short bob, grey-green eyes.',
                          'TODO — fill this in'))

    missing = missing_reference_sections(project_dir)

    assert 'visual-foundation' in missing
    assert 'content-limits' in missing


def test_read_continuity_anchors_is_gone():
    import storyforge.illustrations as ill
    assert not hasattr(ill, 'read_continuity_anchors')
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `python3 -m pytest tests/test_illustration_canon.py -k "reference_tier or reference_sections or continuity_anchors" -v`

Expected: FAIL on the two imports and on `read_continuity_anchors` still existing.

- [ ] **Step 3: Add the canon-backed replacements**

```python
# illustrations.py
def has_reference_tier(project_dir: str) -> bool:
    """True when every book-level canon file exists and is populated.

    The reference tier is what makes a book's images look like one book. A
    project without it can still be planned, but its prompts would carry no
    house style, which is why --prompts warns loudly rather than proceeding
    quietly.
    """
    return not missing_reference_sections(project_dir)


def missing_reference_sections(project_dir: str) -> list[str]:
    """Book-level canon ids that are absent or still placeholder text."""
    from storyforge import canon
    from storyforge.prompts_illustrate import CANON_PLAN

    missing: list[str] = []
    for canon_id, _canon_type, _purpose in CANON_PLAN:
        path = canon.resolve_canon_path(project_dir, canon_id)
        if path is None:
            missing.append(canon_id)
            continue
        body = canon.embeddable_block_text(path)
        if body is None or canon._section_body_is_placeholder(body):
            missing.append(canon_id)
    return missing
```

- [ ] **Step 4: Delete the dead readers and fix every call site**

Delete `read_continuity_anchors`, `missing_direction_sections`, `anchors_section_headings`, and `has_direction`. Keep `read_direction`, `find_section`, `direction_path`, `DIRECTION_SECTIONS`, and `ANCHORS_SECTION` — `_direction_anchor_mismatches` uses them. Add a comment on `DIRECTION_SECTIONS` recording that it now exists only for the safety net.

Find every call site before deleting:

```bash
grep -rn "read_continuity_anchors\|missing_direction_sections\|anchors_section_headings\|has_direction" scripts/ skills/ tests/ | grep -v worktrees
```

Update each. In `cmd_illustrate`, mode detection changes from "no direction document" to "no reference tier", and `--diagnose` reports missing canon ids instead of missing document sections.

- [ ] **Step 5: Run the suite**

Run: `python3 -m pytest tests/ -q`

Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add -A
git commit -m "Retire the direction-document readers in favour of canon

has_reference_tier and missing_reference_sections replace has_direction and
missing_direction_sections; read_continuity_anchors is deleted. read_direction
and find_section survive because the direction_anchor_mismatch safety net
still reads the old file while it exists."
git push
```

---

### Task 8: Document the reference tier

**Files:**
- Modify: `CLAUDE.md` — the Interior Illustrations section
- Modify: `skills/illustrate/SKILL.md` — Step 1, Step 2 mode table, Mode: Direct, and the anchor guidance in Mode: Art-direct
- Test: none; documentation task verified by reading

- [ ] **Step 1: Update CLAUDE.md**

In the Interior Illustrations section, replace the direction-document paragraph with the canon tier: the section-to-canon mapping table, that an entity canon file's `## Embeddable block` *is* the anchor, that `embeds_as` is GN-only, that creatures live under `characters/` and props under `motifs/` because `canon_missing_registry_entry` wants a registry row, and that there is no migration — the one existing project is hand-edited, with `illus_direction_anchor_mismatch` as the safety net.

Also correct the finding-name convention while you are there: `IllustrationFindingKind` members are bare and `cmd_cleanup` prefixes them with `illus_`. The existing documentation lists the prefixed forms without saying where the prefix comes from, which is what makes a new kind get added as `illus_foo` and render as `illus_illus_foo`.

- [ ] **Step 2: Update the skill**

- Step 1 "Read Project State": read `reference/canon/` instead of `reference/illustration-direction.md`.
- Step 2 mode table: "No canon files" → Direct.
- "Mode: Direct": describe writing canon files, and keep the argument that this is the highest-leverage artifact in the flow.
- "Mode: Art-direct" point 3: anchors live in entity canon files' `## Embeddable block`, matched against `canon_refs` by `canon_id`.

- [ ] **Step 3: Verify no stale references remain**

```bash
grep -rn "illustration-direction" CLAUDE.md skills/ | grep -v worktrees
```

Expected: only mentions that describe the hand-edit and the safety net.

- [ ] **Step 4: Bump the version**

Edit `.claude-plugin/plugin.json` and raise the minor version — this phase adds a capability.

- [ ] **Step 5: Commit**

```bash
git add CLAUDE.md skills/illustrate/SKILL.md .claude-plugin/plugin.json
git commit -m "Document the canon reference tier for prose illustrations

Records the section-to-canon mapping, the creature/prop registry
convention, that embeds_as is GN-only, and that there is no migration.
Also documents that IllustrationFindingKind members are bare and
cmd_cleanup adds the illus_ prefix — the existing docs listed only the
prefixed forms, which invites adding a kind as illus_foo."
git push
```

---

## Self-Review

**Spec coverage for this phase.** Canon adoption (Tasks 1–4, 6, 7), the three adoption requirements — medium-aware guard (1), registry placement (documented in 8, enforced by existing `canon_missing_registry_entry`), `embeds_as` optional (2) — no-migration plus safety net (5), documentation (8). Deferred to later phases by design: the state matrix, `--audit`, `--package`, the anchor batch, thinner leaf entries, and the six other new finding kinds, all of which read from the canon tier this phase establishes.

**Placeholders.** Step 5 of Task 6 and Step 4 of Task 7 describe edits across an unknown number of call sites rather than showing final code, because the call-site list depends on what `grep` returns in the worktree. Both give the exact grep command and the rule to apply. Every other code step carries real code.

**Type consistency.** `anchor_texts` returns `dict[str, str]` keyed by `canon_id`, consumed by `anchors_for_prompt` (Task 4), `_direction_anchor_mismatches` (Task 5), and `missing_reference_sections` (Task 7) — via `embeddable_block_text` in the last case, which returns `str | None` and is guarded at each call. `resolve_canon_path` returns `str | None`, guarded in Tasks 6 and 7. `direction_anchor_mismatch` is spelled identically in the Literal, `WARNING_FINDINGS`, `_ILLUSTRATION_ACTIONS`, and all four tests.

**One known coupling to watch.** `missing_reference_sections` reaches into `canon._section_body_is_placeholder`, a private function. That is deliberate rather than sloppy: promoting it to public API is a decision for the staleness-unification issue, which will likely move placeholder detection anyway. If the implementer prefers, promote it in Task 3 alongside the other accessors and drop the underscore everywhere.
