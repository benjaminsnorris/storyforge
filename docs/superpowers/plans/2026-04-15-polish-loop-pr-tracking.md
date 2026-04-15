# Polish Loop PR Tracking Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make `revise --polish --loop` create a draft PR with initial deterministic scores, update the PR body as each iteration completes, and post a final comment comparing baseline vs final scores.

**Architecture:** Three new helper functions in `cmd_revise.py` handle PR formatting (`_build_polish_pr_body`, `_update_pr_body_iteration`, `_post_polish_summary_comment`). The existing `_run_polish_loop` is restructured to call these at the right points and to commit/push the initial scores before creating the PR. All git/PR operations go through existing `storyforge.git` helpers.

**Tech Stack:** Python, `storyforge.git` (create_draft_pr, update_pr_task, commit_and_push, has_gh), `subprocess` for `gh pr` commands.

---

### Task 1: Add `_format_scores_table` helper

Shared formatting function that turns a diagnosis summary dict into a markdown table. Used by both the PR body builder and the final comment.

**Files:**
- Modify: `scripts/lib/python/storyforge/cmd_revise.py` (insert after `_summarize_diagnosis` at ~line 488)
- Test: `tests/test_revise_loop.py`

- [ ] **Step 1: Write the failing test**

```python
# In tests/test_revise_loop.py — new class at bottom

class TestFormatScoresTable:
    def test_formats_principles_as_markdown_table(self):
        from storyforge.cmd_revise import _format_scores_table

        diag_rows = [
            {'principle': 'avoid_passive', 'scale': 'scene', 'avg_score': '2.1',
             'worst_items': 's01;s03', 'priority': 'high'},
            {'principle': 'avoid_adverbs', 'scale': 'scene', 'avg_score': '3.5',
             'worst_items': 's02', 'priority': 'medium'},
            {'principle': 'economy_clarity', 'scale': 'scene', 'avg_score': '4.2',
             'worst_items': '', 'priority': 'low'},
        ]

        table = _format_scores_table(diag_rows)
        assert '| Principle' in table
        assert '| avoid passive' in table
        assert '| 2.10' in table
        assert '| high' in table
        # Low priority still shown
        assert '| economy clarity' in table

    def test_empty_diag_returns_no_issues(self):
        from storyforge.cmd_revise import _format_scores_table
        table = _format_scores_table([])
        assert 'No issues' in table

    def test_only_scene_scale_included(self):
        from storyforge.cmd_revise import _format_scores_table

        diag_rows = [
            {'principle': 'avoid_passive', 'scale': 'scene', 'avg_score': '2.1',
             'worst_items': 's01', 'priority': 'high'},
            {'principle': 'genre_contract', 'scale': 'act', 'avg_score': '1.5',
             'worst_items': '', 'priority': 'high'},
        ]
        table = _format_scores_table(diag_rows)
        assert 'avoid passive' in table
        assert 'genre contract' not in table
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python3 -m pytest tests/test_revise_loop.py::TestFormatScoresTable -v`
Expected: FAIL — `_format_scores_table` does not exist

- [ ] **Step 3: Implement `_format_scores_table`**

Insert after the `_summarize_diagnosis` function (~line 488) in `cmd_revise.py`:

