# Deterministic Findings Guidance Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Persist detailed findings from deterministic scorers to CSV files, then feed those findings into `--scores` revision plan guidance as manuscript-wide patterns + per-scene specifics.

**Architecture:** Two changes to the scoring pipeline (`_score_repetition` writes `repetition-findings.csv`, `_score_single_principle` writes `scene-findings.csv`), then two new functions in `cmd_revise.py` (`_load_findings`, `_build_findings_guidance`) wired into the existing `_generate_scores_plan` and `_generate_targeted_polish_plan`.

**Tech Stack:** Python, pipe-delimited CSV, existing `storyforge` scorer modules.

---

## File Structure

| File | Change |
|------|--------|
| `scripts/lib/python/storyforge/cmd_score.py` | Modify `_score_repetition` and `_score_single_principle` to write findings files |
| `scripts/lib/python/storyforge/cmd_revise.py` | Add `_load_findings`, `_build_findings_guidance`, wire into plan generators |
| `tests/test_findings_persistence.py` | Tests for findings file writing |
| `tests/test_findings_guidance.py` | Tests for guidance generation from findings |

---

### Task 1: Persist repetition findings in `_score_repetition`

After `scan_manuscript` returns the full findings list, write it to `repetition-findings.csv` in the cycle directory.

**Files:**
- Modify: `scripts/lib/python/storyforge/cmd_score.py:493-512` (`_score_repetition`)
- Create: `tests/test_findings_persistence.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/test_findings_persistence.py
"""Tests for deterministic scorer findings persistence."""

import os
import csv
import pytest


class TestRepetitionFindings:
    def _setup_project(self, tmp_path):
        """Create a minimal project with scenes that have repeated phrases."""
        project_dir = str(tmp_path / 'project')
        scenes_dir = os.path.join(project_dir, 'scenes')
        ref_dir = os.path.join(project_dir, 'reference')
        os.makedirs(scenes_dir)
        os.makedirs(ref_dir)

        with open(os.path.join(ref_dir, 'scenes.csv'), 'w') as f:
            f.write('id|seq|title|part|pov|status|word_count|target_words\n')
            f.write('s01|1|Scene 1|1|Alice|drafted|100|1000\n')
            f.write('s02|2|Scene 2|1|Bob|drafted|100|1000\n')
            f.write('s03|3|Scene 3|1|Alice|drafted|100|1000\n')

        # Create scenes with repeated phrases across them
        with open(os.path.join(scenes_dir, 's01.md'), 'w') as f:
            f.write('Alice stood at the edge of the garden. She looked at the flowers. '
                    'The dog put her chin on her paws and watched. '
                    'Alice could feel the warmth of the sun on her face.\n')
        with open(os.path.join(scenes_dir, 's02.md'), 'w') as f:
            f.write('Bob walked to the edge of the yard. He looked at the house. '
                    'The dog put her chin on her paws again. '
                    'He could feel the cold of the night air.\n')
        with open(os.path.join(scenes_dir, 's03.md'), 'w') as f:
            f.write('They met at the edge of the road. She looked at him. '
                    'The dog lifted her chin on her paws. '
                    'She could feel the tension in the room.\n')

        with open(os.path.join(project_dir, 'storyforge.yaml'), 'w') as f:
            f.write('project:\n  title: Test\n')

        return project_dir

    def test_writes_repetition_findings_csv(self, tmp_path):
        from storyforge.cmd_score import _score_repetition

        project_dir = self._setup_project(tmp_path)
        cycle_dir = str(tmp_path / 'cycle-1')
        os.makedirs(cycle_dir)

        _score_repetition(['s01', 's02', 's03'], project_dir, cycle_dir)

        findings_path = os.path.join(cycle_dir, 'repetition-findings.csv')
        assert os.path.isfile(findings_path)

        with open(findings_path) as f:
            content = f.read()
        assert 'phrase|category|severity|count|scene_ids' in content
        # Should have at least one repeated phrase
        lines = content.strip().split('\n')
        assert len(lines) >= 2  # header + at least one finding

    def test_findings_contain_phrase_and_scenes(self, tmp_path):
        from storyforge.cmd_score import _score_repetition

        project_dir = self._setup_project(tmp_path)
        cycle_dir = str(tmp_path / 'cycle-1')
        os.makedirs(cycle_dir)

        _score_repetition(['s01', 's02', 's03'], project_dir, cycle_dir)

        findings_path = os.path.join(cycle_dir, 'repetition-findings.csv')
        with open(findings_path, newline='', encoding='utf-8') as f:
            reader = csv.DictReader(f, delimiter='|')
            rows = list(reader)

        # At least one finding should have multiple scenes
        multi_scene = [r for r in rows if ';' in r.get('scene_ids', '')]
        assert len(multi_scene) >= 1

        # Each row should have required fields
        for row in rows:
            assert row.get('phrase')
            assert row.get('category')
            assert row.get('severity') in ('high', 'medium')
            assert int(row.get('count', '0')) >= 2

    def test_scores_csv_still_written(self, tmp_path):
        """Findings persistence should not break existing score output."""
        from storyforge.cmd_score import _score_repetition

        project_dir = self._setup_project(tmp_path)
        cycle_dir = str(tmp_path / 'cycle-1')
        os.makedirs(cycle_dir)

        scores_path = _score_repetition(['s01', 's02', 's03'], project_dir, cycle_dir)
        assert os.path.isfile(scores_path)
        with open(scores_path) as f:
            content = f.read()
        assert 'id|prose_repetition' in content
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python3 -m pytest tests/test_findings_persistence.py::TestRepetitionFindings -v`
Expected: FAIL — no `repetition-findings.csv` written

