"""The typed-state set (#744): the gate's typed-state checks (possession,
injury, life, time, travel, knowledge, names, sky: `storyforge.continuity`)
replayed on a real book's gate runs, each finding labelled real, debatable or
false by a reader.

**Why.** The checks are code with unit tests (`tests/test_continuity.py`),
but nothing measured them on a large-cast book: in *Wrath Like Smoke*'s
overnight run (2026-11-16/17) they made 64 blocking findings and none was
real (the checker review, `docs/plans/2026-11-26-checker-review/`, report A
section 2). This set replays those gate runs, free, so a change to the
checks (#732 possession, #733 injury and life) is measured before and after.

**What a run is.** One gate run of one scene: the project as the gate saw it
(the book's commit before the scene's, with the scene's prose, its stage
sheet and its typed state from the scene's own commit), replayed through
`continuity.check_continuity` with the extraction call answered from the
saved typed state (`replay`), so every check, the book it reads and the
quote verification are today's code, and only the model's reply is fixed.
A change to what the extraction returns (a new field, #748) needs new
replies; a change to the checks needs nothing.

**Labels** are report A's verdicts on every typed-state finding of that run
(65: possession 43, injury 13, life 8, time 1), each with the gate runs it
appeared in. A label is scored when one of its runs is in the set; the
others are kept, counted and named (`not_replayable`), for when their runs
can be added.

**Which runs.** The book's repo commits each scene once, with its final
prose and that run's typed state, so the set holds each scene's final gate
run (`build.py`). Earlier runs' replies are in the gate logs
(`working/logs/gate/`, gitignored) and their prose was rebuilt from the
session logs by the review; neither is in the book's repo, so they are not
in the set yet.

**The set is private** (the author's unpublished prose), in the
storyforge-evals repo at `STORYFORGE_PRIVATE_EVALS_DIR` (default
`~/Developer/evals`), under `typed-state-set/`:

- `set.json`: ``{"format", "book", "built_from", "runs", "labels",
  "not_replayable"}``. A run is ``{"id", "scene", "round", "commit",
  "files": {path: sha256}}``; a label ``{"id", "scene", "rounds", "check",
  "verdict", "quote", "reason"}`` (`VERDICTS`, `CHECKS`); `not_replayable`
  names each gate run left out and why.
- `blobs/<sha256[:2]>/<sha256>.gz`: each file's bytes, gzipped, stored once
  however many runs share it.
- `results/latest.json` (gitignored there): the last run's findings per
  run, with quotes. Nothing in this repo quotes the set; the suite's notes
  carry label ids, scene ids and counts.

**Matching.** A finding is on a label when they are of the same scene and
check, the label lists the run's round, and their quotes are on the same
words (`continuity.overlaps`, normalized, one inside the other). Each
finding takes at most one label and each label one finding.
"""

from __future__ import annotations

import gzip
import hashlib
import json
import os
import re
from collections import Counter
from contextlib import contextmanager

from harness import SuiteUnavailable

PRIVATE_ENV = 'STORYFORGE_PRIVATE_EVALS_DIR'
SET_NAME = 'typed-state-set'
SET_FILE = 'set.json'
FORMAT = 1

#: `continuity.CODES`' checks, in the order the suite reports them
CHECKS = ('possession', 'injury', 'life', 'time', 'travel', 'knowledge', 'names', 'sky')
VERDICTS = ('real', 'debatable', 'false')
_CHECK_IN_EXPLANATION = re.compile(r'^\(typed state, (\w+)\)')


class ReplayError(ValueError):
    """A run this module can't replay. Its message names run ids, paths and
    hashes, never prose, so it may reach the report."""


class SetMissing(SuiteUnavailable):
    """The private set isn't on this machine; the message says where to put it."""


def private_dir() -> str:
    return os.environ.get(PRIVATE_ENV) or os.path.expanduser('~/Developer/evals')


def set_dir(root: str | None = None) -> str:
    """The set's directory. Raises `SetMissing` when its `set.json` isn't there."""
    path = os.path.join(root or private_dir(), SET_NAME)
    if not os.path.isfile(os.path.join(path, SET_FILE)):
        raise SetMissing(
            f'the typed-state set is not at {path} (no {SET_FILE}): it lives in the private '
            f'storyforge-evals repo (benjaminsnorris/storyforge-evals, {SET_NAME}/). Clone it '
            f'to ~/Developer/evals or set {PRIVATE_ENV} to its checkout.')
    return path


def load(path: str) -> dict:
    """`set.json`. Raises ValueError when it isn't one of this format."""
    with open(os.path.join(path, SET_FILE), encoding='utf-8') as f:
        data = json.load(f)
    if not isinstance(data, dict) or data.get('format') != FORMAT:
        raise ValueError(f'{path}/{SET_FILE}: not format {FORMAT}')
    for key in ('runs', 'labels', 'not_replayable'):
        if not isinstance(data.get(key), list):
            raise ValueError(f'{path}/{SET_FILE}: no "{key}" list')
    return data


