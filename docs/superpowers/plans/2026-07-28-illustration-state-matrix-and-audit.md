# Illustration State Matrix and Contradiction Audit Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Record what visual state is true at each point in the story, and read the prose against that record before any art is paid for.

**Architecture:** A sparse transition log (`reference/visual-state.csv`) says when an entity's visible state changes; state at any scene is a forward walk. `--audit` runs a deterministic pre-pass over that log and the prose, narrows to the scenes that could disagree, and sends only those to one LLM pass. Phase 2 of the spec at `docs/superpowers/specs/2026-07-28-illustration-state-matrix-and-packet-design.md`; Phase 3 (the packet) consumes what this builds.

**Tech Stack:** Python 3, pytest, pipe-delimited CSV, no external dependencies.

## Global Constraints

- **Anchor text is byte-identical or it is broken.** Never normalize, reflow, or re-case a canon `## Embeddable block` on any read or write path. Comparison-time normalization via `common.normalize_for_comparison` is fine.
- **Finding kinds are bare.** `cmd_cleanup.py` does `'type': f'illus_{kind}'`. A kind added as `illus_foo` renders `illus_illus_foo`.
- **`severity_of` defaults unknown kinds to `'error'`**, and `BLOCKING_FINDINGS` / `WARNING_FINDINGS` must stay a true partition — an existing test enforces it.
- **New plan columns go in `OPTIONAL_PLAN_COLUMNS`** or every legacy plan becomes a `validate` error and a `cleanup` action item. `ingested_at` set that precedent.
- **CSV writers must pass `lineterminator='\n'`.** `newline='\n'` on the open does not work; `csv.writer` emits its own terminator.
- **Patch `cmd_illustrate._invoke` in tests**, never `storyforge.api.invoke_api` — `cmd_illustrate` imported `invoke` directly, and a test patching the wrong symbol passes vacuously. Any test asserting no-API behavior must also `monkeypatch.setenv('ANTHROPIC_API_KEY', 'test-key')`, or the missing-key guard short-circuits ahead of the trap.
- **Never swallow an error into a silent fallback.** A skipped row, an unresolvable scene, a dropped entity — each gets a log line naming what happened.
- Run the suite with `python3 -m pytest tests/ -q`. It passes **5275** at branch start.
- Commit and push per task. Never commit to `main`.

## File Structure

**Create:**
- `scripts/lib/python/storyforge/visual_state.py` — the transition log: read, resolve, validate. One responsibility, no LLM, no I/O beyond the CSV and scenes.
- `tests/test_visual_state.py` — resolution and validation
- `tests/test_illustrate_audit.py` — the audit pre-pass and its LLM boundary

**Modify:**
- `scripts/lib/python/storyforge/illustrations.py` — three plan columns, five finding kinds
- `scripts/lib/python/storyforge/cmd_illustrate.py` — `--state`, `--audit`, mode reporting in `--diagnose`
- `scripts/lib/python/storyforge/prompts_illustrate.py` — the state-proposal and audit prompt builders, coaching variants
- `scripts/lib/python/storyforge/cmd_cleanup.py` — remediation text for the new kinds
- `skills/illustrate/SKILL.md`, `CLAUDE.md` — the new modes
- `tests/fixtures/test-project/reference/` — a `visual-state.csv`

---

### Task 1: The transition log — read, resolve, validate

**Files:**
- Create: `scripts/lib/python/storyforge/visual_state.py`
- Create: `tests/test_visual_state.py`
- Modify: `tests/fixtures/test-project/reference/visual-state.csv` (new file)

**Interfaces:**
- Consumes: `illustrations._read_ref_csv`, `illustrations._scene_order`, `common.log`
- Produces:
  - `STATE_COLUMNS: list[str]` — `['entity', 'from_scene', 'state', 'evidence']`
  - `read_transitions(project_dir) -> list[Transition]` where `Transition` is a `TypedDict` with those four keys
  - `state_at(project_dir, scene_id) -> dict[str, str]` — entity → state, resolved by forward walk
  - `entities(project_dir) -> list[str]` — every distinct entity, sorted
  - `write_transitions(project_dir, rows) -> str` — `lineterminator='\n'`