- [ ] **Step 3: Implement findings persistence in `_score_repetition`**

In `scripts/lib/python/storyforge/cmd_score.py`, modify `_score_repetition` (line 493). After the `rep_findings = scan_manuscript(...)` call (line 498), add the findings file write before the scores loop:

```python
def _score_repetition(scene_ids, project_dir, cycle_dir):
    """Run deterministic repetition scoring. Returns path to scores CSV."""
    from storyforge.repetition import scan_manuscript, score_scene_repetition

    log('Running repetition scan...')
    rep_findings = scan_manuscript(project_dir, scene_ids=scene_ids)
    rep_high = sum(1 for f in rep_findings if f['severity'] == 'high')
    log(f'Repetition scan: {len(rep_findings)} findings ({rep_high} high-severity)')

    # Persist findings for revision guidance
    findings_path = os.path.join(cycle_dir, 'repetition-findings.csv')
    with open(findings_path, 'w', encoding='utf-8') as f:
        f.write('phrase|category|severity|count|scene_ids\n')
        for finding in rep_findings:
            phrase = finding['phrase']
            category = finding['category']
            severity = finding['severity']
            count = finding['count']
            sids = ';'.join(finding['scene_ids'])
            f.write(f'{phrase}|{category}|{severity}|{count}|{sids}\n')
    log(f'Repetition findings: {findings_path} ({len(rep_findings)} entries)')

    rep_scores_path = os.path.join(cycle_dir, 'repetition-latest.csv')
    with open(rep_scores_path, 'w', encoding='utf-8') as f:
        f.write('id|prose_repetition\n')
        for sid in scene_ids:
            markers = score_scene_repetition(sid, rep_findings)
            active = sum(markers[k] for k in ('pr-1', 'pr-2', 'pr-3', 'pr-4'))
            prose_rep_score = max(1, 5 - active)
            f.write(f'{sid}|{prose_rep_score}\n')

    log(f'Repetition scores: {rep_scores_path}')
    return rep_scores_path
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `python3 -m pytest tests/test_findings_persistence.py::TestRepetitionFindings -v`
Expected: 3 passed

- [ ] **Step 5: Commit**

```bash
git add scripts/lib/python/storyforge/cmd_score.py tests/test_findings_persistence.py
git commit -m "Persist repetition findings to CSV for revision guidance"
git push
```

---

### Task 2: Persist per-scene findings in `_score_single_principle`

Modify the generic scorer wrapper to collect `details` strings from each scorer and write them to `scene-findings.csv`.

**Files:**
- Modify: `scripts/lib/python/storyforge/cmd_score.py:527-546` (`_score_single_principle`)
- Modify: `tests/test_findings_persistence.py`

- [ ] **Step 1: Write the failing tests**

Add to `tests/test_findings_persistence.py`:

```python
class TestSceneFindings:
    def _setup_project(self, tmp_path):
        project_dir = str(tmp_path / 'project')
        scenes_dir = os.path.join(project_dir, 'scenes')
        ref_dir = os.path.join(project_dir, 'reference')
        os.makedirs(scenes_dir)
        os.makedirs(ref_dir)

        with open(os.path.join(ref_dir, 'scenes.csv'), 'w') as f:
            f.write('id|seq|title|part|pov|status|word_count|target_words\n')
            f.write('s01|1|Scene 1|1|Alice|drafted|200|1000\n')

        # Scene with passive voice clusters and adverb issues
        with open(os.path.join(scenes_dir, 's01.md'), 'w') as f:
            f.write('The door was opened by Alice. The room was filled with smoke. '
                    'The window was broken by the wind. The floor was covered in glass. '
                    'She walked slowly and carefully through the debris. '
                    'He said quietly that the building was being evacuated. '
                    'She nodded reluctantly and moved cautiously toward the exit.\n')

        with open(os.path.join(project_dir, 'storyforge.yaml'), 'w') as f:
            f.write('project:\n  title: Test\n')

        return project_dir

    def test_writes_scene_findings_csv(self, tmp_path):
        from storyforge.cmd_score import _score_passive

        project_dir = self._setup_project(tmp_path)
        cycle_dir = str(tmp_path / 'cycle-1')
        os.makedirs(cycle_dir)

        _score_passive(['s01'], project_dir, cycle_dir)

        findings_path = os.path.join(cycle_dir, 'scene-findings.csv')
        assert os.path.isfile(findings_path)

        with open(findings_path) as f:
            content = f.read()
        assert 'scene_id|principle|finding|detail' in content

    def test_multiple_scorers_append_to_same_file(self, tmp_path):
        from storyforge.cmd_score import _score_passive, _score_adverbs

        project_dir = self._setup_project(tmp_path)
        cycle_dir = str(tmp_path / 'cycle-1')
        os.makedirs(cycle_dir)

        _score_passive(['s01'], project_dir, cycle_dir)
        _score_adverbs(['s01'], project_dir, cycle_dir)

        findings_path = os.path.join(cycle_dir, 'scene-findings.csv')
        with open(findings_path, newline='', encoding='utf-8') as f:
            reader = csv.DictReader(f, delimiter='|')
            rows = list(reader)

        principles = set(r['principle'] for r in rows)
        assert 'avoid_passive' in principles
        assert 'avoid_adverbs' in principles

    def test_only_scenes_with_findings_written(self, tmp_path):
        """Scenes that score 5 (no issues) should not appear in findings."""
        from storyforge.cmd_score import _score_weather

        project_dir = self._setup_project(tmp_path)
        cycle_dir = str(tmp_path / 'cycle-1')
        os.makedirs(cycle_dir)

        # The test scene doesn't start with weather/dream/waking
        _score_weather(['s01'], project_dir, cycle_dir)

        findings_path = os.path.join(cycle_dir, 'scene-findings.csv')
        if os.path.isfile(findings_path):
            with open(findings_path, newline='', encoding='utf-8') as f:
                reader = csv.DictReader(f, delimiter='|')
                weather_rows = [r for r in reader if r['principle'] == 'no_weather_dreams']
            assert len(weather_rows) == 0

    def test_scores_csv_still_written(self, tmp_path):
        """Findings persistence should not break existing score output."""
        from storyforge.cmd_score import _score_passive

        project_dir = self._setup_project(tmp_path)
        cycle_dir = str(tmp_path / 'cycle-1')
        os.makedirs(cycle_dir)

        scores_path = _score_passive(['s01'], project_dir, cycle_dir)
        assert os.path.isfile(scores_path)
        with open(scores_path) as f:
            content = f.read()
        assert 'id|avoid_passive' in content
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python3 -m pytest tests/test_findings_persistence.py::TestSceneFindings -v`
Expected: FAIL — no `scene-findings.csv` written

- [ ] **Step 3: Implement findings persistence in `_score_single_principle`**

Modify `_score_single_principle` in `cmd_score.py` (line 527) to collect and write findings:

```python
def _score_single_principle(scene_ids, project_dir, cycle_dir,
                            principle, scorer_fn):
    """Generic scorer for single-scene deterministic principles.

    scorer_fn(text) -> {'score': int, 'markers': dict, 'details': str}
    Returns path to the scores CSV. Also appends findings to scene-findings.csv.
    """
    scene_texts = _load_scene_texts(scene_ids, project_dir)

    log(f'Running {principle} scorer...')
    scores_path = os.path.join(cycle_dir, f'{principle}-latest.csv')
    findings_path = os.path.join(cycle_dir, 'scene-findings.csv')

    # Check if findings file needs a header
    write_header = not os.path.isfile(findings_path)

    findings_rows = []
    with open(scores_path, 'w', encoding='utf-8') as f:
        f.write(f'id|{principle}\n')
        for sid in scene_ids:
            text = scene_texts.get(sid, '')
            result = scorer_fn(text)
            f.write(f'{sid}|{result["score"]}\n')

            # Collect findings for scenes with issues (score < 5)
            if result['score'] < 5 and result.get('details'):
                # Parse markers to determine finding types
                for marker_name, marker_val in result.get('markers', {}).items():
                    if marker_val:
                        findings_rows.append({
                            'scene_id': sid,
                            'principle': principle,
                            'finding': marker_name,
                            'detail': result['details'],
                        })
                        break  # One row per scene per principle (details covers all markers)

    # Append findings to shared file
    if findings_rows:
        with open(findings_path, 'a', encoding='utf-8') as f:
            if write_header:
                f.write('scene_id|principle|finding|detail\n')
            for row in findings_rows:
                detail = row['detail'].replace('|', ',').replace('\n', ' ')
                f.write(f'{row["scene_id"]}|{row["principle"]}|{row["finding"]}|{detail}\n')

    log(f'{principle} scores: {scores_path}')
    return scores_path
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `python3 -m pytest tests/test_findings_persistence.py -v`
Expected: All passed (both TestRepetitionFindings and TestSceneFindings)

