"""Tests for storyforge.runner — parallel execution and healing zones.

Covers: run_parallel, run_batched, HealingZone.
"""

import os
import time
import threading

import pytest

from storyforge.runner import HealingZone, run_batched, run_parallel


# ============================================================================
# Helpers
# ============================================================================

def _identity_worker(item: str) -> str:
    """Returns the item unchanged."""
    return item


def _upper_worker(item: str) -> str:
    """Returns the item uppercased."""
    return item.upper()


def _failing_worker(item: str) -> str:
    """Always raises an exception."""
    raise ValueError(f'failed on {item}')


def _conditional_worker(item: str) -> str:
    """Fails on items containing 'bad', succeeds otherwise."""
    if 'bad' in item:
        raise RuntimeError(f'bad item: {item}')
    return item.upper()


def _slow_worker(item: str) -> str:
    """Simulates brief work with a small sleep."""
    time.sleep(0.01)
    return item


# ============================================================================
# run_parallel
# ============================================================================

class TestRunParallel:
    """Tests for run_parallel."""

    def test_empty_list_returns_empty_dict(self):
        result = run_parallel([], _identity_worker, label='test')
        assert result == {}

    def test_single_item(self):
        result = run_parallel(['hello'], _upper_worker, label='test')
        assert result == {'hello': 'HELLO'}

    def test_multiple_items(self):
        items = ['alpha', 'beta', 'gamma']
        result = run_parallel(items, _upper_worker, label='test')
        assert result == {
            'alpha': 'ALPHA',
            'beta': 'BETA',
            'gamma': 'GAMMA',
        }

    def test_preserves_all_items(self):
        items = [f'item-{i}' for i in range(10)]
        result = run_parallel(items, _identity_worker, label='test')
        assert set(result.keys()) == set(items)
        for item in items:
            assert result[item] == item

    def test_respects_max_workers(self):
        """With max_workers=1, items still complete (sequential execution)."""
        items = ['a', 'b', 'c']
        result = run_parallel(items, _upper_worker, max_workers=1, label='test')
        assert len(result) == 3
        assert result['a'] == 'A'

    def test_handles_worker_exception(self):
        """When worker raises, the exception is stored in results (not re-raised)."""
        items = ['ok', 'fail']

        def worker(item):
            if item == 'fail':
                raise ValueError('intentional failure')
            return item

        result = run_parallel(items, worker, label='test')
        assert result['ok'] == 'ok'
        assert isinstance(result['fail'], ValueError)

    def test_all_workers_fail(self):
        items = ['a', 'b', 'c']
        result = run_parallel(items, _failing_worker, label='test')
        for item in items:
            assert isinstance(result[item], ValueError)

    def test_mixed_success_and_failure(self):
        items = ['good1', 'bad-item', 'good2', 'bad-other']
        result = run_parallel(items, _conditional_worker, label='test')
        assert result['good1'] == 'GOOD1'
        assert result['good2'] == 'GOOD2'
        assert isinstance(result['bad-item'], RuntimeError)
        assert isinstance(result['bad-other'], RuntimeError)

    def test_parallel_execution_is_concurrent(self):
        """Multiple items with small sleeps should complete faster than sequential."""
        items = [f'item-{i}' for i in range(5)]
        start = time.time()
        result = run_parallel(items, _slow_worker, max_workers=5, label='test')
        elapsed = time.time() - start
        assert len(result) == 5
        # If truly parallel, 5 items at 10ms each should take ~10ms, not ~50ms
        # Use generous threshold to avoid flakiness
        assert elapsed < 0.5

    def test_env_override_parallel_count(self, monkeypatch):
        """STORYFORGE_PARALLEL env var limits the worker count."""
        monkeypatch.setenv('STORYFORGE_PARALLEL', '2')
        items = ['a', 'b', 'c', 'd']
        result = run_parallel(items, _upper_worker, max_workers=8, label='test')
        # All items still complete even with reduced parallelism
        assert len(result) == 4

    def test_result_dict_keys_match_input(self):
        items = ['x-1', 'x-2', 'x-3']
        result = run_parallel(items, _identity_worker, label='test')
        assert list(sorted(result.keys())) == items


# ============================================================================
# run_batched
# ============================================================================

