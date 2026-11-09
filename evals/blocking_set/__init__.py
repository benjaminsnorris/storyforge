"""The blocking set (#646): known blocking slips, labelled, to measure a
blocking check against.

Blocking errors (which hand holds what, who sits, who can see what, what is
worn, where people and things are, where the light falls) are real
continuity errors, and they block. To replace today's whole-scene blocking
read (`storyforge.blocking`, #626) with the stage sheet (#647), both need a
fixed set of known slips to be measured against (plan
`docs/plans/2026-11-08-deterministic-gate-and-voiceprint.md`, A4 and Part E).

**The set is private.** Its scenes are the author's unpublished prose, and
this repo is public, so the set lives in the private storyforge-evals repo
(benjaminsnorris/storyforge-evals), cloned at `STORYFORGE_PRIVATE_EVALS_DIR`
(default `~/Developer/evals`), under `blocking-set/`. Its recordings live
there too (`blocking-set/cassettes/<suite>/`): a recording holds the request,
and the request holds the scene. Nothing in this module, the suite or the
tests may quote it; what this repo keeps is code, counts and rates.

Layout of `blocking-set/` (built by its `build.py`, which says where every
case came from):

- `scenes.json`: a list of scenes ``{"book", "scene", "pov", "role", "commit",
  "words", ...}``; ``role`` is ``case`` (a scene with labelled slips, as it
  stood before they were fixed) or ``clean`` (no slip known after close
  reads, for false alarms).
- `scenes/<book>/<scene>.md`: each scene's prose.
- `cases.json`: ``{"cases": [<case>, ...]}``, a case being::

      {"id": "gawain-001", "book": "gawain", "scene": "<scene id>",
       "category": "hands",      # CATEGORIES
       "scope": "scene",         # SCOPES: "book" needs facts from other scenes
       "verdict": "fixed",       # VERDICTS: "fixed" a real slip, fixed;
                                 # "left" a reading judged plausible and
                                 # left alone (a flag on it is a false alarm)
       "quotes": ["<verbatim>", ...],     # the slip, then what it's set against
       "fix_quotes": ["<verbatim>", ...], # optional: other lines the fix changed
       "summary": "...", "fix": "...", "found_by": "...", "kind": "..."}

**Matching.** A finding catches a case when one of its quotes falls on the
same words of the scene as one of the case's quotes (or fix quotes): their
places in the normalized prose (`storyforge.quotes.normalize`) overlap. A
finding is about a place in the scene, and the place is what the labels
give; wording varies between readings. Only verified findings can catch a
case: an unverified finding's quote isn't in the scene, so it has no place.
"""

from __future__ import annotations

import json
import os
import re
from collections import Counter

PRIVATE_ENV = 'STORYFORGE_PRIVATE_EVALS_DIR'
SET_NAME = 'blocking-set'

CATEGORIES = ('hands', 'posture', 'sightline', 'worn', 'position', 'light', 'other')
SCOPES = ('scene', 'book')
VERDICTS = ('fixed', 'left')
ROLES = ('case', 'clean')
BOOK_ID = re.compile(r'^[a-z0-9-]+$')

#: Who found a case, as the two subsets the plan compares: slips people
#: found (`readers`: the gawain readers and Ben's notes) and slips a
#: blocking read found (`tool`), whose recall is partly the read's
#: run-to-run agreement with itself
SUBSET_READERS = ('readers', 'author')


class SetMissing(RuntimeError):
    """The private set isn't on this machine; the message says where to put it."""


def private_dir() -> str:
    return os.environ.get(PRIVATE_ENV) or os.path.expanduser('~/Developer/evals')


def set_dir(root: str | None = None) -> str:
    """The set's directory. Raises `SetMissing` when it isn't there."""
    path = os.path.join(root or private_dir(), SET_NAME)
    if not os.path.isfile(os.path.join(path, 'cases.json')):
        raise SetMissing(
            f'the blocking set is not at {path}: it lives in the private storyforge-evals '
            f'repo (benjaminsnorris/storyforge-evals, {SET_NAME}/). Clone it to '
            f'~/Developer/evals or set {PRIVATE_ENV} to its checkout.')
    return path


def cassettes_dir(suite_name: str, root: str | None = None) -> str:
    """Where the suite's recordings live: beside the set, never in this repo."""
    return os.path.join(set_dir(root), 'cassettes', suite_name)