```python
def _format_scores_table(diag_rows: list[dict]) -> str:
    """Format diagnosis rows as a markdown table for PR display."""
    scene_rows = [r for r in diag_rows if r.get('scale') == 'scene']
    if not scene_rows:
        return 'No issues detected.'

    lines = ['| Principle | Avg Score | Priority | Weakest Scenes |',
             '|-----------|-----------|----------|----------------|']
    for r in sorted(scene_rows, key=lambda x: x.get('priority', 'low') != 'high'):
        principle = r.get('principle', '').replace('_', ' ')
        avg = f'{float(r.get("avg_score", 0)):.2f}'
        priority = r.get('priority', '')
        worst = r.get('worst_items', '').replace(';', ', ')
        lines.append(f'| {principle} | {avg} | {priority} | {worst} |')
    return '\n'.join(lines)
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `python3 -m pytest tests/test_revise_loop.py::TestFormatScoresTable -v`
Expected: 3 passed

- [ ] **Step 5: Commit**

```bash
git add scripts/lib/python/storyforge/cmd_revise.py tests/test_revise_loop.py
git commit -m "Add _format_scores_table helper for polish loop PR display"
git push
```

---

### Task 2: Add `_build_polish_pr_body` helper

Builds the initial PR body with title, scene count, initial score table, and a task checklist.

**Files:**
- Modify: `scripts/lib/python/storyforge/cmd_revise.py` (insert after `_format_scores_table`)
- Test: `tests/test_revise_loop.py`

- [ ] **Step 1: Write the failing test**

```python
class TestBuildPolishPrBody:
    def test_contains_initial_scores_table(self):
        from storyforge.cmd_revise import _build_polish_pr_body

        diag_rows = [
            {'principle': 'avoid_passive', 'scale': 'scene', 'avg_score': '2.1',
             'worst_items': 's01', 'priority': 'high'},
        ]
        body = _build_polish_pr_body('Test Novel', 5, 3, diag_rows)
        assert '## Initial Deterministic Scores' in body
        assert 'avoid passive' in body
        assert '2.10' in body

    def test_contains_task_checklist(self):
        from storyforge.cmd_revise import _build_polish_pr_body

        diag_rows = [
            {'principle': 'avoid_passive', 'scale': 'scene', 'avg_score': '2.1',
             'worst_items': 's01', 'priority': 'high'},
        ]
        body = _build_polish_pr_body('Test Novel', 5, 3, diag_rows)
        assert '- [x] Initial deterministic scoring' in body
        assert '## Progress' in body

    def test_contains_metadata(self):
        from storyforge.cmd_revise import _build_polish_pr_body

        body = _build_polish_pr_body('My Novel', 10, 5, [])
        assert 'My Novel' in body
        assert '10 scenes' in body
        assert '5 max iterations' in body
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python3 -m pytest tests/test_revise_loop.py::TestBuildPolishPrBody -v`
Expected: FAIL — `_build_polish_pr_body` does not exist

- [ ] **Step 3: Implement `_build_polish_pr_body`**

Insert after `_format_scores_table` in `cmd_revise.py`:

```python
def _build_polish_pr_body(title: str, scene_count: int, max_loops: int,
                          diag_rows: list[dict]) -> str:
    """Build the initial PR body for a polish loop run."""
    scores_table = _format_scores_table(diag_rows)
    summary = _summarize_diagnosis(diag_rows)

    return f"""## Polish Loop — {title}

{scene_count} scenes | {max_loops} max iterations

## Initial Deterministic Scores

Overall avg: **{summary['overall_avg']:.2f}** | {summary['high_count']} high | {summary['medium_count']} medium priority

{scores_table}

## Progress

- [x] Initial deterministic scoring
"""
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `python3 -m pytest tests/test_revise_loop.py::TestBuildPolishPrBody -v`
Expected: 3 passed

- [ ] **Step 5: Commit**

```bash
git add scripts/lib/python/storyforge/cmd_revise.py tests/test_revise_loop.py
git commit -m "Add _build_polish_pr_body helper for PR creation"
git push
```

---

### Task 3: Add `_update_pr_body_iteration` helper

Appends an iteration summary line to the PR body's Progress section.

**Files:**
- Modify: `scripts/lib/python/storyforge/cmd_revise.py` (insert after `_build_polish_pr_body`)
- Modify: `scripts/lib/python/storyforge/git.py` (add `get_pr_body` and `set_pr_body` helpers)
- Test: `tests/test_revise_loop.py`

- [ ] **Step 1: Write the failing tests**

```python
class TestUpdatePrBodyIteration:
    def test_appends_iteration_line(self, tmp_path, monkeypatch):
        from storyforge.cmd_revise import _update_pr_body_iteration

        project_dir = str(tmp_path)
        existing_body = (
            '## Progress\n\n'
            '- [x] Initial deterministic scoring\n'
        )

        # Mock git.get_pr_body / git.set_pr_body
        monkeypatch.setattr('storyforge.cmd_revise.get_pr_body',
                            lambda pd, pr: existing_body)
        captured = {}
        def fake_set(pd, pr, body):
            captured['body'] = body
        monkeypatch.setattr('storyforge.cmd_revise.set_pr_body', fake_set)

        summary = {'overall_avg': 3.5, 'high_count': 1, 'medium_count': 0,
                   'high_principles': ['avoid_passive'], 'medium_principles': [],
                   'scene_principle_count': 3}
        _update_pr_body_iteration(project_dir, '42', 1, summary)

        assert '- [x] Iteration 1' in captured['body']
        assert 'avg 3.50' in captured['body']
        assert '1 high' in captured['body']

    def test_no_op_without_pr_number(self, tmp_path, monkeypatch):
        from storyforge.cmd_revise import _update_pr_body_iteration

        # Should not raise
        _update_pr_body_iteration(str(tmp_path), '', 1,
                                  {'overall_avg': 0, 'high_count': 0, 'medium_count': 0,
                                   'high_principles': [], 'medium_principles': [],
                                   'scene_principle_count': 0})

    def test_appends_convergence_line(self, tmp_path, monkeypatch):
        from storyforge.cmd_revise import _update_pr_body_iteration

        project_dir = str(tmp_path)
        existing_body = (
            '## Progress\n\n'
            '- [x] Initial deterministic scoring\n'
            '- [x] Iteration 1 — avg 3.50, 1 high / 0 medium\n'
        )

        monkeypatch.setattr('storyforge.cmd_revise.get_pr_body',
                            lambda pd, pr: existing_body)
        captured = {}
        monkeypatch.setattr('storyforge.cmd_revise.set_pr_body',
                            lambda pd, pr, body: captured.update({'body': body}))

        summary = {'overall_avg': 4.0, 'high_count': 0, 'medium_count': 0,
                   'high_principles': [], 'medium_principles': [],
                   'scene_principle_count': 3}
        _update_pr_body_iteration(project_dir, '42', 2, summary, converged=True)

        assert '- [x] Iteration 2' in captured['body']
        assert 'converged' in captured['body'].lower()
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python3 -m pytest tests/test_revise_loop.py::TestUpdatePrBodyIteration -v`
Expected: FAIL — functions do not exist

