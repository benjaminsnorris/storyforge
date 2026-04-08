"""Direct Anthropic API invocation and Batch API helpers.

Replaces api.sh — provides reliable JSON handling, HTTP calls, and
cost calculation without jq/curl/awk compatibility issues.
"""

import json
import os
import sys
import time
import threading
from urllib.request import Request, urlopen
from urllib.error import HTTPError, URLError

from storyforge.costs import PRICING, calculate_cost, log_operation


API_BASE = 'https://api.anthropic.com/v1'
API_VERSION = '2023-06-01'
HEARTBEAT_INTERVAL = 120  # seconds between status messages during API calls
API_TIMEOUT = 600  # seconds before giving up on an API call (10 min)
REVISION_TIMEOUT = 3600  # seconds for large revision calls (60 min)
API_RETRIES = 2  # retry transient failures (timeouts, 5xx)

# Model output token limits — the API returns HTTP 400 if max_tokens exceeds these.
# You only pay for tokens actually generated, so requesting the max is safe cost-wise.
MODEL_MAX_OUTPUT = {
    'claude-opus-4-6': 128000,
    'claude-sonnet-4-6': 64000,
    'claude-haiku-4-5-20251001': 16384,
}
_DEFAULT_MAX_OUTPUT = 32768


def max_output_tokens(model: str) -> int:
    """Return the maximum output tokens supported by a model."""
    return MODEL_MAX_OUTPUT.get(model, _DEFAULT_MAX_OUTPUT)


class _Heartbeat:
    """Background thread that prints elapsed time during long API calls."""

    def __init__(self, label: str = 'API call'):
        self._label = label
        self._stop = threading.Event()
        self._thread = None
        self._start = 0.0

    def start(self):
        self._start = time.time()
        self._thread = threading.Thread(target=self._run, daemon=True)
        self._thread.start()

    def stop(self):
        self._stop.set()
        if self._thread:
            self._thread.join(timeout=1)

    def _run(self):
        from storyforge.common import log
        while not self._stop.wait(HEARTBEAT_INTERVAL):
            elapsed = int(time.time() - self._start)
            mins, secs = divmod(elapsed, 60)
            log(f'  Still waiting on {self._label}... ({mins}m{secs}s elapsed)')


def get_api_key() -> str:
    key = os.environ.get('ANTHROPIC_API_KEY', '')
    if not key:
        raise RuntimeError('ANTHROPIC_API_KEY not set')
    return key


def _api_request(path: str, body: dict | None = None, method: str = 'GET',
                 timeout: int = API_TIMEOUT) -> dict:
    """Make an authenticated API request."""
    url = f'{API_BASE}/{path}'
    headers = {
        'x-api-key': get_api_key(),
        'anthropic-version': API_VERSION,
        'content-type': 'application/json',
    }

    data = json.dumps(body).encode() if body else None
    req = Request(url, data=data, headers=headers, method=method)

    last_err = None
    for attempt in range(1, API_RETRIES + 1):
        try:
            with urlopen(req, timeout=timeout) as resp:
                return json.loads(resp.read().decode())
        except HTTPError as e:
            error_body = e.read().decode() if e.fp else ''
            if e.code >= 500 and attempt < API_RETRIES:
                from storyforge.common import log
                log(f'  API returned {e.code}, retrying ({attempt}/{API_RETRIES})...')
                time.sleep(2 ** attempt)
                last_err = e
                continue
            raise RuntimeError(f'API returned HTTP {e.code}: {error_body[:500]}') from e
        except (URLError, TimeoutError, OSError) as e:
            if attempt < API_RETRIES:
                from storyforge.common import log
                log(f'  API connection error: {e}, retrying ({attempt}/{API_RETRIES})...')
                time.sleep(2 ** attempt)
                last_err = e
                continue
            raise RuntimeError(f'API request failed after {API_RETRIES} attempts: {e}') from last_err


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
    heartbeat = _Heartbeat(label or model)
    heartbeat.start()
    try:
        return _api_request('messages', body, method='POST', timeout=timeout)
    finally:
        heartbeat.stop()


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
    os.makedirs(os.path.dirname(log_file) or '.', exist_ok=True)
    with open(log_file, 'w') as f:
        json.dump(response, f)
    return response


