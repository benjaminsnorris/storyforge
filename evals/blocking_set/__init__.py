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
       "quotes": ["<verbatim>", ...],     # the slip, then (when the source
                                          # gave one) what it's set against
       "fix_quotes": ["<verbatim>", ...], # optional: other lines the fix changed
       "summary": "...", "fix": "...",
       "found_by": "...",  # provenance; its opening is a FINDERS key
       "kind": "..."}      # storyforge.blocking.KINDS, or '' when the source gave none

  A case may carry only the slip: Wrath's gate report quotes the flagged
  line alone, so its contradictions' other side is in `fix_quotes` when the
  fix touched it, and otherwise nowhere. Every quote must fall at exactly
  one place in its scene (`validate`), so a case has a place to be caught at.

**Categories and the stage sheet (#647).** The sheet's fields map onto the
categories: hands -> hands; posture -> posture; facing/sightline ->
sightline; worn/carried -> worn; position and present -> position (an
arrival order or who is in a place is filed as position: there is no
`present` category); light/place -> light. `other` holds an object's state
or count, physics, and slips no field types (an unclear "he", a cause).

**Matching.** A finding catches a case when one of its quotes falls on the
same words of the scene as one of the case's quotes (or fix quotes): their
places in the normalized prose (`storyforge.quotes.normalize`) overlap. A
quote's place is where it matches as `storyforge.quotes.quote_in` matches
it (whole words, a `...` quote's parts in order), at each place it matches;
a part found inside a longer word, or out of order, is no place. Each
finding catches at most one case and each case is caught once (a maximum
matching, trying the finding's own slip quote, its first, before the line
it set the slip against), so one finding set against a line two cases share
can't score both. A finding is about a place in the scene, and the place is
what the labels give; wording varies between readings. Only verified
findings can catch a case: an unverified finding's quote isn't in the
scene, so it has no place.
"""

from __future__ import annotations

import json
import os
import re
from collections import Counter

from harness import SuiteUnavailable

PRIVATE_ENV = 'STORYFORGE_PRIVATE_EVALS_DIR'
SET_NAME = 'blocking-set'

CATEGORIES = ('hands', 'posture', 'sightline', 'worn', 'position', 'light', 'other')
#: storyforge.blocking.KINDS, or '' (a source that gave none)
KINDS = ('contradiction', 'impossible', 'unclear', '')
SCOPES = ('scene', 'book')
VERDICTS = ('fixed', 'left')
ROLES = ('case', 'clean')
BOOK_ID = re.compile(r'^[a-z0-9-]+$')

#: Who found a case, as the two subsets the plan compares: slips people
#: found (`readers`: the gawain readers and Ben's notes) and slips a
#: blocking read found (`tool`), whose recall is partly the read's
#: run-to-run agreement with itself. A case's `found_by` must open with one
#: of these keys (exactly, then the end or a space), or `validate` names it:
#: a new spelling must not move the independent number silently
FINDERS = {'readers': 'readers', 'author': 'readers', 'storyforge': 'tool'}


class SetMissing(SuiteUnavailable):
    """The private set isn't on this machine; the message says where to put
    it. A `SuiteUnavailable`: the suite is reported unavailable (``stale``,
    with this reason), not errored, on a clone without the private repo."""


def private_dir() -> str:
    return os.environ.get(PRIVATE_ENV) or os.path.expanduser('~/Developer/evals')


def set_dir(root: str | None = None) -> str:
    """The set's directory. Raises `SetMissing` when it, its `cases.json` or
    its `scenes.json` isn't there."""
    path = os.path.join(root or private_dir(), SET_NAME)
    absent = [f for f in ('cases.json', 'scenes.json') if not os.path.isfile(os.path.join(path, f))]
    if absent:
        raise SetMissing(
            f'the blocking set is not at {path} (no {" or ".join(absent)}): it lives in the '
            f'private storyforge-evals repo (benjaminsnorris/storyforge-evals, {SET_NAME}/). '
            f'Clone it to ~/Developer/evals or set {PRIVATE_ENV} to its checkout.')
    return path


def cassettes_dir(suite_name: str, root: str | None = None, run: str = '') -> str:
    """Where the suite's recordings live: beside the set, never in this repo.
    `run` is the harness's run label: '' the main run
    (`cassettes/<suite>/`), ``run2``... the other runs of ``--runs N``
    (`cassettes/run2/<suite>/`), each recorded on its own."""
    return os.path.join(set_dir(root), 'cassettes', *([run] if run else []), suite_name)


def load(path: str) -> tuple[list[dict], list[dict]]:
    """(cases, scenes), each scene with its `text` read in. Raises
    `ValueError` when `cases.json` has no `cases` list or `scenes.json`
    isn't a list: a misspelled key would otherwise read as an empty set."""
    with open(os.path.join(path, 'cases.json'), encoding='utf-8') as f:
        data = json.load(f)
    cases = data.get('cases') if isinstance(data, dict) else None
    if not isinstance(cases, list):
        raise ValueError(f'{path}/cases.json: no "cases" list')
    with open(os.path.join(path, 'scenes.json'), encoding='utf-8') as f:
        scenes = json.load(f)
    if not (isinstance(scenes, list) and all(isinstance(s, dict) for s in scenes)):
        raise ValueError(f'{path}/scenes.json: not a list of scenes')
    for s in scenes:
        file = scene_file(path, s)
        s['text'] = ''
        if os.path.isfile(file):
            with open(file, encoding='utf-8') as f:
                s['text'] = f.read()
    return cases, scenes


def scene_file(path: str, scene: dict) -> str:
    return os.path.join(path, 'scenes', str(scene.get('book')), f'{scene.get("scene")}.md')


def finder(case: dict) -> str | None:
    """The `FINDERS` subset a case's `found_by` opens with, or None."""
    found_by = str(case.get('found_by', ''))
    return next((subset for key, subset in FINDERS.items()
                 if found_by == key or found_by.startswith(key + ' ')), None)


def validate(cases: list[dict], scenes: list[dict]) -> list[str]:
    """The structural problems that would make scoring wrong, without
    quoting the set (a problem names a case or scene id, never its words).
    Empty when sound."""
    from storyforge.quotes import normalize, quote_in
    problems = []
    if not cases:
        problems.append('the set has no cases')
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
    with_cases = {(c.get('book'), c.get('scene')) for c in cases}
    for key, s in by_key.items():
        if s.get('role') == 'case' and key not in with_cases:
            problems.append(f'scene {key[0]}/{key[1]}: role case, but no case is in it')
    for n, c in enumerate(cases, 1):
        if not (isinstance(c.get('id'), str) and c['id']):
            problems.append(f'case {n}: no id')
            continue
        cid = c['id']
        if ids[cid] > 1:
            problems.append(f'{cid}: id used {ids[cid]} times')
        if c.get('kind', '') not in KINDS:
            problems.append(f'{cid}: kind must be one of {KINDS}')
        if finder(c) is None:
            problems.append(f'{cid}: found_by must open with one of {tuple(FINDERS)}')
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
        quotes, fix_quotes = c.get('quotes'), c.get('fix_quotes', [])
        if not (isinstance(quotes, list) and quotes):
            problems.append(f'{cid}: no quotes')
            continue
        if not isinstance(fix_quotes, list):
            problems.append(f'{cid}: fix_quotes must be a list')
            continue
        prose = normalize(scene['text'])
        for n, q in enumerate(quotes + fix_quotes, 1):
            if not (isinstance(q, str) and q.strip() and quote_in(scene['text'], q)):
                problems.append(f'{cid}: quote {n} is not in its scene')
            elif len(places(prose, q)) > 1:
                # a quote at several places would let a finding at any of
                # them catch the case
                problems.append(f'{cid}: quote {n} falls at {len(places(prose, q))} places in '
                                f'its scene; quote enough to name one')
    return problems


# --- matching ---------------------------------------------------------------

def places(prose_normalized: str, quote: str) -> list[list[tuple[int, int]]]:
    """Each place `quote` falls in the normalized prose, matched as
    `storyforge.quotes.quote_in` matches it: whole words, and a `...`
    quote's parts in order. A place is its parts' character ranges."""
    from storyforge.quotes import part_pattern, quote_parts
    parts = quote_parts(quote)
    if not parts:
        return []
    patterns = [part_pattern(p) for p in parts]
    out = []
    for m in patterns[0].finditer(prose_normalized):
        place, pos = [(m.start(), m.end())], m.end()
        for pattern in patterns[1:]:
            nxt = pattern.search(prose_normalized, pos)
            if not nxt:
                break
            place.append((nxt.start(), nxt.end()))
            pos = nxt.end()
        else:
            out.append(place)
    return out


def spans(prose_normalized: str, quote: str) -> list[tuple[int, int]]:
    """The character ranges of every place `quote` falls (`places`)."""
    return [sp for place in places(prose_normalized, quote) for sp in place]


def overlaps(a: list[tuple[int, int]], b: list[tuple[int, int]]) -> bool:
    return any(a0 < b1 and b0 < a1 for a0, a1 in a for b0, b1 in b)


def _preferences(prose_normalized: str, finding: dict, cases: list[dict]) -> list[int]:
    """The cases (indexes into `cases`) a finding lands on, best first: its
    slip quote (the first) on a case's quotes, then on its fix quotes, then
    its other quotes on the case's quotes, then on its fix quotes."""
    quotes = finding.get('quotes') or []
    own = [sp for q in quotes[:1] for sp in spans(prose_normalized, q)]
    rest = [sp for q in quotes[1:] for sp in spans(prose_normalized, q)]
    sides = [([sp for q in c['quotes'] for sp in spans(prose_normalized, q)],
              [sp for q in c.get('fix_quotes') or [] for sp in spans(prose_normalized, q)])
             for c in cases]
    ranked = []
    for mine, side in ((own, 0), (own, 1), (rest, 0), (rest, 1)):
        ranked += [i for i, s in enumerate(sides) if i not in ranked and overlaps(mine, s[side])]
    return ranked


def match(prose_normalized: str, findings: list[dict], cases: list[dict]
          ) -> tuple[dict[int, int], set[int]]:
    """Which finding catches which case in one scene: ({case index: finding
    index}, the findings that land on any case). Each finding catches at
    most one case, each case is caught once, and as many cases as possible
    are caught (a maximum matching, each finding trying its preferred
    cases first). A finding that lands on a case another finding caught
    (the second reading of the same slip) still landed: it isn't
    unlabelled. `findings` are the verified ones."""
    prefs = {f: _preferences(prose_normalized, finding, cases)
             for f, finding in enumerate(findings)}
    caught_by: dict[int, int] = {}

    def assign(f, seen):
        for c in prefs[f]:
            if c in seen:
                continue
            seen.add(c)
            if c not in caught_by or assign(caught_by[c], seen):
                caught_by[c] = f
                return True
        return False

    for f in prefs:
        assign(f, set())
    return caught_by, {f for f, p in prefs.items() if p}


# --- scoring ----------------------------------------------------------------

def _rate(hit: int, of: int) -> float:
    return round(hit / of, 4) if of else 0.0


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
    clean prose; and `left_flagged`, the `left` readings a verified finding
    catches (a count of readings, not of findings: an unverified finding
    has no place, so it can't land on one). A verified finding on a case
    scene that lands on no case is `unlabelled`: a slip no one labelled or
    a false alarm, so it is counted, never scored.

    Each outcome's `findings` holds the index, into that scene's list in
    `flags`, of the finding that caught it (none or one).
    """
    from storyforge.quotes import normalize
    missing = [f'{s["book"]}/{s["scene"]}' for s in scenes if (s['book'], s['scene']) not in flags]
    if missing:
        raise ValueError(f'{len(missing)} scene(s) have no result')
    by_key = {(s['book'], s['scene']): s for s in scenes}
    norm = {k: normalize(s['text']) for k, s in by_key.items()}
    verified = {k: [i for i, f in enumerate(flags[k]) if f.get('verified')] for k in by_key}
    by_scene: dict[tuple[str, str], list[int]] = {}
    for n, c in enumerate(cases):
        by_scene.setdefault((c['book'], c['scene']), []).append(n)
    credited: dict[int, int] = {}  # case index -> index into flags[scene]
    unlabelled = 0
    for key, scene in by_key.items():
        here = by_scene.get(key, [])
        caught_by, landed = match(norm[key], [flags[key][i] for i in verified[key]],
                                  [cases[n] for n in here])
        credited.update({here[c]: verified[key][f] for c, f in caught_by.items()})
        if scene['role'] == 'case':
            unlabelled += len(verified[key]) - len(landed)
    outcomes = [{'id': c['id'], 'caught': n in credited,
                 'findings': [credited[n]] if n in credited else []}
                for n, c in enumerate(cases)]
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
        **{f'recall_found_by_{name}': recall([c for c in in_scene if finder(c) == name])
           for name in ('readers', 'tool') if any(finder(c) == name for c in in_scene)},
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
