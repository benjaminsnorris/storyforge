# `storyforge status` Next-Step Verdict Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a deterministic, no-LLM `storyforge status` command that synthesizes existing floor/consistency/coverage checks into one routable next-step verdict, and wire `forge`/`elaborate` to surface prose-tier + story-power scoring (#267).

**Architecture:** A pure domain module `status.py` walks the elaboration ladder (L0–L6 floor checks) to find the first incomplete rung, folds coverage/consistency mismatches into `blockers`, and derives post-briefs rungs from scene draft-state — returning a verdict dict. A thin `cmd_status.py` renders it as a human tree or `--json`. Skills call it and route on the stable `next.stage` enum.

**Tech Stack:** Python 3 stdlib only (`argparse`, `json`, `os`, `csv`), pytest. Reuses `storyforge.scoring_levels`, `scoring_consistency`, `scoring_coverage`, `common`.

## Global Constraints

- **Never commit to main.** Work stays on branch `storyforge/status-267` (already created).
- **Commit and push after every task.** No exceptions.
- Bump `version` in `.claude-plugin/plugin.json` (minor — new feature) in the final task.
- Command modules expose `parse_args(argv)` + `main(argv=None)`; import shared utils from `storyforge.common`.
- Pipe-delimited CSVs: field delimiter `|`, array delimiter `;`, header row first, no quoting.
- `status` is read-only, no LLM, no writes to project state.
- Reuse existing scorers — add NO new checks.
- Commit prefixes: `Add`/`Update`/`Fix` for plugin code; `Elaborate:` was used for the spec.

---

## File Structure

- **Create** `scripts/lib/python/storyforge/status.py` — pure verdict logic (`build_status`, ladder walk, recommendation mapping). The unit-tested surface.
- **Create** `scripts/lib/python/storyforge/cmd_status.py` — thin CLI: `parse_args`/`main`, `--json`/`--dry-run`, human-tree + JSON rendering.
- **Modify** `scripts/lib/python/storyforge/__main__.py` — add `'status'` dispatch entry.
- **Create** `tests/commands/test_status.py` — verdict logic over fixtures.
- **Modify** `skills/forge/SKILL.md` — invoke `status --json` first; add prose-tier/story-power/compare routing.
- **Modify** `skills/elaborate/SKILL.md` — pre-spine prose-tier stage; add `--story-power` to Step 5.
- **Modify** `CLAUDE.md` — add `storyforge status` to command table + module table.
- **Modify** `.claude-plugin/plugin.json` — version bump.
- **Create** memory file + `MEMORY.md` pointer.

---

## Reference: interfaces this plan consumes (verbatim from the codebase)

```python
# storyforge.scoring_levels
LEVEL_NAMES = {0:'logline',1:'synopsis',2:'act-shape',3:'spine',
               4:'architecture',5:'scene-map',6:'briefs'}
def score_all_levels(project_dir: str, medium: str = 'novel') -> list[dict]: ...
# each dict: {'level':int,'name':str,'checks':[{'check','passed','detail',
#             'severity','accepted'}],'passed':int,'failed':int,'accepted':int}

# storyforge.scoring_consistency
def score_consistency_all_levels(project_dir: str) -> list[dict]: ...   # levels 3-6
# storyforge.scoring_coverage
def score_coverage_all_levels(project_dir: str) -> list[dict]: ...      # levels 2-4
# (both return the same result-dict shape as above)

# storyforge.common
def parse_story_summary(project_dir=None) -> dict | None:
    # {'frontmatter':{...},'logline':str,'synopsis':str,'act_shape':str,'theme':str}
    # None if reference/story-summary.md is absent
def read_yaml_field(field: str, project_dir=None) -> str:   # e.g. read_yaml_field('phase', pd)
def get_medium(project_dir: str) -> str:                     # 'novel' | 'graphic-novel'
def detect_project_root() -> str
def log(msg: str) -> None

# elaborate --stage choices: 'spine','architecture','map','briefs'
# scenes.csv status values seen: spine, architecture, mapped, briefed, drafted, polished, cut, merged
```

---

## Task 1: Ladder-state helpers in `status.py`

**Files:**
- Create: `scripts/lib/python/storyforge/status.py`
- Test: `tests/commands/test_status.py`

