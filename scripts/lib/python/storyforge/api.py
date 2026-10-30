"""Direct Anthropic API invocation and Batch API helpers.

Replaces api.sh — provides reliable JSON handling, HTTP calls, and
cost calculation without jq/curl/awk compatibility issues.
"""

import json
import os
import sys
import time
import threading
from dataclasses import dataclass, field
from urllib.request import Request, urlopen
from urllib.error import HTTPError, URLError

from storyforge.costs import calculate_cost, log_operation


API_BASE = 'https://api.anthropic.com/v1'
API_VERSION = '2023-06-01'
HEARTBEAT_INTERVAL = 120  # seconds between status messages during API calls
API_TIMEOUT = 600  # seconds before giving up on an API call (10 min)
REVISION_TIMEOUT = 3600  # seconds for large revision calls (60 min)
API_RETRIES = 2  # retry transient failures (timeouts, 5xx)

# Server-side refusal fallback: on a policy decline the API re-runs the
# request on the model Anthropic recommends for that refusal category (Opus 5
# or 4.8 today). Prose calls opt in (``fallback=True``) so a false-positive
# refusal does not leave a scene undrafted; the Batches API rejects it.
FALLBACK_BETA = 'server-side-fallback-2026-07-01'

# Current models think before answering (Opus can't turn it off), and
# thinking counts against max_tokens, so a budget sized for the answer alone
# can end in thinking with no text. invoke adds this much on top of the
# caller's budget. Only generated tokens are billed, so the headroom is free.
THINKING_ALLOWANCE = 16000

# Output limit for a model the catalog does not list (a STORYFORGE_MODEL
# override the API will reject anyway); every listed model reports its own.
_DEFAULT_MAX_OUTPUT = 32768


def max_output_tokens(model: str) -> int:
    """The model's maximum output tokens, from the Models API catalog.

    The API returns HTTP 400 if max_tokens exceeds this. You only pay for
    tokens actually generated, so requesting the max is safe cost-wise.
    """
    from storyforge.common import model_catalog
    for m in model_catalog():
        if m.get('id') == model and m.get('max_tokens'):
            return int(m['max_tokens'])
    return _DEFAULT_MAX_OUTPUT


def max_input_tokens(model: str) -> int:
    """The model's context window in tokens, from the Models API catalog;
    200k for a model the catalog does not list."""
    from storyforge.common import model_catalog
    for m in model_catalog():
        if m.get('id') == model and m.get('max_input_tokens'):
            return int(m['max_input_tokens'])
    return 200_000


def request_max_tokens(model: str, answer_tokens: int) -> int:
    """The max_tokens to send: the answer budget plus THINKING_ALLOWANCE,
    capped at the model's limit."""
    return min(answer_tokens + THINKING_ALLOWANCE, max_output_tokens(model))


def list_models() -> list[dict]:
    """Every model the API offers, following pagination."""
    models: list[dict] = []
    after = ''
    while True:
        page = _api_request('models?limit=1000' + (f'&after_id={after}' if after else ''))
        models.extend(page.get('data', []))
        if not page.get('has_more') or not page.get('last_id'):
            return models
        after = page['last_id']


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
    """Make an authenticated API request, through the eval cassette if one is set.

    Under a cassette the refusal fallback is stripped, so a recording is
    always the requested model's reply (or its refusal): evals measure that
    model, and recordings made before prose calls opted in still replay."""
    from storyforge import cassette
    if cassette.active_dir():
        if body and 'fallbacks' in body:
            body = {k: v for k, v in body.items() if k != 'fallbacks'}
        return cassette.request(method, path, body,
                                lambda: _live_request(path, body, method, timeout))
    return _live_request(path, body, method, timeout)


def _live_request(path: str, body: dict | None, method: str, timeout: int) -> dict:
    url = f'{API_BASE}/{path}'
    headers = {
        'x-api-key': get_api_key(),
        'anthropic-version': API_VERSION,
        'content-type': 'application/json',
    }
    if body and 'fallbacks' in body:
        # the body is the one place that says the fallback is on
        headers['anthropic-beta'] = FALLBACK_BETA

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


class RefusalError(RuntimeError):
    """The model declined the request (``stop_reason == 'refusal'``).

    Its text is empty or cut off mid-sentence, never an answer, so it is
    raised rather than returned: Sonnet 5.5 refused every timeline batch on
    Pride and Prejudice, and the empty text was read as "no calendar"."""

    def __init__(self, response: dict):
        self.response = response
        details = response.get('stop_details') or {}
        self.category = details.get('category', '')
        message = f"model refused the request ({self.category or 'no category'})"
        # Set when the refusal fallback could not run (e.g. that model was
        # rate-limited): a retry may well succeed, unlike a second refusal.
        if details.get('recommended_model'):
            message += (f"; the fallback could not run, and the API suggests "
                        f"retrying on {details['recommended_model']}")
        super().__init__(message)