- [ ] **Step 1: Write the failing test**

```python
# tests/test_visual_state.py
import os
import pytest
from storyforge import visual_state as vs

ROWS = [
    # entity, from_scene, state, evidence
    ('nora-clothing', 'act1-sc01', 'mustard-yellow nightclothes, barefoot', 'bare feet'),
    ('nora-clothing', 'act2-sc01', 'moss-green cardigan, brown ankle boots', 'jacket zipped'),
    ('great-lamp', 'act1-sc02', 'lit, steady gold, several wicks', 'bowl of living wood'),
]


def _write_state(project_dir, rows=ROWS):
    path = os.path.join(project_dir, 'reference', 'visual-state.csv')
    with open(path, 'w', encoding='utf-8') as f:
        f.write('|'.join(vs.STATE_COLUMNS) + '\n')
        for r in rows:
            f.write('|'.join(r) + '\n')
    return path


def test_state_at_walks_forward_from_the_last_transition(project_dir):
    _write_state(project_dir)
    # act1-sc02 is after act1-sc01 and before act2-sc01
    at = vs.state_at(project_dir, 'act1-sc02')
    assert at['nora-clothing'] == 'mustard-yellow nightclothes, barefoot'
    assert at['great-lamp'] == 'lit, steady gold, several wicks'


def test_state_at_the_transition_scene_uses_the_new_state(project_dir):
    """The boundary: a transition takes effect AT its own scene, not after it."""
    _write_state(project_dir)
    at = vs.state_at(project_dir, 'act2-sc01')
    assert at['nora-clothing'] == 'moss-green cardigan, brown ankle boots'


def test_an_entity_with_no_transition_yet_is_absent(project_dir):
    _write_state(project_dir)
    at = vs.state_at(project_dir, 'act1-sc01')
    assert 'great-lamp' not in at, 'great-lamp first changes at act1-sc02'


def test_entities_lists_every_distinct_entity_sorted(project_dir):
    _write_state(project_dir)
    assert vs.entities(project_dir) == ['great-lamp', 'nora-clothing']


def test_no_state_file_is_empty_not_an_error(project_dir):
    assert vs.read_transitions(project_dir) == []
    assert vs.state_at(project_dir, 'act1-sc01') == {}
    assert vs.entities(project_dir) == []


def test_write_transitions_emits_lf_only(project_dir):
    vs.write_transitions(project_dir, [
        {'entity': 'x', 'from_scene': 'act1-sc01', 'state': 'y', 'evidence': 'z'},
    ])
    with open(os.path.join(project_dir, 'reference', 'visual-state.csv'), 'rb') as f:
        assert b'\r' not in f.read()
```

- [ ] **Step 2: Run to verify they fail**

Run: `python3 -m pytest tests/test_visual_state.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'storyforge.visual_state'`.

- [ ] **Step 3: Implement the module**