def fingerprint(path: str) -> str:
    """A hash of `set.json`, which names every file by its hash: floors
    measured on one set mean nothing on another."""
    with open(os.path.join(path, SET_FILE), 'rb') as f:
        return hashlib.sha256(f.read()).hexdigest()


def validate(data: dict) -> list[str]:
    """What's wrong with the set, one line each, naming ids (never quotes)."""
    problems = []
    ids = Counter(r.get('id') for r in data['runs'])
    problems += [f'run id {i!r} repeated' for i, n in ids.items() if n > 1]
    for r in data['runs']:
        for key in ('id', 'scene', 'round', 'commit'):
            if not isinstance(r.get(key), str) or not r.get(key):
                problems.append(f'run {r.get("id")!r}: no {key}')
        files = r.get('files')
        if not isinstance(files, dict) or f'scenes/{r.get("scene")}.md' not in files:
            problems.append(f'run {r.get("id")!r}: its scene\'s prose is not among its files')
        elif f'working/typed-state/{r.get("scene")}.json' not in files:
            problems.append(f'run {r.get("id")!r}: its scene\'s typed state is not among its '
                            f'files')
    labels = Counter(lab.get('id') for lab in data['labels'])
    problems += [f'label id {i!r} repeated' for i, n in labels.items() if n > 1]
    for lab in data['labels']:
        if lab.get('check') not in CHECKS:
            problems.append(f'label {lab.get("id")!r}: check {lab.get("check")!r} is not one of '
                            f'{", ".join(CHECKS)}')
        if lab.get('verdict') not in VERDICTS:
            problems.append(f'label {lab.get("id")!r}: verdict {lab.get("verdict")!r} is not '
                            f'one of {", ".join(VERDICTS)}')
        if not (isinstance(lab.get('rounds'), list) and lab['rounds']):
            problems.append(f'label {lab.get("id")!r}: no rounds')
        if not (isinstance(lab.get('quote'), str) and lab['quote'].strip()):
            problems.append(f'label {lab.get("id")!r}: no quote')
    return problems


# ============================================================================
# Files
# ============================================================================

def blob_path(path: str, digest: str) -> str:
    return os.path.join(path, 'blobs', digest[:2], f'{digest}.gz')


def put_blob(path: str, data: bytes) -> str:
    """Store `data` once; its sha256."""
    digest = hashlib.sha256(data).hexdigest()
    file = blob_path(path, digest)
    if not os.path.isfile(file):
        os.makedirs(os.path.dirname(file), exist_ok=True)
        # mtime=0: the same bytes always make the same file
        with open(file, 'wb') as f:
            f.write(gzip.compress(data, mtime=0))
    return digest


def materialize(path: str, run: dict, dest: str) -> str:
    """Write `run`'s files under `dest`; returns `dest`. Raises ReplayError
    when a path leaves the project, or a blob is missing or isn't the bytes
    its name says."""
    for rel, digest in sorted(run['files'].items()):
        norm = os.path.normpath(rel)
        if os.path.isabs(norm) or norm.startswith('..'):
            raise ReplayError(f'run {run["id"]}: file path {rel!r} leaves the project')
        file = blob_path(path, digest)
        if not os.path.isfile(file):
            raise ReplayError(f'run {run["id"]}: blob {digest[:12]} ({rel}) is missing')
        with open(file, 'rb') as f:
            data = gzip.decompress(f.read())
        if hashlib.sha256(data).hexdigest() != digest:
            raise ReplayError(f'run {run["id"]}: blob {digest[:12]} ({rel}) is not its bytes')
        out = os.path.join(dest, norm)
        os.makedirs(os.path.dirname(out), exist_ok=True)
        with open(out, 'wb') as f:
            f.write(data)
    return dest


# ============================================================================
# Replay
# ============================================================================

@contextmanager
def logged_reply(items: list[dict]):
    """While active, the typed-state extraction call returns `items` (the
    logged reply's records) instead of calling a model."""
    from storyforge import typed_state
    saved = typed_state._call
    typed_state._call = lambda *a, **k: [dict(it) for it in items]
    try:
        yield
    finally:
        typed_state._call = saved


def replay(project: str, scene: str):
    """`continuity.check_continuity` on `scene` as the gate ran it, the
    extraction answered from the scene's saved typed state. Returns its
    `ContinuityResult`. Raises ReplayError when the saved state isn't of the
    scene's prose (it would be another run's reply)."""
    from storyforge import continuity, typed_state
    from storyforge.illustrations import read_scene_raw
    prose = read_scene_raw(project, scene)
    data = typed_state.load_state(typed_state.state_path(project, scene))
    if data.get('prose_sha256') != typed_state.prose_hash(prose or ''):
        raise ReplayError(f'{scene}: its typed state is not of its prose')
    items = [{'type': r.type, 'who': r.who, 'item': r.item, 'value': r.value,
              'detail': r.detail, 'quote': r.quote} for r in data['records']]
    with logged_reply(items):
        # the model the reply came from: it only names the prompt here, and
        # resolving the default would ask the API for its model list
        return continuity.check_continuity(project, scene, prose=prose, reuse=False,
                                           save=False, model=data.get('model') or 'replayed')