def is_refusal(response) -> bool:
    """Whether ``response`` (live or a saved log) is a refusal."""
    return isinstance(response, dict) and response.get('stop_reason') == 'refusal'


def stop_problem(response) -> str:
    """Why ``response``'s text is not a complete answer ('' when it is): the
    model refused, or the reply was cut off at ``max_tokens``. Works on a live
    response and on a saved log, from ``invoke_to_file`` or batch results.
    Only those two stop reasons are known to leave an incomplete answer;
    ``parsing.unsafe_scene_reason`` catches prose cut off any other way."""
    if is_refusal(response):
        return str(RefusalError(response))
    if is_truncated(response):
        return 'the reply was cut off at max_tokens'
    return ''


def fallback_model(response) -> str:
    """The model that wrote ``response`` when the refusal fallback served it
    in place of the requested model, else ''. A fallback that also refused
    returns '' (the response is a refusal), as does a response that names no
    model."""
    if not isinstance(response, dict) or is_refusal(response):
        return ''
    iterations = (response.get('usage') or {}).get('iterations') or []
    if any(it.get('type') == 'fallback_message' for it in iterations):
        return response.get('model') or ''
    return ''


# (label, requested model, model that wrote the reply) for every reply the
# refusal fallback served in this process; commands report them at the end.
_fallback_replies: list[tuple[str, str, str]] = []


def fallback_replies() -> list[tuple[str, str, str]]:
    """Every (label, requested model, serving model) the refusal fallback
    served so far in this process, oldest first."""
    return list(_fallback_replies)


def fallback_note(since: int = 0) -> str:
    """A commit-message suffix naming the fallback replies served after
    the first ``since`` ('' when none), so the history records which prose
    another model wrote."""
    served = sorted({m for _, _, m in _fallback_replies[since:]})
    return f' (refusal fallback: written by {", ".join(served)})' if served else ''


def report_fallback_replies() -> None:
    """Log a WARNING block listing every reply the refusal fallback wrote,
    for an end-of-run summary. Silent when there were none."""
    if not _fallback_replies:
        return
    from storyforge.common import log
    count = len(_fallback_replies)
    log(f'WARNING: {count} repl{"y was" if count == 1 else "ies were"} written by another '
        f'model after a refusal (refusal fallback); read them for voice and continuity:')
    for label, requested, served in _fallback_replies:
        log(f'  {label}: {served} in place of {requested}')


def _check_refusal(response) -> None:
    if is_refusal(response):
        raise RefusalError(response)


def _output_config(schema: dict) -> dict:
    """The request's ``output_config`` for a structured (JSON schema) reply,
    shared by direct and batch requests so they can't drift apart."""
    return {'format': {'type': 'json_schema', 'schema': schema}}


def _send(prompt: str, model: str, max_tokens: int, label: str, timeout: int,
          system: list[dict] | None, output_schema: dict | None = None,
          fallback: bool = False) -> dict:
    """Call the Anthropic Messages API.

    Args:
        prompt: The user message text.
        model: Model ID (from ``common.select_model`` or ``model_for_tier``).
        max_tokens: Output tokens for the answer; THINKING_ALLOWANCE is added,
            capped at the model's limit.
        label: Optional label for heartbeat messages (e.g., 'revision pass 3').
        timeout: Socket timeout in seconds (default API_TIMEOUT).
        system: Optional list of system content blocks (supports cache_control).
        output_schema: Optional JSON schema; the reply's text is then one JSON
            object matching it (structured outputs).
        fallback: Opt into the server-side refusal fallback (FALLBACK_BETA).
            A reply written by a fallback model is logged as a WARNING
            naming ``label`` and that model.

    Returns:
        Full API response dict.
    """
    body = {
        'model': model,
        'max_tokens': request_max_tokens(model, max_tokens),
        'messages': [{'role': 'user', 'content': prompt}],
    }
    if system:
        body['system'] = system
    if output_schema:
        body['output_config'] = _output_config(output_schema)
    if fallback:
        body['fallbacks'] = 'default'
    heartbeat = _Heartbeat(label or model)
    heartbeat.start()
    try:
        response = _api_request('messages', body, method='POST', timeout=timeout)
    finally:
        heartbeat.stop()
    served = fallback_model(response)
    if served:
        # Not always a fresh refusal: after one, the API routes the same
        # request straight to the fallback model for about an hour.
        _fallback_replies.append((label or 'a request', model, served))
        from storyforge.common import log
        log(f'WARNING: {served} wrote the reply to {label or "the request"} in place of '
            f'{model} (refusal fallback)')
    return response


