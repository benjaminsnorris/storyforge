# Prompt Caching and Cost Summary Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Enable Anthropic prompt caching across all API calls (batch and direct) to reduce cost and latency, and show per-session + cumulative cost summaries with human-readable durations.

**Architecture:** A shared context helper (`build_shared_context`) assembles project reference materials into two-tier cacheable system blocks. The API layer (`invoke`, `invoke_to_file`, `build_batch_request`) passes these as the `system` parameter. Prompt builders stop inlining shared material. Cost summaries gain session-scoped filtering and formatted durations.

**Tech Stack:** Python 3.11+, Anthropic Messages API, pytest

**Spec:** `docs/superpowers/specs/2026-04-15-prompt-caching-and-cost-summary-design.md`

---

## File Map

**Modify:**
- `scripts/lib/python/storyforge/costs.py` — add `format_duration()`, session-scoped `print_summary`
- `scripts/lib/python/storyforge/api.py` — add `system` param to `invoke()` family, add `build_batch_request()`
- `scripts/lib/python/storyforge/common.py` — add `build_shared_context()`
- `scripts/lib/python/storyforge/prompts.py` — remove shared content inlining from `build_scene_prompt()`
- `scripts/lib/python/storyforge/prompts_elaborate.py` — remove shared content inlining from stage prompts
- `scripts/lib/python/storyforge/revision.py` — remove shared content inlining from `build_revision_prompt()`
- `scripts/lib/python/storyforge/scoring.py` — remove shared content inlining from scoring prompts
- `scripts/lib/python/storyforge/extract.py` — remove shared content inlining from extraction prompts
- `scripts/lib/python/storyforge/cmd_write.py` — use `build_batch_request`, pass system context, session cost
- `scripts/lib/python/storyforge/cmd_score.py` — use `build_batch_request`, pass system context, session cost
- `scripts/lib/python/storyforge/cmd_evaluate.py` — use `build_batch_request`, pass system context, session cost
- `scripts/lib/python/storyforge/cmd_extract.py` — use `build_batch_request`, pass system context, session cost
- `scripts/lib/python/storyforge/cmd_revise.py` — pass system context to direct calls, session cost
- `scripts/lib/python/storyforge/cmd_elaborate.py` — use `build_batch_request`, pass system context, session cost
- `scripts/lib/python/storyforge/cmd_enrich.py` — use `build_batch_request`, pass system context, session cost
- `scripts/lib/python/storyforge/cmd_timeline.py` — use `build_batch_request`, pass system context, session cost
- `scripts/lib/python/storyforge/cmd_scenes_setup.py` — use `build_batch_request`, pass system context, session cost

**Create:**
- `tests/test_prompt_caching.py` — tests for `build_shared_context` and `build_batch_request`

**Extend:**
- `tests/test_costs.py` — tests for `format_duration` and session-scoped `print_summary`
- `tests/test_api.py` — tests for `invoke()` with system parameter

---

### Task 1: format_duration() + tests

**Files:**
- Modify: `scripts/lib/python/storyforge/costs.py`
- Extend: `tests/test_costs.py`

- [ ] **Step 1: Write failing tests for format_duration**

Add to `tests/test_costs.py`:

```python
from storyforge.costs import format_duration


class TestFormatDuration:
    def test_zero(self):
        assert format_duration(0) == '0s'

    def test_seconds_only(self):
        assert format_duration(45) == '45s'

    def test_minutes_and_seconds(self):
        assert format_duration(180) == '3m 0s'

    def test_minutes_and_nonzero_seconds(self):
        assert format_duration(185) == '3m 5s'

    def test_hours_minutes_seconds(self):
        assert format_duration(3661) == '1h 1m 1s'

    def test_large_duration(self):
        assert format_duration(27888) == '7h 44m 48s'

    def test_exact_hour(self):
        assert format_duration(3600) == '1h 0m 0s'
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python3 -m pytest tests/test_costs.py::TestFormatDuration -v`
Expected: FAIL — `ImportError: cannot import name 'format_duration'`

- [ ] **Step 3: Implement format_duration**

Add to `scripts/lib/python/storyforge/costs.py` after the `check_threshold` function (after line 216):

```python
def format_duration(seconds: int) -> str:
    """Format seconds as Xh Xm Xs, omitting zero leading components."""
    if seconds < 60:
        return f'{seconds}s'
    if seconds < 3600:
        m, s = divmod(seconds, 60)
        return f'{m}m {s}s'
    h, remainder = divmod(seconds, 3600)
    m, s = divmod(remainder, 60)
    return f'{h}h {m}m {s}s'
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `python3 -m pytest tests/test_costs.py::TestFormatDuration -v`
Expected: All 7 tests PASS

- [ ] **Step 5: Update print_summary to use format_duration**

In `scripts/lib/python/storyforge/costs.py`, change line 206 from:

```python
    print(f'Total time:    {total_dur}s')
```

To:

```python
    print(f'Total time:    {format_duration(total_dur)}')
```

- [ ] **Step 6: Run full cost test suite**

Run: `python3 -m pytest tests/test_costs.py -v`
Expected: All tests PASS

- [ ] **Step 7: Commit**

```bash
git add scripts/lib/python/storyforge/costs.py tests/test_costs.py
git commit -m "Add format_duration for human-readable time in cost summaries"
git push
```

---

### Task 2: Session-scoped print_summary + tests

**Files:**
- Modify: `scripts/lib/python/storyforge/costs.py`
- Extend: `tests/test_costs.py`

- [ ] **Step 1: Write failing tests for session-scoped print_summary**

Add to `tests/test_costs.py`:

```python
import os
from storyforge.costs import log_operation, print_summary, LEDGER_HEADER


