# Illustration Handoff Packet Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace fifteen separate prompt pastes with one packet a long-running generation session can work through, and give the set compositional variety it cannot otherwise have.

**Architecture:** `--package` assembles `manuscript/illustration-packet/` from the canon tier (Phase 1), the state matrix (Phase 2), and the plan — regenerated wholesale so it is a render, never hand-edited. Per-illustration entries drop to 80–120 words because the shared sections carry the rest. A four-slot anchor batch renders first so the churn has real references. A sequence pre-pass assigns each illustration a distinct treatment so twenty independent calls stop converging on the same staging.

**Tech Stack:** Python 3, pytest, pipe-delimited CSV, no external dependencies.

## Global Constraints

- **Anchor text is byte-identical or it is broken.** The packet *copies* anchors out of canon files. Every copy must be byte-identical to its `## Embeddable block` source, asserted by byte comparison — not by presence. This is the single most important invariant in the phase.
- **An artifact must never claim coverage it does not have.** Phase 2's blockers were all a report saying "None found" over prose it never read. The packet is the same kind of artifact: if an entry is thin because data was missing, or an anchor could not be resolved, the **packet itself** says so — not a log line the author read twenty minutes earlier.
- **Finding kinds are bare.** `cmd_cleanup.py` does `'type': f'illus_{kind}'`.
- **`severity_of` defaults unknown kinds to `'error'`**; `BLOCKING_FINDINGS` / `WARNING_FINDINGS` must stay a true partition — a test enforces it.
- **New plan columns go in `OPTIONAL_PLAN_COLUMNS`**, or every legacy plan becomes a `validate` error.
- **CSV writers pass `lineterminator='\n'`.** `newline='\n'` on the open does not work.
- **Patch `cmd_illustrate._invoke` in tests**, never `storyforge.api.invoke_api`, and set `ANTHROPIC_API_KEY` in any no-call test or the missing-key guard short-circuits ahead of the trap. Both defects have shipped in this work.
- **Verify a fixture entity actually appears in fixture prose.** Phase 2 nearly turned twelve tests into no-LLM paths by tracking an entity the prose never mentions.
- Run the suite with `python3 -m pytest tests/ -q`. It passes **5421** at branch start.
- Commit per task and push. Never commit to `main`.

## Interfaces this phase consumes

From Phase 1: `canon.anchor_texts`, `canon.anchor_display_names`, `canon.embeddable_block_text`, `canon.resolve_canon_path`, `prompts_illustrate.CANON_PLAN`, `prompts_illustrate.book_level_direction`, `illustrations.missing_reference_sections`.

From Phase 2: `visual_state.state_at`, `visual_state.parse_state_override`, `visual_state.entities`, `visual_state.prepass`, `visual_state.read_provenance`.

Existing: `illustrations.render_order` → `RenderStep{id, scene_id, is_visual_key, locks, status}`, `illustrations.PLAN_COLUMNS` (already carries `register`, `state_override`, `scene_digest`), `illustrations.VALID_REGISTERS = {'darkest','brightest'}`.

## File Structure

**Create:**
- `scripts/lib/python/storyforge/packet.py` — resolve what goes in the packet and validate the copies. No rendering, no LLM.
- `scripts/lib/python/storyforge/prompts_packet.py` — the six section renderers plus the sequence pre-pass prompt.
- `tests/test_packet.py`, `tests/test_illustrate_package.py`

**Modify:**
- `illustrations.py` — two finding kinds, one plan column (`treatment`)
- `cmd_illustrate.py` — `--package`, `--no-prior-refs` interaction, anchor-batch reporting in `--diagnose`
- `cmd_cleanup.py` — remediation for the new kinds
- `skills/illustrate/SKILL.md`, `CLAUDE.md`

---

### Task 1: Resolve the packet's contents, and prove the anchor copies

**Files:**
- Create: `scripts/lib/python/storyforge/packet.py`, `tests/test_packet.py`

**Interfaces:**
- Produces:
  - `PACKET_DIR = os.path.join('manuscript', 'illustration-packet')`
  - `resolve(project_dir) -> PacketContents` — a `TypedDict` with `book_level: dict[str, str]`, `anchors: dict[str, str]`, `entries: list[Entry]`, `references: list[tuple[str, str]]`, `gaps: list[str]`
  - `Entry` — `TypedDict` with `id`, `scene_id`, `layout`, `aspect`, `beat`, `in_frame`, `state`, `absent`, `contrast`, `notes`
  - `anchor_copy_drift(project_dir) -> list[IllustrationFinding]` — compares every anchor string in the written packet against its canon source

`gaps` is the coverage record: an entry whose `beat` or `subject` is empty, an anchor a `canon_refs` names that does not resolve, a book-level canon file missing or placeholder, a scene with no resolvable state for an entity the row names. Every gap is rendered **into the packet**, per the global constraint.

