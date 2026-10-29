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
dropped silently. Holdout cases are excluded. Families:

- ``redraft-from-brief``: ``cmd_write._build_prompt`` with briefs, the path
  ``storyforge write`` and ``revise``'s ``_redraft_from_briefs`` take.
- ``naturalness-upstream``: ``cmd_revise._fix_upstream_briefs`` then
  ``_redraft_scenes`` on the scene, the path ``revise --naturalness`` takes
  when the diagnosis names upstream causes.
- ``revision-plan``: a named pass from the book's own plan CSV, prompted by
  today's ``revision.build_revision_prompt`` with the config block assembled
  as ``cmd_revise.main``'s pass loop assembles it (reader-annotation guidance
  is omitted: there is no Bookshelf in a replay; the pass is narrowed to the
  case's scene). Prose passes only.

Hone passes are not replayed yet. A pre-pass project that predates
``reference/scenes.csv`` cannot be run by current Storyforge at all, and is
reported as unreplayable rather than migrated.

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

FAMILIES = ('redraft-from-brief', 'naturalness-upstream', 'revision-plan')

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
    if 'naturalness' in name and 'upstream' in name:
        return 'naturalness-upstream'
    if 'redraft' in name or name.startswith('write'):
        return 'redraft-from-brief'
    if not name or 'hone' in name or 'illustrate' in name:
        return ''
    return 'revision-plan'


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
    from storyforge.common import model_for_tier
    response = invoke(judge_prompt(case, scene_text), model_for_tier('opus'),
                      max_tokens=1024, label=f'e8 judge {case["id"]}')
    return parse_verdict(extract_text(response))


def plan_row(project_dir: str, pass_name: str) -> dict:
    """The row for ``pass_name`` in the newest CSV plan under working/plans/
    that has one; raises LookupError when no CSV plan names it."""
    from storyforge.cmd_revise import _read_csv_plan
    plans_dir = os.path.join(project_dir, 'working', 'plans')
    names = sorted(os.listdir(plans_dir)) if os.path.isdir(plans_dir) else []
    def number(n):
        m = re.search(r'(\d+)', n)
        return int(m.group(1)) if m else 0
    for name in sorted((n for n in names if n.endswith('.csv')), key=number, reverse=True):
        for row in _read_csv_plan(os.path.join(plans_dir, name)):
            if row.get('name') == pass_name:
                return row
    raise LookupError(f'no CSV plan in the pre-pass project has a pass named {pass_name!r}')


def _pass_block(row: dict) -> str:
    """Mirror of the config block ``cmd_revise.main`` builds for each pass."""
    block = f"- name: {row.get('name', '')}\n    purpose: {row.get('purpose', '')}\n    scope: {row.get('scope', '')}"
    for key in ('targets', 'guidance', 'protection', 'findings'):
        if row.get(key):
            block += f'\n    {key}: {row[key]}'
    return block


def revision_pass(project_dir: str, scene_id: str, row: dict) -> str:
    """Run one named prose pass the way ``cmd_revise.main`` does; return the
    new prose of ``scene_id``."""
    from storyforge.api import extract_text, invoke, max_output_tokens, REVISION_TIMEOUT
    from storyforge.common import build_shared_context, get_coaching_level, select_revision_model
    from storyforge.parsing import extract_scenes_from_response
    from storyforge.revision import build_revision_prompt

    # Narrowed to the one scene the case is about: a pass that targeted thirty
    # scenes would cost thirty scenes of output per case and can hit the output
    # cap, and what E8 measures is what the pass does to this scene.
    row = {**row, 'scope': 'scene-level', 'targets': scene_id}
    name, purpose, scope = row.get('name', ''), row.get('purpose', ''), row.get('scope', 'full')
    if scope in ('scene-level', 'targeted'):
        scope = row['targets'].replace(';', ',') if row.get('targets') else 'full'
    model = select_revision_model(name, purpose)
    system = build_shared_context(project_dir, model=model)
    prompt = build_revision_prompt(name, purpose, scope, project_dir,
                                   pass_config=_pass_block(row),
                                   coaching_level=get_coaching_level(project_dir),
                                   api_mode=True, system_context=bool(system))
    response = invoke(prompt, model, max_tokens=max_output_tokens(model),
                      label=f'e8 pass {name}', timeout=REVISION_TIMEOUT, system=system or None)
    scenes_dir = os.path.join(project_dir, 'scenes')
    before = _read(os.path.join(scenes_dir, f'{scene_id}.md'))
    extract_scenes_from_response(extract_text(response), scenes_dir)
    after = _read(os.path.join(scenes_dir, f'{scene_id}.md'))
    if after == before:
        raise RuntimeError(f'pass {name!r} returned no revision of {scene_id}')
    return after


def naturalness_upstream(project_dir: str, scene_id: str) -> str:
    """Rewrite the scene's brief and redraft it, as ``revise --naturalness`` does."""
    from storyforge.cmd_revise import _fix_upstream_briefs, _redraft_scenes
    if not _fix_upstream_briefs(project_dir, [scene_id]):
        raise RuntimeError(f'upstream brief fix rewrote nothing for {scene_id}')
    if _redraft_scenes(project_dir, [scene_id]) != 1:
        raise RuntimeError(f'naturalness redraft did not rewrite {scene_id}')
    return _read(os.path.join(project_dir, 'scenes', f'{scene_id}.md'))


def _read(path: str) -> str:
    with open(path, encoding='utf-8') as f:
        return f.read()


def replay(case: dict, project_dir: str, scene_id: str) -> str:
    kind = family(case)
    if kind == 'redraft-from-brief':
        return redraft(project_dir, scene_id)
    if kind == 'naturalness-upstream':
        return naturalness_upstream(project_dir, scene_id)
    if kind == 'revision-plan':
        return revision_pass(project_dir, scene_id, plan_row(project_dir, case['introduced_by']['pass']))
    raise ValueError(f'{case["id"]}: no replayable pass family')


def prepare(case: dict, work_dir: str, root: str | None = None) -> tuple[str, str]:
    """Materialize the pre-pass project for ``case``; return (project_dir, scene_id).
    Raises LookupError when the case cannot be replayed, with the reason.

    Each case gets its own copy, because passes write into the project and a
    second case at the same commit must start from the same state."""
    repo_dir = os.path.join(root or e1.corpus_dir(), case['repo'])
    if not os.path.isdir(os.path.join(repo_dir, '.git')):
        raise RuntimeError(f'{case["repo"]} is not cloned at {repo_dir}')
    parent = _git(repo_dir, 'rev-parse', f'{case["introduced_by"]["commit"]}~1').strip()
    project = materialize(repo_dir, parent, os.path.join(work_dir, case['id']))
    scene_id = target_scene(case, repo_dir)
    if not scene_id:
        raise LookupError('introducing commit changed none of the contradicted scenes')
    if not os.path.isfile(os.path.join(project, 'reference', 'scenes.csv')):
        raise LookupError('pre-pass project predates reference/scenes.csv')
    if family(case) != 'revision-plan' and not os.path.isfile(
            os.path.join(project, 'reference', 'scene-briefs.csv')):
        raise LookupError('pre-pass project has no scene-briefs.csv')
    if family(case) == 'revision-plan':
        row = plan_row(project, case['introduced_by']['pass'])
        if row.get('fix_location') in ('structural', 'registry', 'brief', 'intent'):
            raise LookupError(f'pass {row["name"]!r} is a {row["fix_location"]} pass, not prose')
    return project, scene_id
