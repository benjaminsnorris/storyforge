"""E1 — the real-failures corpus: labeled continuity errors mined from the
author's book repos. Format, validation, quote verification, and holdout.

One file per repo, ``evals/fixtures/e1/cases/<repo>.json``::

    {"repo": "shared-dark", "cases": [<case>, ...]}

A case (see ``evals/e1/FORMAT.md`` for the labeling guide)::

    {
      "id": "shared-dark-001",
      "repo": "shared-dark",
      "level": "prose",                    # prose | csv
      "code": "TIM",                       # primary code from harness.ERROR_CODES
      "secondary_codes": [],
      "summary": "Bend to Portland is three hours in one scene, five in another.",
      "established": [<span>, ...],        # empty only with established_by_absence
      "established_by_absence": "",        # KNO cases: why the earlier scenes establish a gap
      "contradicted": [<span>, ...],       # at least one
      "fix": {"status": "fixed", "commit": "<sha>", "after": [<span>, ...],
              "rewrite": false},             # true: the error left in a wholesale rewrite, no targeted edit
      "related_cases": [],                 # e.g. the regression case of this error, and back
      "introduced_by": {"kind": "plan", "pass": "", "commit": ""},
      "regressed_by": [],                  # commits that later reintroduced the error
      "subsets": ["author-labeled"],
      "label_source": "working/annotations.json: <annotation id or quote>",
      "confidence": "high",
      "notes": ""
    }

A span is ``{"scene": <slug at HEAD>, "path": <path at commit>, "commit": <sha>,
"quote": <verbatim prose>}``. ``commit`` is the tree the quote was read from:
for ``established`` and ``contradicted`` that is the fix's parent, for
``fix.after`` the fix itself. ``scene`` is the HEAD slug even when ``path`` is a
pre-rename numeric file, so cases join across id eras.
"""

from __future__ import annotations

import hashlib
import json
import math
import os
import re
import subprocess
from collections import Counter

EVALS_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
FIXTURES_DIR = os.path.join(EVALS_DIR, 'fixtures', 'e1')
CASES_DIR = os.path.join(FIXTURES_DIR, 'cases')
HOLDOUT_FILE = os.path.join(FIXTURES_DIR, 'holdout.json')
HOLDOUT_FRACTION = 0.2

ERROR_CODES = ('PHY', 'TIM', 'KNO', 'REL', 'TRT', 'WLD', 'PRM', 'VOI')
LEVELS = ('prose', 'csv')
FIX_STATUSES = ('fixed', 'incomplete', 'unfixed')
INTRODUCED_KINDS = ('draft', 'author', 'plan', 'tool', 'unknown')
SUBSETS = ('author-labeled', 'tool-introduced', 'unfixed-at-head')
CONFIDENCES = ('high', 'medium', 'low')
_SHA = re.compile(r'^[0-9a-f]{7,40}$')
_ID = re.compile(r'^[a-z0-9-]+-\d{3}$')


def corpus_dir() -> str:
    """Where the book repos are cloned (``STORYFORGE_CORPUS_DIR``, default ``~/Developer``)."""
    return os.environ.get('STORYFORGE_CORPUS_DIR', os.path.expanduser('~/Developer'))


def load_cases(cases_dir: str = CASES_DIR) -> list[dict]:
    cases = []
    if not os.path.isdir(cases_dir):
        return cases
    for filename in sorted(os.listdir(cases_dir)):
        if not filename.endswith('.json'):
            continue
        with open(os.path.join(cases_dir, filename)) as f:
            data = json.load(f)
        repo = filename[:-5]
        if data.get('repo') != repo:
            raise ValueError(f'{filename}: "repo" is {data.get("repo")!r}, expected {repo!r}')
        cases.extend(data.get('cases', []))
    return cases


def _span_problems(where: str, span, require_quote: bool = True) -> list[str]:
    if not isinstance(span, dict):
        return [f'{where}: not an object']
    problems = []
    for key in ('scene', 'path', 'commit'):
        if not isinstance(span.get(key), str) or not span.get(key):
            problems.append(f'{where}: missing {key}')
    if span.get('commit') and not _SHA.match(span['commit']):
        problems.append(f'{where}: commit {span["commit"]!r} is not a sha')
    if require_quote and not (isinstance(span.get('quote'), str) and span['quote'].strip()):
        problems.append(f'{where}: missing quote')
    return problems