def check_of(finding) -> str:
    """The typed check a finding came from ('' when it names none)."""
    m = _CHECK_IN_EXPLANATION.match(finding.explanation or '')
    return m.group(1) if m else ''


def replay_run(path: str, run: dict, dest: str) -> dict:
    """One run, materialized under `dest` and replayed: ``{"findings":
    [{"check", "quote", "established_scene", "explanation"}], "notes"}``,
    or ``{"error": ...}``: a `ReplayError` with its own message (it names
    ids, paths and hashes, never prose), anything else by its type only
    (its message can quote the prose: a malformed record, a reply). Top
    level, plain data in and out, for a process pool."""
    try:
        result = replay(materialize(path, run, dest), run['scene'])
    except ReplayError as e:
        return {'error': f'ReplayError: {e}'}
    except Exception as e:
        return {'error': type(e).__name__}
    return {'findings': [{'check': check_of(f), 'quote': f.scene_quote,
                          'established_scene': f.established_scene,
                          'explanation': f.explanation} for f in result.findings],
            'notes': list(result.notes)}


# ============================================================================
# Scoring
# ============================================================================

def match(run: dict, findings: list[dict], labels: list[dict]) -> list[tuple[dict, dict | None]]:
    """Each finding (``{"check", "quote", ...}``) with the label it is on, or
    None. A label is on a finding of its scene and check when it lists the
    run's round and their quotes overlap; each label is used once."""
    from storyforge.continuity import overlaps
    mine = [lab for lab in labels
            if lab['scene'] == run['scene'] and run['round'] in lab['rounds']]
    used: set[str] = set()
    out = []
    for f in findings:
        lab = next((lab for lab in mine if lab['id'] not in used and lab['check'] == f['check']
                    and overlaps(lab['quote'], f['quote'])), None)
        if lab is not None:
            used.add(lab['id'])
        out.append((f, lab))
    return out


def replayable(data: dict) -> list[dict]:
    """The labels one of whose rounds is a run in the set."""
    runs = {(r['scene'], r['round']) for r in data['runs']}
    return [lab for lab in data['labels']
            if any((lab['scene'], rnd) in runs for rnd in lab['rounds'])]


def score(data: dict, found: dict[str, list[dict]]) -> tuple[dict, dict]:
    """Metrics, and the ids behind them, from each run's findings (`found`,
    by run id). Per check: `{check}_findings`, `_false`, `_debatable`,
    `_real` (labelled findings by verdict), `_unlabelled`, and
    `_precision` (real over findings) when it made any. Overall: the same
    as `findings`, `false_alarms`, `debatable_found`, `real_kept`,
    `unlabelled`, plus `real_missed` and `cleared` (labels in the set no
    finding is on: a real catch lost, a false or debatable one gone)."""
    labels = replayable(data)
    per = {c: Counter() for c in CHECKS}
    ids = {'false': [], 'debatable': [], 'real': [], 'unlabelled': []}
    hit: set[str] = set()
    for run in data['runs']:
        for f, lab in match(run, found.get(run['id'], []), labels):
            c = f['check'] if f['check'] in per else 'other'
            per.setdefault(c, Counter())['findings'] += 1
            if lab is None:
                per[c]['unlabelled'] += 1
                ids['unlabelled'].append(f'{run["scene"]} ({f["check"] or "?"})')
            else:
                hit.add(lab['id'])
                per[c][lab['verdict']] += 1
                ids[lab['verdict']].append(lab['id'])
    m: dict[str, float] = {'runs': len(data['runs']), 'labels': len(data['labels']),
                           'labels_in_set': len(labels)}
    for c, n in per.items():
        for k in ('findings', 'false', 'debatable', 'real', 'unlabelled'):
            m[f'{c}_{k}'] = n[k]
        if n['findings']:
            m[f'{c}_precision'] = round(n['real'] / n['findings'], 4)
    total = sum(per.values(), Counter())
    m.update(findings=total['findings'], false_alarms=total['false'],
             debatable_found=total['debatable'], real_kept=total['real'],
             unlabelled=total['unlabelled'])
    if total['findings']:
        m['precision'] = round(total['real'] / total['findings'], 4)
    ids['real_missed'] = [lab['id'] for lab in labels
                          if lab['verdict'] == 'real' and lab['id'] not in hit]
    ids['cleared'] = [lab['id'] for lab in labels
                      if lab['verdict'] != 'real' and lab['id'] not in hit]
    m['real_missed'] = len(ids['real_missed'])
    m['cleared'] = len(ids['cleared'])
    return m, ids