```python
"""The visual-state transition log.

A row records the moment a tracked entity's visible state *changes*; the state
persists forward until the next transition for that entity. Sparse rather than a
dense scene x entity grid because scene-map operations insert, merge, split, and
reorder — a transition keyed "from act2-sc01 onward" still means something after a
scene lands before it, where a dense grid would have no row and fall silently
blank.
"""
import csv
import os
from typing import TypedDict

STATE_COLUMNS: list[str] = ['entity', 'from_scene', 'state', 'evidence']
STATE_FILE = os.path.join('reference', 'visual-state.csv')


class Transition(TypedDict):
    entity: str
    from_scene: str
    state: str
    evidence: str


def state_path(project_dir: str) -> str:
    return os.path.join(project_dir, STATE_FILE)


def read_transitions(project_dir: str) -> list[Transition]:
    """Every transition, in file order. Absent file is empty, not an error."""
    from storyforge.illustrations import _read_ref_csv
    rows = _read_ref_csv(project_dir, 'visual-state.csv')
    out: list[Transition] = []
    for row in rows:
        entity = (row.get('entity') or '').strip()
        if not entity:
            continue
        out.append({
            'entity': entity,
            'from_scene': (row.get('from_scene') or '').strip(),
            'state': (row.get('state') or '').strip(),
            'evidence': (row.get('evidence') or '').strip(),
        })
    return out


def state_at(project_dir: str, scene_id: str) -> dict[str, str]:
    """Entity -> state in effect at `scene_id`.

    A transition takes effect AT its own scene, so the comparison is `<=`. An
    entity whose first transition is later than `scene_id` is absent rather than
    blank — "not yet established" and "established as empty" are different, and
    the caller reports them differently.
    """
    from storyforge.illustrations import _scene_order
    order = _scene_order(project_dir)
    if scene_id not in order:
        return {}
    target = order[scene_id]

    best: dict[str, tuple[int, str]] = {}
    for t in read_transitions(project_dir):
        pos = order.get(t['from_scene'])
        if pos is None or pos > target:
            continue
        prior = best.get(t['entity'])
        if prior is None or pos >= prior[0]:
            best[t['entity']] = (pos, t['state'])
    return {e: s for e, (_pos, s) in sorted(best.items())}


def entities(project_dir: str) -> list[str]:
    return sorted({t['entity'] for t in read_transitions(project_dir)})


def write_transitions(project_dir: str, rows: list[Transition]) -> str:
    """Write the log. `lineterminator` is explicit — csv.writer defaults to CRLF,
    which `cleanup` flags and which turns every one-field edit into a whole-file
    diff."""
    path = state_path(project_dir)
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, 'w', encoding='utf-8', newline='') as f:
        w = csv.DictWriter(f, fieldnames=STATE_COLUMNS, delimiter='|',
                           lineterminator='\n')
        w.writeheader()
        for row in rows:
            w.writerow({k: row.get(k, '') for k in STATE_COLUMNS})
    return path
```

Note `pos >= prior[0]` rather than `>`: two transitions for one entity at the same scene means the later row in the file wins, which is deterministic and matches how the plan CSV resolves duplicates.

- [ ] **Step 4: Run to verify they pass**

Run: `python3 -m pytest tests/test_visual_state.py -v`
Expected: PASS.

- [ ] **Step 5: Add the fixture and run the suite**

Add `tests/fixtures/test-project/reference/visual-state.csv` with a header and two transitions using scene ids that exist in that fixture. Then check whether `cmd_cleanup`'s `EXPECTED_CSV_SCHEMAS` needs an entry — if a file in `reference/` without one produces a finding, add it, and add `visual-state.csv` to whatever list makes it optional.

Run: `python3 -m pytest tests/ -q`
Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add scripts/lib/python/storyforge/visual_state.py tests/test_visual_state.py \
        tests/fixtures/test-project/reference/visual-state.csv \
        scripts/lib/python/storyforge/cmd_cleanup.py