- [ ] **Step 1: Write the failing test**

```python
# tests/test_packet.py
import os
import pytest
from storyforge import packet, canon


def test_anchors_are_copied_byte_identically(project_dir):
    """The whole mechanism is that every prompt sends the same bytes."""
    src = canon.anchor_texts(project_dir)
    assert src, 'fixture needs at least one entity canon file'
    got = packet.resolve(project_dir)['anchors']
    for canon_id, text in src.items():
        assert got[canon_id] == text, f'{canon_id} was altered in the packet'


def test_a_missing_book_level_file_is_recorded_as_a_gap(project_dir):
    # remove one of the three CANON_PLAN files
    from storyforge.prompts_illustrate import CANON_PLAN
    cid = CANON_PLAN[0][0]
    p = canon.resolve_canon_path(project_dir, cid)
    if p:
        os.remove(p)
    gaps = packet.resolve(project_dir)['gaps']
    assert any(cid in g for g in gaps), f'{cid} absence must be a recorded gap'


def test_an_unresolvable_canon_ref_is_a_gap_not_a_silent_drop(project_dir):
    from storyforge import illustrations as ill
    rows = ill.read_plan(project_dir)
    if not rows:
        pytest.skip('fixture has no plan rows')
    rows[0]['canon_refs'] = 'nobody-by-that-name'
    ill.write_plan(project_dir, rows)
    gaps = packet.resolve(project_dir)['gaps']
    assert any('nobody-by-that-name' in g for g in gaps)


def test_resolve_is_deterministic(project_dir):
    assert packet.resolve(project_dir) == packet.resolve(project_dir)
```

- [ ] **Step 2: Run to verify they fail** — `ModuleNotFoundError: storyforge.packet`.

- [ ] **Step 3: Implement `resolve`.** Read the book-level three via `book_level_direction`, the anchors via `anchor_texts` (verbatim — never `.strip()` beyond what that function already does), the entries from the plan, and the state per entry via `state_at` overlaid with `parse_state_override`. Collect gaps as you go rather than filtering silently.

- [ ] **Step 4: Run, then commit.**

```bash
git add scripts/lib/python/storyforge/packet.py tests/test_packet.py
git commit -m "Resolve packet contents, recording gaps rather than dropping them"
git push
```

---

### Task 2: The two finding kinds and the drift check

**Files:**
- Modify: `illustrations.py` (kinds), `cmd_cleanup.py` (actions), `packet.py` (`anchor_copy_drift`)
- Test: `tests/test_packet.py`

**Interfaces:**
- Produces: bare kinds `packet_stale` (warning) and `anchor_copy_drift` (warning); `anchor_copy_drift(project_dir)`

`packet_stale` fires when any packet file is older than the plan, the state log, or any canon file. `anchor_copy_drift` fires when an anchor string in the written packet differs from its canon source **after `normalize_for_comparison`** — cosmetic whitespace is not drift, a changed word is.

- [ ] **Step 1: Write the failing test**

```python
# tests/test_packet.py — append
def test_a_hand_edited_anchor_in_the_packet_is_reported(project_dir, monkeypatch):
    _write_packet(project_dir)                  # helper: run --package
    p = os.path.join(project_dir, packet.PACKET_DIR, 'canon.md')
    with open(p, encoding='utf-8') as f:
        text = f.read()
    src = canon.anchor_texts(project_dir)
    cid, original = next(iter(src.items()))
    with open(p, 'w', encoding='utf-8') as f:
        f.write(text.replace(original, original.replace('.', '!', 1)))

    kinds = {x['kind'] for x in packet.anchor_copy_drift(project_dir)}
    assert 'anchor_copy_drift' in kinds


def test_cosmetic_whitespace_is_not_drift(project_dir):
    _write_packet(project_dir)
    p = os.path.join(project_dir, packet.PACKET_DIR, 'canon.md')
    with open(p, encoding='utf-8') as f:
        text = f.read()
    with open(p, 'w', encoding='utf-8') as f:
        f.write(text.replace('\n\n', '\n\n\n'))
    assert packet.anchor_copy_drift(project_dir) == []


@pytest.mark.parametrize('kind,expected', [
    ('packet_stale', 'warning'), ('anchor_copy_drift', 'warning')])
def test_new_kinds_have_the_intended_severity(kind, expected):
    from storyforge.illustrations import severity_of
    assert severity_of(kind) == expected
```

- [ ] **Steps 2–4:** run, implement, run, commit.

---

### Task 3: Render the packet — `--package`

**Files:**
- Create: `scripts/lib/python/storyforge/prompts_packet.py`
- Modify: `cmd_illustrate.py` (`--package`, `run_package`)
- Create: `tests/test_illustrate_package.py`