class TestSessionScopedSummary:
    def _make_ledger(self, project_dir, rows):
        """Write a ledger with the given rows (list of pipe-delimited strings)."""
        ledger_dir = os.path.join(project_dir, 'working', 'costs')
        os.makedirs(ledger_dir, exist_ok=True)
        with open(os.path.join(ledger_dir, 'ledger.csv'), 'w') as f:
            f.write(LEDGER_HEADER + '\n')
            for row in rows:
                f.write(row + '\n')

    def test_no_session_start_shows_cumulative_only(self, tmp_path, capsys):
        project_dir = str(tmp_path / 'proj')
        self._make_ledger(project_dir, [
            '2026-04-01T10:00:00|revise|scene-1|claude-opus-4-6|100000|10000|0|0|5.250000|300',
            '2026-04-15T10:00:00|revise|scene-2|claude-opus-4-6|100000|10000|0|0|5.250000|300',
        ])
        print_summary(project_dir, 'revise')
        out = capsys.readouterr().out
        assert 'This session' not in out
        assert 'Project total' not in out
        assert '--- Cost Summary: revise ---' in out
        assert 'Invocations:   2' in out

    def test_session_start_shows_both_sections(self, tmp_path, capsys):
        project_dir = str(tmp_path / 'proj')
        self._make_ledger(project_dir, [
            '2026-04-01T10:00:00|revise|scene-1|claude-opus-4-6|100000|10000|0|0|5.250000|300',
            '2026-04-15T10:00:00|revise|scene-2|claude-opus-4-6|200000|20000|0|0|10.500000|600',
            '2026-04-15T11:00:00|revise|scene-3|claude-opus-4-6|200000|20000|0|0|10.500000|600',
        ])
        print_summary(project_dir, 'revise', session_start='2026-04-15T09:00:00')
        out = capsys.readouterr().out
        assert '--- This session: revise (2 invocations) ---' in out
        assert '--- Project total: revise (3 invocations) ---' in out

    def test_session_filters_by_timestamp(self, tmp_path, capsys):
        project_dir = str(tmp_path / 'proj')
        self._make_ledger(project_dir, [
            '2026-04-01T10:00:00|revise|scene-1|claude-opus-4-6|100000|10000|0|0|5.250000|300',
            '2026-04-15T14:00:00|revise|scene-2|claude-opus-4-6|200000|20000|0|0|10.500000|600',
        ])
        print_summary(project_dir, 'revise', session_start='2026-04-15T00:00:00')
        out = capsys.readouterr().out
        # Session section should only have 1 invocation (the one after session_start)
        assert '1 invocations' in out or '1 invocation' in out

    def test_session_with_no_matching_rows(self, tmp_path, capsys):
        project_dir = str(tmp_path / 'proj')
        self._make_ledger(project_dir, [
            '2026-04-01T10:00:00|revise|scene-1|claude-opus-4-6|100000|10000|0|0|5.250000|300',
        ])
        print_summary(project_dir, 'revise', session_start='2026-04-15T00:00:00')
        out = capsys.readouterr().out
        # Should still show project total even if session is empty
        assert 'Project total' in out

    def test_duration_uses_format_duration(self, tmp_path, capsys):
        project_dir = str(tmp_path / 'proj')
        self._make_ledger(project_dir, [
            '2026-04-15T10:00:00|revise|scene-1|claude-opus-4-6|100000|10000|0|0|5.250000|3661',
        ])
        print_summary(project_dir, 'revise')
        out = capsys.readouterr().out
        assert '1h 1m 1s' in out
        assert '3661s' not in out
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python3 -m pytest tests/test_costs.py::TestSessionScopedSummary -v`
Expected: FAIL — `print_summary() got an unexpected keyword argument 'session_start'`

- [ ] **Step 3: Rewrite print_summary with session support**

Replace the `print_summary` function in `scripts/lib/python/storyforge/costs.py` (lines 125-206) with:

```python
def print_summary(project_dir: str, operation: str | None = None,
                  session_start: str | None = None) -> None:
    """Print cost totals from the ledger, optionally filtered by operation.

    When session_start is provided (ISO timestamp), shows two sections:
    1. This session — rows with timestamp >= session_start
    2. Project total — all matching rows
    """
    ledger_file = os.path.join(project_dir, 'working', 'costs', 'ledger.csv')

    if not os.path.exists(ledger_file):
        print('No cost data available.')
        return

    with open(ledger_file) as f:
        header_line = f.readline().strip()
        if not header_line:
            print('No cost data available.')
            return
        headers = header_line.split('|')
        col_map = {name: idx for idx, name in enumerate(headers)}

        if 'operation' not in col_map:
            print('No cost data available.')
            return

        rows = []
        for line in f:
            line = line.strip()
            if not line:
                continue
            parts = line.split('|')

            op_idx = col_map['operation']
            if op_idx >= len(parts):
                continue
            if operation and parts[op_idx] != operation:
                continue

            rows.append(parts)

    if not rows and not session_start:
        label = f' for operation: {operation}' if operation else ''
        print(f'No cost data{label}.')
        return

    def _accumulate(row_list):
        count = len(row_list)
        total_input = total_output = total_cache_r = total_cache_c = total_dur = 0
        total_cost = 0.0
        field_map = {
            'input_tokens': 'input', 'output_tokens': 'output',
            'cache_read': 'cache_r', 'cache_create': 'cache_c',
            'duration_s': 'dur',
        }
        for parts in row_list:
            for col_name in ('input_tokens', 'output_tokens', 'cache_read',
                             'cache_create', 'duration_s'):
                if col_name in col_map and col_map[col_name] < len(parts):
                    val = parts[col_map[col_name]]
                    if val:
                        if col_name == 'input_tokens':
                            total_input += int(val)
                        elif col_name == 'output_tokens':
                            total_output += int(val)
                        elif col_name == 'cache_read':
                            total_cache_r += int(val)
                        elif col_name == 'cache_create':
                            total_cache_c += int(val)
                        elif col_name == 'duration_s':
                            total_dur += int(val)
            if 'cost_usd' in col_map and col_map['cost_usd'] < len(parts):
                val = parts[col_map['cost_usd']]
                if val:
                    total_cost += float(val)
        return count, total_input, total_output, total_cache_r, total_cache_c, total_cost, total_dur

    def _print_section(label, count, inp, out, cr, cc, cost, dur):
        inv_word = 'invocation' if count == 1 else 'invocations'
        print(f'--- {label} ({count} {inv_word}) ---')
        print(f'Input tokens:  {inp:,}')
        print(f'Output tokens: {out:,}')
        print(f'Cache read:    {cr:,}')
        print(f'Cache create:  {cc:,}')
        print(f'Cost:          ${cost:.4f}')
        print(f'Time:          {format_duration(dur)}')

    label = operation or 'all operations'

    if session_start:
        ts_idx = col_map.get('timestamp', -1)
        session_rows = []
        if ts_idx >= 0:
            session_rows = [r for r in rows
                            if ts_idx < len(r) and r[ts_idx] >= session_start]

        if session_rows:
            _print_section(f'This session: {label}', *_accumulate(session_rows))
            print()

        if rows:
            _print_section(f'Project total: {label}', *_accumulate(rows))
    else:
        if not rows:
            label_str = f' for operation: {operation}' if operation else ''
            print(f'No cost data{label_str}.')
            return
        count, inp, out, cr, cc, cost, dur = _accumulate(rows)
        print(f'--- Cost Summary: {label} ---')
        print(f'Invocations:   {count}')
        print(f'Input tokens:  {inp:,}')
        print(f'Output tokens: {out:,}')
        print(f'Cache read:    {cr:,}')
        print(f'Cache create:  {cc:,}')
        print(f'Total cost:    ${cost:.4f}')
        print(f'Total time:    {format_duration(dur)}')
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `python3 -m pytest tests/test_costs.py -v`
Expected: All tests PASS (including existing tests — the no-session_start path preserves old format)