git commit -m "Add the visual-state transition log with forward resolution"
git push
```

---

### Task 2: Three plan columns and five finding kinds

**Files:**
- Modify: `scripts/lib/python/storyforge/illustrations.py:43-58` (columns), `:1538` (kinds), `WARNING_FINDINGS` / `BLOCKING_FINDINGS`
- Modify: `scripts/lib/python/storyforge/cmd_cleanup.py` (`_ILLUSTRATION_ACTIONS`)
- Test: `tests/test_visual_state.py`, `tests/test_illustrations.py`

**Interfaces:**
- Produces:
  - `PLAN_COLUMNS` gains `state_override`, `register`, `scene_digest`; all three join `OPTIONAL_PLAN_COLUMNS`
  - `parse_state_override(value) -> dict[str, str]` in `visual_state` — splits `;` then the **first** `:` so a state may contain one
  - `VALID_REGISTERS = frozenset({'darkest', 'brightest'})`
  - Five bare finding kinds: `state_unknown_scene` (error), `evidence_not_found`, `state_unspecified`, `prose_changed`, `audit_stale` (warnings)

- [ ] **Step 1: Write the failing test**

```python
# tests/test_visual_state.py — append
def test_parse_state_override_splits_on_the_first_colon_only():
    from storyforge.visual_state import parse_state_override
    got = parse_state_override('nora-face:tear-streaked;leo-hands:muddy, gripping')
    assert got == {'nora-face': 'tear-streaked', 'leo-hands': 'muddy, gripping'}
    # a state containing a colon survives
    assert parse_state_override('x:a:b') == {'x': 'a:b'}
    assert parse_state_override('') == {}
    assert parse_state_override('malformed') == {}


def test_new_plan_columns_are_optional():
    from storyforge.illustrations import PLAN_COLUMNS, OPTIONAL_PLAN_COLUMNS
    for col in ('state_override', 'register', 'scene_digest'):
        assert col in PLAN_COLUMNS
        assert col in OPTIONAL_PLAN_COLUMNS, (
            f'{col} must be optional or every legacy plan becomes an error')
```

```python
# tests/test_illustrations.py — append
@pytest.mark.parametrize('kind,expected', [
    ('state_unknown_scene', 'error'),
    ('evidence_not_found', 'warning'),
    ('state_unspecified', 'warning'),
    ('prose_changed', 'warning'),
    ('audit_stale', 'warning'),
])
def test_new_finding_kinds_have_the_intended_severity(kind, expected):
    from storyforge.illustrations import severity_of
    assert severity_of(kind) == expected


def test_new_finding_kinds_are_bare_not_prefixed():
    """cmd_cleanup adds the illus_ prefix; a prefixed member renders doubled."""
    from storyforge.illustrations import IllustrationFindingKind
    import typing
    for kind in typing.get_args(IllustrationFindingKind):
        assert not kind.startswith('illus_'), kind
```

- [ ] **Step 2: Run to verify they fail**

Run: `python3 -m pytest tests/test_visual_state.py tests/test_illustrations.py -q -k "override or optional or finding_kinds"`
Expected: FAIL on the import and on `severity_of` returning `'error'` for the four warnings.

- [ ] **Step 3: Implement**

Add the three columns to `PLAN_COLUMNS` and to `OPTIONAL_PLAN_COLUMNS`. Add the five kinds to `IllustrationFindingKind`; put `state_unknown_scene` in `BLOCKING_FINDINGS` and the other four in `WARNING_FINDINGS` — the partition test fails if any lands in both or neither. Add `_ILLUSTRATION_ACTIONS` entries for all five.

```python
# visual_state.py
def parse_state_override(value: str) -> dict[str, str]:
    """Parse `entity:state;entity:state` into a mapping.

    Splits on the FIRST colon so a state may itself contain one. An entry with no
    colon is skipped rather than guessed at.
    """
    out: dict[str, str] = {}
    for part in (value or '').split(';'):
        part = part.strip()
        if not part or ':' not in part:
            continue
        entity, _, state = part.partition(':')
        entity, state = entity.strip(), state.strip()
        if entity and state:
            out[entity] = state
    return out
