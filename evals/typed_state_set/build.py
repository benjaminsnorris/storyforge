"""Build the typed-state set (#744) from a book's repo and the checker
review's classified findings. Free: no model call.

    python3 evals/typed_state_set/build.py --book-repo ~/Developer/iliad-adult

reads the overnight run's branch (`BRANCH`: one commit per drafted scene,
"Draft scene <id>" or "Gate scene <id>", each with the scene's final prose
and that gate run's typed state), and report A of the checker review
(`REPORT`: section 1's runs per scene, section 2's verdict on every
blocking finding), and writes `typed-state-set/` in the private
storyforge-evals checkout (`--out`, default `STORYFORGE_PRIVATE_EVALS_DIR`
or `~/Developer/evals`). See `typed_state_set` for the layout.

A run is the project at the scene commit's parent (what the gate read),
with the scene's prose, stage sheet and typed state from its own commit.
Only the files the checks read are kept (`kept`). A scene whose typed
state isn't of its committed prose (a fix the gate discarded) is left out,
and said, as is every earlier gate run (their replies are in the gitignored
gate logs, not the repo). The build stops on anything it can't place: a
scene in the report with no commit, a label whose round isn't one of its
scene's runs, a run count it has no round names for.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import sys

EVALS = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if EVALS not in sys.path:
    sys.path.insert(0, EVALS)
import harness  # noqa: E402,F401  (puts storyforge on the path)
import typed_state_set as tss  # noqa: E402

BOOK = 'wrath'
REPO_NAME = 'benjaminsnorris/iliad-adult'
BRANCH = 'origin/storyforge/write-20261116-2234'
REPORT = os.path.join('docs', 'plans', '2026-11-26-checker-review', 'A-log-census.md')
#: A scene's gate runs in order, by how many it had (report A's run folders:
#: `.` the first, then `recheck`, `recheck-2`; a scene re-gated twice more
#: after a partial fix adds `partial-1` and `partial-2`)
ROUNDS = {1: ['.'], 2: ['.', 'recheck'], 3: ['.', 'recheck', 'recheck-2'],
          5: ['.', 'recheck', 'partial-1', 'recheck-2', 'partial-2']}
_COMMIT = re.compile(r'^(?:Draft|Gate) scene (\S+)')


def kept(path: str) -> bool:
    """Whether the checks read this project file (`continuity.load_book`,
    `check_continuity`): storyforge.yaml, reference's tables and imported
    sources' character registries, the scenes, their typed state and stage
    sheets."""
    parts = path.split('/')
    if path == 'storyforge.yaml':
        return True
    if parts[0] == 'reference':
        if len(parts) == 2:
            return parts[1].endswith('.csv')
        return (parts[1] == 'source' and parts[-1] == 'characters.csv'
                and len(parts) in (4, 5) and (len(parts) == 4 or parts[3] == 'reference'))
    if parts[0] == 'scenes':
        return len(parts) == 2 and parts[1].endswith('.md')
    if parts[:2] in (['working', 'typed-state'], ['working', 'stage-sheets']):
        return len(parts) == 3 and parts[2].endswith('.json')
    return False


# ============================================================================
# Report A
# ============================================================================

def _rows(text: str, heading: str) -> list[list[str]]:
    """The table rows (cells, stripped) of the section under `heading`, up
    to the next section."""
    start = text.index(heading)
    end = text.find('\n## ', start + len(heading))
    rows = []
    for line in text[start:end if end > 0 else None].splitlines():
        if line.startswith('|') and not re.match(r'^\|[\s|:-]+\|$', line):
            rows.append([c.strip() for c in line.strip().strip('|').split('|')])
    return rows


def runs_per_scene(text: str) -> dict[str, int]:
    """Section 1's per-scene table: scene → how many gate runs it had."""
    out = {}
    for cells in _rows(text, '### Per scene'):
        if len(cells) == 4 and cells[1].isdigit():
            out[cells[0]] = int(cells[1])
    if not out:
        raise ValueError('report A: no per-scene table under "### Per scene"')
    return out


def labels(text: str) -> list[dict]:
    """Section 2's classified findings of the typed-state layers."""
    out = []
    for cells in _rows(text, '### Every blocking finding, classified'):
        if len(cells) != 8 or not re.match(r'^Q\d+$', cells[0]):
            continue
        qid, scene, runs, layer, quote, verdict, reason, _log = cells
        if not layer.startswith('typed:'):
            continue
        out.append({'id': qid, 'scene': scene,
                    'rounds': [r.strip() for r in runs.split(',') if r.strip()],
                    'check': layer.split(':', 1)[1], 'verdict': verdict.strip('*').lower(),
                    'quote': quote, 'reason': reason})
    if not out:
        raise ValueError('report A: no typed-state rows in the classified table')
    return out


# ============================================================================
# The book's repo
# ============================================================================

def _git(repo: str, *args: str) -> bytes:
    return subprocess.run(['git', '-C', repo, *args], capture_output=True, check=True).stdout


def scene_commits(repo: str, branch: str) -> list[tuple[str, str]]:
    """(scene, commit) for each scene commit on `branch`, oldest first; a
    scene committed twice keeps its last."""
    out: dict[str, str] = {}
    for line in reversed(_git(repo, 'log', '--first-parent', '--format=%H %s', branch)
                         .decode().splitlines()):
        sha, _, subject = line.partition(' ')
        m = _COMMIT.match(subject)
        if m:
            out.pop(m.group(1), None)
            out[m.group(1)] = sha
    return list(out.items())