def validate_case(case: dict) -> list[str]:
    """Every way ``case`` departs from the format; empty when it is valid."""
    cid = case.get('id', '<no id>')
    p = []

    def bad(msg):
        p.append(f'{cid}: {msg}')

    if not isinstance(case.get('id'), str) or not _ID.match(case['id']):
        bad('id must look like <repo>-NNN')
    elif not case['id'].startswith(f"{case.get('repo')}-"):
        bad('id must start with the repo name')
    if case.get('level') not in LEVELS:
        bad(f'level must be one of {LEVELS}')
    if case.get('code') not in ERROR_CODES:
        bad(f'code must be one of {ERROR_CODES}')
    secondary = case.get('secondary_codes', [])
    if not isinstance(secondary, list) or set(secondary) - set(ERROR_CODES):
        bad('secondary_codes must be a list of error codes')
    if not (isinstance(case.get('summary'), str) and case['summary'].strip()):
        bad('missing summary')

    established = case.get('established', [])
    absence = case.get('established_by_absence', '')
    if not isinstance(established, list):
        bad('established must be a list')
        established = []
    if not established and not (isinstance(absence, str) and absence.strip()):
        bad('established is empty and established_by_absence does not explain why')
    for i, span in enumerate(established):
        p.extend(f'{cid}: {m}' for m in _span_problems(f'established[{i}]', span))

    contradicted = case.get('contradicted', [])
    if not isinstance(contradicted, list) or not contradicted:
        bad('contradicted needs at least one span')
        contradicted = []
    for i, span in enumerate(contradicted):
        p.extend(f'{cid}: {m}' for m in _span_problems(f'contradicted[{i}]', span))

    fix = case.get('fix')
    if not isinstance(fix, dict) or fix.get('status') not in FIX_STATUSES:
        bad(f'fix.status must be one of {FIX_STATUSES}')
        fix = {}
    if fix.get('status') in ('fixed', 'incomplete'):
        if not (isinstance(fix.get('commit'), str) and _SHA.match(fix['commit'])):
            bad('a fixed or incomplete case needs fix.commit')
        for i, span in enumerate(fix.get('after', [])):
            p.extend(f'{cid}: {m}' for m in _span_problems(f'fix.after[{i}]', span))
        if not fix.get('after') and not fix.get('rewrite'):
            bad('a fix with no fix.after spans must set fix.rewrite (the error left in a rewrite)')
    if 'rewrite' in fix and not isinstance(fix['rewrite'], bool):
        bad('fix.rewrite must be true or false')
    related = case.get('related_cases', [])
    if not isinstance(related, list) or not all(isinstance(r, str) for r in related):
        bad('related_cases must be a list of case ids')

    introduced = case.get('introduced_by')
    if not isinstance(introduced, dict) or introduced.get('kind') not in INTRODUCED_KINDS:
        bad(f'introduced_by.kind must be one of {INTRODUCED_KINDS}')
        introduced = {}
    if introduced.get('kind') == 'tool' and not introduced.get('pass'):
        bad('a tool-introduced error must name the pass in introduced_by.pass')

    regressed = case.get('regressed_by', [])
    if not isinstance(regressed, list) or not all(
            isinstance(c, str) and _SHA.match(c) for c in regressed):
        bad('regressed_by must be a list of commit shas')

    subsets = case.get('subsets', [])
    if not isinstance(subsets, list) or set(subsets) - set(SUBSETS):
        bad(f'subsets must be drawn from {SUBSETS}')
        subsets = []
    if 'author-labeled' in subsets and not case.get('label_source'):
        bad('author-labeled needs label_source')
    if ('tool-introduced' in subsets) != (introduced.get('kind') == 'tool'):
        bad('tool-introduced subset and introduced_by.kind == "tool" must agree')
    if ('unfixed-at-head' in subsets) != (fix.get('status') == 'unfixed'):
        bad('unfixed-at-head subset and fix.status == "unfixed" must agree')
    if case.get('confidence') not in CONFIDENCES:
        bad(f'confidence must be one of {CONFIDENCES}')
    return p


def validate_corpus(cases: list[dict]) -> list[str]:
    problems = []
    for case in cases:
        problems.extend(validate_case(case))
    counts = Counter(c.get('id') for c in cases)
    problems.extend(f'{cid}: duplicate id' for cid, n in counts.items() if n > 1)
    for case in cases:
        for other in case.get('related_cases', []) if isinstance(case.get('related_cases'), list) else []:
            if other not in counts:
                problems.append(f'{case.get("id")}: related case {other!r} does not exist')
    return problems