- [ ] **Step 3: Add `get_pr_body` and `set_pr_body` to `git.py`**

Insert after `update_pr_task` (~line 214) in `git.py`:

```python
def get_pr_body(project_dir: str, pr_number: str) -> str:
    """Read the current PR body. Returns empty string on failure."""
    if not has_gh() or not pr_number:
        return ''
    r = subprocess.run(
        ['gh', 'pr', 'view', pr_number, '--json', 'body', '--jq', '.body'],
        capture_output=True, text=True, cwd=project_dir,
    )
    return r.stdout if r.returncode == 0 else ''


def set_pr_body(project_dir: str, pr_number: str, body: str) -> None:
    """Replace the PR body."""
    if not has_gh() or not pr_number:
        return
    subprocess.run(
        ['gh', 'pr', 'edit', pr_number, '--body', body],
        capture_output=True, cwd=project_dir,
    )
```

- [ ] **Step 4: Implement `_update_pr_body_iteration`**

Insert after `_build_polish_pr_body` in `cmd_revise.py`. Add `get_pr_body, set_pr_body` to the import from `storyforge.git` at the top of the file (line 33-36).

```python
def _update_pr_body_iteration(project_dir: str, pr_number: str,
                              iteration: int, summary: dict, *,
                              converged: bool = False) -> None:
    """Append an iteration result line to the PR body's Progress section."""
    if not pr_number:
        return

    body = get_pr_body(project_dir, pr_number)
    if not body:
        return

    status = (f'avg {summary["overall_avg"]:.2f}, '
              f'{summary["high_count"]} high / {summary["medium_count"]} medium')
    if converged:
        status += ' — converged'
    line = f'- [x] Iteration {iteration} — {status}\n'

    body = body.rstrip('\n') + '\n' + line + '\n'
    set_pr_body(project_dir, pr_number, body)
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `python3 -m pytest tests/test_revise_loop.py::TestUpdatePrBodyIteration -v`
Expected: 3 passed

- [ ] **Step 6: Commit**

```bash
git add scripts/lib/python/storyforge/cmd_revise.py scripts/lib/python/storyforge/git.py tests/test_revise_loop.py
git commit -m "Add PR body update helpers for polish loop iteration tracking"
git push
```

---

### Task 4: Add `_post_polish_summary_comment` helper

Posts a final PR comment comparing baseline deterministic scores, final deterministic scores, and (optionally) full LLM scores.

**Files:**
- Modify: `scripts/lib/python/storyforge/cmd_revise.py` (insert after `_update_pr_body_iteration`)
- Modify: `scripts/lib/python/storyforge/git.py` (add `add_pr_comment` helper)
- Test: `tests/test_revise_loop.py`

- [ ] **Step 1: Write the failing test**

```python
class TestPostPolishSummaryComment:
    def test_posts_comparison_comment(self, tmp_path, monkeypatch):
        from storyforge.cmd_revise import _post_polish_summary_comment

        project_dir = str(tmp_path)
        captured = {}
        monkeypatch.setattr('storyforge.cmd_revise.add_pr_comment',
                            lambda pd, pr, body: captured.update({'body': body}))

        baseline_diag = [
            {'principle': 'avoid_passive', 'scale': 'scene', 'avg_score': '2.1',
             'worst_items': 's01', 'priority': 'high'},
        ]
        final_det_diag = [
            {'principle': 'avoid_passive', 'scale': 'scene', 'avg_score': '3.8',
             'worst_items': 's01', 'priority': 'low'},
        ]
        final_llm_diag = [
            {'principle': 'avoid_passive', 'scale': 'scene', 'avg_score': '3.5',
             'worst_items': 's01', 'priority': 'low'},
            {'principle': 'prose_naturalness', 'scale': 'scene', 'avg_score': '3.0',
             'worst_items': 's01', 'priority': 'medium'},
        ]

        _post_polish_summary_comment(project_dir, '42',
                                     baseline_diag, final_det_diag,
                                     final_llm_diag=final_llm_diag)

        body = captured['body']
        assert '## Deterministic Score Changes' in body
        assert 'avoid passive' in body
        assert '2.10' in body  # baseline
        assert '3.80' in body  # final
        assert '## Full LLM Scores' in body
        assert 'prose naturalness' in body

    def test_skips_llm_section_when_none(self, tmp_path, monkeypatch):
        from storyforge.cmd_revise import _post_polish_summary_comment

        project_dir = str(tmp_path)
        captured = {}
        monkeypatch.setattr('storyforge.cmd_revise.add_pr_comment',
                            lambda pd, pr, body: captured.update({'body': body}))

        baseline = [{'principle': 'avoid_passive', 'scale': 'scene',
                     'avg_score': '2.1', 'worst_items': '', 'priority': 'high'}]
        final = [{'principle': 'avoid_passive', 'scale': 'scene',
                  'avg_score': '3.5', 'worst_items': '', 'priority': 'low'}]

        _post_polish_summary_comment(project_dir, '42', baseline, final)

        body = captured['body']
        assert '## Deterministic Score Changes' in body
        assert '## Full LLM Scores' not in body

    def test_no_op_without_pr_number(self, tmp_path, monkeypatch):
        from storyforge.cmd_revise import _post_polish_summary_comment
        # Should not raise
        _post_polish_summary_comment(str(tmp_path), '', [], [])
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python3 -m pytest tests/test_revise_loop.py::TestPostPolishSummaryComment -v`
Expected: FAIL — functions do not exist

- [ ] **Step 3: Add `add_pr_comment` to `git.py`**

Insert after `set_pr_body` in `git.py`:

```python
def add_pr_comment(project_dir: str, pr_number: str, body: str) -> None:
    """Post a comment on a PR."""
    if not has_gh() or not pr_number:
        return
    subprocess.run(
        ['gh', 'pr', 'comment', pr_number, '--body', body],
        capture_output=True, cwd=project_dir,
    )