- [ ] **Step 5: Commit**

```bash
git add scripts/lib/python/storyforge/costs.py tests/test_costs.py
git commit -m "Add session-scoped cost summary with human-readable durations"
git push
```

---

### Task 3: Add system parameter to API invoke family + tests

**Files:**
- Modify: `scripts/lib/python/storyforge/api.py`
- Extend: `tests/test_api.py`

- [ ] **Step 1: Write failing tests for invoke with system parameter**

Add to `tests/test_api.py`:

```python
from unittest.mock import patch, MagicMock


class TestInvokeSystemParam:
    @patch('storyforge.api._api_request')
    @patch('storyforge.api.get_api_key', return_value='test-key')
    def test_invoke_without_system_omits_key(self, mock_key, mock_req):
        from storyforge.api import invoke
        mock_req.return_value = {
            'content': [{'type': 'text', 'text': 'ok'}],
            'usage': {'input_tokens': 10, 'output_tokens': 5},
        }
        invoke('hello', 'claude-sonnet-4-6', max_tokens=100)
        body = mock_req.call_args[0][1]
        assert 'system' not in body
        assert body['messages'] == [{'role': 'user', 'content': 'hello'}]

    @patch('storyforge.api._api_request')
    @patch('storyforge.api.get_api_key', return_value='test-key')
    def test_invoke_with_system_includes_key(self, mock_key, mock_req):
        from storyforge.api import invoke
        mock_req.return_value = {
            'content': [{'type': 'text', 'text': 'ok'}],
            'usage': {'input_tokens': 10, 'output_tokens': 5},
        }
        system_blocks = [
            {'type': 'text', 'text': 'You are helpful.'},
            {'type': 'text', 'text': 'Reference material here.',
             'cache_control': {'type': 'ephemeral'}},
        ]
        invoke('hello', 'claude-sonnet-4-6', max_tokens=100, system=system_blocks)
        body = mock_req.call_args[0][1]
        assert body['system'] == system_blocks
        assert body['messages'] == [{'role': 'user', 'content': 'hello'}]
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python3 -m pytest tests/test_api.py::TestInvokeSystemParam -v`
Expected: FAIL — `invoke() got an unexpected keyword argument 'system'`

- [ ] **Step 3: Add system parameter to invoke()**

In `scripts/lib/python/storyforge/api.py`, change the `invoke` function signature and body (lines 111-135):

Replace:

```python
def invoke(prompt: str, model: str, max_tokens: int = 4096, label: str = '',
           timeout: int = API_TIMEOUT) -> dict:
    """Call the Anthropic Messages API.

    Args:
        prompt: The user message text.
        model: Model ID (e.g., 'claude-opus-4-6').
        max_tokens: Maximum output tokens.
        label: Optional label for heartbeat messages (e.g., 'revision pass 3').
        timeout: Socket timeout in seconds (default API_TIMEOUT).

    Returns:
        Full API response dict.
    """
    body = {
        'model': model,
        'max_tokens': max_tokens,
        'messages': [{'role': 'user', 'content': prompt}],
    }
```

With:

```python
def invoke(prompt: str, model: str, max_tokens: int = 4096, label: str = '',
           timeout: int = API_TIMEOUT, system: list[dict] | None = None) -> dict:
    """Call the Anthropic Messages API.

    Args:
        prompt: The user message text.
        model: Model ID (e.g., 'claude-opus-4-6').
        max_tokens: Maximum output tokens.
        label: Optional label for heartbeat messages (e.g., 'revision pass 3').
        timeout: Socket timeout in seconds (default API_TIMEOUT).
        system: Optional list of system content blocks with cache_control.

    Returns:
        Full API response dict.
    """
    body = {
        'model': model,
        'max_tokens': max_tokens,
        'messages': [{'role': 'user', 'content': prompt}],
    }
    if system:
        body['system'] = system
```

- [ ] **Step 4: Add system parameter to invoke_to_file()**

Change the signature and call (lines 138-153):

Replace:

```python
def invoke_to_file(prompt: str, model: str, log_file: str, max_tokens: int = 4096, label: str = '',
                   timeout: int = API_TIMEOUT) -> dict:
    """Call the API and write the response to a JSON file.

    Args:
        prompt: The user message text.
        model: Model ID.
        log_file: Path to write the JSON response.
        max_tokens: Maximum output tokens.
        label: Optional label for heartbeat messages.
        timeout: Socket timeout in seconds (default API_TIMEOUT).

    Returns:
        Full API response dict.
    """
    response = invoke(prompt, model, max_tokens, label=label, timeout=timeout)
```

With:

```python
def invoke_to_file(prompt: str, model: str, log_file: str, max_tokens: int = 4096, label: str = '',
                   timeout: int = API_TIMEOUT, system: list[dict] | None = None) -> dict:
    """Call the API and write the response to a JSON file.

    Args:
        prompt: The user message text.
        model: Model ID.
        log_file: Path to write the JSON response.
        max_tokens: Maximum output tokens.
        label: Optional label for heartbeat messages.
        timeout: Socket timeout in seconds (default API_TIMEOUT).
        system: Optional list of system content blocks with cache_control.

    Returns:
        Full API response dict.
    """
    response = invoke(prompt, model, max_tokens, label=label, timeout=timeout, system=system)
```

- [ ] **Step 5: Add system parameter to invoke_api()**

Change the signature and call (lines 160-173):

Replace:

```python
def invoke_api(prompt: str, model: str, max_tokens: int = 4096, label: str = '',
               timeout: int = API_TIMEOUT) -> str:
```

With:

```python
def invoke_api(prompt: str, model: str, max_tokens: int = 4096, label: str = '',
               timeout: int = API_TIMEOUT, system: list[dict] | None = None) -> str:
```

And change the invoke call inside it from:

```python
        response = invoke(prompt, model, max_tokens, label=label, timeout=timeout)
```

To:

```python
        response = invoke(prompt, model, max_tokens, label=label, timeout=timeout, system=system)
```

- [ ] **Step 6: Run tests to verify they pass**

Run: `python3 -m pytest tests/test_api.py -v`
Expected: All tests PASS

- [ ] **Step 7: Commit**

```bash
git add scripts/lib/python/storyforge/api.py tests/test_api.py
git commit -m "Add system parameter to invoke family for prompt caching"
git push
```

---

### Task 4: build_batch_request() helper + tests

**Files:**
- Modify: `scripts/lib/python/storyforge/api.py`
- Create: `tests/test_prompt_caching.py`

- [ ] **Step 1: Write failing tests for build_batch_request**

Create `tests/test_prompt_caching.py`:

```python
"""Tests for prompt caching infrastructure."""

import json


class TestBuildBatchRequest:
    def test_without_system(self):
        from storyforge.api import build_batch_request
        result = build_batch_request('scene-1', 'Write a scene.', 'claude-opus-4-6', 8192)
        assert result['custom_id'] == 'scene-1'
        assert result['params']['model'] == 'claude-opus-4-6'
        assert result['params']['max_tokens'] == 8192
        assert result['params']['messages'] == [{'role': 'user', 'content': 'Write a scene.'}]
        assert 'system' not in result['params']

    def test_with_system(self):
        from storyforge.api import build_batch_request
        system = [
            {'type': 'text', 'text': 'Craft engine content here.'},
            {'type': 'text', 'text': 'Voice guide here.',
             'cache_control': {'type': 'ephemeral'}},
        ]
        result = build_batch_request('scene-1', 'Write a scene.', 'claude-opus-4-6', 8192,
                                     system=system)
        assert result['params']['system'] == system
        assert result['params']['messages'] == [{'role': 'user', 'content': 'Write a scene.'}]

    def test_serializes_to_valid_jsonl(self):
        from storyforge.api import build_batch_request
        system = [{'type': 'text', 'text': 'Context.',
                   'cache_control': {'type': 'ephemeral'}}]
        result = build_batch_request('s1', 'prompt', 'claude-sonnet-4-6', 4096, system=system)
        line = json.dumps(result)
        parsed = json.loads(line)
        assert parsed['custom_id'] == 's1'
        assert parsed['params']['system'][0]['cache_control']['type'] == 'ephemeral'

    def test_default_max_tokens(self):
        from storyforge.api import build_batch_request
        result = build_batch_request('s1', 'prompt', 'claude-sonnet-4-6')
        assert result['params']['max_tokens'] == 4096
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python3 -m pytest tests/test_prompt_caching.py::TestBuildBatchRequest -v`
Expected: FAIL — `ImportError: cannot import name 'build_batch_request'`

- [ ] **Step 3: Implement build_batch_request**

Add to `scripts/lib/python/storyforge/api.py` before the `# ============================================================================` Batch API section comment (before line 226):

```python
def build_batch_request(custom_id: str, prompt: str, model: str,
                        max_tokens: int = 4096,
                        system: list[dict] | None = None) -> dict:
    """Build a single batch request item (one JSONL line).

    Args:
        custom_id: Unique identifier for this request in the batch.
        prompt: The user message text.
        model: Model ID.
        max_tokens: Maximum output tokens.
        system: Optional list of system content blocks with cache_control.

    Returns:
        Dict suitable for JSON serialization as one JSONL line.
    """
    params = {
        'model': model,
        'max_tokens': max_tokens,
        'messages': [{'role': 'user', 'content': prompt}],
    }
    if system:
        params['system'] = system
    return {'custom_id': custom_id, 'params': params}
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `python3 -m pytest tests/test_prompt_caching.py::TestBuildBatchRequest -v`
Expected: All 4 tests PASS

- [ ] **Step 5: Commit**

```bash
git add scripts/lib/python/storyforge/api.py tests/test_prompt_caching.py
git commit -m "Add build_batch_request helper for standardized batch construction"
git push
```

---

### Task 5: build_shared_context() + tests

**Files:**
- Modify: `scripts/lib/python/storyforge/common.py`
- Extend: `tests/test_prompt_caching.py`

- [ ] **Step 1: Write failing tests for build_shared_context**

Add to `tests/test_prompt_caching.py`:

```python
import os


