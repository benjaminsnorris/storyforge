"""Extraction typing (#788): does the gate's extraction type what someone
wears, carries or holds as `state`, and what holds for the whole book (a
trait) as `fixed`?

*Wrath Like Smoke* (2026-11-27): extraction recorded a character's armour as
a fixed trait, so the scene built on trading it away halted with no prose
fix possible (`audit.halting_conditions`: a fixed fact a later scene changes
stops that scene). The gear was folded into how the characters look ("the
gold on his armor catching the sun"), beside true traits.

Two suites score the same way:

- `extraction-typing`: invented scenes (`fixtures/extraction-typing/`; this
  repo is public, so no book prose). They pass on the prompt before #788
  too: a short scene alone doesn't bring the slip out. They guard the
  other way, a fixed trait read as state.
- `extraction-typing-book`: real scenes where the slip happened, from the
  books in the corpus (`STORYFORGE_CORPUS_DIR`) at a pinned commit, with
  the gate's full prompt for them (`gate.extraction_prompt`: the facts in
  force and the registries, the scene's own commitments left out as for a
  redraft). Private, like the gate set: the set (its labels quote the
  prose) and its recordings are in the storyforge-evals repo
  (`extraction-typing/`). Before #788, 3 of the 5 gear facts read were
  fixed in both of two readings. Recorded at the new wording: the armour
  and the leopard skin state, the fact merging Menelaus's crest with his
  hair fixed, Sarpedon's tunic not read (`missing`).

Each scene goes through the gate's own extraction and persistence calls
(`gate._read_commitments`, the gate's model and thinking setting); typing is
read off the extraction reply. A label (the words that establish one fact,
and its kind) matches the extracted fact whose quote shares the most of its
content words, at least half of them and `MIN_SHARED`, each fact matching
one label at most (`assign`); none is `missing`, reported and not scored. Metrics: `state_right` (`worn`, `carried`, `held`
labels typed state, over those found), `fixed_right` (`trait` labels typed
fixed, over those found), the counts found, and `missing`. Gates hold the
recorded values exactly (#488).
"""

from __future__ import annotations

import json
import os

from harness import Gate, SuiteOutput

#: Label kinds that should be `state`; every other kind (`trait`) `fixed`
STATE_KINDS = ('worn', 'carried', 'held')
KINDS = (*STATE_KINDS, 'trait')
#: The fewest content words a label and an extracted quote share to match
#: (and at least half the label's)
MIN_SHARED = 2
SET_NAME = 'extraction-typing'


def _words(text: str) -> set[str]:
    """`text`'s content words (`gate._content_words`: stems, no function
    words; #790's review SF-3: "the", "on" and "his" match anything)."""
    from storyforge.gate import _content_words
    return _content_words(text or '')


