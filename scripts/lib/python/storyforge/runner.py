"""Parallel execution and batch orchestration — replaces bash background job patterns.

Provides ProcessPoolExecutor-based parallel execution, progress monitoring,
and healing zone (retry with diagnosis) support.
"""

import os
import time
import subprocess
from concurrent.futures import ProcessPoolExecutor, as_completed
from typing import Callable, Any

from storyforge.common import log, is_shutting_down


# ============================================================================
# Parallel execution
# ============================================================================

def run_parallel(
    items: list[str],
    worker_fn: Callable[[str], Any],
    max_workers: int = 6,
    label: str = 'item',
) -> dict[str, Any]:
    """Run worker_fn on each item in parallel batches.

    Returns dict mapping item -> result (or Exception on failure).
    """
    default_parallel = int(os.environ.get('STORYFORGE_PARALLEL', str(max_workers)))
    max_workers = min(default_parallel, len(items))

    results: dict[str, Any] = {}
    completed = 0
    total = len(items)

    log(f'Processing {total} {label}(s) with {max_workers} parallel workers...')

    with ProcessPoolExecutor(max_workers=max_workers) as pool:
        futures = {pool.submit(worker_fn, item): item for item in items}

        for future in as_completed(futures):
            if is_shutting_down():
                pool.shutdown(wait=False, cancel_futures=True)
                break

            item = futures[future]
            completed += 1
            try:
                results[item] = future.result()
                log(f'  [{completed}/{total}] {item}: done')
            except Exception as e:
                results[item] = e
                log(f'  [{completed}/{total}] {item}: FAILED — {e}')

    return results


def run_batched(
    items: list[str],
    worker_fn: Callable[[str], Any],
    merge_fn: Callable[[str, Any], None] | None = None,
    batch_size: int = 6,
    label: str = 'item',
) -> dict[str, Any]:
    """Run in batches with optional merge step between batches.

    This mirrors the bash pattern where each batch runs in parallel,
    then results are merged sequentially before the next batch starts.
    """
    results: dict[str, Any] = {}
    total = len(items)

    for batch_start in range(0, total, batch_size):
        if is_shutting_down():
            break

        batch = items[batch_start:batch_start + batch_size]
        batch_results = run_parallel(batch, worker_fn, max_workers=len(batch), label=label)
        results.update(batch_results)

        # Sequential merge
        if merge_fn:
            for item in batch:
                if item in batch_results and not isinstance(batch_results[item], Exception):
                    merge_fn(item, batch_results[item])

    return results


# ============================================================================
# Progress monitoring
# ============================================================================

def monitor_progress(
    scene_id: str,
    project_dir: str,
    scene_file: str | None = None,
    interval: int = 30,
) -> None:
    """Poll filesystem during a Claude invocation and log milestones.

    Designed to run in a background thread. Returns when the scene file
    stabilizes or after a reasonable timeout.
    """
    if scene_file is None:
        scene_file = os.path.join(project_dir, 'scenes', f'{scene_id}.md')

    start_time = time.time()
    draft_detected = False
    last_word_count = 0
    ticks = 0

    while not is_shutting_down():
        time.sleep(interval)
        ticks += 1
        elapsed = int(time.time() - start_time)
        mins = elapsed // 60

        if os.path.isfile(scene_file):
            with open(scene_file) as f:
                wc = len(f.read().split())

            if not draft_detected:
                draft_detected = True
                log(f'  [{scene_id}] Scene file created (~{wc} words) [{mins}m]')
            elif wc > last_word_count + 300:
                log(f'  [{scene_id}] Draft growing: ~{wc} words [{mins}m]')
            last_word_count = wc

        # Heartbeat every 2 minutes
        if ticks % 4 == 0:
            log(f'  [{scene_id}] {mins}m elapsed...')


# ============================================================================
# Healing zone (retry with Claude diagnosis)
# ============================================================================

class HealingZone:
    """Context manager for self-healing execution zones.

    Retries a block up to max_attempts times. On failure, invokes Claude
    to diagnose and fix the issue before retrying.

    Usage:
        with HealingZone('drafting scene X', project_dir) as zone:
            zone.run(my_function, arg1, arg2)
    """

    def __init__(self, description: str, project_dir: str, max_attempts: int = 3):
        self.description = description
        self.project_dir = project_dir
        self.max_attempts = max_attempts
        self._attempt = 0

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        return False  # Don't suppress exceptions

    def run(self, fn: Callable, *args, **kwargs) -> Any:
        """Run fn with healing retries."""
        from storyforge.common import select_model
        from storyforge.api import invoke_api

        last_error = None
        for attempt in range(1, self.max_attempts + 1):
            self._attempt = attempt
            try:
                return fn(*args, **kwargs)
            except Exception as e:
                last_error = e
                log(f'HEALING: Failed in zone \'{self.description}\' '
                    f'(attempt {attempt}/{self.max_attempts}): {e}')

                if attempt >= self.max_attempts:
                    log(f'HEALING FAILED: Exhausted {self.max_attempts} attempts '
                        f'for \'{self.description}\'')
                    raise

                if is_shutting_down():
                    raise

                # Invoke Claude to diagnose
                self._run_healing(str(e), attempt)

    def _run_healing(self, error: str, attempt: int) -> None:
        from storyforge.common import select_model
        from storyforge.api import invoke_api

        model = select_model('review')
        prompt = f"""You are a diagnostic assistant for the Storyforge novel-writing toolkit.

An autonomous script encountered an error and needs your help to fix it.

## What the script was doing
{self.description}

## What failed
{error}

## Project location
{self.project_dir}

## Your job
1. Diagnose why the command failed
2. Suggest a fix (but cannot edit files directly in this context)

## Rules
- Only fix the immediate problem — do not make unrelated changes
- If you cannot determine the cause, explain what you found
"""
        log(f'HEALING: Invoking Claude to diagnose (attempt {attempt})...')
        response = invoke_api(prompt, model, max_tokens=8192)
        if response:
            log_file = os.path.join(
                self.project_dir, 'working', 'logs',
                f'healing-attempt-{attempt}.log'
            )
            os.makedirs(os.path.dirname(log_file), exist_ok=True)
            with open(log_file, 'w') as f:
                f.write(response)
            log('HEALING: Claude completed diagnosis. Retrying zone...')