```

- [ ] **Step 4: Implement `_post_polish_summary_comment`**

Insert after `_update_pr_body_iteration` in `cmd_revise.py`. Add `add_pr_comment` to the import from `storyforge.git`.

```python
def _post_polish_summary_comment(project_dir: str, pr_number: str,
                                 baseline_diag: list[dict],
                                 final_det_diag: list[dict], *,
                                 final_llm_diag: list[dict] | None = None) -> None:
    """Post a summary comment comparing baseline and final scores."""
    if not pr_number:
        return

    # Build before/after comparison table for deterministic scores
    baseline_by_p = {r['principle']: r for r in baseline_diag if r.get('scale') == 'scene'}
    final_by_p = {r['principle']: r for r in final_det_diag if r.get('scale') == 'scene'}
    all_principles = sorted(set(baseline_by_p) | set(final_by_p))

    lines = ['## Deterministic Score Changes', '',
             '| Principle | Baseline | Final | Delta |',
             '|-----------|----------|-------|-------|']
    for p in all_principles:
        name = p.replace('_', ' ')
        b_score = float(baseline_by_p[p]['avg_score']) if p in baseline_by_p else 0.0
        f_score = float(final_by_p[p]['avg_score']) if p in final_by_p else 0.0
        delta = f_score - b_score
        sign = '+' if delta >= 0 else ''
        lines.append(f'| {name} | {b_score:.2f} | {f_score:.2f} | {sign}{delta:.2f} |')

    baseline_summary = _summarize_diagnosis(baseline_diag)
    final_summary = _summarize_diagnosis(final_det_diag)
    overall_delta = final_summary['overall_avg'] - baseline_summary['overall_avg']
    sign = '+' if overall_delta >= 0 else ''
    lines.append('')
    lines.append(f'**Overall avg: {baseline_summary["overall_avg"]:.2f} → '
                 f'{final_summary["overall_avg"]:.2f} ({sign}{overall_delta:.2f})**')

    # Full LLM scores section
    if final_llm_diag is not None:
        llm_table = _format_scores_table(final_llm_diag)
        llm_summary = _summarize_diagnosis(final_llm_diag)
        lines.extend(['', '## Full LLM Scores', '',
                      f'Overall avg: **{llm_summary["overall_avg"]:.2f}** | '
                      f'{llm_summary["high_count"]} high | '
                      f'{llm_summary["medium_count"]} medium priority', '',
                      llm_table])

    add_pr_comment(project_dir, pr_number, '\n'.join(lines))
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `python3 -m pytest tests/test_revise_loop.py::TestPostPolishSummaryComment -v`
Expected: 3 passed