def tree(repo: str, commit: str) -> dict[str, str]:
    """path → git object id, for the files `kept` keeps."""
    out = {}
    for line in _git(repo, 'ls-tree', '-r', '-z', commit).decode().split('\0'):
        if not line:
            continue
        meta, _, path = line.partition('\t')
        if meta.split()[1] == 'blob' and kept(path):
            out[path] = meta.split()[2]
    return out


def build(repo: str, report_text: str, out_root: str, branch: str = BRANCH) -> dict:
    from storyforge import typed_state
    counts = runs_per_scene(report_text)
    labs = labels(report_text)
    commits = dict(scene_commits(repo, branch))
    missing = sorted(set(counts) - set(commits))
    if missing:
        raise ValueError(f'scenes in report A with no commit on {branch}: {", ".join(missing)}')
    unknown = sorted({n for n in counts.values() if n not in ROUNDS})
    if unknown:
        raise ValueError(f'report A has scenes with {unknown} gate runs: no round names for them')
    bad = [lab['id'] for lab in labs
           if lab['scene'] not in counts
           or not set(lab['rounds']) <= set(ROUNDS[counts[lab['scene']]])]
    if bad:
        raise ValueError(f'labels whose rounds aren\'t runs of their scene: {", ".join(bad)}')
    path = os.path.join(out_root, tss.SET_NAME)
    os.makedirs(path, exist_ok=True)
    oids: dict[str, str] = {}   # git object id → sha256 of its bytes

    def digest(oid: str) -> str:
        if oid not in oids:
            oids[oid] = tss.put_blob(path, _git(repo, 'cat-file', 'blob', oid))
        return oids[oid]

    runs, left = [], []
    order = [s for s, _ in scene_commits(repo, branch) if s in counts]
    for scene in order:
        sha = commits[scene]
        rounds = ROUNDS[counts[scene]]
        left += [{'scene': scene, 'round': r, 'why': 'an earlier gate run: its reply is in '
                  'the gate logs and its prose in the session logs, neither in the book\'s repo'}
                 for r in rounds[:-1]]
        files = tree(repo, f'{sha}^')
        own = tree(repo, sha)
        for rel in (f'scenes/{scene}.md', f'working/typed-state/{scene}.json',
                    f'working/stage-sheets/{scene}.writer.json'):
            if rel in own:
                files[rel] = own[rel]
        state = f'working/typed-state/{scene}.json'
        prose = f'scenes/{scene}.md'
        if state not in files or prose not in files:
            left.append({'scene': scene, 'round': rounds[-1],
                         'why': 'its commit has no typed state or no prose'})
            continue
        text = _git(repo, 'cat-file', 'blob', files[prose]).decode('utf-8')
        saved = json.loads(_git(repo, 'cat-file', 'blob', files[state]))
        if saved.get('prose_sha256') != typed_state.prose_hash(text):
            left.append({'scene': scene, 'round': rounds[-1],
                         'why': 'its typed state is not of its committed prose (a later run\'s '
                                'fix was discarded, and the state is that fix\'s)'})
            continue
        runs.append({'id': f'{BOOK}/{scene}/{rounds[-1]}', 'scene': scene, 'round': rounds[-1],
                     'commit': sha, 'files': {p: digest(o) for p, o in sorted(files.items())}})
    head = _git(repo, 'rev-parse', branch).decode().strip()
    data = {'format': tss.FORMAT, 'book': BOOK,
            'built_from': {'repo': REPO_NAME, 'branch': branch, 'head': head,
                           'report': REPORT.replace(os.sep, '/')},
            'runs': runs, 'labels': labs, 'not_replayable': left}
    problems = tss.validate(data)
    if problems:
        raise ValueError(f'the built set has {len(problems)} problem(s), e.g. {problems[0]}')
    with open(os.path.join(path, tss.SET_FILE), 'w', encoding='utf-8', newline='\n') as f:
        json.dump(data, f, indent=1, ensure_ascii=False, sort_keys=True)
        f.write('\n')
    return data


def main(argv=None) -> int:
    p = argparse.ArgumentParser(description=__doc__.split('\n\n')[0])
    p.add_argument('--book-repo', required=True, help='a clone of ' + REPO_NAME)
    p.add_argument('--branch', default=BRANCH)
    p.add_argument('--report', default=os.path.join(harness.REPO_ROOT, REPORT))
    p.add_argument('--out', default=None, help='the storyforge-evals checkout (default '
                   f'${tss.PRIVATE_ENV} or ~/Developer/evals)')
    args = p.parse_args(argv)
    with open(args.report, encoding='utf-8') as f:
        text = f.read()
    data = build(os.path.expanduser(args.book_repo), text, args.out or tss.private_dir(),
                 args.branch)
    in_set = tss.replayable(data)
    print(f'{len(data["runs"])} runs, {len(data["labels"])} labels ({len(in_set)} on a run in '
          f'the set), {len(data["not_replayable"])} gate runs left out')
    return 0


if __name__ == '__main__':
    sys.exit(main())