class TestBuildSharedContext:
    def test_returns_list_of_dicts(self, fixture_dir, plugin_dir):
        from storyforge.common import build_shared_context
        result = build_shared_context(fixture_dir, model='claude-sonnet-4-6')
        assert isinstance(result, list)
        assert len(result) > 0
        for block in result:
            assert block['type'] == 'text'
            assert 'text' in block

    def test_tier1_blocks_come_first(self, fixture_dir, plugin_dir):
        from storyforge.common import build_shared_context
        result = build_shared_context(fixture_dir, model='claude-sonnet-4-6')
        texts = [b['text'] for b in result]
        # Craft engine is tier 1, character bible is tier 2
        craft_idx = next((i for i, t in enumerate(texts) if 'Craft Engine' in t), None)
        bible_idx = next((i for i, t in enumerate(texts) if 'Character Bible' in t), None)
        assert craft_idx is not None
        assert bible_idx is not None
        assert craft_idx < bible_idx

    def test_has_cache_control_breakpoints(self, fixture_dir, plugin_dir):
        from storyforge.common import build_shared_context
        result = build_shared_context(fixture_dir, model='claude-sonnet-4-6')
        blocks_with_cc = [b for b in result if 'cache_control' in b]
        # Should have at least one breakpoint (possibly two if both tiers meet threshold)
        assert len(blocks_with_cc) >= 1

    def test_skips_missing_files(self, tmp_path):
        from storyforge.common import build_shared_context, _shared_context_cache
        _shared_context_cache.clear()
        # Empty project dir with no reference files
        project_dir = str(tmp_path / 'empty')
        os.makedirs(os.path.join(project_dir, 'reference'), exist_ok=True)
        result = build_shared_context(project_dir, model='claude-sonnet-4-6')
        # Should still return blocks (tier 1 comes from plugin dir)
        assert isinstance(result, list)

    def test_in_process_cache(self, fixture_dir, plugin_dir):
        from storyforge.common import build_shared_context, _shared_context_cache
        _shared_context_cache.clear()
        result1 = build_shared_context(fixture_dir, model='claude-sonnet-4-6')
        result2 = build_shared_context(fixture_dir, model='claude-sonnet-4-6')
        assert result1 is result2  # Same object, not just equal

    def test_includes_project_references(self, fixture_dir, plugin_dir):
        from storyforge.common import build_shared_context
        result = build_shared_context(fixture_dir, model='claude-sonnet-4-6')
        all_text = ' '.join(b['text'] for b in result)
        # Fixture has these files
        assert 'Voice Guide' in all_text or 'voice-guide' in all_text.lower()
        assert 'Character Bible' in all_text or 'character-bible' in all_text.lower()

    def test_tier1_breakpoint_has_1h_ttl(self, fixture_dir, plugin_dir):
        from storyforge.common import build_shared_context
        result = build_shared_context(fixture_dir, model='claude-sonnet-4-6')
        # Find the tier 1 breakpoint (last block before project-level content)
        # It should have ttl if tier 1 meets threshold
        tier1_labels = ('Craft Engine', 'Scoring Rubrics', 'AI-Tell Vocabulary')
        tier1_end = -1
        for i, b in enumerate(result):
            if any(label in b['text'] for label in tier1_labels):
                tier1_end = i
        if tier1_end >= 0 and 'cache_control' in result[tier1_end]:
            # Verify the breakpoint TTL is extended (not the default 5m)
            assert result[tier1_end]['cache_control'].get('ttl') in (3600, '1h', None)
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python3 -m pytest tests/test_prompt_caching.py::TestBuildSharedContext -v`
Expected: FAIL — `ImportError: cannot import name 'build_shared_context'`

- [ ] **Step 3: Implement build_shared_context**

Add to `scripts/lib/python/storyforge/common.py` after the `extract_craft_sections` function (after line 238):

```python
# ============================================================================
# Shared context for prompt caching
# ============================================================================

_shared_context_cache: dict[str, list[dict]] = {}

# Minimum tokens per cache breakpoint (estimated at ~4 chars/token)
_MIN_CACHE_CHARS = {
    'opus': 4096 * 4,
    'sonnet': 2048 * 4,
    'haiku': 2048 * 4,
}


def _model_tier(model: str) -> str:
    """Map model name to pricing tier for cache threshold."""
    m = model.lower()
    if 'opus' in m:
        return 'opus'
    if 'haiku' in m:
        return 'haiku'
    return 'sonnet'


def _read_if_exists(path: str) -> str:
    """Read a file if it exists, return empty string otherwise."""
    if os.path.isfile(path):
        with open(path) as f:
            return f.read().strip()
    return ''


def build_shared_context(project_dir: str, model: str = '') -> list[dict]:
    """Assemble project reference materials as cacheable system blocks.

    Two-tier structure:
    - Tier 1 (1h TTL): Plugin-level references (craft engine, rubrics, AI-tell words)
    - Tier 2 (5m TTL): Project-level references (bibles, voice guide, registries)

    Results are cached in-process so repeated calls don't re-read files.

    Args:
        project_dir: Path to the Storyforge project.
        model: Model ID for determining minimum cache token threshold.

    Returns:
        List of content blocks for the API 'system' parameter.
    """
    cache_key = f'{project_dir}:{model}'
    if cache_key in _shared_context_cache:
        return _shared_context_cache[cache_key]

    plugin_dir = get_plugin_dir()
    min_chars = _MIN_CACHE_CHARS.get(_model_tier(model), 4096 * 4)

    # --- Tier 1: Plugin-level (near-permanent) ---
    tier1_sources = [
        (os.path.join(plugin_dir, 'references', 'craft-engine.md'), 'Craft Engine'),
        (os.path.join(plugin_dir, 'references', 'scoring-rubrics.md'), 'Scoring Rubrics'),
        (os.path.join(plugin_dir, 'references', 'ai-tell-words.csv'), 'AI-Tell Vocabulary'),
    ]

    tier1_blocks = []
    tier1_chars = 0
    for path, label in tier1_sources:
        content = _read_if_exists(path)
        if content:
            tier1_blocks.append({'type': 'text', 'text': f'=== {label} ===\n\n{content}'})
            tier1_chars += len(content) + len(label) + 10

    # --- Tier 2: Project-level (session-stable) ---
    ref_dir = os.path.join(project_dir, 'reference')
    tier2_sources = [
        (os.path.join(ref_dir, 'character-bible.md'), 'Character Bible'),
        (os.path.join(ref_dir, 'world-bible.md'), 'World Bible'),
        (os.path.join(ref_dir, 'voice-guide.md'), 'Voice Guide'),
        (os.path.join(ref_dir, 'voice-profile.csv'), 'Voice Profile'),
        (os.path.join(ref_dir, 'characters.csv'), 'Character Registry'),
        (os.path.join(ref_dir, 'locations.csv'), 'Location Registry'),
        (os.path.join(ref_dir, 'mice-threads.csv'), 'MICE Thread Registry'),
    ]

    tier2_blocks = []
    tier2_chars = 0
    for path, label in tier2_sources:
        content = _read_if_exists(path)
        if content:
            tier2_blocks.append({'type': 'text', 'text': f'=== {label} ===\n\n{content}'})
            tier2_chars += len(content) + len(label) + 10

    # --- Apply cache_control breakpoints ---
    blocks = []

    if tier1_blocks:
        if tier1_chars >= min_chars:
            # Tier 1 meets threshold — add breakpoint with extended TTL
            tier1_blocks[-1]['cache_control'] = {'type': 'ephemeral', 'ttl': 3600}
        blocks.extend(tier1_blocks)

    if tier2_blocks:
        cumulative_chars = tier1_chars + tier2_chars
        if cumulative_chars >= min_chars:
            # Cumulative prefix meets threshold — add breakpoint with default TTL
            tier2_blocks[-1]['cache_control'] = {'type': 'ephemeral'}
        blocks.extend(tier2_blocks)

    _shared_context_cache[cache_key] = blocks
    return blocks
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `python3 -m pytest tests/test_prompt_caching.py::TestBuildSharedContext -v`
Expected: All tests PASS