**Interfaces:**
- Consumes: `score_all_levels`, `score_consistency_all_levels`, `score_coverage_all_levels`, `LEVEL_NAMES`, `parse_story_summary`.
- Produces:
  - `LADDER_LEVELS = [0,1,2,3,4,5,6]`
  - `PROSE_STAGES = ('logline','synopsis','act-shape')`
  - `ELABORATE_STAGE: dict[str,str]` mapping rung name → `elaborate --stage` arg
  - `artifact_present(project_dir: str, level: int) -> bool`
  - `ladder_states(project_dir: str, medium: str='novel') -> list[dict]` where each item is `{'level':int,'name':str,'state':'solid'|'thin'|'not_started','detail':str}`

- [ ] **Step 1: Write the failing test**

Add to `tests/commands/test_status.py`:

```python
import os
from storyforge import status


def _write(path, text):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, 'w', encoding='utf-8') as f:
        f.write(text)


def test_artifact_present_prose_and_csv(tmp_path):
    pd = str(tmp_path)
    # No story-summary.md, no CSVs → nothing present.
    assert status.artifact_present(pd, 0) is False
    assert status.artifact_present(pd, 3) is False

    _write(os.path.join(pd, 'reference', 'story-summary.md'),
           "## Logline\nA mapmaker who cannot lie must chart a lie.\n\n"
           "## Synopsis\n\n## Act-shape\n\n## Theme\n")
    assert status.artifact_present(pd, 0) is True   # logline has body
    assert status.artifact_present(pd, 1) is False  # synopsis empty

    # CSV present only counts when it has a data row beyond the header.
    _write(os.path.join(pd, 'reference', 'spine.csv'), "id|seq|title\n")
    assert status.artifact_present(pd, 3) is False
    _write(os.path.join(pd, 'reference', 'spine.csv'),
           "id|seq|title\ne1|1|Opening\n")
    assert status.artifact_present(pd, 3) is True


def test_ladder_states_empty_project(tmp_path):
    ladder = status.ladder_states(str(tmp_path))
    assert [r['level'] for r in ladder] == [0, 1, 2, 3, 4, 5, 6]
    assert all(r['state'] == 'not_started' for r in ladder)
    assert ladder[0]['name'] == 'logline'
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python3 -m pytest tests/commands/test_status.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'storyforge.status'` (or `AttributeError`).

- [ ] **Step 3: Write minimal implementation**

Create `scripts/lib/python/storyforge/status.py`:

```python
"""storyforge status — deterministic next-step verdict.

Composes the existing floor / consistency / coverage scorers plus phase and
scene draft-state into a single routable verdict: where the project sits on
the elaboration ladder and the single recommended next action.

No LLM, no writes. Pure over project files.
"""

import os

from storyforge.scoring_levels import score_all_levels, LEVEL_NAMES
from storyforge.scoring_consistency import score_consistency_all_levels
from storyforge.scoring_coverage import score_coverage_all_levels
from storyforge.common import parse_story_summary

LADDER_LEVELS = [0, 1, 2, 3, 4, 5, 6]
PROSE_STAGES = ('logline', 'synopsis', 'act-shape')

# Rung name -> `elaborate --stage` argument (only rungs with a command stage).
ELABORATE_STAGE = {
    'spine': 'spine',
    'architecture': 'architecture',
    'scene-map': 'map',
    'briefs': 'briefs',
}

# Which reference CSV backs each structural rung.
_LEVEL_CSV = {
    3: 'spine.csv',
    4: 'architecture.csv',
    5: 'scenes.csv',
    6: 'scene-briefs.csv',
}

# Prose-tier level -> parse_story_summary key.
_PROSE_KEY = {0: 'logline', 1: 'synopsis', 2: 'act_shape'}


def artifact_present(project_dir: str, level: int) -> bool:
    """True when the artifact backing `level` exists with real content."""
    if level in _PROSE_KEY:
        parsed = parse_story_summary(project_dir)
        if parsed is None:
            return False
        return bool(parsed.get(_PROSE_KEY[level], '').strip())
    path = os.path.join(project_dir, 'reference', _LEVEL_CSV[level])
    if not os.path.isfile(path):
        return False
    with open(path, encoding='utf-8') as f:
        rows = [ln for ln in f.read().splitlines() if ln.strip()]
    return len(rows) > 1  # header + at least one data row


def _real_failed(floor: dict) -> int:
    """Floor failures that the author has NOT accepted via override."""
    return floor['failed'] - floor['accepted']


def ladder_states(project_dir: str, medium: str = 'novel') -> list[dict]:
    """Return per-rung state for levels 0-6, derived from floor checks only.

    Coverage/consistency are NOT folded in here — they look downstream and
    would wrongly keep an upstream rung `thin`; they surface as blockers.
    """
    floors = {r['level']: r for r in score_all_levels(project_dir, medium)}
    ladder = []
    for level in LADDER_LEVELS:
        floor = floors[level]
        if not artifact_present(project_dir, level):
            state, detail = 'not_started', ''
        elif _real_failed(floor) == 0:
            state, detail = 'solid', ''
        else:
            state = 'thin'
            fails = [c['detail'] or c['check'] for c in floor['checks']
                     if not c['passed'] and not c.get('accepted')]
            detail = fails[0] if fails else ''
        ladder.append({'level': level, 'name': LEVEL_NAMES[level],
                       'state': state, 'detail': detail})
    return ladder
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python3 -m pytest tests/commands/test_status.py -v`
Expected: PASS (both tests).