def _normalize(text: str) -> str:
    text = text.replace('’', "'").replace('‘', "'")
    text = text.replace('“', '"').replace('”', '"')
    return ' '.join(text.split())


def _show(repo_dir: str, commit: str, path: str, cache: dict) -> str | None:
    key = (commit, path)
    if key not in cache:
        out = subprocess.run(['git', '-C', repo_dir, 'show', f'{commit}:{path}'],
                             capture_output=True)
        cache[key] = (out.stdout.decode('utf-8', errors='replace')
                      if out.returncode == 0 else None)
    return cache[key]


def verify_quotes(cases: list[dict], root: str | None = None) -> list[str]:
    """Check every quote appears verbatim (modulo whitespace and curly quotes)
    in its file at its commit. A repo that is not cloned is reported, not skipped."""
    root = root or corpus_dir()
    problems, caches = [], {}
    for case in cases:
        repo_dir = os.path.join(root, case.get('repo', ''))
        if not os.path.isdir(os.path.join(repo_dir, '.git')):
            problems.append(f'{case.get("id")}: repo not cloned at {repo_dir}')
            continue
        cache = caches.setdefault(repo_dir, {})
        spans = [('established', s) for s in case.get('established', [])]
        spans += [('contradicted', s) for s in case.get('contradicted', [])]
        spans += [('fix.after', s) for s in (case.get('fix') or {}).get('after', [])]
        for sha in case.get('regressed_by', []) + [(case.get('fix') or {}).get('commit') or '']:
            if sha and subprocess.run(['git', '-C', repo_dir, 'cat-file', '-e', f'{sha}^{{commit}}'],
                                      capture_output=True).returncode != 0:
                problems.append(f'{case["id"]}: commit {sha} does not exist in {case["repo"]}')
        for where, span in spans:
            text = _show(repo_dir, span.get('commit', ''), span.get('path', ''), cache)
            if text is None:
                problems.append(f'{case["id"]}: {where} {span.get("commit")}:{span.get("path")} '
                                f'does not exist')
            elif _normalize(span.get('quote', '')) not in _normalize(text):
                problems.append(f'{case["id"]}: {where} quote not found in '
                                f'{span.get("commit")}:{span.get("path")}: '
                                f'{span.get("quote", "")[:80]!r}')
    return problems


def _rank(case_id: str) -> str:
    return hashlib.sha256(case_id.encode()).hexdigest()


def assign_holdout(cases: list[dict], existing: list[str],
                   fraction: float = HOLDOUT_FRACTION) -> list[str]:
    """Extend the holdout to ``fraction`` of each repo's cases.

    Membership is frozen once assigned — moving a case out of the holdout
    after anyone has looked at it would leak it — so new cases only top each
    repo up, picked in hash order (stable, and independent of labeling order).
    Ids no longer in the corpus are dropped.
    """
    ids = {c['id'] for c in cases}
    holdout = [i for i in existing if i in ids]
    by_repo: dict[str, list[str]] = {}
    for case in cases:
        by_repo.setdefault(case['repo'], []).append(case['id'])
    for repo_ids in by_repo.values():
        target = math.ceil(fraction * len(repo_ids))
        have = sum(1 for i in repo_ids if i in holdout)
        candidates = sorted((i for i in repo_ids if i not in holdout), key=_rank)
        holdout.extend(candidates[:max(0, target - have)])
    return sorted(holdout)


def load_holdout(path: str = HOLDOUT_FILE) -> list[str]:
    if not os.path.isfile(path):
        return []
    with open(path) as f:
        return json.load(f)['ids']


def stats(cases: list[dict], holdout: list[str]) -> dict:
    prose = [c for c in cases if c.get('level') == 'prose']
    held = set(holdout)
    return {
        'cases': len(cases),
        'prose_cases': len(prose),
        'by_code': dict(sorted(Counter(c.get('code') for c in prose).items())),
        'by_repo': dict(sorted(Counter(c.get('repo') for c in cases).items())),
        'by_subset': {s: sum(1 for c in prose if s in c.get('subsets', [])) for s in SUBSETS},
        'by_confidence': dict(sorted(Counter(c.get('confidence') for c in prose).items())),
        'holdout': len(held & {c['id'] for c in cases}),
    }