- [ ] **Step 5: Run full test suite to check for regressions**

Run: `python3 -m pytest tests/ -v --timeout=30 2>&1 | tail -20`
Expected: No regressions — `build_shared_context` is additive, no existing code calls it yet.

- [ ] **Step 6: Commit**

```bash
git add scripts/lib/python/storyforge/common.py tests/test_prompt_caching.py
git commit -m "Add build_shared_context for two-tier prompt caching"
git push
```

---

### Task 6: Integrate cmd_write (batch + direct)

**Files:**
- Modify: `scripts/lib/python/storyforge/cmd_write.py`
- Modify: `scripts/lib/python/storyforge/prompts.py`

**Context:** `cmd_write.py` builds batch requests at line 432-439 and has a direct invoke path at line 566. The prompt is built by `_build_prompt()` which calls `build_scene_prompt()` from `prompts.py`. `build_scene_prompt()` inlines: craft engine (line 722), AI-tell words (line 729), voice profile (line 733), and all reference files in api_mode (lines 692-703).

- [ ] **Step 1: Add system_context parameter to build_scene_prompt**

In `scripts/lib/python/storyforge/prompts.py`, add `system_context: bool = False` to the `build_scene_prompt()` signature. When `True`, skip inlining:
- Reference file reading loop (lines 692-703 where `api_mode` reads files with `=== FILE:` markers)
- Craft engine sections via `extract_craft_sections()` (line 722)
- AI-tell vocabulary loading via `load_ai_tell_words()` (line 729)
- Voice profile loading via `load_voice_profile()` (line 733)

Each of these sections should be wrapped in `if not system_context:` guards. The `build_weighted_directive()` call (craft-weights.csv) stays — it's project-specific weighted formatting, not raw reference material.

- [ ] **Step 2: Add system_context parameter to build_scene_prompt_from_briefs if it exists**

Check if `build_scene_prompt_from_briefs()` exists in prompts.py and apply the same pattern. If it delegates to `build_scene_prompt()`, the parameter just needs to be passed through.

- [ ] **Step 3: Update _build_prompt in cmd_write.py**

Find `_build_prompt()` in cmd_write.py and add a `system_context=False` parameter. Pass it through to `build_scene_prompt()` / `build_scene_prompt_from_briefs()`.

- [ ] **Step 4: Update batch construction in _run_batch_mode**

In `cmd_write.py`, in the `_run_batch_mode()` function:

1. Before the scene loop, add:
```python
from storyforge.common import build_shared_context
system = build_shared_context(project_dir, model=model)
```

2. Change the prompt building call to pass `system_context=True`:
```python
prompt = _build_prompt(scene_id, project_dir, coaching, use_briefs, system_context=True)
```

3. Replace the inline dict construction (lines 432-439):
```python
from storyforge.api import build_batch_request
request = build_batch_request(scene_id, prompt, model, 8192, system=system)
```

- [ ] **Step 5: Update direct mode in _run_direct_mode**

In the `_run_direct_mode()` function:

1. Build shared context once before the loop:
```python
from storyforge.common import build_shared_context
system = build_shared_context(project_dir, model=model)
```

2. Pass `system_context=True` to `_build_prompt()`.

3. Pass `system=system` to the `invoke_to_file()` call (line 566).

- [ ] **Step 6: Add session_start to main() and print_summary**

In `cmd_write.py`:

1. At the top of `main()` (after `args = parse_args(...)` and `project_dir = detect_project_root()`), add:
```python
from datetime import datetime
session_start = datetime.now().strftime('%Y-%m-%dT%H:%M:%S')
```

2. Update the `print_summary` call (line 211) to:
```python
print_summary(project_dir, 'draft', session_start=session_start)
```

- [ ] **Step 7: Run tests and verify no regressions**

Run: `python3 -m pytest tests/ -v --timeout=30 -k "write or prompt or draft" 2>&1 | tail -30`
Expected: All existing tests PASS. The `system_context=False` default preserves old behavior for any test that calls `build_scene_prompt()` directly.

- [ ] **Step 8: Commit**

```bash
git add scripts/lib/python/storyforge/cmd_write.py scripts/lib/python/storyforge/prompts.py
git commit -m "Add prompt caching to cmd_write (batch + direct)"
git push
```

---

### Task 7: Integrate cmd_score (batch + direct)

**Files:**
- Modify: `scripts/lib/python/storyforge/cmd_score.py`
- Modify: `scripts/lib/python/storyforge/scoring.py`

**Context:** `cmd_score.py` has two batch paths: craft scoring (line 876) and fidelity scoring (line 1044). It also has direct `invoke_to_file` calls for act-level (line 1186), novel-level (line 1264), and narrative scoring (line 1340). The prompts are built by functions in `scoring.py` and inline in `cmd_score.py`. `scoring.py` reads per-principle rubric sections from scoring-rubrics.md (line 784) — this per-principle extraction stays in the user message since it's specific to each scoring call; the full rubrics file is in shared context for general reference.

- [ ] **Step 1: Add system parameter to batch construction for craft scoring**

In `cmd_score.py`, in the craft scoring batch loop:

1. Before the loop, add:
```python
from storyforge.common import build_shared_context
system = build_shared_context(project_dir, model=eval_model)
```

2. Replace the inline batch dict (lines 876-883) with:
```python
from storyforge.api import build_batch_request
request = build_batch_request(sid, prompt, eval_model, 4096, system=system)
```

- [ ] **Step 2: Add system parameter to fidelity scoring batch**

Same pattern for the fidelity batch (lines 1044-1051):
```python
request = build_batch_request(f'fidelity-{sid}', prompt, sonnet_model, 2048, system=system)
```

- [ ] **Step 3: Pass system to direct invoke_to_file calls**

For each direct `invoke_to_file` call in cmd_score.py (lines 961, 1073, 1186, 1264, 1340), add `system=system`.

- [ ] **Step 4: Add session_start to main() and print_summary**

1. Record `session_start` at top of `main()`.
2. Update `print_summary` call (line 413) to include `session_start=session_start`.

- [ ] **Step 5: Run tests**

Run: `python3 -m pytest tests/ -v --timeout=30 -k "scor" 2>&1 | tail -30`
Expected: All tests PASS

- [ ] **Step 6: Commit**

```bash
git add scripts/lib/python/storyforge/cmd_score.py
git commit -m "Add prompt caching to cmd_score (batch + direct)"
git push
```

---

### Task 8: Integrate cmd_evaluate (batch + direct)

**Files:**
- Modify: `scripts/lib/python/storyforge/cmd_evaluate.py`

**Context:** `cmd_evaluate.py` has one batch path (line 1054) for evaluator panels, and direct calls for synthesis (line 1217) and assessment (line 1285). The evaluator prompts are built inline in the module.

- [ ] **Step 1: Add system parameter to evaluator batch**

1. Before the batch loop, call `build_shared_context(project_dir, model=eval_models[0])`.
2. Replace inline dict (lines 1054-1061) with `build_batch_request()`.

- [ ] **Step 2: Pass system to synthesis and assessment invoke_to_file calls**

Add `system=system` to the `invoke_to_file` calls at lines 1217 and 1285.

- [ ] **Step 3: Add session_start to main() and print_summary**

1. Record `session_start` at top of `main()`.
2. Update the three `print_summary` calls (lines 1358-1360) to include `session_start=session_start`.

- [ ] **Step 4: Run tests**

Run: `python3 -m pytest tests/ -v --timeout=30 -k "eval" 2>&1 | tail -30`
Expected: All tests PASS

- [ ] **Step 5: Commit**

```bash
git add scripts/lib/python/storyforge/cmd_evaluate.py
git commit -m "Add prompt caching to cmd_evaluate (batch + direct)"
git push
```

---

### Task 9: Integrate cmd_extract (batch + direct)

**Files:**
- Modify: `scripts/lib/python/storyforge/cmd_extract.py`

**Context:** `cmd_extract.py` has three batch phases: skeleton (line 371), intent (line 467), briefs (line 579). Direct calls for characterization (line 311), knowledge fixing (line 663), and physical state fixing (line 725). Prompts use `registries_text` parameter from `extract.py` — much of the shared content already flows as a parameter rather than being inlined by the builder.

- [ ] **Step 1: Add system parameter to all three batch phases**

For each phase batch loop:
1. Call `build_shared_context(project_dir, model=model)` once before the phase.
2. Replace inline dicts with `build_batch_request()`.

Phase 1 (lines 371-378), Phase 2 (lines 467-474), Phase 3 (lines 579-586).

- [ ] **Step 2: Pass system to direct invoke_to_file calls**

Add `system=system` to calls at lines 311, 663, 725.

- [ ] **Step 3: Add session_start to main() and print_summary**

1. Record `session_start` at top of `main()`.
2. Update `print_summary` call (line 209) to include `session_start=session_start`.

- [ ] **Step 4: Run tests**

Run: `python3 -m pytest tests/ -v --timeout=30 -k "extract" 2>&1 | tail -30`
Expected: All tests PASS

- [ ] **Step 5: Commit**

```bash
git add scripts/lib/python/storyforge/cmd_extract.py
git commit -m "Add prompt caching to cmd_extract (batch + direct)"
git push
```

---

### Task 10: Integrate cmd_revise (direct only)

**Files:**
- Modify: `scripts/lib/python/storyforge/cmd_revise.py`
- Modify: `scripts/lib/python/storyforge/revision.py`

**Context:** `cmd_revise.py` uses direct API calls only (no batch). Main invoke points: line 204 (redraft), line 1548 and 2213 (revision steps), line 1149 and 1215 (interactive). `revision.py` builds prompts that inline craft-engine.md (line 232), scoring-rubrics.md (line 310), exemplars.csv (line 358), and reference files (lines 590-607).

- [ ] **Step 1: Add system_context parameter to build_revision_prompt**

In `scripts/lib/python/storyforge/revision.py`, add `system_context: bool = False` to `build_revision_prompt()`. When `True`, skip inlining:
- `extract_craft_sections()` (craft engine)
- `_load_rubric_sections()` (scoring rubrics)
- Reference file reading loop (voice-guide.md, scenes.csv, intent.csv, knowledge.csv at lines 590-607)

