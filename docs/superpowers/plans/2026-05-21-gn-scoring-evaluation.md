# GN Scoring and Lightweight Evaluation (Issue #209)

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development or superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Give graphic-novel authors actionable feedback on drafted scenes via deterministic craft scoring + a lightweight multi-evaluator panel. `cmd_revise_gn` is explicitly deferred to a followup once we have real-world scoring data to inform what revisions matter.

**Architecture:** Two new commands (`cmd_score_gn`, `cmd_evaluate_gn`) routed by the dispatcher. Six deterministic scorers in a single `scoring_gn.py` module (mirrors the novel-mode scoring modules but produces structured score dicts directly rather than the LLM pipeline). Three evaluator personas as markdown files. Existing `score` skill becomes medium-aware.

**Issue:** [#209](https://github.com/benjaminsnorris/storyforge/issues/209)

**v1 scope:** Score + lightweight evaluate. Revise deferred to followup (will be opened as a new issue at end).

---

## v1 Craft Principles (Deterministic)

Each principle runs without API calls, scoring panel scripts on objective signals:

| Principle | What it measures | Score formula |
|---|---|---|
| `brief_fidelity` | Does the script honor the brief contract? Wraps `script_format.check_brief_fidelity`. | 1.0 - (failures / total_checks), clamped to [0, 1] |
| `panel_density` | Average panels per page. Sweet spot 4-7. | 1.0 - (distance from 5.5) / 5.5, clamped |
| `dialogue_compression` | Word balloons ≤ 25 words. | Fraction of balloons under threshold |
| `layout_rhythm` | Variation in per-page panel counts. Too uniform = mechanical; too varied = chaotic. | Penalizes both extremes around stdev ≈ 1.5 |
| `caption_economy` | Captions per page. Strategy-aware: `minimal` expects ≤1, `journal-voiceover` expects ≤3, `none` expects 0, `omniscient` expects ≤4. | Fraction of pages within strategy's target |
| `panel_composition_depth` | Composition prose word count per panel. Sweet spot 15-50 words. | Fraction of panels in the sweet spot |

Each scorer returns `{principle, score, scene_id, findings: [...]}` where findings are actionable specifics (e.g., "Page 3 panel 4 has only 6 words of composition; artist needs more visual detail").

## v1 Evaluator Personas

Three markdown files, each containing the system prompt that turns Claude into that evaluator:

1. **panel-composition-critic.md** — Reads the script. Asks: does each panel give the artist enough? Are character/setting visuals consistent with the bibles? Where is composition too sparse to draw?

2. **pacing-critic.md** — Reads the script. Asks: does the page-to-page rhythm match the emotional arc? Are page-turn beats earned? Where does pacing falter (too many quiet pages in a row, no breathing room after action)?

3. **dialogue-critic.md** — Reads the script. Asks: are balloons compressed? Are character voices distinct? Does caption strategy actually appear consistent with what the brief specified?

Each evaluator outputs findings in the existing evaluation findings format (fix_location, severity, message, scene_id, page/panel anchor).

---

## File Structure

### Created

| Path | Purpose |
|---|---|
| `scripts/lib/python/storyforge/scoring_gn.py` | All 6 deterministic scorers in one module |
| `scripts/lib/python/storyforge/cmd_score_gn.py` | Orchestration: loads scenes, runs scorers, writes output |
| `scripts/lib/python/storyforge/cmd_evaluate_gn.py` | Orchestration: builds prompts per evaluator, invokes API, parses findings |
| `scripts/prompts/evaluators-gn/panel-composition-critic.md` | Persona prompt |
| `scripts/prompts/evaluators-gn/pacing-critic.md` | Persona prompt |
| `scripts/prompts/evaluators-gn/dialogue-critic.md` | Persona prompt |
| `references/default-craft-weights-gn.csv` | GN-specific weights (6 principles for v1) |
| `tests/test_scoring_gn.py` | Unit tests for the 6 deterministic scorers |
| `tests/test_cmd_score_gn.py` | End-to-end tests with the GN fixture |
| `tests/test_cmd_evaluate_gn.py` | End-to-end tests with API mocked |

### Modified

| Path | Change |
|---|---|
| `scripts/lib/python/storyforge/__main__.py` | Remove `score`, `evaluate` from `GN_UNSUPPORTED_COMMANDS`; add to `GN_ROUTED_COMMANDS` |
| `skills/score/SKILL.md` | Add medium-aware section for graphic-novel projects |
| `tests/wiring/test_cli_dispatch.py` | Update EXPECTED_COMMANDS if needed |
| `.claude-plugin/plugin.json` | Bump to 1.22.0 |
| `CLAUDE.md` | Move `score`, `evaluate` from "Not yet supported" to "Supported"; mention scoring_gn principles |

---

## Tasks

### Task 1: `scoring_gn.py` — six deterministic scorers

**Files:**
- Create: `scripts/lib/python/storyforge/scoring_gn.py`
- Create: `tests/test_scoring_gn.py`

Module structure (mirror the existing `scoring_passive.py`, `scoring_adverbs.py`, etc. pattern):

```python
"""Deterministic craft scorers for graphic-novel mode.

Each scorer takes a parsed script (via storyforge.script_format.parse_script)
and a brief row, then returns a structured score dict with findings.

Scorers expose `score_scene(parsed_script, brief_row, scene_id) -> dict` and
the module exposes a top-level `score_project(project_dir) -> dict` for the
dispatcher contract (returns {'skipped': True, 'reason': '...'} on errors,
otherwise a structured score dict).
"""

import statistics
from storyforge.script_format import parse_script, check_brief_fidelity
from storyforge.common import get_medium

PRINCIPLES = (
    'brief_fidelity', 'panel_density', 'dialogue_compression',
    'layout_rhythm', 'caption_economy', 'panel_composition_depth',
)


def score_brief_fidelity(parsed, brief_row, script_text):
    """1.0 - (failures / total_brief_checks). 4 checks: dialogue, visuals, panels, page-turns."""
    failures = check_brief_fidelity(brief_row, script_text)
    total_checks = 4  # 4 kinds of fidelity failures possible
    failure_count = len(failures)
    score = max(0.0, 1.0 - (failure_count / total_checks))
    findings = [
        {'kind': f['kind'], 'detail': f['detail'], 'severity': f.get('severity', 'medium')}
        for f in failures
    ]
    return {'principle': 'brief_fidelity', 'score': score, 'findings': findings}


def score_panel_density(parsed, brief_row=None, script_text=None):
    """Sweet spot: 4-7 panels per page. Score = 1.0 - (|avg - 5.5| / 5.5)."""
    pages = parsed['pages']
    if not pages:
        return {'principle': 'panel_density', 'score': 1.0, 'findings': []}
    densities = [len(p['panels']) for p in pages]
    avg = sum(densities) / len(densities)
    score = max(0.0, 1.0 - abs(avg - 5.5) / 5.5)
    findings = []
    for p in pages:
        n = len(p['panels'])
        if n > 9:
            findings.append({
                'kind': 'panel_density_high',
                'detail': f'Page {p["number"]}: {n} panels (cramped)',
                'severity': 'medium',
            })
        elif n == 0:
            findings.append({
                'kind': 'panel_density_zero',
                'detail': f'Page {p["number"]}: no panels parsed',
                'severity': 'high',
            })
    return {'principle': 'panel_density', 'score': score, 'findings': findings}


def score_dialogue_compression(parsed, brief_row=None, script_text=None):
    """Word balloons ≤ 25 words. Score = fraction under threshold."""
    MAX_WORDS = 25
    all_balloons = []
    for page in parsed['pages']:
        for panel in page['panels']:
            for d in panel['dialogue']:
                # Only count actual dialogue and captions — skip SFX
                if d['prefix'] in ('SFX',):
                    continue
                word_count = len(d['text'].split())
                all_balloons.append((page['number'], panel['number'],
                                     d['prefix'], word_count))
    if not all_balloons:
        return {'principle': 'dialogue_compression', 'score': 1.0, 'findings': []}
    under = sum(1 for _, _, _, w in all_balloons if w <= MAX_WORDS)
    score = under / len(all_balloons)
    findings = [
        {
            'kind': 'balloon_too_long',
            'detail': f'Page {pg} panel {pn} {pre}: {w} words (max {MAX_WORDS})',
            'severity': 'medium' if w <= 40 else 'high',
        }
        for pg, pn, pre, w in all_balloons if w > MAX_WORDS
    ]
    return {'principle': 'dialogue_compression', 'score': score, 'findings': findings}


def score_layout_rhythm(parsed, brief_row=None, script_text=None):
    """Stdev of panels-per-page. Penalize both extremes (≤ 0.3 = mechanical,
    ≥ 3.0 = chaotic). Sweet spot stdev ≈ 1.0-2.0."""
    pages = parsed['pages']
    if len(pages) < 2:
        return {'principle': 'layout_rhythm', 'score': 1.0, 'findings': []}
    densities = [len(p['panels']) for p in pages]
    stdev = statistics.stdev(densities)
    # Triangle scoring: peak at stdev=1.5, falls off either side
    if stdev <= 1.5:
        score = max(0.0, stdev / 1.5)
    else:
        score = max(0.0, 1.0 - (stdev - 1.5) / 2.0)
    findings = []
    if stdev <= 0.3:
        findings.append({
            'kind': 'layout_too_uniform',
            'detail': f'Panel-count stdev {stdev:.2f}: pages feel mechanically identical',
            'severity': 'medium',
        })
    if stdev >= 3.0:
        findings.append({
            'kind': 'layout_too_chaotic',
            'detail': f'Panel-count stdev {stdev:.2f}: wild variation may disorient',
            'severity': 'low',
        })
    return {'principle': 'layout_rhythm', 'score': score, 'findings': findings}


CAPTION_STRATEGY_TARGETS = {
    'minimal': 1,
    'journal-voiceover': 3,
    'journal voiceover': 3,
    'omniscient': 4,
    'omniscient narration': 4,
    'none': 0,
}


def score_caption_economy(parsed, brief_row, script_text=None):
    """Captions per page. Strategy-aware target."""
    strategy = (brief_row.get('caption_strategy') or 'minimal').strip().lower()
    target = CAPTION_STRATEGY_TARGETS.get(strategy, 2)
    pages = parsed['pages']
    if not pages:
        return {'principle': 'caption_economy', 'score': 1.0, 'findings': []}
    findings = []
    within = 0
    for page in pages:
        captions = [
            d for panel in page['panels'] for d in panel['dialogue']
            if d['prefix'] == 'CAPTION'
        ]
        cap_count = len(captions)
        # Allow exceeding target by 1; flag at +2
        if cap_count <= target + 1:
            within += 1
        else:
            findings.append({
                'kind': 'caption_excess',
                'detail': f'Page {page["number"]}: {cap_count} captions (strategy "{strategy}" suggests ≤ {target})',
                'severity': 'low' if cap_count <= target + 2 else 'medium',
            })
        # Strategy=none: any caption is a failure
        if strategy == 'none' and cap_count > 0:
            findings.append({
                'kind': 'caption_when_none',
                'detail': f'Page {page["number"]}: {cap_count} captions; strategy is "none"',
                'severity': 'high',
            })
            within = max(within - 1, 0)
    score = within / len(pages)
    return {'principle': 'caption_economy', 'score': score, 'findings': findings}


def score_panel_composition_depth(parsed, brief_row=None, script_text=None):
    """Composition prose word count. Sweet spot: 15-50 words per panel."""
    MIN_WORDS = 15
    MAX_WORDS = 50
    panels = [(page['number'], panel)
              for page in parsed['pages'] for panel in page['panels']]
    if not panels:
        return {'principle': 'panel_composition_depth', 'score': 1.0, 'findings': []}
    findings = []
    within = 0
    for page_num, panel in panels:
        w = len(panel['composition'].split())
        if MIN_WORDS <= w <= MAX_WORDS:
            within += 1
        elif w < MIN_WORDS:
            findings.append({
                'kind': 'composition_too_sparse',
                'detail': f'Page {page_num} panel {panel["number"]}: {w} words (artist needs more visual detail)',
                'severity': 'medium',
            })
        else:  # w > MAX_WORDS
            findings.append({
                'kind': 'composition_too_dense',
                'detail': f'Page {page_num} panel {panel["number"]}: {w} words (consider tightening)',
                'severity': 'low',
            })
    score = within / len(panels)
    return {'principle': 'panel_composition_depth', 'score': score, 'findings': findings}


SCORERS = {
    'brief_fidelity': score_brief_fidelity,
    'panel_density': score_panel_density,
    'dialogue_compression': score_dialogue_compression,
    'layout_rhythm': score_layout_rhythm,
    'caption_economy': score_caption_economy,
    'panel_composition_depth': score_panel_composition_depth,
}


def score_scene(scene_id, parsed_script, brief_row, script_text):
    """Run all scorers on one scene. Returns dict of principle → score+findings."""
    return {
        principle: fn(parsed_script, brief_row, script_text)
        for principle, fn in SCORERS.items()
    }


def score_project(project_dir):
    """Top-level entry — matches the contract used by novel-mode scorers."""
    if get_medium(project_dir) != 'graphic-novel':
        return {'skipped': True, 'reason': 'not a graphic-novel project'}
    # Actual scoring orchestration lives in cmd_score_gn — this is just the contract.
    return {'principles': list(PRINCIPLES)}
```

**Tests** (`tests/test_scoring_gn.py`):

- Test each scorer in isolation with crafted parsed_script + brief_row inputs that exercise:
  - All-pass case (score should be 1.0)
  - Boundary cases (just at threshold)
  - Failure case (score should drop and findings should appear)
- Test the `score_project()` entry contract (skipped for non-GN)

Aim for ~15 tests covering the six principles.

**Commit:** `Add scoring_gn module with six deterministic principles`

---

### Task 2: `cmd_score_gn.py` orchestration

**Files:**
- Create: `scripts/lib/python/storyforge/cmd_score_gn.py`
- Create: `tests/test_cmd_score_gn.py`

Same CLI surface as novel mode `cmd_score`:
```
storyforge score                      # score all drafted scenes
storyforge score scene-id             # score one scene
storyforge score --scenes a,b,c       # multiple scenes
storyforge score --principles X,Y     # only certain principles
storyforge score --dry-run            # show what would be scored
```

For each target scene:
1. Read `scenes/{id}.md`
2. Parse via `script_format.parse_script`
3. Read the brief row
4. Run `scoring_gn.score_scene(...)`
5. Write output to `working/scores/latest/{scene_id}.json` with the structure:
   ```json
   {
     "scene_id": "...",
     "scored_at": "2026-05-21T...",
     "scores": {
       "brief_fidelity": {"score": 0.75, "findings": [...]},
       ...
     },
     "overall_score": 0.82,  // weighted average using craft-weights-gn.csv
     "findings": [...]  // flat list across all principles
   }
   ```
6. After all scenes scored, write `working/scores/latest/summary.csv` with per-scene scores
7. Print a human-readable summary

Use the existing weights helpers in `storyforge.common` (look at `get_coaching_level` for the pattern; weights live in `working/craft-weights.csv` per project, with `references/default-craft-weights-gn.csv` as the default).

Refuse to run on non-GN projects with a clear error.

**Tests** (~5 tests): full-fixture scoring run produces expected output files; per-principle filter; dry-run no-op; non-GN refusal; scene without draft is skipped.

**Commit:** `Add cmd_score_gn for graphic-novel scoring`

---

### Task 3: `default-craft-weights-gn.csv`

**Files:**
- Create: `references/default-craft-weights-gn.csv`

Six rows in the same format as `default-craft-weights.csv`:

```
section|principle|weight|author_weight|notes
gn_craft|brief_fidelity|8||Brief contract is load-bearing
gn_craft|panel_density|5||Pacing-critical
gn_craft|dialogue_compression|6||Lettering reality check
gn_craft|layout_rhythm|5||Page-to-page variety
gn_craft|caption_economy|5||Strategy adherence
gn_craft|panel_composition_depth|6||Artist actionability
```

**Commit:** `Add default GN craft weights`

---

### Task 4: Evaluator persona markdown files

**Files:**
- Create: `scripts/prompts/evaluators-gn/panel-composition-critic.md`
- Create: `scripts/prompts/evaluators-gn/pacing-critic.md`
- Create: `scripts/prompts/evaluators-gn/dialogue-critic.md`

Each ~80-120 lines. Read the existing `scripts/prompts/evaluators/line-editor.md` and `developmental-editor.md` for format. Each file is a complete system-prompt persona that:
- Establishes the evaluator's domain expertise
- Defines what they look for (specific criteria for GN)
- Specifies output format: structured JSON findings with `severity`, `fix_location`, `message`, `scene_id`, optional `page`/`panel` anchor

Substantive guidance per persona:

**panel-composition-critic.md** — silhouette consistency, costume continuity, composition specificity (enough for the artist), visual storytelling (does the panel show what dialogue says — or compete with it?), location/setting fidelity. Outputs `fix_location: composition`.

**pacing-critic.md** — page-to-page rhythm, splash placement (earned vs. wasted), page-turn beat payoff, panel-to-panel transition variety (à la McCloud — moment/action/subject/scene/aspect), beat density vs. emotional arc. Outputs `fix_location: pacing` or `layout`.

**dialogue-critic.md** — balloon economy, character voice differentiation (do speakers sound distinct?), caption strategy alignment, SFX appropriateness, OFF-PANEL usage. Outputs `fix_location: dialogue`.

**Commit:** `Add three GN evaluator personas`

---

### Task 5: `cmd_evaluate_gn.py`

**Files:**
- Create: `scripts/lib/python/storyforge/cmd_evaluate_gn.py`
- Create: `tests/test_cmd_evaluate_gn.py`

Same CLI surface as novel mode `cmd_evaluate`:
```
storyforge evaluate                      # all drafted scenes
storyforge evaluate scene-id             # one scene
storyforge evaluate --scenes a,b,c
storyforge evaluate --personas A,B       # only specific evaluators
storyforge evaluate --dry-run
```

For each target scene:
1. Read `scenes/{id}.md`
2. Read brief, intent, scene metadata
3. For each evaluator persona (all 3 by default):
   a. Load persona system prompt from `scripts/prompts/evaluators-gn/{name}.md`
   b. Build user prompt: scene metadata + brief + script + visual references
   c. Invoke API via `api.invoke_to_file`
   d. Parse structured JSON findings from response
4. Aggregate findings into `working/evaluations/latest/{scene_id}.json`
5. Print summary

Mock-friendly: prompts/responses go through `api.invoke_to_file` so they can be stubbed in tests.

Refuse non-GN projects.

**Tests** (~4 tests): full-fixture eval with mocked API, single-evaluator filter, dry-run, non-GN refusal.

**Commit:** `Add cmd_evaluate_gn for graphic-novel evaluation panel`

---

### Task 6: Dispatcher routing

**Files:**
- Modify: `scripts/lib/python/storyforge/__main__.py`
- Modify: `tests/test_medium.py`

Remove `'score'` and `'evaluate'` from `GN_UNSUPPORTED_COMMANDS`.

Add to `GN_ROUTED_COMMANDS`:
```python
GN_ROUTED_COMMANDS = {
    'write': 'storyforge.cmd_write_gn',
    'assemble': 'storyforge.cmd_script_package',
    'score': 'storyforge.cmd_score_gn',
    'evaluate': 'storyforge.cmd_evaluate_gn',
}
```

Update `test_dispatcher_blocks_unsupported_commands_in_gn_mode` parametrize: remove `'score'`, `'evaluate'`.

Add `test_dispatcher_routes_score_to_gn_in_gn_mode` and `test_dispatcher_routes_evaluate_to_gn_in_gn_mode` mirroring the write/assemble routing tests.

**Commit:** `Route score and evaluate to GN modules when medium is graphic-novel`

---

### Task 7: Skill update

**Files:**
- Modify: `skills/score/SKILL.md`

Add a `## Graphic-novel mode` section explaining:
- The 6 GN-specific principles (vs. novel's 25)
- All principles are deterministic (no API calls; scoring is fast)
- Where output lives (`working/scores/latest/`)
- That `evaluate` complements scoring with multi-agent commentary

**Commit:** `Update score skill with graphic-novel section`

---

### Task 8: Version, CLAUDE.md, PR

**Files:**
- Modify: `.claude-plugin/plugin.json` — bump 1.21.0 → 1.22.0
- Modify: `CLAUDE.md` — move `score`, `evaluate` from "Not yet supported" to "Supported"; mention scoring_gn principles

Open draft PR closing #209 (partial — note revise is deferred and create new followup issue).

**Commit:** `Bump version to 1.22.0; document GN scoring and evaluation`

---

## Self-Review

- Coverage: every part of issue #209's v1-scope (score + evaluate, not revise) has a task
- Type/name consistency: `score_scene` returns dict; scorers expose `(parsed, brief_row, script_text)` signature uniformly; findings have `kind`/`detail`/`severity`
- Sequencing: Tasks 1-3 must land before 2 (cmd_score_gn imports scoring_gn); Tasks 4 before 5; Task 6 needs both commands; Tasks 7-8 last
- Followup issue: open a new issue at end for `cmd_revise_gn` with notes on what scoring/evaluation produced (so the revise design has real data)