- [ ] **Step 6: Commit**

```bash
git add scripts/lib/python/storyforge/cmd_revise.py scripts/lib/python/storyforge/git.py tests/test_revise_loop.py
git commit -m "Add _post_polish_summary_comment for final PR comparison"
git push
```

---

### Task 5: Wire helpers into `_run_polish_loop`

Restructure the loop to: (1) score first, (2) commit initial scores, (3) create draft PR, (4) update PR body after each iteration, (5) post final summary comment.

**Files:**
- Modify: `scripts/lib/python/storyforge/cmd_revise.py` (`_run_polish_loop` at line 866)
- Test: `tests/test_revise_loop.py`

- [ ] **Step 1: Write the failing test**

Add to `TestPolishLoopOrchestration`:

```python
    def test_creates_pr_with_initial_scores(self, tmp_path, monkeypatch):
        """Loop should create a draft PR after initial scoring."""
        from storyforge.cmd_revise import _run_polish_loop

        project_dir = self._setup_project(tmp_path)
        pr_calls = {'create': [], 'update_body': [], 'comment': []}

        converged_diag = self._make_diag(high=0, medium=0, avg=4.5)

        def fake_deterministic(proj, scene_ids):
            cycle_dir = os.path.join(proj, 'working', 'scores', 'cycle-1')
            os.makedirs(cycle_dir, exist_ok=True)
            return cycle_dir, converged_diag

        monkeypatch.setattr('storyforge.cmd_revise._run_deterministic_score', fake_deterministic)
        monkeypatch.setattr('storyforge.cmd_revise._run_lightweight_score',
                            lambda p, s: ('', converged_diag))
        monkeypatch.setattr('storyforge.cmd_revise.create_branch', lambda *a: 'storyforge/revise-test')
        monkeypatch.setattr('storyforge.cmd_revise.ensure_branch_pushed', lambda *a: None)
        monkeypatch.setattr('storyforge.cmd_revise.commit_and_push', lambda *a, **kw: True)
        monkeypatch.setattr('storyforge.cmd_revise.create_draft_pr',
                            lambda title, body, pd, work_type='': pr_calls['create'].append(body) or '99')
        monkeypatch.setattr('storyforge.cmd_revise.get_pr_body', lambda pd, pr: '')
        monkeypatch.setattr('storyforge.cmd_revise.set_pr_body', lambda pd, pr, b: None)
        monkeypatch.setattr('storyforge.cmd_revise.add_pr_comment',
                            lambda pd, pr, body: pr_calls['comment'].append(body))

        _run_polish_loop(project_dir, 3, None)

        # PR was created
        assert len(pr_calls['create']) == 1
        pr_body = pr_calls['create'][0]
        assert 'Initial Deterministic Scores' in pr_body
        assert '- [x] Initial deterministic scoring' in pr_body

        # Final comment was posted
        assert len(pr_calls['comment']) == 1
        assert 'Deterministic Score Changes' in pr_calls['comment'][0]

    def test_updates_pr_body_each_iteration(self, tmp_path, monkeypatch):
        """Loop should update PR body after each polish iteration."""
        from storyforge.cmd_revise import _run_polish_loop

        project_dir = self._setup_project(tmp_path)
        body_updates = []

        call_count = [0]
        def fake_deterministic(proj, scene_ids):
            call_count[0] += 1
            cycle_dir = os.path.join(proj, 'working', 'scores', f'cycle-{call_count[0]}')
            os.makedirs(cycle_dir, exist_ok=True)
            if call_count[0] == 1:
                return cycle_dir, self._make_diag(high=1, avg=2.0)
            return cycle_dir, self._make_diag(high=0, medium=0, avg=4.5)

        def fake_set_body(pd, pr, body):
            body_updates.append(body)

        monkeypatch.setattr('storyforge.cmd_revise._run_deterministic_score', fake_deterministic)
        monkeypatch.setattr('storyforge.cmd_revise._run_lightweight_score',
                            lambda p, s: ('', self._make_diag(high=0, avg=4.5)))
        monkeypatch.setattr('storyforge.cmd_revise._execute_single_pass',
                            lambda *a, **kw: None)
        monkeypatch.setattr('storyforge.cmd_revise.create_branch', lambda *a: 'storyforge/revise-test')
        monkeypatch.setattr('storyforge.cmd_revise.ensure_branch_pushed', lambda *a: None)
        monkeypatch.setattr('storyforge.cmd_revise.commit_and_push', lambda *a, **kw: True)
        monkeypatch.setattr('storyforge.cmd_revise.create_draft_pr',
                            lambda title, body, pd, work_type='': '99')
        monkeypatch.setattr('storyforge.cmd_revise.get_pr_body',
                            lambda pd, pr: '## Progress\n\n- [x] Initial deterministic scoring\n')
        monkeypatch.setattr('storyforge.cmd_revise.set_pr_body', fake_set_body)
        monkeypatch.setattr('storyforge.cmd_revise.add_pr_comment', lambda pd, pr, body: None)

        _run_polish_loop(project_dir, 3, None)

        # At least one body update (iteration 1 result, then iteration 2 convergence)
        assert len(body_updates) >= 1
        assert any('Iteration' in u for u in body_updates)
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python3 -m pytest tests/test_revise_loop.py::TestPolishLoopOrchestration::test_creates_pr_with_initial_scores tests/test_revise_loop.py::TestPolishLoopOrchestration::test_updates_pr_body_each_iteration -v`
Expected: FAIL — `_run_polish_loop` doesn't call PR helpers yet

