"""Command-level tests for storyforge.runner module.

Tests run_parallel, run_batched, and HealingZone.
"""

import os

import pytest

from storyforge.runner import run_parallel, run_batched, HealingZone


# ============================================================================
# run_parallel
# ============================================================================

class TestRunParallel:
    def test_processes_all_items(self):
        items = ['a', 'b', 'c']
        results = run_parallel(items, str.upper, max_workers=2, label='letter')
        assert results == {'a': 'A', 'b': 'B', 'c': 'C'}

    def test_single_item(self):
        results = run_parallel(['x'], lambda x: x * 2, max_workers=1, label='item')
        assert results == {'x': 'xx'}

    def test_empty_items_raises(self):
        """Empty items list causes ValueError from ThreadPoolExecutor(max_workers=0)."""
        with pytest.raises(ValueError, match='max_workers'):
            run_parallel([], lambda x: x, max_workers=1, label='item')

    def test_failure_captured_as_exception(self):
        def fail_on_b(x):
            if x == 'b':
                raise ValueError('bad item')
            return x

        results = run_parallel(['a', 'b', 'c'], fail_on_b, max_workers=2, label='item')
        assert results['a'] == 'a'
        assert results['c'] == 'c'
        assert isinstance(results['b'], ValueError)

    def test_respects_max_workers(self):
        """max_workers is clamped to len(items)."""
        results = run_parallel(['a', 'b'], str.upper, max_workers=100, label='item')
        assert len(results) == 2

    def test_worker_receives_item(self):
        received = []
        def worker(item):
            received.append(item)
            return item
        run_parallel(['x', 'y'], worker, max_workers=1, label='item')
        assert set(received) == {'x', 'y'}


# ============================================================================
# run_batched
# ============================================================================

class TestRunBatched:
    def test_processes_all_items(self):
        results = run_batched(['a', 'b', 'c', 'd'], str.upper,
                              batch_size=2, label='letter')
        assert results == {'a': 'A', 'b': 'B', 'c': 'C', 'd': 'D'}

    def test_merge_fn_called(self):
        merged = {}
        def merge(item, result):
            merged[item] = result

        run_batched(['a', 'b'], str.upper, merge_fn=merge,
                    batch_size=2, label='item')
        assert merged == {'a': 'A', 'b': 'B'}

    def test_batch_size_larger_than_items(self):
        results = run_batched(['a'], str.upper, batch_size=10, label='item')
        assert results == {'a': 'A'}

    def test_empty_items(self):
        results = run_batched([], str.upper, batch_size=5, label='item')
        assert results == {}

    def test_merge_fn_skips_failures(self):
        merged = {}

        def fail_on_b(x):
            if x == 'b':
                raise ValueError('bad')
            return x

        def merge(item, result):
            merged[item] = result

        results = run_batched(['a', 'b', 'c'], fail_on_b, merge_fn=merge,
                              batch_size=3, label='item')
        # 'b' failed so merge should NOT have been called for it
        assert 'b' not in merged
        assert merged['a'] == 'a'
        assert merged['c'] == 'c'


# ============================================================================
# HealingZone
# ============================================================================

class TestHealingZone:
    def test_success_on_first_attempt(self, mock_api):
        """Function succeeds immediately, no healing needed."""
        with HealingZone('test zone', '/fake/project', max_attempts=3) as zone:
            result = zone.run(lambda: 'success')
        assert result == 'success'

    def test_retries_on_failure(self, mock_api, tmp_path):
        """Function fails once then succeeds."""
        mock_api.set_response('diagnosis text')
        attempts = [0]

        def flaky():
            attempts[0] += 1
            if attempts[0] < 2:
                raise RuntimeError('temporary error')
            return 'recovered'

        with HealingZone('flaky task', str(tmp_path), max_attempts=3) as zone:
            result = zone.run(flaky)
        assert result == 'recovered'
        assert attempts[0] == 2

    def test_exhausts_attempts_then_raises(self, mock_api, tmp_path):
        """After max_attempts, should raise the last error."""
        mock_api.set_response('diagnosis text')

        def always_fails():
            raise RuntimeError('permanent error')

        with pytest.raises(RuntimeError, match='permanent error'):
            with HealingZone('doomed task', str(tmp_path), max_attempts=2) as zone:
                zone.run(always_fails)

    def test_context_manager_protocol(self):
        """HealingZone works as a context manager."""
        zone = HealingZone('test', '/fake')
        assert hasattr(zone, '__enter__')
        assert hasattr(zone, '__exit__')
        with zone:
            pass  # Should not raise

    def test_exit_does_not_suppress_exceptions(self):
        """__exit__ returns False, so exceptions propagate."""
        zone = HealingZone('test', '/fake')
        assert zone.__exit__(None, None, None) is False

    def test_passes_args_and_kwargs(self, mock_api):
        """zone.run passes positional and keyword args to the function."""
        def add(a, b, extra=0):
            return a + b + extra

        with HealingZone('add test', '/fake') as zone:
            result = zone.run(add, 3, 4, extra=10)
        assert result == 17