def invoke_api(prompt: str, model: str, max_tokens: int = 4096, label: str = '',
               timeout: int = API_TIMEOUT) -> str:
    """High-level convenience: invoke API and return text response.

    Returns empty string on failure (logs warning but doesn't raise).
    Used by git.py review phase, runner.py healing zones, and command modules.
    """
    try:
        response = invoke(prompt, model, max_tokens, label=label, timeout=timeout)
        return extract_text(response)
    except Exception as e:
        from storyforge.common import log
        log(f'WARNING: API call failed: {e}')
        return ''


def extract_response(log_file: str) -> str:
    """Extract text from a JSON response file. Alias for extract_text_from_file."""
    return extract_text_from_file(log_file)


def extract_text(response: dict) -> str:
    """Extract text content from an API response dict."""
    texts = []
    for block in response.get('content', []):
        if block.get('type') == 'text':
            texts.append(block.get('text', ''))
    return '\n'.join(texts)


def extract_text_from_file(log_file: str) -> str:
    """Extract text content from a JSON response file."""
    try:
        with open(log_file) as f:
            return extract_text(json.load(f))
    except (json.JSONDecodeError, FileNotFoundError):
        return ''


def extract_usage(response: dict) -> dict:
    """Extract usage data from an API response."""
    usage = response.get('usage', {})
    return {
        'input_tokens': usage.get('input_tokens', 0),
        'output_tokens': usage.get('output_tokens', 0),
        'cache_read': usage.get('cache_read_input_tokens', 0),
        'cache_create': usage.get('cache_creation_input_tokens', 0),
    }


def calculate_cost_from_usage(usage: dict, model: str) -> float:
    """Calculate cost in USD from a usage dict (as returned by extract_usage).

    Thin wrapper around costs.calculate_cost for backward compatibility.
    """
    return calculate_cost(
        model,
        usage['input_tokens'],
        usage['output_tokens'],
        cache_read=usage.get('cache_read', 0),
        cache_create=usage.get('cache_create', 0),
    )


# ============================================================================
# Batch API
# ============================================================================

def submit_batch(batch_file: str) -> str:
    """Submit a JSONL batch file. Returns the batch ID."""
    with open(batch_file) as f:
        requests = [json.loads(line) for line in f if line.strip()]

    body = {'requests': requests}
    response = _api_request('messages/batches', body, method='POST')

    batch_id = response.get('id', '')
    if not batch_id:
        raise RuntimeError(f'No batch ID returned: {json.dumps(response)[:500]}')

    return batch_id


def poll_batch(batch_id: str, log_fn=None) -> str:
    """Poll a batch until it ends. Returns the results_url."""
    interval = 15
    start = time.time()

    while True:
        time.sleep(interval)
        status = _api_request(f'messages/batches/{batch_id}')

        pstatus = status.get('processing_status', 'unknown')
        counts = status.get('request_counts', {})
        elapsed = int(time.time() - start)

        msg = f"  {elapsed}s: {pstatus} ({counts.get('succeeded', 0)} succeeded, {counts.get('errored', 0)} errored)"
        if log_fn:
            log_fn(msg)
        else:
            print(msg, file=sys.stderr)

        if pstatus == 'ended':
            return status.get('results_url', '')

        if interval < 30:
            interval += 5