- [ ] **Step 5: Run full test suite to check for regressions**

Run: `python3 -m pytest tests/ --tb=short`
Expected: No regressions

- [ ] **Step 6: Commit**

```bash
git add scripts/lib/python/storyforge/cmd_score.py tests/test_findings_persistence.py
git commit -m "Persist per-scene deterministic findings to scene-findings.csv"
git push
```

---

### Task 3: Add `_load_findings` and `_build_findings_guidance` to cmd_revise.py

Read findings files and construct two-layer guidance (manuscript-wide + per-scene).

**Files:**
- Modify: `scripts/lib/python/storyforge/cmd_revise.py`
- Create: `tests/test_findings_guidance.py`

- [ ] **Step 1: Write the failing tests**

```python
# tests/test_findings_guidance.py
"""Tests for findings-based revision guidance generation."""

import os
import pytest


class TestLoadFindings:
    def test_loads_repetition_findings(self, tmp_path):
        from storyforge.cmd_revise import _load_findings

        cycle_dir = str(tmp_path)
        with open(os.path.join(cycle_dir, 'repetition-findings.csv'), 'w') as f:
            f.write('phrase|category|severity|count|scene_ids\n')
            f.write('the edge of the|signature_phrase|high|21|s01;s02;s03\n')
            f.write('chin on her paws|character_tell|high|16|s01;s04;s05\n')

        findings = _load_findings(cycle_dir)
        assert len(findings['repetition']) == 2
        assert findings['repetition'][0]['phrase'] == 'the edge of the'
        assert findings['repetition'][0]['count'] == 21

    def test_loads_scene_findings(self, tmp_path):
        from storyforge.cmd_revise import _load_findings

        cycle_dir = str(tmp_path)
        with open(os.path.join(cycle_dir, 'scene-findings.csv'), 'w') as f:
            f.write('scene_id|principle|finding|detail\n')
            f.write('s01|avoid_passive|ap-1|5/20 passive sentences (25%), cluster=True\n')
            f.write('s01|avoid_adverbs|aa-1|3 adverb issues (2.1/1000 words)\n')
            f.write('s02|economy_clarity|ec-1|filler 4.2/1000 words\n')

        findings = _load_findings(cycle_dir)
        assert 's01' in findings['scenes']
        assert len(findings['scenes']['s01']) == 2
        assert findings['scenes']['s01'][0]['principle'] == 'avoid_passive'

    def test_missing_files_return_empty(self, tmp_path):
        from storyforge.cmd_revise import _load_findings

        findings = _load_findings(str(tmp_path))
        assert findings['repetition'] == []
        assert findings['scenes'] == {}


class TestBuildFindingsGuidance:
    def test_manuscript_preamble_from_repetition(self):
        from storyforge.cmd_revise import _build_findings_guidance

        findings = {
            'repetition': [
                {'phrase': 'the edge of the', 'category': 'signature_phrase',
                 'severity': 'high', 'count': 21, 'scene_ids': ['s01', 's02', 's03']},
                {'phrase': 'chin on her paws', 'category': 'character_tell',
                 'severity': 'high', 'count': 16, 'scene_ids': ['s01', 's04']},
            ],
            'scenes': {},
        }

        guidance = _build_findings_guidance(findings, target_scenes=['s01', 's02'])
        assert 'the edge of the' in guidance
        assert '21' in guidance
        assert 'reduce' in guidance.lower()
        assert 'eliminate' not in guidance.lower()

    def test_per_scene_specifics(self):
        from storyforge.cmd_revise import _build_findings_guidance

        findings = {
            'repetition': [],
            'scenes': {
                's01': [
                    {'principle': 'avoid_passive', 'finding': 'ap-1',
                     'detail': '5/20 passive sentences (25%), cluster=True'},
                    {'principle': 'avoid_adverbs', 'finding': 'aa-1',
                     'detail': '3 adverb issues'},
                ],
                's02': [
                    {'principle': 'economy_clarity', 'finding': 'ec-1',
                     'detail': 'filler 4.2/1000 words'},
                ],
            },
        }

        guidance = _build_findings_guidance(findings, target_scenes=['s01', 's02'])
        assert 's01' in guidance
        assert 'passive' in guidance.lower()
        assert 's02' in guidance
        assert 'filler' in guidance.lower()

    def test_only_target_scenes_included(self):
        from storyforge.cmd_revise import _build_findings_guidance

        findings = {
            'repetition': [],
            'scenes': {
                's01': [{'principle': 'avoid_passive', 'finding': 'ap-1',
                         'detail': 'passive cluster'}],
                's99': [{'principle': 'avoid_passive', 'finding': 'ap-1',
                         'detail': 'should not appear'}],
            },
        }

        guidance = _build_findings_guidance(findings, target_scenes=['s01'])
        assert 's01' in guidance
        assert 's99' not in guidance

    def test_empty_findings_returns_empty_string(self):
        from storyforge.cmd_revise import _build_findings_guidance

        findings = {'repetition': [], 'scenes': {}}
        guidance = _build_findings_guidance(findings, target_scenes=['s01'])
        assert guidance == ''

    def test_repetition_target_count(self):
        """Target occurrences should be count/5, minimum 2."""
        from storyforge.cmd_revise import _build_findings_guidance

        findings = {
            'repetition': [
                {'phrase': 'common phrase', 'category': 'signature_phrase',
                 'severity': 'high', 'count': 10, 'scene_ids': ['s01']},
                {'phrase': 'rare phrase', 'category': 'signature_phrase',
                 'severity': 'medium', 'count': 3, 'scene_ids': ['s01']},
            ],
            'scenes': {},
        }

        guidance = _build_findings_guidance(findings, target_scenes=['s01'])
        # count=10 -> target 2, count=3 -> target 2 (minimum)
        assert 'reduce to 2' in guidance.lower()

    def test_limits_to_top_10_repetitions(self):
        from storyforge.cmd_revise import _build_findings_guidance

        findings = {
            'repetition': [
                {'phrase': f'phrase {i}', 'category': 'signature_phrase',
                 'severity': 'high', 'count': 20 - i, 'scene_ids': ['s01']}
                for i in range(15)
            ],
            'scenes': {},
        }

        guidance = _build_findings_guidance(findings, target_scenes=['s01'])
        # Should only include top 10
        assert 'phrase 0' in guidance
        assert 'phrase 9' in guidance
        assert 'phrase 10' not in guidance

    def test_limits_to_top_5_findings_per_scene(self):
        from storyforge.cmd_revise import _build_findings_guidance

        findings = {
            'repetition': [],
            'scenes': {
                's01': [
                    {'principle': f'principle_{i}', 'finding': f'f{i}',
                     'detail': f'detail {i}'}
                    for i in range(8)
                ],
            },
        }

        guidance = _build_findings_guidance(findings, target_scenes=['s01'])
        # Should have at most 5 details for s01
        assert 'detail 0' in guidance
        assert 'detail 4' in guidance
        assert 'detail 5' not in guidance
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python3 -m pytest tests/test_findings_guidance.py -v`
Expected: FAIL — functions don't exist

