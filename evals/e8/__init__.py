"""E8's replay helpers: a corpus book at the commit before a past pass, and
the gate the way revise and write run it.

E8 (revision safety: does today's pass reintroduce an error a past pass
wrote?) was retired as a suite on 2026-11-27 (#788): it redrafted prose to
measure the gate end to end, about $55 a run, and its labelled prose is
already frozen in the gate set (`evals/gate_set`), built from E8's
recordings (`fixtures/cassettes/e8-revision-safety`, kept as that source).
What is left here serves the gate set, E2 and E5:

- `materialize`, `prepare`: a book repo (under ``STORYFORGE_CORPUS_DIR``,
  see ``evals/e1``) at the parent of the commit that introduced an E1
  ``tool-introduced`` case's error, the exact project the old pass saw, its
  scene renamed through E1's id-maps and a pre-``scenes.csv`` project
  migrated by a port of the removed migrate script
  (`migrate_scene_metadata`, an approximation).
- `redraft`: ``cmd_write``'s redraft from briefs, then the gate
  (`gate_as_revise`), as ``write --force`` and revise run it.
- `family`, `judge_prompt`, `parse_verdict`, `VERDICTS`, `EXCLUDED_CASES`:
  how E8 classed and judged a case, which the gate set's build reads back
  from E8's recorded judge calls.
"""

from __future__ import annotations

import json
import os
import re
import subprocess
import tarfile
import io

import e1
from harness import migrate_tree

# families whose pass writes data, judged on what it wrote (see written())
DATA_FAMILIES = ('brief-fix', 'hone-physical-states', 'illustrate-state', 'illustrate-prompts')
FAMILIES = ('redraft-from-brief', 'naturalness-upstream', 'revision-plan', *DATA_FAMILIES)

ID_MAPS_DIR = os.path.join(e1.FIXTURES_DIR, 'id-maps')

# Cases whose error a replay of the introducing pass cannot show, with why.
# Reported as unreplayable like every other exclusion.
EXCLUDED_CASES = {
    'lantern-folk-032': ('the --state pass logged the pre-pass prose faithfully ("Two relit. Two '
                         'still dark."); the error is the log going stale after a later prose '
                         'fix (37bc78e), which a replay of the pass cannot show'),
    'thornwall-028': ('the introducing commit wrote both sides (the six years and the nine), so '
                      'the pre-pass project has no established fact for the replay to contradict'),
    # #614's audit (2026-11-07): the pre-pass book already carries the
    # case's error elsewhere, so a replay that writes it agrees with the
    # book it runs on and the gate is right to pass it. Re-check these if a
    # case's introducing commit or the corpus is relabelled.
    'governor-016': ('the pre-pass book already has the stone-cutters on Block Fourteen: '
                     'terrace-row ("The stone-cutters on Block Fourteen had stopped for their '
                     'afternoon break"), the continuity tracker, and the scene\'s own brief'),
    'thornwall-026': ('the pre-pass book already has the cooperative Greenhollow Warden: '
                      'thessan-at-verath ("his signature on the transfer papers steady") and '
                      'thessan-rides ("had signed every form") say what the replay is judged '
                      'for writing'),
    'thornwall-030': ('the pre-pass ivra-seals-archive already says "declining allotments over '
                      'nine years"; the introducing commit (48a7d28) only changed a colon to a '
                      'period, so the error predates the pass'),
}

# storyforge-migrate-elaborate's scenes.csv columns
MIGRATED_SCENE_COLUMNS = ['id', 'seq', 'title', 'part', 'pov', 'location', 'timeline_day',
                          'time_of_day', 'duration', 'status', 'word_count', 'target_words']

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

CSV_JUDGE_PROMPT = """You are checking what a novel-writing tool wrote into a book's project data (a scene brief, a registry row, an illustration log or prompt) for one specific continuity error.

The book had already established this, earlier or elsewhere:
{established}

A past run of the same tool wrote data that contradicted it. The error looked like this (quoted from that data, or from prose later drafted from it):
{error}
(Summary: {summary})

Here is what a NEW run of the tool wrote (the rows or files it added or changed):
<written>
{written}
</written>

Does the new output make the same error — does it assert something that contradicts what was established, in the way described? Output that simply leaves the fact out does not make the error.

Answer with one JSON object and nothing else:
{{"verdict": "reintroduced" | "consistent" | "not_present", "evidence": "<verbatim line from the new output that decides it, or empty for not_present>"}}

"reintroduced": the new output contradicts the established fact.
"consistent": the new output states the fact and agrees with what was established.
"not_present": the new output does not touch the fact either way."""

VERDICTS = ('reintroduced', 'consistent', 'not_present')