```

- [ ] **Step 4: Run and commit**

Run: `python3 -m pytest tests/ -q` → PASS.

```bash
git add -A && git commit -m "Add state_override, register, scene_digest columns and five finding kinds" && git push
```

---

### Task 3: Validate the log — the deterministic pre-pass

**Files:**
- Modify: `scripts/lib/python/storyforge/visual_state.py`
- Modify: `scripts/lib/python/storyforge/illustrations.py` (`validate_plan` calls it)
- Test: `tests/test_visual_state.py`

**Interfaces:**
- Consumes: `illustrations.find_anchor` (whitespace-tolerant), `illustrations._read_scene`, `illustrations.strip_markers`, `visual_state.state_at`, `visual_state.parse_state_override`
- Produces: `prepass(project_dir) -> PrepassResult`, a `TypedDict` with `findings: list[IllustrationFinding]` and `candidate_scenes: list[str]`

The four deterministic checks, from the spec:

1. `from_scene` that does not resolve to a scene → `state_unknown_scene` (**error**)
2. `evidence` quote not found in `from_scene`'s prose → `evidence_not_found` (warning). Use `find_anchor` so the quote survives reflow, and strip markers first.
3. An illustration whose `canon_refs` names an entity with no resolved state at its scene → `state_unspecified` (warning). Match `canon_refs` ids against transition entities by exact id **and** by `{canon_id}-{aspect}` prefix, since `nora-clothing` is a track of `nora`.
4. `candidate_scenes` — scenes that mention a tracked entity and lie between that entity's transitions. This is the narrowed set the LLM reads.

- [ ] **Step 1: Write the failing test**

```python
# tests/test_visual_state.py — append
def test_unresolvable_from_scene_is_an_error(project_dir):
    _write_state(project_dir, ROWS + [
        ('great-lamp', 'scene-that-was-cut', 'dark', 'the Lamp was out'),
    ])
    kinds = {f['kind'] for f in vs.prepass(project_dir)['findings']}
    assert 'state_unknown_scene' in kinds


def test_evidence_absent_from_the_prose_is_reported(project_dir):
    _write_state(project_dir, [
        ('great-lamp', 'act1-sc01', 'lit', 'a phrase that is not in this scene'),
    ])
    f = [x for x in vs.prepass(project_dir)['findings']
         if x['kind'] == 'evidence_not_found']
    assert len(f) == 1
    assert f[0]['id'] == 'great-lamp'


def test_evidence_survives_reflowed_prose(project_dir):
    """find_anchor is whitespace-tolerant, so a quote broken across lines matches."""
    scene = os.path.join(project_dir, 'scenes', 'act1-sc01.md')
    with open(scene, encoding='utf-8') as fh:
        text = fh.read()
    first = ' '.join(text.split()[:6])
    reflowed = first.replace(' ', '\n', 2)
    _write_state(project_dir, [('x', 'act1-sc01', 'y', reflowed)])
    kinds = {f['kind'] for f in vs.prepass(project_dir)['findings']}
    assert 'evidence_not_found' not in kinds


def test_an_illustration_naming_an_unstated_entity_is_reported(project_dir):
    from storyforge import illustrations as ill
    _write_state(project_dir, ROWS)
    rows = ill.read_plan(project_dir)
    assert rows, 'fixture needs at least one plan row'
    rows[0]['scene_id'] = 'act1-sc01'
    rows[0]['canon_refs'] = 'murkwolves'      # no transition names it
    ill.write_plan(project_dir, rows)
    f = [x for x in vs.prepass(project_dir)['findings']
         if x['kind'] == 'state_unspecified']
    assert len(f) == 1


def test_an_aspect_track_satisfies_its_bare_canon_id(project_dir):
    """canon_refs says `nora`; the log tracks `nora-clothing`. That counts."""
    from storyforge import illustrations as ill
    _write_state(project_dir, ROWS)
    rows = ill.read_plan(project_dir)
    rows[0]['scene_id'] = 'act1-sc01'
    rows[0]['canon_refs'] = 'nora'
    ill.write_plan(project_dir, rows)
    kinds = {f['kind'] for f in vs.prepass(project_dir)['findings']}
    assert 'state_unspecified' not in kinds