def invoke(prompt: str, model: str, max_tokens: int = 4096, label: str = '',
           timeout: int = API_TIMEOUT, system: list[dict] | None = None,
           output_schema: dict | None = None, fallback: bool = False) -> dict:
    """Call the Anthropic Messages API.

    Args:
        prompt: The user message text.
        model: Model ID (from ``common.select_model`` or ``model_for_tier``).
        max_tokens: Output tokens for the answer; THINKING_ALLOWANCE is added,
            capped at the model's limit.
        label: Optional label for heartbeat messages (e.g., 'revision pass 3').
        timeout: Socket timeout in seconds (default API_TIMEOUT).
        system: Optional list of system content blocks (supports cache_control).
        output_schema: Optional JSON schema for a structured reply (see _send).
        fallback: Opt into the server-side refusal fallback (see _send).

    Returns:
        Full API response dict.

    Raises:
        RefusalError: the model refused the request (with ``fallback``, no
            fallback model served it: it refused too, could not run, or the
            requested model has none).
    """
    response = _send(prompt, model, max_tokens, label, timeout, system, output_schema,
                     fallback)
    _check_refusal(response)
    return response


def invoke_to_file(prompt: str, model: str, log_file: str, max_tokens: int = 4096, label: str = '',
                   timeout: int = API_TIMEOUT, system: list[dict] | None = None,
                   output_schema: dict | None = None, fallback: bool = False) -> dict:
    """Call the API and write the response to a JSON file.

    Args:
        prompt: The user message text.
        model: Model ID.
        log_file: Path to write the JSON response.
        max_tokens: Maximum output tokens.
        label: Optional label for heartbeat messages.
        timeout: Socket timeout in seconds (default API_TIMEOUT).
        system: Optional list of system content blocks (supports cache_control).
        output_schema: Optional JSON schema for a structured reply (see _send).
        fallback: Opt into the server-side refusal fallback (see _send).

    Returns:
        Full API response dict.

    Raises:
        RefusalError: the model refused the request (the log is written first).
    """
    try:
        response = invoke(prompt, model, max_tokens, label=label, timeout=timeout, system=system,
                          output_schema=output_schema, fallback=fallback)
    except RefusalError as e:
        _write_log(log_file, e.response)
        raise
    _write_log(log_file, response)
    return response


def _write_log(log_file: str, response: dict) -> None:
    os.makedirs(os.path.dirname(log_file) or '.', exist_ok=True)
    with open(log_file, 'w') as f:
        json.dump(response, f)


class ToolInputError(ValueError):
    """A tool handler's answer to input it can't serve (an unknown scene id,
    a malformed query). ``converse`` sends the message back to the model as
    an error result, so it can correct the call; any other exception from a
    handler is a bug and propagates."""


class ToolLoopError(RuntimeError):
    """The model was still calling tools after ``max_turns`` requests."""


@dataclass
class ToolRun:
    """What ``converse`` returns.

    ``response``: the last reply (its text is the answer). ``responses``:
    every reply in order. ``calls``: ``(tool name, input, is_error)`` for
    each tool call made. ``usage``: the replies' token counts summed, in the
    API's usage shape, so ``extract_usage`` and the cost helpers take it.
    """
    response: dict
    responses: list[dict] = field(default_factory=list)
    calls: list[tuple[str, dict, bool]] = field(default_factory=list)

    @property
    def usage(self) -> dict:
        keys = ('input_tokens', 'output_tokens', 'cache_read_input_tokens',
                'cache_creation_input_tokens')
        return {k: sum((r.get('usage') or {}).get(k, 0) or 0 for r in self.responses)
                for k in keys}


