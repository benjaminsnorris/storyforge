"""E8 — revision safety: does the *current* Storyforge pass reintroduce an
error a past pass wrote?

Built from E1's ``tool-introduced`` cases. For each one, the book repo is
materialized at the parent of the commit that introduced the error — the
exact project state the old pass saw, wrong brief and all — and the current
version of that pass is run on the scene it rewrote. A judge then reads the
new prose against the case's established fact and says whether the error is
back. A pass is safe when it reintroduces nothing.

Only pass families that current Storyforge can re-run in-process are
replayed; every other case is reported as excluded with its reason, never
dropped silently. Family 1 is redraft-from-brief (``cmd_write._build_prompt``
with briefs, the same path ``storyforge write`` and ``revise``'s
``_redraft_from_briefs`` take). Holdout cases are excluded.

Needs the book repos cloned under ``STORYFORGE_CORPUS_DIR`` (see ``evals/e1``).
"""

from __future__ import annotations

import json
import os
import re
import subprocess
import sys
import tarfile
import io
from dataclasses import dataclass, field

import e1

FAMILIES = ('redraft-from-brief',)

JUDGE_PROMPT = """You are checking one scene of a novel for one specific continuity error.

The book had already established this, earlier or elsewhere:
{established}

A past rewrite of this scene contradicted it. The error looked like this:
{error}
(Summary: {summary})

Here is a NEW draft of the same scene:
<scene>
{scene}
</scene>

Does the new draft make the same error — does it assert something that contradicts what was established, in the way described? A draft that simply leaves the fact out does not make the error.

Answer with one JSON object and nothing else:
{{"verdict": "reintroduced" | "consistent" | "not_present", "evidence": "<verbatim sentence from the new draft that decides it, or empty for not_present>"}}

"reintroduced": the new draft contradicts the established fact.
"consistent": the new draft states the fact and agrees with what was established.
"not_present": the new draft does not touch the fact either way."""

VERDICTS = ('reintroduced', 'consistent', 'not_present')


def family(case: dict) -> str:
    name = (case.get('introduced_by') or {}).get('pass', '').lower()
    if 'redraft' in name or name.startswith('write'):
        return 'redraft-from-brief'
    return ''


@dataclass
class Selection:
    cases: list[dict] = field(default_factory=list)
    excluded: dict[str, list[str]] = field(default_factory=dict)  # reason -> ids

    def exclude(self, reason: str, case_id: str) -> None:
        self.excluded.setdefault(reason, []).append(case_id)


def select(cases: list[dict], holdout: list[str]) -> Selection:
    held = set(holdout)
    sel = Selection()
    for case in cases:
        if 'tool-introduced' not in case.get('subsets', []):
            continue
        if case['id'] in held:
            sel.exclude('holdout', case['id'])
        elif case.get('level') != 'prose':
            sel.exclude('csv-level (no prose to redraft)', case['id'])
        elif not family(case):
            sel.exclude(f"pass not replayable yet: {case['introduced_by'].get('pass', '?')}",
                        case['id'])
        elif not case['introduced_by'].get('commit'):
            sel.exclude('no introducing commit recorded', case['id'])
        else:
            sel.cases.append(case)
    return sel


def _git(repo_dir: str, *args: str) -> str:
    out = subprocess.run(['git', '-C', repo_dir, *args], capture_output=True, text=True)
    if out.returncode != 0:
        raise RuntimeError(f'git {" ".join(args)} failed in {repo_dir}: {out.stderr.strip()}')
    return out.stdout


def materialize(repo_dir: str, commit: str, dest: str) -> str:
    """Write the tree at ``commit`` to ``dest`` (once) and return ``dest``."""
    if os.path.isdir(dest):
        return dest
    archive = subprocess.run(['git', '-C', repo_dir, 'archive', commit], capture_output=True)
    if archive.returncode != 0:
        raise RuntimeError(f'git archive {commit} failed in {repo_dir}: '
                           f'{archive.stderr.decode(errors="replace").strip()}')
    os.makedirs(dest)
    with tarfile.open(fileobj=io.BytesIO(archive.stdout)) as tar:
        try:
            tar.extractall(dest, filter='data')
        except TypeError:  # Python before 3.10.12 / 3.11.4 has no extraction filters
            tar.extractall(dest)
    return dest