def test_a_state_override_satisfies_the_check(project_dir):
    from storyforge import illustrations as ill
    _write_state(project_dir, ROWS)
    rows = ill.read_plan(project_dir)
    rows[0]['scene_id'] = 'act1-sc01'
    rows[0]['canon_refs'] = 'murkwolves'
    rows[0]['state_override'] = 'murkwolves:dissolving into fog'
    ill.write_plan(project_dir, rows)
    kinds = {f['kind'] for f in vs.prepass(project_dir)['findings']}
    assert 'state_unspecified' not in kinds


def test_clean_log_yields_no_findings(project_dir):
    _write_state(project_dir)
    assert vs.prepass(project_dir)['findings'] == []
```

- [ ] **Step 2: Run to verify they fail**

Run: `python3 -m pytest tests/test_visual_state.py -v -k prepass or unstated or evidence`
Expected: FAIL — `prepass` does not exist.

- [ ] **Step 3: Implement `prepass`**

Write the four checks. For check 2, read the scene with `illustrations._read_scene`, pass it through `illustrations.strip_markers` first (a marker is not prose), then `illustrations.find_anchor`. For check 3, resolve `state_at` for the row's `scene_id`, overlay `parse_state_override`, and treat an entity as covered when any key equals the ref or starts with `f'{ref}-'`.

For `candidate_scenes`, walk scenes in `_scene_order`; a scene is a candidate when it mentions a tracked entity's name (use the entity's bare `canon_id` portion and its display name from `canon.anchor_display_names` if available) and sits at or after that entity's first transition. Report the count in the log so a run that reads nothing says so.

- [ ] **Step 4: Wire into `validate_plan` and run**

`validate_plan` extends its findings with `prepass(project_dir)['findings']`. Confirm the partition test and the every-kind-has-an-action test still pass.

Run: `python3 -m pytest tests/ -q` → PASS.

- [ ] **Step 5: Commit**

```bash
git add -A && git commit -m "Validate the visual-state log: four deterministic checks" && git push
```

---

### Task 4: `--state` writes the log, coaching-aware

**Files:**
- Modify: `scripts/lib/python/storyforge/cmd_illustrate.py` (arg, `run_state`)
- Modify: `scripts/lib/python/storyforge/prompts_illustrate.py` (request + coach/strict renderers)
- Test: `tests/test_illustrate_cmd.py`

**Interfaces:**
- Consumes: `visual_state.write_transitions`, `canon.anchor_texts`, `canon.anchor_display_names`, `common.get_coaching_level`
- Produces: `--state` flag; `run_state(project_dir, coaching, dry_run) -> int`; `prompts_illustrate.build_state_request(...)`, `parse_state_response(text) -> list[Transition]`, `render_state_brief(...)`, `render_state_checklist(...)`

Behavior by coaching level, following the house pattern:

- `full` — one LLM call proposing transitions from the prose, each with its evidence quote; written to the CSV, **existing rows preserved** (never revise a transition the author wrote)
- `coach` — `working/coaching/visual-state-brief.md`, questions per entity
- `strict` — a blank template seeded with the entity list from canon and the registries; **no API call**

- [ ] **Step 1: Write the failing test**

```python
# tests/test_illustrate_cmd.py — append
def test_state_strict_writes_a_template_and_makes_no_api_call(in_project, monkeypatch):
    monkeypatch.setenv('ANTHROPIC_API_KEY', 'test-key')   # or the guard fires first
    def _boom(*a, **k):
        raise AssertionError('strict coaching must not call the API')
    monkeypatch.setattr(cmd_illustrate, '_invoke', _boom)

    assert cmd_illustrate.main(['--state', '--coaching', 'strict']) == 0
    assert os.path.isfile(os.path.join(in_project, 'reference', 'visual-state.csv'))


def test_state_full_writes_proposed_transitions(in_project, monkeypatch):
    monkeypatch.setenv('ANTHROPIC_API_KEY', 'test-key')
    monkeypatch.setattr(cmd_illustrate, '_invoke', lambda *a, **k: (
        '[{"entity": "nora-clothing", "from_scene": "act1-sc01", '
        '"state": "nightclothes, barefoot", "evidence": "bare feet"}]'
    ))
    assert cmd_illustrate.main(['--state', '--coaching', 'full']) == 0
    from storyforge import visual_state as vs
    t = vs.read_transitions(in_project)
    assert any(x['entity'] == 'nora-clothing' for x in t)


