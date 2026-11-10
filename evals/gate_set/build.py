"""Build the gate set (#677) from E8's recordings: free, no API call.

    python3 evals/gate_set/build.py [--out DIR]

Reads every recorded E8 judge call (the main cassettes and E6's runs 2 and
3), finds which E1 case each judged by its prompt (``e8.judge_prompt`` around
the scene), and writes each distinct (case, prose) with the judge's verdict
to the private set (`gate_set` doc: layout and roles). Data-family judge calls
(``CSV_JUDGE_PROMPT``) aren't gated, so they're left out. A judge call that
matches no case, whose verdict won't parse, or that judged the same prose as
another call with a different verdict stops the build: each is named by its
recording file and nothing is written. Every other call it skips is
counted in the summary.

Prints counts and recording file names only: the set is private prose.
"""

from __future__ import annotations

import argparse
import glob
import gzip
import json
import os
import sys

EVALS_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if EVALS_DIR not in sys.path:
    sys.path.insert(0, EVALS_DIR)

import harness  # noqa: E402,F401  (puts the storyforge package on the path)
import gate_set  # noqa: E402

FIXTURES = os.path.join(EVALS_DIR, 'fixtures')
#: E8's recordings: the main run, then E6's runs 2 and 3
RECORDINGS = {'cassettes': os.path.join(FIXTURES, 'cassettes', 'e8-revision-safety'),
              'run2': os.path.join(FIXTURES, 'e6', 'run2', 'e8-revision-safety'),
              'run3': os.path.join(FIXTURES, 'e6', 'run3', 'e8-revision-safety')}
_MARK = '\x00SCENE\x00'


def _text(blocks) -> str:
    if isinstance(blocks, str):
        return blocks
    return ''.join(b.get('text', '') for b in blocks or [] if isinstance(b, dict)
                   and b.get('type', 'text') == 'text')


def frames(cases: list[dict]) -> list[tuple[str, str, dict]]:
    """(text before the scene, text after it, case) for each gated case's
    judge prompt, longest prefix first so no case's frame shadows another's."""
    from e8 import family, judge_prompt
    out = []
    for case in cases:
        if family(case) not in gate_set.COMMANDS:
            continue
        before, after = judge_prompt(case, _MARK).split(_MARK)
        out.append((before, after, case))
    return sorted(out, key=lambda f: -len(f[0]))


def read_recordings(dirs: dict[str, str], cases: list[dict]) -> tuple[list[dict], dict]:
    """The judged items, deduplicated by id, and counts of what was skipped."""
    from e8 import parse_verdict
    fr = frames(cases)
    items: dict[str, dict] = {}
    skipped = {'other calls': 0, 'data-family judge calls': 0, 'unmatched': [],
               'unparsed verdict': [], 'conflicting verdicts': [], 'duplicates': 0}
    for label, d in dirs.items():
        for path in sorted(glob.glob(os.path.join(d, '**', '*.json*'), recursive=True)):
            opener = gzip.open if path.endswith('.gz') else open
            with opener(path, 'rt', encoding='utf-8') as f:
                rec = json.load(f)
            body = (rec.get('request') or {}).get('body') or {}
            messages = body.get('messages') or []
            prompt = _text(messages[0].get('content')) if messages else ''
            if prompt.startswith('You are checking what a novel-writing tool wrote'):
                skipped['data-family judge calls'] += 1
                continue
            if not prompt.startswith('You are checking one scene of a novel for one specific'):
                skipped['other calls'] += 1
                continue
            match = next(((b, a, c) for b, a, c in fr
                          if prompt.startswith(b) and prompt.endswith(a)), None)
            name = os.path.relpath(path, FIXTURES)
            if match is None:
                skipped['unmatched'].append(name)
                continue
            before, after, case = match
            prose = prompt[len(before):len(prompt) - len(after)]
            try:
                verdict = parse_verdict(_text((rec.get('response') or {}).get('content')))
            except ValueError:
                skipped['unparsed verdict'].append(name)
                continue
            iid = gate_set.item_id(case['id'], prose)
            if iid in items:
                if items[iid]['verdict'] != verdict['verdict']:
                    skipped['conflicting verdicts'].append(name)
                skipped['duplicates'] += 1
                continue
            from e8 import family
            items[iid] = {'id': iid, 'case': case['id'], 'family': family(case),
                          'code': case.get('code', ''), 'verdict': verdict['verdict'],
                          'evidence': verdict.get('evidence', '') or '', 'recording': label,
                          'prose': prose}
    return sorted(items.values(), key=lambda i: i['id']), skipped


def write_set(out: str, items: list[dict]) -> None:
    os.makedirs(os.path.join(out, 'prose'), exist_ok=True)
    for item in items:
        with open(gate_set.prose_file(out, item['id']), 'w', encoding='utf-8') as f:
            f.write(item['prose'])
    data = {'source': 'E8 judge calls in evals/fixtures (built by evals/gate_set/build.py)',
            'items': [{k: v for k, v in i.items() if k != 'prose'} for i in items]}
    with open(os.path.join(out, 'cases.json'), 'w', encoding='utf-8') as f:
        json.dump(data, f, indent=1, ensure_ascii=False)
        f.write('\n')


def main(argv=None) -> int:
    from e1 import load_cases
    from blocking_set import private_dir
    parser = argparse.ArgumentParser(description=__doc__.split('\n\n')[0])
    parser.add_argument('--out', help='the set directory (default: <private evals>/gate-set)')
    args = parser.parse_args(argv)
    out = args.out or os.path.join(private_dir(), gate_set.SET_NAME)
    items, skipped = read_recordings(RECORDINGS, load_cases())
    stops = ('unmatched', 'unparsed verdict', 'conflicting verdicts')
    if any(skipped[k] for k in stops):
        # an unmatched judge call is a case renamed or a prompt changed since
        # the recording; two verdicts on the same prose are a label nobody
        # can pick between: name them, and build nothing over a partial read
        for key in stops:
            for name in skipped[key][:10]:
                print(f'ERROR: {key}: {name}', file=sys.stderr)
        print('ERROR: ' + ', '.join(f'{len(skipped[k])} {k}' for k in stops)
              + ' judge call(s); nothing written', file=sys.stderr)
        return 1
    if not items:
        print('ERROR: no gated judge call found in E8\'s recordings; nothing written',
              file=sys.stderr)
        return 1
    gate_set.assign_roles(items)
    problems = gate_set.validate(items, {c['id']: c for c in load_cases()})
    if problems:
        for p in problems[:10]:
            print(f'ERROR: {p}', file=sys.stderr)
        return 1
    write_set(out, items)
    roles = {r: sum(1 for i in items if i['role'] == r) for r in gate_set.ROLES}
    verdicts = {}
    for i in items:
        verdicts[i['verdict']] = verdicts.get(i['verdict'], 0) + 1
    print(f'wrote {len(items)} item(s) to {out}: {roles}; verdicts {verdicts}; '
          f'{len({i["case"] for i in items if i["role"] == "positive"})} case(s) with a positive; '
          f'skipped {skipped["data-family judge calls"]} data-family judge call(s), '
          f'{skipped["other calls"]} other call(s) (not judge calls), '
          f'{skipped["duplicates"]} duplicate(s) of the same verdict')
    return 0


if __name__ == '__main__':
    sys.exit(main())
