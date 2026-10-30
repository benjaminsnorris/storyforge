"""Record and replay Anthropic API calls, for the eval harness.

Inert unless ``STORYFORGE_CASSETTE`` names a directory. When it does, every
request through ``api._api_request`` is keyed by a hash of its method, path,
and body, and ``STORYFORGE_CASSETTE_MODE`` decides what happens:

- ``replay`` (default): return the recorded response. A request with no
  recording raises ``CassetteMiss`` — a replay that quietly went live would
  spend money and stop being deterministic, which is the whole point lost.
- ``record``: call the API and overwrite the recording — once per run. A
  request this run already recorded (two cases sharing one scene send the
  same extraction request) replays that recording: a second live call would
  overwrite the first reply, and whatever was built from the first (a
  judge prompt quoting it) could then never replay.
- ``auto``: replay what exists, record what does not.

Environment variables rather than a function argument because evals drive
commands as subprocesses too, and the environment is what they inherit.

``STORYFORGE_CASSETTE_LOG``, if set, names a JSONL file that gets one line per
call (key, model, usage, whether it was replayed). The harness sums it into a
cost report; a replayed call reports what it *would* have cost live.

Every cassette failure is a ``CassetteError``, and every one is also written
to that log before it is raised. Command code is full of ``except Exception``
that turns an API failure into a skipped scene, so the exception alone cannot
be trusted to reach the harness — the log line can, and the harness treats a
logged failure as an errored suite whatever the suite returned.

The Batch API is refused under a cassette: its ids and polling sequence are
not reproducible, so a recording of one could never replay.
"""

import gzip
import hashlib
import json
import os
import tempfile

MODES = ('replay', 'record', 'auto')


class CassetteError(RuntimeError):
    """The cassette could not serve a request (bad mode, bad recording, batch call)."""


class CassetteMiss(CassetteError):
    """A replay-mode request has no recording."""


def active_dir() -> str:
    return os.environ.get('STORYFORGE_CASSETTE', '')


def mode() -> str:
    value = os.environ.get('STORYFORGE_CASSETTE_MODE', 'replay')
    if value not in MODES:
        raise CassetteError(
            f'STORYFORGE_CASSETTE_MODE={value!r} is not one of {", ".join(MODES)}')
    return value


def request_key(method: str, path: str, body: dict | None) -> str:
    canonical = json.dumps({'method': method, 'path': path, 'body': body},
                           sort_keys=True, separators=(',', ':'))
    return hashlib.sha256(canonical.encode()).hexdigest()


def recording_path(cassette_dir: str, key: str) -> str:
    """Where a recording is written: gzipped JSON, since a recording keeps the
    full request (often a whole scene plus its references) for debugging."""
    return os.path.join(cassette_dir, key[:2], f'{key}.json.gz')


def _existing_recording(cassette_dir: str, key: str) -> str:
    """The recording for ``key`` if one exists — gzipped, or plain JSON from
    before recordings were compressed — else ''."""
    gz = recording_path(cassette_dir, key)
    plain = gz[:-len('.gz')]
    return gz if os.path.isfile(gz) else plain if os.path.isfile(plain) else ''


# Keys this process recorded live, per run (a run is its log file); the log
# itself (below) covers subprocesses too
_recorded_here: set[tuple[str, str, str]] = set()


def _run_id(cassette_dir: str, key: str) -> tuple[str, str, str]:
    return (os.environ.get('STORYFORGE_CASSETTE_LOG', ''), cassette_dir, key)


def _recorded_this_run(cassette_dir: str, key: str) -> bool:
    """Whether this run already recorded ``key`` live: in this process, or
    in any process sharing the run's ``STORYFORGE_CASSETTE_LOG``."""
    if _run_id(cassette_dir, key) in _recorded_here:
        return True
    log_file = os.environ.get('STORYFORGE_CASSETTE_LOG', '')
    if not log_file or not os.path.isfile(log_file):
        return False
    with open(log_file) as f:
        for line in f:
            if key not in line:
                continue
            try:
                entry = json.loads(line)
            except ValueError:
                continue
            if entry.get('key') == key and entry.get('replayed') is False:
                return True
    return False