def download_batch_results(results_url: str, output_dir: str, log_dir: str) -> list[str]:
    """Download and parse batch results into per-item files.

    Creates for each item:
        output_dir/.status-{custom_id}  — "ok" or "fail"
        log_dir/{custom_id}.json        — API response (for log_usage)
        log_dir/{custom_id}.txt         — text content

    Returns:
        List of custom_ids that succeeded.
    """
    headers = {
        'x-api-key': get_api_key(),
        'anthropic-version': API_VERSION,
    }
    req = Request(results_url, headers=headers)

    os.makedirs(output_dir, exist_ok=True)
    os.makedirs(log_dir, exist_ok=True)

    succeeded = []

    with urlopen(req, timeout=API_TIMEOUT) as resp:
        for line in resp.read().decode().splitlines():
            if not line.strip():
                continue
            try:
                obj = json.loads(line)
            except json.JSONDecodeError:
                continue

            cid = obj.get('custom_id', '')
            result = obj.get('result', {})
            rtype = result.get('type', '')

            if rtype != 'succeeded':
                with open(os.path.join(output_dir, f'.status-{cid}'), 'w') as f:
                    f.write('fail')
                continue

            msg = result.get('message', {})
            usage = msg.get('usage', {})

            # Extract text
            text = ''
            for block in msg.get('content', []):
                if block.get('type') == 'text':
                    text = block.get('text', '')

            # Write JSON response (for log_usage)
            with open(os.path.join(log_dir, f'{cid}.json'), 'w') as f:
                json.dump({'usage': usage, 'content': msg.get('content', [])}, f)

            # Write text content
            with open(os.path.join(log_dir, f'{cid}.txt'), 'w') as f:
                f.write(text)

            # Write status
            with open(os.path.join(output_dir, f'.status-{cid}'), 'w') as f:
                f.write('ok')

            succeeded.append(cid)

    return succeeded


# --- CLI interface for calling from bash ---

def main():
    """CLI entry point. Usage:

    python3 -m storyforge.api invoke <prompt_file> <model> <log_file> [max_tokens]
    python3 -m storyforge.api extract-text <log_file>
    python3 -m storyforge.api log-usage <log_file> <operation> <target> <model> [unused] [duration]
    python3 -m storyforge.api submit-batch <batch_file>
    python3 -m storyforge.api poll-batch <batch_id>
    python3 -m storyforge.api download-results <results_url> <output_dir> <log_dir>
    """
    if len(sys.argv) < 2:
        print('Usage: python3 -m storyforge.api <command> [args]', file=sys.stderr)
        sys.exit(1)

    command = sys.argv[1]

    if command == 'invoke':
        prompt_file, model, log_file = sys.argv[2], sys.argv[3], sys.argv[4]
        max_tokens = int(sys.argv[5]) if len(sys.argv) > 5 else 4096
        with open(prompt_file) as f:
            prompt = f.read()
        invoke_to_file(prompt, model, log_file, max_tokens)
        print('ok')

    elif command == 'extract-text':
        log_file = sys.argv[2]
        print(extract_text_from_file(log_file))

    elif command == 'log-usage':
        # Legacy CLI: parse an API response file and log to ledger
        log_file, operation, target, model = sys.argv[2:6]
        duration = int(sys.argv[7]) if len(sys.argv) > 7 else 0
        try:
            with open(log_file) as f:
                response = json.load(f)
        except (json.JSONDecodeError, FileNotFoundError):
            response = {}
        usage = extract_usage(response)
        cost = calculate_cost_from_usage(usage, model)
        project_dir = os.environ.get('PROJECT_DIR', '.')
        log_operation(project_dir, operation, model,
                      usage['input_tokens'], usage['output_tokens'],
                      cost, duration)
        print('ok')

    elif command == 'submit-batch':
        batch_file = sys.argv[2]
        batch_id = submit_batch(batch_file)
        print(batch_id)

    elif command == 'poll-batch':
        batch_id = sys.argv[2]
        results_url = poll_batch(batch_id)
        print(results_url)

    elif command == 'download-results':
        results_url, output_dir, log_dir = sys.argv[2:5]
        succeeded = download_batch_results(results_url, output_dir, log_dir)
        for cid in succeeded:
            print(cid)

    else:
        print(f'Unknown command: {command}', file=sys.stderr)
        sys.exit(1)


if __name__ == '__main__':
    main()