- [ ] **Step 3: Restructure `_run_polish_loop`**

The key changes to `_run_polish_loop` (line 866-1007):

1. **Move initial scoring before the loop** — run it once unconditionally (or use existing scores with `--skip-initial-score`), then commit and create the PR.
2. **Track `pr_number`** and `baseline_diag` for the final comment.
3. **After each iteration's polish pass**, call `_update_pr_body_iteration`.
4. **On convergence**, call `_update_pr_body_iteration` with `converged=True`.
5. **After Phase 2 (or skip)**, call `_post_polish_summary_comment`.

Replace the entire `_run_polish_loop` function body with:

```python
def _run_polish_loop(project_dir: str, max_loops: int,
                     coaching_override: str | None, *,
                     skip_initial_score: bool = False,
                     skip_final_score: bool = False) -> None:
    """Two-phase polish loop: deterministic scoring → full LLM scoring.

    Phase 1: Score only deterministic principles (free, instant), polish with
    Sonnet (mechanical fixes), repeat until converged or max_loops reached.

    Phase 2: Run one full LLM scoring pass for the complete picture (unless
    --skip-final-score is set).
    """
    from storyforge.common import get_coaching_level, read_yaml_field
    from storyforge.git import create_branch, ensure_branch_pushed, commit_and_push
    from storyforge.scene_filter import build_scene_list

    if coaching_override:
        os.environ['STORYFORGE_COACHING'] = coaching_override

    title = read_yaml_field('project.title', project_dir) or '(untitled)'
    metadata_csv = os.path.join(project_dir, 'reference', 'scenes.csv')
    scenes_dir = os.path.join(project_dir, 'scenes')

    # Build scene list (only drafted scenes)
    all_ids = build_scene_list(metadata_csv)
    scene_ids = [sid for sid in all_ids
                 if os.path.isfile(os.path.join(scenes_dir, f'{sid}.md'))]

    if not scene_ids:
        log('ERROR: No drafted scenes found.')
        sys.exit(1)

    # Create branch once for the whole loop
    create_branch('revise', project_dir)
    ensure_branch_pushed(project_dir)

    log('============================================')
    log(f'Storyforge Polish Loop — {title}')
    log(f'Scenes: {len(scene_ids)}')
    log(f'Max iterations: {max_loops}')
    log('============================================')

    csv_plan_file = os.path.join(project_dir, 'working', 'plans', 'revision-plan.csv')
    sonnet_model = select_model('evaluation')

    # ------------------------------------------------------------------
    # Initial scoring (before the loop)
    # ------------------------------------------------------------------
    if skip_initial_score:
        latest_dir = os.path.join(project_dir, 'working', 'scores', 'latest')
        if not os.path.isdir(latest_dir):
            log('ERROR: --skip-initial-score but no existing scores in working/scores/latest')
            sys.exit(1)
        baseline_diag = _read_diagnosis(latest_dir)
        if not baseline_diag:
            log('ERROR: --skip-initial-score but no diagnosis.csv in existing scores')
            log('  Run a scoring cycle first, or remove --skip-initial-score')
            sys.exit(1)
        log('  Skipped initial scoring (--skip-initial-score) — using existing scores')
    else:
        log(f'\n=== Initial Deterministic Score ===')
        _, baseline_diag = _run_deterministic_score(project_dir, scene_ids)

    baseline_summary = _summarize_diagnosis(baseline_diag)
    log(f'  Overall avg: {baseline_summary["overall_avg"]:.2f}')
    log(f'  High priority: {baseline_summary["high_count"]} principles')
    log(f'  Medium priority: {baseline_summary["medium_count"]} principles')

    # Commit initial scores and create PR
    commit_and_push(project_dir, 'Polish: initial deterministic scores', ['working/'])
    pr_body = _build_polish_pr_body(title, len(scene_ids), max_loops, baseline_diag)
    pr_number = create_draft_pr(f'Polish: {title}', pr_body, project_dir,
                                work_type='polish')

    # ------------------------------------------------------------------
    # Phase 1: Deterministic scoring loop (free, instant)
    # ------------------------------------------------------------------
    log(f'\n=== Phase 1: Deterministic Polish (free) ===')

    prev_avg = baseline_summary['overall_avg']
    summary = baseline_summary
    latest_diag = baseline_diag

    for iteration in range(1, max_loops + 1):
        # Convergence check: no actionable issues
        if summary['high_count'] == 0 and summary['medium_count'] == 0:
            log('  No high or medium priority issues — converged')
            _update_pr_body_iteration(project_dir, pr_number, iteration, summary,
                                      converged=True)
            break

        # Check for upstream causes before craft polish
        upstream_scenes = _detect_upstream_scenes(project_dir, latest_diag)
        if upstream_scenes:
            log(f'  Upstream issues in {len(upstream_scenes)} scenes — fixing briefs first')
            _fix_upstream_briefs(project_dir, upstream_scenes)
            _redraft_scenes(project_dir, upstream_scenes)
            commit_and_push(project_dir,
                            f'Polish: upstream brief fixes for {len(upstream_scenes)} scenes',
                            ['reference/', 'scenes/', 'working/'])

        # Generate targeted plan from diagnosis and execute
        log(f'\n=== Iteration {iteration}/{max_loops}: Polish (Sonnet) ===')
        plan_rows = _generate_targeted_polish_plan(csv_plan_file, latest_diag)
        _execute_single_pass(project_dir, csv_plan_file, plan_rows, iteration,
                             model_override=sonnet_model)

        # Re-score
        log(f'\n=== Iteration {iteration}/{max_loops}: Re-score ===')
        _, latest_diag = _run_deterministic_score(project_dir, scene_ids)
        summary = _summarize_diagnosis(latest_diag)

        log(f'  Overall avg: {summary["overall_avg"]:.2f}')
        log(f'  High priority: {summary["high_count"]} principles')

        # Update PR with iteration results
        converged = (summary['high_count'] == 0 and summary['medium_count'] == 0)
        if not converged and iteration > 1 and summary['overall_avg'] <= prev_avg:
            converged = True
            log(f'  Overall avg did not improve ({summary["overall_avg"]:.2f} <= '
                f'{prev_avg:.2f}) — converged')
        _update_pr_body_iteration(project_dir, pr_number, iteration, summary,
                                  converged=converged)

        if converged:
            break

        prev_avg = summary['overall_avg']

    else:
        log(f'\n  Reached max iterations ({max_loops})')

    # Commit deterministic phase results
    commit_and_push(project_dir, 'Polish: deterministic phase complete', ['working/'])

    # ------------------------------------------------------------------
    # Phase 2: Full LLM scoring (one run for the complete picture)
    # ------------------------------------------------------------------
    final_llm_diag = None
    if skip_final_score:
        log(f'\n=== Skipping Phase 2: Full Score (--skip-final-score) ===')
        final_summary = summary
    else:
        log(f'\n=== Phase 2: Full Score ===')
        _, final_llm_diag = _run_lightweight_score(project_dir, scene_ids)
        final_summary = _summarize_diagnosis(final_llm_diag)
        commit_and_push(project_dir, 'Polish: full score after deterministic loop',
                        ['working/'])

    # Post summary comment
    _post_polish_summary_comment(project_dir, pr_number,
                                 baseline_diag, latest_diag,
                                 final_llm_diag=final_llm_diag)

    log('\n============================================')
    log('Polish loop complete')
    log(f'  Deterministic baseline: avg {baseline_summary["overall_avg"]:.2f}, '
        f'{baseline_summary["high_count"]} high / {baseline_summary["medium_count"]} medium priority')
    log(f'  Final: avg {final_summary["overall_avg"]:.2f}, '
        f'{final_summary["high_count"]} high / {final_summary["medium_count"]} medium priority')
    if baseline_summary['overall_avg'] > 0:
        delta = final_summary['overall_avg'] - baseline_summary['overall_avg']
        log(f'  Deterministic improvement: {delta:+.2f} avg score')
    log('============================================')
```