def load(path: str) -> tuple[list[dict], list[dict]]:
    """(cases, scenes), each scene with its `text` read in."""
    with open(os.path.join(path, 'cases.json'), encoding='utf-8') as f:
        cases = json.load(f).get('cases', [])
    with open(os.path.join(path, 'scenes.json'), encoding='utf-8') as f:
        scenes = json.load(f)
    for s in scenes:
        file = scene_file(path, s)
        s['text'] = ''
        if os.path.isfile(file):
            with open(file, encoding='utf-8') as f:
                s['text'] = f.read()
    return cases, scenes


def scene_file(path: str, scene: dict) -> str:
    return os.path.join(path, 'scenes', str(scene.get('book')), f'{scene.get("scene")}.md')


def validate(cases: list[dict], scenes: list[dict]) -> list[str]:
    """Every way the set departs from its format, without quoting it (a
    problem names a case or scene id, never its words). Empty when sound."""
    from storyforge.quotes import quote_in
    problems = []
    by_key = {}
    for s in scenes:
        key = (s.get('book'), s.get('scene'))
        where = f'scene {key[0]}/{key[1]}'
        if not (isinstance(key[0], str) and BOOK_ID.match(key[0])
                and isinstance(key[1], str) and BOOK_ID.match(key[1])):
            problems.append(f'{where}: book and scene must be slugs')
            continue
        if key in by_key:
            problems.append(f'{where}: listed twice')
        by_key[key] = s
        if s.get('role') not in ROLES:
            problems.append(f'{where}: role must be one of {ROLES}')
        if not (s.get('text') or '').strip():
            problems.append(f'{where}: no prose (scenes/{key[0]}/{key[1]}.md)')
    ids = Counter(c.get('id') for c in cases)
    for c in cases:
        cid = c.get('id') or '<no id>'
        if ids[c.get('id')] > 1:
            problems.append(f'{cid}: id used {ids[c.get("id")]} times')
        if c.get('category') not in CATEGORIES:
            problems.append(f'{cid}: category must be one of {CATEGORIES}')
        if c.get('scope', 'scene') not in SCOPES:
            problems.append(f'{cid}: scope must be one of {SCOPES}')
        if c.get('verdict') not in VERDICTS:
            problems.append(f'{cid}: verdict must be one of {VERDICTS}')
        scene = by_key.get((c.get('book'), c.get('scene')))
        if scene is None:
            problems.append(f'{cid}: its scene is not in scenes.json')
            continue
        if c.get('verdict') == 'fixed' and scene.get('role') != 'case':
            problems.append(f'{cid}: a fixed slip in a scene whose role is not case')
        quotes = c.get('quotes')
        if not (isinstance(quotes, list) and quotes):
            problems.append(f'{cid}: no quotes')
            continue
        for n, q in enumerate(list(quotes) + list(c.get('fix_quotes') or []), 1):
            if not (isinstance(q, str) and q.strip() and quote_in(scene['text'], q)):
                problems.append(f'{cid}: quote {n} is not in its scene')
    return problems


# --- matching ---------------------------------------------------------------

def spans(prose_normalized: str, quote: str) -> list[tuple[int, int]]:
    """Every place `quote` (or each `...`-separated part of it) falls in the
    normalized prose, as character ranges."""
    from storyforge.quotes import normalize
    out = []
    for part in normalize(quote).split('...'):
        part = part.strip(' .,;:!?"\'-')
        if not re.search(r'\w', part):
            continue
        out.extend((m.start(), m.end()) for m in re.finditer(re.escape(part), prose_normalized))
    return out


def overlaps(a: list[tuple[int, int]], b: list[tuple[int, int]]) -> bool:
    return any(a0 < b1 and b0 < a1 for a0, a1 in a for b0, b1 in b)


def case_spans(prose_normalized: str, case: dict) -> list[tuple[int, int]]:
    return [sp for q in list(case['quotes']) + list(case.get('fix_quotes') or [])
            for sp in spans(prose_normalized, q)]


def finding_spans(prose_normalized: str, finding: dict) -> list[tuple[int, int]]:
    return [sp for q in finding.get('quotes', []) for sp in spans(prose_normalized, q)]


# --- scoring ----------------------------------------------------------------

def _rate(hit: int, of: int) -> float:
    return round(hit / of, 4) if of else 0.0


def subset(case: dict) -> str:
    return 'readers' if str(case.get('found_by', '')).startswith(SUBSET_READERS) else 'tool'