- [ ] **Step 5: Commit**

```bash
git add scripts/lib/python/storyforge/status.py tests/commands/test_status.py
git commit -m "Add status.py ladder-state helpers (#267)"
git push
```

---

## Task 2: Blockers, draft-state, and `build_status` verdict

**Files:**
- Modify: `scripts/lib/python/storyforge/status.py`
- Test: `tests/commands/test_status.py`

**Interfaces:**
- Consumes: Task 1's `ladder_states`, `artifact_present`, `ELABORATE_STAGE`, `PROSE_STAGES`; `read_yaml_field`.
- Produces:
  - `collect_blockers(project_dir: str) -> list[dict]` → items `{'source':'coverage'|'consistency','level':int,'detail':str}`
  - `draft_stage(project_dir: str) -> tuple[str, int, int]` → `(stage, drafted, total)` where `stage` ∈ `{'draft','evaluate'}`
  - `build_status(project_dir: str, medium: str='novel') -> dict` → the verdict:
    ```
    {'phase':str,'phase_declared':str,'phase_matches_yaml':bool,
     'ladder':[...],'next':{'stage','action','command','reason'},
     'then':{'stage','action','command','reason'}|None,'blockers':[...]}
    ```

- [ ] **Step 1: Write the failing test**

Append to `tests/commands/test_status.py`:

```python
def test_build_status_empty_project_points_to_logline(tmp_path):
    v = status.build_status(str(tmp_path))
    assert v['phase'] == 'logline'
    assert v['next']['stage'] == 'logline'
    assert v['next']['command'] == 'storyforge score --level 0'
    assert v['then']['stage'] == 'story-power'
    assert v['blockers'] == []


def test_build_status_prose_solid_points_to_spine(tmp_path):
    pd = str(tmp_path)
    _write(os.path.join(pd, 'reference', 'story-summary.md'),
           "## Logline\n"
           "A cartographer who cannot draw a false line is ordered to forge "
           "a map that will start a war.\n\n"
           "## Synopsis\n"
           "She takes the commission. She learns the war it will start. She "
           "must choose between the guild that made her and the truth only "
           "she can draw. In the end she draws the true map and burns the "
           "guild's copy.\n\n"
           "## Act-shape\n"
           "### Act 1\nShe accepts the forbidden commission.\n"
           "### Act 2\nShe uncovers the war it will trigger and is trapped.\n"
           "### Act 3\nShe draws the truth and pays for it.\n\n"
           "## Theme\nTruth has a cost; someone must pay it.\n")
    v = status.build_status(pd)
    # All three prose rungs solid → phase advances to spine.
    prose = {r['name']: r['state'] for r in v['ladder'] if r['level'] < 3}
    assert prose == {'logline': 'solid', 'synopsis': 'solid',
                     'act-shape': 'solid'}
    assert v['phase'] == 'spine'
    assert v['next']['stage'] == 'spine'
    assert v['next']['command'] == 'storyforge elaborate --stage spine'


def test_phase_mismatch_is_reported(tmp_path):
    pd = str(tmp_path)
    _write(os.path.join(pd, 'storyforge.yaml'), "phase: architecture\n")
    v = status.build_status(pd)
    assert v['phase_declared'] == 'architecture'
    assert v['phase'] == 'logline'          # nothing built yet
    assert v['phase_matches_yaml'] is False
    assert any(b['source'] == 'phase' for b in v['blockers'])
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python3 -m pytest tests/commands/test_status.py -v`
Expected: FAIL — `AttributeError: module 'storyforge.status' has no attribute 'build_status'`.