def _append_log(entry: dict) -> None:
    log_file = os.environ.get('STORYFORGE_CASSETTE_LOG', '')
    if log_file:
        with open(log_file, 'a') as f:
            f.write(json.dumps(entry) + '\n')


def _log_call(key: str, body: dict | None, response: dict, replayed: bool) -> None:
    _append_log({
        'key': key,
        'model': (body or {}).get('model', ''),
        'usage': response.get('usage', {}) if isinstance(response, dict) else {},
        'replayed': replayed,
    })


def _fail(error: CassetteError) -> CassetteError:
    """Log ``error`` where the harness will see it, then hand it back to raise."""
    try:
        _append_log({'error': f'{type(error).__name__}: {error}'})
    except OSError:
        pass  # the raise below still reports it; a log we cannot write is not a second failure
    return error


def _prompt_preview(body: dict | None) -> str:
    try:
        content = body['messages'][-1]['content']
    except (KeyError, IndexError, TypeError):
        return ''
    text = content if isinstance(content, str) else json.dumps(content)
    return ' '.join(text[:200].split())


def request(method: str, path: str, body: dict | None, live) -> dict:
    """Serve one API request through the active cassette.

    ``live`` is a zero-argument callable that performs the real request.
    """
    cassette_dir = active_dir()
    if path.startswith('messages/batches'):
        raise _fail(CassetteError(
            'The Batch API cannot run under STORYFORGE_CASSETTE: batch ids and '
            'polling are not reproducible. Run the command in direct mode.'))
    try:
        current = mode()
    except CassetteError as e:
        raise _fail(e)
    key = request_key(method, path, body)
    target = recording_path(cassette_dir, key)

    existing = _existing_recording(cassette_dir, key)
    if existing and (current != 'record' or _recorded_this_run(cassette_dir, key)):
        try:
            opener = gzip.open if existing.endswith('.gz') else open
            with opener(existing, 'rt', encoding='utf-8') as f:
                response = json.load(f)['response']
        except (OSError, EOFError, ValueError, KeyError, TypeError) as e:
            raise _fail(CassetteError(f'Unreadable recording {existing}: {e}')) from e
        _log_call(key, body, response, replayed=True)
        return response

    if current == 'replay':
        raise _fail(CassetteMiss(
            f'No recording for {method} {path} (key {key[:12]}) in {cassette_dir}. '
            f'Prompt starts: "{_prompt_preview(body)}". If the prompt embeds a temp '
            f'path, date, or id it changes every run and can never replay. Otherwise '
            f're-run with STORYFORGE_CASSETTE_MODE=record or auto.'))

    try:
        response = live()
    except Exception as e:
        # Command code often swallows API errors into a skipped scene; the
        # log is how the harness still sees a failed live call
        try:
            _append_log({'error': f'live call failed: {type(e).__name__}: {e}'})
        except OSError:
            pass
        raise
    try:
        os.makedirs(os.path.dirname(target), exist_ok=True)
        fd, tmp = tempfile.mkstemp(dir=os.path.dirname(target), suffix='.tmp')
        with os.fdopen(fd, 'wb') as raw, gzip.GzipFile(fileobj=raw, mode='wb', mtime=0) as f:
            f.write(json.dumps({'request': {'method': method, 'path': path, 'body': body},
                                'response': response}, indent=1).encode('utf-8'))
        os.replace(tmp, target)
    except OSError as e:
        # The call was paid for: log it, and the failure, where the harness
        # sees both (command code may swallow the raise)
        _log_call(key, body, response, replayed=False)
        raise _fail(CassetteError(f'Could not save the recording {target}: {e}')) from e
    plain = target[:-len('.gz')]
    if os.path.isfile(plain):
        os.remove(plain)  # a re-record supersedes the uncompressed original
    # Logged once the recording is in place: a later identical request in
    # this run replays it (see _recorded_this_run), never an older one
    _log_call(key, body, response, replayed=False)
    _recorded_here.add(_run_id(cassette_dir, key))
    return response