def family(case: dict) -> str:
    name = (case.get('introduced_by') or {}).get('pass', '').lower()
    if 'naturalness' in name and 'upstream' in name:
        return 'naturalness-upstream'
    if 'upstream' in name and 'brief' in name:
        return 'brief-fix'
    if 'hone' in name:
        return 'hone-physical-states' if 'physical' in name else ''
    if 'illustrate' in name:
        return {'--state': 'illustrate-state', '--prompts': 'illustrate-prompts'}.get(
            name.split()[-1], '')
    if 'redraft' in name or name.startswith('write'):
        return 'redraft-from-brief'
    if not name:
        return ''
    return 'revision-plan'


def _git(repo_dir: str, *args: str) -> str:
    out = subprocess.run(['git', '-C', repo_dir, *args], capture_output=True, text=True)
    if out.returncode != 0:
        raise RuntimeError(f'git {" ".join(args)} failed in {repo_dir}: {out.stderr.strip()}')
    return out.stdout


def materialize(repo_dir: str, commit: str, dest: str) -> str:
    """Write the tree at ``commit`` to ``dest`` (once) and return ``dest``,
    its registries moved into the ledger (``harness.migrate_tree``)."""
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
    migrate_tree(dest, f'{os.path.basename(repo_dir)}@{commit[:12]}')
    return dest


def old_ids(repo: str, slug: str) -> list[str]:
    """The pre-rename scene ids E1's id-map records for ``slug``
    (``scenes/s09-garrens-watch.md|garrens-ledger|...`` -> ``s09-garrens-watch``)."""
    path = os.path.join(ID_MAPS_DIR, f'{repo}.csv')
    if not os.path.isfile(path):
        return []
    with open(path, encoding='utf-8') as f:
        rows = [line.rstrip('\n').split('|') for line in f.readlines()[1:] if line.strip()]
    return [os.path.splitext(os.path.basename(r[0]))[0] for r in rows if len(r) > 1 and r[1] == slug]


def _changed_scenes(repo_dir: str, commit: str) -> set[str]:
    return {os.path.splitext(os.path.basename(p))[0]
            for p in _git(repo_dir, 'show', '--name-only', '--format=', commit).split()
            if p.startswith('scenes/') and p.endswith('.md')}


def _span_ids(case: dict, span: dict) -> list[str]:
    """Every id the span's scene may have had: its slug, its path's stem, and
    the old ids E1's id-map gives the slug (scenes renamed after the commit)."""
    return [span['scene'], os.path.splitext(os.path.basename(span['path']))[0],
            *old_ids(case['repo'], span['scene'])]


def target_scene(case: dict, repo_dir: str) -> str:
    """The scene the introducing pass rewrote that carries the error, as an id
    in the pre-pass project; '' when it cannot be determined."""
    changed = _changed_scenes(repo_dir, case['introduced_by']['commit'])
    for span in case['contradicted']:
        if span.get('source', 'prose') != 'prose':
            continue
        for candidate in _span_ids(case, span):
            if candidate in changed:
                return candidate
    return ''


def _untouched_reason(case: dict, repo_dir: str) -> str:
    """Why the introducing commit changed none of the contradicted scenes."""
    changed = _changed_scenes(repo_dir, case['introduced_by']['commit'])
    wrote = sorted({s['scene'] for s in case['established']
                    if any(i in changed for i in _span_ids(case, s))})
    if wrote:
        # e.g. a pass that planted a promise (established) whose payoff
        # (contradicted) it never wrote: replaying it cannot show the error
        return (f'introducing commit wrote only the established side ({", ".join(wrote)}), '
                'not a contradicted scene')
    return 'introducing commit changed none of the contradicted scenes'


def migrate_scene_metadata(project_dir: str) -> bool:
    """Convert a pre-April-2026 ``reference/scene-metadata.csv`` into
    ``reference/scenes.csv`` in the materialized copy (never the book repo).

    A port of the scenes.csv step of Storyforge's own ``storyforge-migrate-
    elaborate`` (removed in e22a58c4): the same columns are copied, and a
    status other than drafted, revised, consolidated or polished is
    recomputed the same way. It is an approximation of the books' history:
    governor, shared-dark and thornwall got ``scenes.csv`` from ``extract``'s
    skeleton phase after the script was removed. ``scene-intent.csv`` is left as it is, and no
    ``scene-briefs.csv`` is created: those projects had no briefs, so a pass
    that needs them is reported as unreplayable rather than run on empty ones.
    Returns False when there is no ``scene-metadata.csv`` to convert."""
    import csv
    ref_dir = os.path.join(project_dir, 'reference')
    old_path = os.path.join(ref_dir, 'scene-metadata.csv')
    if not os.path.isfile(old_path):
        return False
    with open(old_path, newline='', encoding='utf-8') as f:
        old_rows = list(csv.DictReader(f, delimiter='|'))
    new_rows = []
    for row in old_rows:
        new_row = {c: row.get(c) or '' for c in MIGRATED_SCENE_COLUMNS}
        if new_row['status'] not in ('drafted', 'revised', 'consolidated', 'polished'):
            new_row['status'] = 'drafted' if new_row['word_count'] not in ('0', '') else 'mapped'
        new_rows.append(new_row)
    with open(os.path.join(ref_dir, 'scenes.csv'), 'w', newline='', encoding='utf-8') as f:
        writer = csv.DictWriter(f, fieldnames=MIGRATED_SCENE_COLUMNS, delimiter='|',
                                lineterminator='\n')
        writer.writeheader()
        writer.writerows(new_rows)
    return True