def _shared_enough(label: set[str], n: int) -> bool:
    return n >= max(MIN_SHARED, (len(label) + 1) // 2)


def match(label: str, found: list[dict]) -> dict | None:
    """The extracted fact whose quote shares the most content words with
    `label`, enough of them (`_shared_enough`); None when none does."""
    want = _words(label)
    best, best_n = None, 0
    for f in found:
        n = len(want & _words(f.get('quote', '')))
        if n > best_n and _shared_enough(want, n):
            best, best_n = f, n
    return best


def assign(labels: list[dict], found: list[dict]) -> list[dict | None]:
    """Each label's fact, each fact taken by one label at most (#790's
    review TD-5: a fact merging gear with a trait would otherwise be scored
    for both, one of them wrong by construction): the pairs sharing the
    most content words first."""
    pairs = []
    for i, lab in enumerate(labels):
        want = _words(lab['quote'])
        for j, f in enumerate(found):
            n = len(want & _words(f.get('quote', '')))
            if _shared_enough(want, n):
                pairs.append((-n, i, j))
    out: list[dict | None] = [None] * len(labels)
    taken: set[int] = set()
    for _, i, j in sorted(pairs):
        if out[i] is None and j not in taken:
            out[i] = found[j]
            taken.add(j)
    return out


def score(scenes: list[dict], extracted: dict[str, list[dict]], *,
          quote_labels: bool = True) -> tuple[dict, list[str]]:
    """Metrics and notes for `extracted` (scene id → the facts read).
    `quote_labels`: name a label by its words in the notes (False for a
    private set: by its kind and number)."""
    counts = {'state': [0, 0], 'fixed': [0, 0]}   # [right, found]
    missing, notes = 0, []
    for scene in scenes:
        for n, lab in enumerate(scene['labels'], start=1):
            if lab['kind'] not in KINDS:
                raise ValueError(f'{scene["id"]} label {n}: kind {lab["kind"]!r} is not one '
                                 f'of {", ".join(KINDS)}')
        got_all = assign(scene['labels'], extracted.get(scene['id'], []))
        for n, (lab, got) in enumerate(zip(scene['labels'], got_all), start=1):
            name = (f'{scene["id"]}: {lab["kind"]} "{lab["quote"]}"' if quote_labels
                    else f'{scene["id"]}: label {n} ({lab["kind"]})')
            want = 'state' if lab['kind'] in STATE_KINDS else 'fixed'
            if got is None:
                missing += 1
                notes.append(f'{name}: missing')
                continue
            typed = (got.get('mutable') or 'state').strip()
            counts[want][1] += 1
            counts[want][0] += typed == want
            if typed != want:
                notes.append(f'{name}: typed {typed}, should be {want}'
                             + (f' ("{got.get("statement", "")}")' if quote_labels else ''))

    def share(k):
        right, found = counts[k]
        return round(right / found, 4) if found else 0.0
    return {'state_right': share('state'), 'fixed_right': share('fixed'),
            'state_found': counts['state'][1], 'fixed_found': counts['fixed'][1],
            'missing': missing}, notes


def read(scene_id: str, prose: str, prompt: str, log_dir: str) -> list[dict]:
    """The gate's extraction of `prose` from `prompt` (and its persistence
    check, which the gate always runs): the facts the reply read."""
    from storyforge import gate
    from storyforge.common import select_model
    os.makedirs(log_dir, exist_ok=True)
    found, _verdict = gate._read_commitments(scene_id, prose, prompt,
                                             select_model('evaluation'), log_dir)
    return found


def output(metrics: dict, notes: list[str], floors: dict) -> SuiteOutput:
    from storyforge.common import select_model
    gates = [Gate(k, metrics[k], '==', v) for k, v in floors.items() if v is not None]
    if not gates:
        notes.append('no floor recorded yet: record the suite, then set FLOORS to its values')
        gates = [Gate('state_found', metrics['state_found'], '>=', 1)]
    notes.append(f'model {select_model("evaluation")}; typing read off the extraction reply, '
                 f'before the persistence check')
    return SuiteOutput(metrics=metrics, gates=gates, notes=notes)


# ============================================================================
# The private set: real scenes (extraction-typing-book)
# ============================================================================

def set_dir(root: str | None = None) -> str:
    """The private set's directory; raises `SuiteUnavailable` when it, or
    its `cases.json`, isn't there."""
    import blocking_set
    from harness import SuiteUnavailable
    path = os.path.join(root or blocking_set.private_dir(), SET_NAME)
    if not os.path.isfile(os.path.join(path, 'cases.json')):
        raise SuiteUnavailable(f'the extraction-typing book set is not at {path} (no '
                               f'cases.json): it lives in the private storyforge-evals repo')
    return path


def book_scenes(work_dir: str, root: str | None = None) -> list[dict]:
    """The private set's scenes, each with its `prompt` and `prose` built
    from its book at its pinned commit (`cases.json`: ``{"scenes": [{"id",
    "repo", "commit", "labels"}]}``). Raises `SuiteUnavailable` when a book
    isn't cloned."""
    import e1
    from e8 import materialize
    from harness import SuiteUnavailable
    from storyforge import gate
    with open(os.path.join(set_dir(root), 'cases.json'), encoding='utf-8') as f:
        cases = json.load(f)
    out = []
    for scene in cases['scenes']:
        repo = os.path.join(e1.corpus_dir(), scene['repo'])
        if not os.path.isdir(os.path.join(repo, '.git')):
            raise SuiteUnavailable(f'{scene["repo"]} is not cloned under {e1.corpus_dir()}')
        project = materialize(repo, scene['commit'],
                              os.path.join(work_dir, f'{scene["repo"]}-{scene["commit"][:8]}'))
        with open(os.path.join(project, 'scenes', f'{scene["id"]}.md'), encoding='utf-8') as f:
            prose = f.read()
        out.append({**scene, 'prose': prose,
                    'prompt': gate.extraction_prompt(project, scene['id'], prose)})
    return out