- [ ] **Step 4: Update imports at top of `cmd_revise.py`**

Add `get_pr_body, set_pr_body, add_pr_comment` to the import block at line 33-36:

```python
from storyforge.git import (
    create_branch, ensure_branch_pushed, create_draft_pr,
    update_pr_task, commit_and_push, _git, has_gh, current_branch,
    get_pr_body, set_pr_body, add_pr_comment,
)
```

- [ ] **Step 5: Run all tests to verify they pass**

Run: `python3 -m pytest tests/test_revise_loop.py -v`
Expected: All tests pass (existing + new)

- [ ] **Step 6: Commit**

```bash
git add scripts/lib/python/storyforge/cmd_revise.py tests/test_revise_loop.py
git commit -m "Wire PR tracking into _run_polish_loop"
git push
```

---

### Task 6: Fix existing tests that mock `_run_polish_loop` dependencies

The restructured `_run_polish_loop` now calls `create_draft_pr`, `get_pr_body`, `set_pr_body`, and `add_pr_comment`. Existing tests that mock `create_branch` / `commit_and_push` need the new mocks too.

**Files:**
- Modify: `tests/test_revise_loop.py`

- [ ] **Step 1: Run existing `TestPolishLoopOrchestration` tests to find failures**

Run: `python3 -m pytest tests/test_revise_loop.py::TestPolishLoopOrchestration -v`
Expected: Some existing tests fail because they don't mock the new PR helpers.