def _quotes(spans: list[dict]) -> str:
    return '\n'.join(f'- ({s["scene"]}) "{s["quote"]}"' for s in spans)


def judge_prompt(case: dict, scene_text: str) -> str:
    established = _quotes(case['established']) or case.get('established_by_absence', '')
    if family(case) in DATA_FAMILIES:
        return CSV_JUDGE_PROMPT.format(established=established, error=_quotes(case['contradicted']),
                                       summary=case['summary'], written=scene_text)
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


def redraft(project_dir: str, scene_id: str, gated: bool = True, rewrite: bool = True) -> str:
    """Run the current redraft-from-brief pass on one scene; return the new
    prose. With `gated` (E8), as write and revise run it: through the gate.
    The re-check of later scenes that follows a pass in write and revise
    (Phase 4) only reports, never changes this scene, so E8 doesn't run it.
    Without (E5, which measures what the redraft itself changes), the draft
    alone. With `rewrite` (write and revise), the scene's current prose is
    its voice reference; without, it drafts from the plan and ledger alone
    (E5's ledger-gap measure)."""
    from storyforge.api import RefusalError, extract_text, invoke
    from storyforge.cmd_write import _build_prompt
    from storyforge.common import build_shared_context, select_model
    from storyforge.parsing import clean_scene_content, extract_single_scene

    from storyforge import gate
    model = select_model('creative')
    system = build_shared_context(project_dir, model=model)
    prompt = _build_prompt(scene_id, project_dir, 'full', use_briefs=True,
                           system_context=bool(system), rewrite=rewrite)
    if not prompt:
        raise RuntimeError(f'could not build a redraft prompt for {scene_id}')
    from storyforge.prompts import prior_prose_blocks, prior_prose_mode
    if system:  # the earlier prose write and revise send with it
        system = list(system) + prior_prose_blocks(scene_id, project_dir,
                                                   prior_prose_mode(project_dir))
    try:
        response = invoke(prompt, model, max_tokens=16384, label=f'e8 redraft {scene_id}',
                          system=system or None)
    except RefusalError as e:  # what write/revise do when the fallback also refuses
        raise PassHalted(f'redraft of {scene_id} refused: {e}') from e
    text = extract_text(response)
    if not text:
        raise RuntimeError(f'empty redraft for {scene_id}')
    prose = clean_scene_content(extract_single_scene(text) or text)
    if not gated:
        return prose
    before = gate.snapshot(project_dir)   # as revise takes it, before the prose is written
    with open(os.path.join(project_dir, 'scenes', f'{scene_id}.md'), 'w',
              encoding='utf-8') as f:
        f.write(prose)
    return gate_as_revise(project_dir, scene_id, 'redraft', prose, before=before)


#: Where `gate_as_revise` leaves what the gate's last run found, by kind
#: (`gate_counts`), for the suite
def gate_as_revise(project_dir: str, scene_id: str, command: str, prose: str,
                   before=None) -> str:
    """Gate `prose` as write and revise do (`gate.gate_and_fix`: fix and re-check up to
    ``gate.FIX_ROUNDS`` times) and return the prose they keep, passed or not. A scene the
    gate didn't pass, or couldn't finish, is listed in
    working/gate-pending.csv as they list it. `before` is the book before the pass (`gate.snapshot`), as revise
    passes it. Only
    `GateError` is caught: a bug errors the suite rather than being judged
    as gated prose, and a cassette miss errors it anyway."""
    from storyforge import gate
    try:
        out = gate.gate_and_fix(project_dir, scene_id, command=command, prose=prose,
                                log_dir=os.path.join(project_dir, 'working', 'logs', 'gate'),
                                before=before)
    except gate.GateError as e:
        gate.mark_pending(project_dir, scene_id, command, f'the gate could not finish: {e}')
        return prose
    if not out.result.passed:
        gate.mark_pending(project_dir, scene_id, command, 'the gate did not pass it')
    return out.prose


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