def converse(prompt: str, model: str, tools: list[dict], handlers: dict,
             max_tokens: int = 4096, max_turns: int = 20, label: str = '',
             timeout: int = API_TIMEOUT, system: list[dict] | None = None,
             output_schema: dict | None = None, log_file: str = '') -> ToolRun:
    """A tool-using exchange: send ``prompt`` with ``tools``, run each tool
    call through ``handlers`` (name → function of the call's input returning
    a string), send the results back, and repeat until the model answers.

    History is append-only: every reply's content goes back unchanged
    (thinking blocks included), and all of one turn's results go in one user
    message. Tools are sent ``strict``, so each input matches its schema.
    The request is auto-cached, so each turn reads the conversation so far
    from cache. With ``output_schema`` the final answer's text is one JSON
    object matching it.

    ``max_tokens`` is per reply (``THINKING_ALLOWANCE`` is added). A reply cut
    off at ``max_tokens`` ends the exchange and is returned: check
    ``is_truncated(run.response)``. ``log_file``, if given, gets every reply
    as a JSON list, written after each turn so a failure leaves the trail.

    Raises:
        RefusalError: the model refused (the log is written first).
        ToolLoopError: no answer after ``max_turns`` requests.
        Whatever a handler raises other than ``ToolInputError``.
    """
    tools = [{**t, 'strict': True} for t in tools]
    missing = [t['name'] for t in tools if t['name'] not in handlers]
    if missing:
        raise ValueError(f'no handler for tool(s): {", ".join(missing)}')
    messages: list[dict] = [{'role': 'user', 'content': prompt}]
    run = ToolRun(response={})
    for _ in range(max_turns):
        body = {
            'model': model,
            'max_tokens': request_max_tokens(model, max_tokens),
            'messages': messages,
            'tools': tools,
            'cache_control': {'type': 'ephemeral'},
        }
        if system:
            body['system'] = system
        if output_schema:
            body['output_config'] = _output_config(output_schema)
        heartbeat = _Heartbeat(label or model)
        heartbeat.start()
        try:
            response = _api_request('messages', body, method='POST', timeout=timeout)
        finally:
            heartbeat.stop()
        run.responses.append(response)
        run.response = response
        if log_file:
            _write_log(log_file, run.responses)
        _check_refusal(response)
        uses = [b for b in response.get('content', []) if b.get('type') == 'tool_use']
        if response.get('stop_reason') != 'tool_use' or not uses:
            return run
        messages = messages + [{'role': 'assistant', 'content': response['content']}]
        results = []
        for use in uses:
            name, args = use.get('name', ''), use.get('input') or {}
            handler = handlers.get(name)
            try:
                if handler is None:
                    raise ToolInputError(f'there is no tool named {name!r}')
                content, is_error = str(handler(args)), False
            except ToolInputError as e:
                content, is_error = str(e), True
            run.calls.append((name, args, is_error))
            result = {'type': 'tool_result', 'tool_use_id': use['id'], 'content': content}
            if is_error:
                result['is_error'] = True
            results.append(result)
        messages = messages + [{'role': 'user', 'content': results}]
    raise ToolLoopError(f'{label or "tool exchange"}: still calling tools after '
                        f'{max_turns} requests')


def is_truncated(response) -> bool:
    """Whether an API response stopped at its ``max_tokens`` limit, so its
    text is cut off. Callers that parse a structured answer must check this
    rather than apply a partial one."""
    return isinstance(response, dict) and response.get('stop_reason') == 'max_tokens'


_invoke_api_consecutive_failures = 0
_INVOKE_API_FAILURE_THRESHOLD = 5


def invoke_api(prompt: str, model: str, max_tokens: int = 4096, label: str = '',
               timeout: int = API_TIMEOUT, system: list[dict] | None = None,
               fallback: bool = False) -> str:
    """High-level convenience: invoke API and return text response.

    Returns empty string on failure (logs warning but doesn't raise).
    Raises RuntimeError if failures exceed threshold (likely systemic issue).
    Used by git.py review phase, runner.py healing zones, and command modules.
    """
    global _invoke_api_consecutive_failures
    try:
        response = invoke(prompt, model, max_tokens, label=label, timeout=timeout, system=system,
                          fallback=fallback)
        _invoke_api_consecutive_failures = 0
        return extract_text(response)
    except Exception as e:
        from storyforge.cassette import CassetteError
        if isinstance(e, CassetteError):
            raise  # an eval replay that cannot be served must fail, not read as an empty answer
        from storyforge.common import log
        _invoke_api_consecutive_failures += 1
        log(f'WARNING: API call failed: {e}')
        if _invoke_api_consecutive_failures >= _INVOKE_API_FAILURE_THRESHOLD:
            _invoke_api_consecutive_failures = 0
            raise RuntimeError(
                f'API calls failed {_INVOKE_API_FAILURE_THRESHOLD} times consecutively — '
                f'likely a systemic issue (bad API key, malformed request, etc.). '
                f'Last error: {e}'
            ) from e
        return ''