- [ ] **Step 3: Implement `_load_findings`**

Add to `cmd_revise.py` after `_format_scores_table` (around line 505):

```python
def _load_findings(cycle_dir: str) -> dict:
    """Load deterministic scorer findings from a scoring cycle directory.

    Returns dict with 'repetition' (list of finding dicts) and
    'scenes' (dict mapping scene_id to list of finding dicts).
    """
    result = {'repetition': [], 'scenes': {}}

    # Load repetition findings (manuscript-wide)
    rep_path = os.path.join(cycle_dir, 'repetition-findings.csv')
    if os.path.isfile(rep_path):
        with open(rep_path, newline='', encoding='utf-8') as f:
            raw = f.read().replace('\r\n', '\n').replace('\r', '')
        reader = csv.DictReader(raw.splitlines(), delimiter='|')
        for row in reader:
            result['repetition'].append({
                'phrase': row.get('phrase', ''),
                'category': row.get('category', ''),
                'severity': row.get('severity', ''),
                'count': int(row.get('count', '0')),
                'scene_ids': row.get('scene_ids', '').split(';'),
            })

    # Load per-scene findings
    scene_path = os.path.join(cycle_dir, 'scene-findings.csv')
    if os.path.isfile(scene_path):
        with open(scene_path, newline='', encoding='utf-8') as f:
            raw = f.read().replace('\r\n', '\n').replace('\r', '')
        reader = csv.DictReader(raw.splitlines(), delimiter='|')
        for row in reader:
            sid = row.get('scene_id', '').strip()
            if sid:
                result['scenes'].setdefault(sid, []).append({
                    'principle': row.get('principle', ''),
                    'finding': row.get('finding', ''),
                    'detail': row.get('detail', ''),
                })

    return result
```