def test_state_full_never_revises_an_existing_transition(in_project, monkeypatch):
    from storyforge import visual_state as vs
    vs.write_transitions(in_project, [{
        'entity': 'nora-clothing', 'from_scene': 'act1-sc01',
        'state': 'AUTHOR ORIGINAL', 'evidence': 'bare feet'}])
    monkeypatch.setenv('ANTHROPIC_API_KEY', 'test-key')
    monkeypatch.setattr(cmd_illustrate, '_invoke', lambda *a, **k: (
        '[{"entity": "nora-clothing", "from_scene": "act1-sc01", '
        '"state": "MODEL GUESS", "evidence": "bare feet"}]'
    ))
    assert cmd_illustrate.main(['--state', '--coaching', 'full']) == 0
    kept = [x for x in vs.read_transitions(in_project)
            if x['entity'] == 'nora-clothing' and x['from_scene'] == 'act1-sc01']
    assert len(kept) == 1
    assert kept[0]['state'] == 'AUTHOR ORIGINAL'
```

- [ ] **Step 2: Run to verify they fail** — `--state` is not a recognized flag, so argparse exits 2.

- [ ] **Step 3: Implement** the flag, `run_state`, and the three coaching paths. The preserve rule keys on `(entity, from_scene)`.

- [ ] **Step 4: Run the suite, then commit.**

```bash
git add -A && git commit -m "Add illustrate --state: propose or template the transition log" && git push
```

---

### Task 5: `--audit` — the contradiction pass

**Files:**
- Modify: `scripts/lib/python/storyforge/cmd_illustrate.py` (arg, `run_audit`)
- Modify: `scripts/lib/python/storyforge/prompts_illustrate.py` (audit request + report renderer)
- Create: `tests/test_illustrate_audit.py`

**Interfaces:**
- Consumes: `visual_state.prepass`, `visual_state.state_at`, `illustrations._read_scene`, `illustrations.strip_markers`, `common.normalize_for_comparison`
- Produces: `--audit` flag; `run_audit(project_dir, dry_run) -> int`; writes `working/illustration-contradictions.md` and `working/illustration-audit-provenance.csv`

Read-only with respect to prose and the log — it reports, it never edits.

**Why the LLM pass is necessary, and it must be stated in the report's own prose:** the author writes two transitions — village-lights dark at s10, four surviving at s13 — and nothing about them disagrees, because things are allowed to change. The contradiction is that a scene between them *asserts* a state the span cannot support. Only reading prose against the matrix finds it.

**Cost discipline:** when the pre-pass finds no findings **and** no candidate scenes, make **no LLM call** and say so. Model: Sonnet — analytical, not creative.

- [ ] **Step 1: Write the failing test**

```python
# tests/test_illustrate_audit.py
import os
from storyforge import cmd_illustrate, visual_state as vs


def test_audit_makes_no_api_call_when_the_prepass_is_empty(project_dir, monkeypatch):
    monkeypatch.setenv('ANTHROPIC_API_KEY', 'test-key')
    def _boom(*a, **k):
        raise AssertionError('no candidates means no call')
    monkeypatch.setattr(cmd_illustrate, '_invoke', _boom)
    monkeypatch.chdir(project_dir)
    assert cmd_illustrate.main(['--audit']) == 0
    report = os.path.join(project_dir, 'working', 'illustration-contradictions.md')
    assert os.path.isfile(report)
    with open(report, encoding='utf-8') as f:
        assert 'no' in f.read().lower()