Six files, regenerated wholesale:

```
manuscript/illustration-packet/
├── README.md            the two phases, how to work the packet, what to return
├── canon.md             the reference tier, assembled from reference/canon/
├── visual-state.md      derived dense view: scene x entity
├── illustrations.md     per-illustration entries
├── reference-images.md  which files to upload, in what order, what each is for
└── acceptance.md        global acceptance criteria and sequence-contrast rules
```

Reference images are **not copied**; `reference-images.md` carries project-relative paths. No API calls — assembly only.

**Entry shape, 80–120 words.** Only what is specific to *this* image. `State` stays because it is a resolution for one scene, not a duplication. What lives in `acceptance.md` instead: the colour prohibitions, orientation, no-lettering, and every check identical across the set.

**`Absent` and the colour rules are the deliberate exception to positive framing** — narrow and enumerable: named entities that must not appear, and violations of stated colour logic. Orientation and no-text remain the other two exceptions.

- [ ] **Step 1: Write the failing test**

```python
# tests/test_illustrate_package.py
import os
from storyforge import cmd_illustrate, packet, canon


def test_package_writes_all_six_files(in_project):
    assert cmd_illustrate.main(['--package']) == 0
    for name in ('README.md', 'canon.md', 'visual-state.md',
                 'illustrations.md', 'reference-images.md', 'acceptance.md'):
        assert os.path.isfile(os.path.join(in_project, packet.PACKET_DIR, name))


def test_package_makes_no_api_call(in_project, monkeypatch):
    monkeypatch.setenv('ANTHROPIC_API_KEY', 'test-key')
    def _boom(*a, **k):
        raise AssertionError('--package is assembly, not generation')
    monkeypatch.setattr(cmd_illustrate, '_invoke', _boom)
    assert cmd_illustrate.main(['--package']) == 0


def test_the_packet_states_its_own_gaps(in_project):
    """A thin entry or an unresolved anchor is named IN the packet."""
    from storyforge import illustrations as ill
    rows = ill.read_plan(in_project)
    rows[0]['beat'] = ''
    ill.write_plan(in_project, rows)
    cmd_illustrate.main(['--package'])
    with open(os.path.join(in_project, packet.PACKET_DIR, 'README.md'),
              encoding='utf-8') as f:
        assert rows[0]['id'] in f.read()


def test_regeneration_is_idempotent(in_project):
    cmd_illustrate.main(['--package'])
    first = _read_all(in_project)
    cmd_illustrate.main(['--package'])
    assert _read_all(in_project) == first


def test_anchors_in_the_written_packet_are_byte_identical(in_project):
    cmd_illustrate.main(['--package'])
    with open(os.path.join(in_project, packet.PACKET_DIR, 'canon.md'),
              encoding='utf-8') as f:
        written = f.read()
    for text in canon.anchor_texts(in_project).values():
        assert text in written, 'anchor text was altered on the way in'
```

- [ ] **Steps 2–4:** run, implement the six renderers and `run_package`, run, commit.

---

### Task 4: The anchor batch

**Files:**
- Modify: `packet.py` (`anchor_batch`), `cmd_illustrate.py` (`--diagnose` reports it)
- Test: `tests/test_packet.py`

Derived, never stored, so it cannot disagree with the plan. Four slots:

1. **Establisher** — the existing visual key from `render_order`
2. **Darkest register** — first row with `register=darkest`
3. **Brightest register** — first row with `register=brightest`
4. **Later-state exemplar** — the illustration with the most resolved state entities whose governing transition is **not** that entity's first, ties broken by earliest position

When `register` is unpopulated, slots 2 and 3 fall back to the first and last illustration in story order **and the fallback is reported**. A silent guess about which image is the darkest in the book is how you discover at image twenty that nothing is.

- [ ] **Step 1: Write the failing test**

```python
# tests/test_packet.py — append
def test_all_four_slots_when_register_is_populated(project_dir):
    ...  # set register on two rows; assert four distinct ids and no fallback note


def test_the_fallback_is_reported_when_register_is_empty(project_dir):
    batch = packet.anchor_batch(project_dir)
    assert batch['fallback'], 'a guessed darkest/brightest must be disclosed'


def test_the_establisher_is_the_visual_key(project_dir):
    from storyforge import illustrations as ill
    key = next((s['id'] for s in ill.render_order(project_dir)
                if s['is_visual_key']), None)
    assert packet.anchor_batch(project_dir)['establisher'] == key
```

- [ ] **Steps 2–4:** run, implement, run, commit.

---

### Task 5: The sequence pre-pass — compositional variety