- [ ] **Step 3: Write minimal implementation**

Append to `scripts/lib/python/storyforge/status.py`:

```python
from storyforge.common import read_yaml_field  # noqa: E402  (grouped with helpers)

# Scene statuses that count as drafted-or-later.
_DRAFTED_STATUSES = {'drafted', 'polished'}
_EXCLUDED_STATUSES = {'cut', 'merged'}


def collect_blockers(project_dir: str) -> list[dict]:
    """Coverage + consistency failures for rungs whose artifact is present."""
    blockers: list[dict] = []
    for source, results in (
        ('coverage', score_coverage_all_levels(project_dir)),
        ('consistency', score_consistency_all_levels(project_dir)),
    ):
        for r in results:
            level = r['level']
            if not artifact_present(project_dir, level):
                continue
            for c in r['checks']:
                if not c['passed'] and not c.get('accepted'):
                    blockers.append({'source': source, 'level': level,
                                     'detail': c['detail'] or c['check']})
    return blockers


def _read_scene_statuses(project_dir: str) -> list[str]:
    path = os.path.join(project_dir, 'reference', 'scenes.csv')
    if not os.path.isfile(path):
        return []
    with open(path, encoding='utf-8') as f:
        lines = [ln for ln in f.read().splitlines() if ln.strip()]
    if len(lines) < 2:
        return []
    header = lines[0].split('|')
    try:
        idx = header.index('status')
    except ValueError:
        return []
    out = []
    for ln in lines[1:]:
        cells = ln.split('|')
        out.append(cells[idx] if idx < len(cells) else '')
    return out


def draft_stage(project_dir: str) -> tuple[str, int, int]:
    """Return (stage, drafted, total) for the post-briefs rungs.

    stage is 'evaluate' once every non-cut/merged scene is drafted+; else
    'draft'. total counts scenes excluding cut/merged.
    """
    statuses = [s for s in _read_scene_statuses(project_dir)
                if s not in _EXCLUDED_STATUSES]
    total = len(statuses)
    drafted = sum(1 for s in statuses if s in _DRAFTED_STATUSES)
    if total > 0 and drafted == total:
        return 'evaluate', drafted, total
    return 'draft', drafted, total


def _recommend(stage: str) -> tuple[dict, dict | None]:
    """Map the current stage to (next, then) step objects."""
    if stage in PROSE_STAGES:
        level = {'logline': 0, 'synopsis': 1, 'act-shape': 2}[stage]
        nxt = {'stage': stage,
               'action': f'Develop the {stage} (elaborate skill, prose tier)',
               'command': f'storyforge score --level {level}',
               'reason': f'The {stage} floor is not yet met'}
        then = {'stage': 'story-power',
                'action': 'Pressure-test the pitch with the story-power scorecard',
                'command': 'storyforge score --story-power',
                'reason': 'Validate narrative design before building the spine'}
        return nxt, then
    if stage in ELABORATE_STAGE:
        order = ['spine', 'architecture', 'scene-map', 'briefs']
        nxt = {'stage': stage,
               'action': f'Develop the {stage}',
               'command': f'storyforge elaborate --stage {ELABORATE_STAGE[stage]}',
               'reason': f'{stage} is the next incomplete rung'}
        i = order.index(stage)
        if i + 1 < len(order):
            nxt_name = order[i + 1]
            then = {'stage': nxt_name,
                    'action': f'Develop the {nxt_name}',
                    'command': f'storyforge elaborate --stage {ELABORATE_STAGE[nxt_name]}',
                    'reason': ''}
        else:
            then = {'stage': 'draft', 'action': 'Draft scenes',
                    'command': 'storyforge write', 'reason': ''}
        return nxt, then
    if stage == 'draft':
        return ({'stage': 'draft', 'action': 'Draft scenes',
                 'command': 'storyforge write',
                 'reason': 'Briefs are complete; scenes are ready to draft'},
                {'stage': 'evaluate', 'action': 'Evaluate drafted scenes',
                 'command': 'storyforge evaluate', 'reason': ''})
    return ({'stage': 'evaluate', 'action': 'Evaluate and polish',
             'command': 'storyforge evaluate',
             'reason': 'All scenes are drafted'}, None)


def build_status(project_dir: str, medium: str = 'novel') -> dict:
    """Compose the full next-step verdict. Deterministic, read-only."""
    ladder = ladder_states(project_dir, medium)

    # Current phase = first rung that is not solid; if all solid, derive from
    # scene draft-state.
    phase = None
    for rung in ladder:
        if rung['state'] != 'solid':
            phase = rung['name']
            break
    if phase is None:
        phase, _drafted, _total = draft_stage(project_dir)

    declared = (read_yaml_field('phase', project_dir) or '').strip()
    # yaml phases use 'scene-map' spelled 'scene-map'; declared legacy phases
    # (drafting/evaluation/etc.) simply won't match a ladder rung name.
    matches = (declared == phase) if declared else True

    blockers = collect_blockers(project_dir)
    if declared and not matches:
        blockers.insert(0, {
            'source': 'phase', 'level': -1,
            'detail': (f"storyforge.yaml phase is '{declared}' but the ladder "
                       f"puts the project at '{phase}'"),
        })

    nxt, then = _recommend(phase)
    return {
        'phase': phase,
        'phase_declared': declared,
        'phase_matches_yaml': matches,
        'ladder': ladder,
        'next': nxt,
        'then': then,
        'blockers': blockers,
    }
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python3 -m pytest tests/commands/test_status.py -v`
Expected: PASS (all tests in the file).