def target_scene(case: dict, repo_dir: str) -> str:
    """The scene the introducing pass rewrote that carries the error, as an id
    in the pre-pass project; '' when it cannot be determined."""
    commit = case['introduced_by']['commit']
    changed = {os.path.splitext(os.path.basename(p))[0]
               for p in _git(repo_dir, 'show', '--name-only', '--format=', commit).split()
               if p.startswith('scenes/') and p.endswith('.md')}
    for span in case['contradicted']:
        if span.get('source', 'prose') != 'prose':
            continue
        for candidate in (span['scene'], os.path.splitext(os.path.basename(span['path']))[0]):
            if candidate in changed:
                return candidate
    return ''


def _quotes(spans: list[dict]) -> str:
    return '\n'.join(f'- ({s["scene"]}) "{s["quote"]}"' for s in spans)


def judge_prompt(case: dict, scene_text: str) -> str:
    established = _quotes(case['established']) or case.get('established_by_absence', '')
    return JUDGE_PROMPT.format(established=established, error=_quotes(case['contradicted']),
                               summary=case['summary'], scene=scene_text)


def parse_verdict(text: str) -> dict:
    """The judge's JSON verdict. Raises ValueError rather than guessing: an
    unreadable verdict must make the suite error, never count as safe."""
    match = re.search(r'\{.*\}', text, re.DOTALL)
    if not match:
        raise ValueError(f'judge returned no JSON object: {text[:200]!r}')
    verdict = json.loads(match.group(0))
    if verdict.get('verdict') not in VERDICTS:
        raise ValueError(f'judge verdict {verdict.get("verdict")!r} is not one of {VERDICTS}')
    return verdict


def redraft(project_dir: str, scene_id: str) -> str:
    """Run the current redraft-from-brief pass on one scene; return the new prose."""
    from storyforge.api import extract_text, invoke
    from storyforge.cmd_write import _build_prompt
    from storyforge.common import build_shared_context, select_model
    from storyforge.parsing import clean_scene_content, extract_single_scene

    model = select_model('creative')
    system = build_shared_context(project_dir, model=model)
    prompt = _build_prompt(scene_id, project_dir, 'full', use_briefs=True,
                           system_context=bool(system))
    if not prompt:
        raise RuntimeError(f'could not build a redraft prompt for {scene_id}')
    response = invoke(prompt, model, max_tokens=16384, label=f'e8 redraft {scene_id}',
                      system=system or None)
    text = extract_text(response)
    if not text:
        raise RuntimeError(f'empty redraft for {scene_id}')
    return clean_scene_content(extract_single_scene(text) or text)


def judge(case: dict, scene_text: str) -> dict:
    from storyforge.api import extract_text, invoke
    from storyforge.common import LATEST_MODELS
    response = invoke(judge_prompt(case, scene_text), LATEST_MODELS['opus'],
                      max_tokens=1024, label=f'e8 judge {case["id"]}')
    return parse_verdict(extract_text(response))


def prepare(case: dict, work_dir: str, root: str | None = None) -> tuple[str, str]:
    """Materialize the pre-pass project for ``case``; return (project_dir, scene_id).
    Raises when the case cannot be replayed, with the reason."""
    repo_dir = os.path.join(root or e1.corpus_dir(), case['repo'])
    if not os.path.isdir(os.path.join(repo_dir, '.git')):
        raise RuntimeError(f'{case["repo"]} is not cloned at {repo_dir}')
    parent = _git(repo_dir, 'rev-parse', f'{case["introduced_by"]["commit"]}~1').strip()
    project = materialize(repo_dir, parent, os.path.join(work_dir, f'{case["repo"]}-{parent[:12]}'))
    scene_id = target_scene(case, repo_dir)
    if not scene_id:
        raise LookupError('introducing commit changed none of the contradicted scenes')
    if not os.path.isfile(os.path.join(project, 'reference', 'scene-briefs.csv')):
        raise LookupError('pre-pass project has no scene-briefs.csv')
    return project, scene_id