- [ ] **Step 4: Implement `_build_findings_guidance`**

Add after `_load_findings`:

```python
def _build_findings_guidance(findings: dict, target_scenes: list[str]) -> str:
    """Build two-layer guidance from deterministic scorer findings.

    Layer 1: Manuscript-wide repetition patterns (top 10, frequency-aware).
    Layer 2: Per-scene specifics for target scenes (top 5 per scene).
    """
    parts = []

    # Layer 1: Manuscript-wide repetition preamble
    rep = findings.get('repetition', [])
    if rep:
        # Sort by count descending, take top 10
        top_rep = sorted(rep, key=lambda r: -r['count'])[:10]
        lines = ['Cross-scene repetition patterns (reduce frequency, do not eliminate):']
        for r in top_rep:
            target = max(2, r['count'] // 5)
            lines.append(f'  - "{r["phrase"]}" ({r["count"]}x, {r["category"]}) '
                         f'— reduce to {target} occurrences')
        parts.append('\n'.join(lines))

    # Layer 2: Per-scene specifics
    scene_findings = findings.get('scenes', {})
    scene_lines = []
    for sid in target_scenes:
        if sid not in scene_findings:
            continue
        scene_hits = scene_findings[sid][:5]  # Top 5 per scene
        if not scene_hits:
            continue
        details = '; '.join(f'{h["principle"]}: {h["detail"]}' for h in scene_hits)
        scene_lines.append(f'  {sid}: {details}')

    if scene_lines:
        parts.append('Scene-specific findings:\n' + '\n'.join(scene_lines))

    return '\n\n'.join(parts)
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `python3 -m pytest tests/test_findings_guidance.py -v`
Expected: All passed

- [ ] **Step 6: Commit**

```bash
git add scripts/lib/python/storyforge/cmd_revise.py tests/test_findings_guidance.py
git commit -m "Add _load_findings and _build_findings_guidance for revision planning"
git push
```

---

### Task 4: Wire findings guidance into plan generators

Inject findings-based guidance into `_generate_scores_plan` and `_generate_targeted_polish_plan`.

**Files:**
- Modify: `scripts/lib/python/storyforge/cmd_revise.py` (`_generate_scores_plan` and `_generate_targeted_polish_plan`)
- Modify: `tests/test_findings_guidance.py`

- [ ] **Step 1: Write the failing tests**

Add to `tests/test_findings_guidance.py`:

```python
class TestScoresPlanWithFindings:
    def test_scores_plan_includes_repetition_guidance(self, tmp_path):
        from storyforge.cmd_revise import _generate_scores_plan

        plan_file = str(tmp_path / 'revision-plan.csv')

        # Create findings files in a fake "latest" dir
        latest_dir = str(tmp_path / 'latest')
        os.makedirs(latest_dir)
        with open(os.path.join(latest_dir, 'repetition-findings.csv'), 'w') as f:
            f.write('phrase|category|severity|count|scene_ids\n')
            f.write('the edge of|signature_phrase|high|15|s01;s02;s03\n')

        diag_rows = [
            {'principle': 'prose_naturalness', 'scale': 'scene', 'avg_score': '2.1',
             'worst_items': 's01;s02', 'priority': 'high', 'root_cause': 'brief'},
        ]

        rows = _generate_scores_plan(plan_file, diag_rows, findings_dir=latest_dir)
        assert len(rows) >= 1
        # Guidance should include repetition findings
        all_guidance = ' '.join(r['guidance'] for r in rows)
        assert 'the edge of' in all_guidance
        assert 'reduce' in all_guidance.lower()

    def test_scores_plan_includes_scene_findings(self, tmp_path):
        from storyforge.cmd_revise import _generate_scores_plan

        plan_file = str(tmp_path / 'revision-plan.csv')

        latest_dir = str(tmp_path / 'latest')
        os.makedirs(latest_dir)
        with open(os.path.join(latest_dir, 'scene-findings.csv'), 'w') as f:
            f.write('scene_id|principle|finding|detail\n')
            f.write('s01|avoid_passive|ap-1|passive cluster (25%)\n')

        diag_rows = [
            {'principle': 'avoid_passive', 'scale': 'scene', 'avg_score': '2.0',
             'worst_items': 's01', 'priority': 'high', 'root_cause': 'craft'},
        ]

        rows = _generate_scores_plan(plan_file, diag_rows, findings_dir=latest_dir)
        craft_passes = [r for r in rows if r['fix_location'] == 'craft']
        assert len(craft_passes) >= 1
        assert 'passive cluster' in craft_passes[0]['guidance']

    def test_scores_plan_works_without_findings(self, tmp_path):
        """Plan generation should still work when no findings files exist."""
        from storyforge.cmd_revise import _generate_scores_plan

        plan_file = str(tmp_path / 'revision-plan.csv')
        diag_rows = [
            {'principle': 'prose_naturalness', 'scale': 'scene', 'avg_score': '2.1',
             'worst_items': 's01', 'priority': 'high', 'root_cause': 'brief'},
        ]

        rows = _generate_scores_plan(plan_file, diag_rows, findings_dir=str(tmp_path))
        assert len(rows) >= 1  # Should still generate a plan
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python3 -m pytest tests/test_findings_guidance.py::TestScoresPlanWithFindings -v`
Expected: FAIL — `_generate_scores_plan` doesn't accept `findings_dir` parameter

- [ ] **Step 3: Add `findings_dir` parameter to `_generate_scores_plan`**

Modify `_generate_scores_plan` signature to accept an optional `findings_dir`:

```python
def _generate_scores_plan(plan_file: str, diag_rows: list[dict],
                          findings_dir: str = '') -> list[dict]:
```

At the start of the function, after the existing `actionable` filter, load findings and build guidance:

```python
    # Load deterministic findings for enhanced guidance
    findings_guidance = ''
    if findings_dir:
        findings = _load_findings(findings_dir)
        target_scenes = set()
        for item in actionable:
            for sid in item['worst_items'].split(';'):
                sid = sid.strip()
                if sid:
                    target_scenes.add(sid)
        findings_guidance = _build_findings_guidance(findings, sorted(target_scenes))
```

Then append `findings_guidance` to the `guidance` field of each generated pass. For the brief pass, after the existing guidance string:

```python
        if findings_guidance:
            guidance += '\n\n' + findings_guidance
```

Same for the craft pass guidance.

- [ ] **Step 4: Update the `--scores` wiring in `main()` to pass `findings_dir`**

In `main()`, in the `elif args.scores:` block, after reading diagnosis, pass the findings directory:

```python
    elif args.scores:
        log('Scores mode -- generating revision plan from diagnosis data...')
        diag_file = os.path.join(project_dir, 'working', 'scores', 'latest', 'diagnosis.csv')
        if not os.path.isfile(diag_file):
            log(f'ERROR: No diagnosis found at {diag_file}')
            log('Run: storyforge score first')
            sys.exit(1)
        diag_rows = _read_diagnosis(os.path.dirname(diag_file))
        findings_dir = os.path.dirname(diag_file)  # same as latest cycle dir
        plan_rows = _generate_scores_plan(csv_plan_file, diag_rows,
                                          findings_dir=findings_dir)
        if not plan_rows:
            log('No actionable items in diagnosis — nothing to revise')
            sys.exit(0)