Keep: pass-specific configuration, scene prose, brief data, overrides, exemplars (these are per-pass/per-principle, not shared project context — the spec lists exemplars for removal but they're pass-filtered content that belongs in the user message).

- [ ] **Step 2: Build shared context once per session**

In `cmd_revise.py`, early in the revision orchestration (after project_dir is known):
```python
from storyforge.common import build_shared_context
system = build_shared_context(project_dir, model=pass_model)
```

- [ ] **Step 3: Pass system to all invoke_to_file / invoke_api calls**

Add `system=system` to the `invoke_to_file` calls at lines 204, 1548, 2213, and to `invoke_api` calls at lines 1149, 1215. Pass `system_context=True` to `build_revision_prompt()`.

- [ ] **Step 4: Add session_start to main() and print_summary**

1. Record `session_start` at top of `main()`.
2. Update `print_summary` call (line 2436) to include `session_start=session_start`.

- [ ] **Step 5: Run tests**

Run: `python3 -m pytest tests/ -v --timeout=30 -k "revis" 2>&1 | tail -30`
Expected: All tests PASS

- [ ] **Step 6: Commit**

```bash
git add scripts/lib/python/storyforge/cmd_revise.py scripts/lib/python/storyforge/revision.py
git commit -m "Add prompt caching to cmd_revise (direct calls)"
git push
```

---

### Task 11: Integrate cmd_elaborate (batch + direct)

**Files:**
- Modify: `scripts/lib/python/storyforge/cmd_elaborate.py`
- Modify: `scripts/lib/python/storyforge/prompts_elaborate.py`

**Context:** `cmd_elaborate.py` has direct invoke for stage prompts (line 578), gap-fill batch (line 300), MICE fill (line 161), and knowledge fixing (line 396). `prompts_elaborate.py` inlines via `_existing_refs()` (character bible, world bible, voice guide, story architecture at lines 48-64) and `_craft_principles()` (craft engine at lines 67-88).

- [ ] **Step 1: Add system_context parameter to elaborate prompt builders**

In `scripts/lib/python/storyforge/prompts_elaborate.py`:
- Add `system_context: bool = False` to `build_spine_prompt()`, `build_architecture_prompt()`, `build_map_prompt()`, `build_briefs_prompt()`, `build_voice_prompt()`.
- When `True`, skip calling `_existing_refs()` and `_craft_principles()`.

- [ ] **Step 2: Update cmd_elaborate to use shared context**

1. Build `system = build_shared_context(project_dir, model=stage_model)` before invoking.
2. Pass `system_context=True` to prompt builders.
3. Replace gap-fill batch inline dicts (line 300-307) with `build_batch_request()`.
4. Pass `system=system` to all `invoke_to_file` and `invoke` calls.

- [ ] **Step 3: Add session_start and update print_summary calls**

1. Record `session_start` at top of `main()`.
2. Update `print_summary` calls (lines 489, 836) with `session_start=session_start`.

- [ ] **Step 4: Run tests**

Run: `python3 -m pytest tests/ -v --timeout=30 -k "elaborate" 2>&1 | tail -30`
Expected: All tests PASS

- [ ] **Step 5: Commit**

```bash
git add scripts/lib/python/storyforge/cmd_elaborate.py scripts/lib/python/storyforge/prompts_elaborate.py
git commit -m "Add prompt caching to cmd_elaborate (batch + direct)"
git push
```

---

### Task 12: Integrate cmd_enrich (batch)

**Files:**
- Modify: `scripts/lib/python/storyforge/cmd_enrich.py`

**Context:** `cmd_enrich.py` has batch requests at line 658 and a direct invoke at line 728.

- [ ] **Step 1: Update batch and direct paths**

1. Build `system = build_shared_context(project_dir, model=model)` once.
2. Replace inline dict (lines 658-665) with `build_batch_request()`.
3. Pass `system=system` to `invoke_to_file` (line 728).

- [ ] **Step 2: Add session_start and update print_summary**

1. Record `session_start` at top of `main()`.
2. Update `print_summary` call (line 863) with `session_start=session_start`.

- [ ] **Step 3: Run tests and commit**

Run: `python3 -m pytest tests/ -v --timeout=30 -k "enrich" 2>&1 | tail -30`

```bash
git add scripts/lib/python/storyforge/cmd_enrich.py
git commit -m "Add prompt caching to cmd_enrich"
git push
```

---

### Task 13: Integrate cmd_timeline (batch + direct)

**Files:**
- Modify: `scripts/lib/python/storyforge/cmd_timeline.py`

**Context:** `cmd_timeline.py` has batch at line 321, direct invoke_to_file at lines 399, 490, and invoke_api at lines 411, 488.

- [ ] **Step 1: Update batch and direct paths**

1. Build `system = build_shared_context(project_dir, model=haiku_model)` once.
2. Replace inline dict (lines 321-328) with `build_batch_request()`.
3. Pass `system=system` to all `invoke_to_file` and `invoke_api` calls.

- [ ] **Step 2: Add session_start and update print_summary**

1. Record `session_start` at top of `main()`.
2. Update `print_summary` calls (lines 570, 645, 646) with `session_start=session_start`.

- [ ] **Step 3: Run tests and commit**

Run: `python3 -m pytest tests/ -v --timeout=30 -k "timeline" 2>&1 | tail -30`

```bash
git add scripts/lib/python/storyforge/cmd_timeline.py
git commit -m "Add prompt caching to cmd_timeline"
git push
```

---

### Task 14: Integrate cmd_scenes_setup (batch + direct)

**Files:**
- Modify: `scripts/lib/python/storyforge/cmd_scenes_setup.py`

**Context:** `cmd_scenes_setup.py` has batch at line 521 and direct invoke at line 317.

- [ ] **Step 1: Update batch and direct paths**

1. Build `system = build_shared_context(project_dir, model=model)` once.
2. Replace inline dict (lines 521-528) with `build_batch_request()`.
3. Pass `system=system` to `invoke_to_file` (line 317).

- [ ] **Step 2: Add session_start and update print_summary**

1. Record `session_start` at top of `main()`.
2. Update `print_summary` calls (lines 865, 896) with `session_start=session_start`.

- [ ] **Step 3: Run tests and commit**

Run: `python3 -m pytest tests/ -v --timeout=30 -k "scene" 2>&1 | tail -30`

```bash
git add scripts/lib/python/storyforge/cmd_scenes_setup.py
git commit -m "Add prompt caching to cmd_scenes_setup"
git push
```

---

### Task 15: Full regression test + version bump

**Files:**
- Modify: `.claude-plugin/plugin.json`

- [ ] **Step 1: Run the complete test suite**

Run: `python3 -m pytest tests/ -v --timeout=60 2>&1 | tail -40`
Expected: All tests PASS with no regressions.

- [ ] **Step 2: Bump version**

In `.claude-plugin/plugin.json`, bump the minor version (e.g., `1.16.3` -> `1.17.0`) since this is a new feature.

- [ ] **Step 3: Final commit**

```bash
git add .claude-plugin/plugin.json
git commit -m "Bump version to 1.17.0"
git push
```
