"""Record and replay Anthropic API calls, for the eval harness.

Inert unless ``STORYFORGE_CASSETTE`` names a directory. When it does, every
request through ``api._api_request`` is keyed by a hash of its method, path,
and body, and ``STORYFORGE_CASSETTE_MODE`` decides what happens:

- ``replay`` (default): return the recorded response. A request with no
  recording raises ``CassetteMiss`` — a replay that quietly went live would
  spend money and stop being deterministic, which is the whole point lost.
- ``record``: call the API and overwrite the recording.
- ``auto``: replay what exists, record what does not.

Environment variables rather than a function argument because evals drive
commands as subprocesses too, and the environment is what they inherit.

``STORYFORGE_CASSETTE_LOG``, if set, names a JSONL file that gets one line per
call (key, model, usage, whether it was replayed). The harness sums it into a
cost report; a replayed call reports what it *would* have cost live.

The Batch API is refused under a cassette: its ids and polling sequence are
not reproducible, so a recording of one could never replay.
"""

import hashlib
import json
import os

MODES = ('replay', 'record', 'auto')


class CassetteMiss(RuntimeError):
    """A replay-mode request has no recording."""


def active_dir() -> str:
    return os.environ.get('STORYFORGE_CASSETTE', '')


def mode() -> str:
    value = os.environ.get('STORYFORGE_CASSETTE_MODE', 'replay')
    if value not in MODES:
        raise RuntimeError(
            f'STORYFORGE_CASSETTE_MODE={value!r} is not one of {", ".join(MODES)}')
    return value


def request_key(method: str, path: str, body: dict | None) -> str:
    canonical = json.dumps({'method': method, 'path': path, 'body': body},
                           sort_keys=True, separators=(',', ':'))
    return hashlib.sha256(canonical.encode()).hexdigest()


def recording_path(cassette_dir: str, key: str) -> str:
    return os.path.join(cassette_dir, key[:2], f'{key}.json')


def _log_call(key: str, body: dict | None, response: dict, replayed: bool) -> None:
    log_file = os.environ.get('STORYFORGE_CASSETTE_LOG', '')
    if not log_file:
        return
    entry = {
        'key': key,
        'model': (body or {}).get('model', ''),
        'usage': response.get('usage', {}) if isinstance(response, dict) else {},
        'replayed': replayed,
    }
    with open(log_file, 'a') as f:
        f.write(json.dumps(entry) + '\n')


def request(method: str, path: str, body: dict | None, live) -> dict:
    """Serve one API request through the active cassette.

    ``live`` is a zero-argument callable that performs the real request.
    """
    cassette_dir = active_dir()
    if path.startswith('messages/batches'):
        raise RuntimeError(
            'The Batch API cannot run under STORYFORGE_CASSETTE: batch ids and '
            'polling are not reproducible. Run the command in direct mode.')

    current = mode()
    key = request_key(method, path, body)
    target = recording_path(cassette_dir, key)

    if current != 'record' and os.path.isfile(target):
        with open(target) as f:
            response = json.load(f)['response']
        _log_call(key, body, response, replayed=True)
        return response

    if current == 'replay':
        raise CassetteMiss(
            f'No recording for {method} {path} (key {key[:12]}) in {cassette_dir}. '
            f'Re-run with STORYFORGE_CASSETTE_MODE=record or auto to make one.')

    response = live()
    os.makedirs(os.path.dirname(target), exist_ok=True)
    tmp = target + '.tmp'
    with open(tmp, 'w') as f:
        json.dump({'request': {'method': method, 'path': path, 'body': body},
                   'response': response}, f, indent=1)
    os.replace(tmp, target)
    _log_call(key, body, response, replayed=False)
    return response