class PassHalted(Exception):
    """The current pass refused to write the scene (a cut-off reply, or the
    model refused the request) and halted. Nothing was written, so nothing can be reintroduced; counted as
    ``halted``, separately from the replayed cases."""


def _read(path: str) -> str:
    with open(path, encoding='utf-8') as f:
        return f.read()


class _cassette_key:
    """Under a cassette, give commands that check ``ANTHROPIC_API_KEY``
    themselves (``illustrate``) a placeholder, as ``api`` needs none to
    replay; without it a keyless replay would exit 1 and look like a halt."""

    def __enter__(self):
        self.added = bool(os.environ.get('STORYFORGE_CASSETTE')) and not os.environ.get('ANTHROPIC_API_KEY')
        if self.added:
            os.environ['ANTHROPIC_API_KEY'] = 'cassette-replay'

    def __exit__(self, *exc):
        if self.added:
            del os.environ['ANTHROPIC_API_KEY']


def _brief_ids(project_dir: str) -> set[str]:
    path = os.path.join(project_dir, 'reference', 'scene-briefs.csv')
    with open(path, encoding='utf-8') as f:
        return {line.split('|')[0] for line in f.read().splitlines()[1:] if line.strip()}


def prepare(case: dict, work_dir: str, root: str | None = None) -> tuple[str, str]:
    """Materialize the pre-pass project for ``case``; return (project_dir, scene_id).
    Raises LookupError when the case cannot be replayed, with the reason.

    ``scene_id`` is the pre-pass id of the scene the pass rewrites (prose
    families) or whose brief it rewrites (``brief-fix``). For a whole-project
    data pass (hone, illustrate) it only labels the case in the notes: the
    scene whose data or prose carries the error.

    Each case gets its own copy, because passes write into the project and a
    second case at the same commit must start from the same state."""
    if case['id'] in EXCLUDED_CASES:
        raise LookupError(EXCLUDED_CASES[case['id']])
    repo_dir = os.path.join(root or e1.corpus_dir(), case['repo'])
    if not os.path.isdir(os.path.join(repo_dir, '.git')):
        raise RuntimeError(f'{case["repo"]} is not cloned at {repo_dir}')
    parent = _git(repo_dir, 'rev-parse', f'{case["introduced_by"]["commit"]}~1').strip()
    project = materialize(repo_dir, parent, os.path.join(work_dir, case['id']))
    kind = family(case)
    spans = case['contradicted']
    if kind in DATA_FAMILIES:
        if not spans:
            raise ValueError(f'{case["id"]}: no contradicted span')
        scene_id = next((s['scene'] for s in spans if s['path'].endswith('scene-briefs.csv')),
                        spans[0]['scene'])
    else:
        scene_id = target_scene(case, repo_dir)
    if not scene_id:
        raise LookupError(_untouched_reason(case, repo_dir))
    if (not os.path.isfile(os.path.join(project, 'reference', 'scenes.csv'))
            and not migrate_scene_metadata(project)):
        if os.path.isfile(os.path.join(project, 'scenes', 'scene-index.yaml')):
            # Storyforge's YAML-to-CSV migration went with the squash of #13,
            # so running these would mean inventing that conversion (and, for
            # a plan pass, converting a YAML plan, which revise refuses).
            yaml_plan = any(n.endswith('.yaml') for n in os.listdir(
                os.path.join(project, 'working', 'plans'))) if os.path.isdir(
                os.path.join(project, 'working', 'plans')) else False
            raise LookupError('pre-pass project keeps its scenes in scenes/scene-index.yaml'
                              + (' and its plan in YAML (current revise refuses YAML plans)'
                                 if yaml_plan else '')
                              + '; Storyforge has no migration for it')
        raise LookupError('pre-pass project predates reference/scenes.csv')
    needs_briefs = ('redraft-from-brief', 'naturalness-upstream', 'brief-fix', 'hone-physical-states')
    if kind in needs_briefs and not os.path.isfile(
            os.path.join(project, 'reference', 'scene-briefs.csv')):
        raise LookupError('pre-pass project has no scene-briefs.csv')
    if kind == 'brief-fix':
        span = next((s for s in spans if s['path'].endswith('scene-briefs.csv')), spans[0])
        ids = _brief_ids(project)
        scene_id = next((i for i in _span_ids(case, span) if i in ids), '')
        if not scene_id:
            raise LookupError(f'pre-pass scene-briefs.csv has no row for {span["scene"]}')
    if kind == 'revision-plan':
        row = plan_row(project, case['introduced_by']['pass'])
        if row.get('fix_location') in ('structural', 'registry', 'brief', 'intent'):
            raise LookupError(f'pass {row["name"]!r} is a {row["fix_location"]} pass, not prose')
    return project, scene_id