def test_audit_reports_a_prose_assertion_that_contradicts_the_log(project_dir, monkeypatch):
    """The load-bearing case: two transitions do not disagree with each other;
    a scene between them asserts a state the span cannot support."""
    ...  # seed transitions + a scene, mock _invoke to return one finding,
         # assert the report names the scene and which transition it disagrees with


def test_audit_records_a_digest_per_scene_it_read(project_dir, monkeypatch):
    ...  # assert working/illustration-audit-provenance.csv has a row per scene read


def test_audit_never_edits_the_log_or_the_prose(project_dir, monkeypatch):
    ...  # snapshot bytes of visual-state.csv and every scene, assert unchanged
```

Fill the three stubs with the same shape as the first: seed state, patch `cmd_illustrate._invoke`, assert on the written report. The byte-snapshot test is the important one — an audit that edits prose is a far worse bug than one that misses a contradiction.

- [ ] **Step 2–4: run, implement, run.** Provenance rows are `scene_id|digest|audited_at`, digest via `common.normalize_for_comparison` so a whitespace-only edit does not read as staleness.

- [ ] **Step 5: Commit.**

```bash
git add -A && git commit -m "Add illustrate --audit: contradiction pass over prose and the state log" && git push
```

---

### Task 6: Wire the modes in and document

**Files:**
- Modify: `scripts/lib/python/storyforge/cmd_illustrate.py` (`--diagnose` reports state/audit rungs)
- Modify: `skills/illustrate/SKILL.md` (mode table gains State and Audit)
- Modify: `CLAUDE.md` (command table, the Interior Illustrations section, `visual_state.py` in the module table)
- Modify: `.claude-plugin/plugin.json` — bump the **minor** version; this is new capability

- [ ] **Step 1:** `--diagnose` reports whether the state log exists, how many entities it tracks, and whether the audit has run or is stale. Test it.
- [ ] **Step 2:** the skill's mode table gains `Plan exists, no state matrix → State` and `Matrix exists, audit unrun or stale → Audit`, with the flags as *output* — the author types none of them.
- [ ] **Step 3:** CLAUDE.md — command table entry for the new flags, `visual_state.py` in Domain modules, and the state matrix in the Interior Illustrations section. State the `{canon_id}-{aspect}` convention and that a transition takes effect **at** its scene.
- [ ] **Step 4:** version bump, full suite, commit.

```bash
git add -A && git commit -m "Report the state and audit rungs; document the state matrix" && git push
```

---

## Self-Review

**Spec coverage.** `reference/visual-state.csv` (T1), the three plan columns (T2), five of the seven finding kinds (T2/T3), `--state` with coaching (T4), `--audit` with the deterministic pre-pass and cost discipline (T5), mode detection and docs (T6). **Deferred to Phase 3 by design:** `--package`, thin per-illustration entries, the anchor batch, `illus_packet_stale`, `illus_anchor_copy_drift`, and the sequence pre-pass (source-report item 2).

**Placeholders.** Task 5's steps 1 and 2–4 describe three test bodies by shape rather than in full, and Task 6's steps are prose. Both are deliberate: the audit's report format is settled during implementation, and Task 6 is documentation whose exact wording depends on what Tasks 1–5 produced. Every other code step carries real code.

**Type consistency.** `Transition` is the one row type, produced by `read_transitions` and consumed by `write_transitions`, `state_at`, and `parse_state_response`. `state_at` returns `dict[str, str]`, overlaid by `parse_state_override`'s `dict[str, str]`. `prepass` returns findings typed `IllustrationFinding` so `validate_plan` can extend its list directly. All five new kinds are spelled identically in the Literal, the severity sets, `_ILLUSTRATION_ACTIONS`, and the tests.

**One thing to watch during implementation.** `state_at` calls `_scene_order`, which prefers the chapter map and falls back to `scenes.csv:seq`. A project whose chapter map omits a scene will resolve that scene's state as `{}` rather than raising. That is the right degradation, but it means a missing chapter-map entry looks like "no state" — worth a log line if it is cheap to detect.