```

- [ ] **Step 5: Also wire into `_generate_targeted_polish_plan`**

Add `findings_dir` parameter to `_generate_targeted_polish_plan` with the same pattern:

```python
def _generate_targeted_polish_plan(plan_file: str, diag_rows: list[dict],
                                   findings_dir: str = '') -> list[dict]:
```

Load findings at the start, append to guidance. Update callers in `_run_polish_loop` to pass `findings_dir`:

In `_run_polish_loop`, the call at the line `plan_rows = _generate_targeted_polish_plan(csv_plan_file, latest_diag)` becomes:

```python
        latest_cycle = os.path.join(project_dir, 'working', 'scores', 'latest')
        plan_rows = _generate_targeted_polish_plan(csv_plan_file, latest_diag,
                                                    findings_dir=latest_cycle)
```

- [ ] **Step 6: Run all tests**

Run: `python3 -m pytest tests/test_findings_guidance.py tests/test_findings_persistence.py tests/test_revise_loop.py tests/test_revise_scores.py -v`
Expected: All pass

- [ ] **Step 7: Run full test suite**

Run: `python3 -m pytest tests/ --tb=short`
Expected: No regressions

- [ ] **Step 8: Commit**

```bash
git add scripts/lib/python/storyforge/cmd_revise.py tests/test_findings_guidance.py
git commit -m "Wire deterministic findings into --scores and polish loop guidance"
git push
```

---

### Task 5: Version bump and test on real project

**Files:**
- Modify: `.claude-plugin/plugin.json`

- [ ] **Step 1: Bump patch version**

Change `"version": "1.16.0"` to `"version": "1.16.1"`.

- [ ] **Step 2: Run scoring on shared-dark to generate findings**

```bash
cd ~/Developer/shared-dark && PYTHONPATH=~/Developer/storyforge/scripts/lib/python python3 -m storyforge score --principles prose_repetition,avoid_passive,avoid_adverbs,no_weather_dreams,sentence_as_thought,economy_clarity
```

Verify that `working/scores/latest/repetition-findings.csv` and `working/scores/latest/scene-findings.csv` now exist.

- [ ] **Step 3: Test `--scores` plan generation with findings**

```bash
cd ~/Developer/shared-dark && PYTHONPATH=~/Developer/storyforge/scripts/lib/python python3 -c "
from storyforge.cmd_revise import _read_diagnosis, _generate_scores_plan, _load_findings
import os

diag = _read_diagnosis('working/scores/latest')
rows = _generate_scores_plan('/tmp/test-plan.csv', diag, findings_dir='working/scores/latest')
for r in rows:
    print(f'{r[\"name\"]}: {r[\"fix_location\"]}')
    # Show first 200 chars of guidance
    print(f'  guidance: {r[\"guidance\"][:200]}...')
"
```

Verify guidance includes repetition phrases and per-scene findings.

- [ ] **Step 4: Commit**

```bash
git add .claude-plugin/plugin.json
git commit -m "Bump version to 1.16.1"
git push
```