def score(cases: list[dict], scenes: list[dict],
          flags: dict[tuple[str, str], list[dict]]) -> tuple[dict, list[dict]]:
    """Metrics and per-case outcomes.

    `flags` maps (book, scene) to that scene's findings, each
    ``{"quotes": [...], "verified": bool}``; every scene in `scenes` must
    have an entry (an empty list when the check found nothing), or this
    raises: a scene left unchecked would read as one with no flags.

    Recall is over the `fixed` cases, overall, per category, per book and
    per subset; `book`-scope cases (they need facts from other scenes,
    which a read of the scene alone can't have) are reported apart and kept
    out of the headline recall. False alarms: every finding on a clean
    scene, verified or not (the gate stops on both), per 10,000 words of
    clean prose; and the findings on a `left` reading anywhere. A verified
    finding on a case scene that matches no case is `unlabelled`: a slip no
    one labelled or a false alarm, so it is counted, never scored.
    """
    from storyforge.quotes import normalize
    missing = [f'{s["book"]}/{s["scene"]}' for s in scenes if (s['book'], s['scene']) not in flags]
    if missing:
        raise ValueError(f'{len(missing)} scene(s) have no result')
    by_key = {(s['book'], s['scene']): s for s in scenes}
    norm = {k: normalize(s['text']) for k, s in by_key.items()}
    found_spans = {k: [(f, finding_spans(norm[k], f)) for f in flags[k] if f.get('verified')]
                   for k in by_key}
    outcomes, matched = [], set()
    for c in cases:
        key = (c['book'], c['scene'])
        cs = case_spans(norm[key], c)
        hits = [i for i, (f, fs) in enumerate(found_spans[key]) if overlaps(fs, cs)]
        matched.update((key, i) for i in hits)
        outcomes.append({'id': c['id'], 'caught': bool(hits), 'findings': hits})
    caught = {o['id'] for o in outcomes if o['caught']}

    def recall(group):
        return _rate(sum(1 for c in group if c['id'] in caught), len(group))

    fixed = [c for c in cases if c['verdict'] == 'fixed']
    in_scene = [c for c in fixed if c.get('scope', 'scene') == 'scene']
    book_scope = [c for c in fixed if c.get('scope', 'scene') == 'book']
    left = [c for c in cases if c['verdict'] == 'left']
    clean = [k for k, s in by_key.items() if s['role'] == 'clean']
    case_keys = [k for k, s in by_key.items() if s['role'] == 'case']
    clean_words = sum(len(by_key[k]['text'].split()) for k in clean)
    case_words = sum(len(by_key[k]['text'].split()) for k in case_keys)
    clean_flags = sum(len(flags[k]) for k in clean)
    unlabelled = sum(1 for k in case_keys for i in range(len(found_spans[k])) if (k, i) not in matched)
    metrics = {
        'cases': len(in_scene),
        'caught': sum(1 for c in in_scene if c['id'] in caught),
        'recall': recall(in_scene),
        **{f'recall_{cat}': recall([c for c in in_scene if c['category'] == cat])
           for cat in CATEGORIES if any(c['category'] == cat for c in in_scene)},
        **{f'cases_{cat}': sum(1 for c in in_scene if c['category'] == cat)
           for cat in CATEGORIES if any(c['category'] == cat for c in in_scene)},
        **{f'recall_book_{b}': recall([c for c in in_scene if c['book'] == b])
           for b in sorted({c['book'] for c in in_scene})},
        **{f'recall_found_by_{name}': recall([c for c in in_scene if subset(c) == name])
           for name in ('readers', 'tool') if any(subset(c) == name for c in in_scene)},
        'book_scope_cases': len(book_scope),
        'book_scope_caught': sum(1 for c in book_scope if c['id'] in caught),
        'left_cases': len(left),
        'left_flagged': sum(1 for c in left if c['id'] in caught),
        'clean_scenes': len(clean),
        'clean_words': clean_words,
        'clean_flags': clean_flags,
        'false_alarms_per_10k': round(clean_flags * 10000 / clean_words, 2) if clean_words else 0.0,
        'case_scene_words': case_words,
        'unlabelled_flags': unlabelled,
        'unlabelled_per_10k': round(unlabelled * 10000 / case_words, 2) if case_words else 0.0,
        'flags': sum(len(v) for v in flags.values()),
        'unverified_flags': sum(1 for v in flags.values() for f in v if not f.get('verified')),
    }
    return metrics, outcomes