- [ ] **Step 2: Add missing mocks to existing tests**

Each test in `TestPolishLoopOrchestration` that monkeypatches `create_branch` / `commit_and_push` needs these additional lines:

```python
monkeypatch.setattr('storyforge.cmd_revise.create_draft_pr',
                    lambda title, body, pd, work_type='': '')
monkeypatch.setattr('storyforge.cmd_revise.get_pr_body', lambda pd, pr: '')
monkeypatch.setattr('storyforge.cmd_revise.set_pr_body', lambda pd, pr, b: None)
monkeypatch.setattr('storyforge.cmd_revise.add_pr_comment', lambda pd, pr, body: None)
```

Apply to these tests:
- `test_phase1_uses_deterministic_score`
- `test_skip_final_score_skips_phase2`
- `test_polish_uses_sonnet_model`
- `test_convergence_stops_loop`
- `test_zero_max_loops_no_crash`
- `test_skip_initial_score_exits_on_empty_diagnosis`

- [ ] **Step 3: Update `test_convergence_stops_loop` expected counts**

The restructured flow runs the initial score *outside* the loop. The test sends the same `avg=3.0` with `high=1` every time. New flow: baseline (call 1, high=1) → iteration 1 polishes + re-scores (call 2, same avg but `iteration > 1` is False) → iteration 2 polishes + re-scores (call 3, `iteration > 1` is True, avg <= prev → converge). Update expectations:

```python
        # Baseline (1) + iteration 1 re-score (2) + iteration 2 re-score (3)
        assert call_count[0] == 3
        # Iteration 1 polished + iteration 2 polished before convergence detected
        assert polish_count[0] == 2
```

- [ ] **Step 4: Update `test_phase1_uses_deterministic_score` expected counts**

The initial deterministic score now runs outside the loop (before Phase 1). With a converged diag (high=0, medium=0), the loop body never executes a second deterministic score. The existing expectation of `calls['deterministic'] == 1` is still correct, but verify the initial score call happens outside the loop and Phase 2 still uses lightweight.

- [ ] **Step 5: Run all loop tests to verify they pass**

Run: `python3 -m pytest tests/test_revise_loop.py -v`
Expected: All tests pass

- [ ] **Step 4: Run full test suite to check for wider regressions**

Run: `python3 -m pytest tests/ -v --tb=short`
Expected: No regressions

- [ ] **Step 5: Commit**

```bash
git add tests/test_revise_loop.py
git commit -m "Fix existing polish loop tests for new PR tracking mocks"
git push
```