- [ ] **Step 5: Commit**

```bash
git add scripts/lib/python/storyforge/status.py tests/commands/test_status.py
git commit -m "Add build_status verdict: blockers, draft-state, recommendations (#267)"
git push
```

---

## Task 3: `cmd_status.py` CLI + dispatch

**Files:**
- Create: `scripts/lib/python/storyforge/cmd_status.py`
- Modify: `scripts/lib/python/storyforge/__main__.py` (COMMANDS dict, lines 42–70)
- Test: `tests/commands/test_status.py`

**Interfaces:**
- Consumes: `status.build_status`, `common.detect_project_root`, `common.get_medium`.
- Produces: `cmd_status.parse_args(argv)`, `cmd_status.main(argv=None)`, `cmd_status.render_human(verdict) -> str`.

- [ ] **Step 1: Write the failing test**

Append to `tests/commands/test_status.py`:

```python
from storyforge import cmd_status


def test_render_human_contains_ladder_and_next(tmp_path):
    v = status.build_status(str(tmp_path))
    text = cmd_status.render_human(v)
    assert 'PHASE:' in text
    assert 'L0 logline' in text
    assert 'NEXT:' in text
    assert 'storyforge score --level 0' in text


def test_main_json_output(tmp_path, capsys, monkeypatch):
    import json as _json
    monkeypatch.setattr(cmd_status, 'detect_project_root',
                        lambda: str(tmp_path))
    monkeypatch.setattr(cmd_status, 'get_medium', lambda pd: 'novel')
    cmd_status.main(['--json'])
    out = capsys.readouterr().out
    data = _json.loads(out)
    assert data['phase'] == 'logline'
    assert data['next']['stage'] == 'logline'
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python3 -m pytest tests/commands/test_status.py -k "render_human or json_output" -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'storyforge.cmd_status'`.

- [ ] **Step 3: Write minimal implementation**

Create `scripts/lib/python/storyforge/cmd_status.py`:

```python
"""storyforge status — deterministic next-step verdict.

Usage:
    storyforge status            # human-readable tree + recommended next step
    storyforge status --json     # structured verdict for tooling (e.g. forge)

Read-only, no LLM. Synthesizes the elaboration floor/coverage/consistency
checks plus phase and scene draft-state into one routable verdict.
"""

import argparse
import json

from storyforge.common import detect_project_root, get_medium
from storyforge.status import build_status

_STATE_MARK = {'solid': '✓', 'thin': '✗', 'not_started': '—'}


def parse_args(argv):
    parser = argparse.ArgumentParser(
        prog='storyforge status',
        description='Deterministic next-step verdict for the current project.')
    parser.add_argument('--json', action='store_true', dest='json_output',
                        help='Emit the structured verdict as JSON')
    parser.add_argument('--dry-run', action='store_true',
                        help='No-op flag for interface parity (status never writes)')
    return parser.parse_args(argv)


def render_human(verdict: dict) -> str:
    lines = []
    match = ('matches storyforge.yaml' if verdict['phase_matches_yaml']
             else f"declared '{verdict['phase_declared']}'")
    suffix = '' if not verdict['phase_declared'] else f'  ({match})'
    lines.append(f"PHASE: {verdict['phase']}{suffix}")
    lines.append('LADDER:')
    for r in verdict['ladder']:
        mark = _STATE_MARK[r['state']]
        detail = f" — {r['detail']}" if r['detail'] else ''
        lines.append(f"  L{r['level']} {r['name']:<13} {mark} {r['state']}{detail}")
    nxt = verdict['next']
    cmd = f"  [{nxt['command']}]" if nxt['command'] else ''
    lines.append(f"NEXT:  {nxt['action']}{cmd}")
    if nxt['reason']:
        lines.append(f"       {nxt['reason']}")
    if verdict['then']:
        lines.append(f"THEN:  {verdict['then']['action']}")
    if verdict['blockers']:
        lines.append('BLOCKERS:')
        for b in verdict['blockers']:
            lines.append(f"  [{b['source']}] {b['detail']}")
    else:
        lines.append('BLOCKERS: none')
    return '\n'.join(lines)


def main(argv=None):
    parse_args(argv or [])  # validates flags
    args = parse_args(argv or [])
    project_dir = detect_project_root()
    medium = get_medium(project_dir) or 'novel'
    verdict = build_status(project_dir, medium)
    if args.json_output:
        print(json.dumps(verdict, indent=2))
    else:
        print(render_human(verdict))
```

- [ ] **Step 4: Add the dispatch entry**

In `scripts/lib/python/storyforge/__main__.py`, add to the `COMMANDS` dict (alphabetically near the others, after the `'sync'` line):

```python
    'status': 'storyforge.cmd_status',
```

- [ ] **Step 5: Run tests + the real CLI**

Run: `python3 -m pytest tests/commands/test_status.py -v`
Expected: PASS (all tests).

Run: `./storyforge status` from the fixture project:
```bash
(cd tests/fixtures/test-project && python3 -m storyforge status)
```
Expected: prints a `PHASE: / LADDER: / NEXT:` tree without error.

Run: `(cd tests/fixtures/test-project && python3 -m storyforge status --json)`
Expected: valid JSON with a `phase` key.

- [ ] **Step 6: Commit**

```bash
git add scripts/lib/python/storyforge/cmd_status.py \
        scripts/lib/python/storyforge/__main__.py \
        tests/commands/test_status.py
git commit -m "Add storyforge status command + dispatch (#267)"
git push
```

---

## Task 4: Wire `forge` skill to invoke `status`

**Files:**
- Modify: `skills/forge/SKILL.md`

**Interfaces:**
- Consumes: `storyforge status --json` (`next.stage` enum, `blockers`, `ladder`).

- [ ] **Step 1: Read the current routing sections**

Run: `grep -n "phase\|Guided\|Directed\|Score\|elaboration" skills/forge/SKILL.md`
Read the "Read Project State", guided-mode ladder (~line 49), and directed-mode "Score" routing (~line 225) blocks so edits slot into the existing structure.

- [ ] **Step 2: Add a status-first step to "Read Project State"**

After the step that reads `storyforge.yaml` (step 1, ~line 22), add a new step:

```markdown
2. **Run `storyforge status --json`** and parse the verdict. This is the
   deterministic source of truth for *where the project is and what to do
   next* — prefer it over inferring phase from `storyforge.yaml` by hand. Key
   fields:
   - `next.stage` — the stable routing key. Route on this, not on prose.
   - `next.command` — the concrete command to recommend/run (may be empty for
     prose-tier steps that route to the `elaborate` skill).
   - `blockers` — coverage/consistency mismatches and any phase/yaml
     disagreement; surface these before advancing.
   - `ladder` — per-rung `solid`/`thin`/`not_started` for the status readout.
```

Renumber the subsequent steps in that section (+1).

- [ ] **Step 3: Add prose-tier + story-power routing to guided mode**

In the guided-mode elaboration rung (the "If the project is in an elaboration phase" block, ~line 51), add before the spine handling:

```markdown
- **If `status` reports `next.stage` is `logline`, `synopsis`, or `act-shape`**
  (the pitch/prose tier), the project has not solidified its pitch. Route to
  the `elaborate` skill's prose-tier stage to develop that section, then:
  - `storyforge score --level 0|1|2` — deterministic floor check on the section
  - `storyforge score --story-power` — the 8-axis pitch-tier scorecard
    (pressure-tests logline/synopsis/act-shape before any spine work)
  - `storyforge score --compare <a> <b> [--level N]` — compare candidate
    loglines/synopses when the author is exploring options
- **If `next.stage` is `story-power`**, recommend running
  `storyforge score --story-power` to validate narrative design before the spine.
```

- [ ] **Step 4: Add prose-tier flags to directed-mode "Score" routing**

In the directed-mode Score section (~line 225), add:

```markdown
- **Pitch/prose tier:** `storyforge score --story-power` (8-axis pitch
  scorecard), `storyforge score --level 0|1|2` (logline/synopsis/act-shape
  floor checks), `storyforge score --compare <candidates> --level N` (compare
  prose candidates). Use these before/independent of the structural
  `--level 3-5` tiers.
```

- [ ] **Step 5: Verify the edits**

Run: `grep -n "story-power\|status --json\|next.stage\|--compare" skills/forge/SKILL.md`
Expected: matches in Read Project State, guided-mode, and directed-mode sections.

- [ ] **Step 6: Commit**

```bash
git add skills/forge/SKILL.md
git commit -m "Update forge skill: invoke status, route prose-tier + story-power (#267)"
git push
```

---

## Task 5: Wire `elaborate` skill with the pre-spine prose-tier stage

**Files:**
- Modify: `skills/elaborate/SKILL.md`

- [ ] **Step 1: Read the current pipeline + Step 5**

Run: `grep -n "spine\|Step 5\|Validate\|stage\|pipeline\|structural" skills/elaborate/SKILL.md`
Read the pipeline-overview block and the "Validate and Report" (Step 5) block so the new stage and the `--story-power` addition slot in correctly.

- [ ] **Step 2: Add the pre-spine prose-tier stage to the pipeline**

Before the spine stage in the pipeline description, add:

```markdown
### Stage 0 — Pitch / prose tier (before spine)

Before building the spine, solidify the pitch in `reference/story-summary.md`:
logline → synopsis → act-shape. This is the loop the story-power scorecard was
built for; skipping it means building structure on an unvalidated premise.

For each section, in order:
1. Develop/refine the section with the author (logline first, then synopsis,
   then act-shape).
2. `storyforge score --level 0|1|2` — deterministic floor check (length,
   presence, shape) for that section.
3. `storyforge score --story-power` — the 8-axis pitch-tier scorecard;
   pressure-tests specificity, emotional resonance, stakes, etc.
4. When exploring alternatives, `storyforge score --compare <a> <b> --level N`
   to compare candidate loglines/synopses side by side.

Advance to spine only when the prose tier reads `solid` in
`storyforge status` and the story-power scorecard is acceptable to the author.
```

- [ ] **Step 3: Add `--story-power` to Step 5 (Validate and Report)**

In the Step 5 block, alongside the existing `validate`/`--structural` mentions, add:

```markdown
- `storyforge score --story-power` — re-run the pitch-tier scorecard to
  confirm the structure still serves the premise after elaboration.
- `storyforge status` — confirm the ladder shows the expected rung as `solid`
  and surfaces no blockers before advancing.
```

- [ ] **Step 4: Verify the edits**

Run: `grep -n "prose tier\|story-power\|score --level\|storyforge status" skills/elaborate/SKILL.md`
Expected: matches in the pipeline (Stage 0) and Step 5 blocks.

- [ ] **Step 5: Commit**

```bash
git add skills/elaborate/SKILL.md
git commit -m "Update elaborate skill: pre-spine prose-tier stage + story-power in Step 5 (#267)"
git push
```

---

## Task 6: Docs, version bump, memory

**Files:**
- Modify: `CLAUDE.md`
- Modify: `.claude-plugin/plugin.json`
- Create: memory file under the project memory dir + `MEMORY.md` pointer

- [ ] **Step 1: Add `status` to the CLAUDE.md command table**

In the Commands table, add a row (keep the existing column format):

```markdown
| `storyforge status` | `cmd_status.py` | Deterministic next-step verdict — walks the elaboration ladder (L0–L6 floor checks), folds coverage/consistency into blockers, derives draft/evaluate rungs from scene status. `--json` for tooling (forge routes on `next.stage`). No LLM, read-only. |
```