def extract_response(log_file: str) -> str:
    """Extract text from a JSON response file. Alias for extract_text_from_file."""
    return extract_text_from_file(log_file)


def extract_text(response: dict) -> str:
    """Extract text content from an API response dict. Only text after the
    last ``fallback`` block is kept: our non-streamed replies put that block
    first, but a streamed mid-output decline would leave the refused model's
    partial before it."""
    texts = []
    for block in response.get('content', []):
        if block.get('type') == 'fallback':
            texts = []
        elif block.get('type') == 'text':
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


def calculate_cost_from_usage(usage: dict, model: str, batch: bool = False) -> float:
    """Calculate cost in USD from a usage dict (as returned by extract_usage).

    Thin wrapper around costs.calculate_cost for backward compatibility.
    If batch=True, applies the Anthropic Batch API 50% discount.
    """
    return calculate_cost(
        model,
        usage['input_tokens'],
        usage['output_tokens'],
        cache_read=usage.get('cache_read', 0),
        cache_create=usage.get('cache_create', 0),
        batch=batch,
    )


def build_batch_request(custom_id: str, prompt: str, model: str,
                        max_tokens: int = 4096,
                        system: list[dict] | None = None,
                        output_schema: dict | None = None) -> dict:
    """Build a single batch request item (one JSONL line).

    Args:
        custom_id: Unique identifier for this request in the batch.
        prompt: The user message text.
        model: Model ID.
        max_tokens: Maximum output tokens.
        system: Optional list of system content blocks with cache_control.
        output_schema: Optional JSON schema for a structured reply (see _send).

    Returns:
        Dict suitable for JSON serialization as one JSONL line.
    """
    params = {
        'model': model,
        'max_tokens': request_max_tokens(model, max_tokens),
        'messages': [{'role': 'user', 'content': prompt}],
    }
    if system:
        params['system'] = system
    if output_schema:
        params['output_config'] = _output_config(output_schema)
    return {'custom_id': custom_id, 'params': params}


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


def download_batch_results(results_url: str, output_dir: str, log_dir: str,
                           keep_incomplete: bool = False) -> list[str]:
    """Download and parse batch results into per-item files.

    Creates for each item:
        output_dir/.status-{custom_id}  — "ok" or "fail"
        log_dir/{custom_id}.json        — API response (for log_usage)
        log_dir/{custom_id}.txt         — text content, only when "ok"

    An item that errored, expired or was canceled is marked "fail", named in
    a WARNING, and left with neither file (stale ones from an earlier run are
    removed, so no caller reads an old answer or bills an old reply). A reply
    the model refused or that was cut off at ``max_tokens``
    (``stop_problem``) is not an answer either: it is marked "fail", gets no
    .txt and is named in a WARNING, but its .json is written, since it was
    paid for. Unlike ``invoke``, which returns a cut-off reply, this rejects
    it; ``keep_incomplete=True`` treats such replies as "ok", for a caller
    that checks ``stop_problem`` itself (``write`` retries refusals,
    ``evaluate`` keeps a cut-off report).

    Returns:
        The custom_ids marked "ok": refused and cut-off replies are left out
        unless ``keep_incomplete``.
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
            txt_path = os.path.join(log_dir, f'{cid}.txt')

            if rtype != 'succeeded':
                from storyforge.common import log
                error = (result.get('error') or {})
                error = error.get('error', error) if isinstance(error, dict) else {}
                why = error.get('message') or error.get('type') or ''
                log(f'WARNING: batch item {cid}: the request {rtype or "failed"}'
                    f'{f" ({why})" if why else ""}; there is no reply.')
                for stale in (txt_path, os.path.join(log_dir, f'{cid}.json')):
                    if os.path.isfile(stale):
                        os.remove(stale)
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

            # Write JSON response (for log_usage). stop_reason/stop_details
            # let a caller tell a refused or cut-off reply from a finished one.
            record = {'usage': usage, 'content': msg.get('content', []),
                      'stop_reason': msg.get('stop_reason'),
                      'stop_details': msg.get('stop_details')}
            with open(os.path.join(log_dir, f'{cid}.json'), 'w') as f:
                json.dump(record, f)

            problem = '' if keep_incomplete else stop_problem(record)
            if problem:
                from storyforge.common import log
                log(f'WARNING: batch item {cid}: {problem}; its reply is not used.')
                if os.path.isfile(txt_path):
                    os.remove(txt_path)
                with open(os.path.join(output_dir, f'.status-{cid}'), 'w') as f:
                    f.write('fail')
                continue

            # Write text content
            with open(txt_path, 'w') as f:
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