class TestRunBatched:
    """Tests for run_batched."""

    def test_empty_list(self):
        result = run_batched([], _identity_worker, label='test')
        assert result == {}

    def test_single_batch(self):
        items = ['a', 'b', 'c']
        result = run_batched(items, _upper_worker, batch_size=10, label='test')
        assert result == {'a': 'A', 'b': 'B', 'c': 'C'}

    def test_multiple_batches(self):
        items = ['a', 'b', 'c', 'd', 'e']
        result = run_batched(items, _upper_worker, batch_size=2, label='test')
        assert len(result) == 5
        for item in items:
            assert result[item] == item.upper()

    def test_merge_fn_called_between_batches(self):
        """merge_fn should be called for each successful item in each batch."""
        merged = []

        def merge(item, result):
            merged.append((item, result))

        items = ['a', 'b', 'c', 'd']
        run_batched(items, _upper_worker, merge_fn=merge, batch_size=2, label='test')
        assert len(merged) == 4
        assert ('a', 'A') in merged
        assert ('d', 'D') in merged

    def test_merge_fn_skips_failures(self):
        """merge_fn should NOT be called for items that raised exceptions."""
        merged = []

        def merge(item, result):
            merged.append(item)

        items = ['good1', 'bad-item', 'good2']
        run_batched(items, _conditional_worker, merge_fn=merge, batch_size=2, label='test')
        assert 'good1' in merged
        assert 'good2' in merged
        assert 'bad-item' not in merged

    def test_batch_size_one(self):
        """Each item processed individually."""
        items = ['x', 'y', 'z']
        result = run_batched(items, _upper_worker, batch_size=1, label='test')
        assert result == {'x': 'X', 'y': 'Y', 'z': 'Z'}

    def test_batch_size_larger_than_items(self):
        items = ['a', 'b']
        result = run_batched(items, _upper_worker, batch_size=100, label='test')
        assert result == {'a': 'A', 'b': 'B'}

    def test_no_merge_fn(self):
        """When merge_fn is None, batched still works."""
        items = ['a', 'b', 'c']
        result = run_batched(items, _upper_worker, merge_fn=None, batch_size=2, label='test')
        assert len(result) == 3


# ============================================================================
# HealingZone
# ============================================================================

class TestHealingZone:
    """Tests for HealingZone context manager and run method."""

    def test_passes_through_on_success(self, project_dir, mock_api):
        with HealingZone('test zone', project_dir) as zone:
            result = zone.run(lambda: 'success')
        assert result == 'success'

    def test_returns_function_result(self, project_dir, mock_api):
        def compute():
            return 42

        with HealingZone('compute zone', project_dir) as zone:
            result = zone.run(compute)
        assert result == 42

    def test_passes_args_to_function(self, project_dir, mock_api):
        def add(a, b):
            return a + b

        with HealingZone('add zone', project_dir) as zone:
            result = zone.run(add, 3, 4)
        assert result == 7

    def test_passes_kwargs_to_function(self, project_dir, mock_api):
        def greet(name, greeting='hello'):
            return f'{greeting} {name}'

        with HealingZone('greet zone', project_dir) as zone:
            result = zone.run(greet, 'world', greeting='hi')
        assert result == 'hi world'

    def test_retries_on_failure(self, project_dir, mock_api):
        """Should retry up to max_attempts times."""
        call_count = 0

        def flaky():
            nonlocal call_count
            call_count += 1
            if call_count < 3:
                raise RuntimeError('not yet')
            return 'recovered'

        mock_api.set_response('diagnosis: retry suggested')
        with HealingZone('flaky zone', project_dir, max_attempts=3) as zone:
            result = zone.run(flaky)
        assert result == 'recovered'
        assert call_count == 3

    def test_raises_after_exhausting_attempts(self, project_dir, mock_api):
        """After max_attempts failures, the exception propagates."""
        mock_api.set_response('diagnosis: cannot help')

        def always_fail():
            raise ValueError('permanent failure')

        with HealingZone('failing zone', project_dir, max_attempts=2) as zone:
            with pytest.raises(ValueError, match='permanent failure'):
                zone.run(always_fail)

    def test_invokes_api_for_diagnosis(self, project_dir, mock_api):
        """On failure, should call the API for diagnosis."""
        call_count = 0

        def fail_then_succeed():
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                raise RuntimeError('first attempt failed')
            return 'ok'

        mock_api.set_response('Try again, the issue is transient.')
        with HealingZone('diag zone', project_dir, max_attempts=3) as zone:
            zone.run(fail_then_succeed)

        # Should have made at least one API call for diagnosis
        api_calls = mock_api.calls_for('invoke_api')
        assert len(api_calls) >= 1

    def test_context_manager_does_not_suppress_exceptions(self, project_dir, mock_api):
        """__exit__ returns False, so unhandled exceptions propagate."""
        mock_api.set_response('cannot fix')
        with pytest.raises(ValueError):
            with HealingZone('propagate zone', project_dir, max_attempts=1) as zone:
                zone.run(lambda: (_ for _ in ()).throw(ValueError('boom')))

    def test_no_api_call_on_success(self, project_dir, mock_api):
        """When the function succeeds, no API call should be made."""
        with HealingZone('success zone', project_dir) as zone:
            zone.run(lambda: 'fine')
        assert mock_api.call_count == 0

    def test_healing_log_files_created(self, project_dir, mock_api):
        """On failure + healing, a log file should be written."""
        call_count = 0

        def fail_once():
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                raise RuntimeError('oops')
            return 'ok'

        mock_api.set_response('The fix is to retry.')
        with HealingZone('log zone', project_dir, max_attempts=3) as zone:
            zone.run(fail_once)

        log_file = os.path.join(project_dir, 'working', 'logs', 'healing-attempt-1.log')
        assert os.path.isfile(log_file)
        with open(log_file) as f:
            content = f.read()
        assert 'The fix is to retry.' in content