Add to the Python-modules "Domain modules" table:

```markdown
| `status.py` | Next-step verdict: ladder-state walk, blockers, draft-state, recommendation mapping (backs `storyforge status`) |
```

- [ ] **Step 2: Bump the version**

Read `.claude-plugin/plugin.json`, then bump the `version` field's minor component (new feature). E.g. `1.44.1` → `1.45.0`.

Run: `grep '"version"' .claude-plugin/plugin.json`
Expected: shows the new minor version.

- [ ] **Step 3: Run the full suite to confirm nothing regressed**

Run: `python3 -m pytest tests/ -q`
Expected: all tests pass (including the new `tests/commands/test_status.py`).

- [ ] **Step 4: Write the memory file**

Create `/Users/cadencedev/.claude/projects/-Users-cadencedev-Developer-storyforge/memory/project_status_command.md`:

```markdown
---
name: project-status-command
description: storyforge status command — deterministic next-step verdict that forge/elaborate route on
metadata:
  type: project
---

`storyforge status` (added for #267) is the deterministic, no-LLM,
read-only next-step verdict. `status.py:build_status()` walks the
elaboration ladder (L0–L6 floor checks from [[project_elaboration_pipeline]]),
folds coverage/consistency into `blockers`, derives draft/evaluate rungs from
scene status, and emits `{phase, ladder, next, then, blockers}`. `--json`
exposes a stable `next.stage` enum that the `forge` skill routes on (rather
than inferring phase from prose). It recommends the LLM tools
(`score --story-power`, `--compare`) as next actions but never runs them.

**How to apply:** when adding a ladder rung or a scoring entry point, extend
`status.py`'s recommendation mapping and ladder walk so forge keeps routing
correctly.
```

Add a pointer line to `/Users/cadencedev/.claude/projects/-Users-cadencedev-Developer-storyforge/memory/MEMORY.md` under Project Overview or a suitable section:

```markdown
- [status command](project_status_command.md) — deterministic next-step verdict forge/elaborate route on
```

- [ ] **Step 5: Commit**

```bash
git add CLAUDE.md .claude-plugin/plugin.json
git commit -m "Bump version to 1.45.0 — storyforge status next-step verdict (#267)"
git push
```

(The memory files live outside the repo; they are not part of this commit.)

---

## Self-Review

**Spec coverage:**
- `storyforge status` command → Tasks 1–3. ✅
- Ladder model (first-incomplete-rung, floor-only state) → Task 1 `ladder_states`. ✅
- Verdict (phase, next, then, blockers, phase/yaml mismatch) → Task 2 `build_status`. ✅
- Human + `--json` output contract → Task 3 `render_human`/`main`. ✅
- Coaching-neutral command / posture in skill → command emits data only (Task 3); forge adapts (Task 4). ✅
- Recommends LLM tools without running them → Task 2 `_recommend`. ✅
- forge wiring (status-first, prose-tier/story-power/compare) → Task 4. ✅
- elaborate wiring (pre-spine stage, `--story-power` in Step 5) → Task 5. ✅
- Medium-aware → `get_medium` threaded through `build_status` (Tasks 2/3), asserted implicitly; add GN note in Task 1/2 tests if desired. ✅
- CLAUDE.md + version bump + memory → Task 6. ✅
- Testing plan (empty project, thin/missing/mismatch, phase mismatch, json schema) → Tasks 1–3 tests. ✅

**Placeholder scan:** No TBD/TODO; every code step shows complete code; every command shows expected output. ✅

**Type consistency:** `build_status` return keys (`phase`, `phase_declared`, `phase_matches_yaml`, `ladder`, `next`, `then`, `blockers`) are consistent across Tasks 2, 3, 4. `next`/`then` shape `{stage, action, command, reason}` consistent. `ladder` item shape `{level, name, state, detail}` consistent between Task 1 producer and Task 3 renderer. Blocker shape `{source, level, detail}` consistent between Task 2 producer and Task 3 renderer. ✅

**Note for implementer:** `cmd_status.main` references `detect_project_root`/`get_medium` as module globals so the Task 3 test can `monkeypatch` them — keep the top-level `from storyforge.common import detect_project_root, get_medium` import (do not inline-import inside `main`).