**Files:**
- Modify: `illustrations.py` (`treatment` plan column, optional), `prompts_packet.py` (request + parser), `cmd_illustrate.py` (`--sequence`)
- Test: `tests/test_illustrate_package.py`

This is source-report item 2, deferred here from the prompt-items round. **The evidence:** on the real book, LF-05, LF-18, LF-19 and LF-20 are all "two children kneeling around a lit lamp." Twenty independent calls cannot see each other, so they converge on the same staging — each prompt individually good, the set monotonous. The original 20-image review found the same thing as "three of the last four images are the same shot."

**Do not generate all prompts in one call.** That regresses three things worth keeping: retry granularity (one failure becomes twenty), output quality (a long response gets terser toward the end, so the last illustrations get the worst prompts), and parsing (one malformed heading can eat several prompts).

Instead: one cheap call that sees every plan row — beats and layouts only, not scene prose — and assigns each a distinct treatment (camera distance and height, time of day, how much of the frame the subject occupies, interior versus environmental). Persist to the `treatment` column. `build_art_direction_request` takes it as an input, and the packet entry renders it.

`build_selection_prompt` / `parse_selection_response` are the precedent for the multi-row JSON shape — follow them.

- [ ] **Step 1: Write the failing test**

```python
# tests/test_illustrate_package.py — append
def test_sequence_assigns_a_distinct_treatment_per_row(in_project, monkeypatch):
    monkeypatch.setenv('ANTHROPIC_API_KEY', 'test-key')
    monkeypatch.setattr(cmd_illustrate, '_invoke', lambda *a, **k: (
        '{"treatments": ['
        '{"id": "lantern-vigil", "treatment": "close, low, interior, night"}]}'
    ))
    assert cmd_illustrate.main(['--sequence']) == 0
    from storyforge import illustrations as ill
    row = ill.read_plan_as_map(in_project)['lantern-vigil']
    assert 'close' in row['treatment']


def test_sequence_never_overwrites_an_author_treatment(in_project, monkeypatch):
    ...  # author sets treatment; model proposes different; author's survives


def test_a_repeated_treatment_across_rows_is_reported(in_project, monkeypatch):
    """The point of the pass is variety — identical treatments defeat it."""
    ...  # model returns the same treatment for two rows; assert a WARNING names them
```

- [ ] **Steps 2–4:** run, implement, run, commit.

---

### Task 6: Wire the modes in, document, bump

**Files:** `cmd_illustrate.py` (`--diagnose` rungs), `skills/illustrate/SKILL.md`, `CLAUDE.md`, `.claude-plugin/plugin.json`

- [ ] **Step 1:** `--diagnose` reports the packet rung — built or stale, the anchor batch with its fallback disclosed, and which batch rows are still unrendered.
- [ ] **Step 2:** the skill's mode table gains `Prompts written, no packet or packet stale → Package`, `Packet built, any anchor-batch row not ingested → Anchor`, and `Every anchor-batch row ingested → Churn`. Flags are **output**, not vocabulary the author types. Document the two-phase flow: render and approve the anchor batch, then hand the packet over.
- [ ] **Step 3:** CLAUDE.md — the packet's shape, that it is a render and never hand-edited, the byte-identical anchor invariant, `packet.py` and `prompts_packet.py` in the module table.
- [ ] **Step 4:** minor version bump, full suite, commit.

---

## Self-Review

**Spec coverage.** The packet's six files (T3), the byte-identical anchor invariant with drift detection (T1/T2), `packet_stale` and `anchor_copy_drift` — the last two of the spec's seven finding kinds (T2), the four-slot anchor batch with reported fallback (T4), thin entries with `acceptance.md` holding the set-identical checks (T3), the sequence pre-pass (T5), mode detection and docs (T6). Nothing from the spec's Phase 3 is left out.

**Placeholders.** Tasks 4 and 5 describe four test bodies by shape rather than in full, and Task 6 is prose. Deliberate: the batch's fallback-reporting format and the treatment vocabulary settle during implementation, and Task 6's wording depends on what Tasks 1–5 produced. Every other code step carries real code.

**Type consistency.** `PacketContents` is produced by `resolve` and consumed by every renderer in `prompts_packet`. `Entry` is the one entry type. `anchor_copy_drift` and `packet_stale` return `IllustrationFinding`, so `validate_plan` can extend directly. `anchor_batch` returns a dict with `establisher`, `darkest`, `brightest`, `later_state`, `fallback`.

**The risk I most want watched.** Task 1's byte-identical test compares `resolve`'s output against `anchor_texts`; Task 3's compares the *written file* against `anchor_texts`. Both are needed — the first catches a transform in resolution, the second catches one in rendering, and only the second would catch a renderer that wraps or re-indents a long anchor. If the implementer consolidates them into one test, the rendering path loses its guard.
