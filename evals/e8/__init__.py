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
  ``storyforge write`` and ``revise``'s ``_redraft_from_briefs`` take, without
  their refusal fallback (E8 measures the requested model). Their cut-off
  guard is not applied here: a refusal halts, a cut-off reply would be
  replayed as a revision.
- ``naturalness-upstream``: ``cmd_revise._fix_upstream_briefs`` then
  ``_redraft_scenes`` on the scene, the path ``revise --naturalness`` takes
  when the diagnosis names upstream causes. Production code asks for the
  refusal fallback here; under the cassette it is stripped.
- ``revision-plan``: a named pass from the book's own plan CSV, prompted by
  today's ``revision.build_revision_prompt`` with the config block assembled
  as ``cmd_revise.main``'s pass loop assembles it (reader-annotation guidance
  is omitted: there is no Bookshelf in a replay; the pass is narrowed to the
  case's scene). Prose passes only.

Passes that write data rather than prose are replayed the same way, and the
judge reads what the pass wrote (the rows or files it added or changed, see
``written``) instead of a scene (``CSV_JUDGE_PROMPT``). A pass that writes
nothing reintroduces nothing and is counted ``not_present`` without a judge
call. These families:

- ``brief-fix``: ``cmd_revise._fix_upstream_briefs`` on the case's scene, the
  brief rewrite polish/naturalness runs before redrafting; the judge reads the
  rewritten brief row. A rewrite the fix's own guard rejects halts.
- ``hone-physical-states``: ``hone.reconcile_domain('physical-states')``, what
  ``storyforge hone --domain physical-states`` runs, with hone's model; the
  judge reads the rows it added to or changed in the ledger
  (``commitments.csv``, which holds the physical states).
- ``illustrate-state``: ``cmd_illustrate.run_state`` at ``full`` coaching (the
  old pass proposed transitions; coach and strict write no content); the judge
  reads the rows it added to the visual-state log.
- ``illustrate-prompts``: ``cmd_illustrate.run_prompts`` for the prompt file
  the case quotes; the judge reads the prompt files it wrote.

A data pass that exits non-zero errors the suite (it did not do its job); a
hone batch cut off at the token limit halts the case, as a cut-off does in
the prose families. ``EXCLUDED_CASES`` lists cases whose error a replay
cannot show, with why.

A pre-pass project that predates
``reference/scenes.csv`` but has ``scene-metadata.csv`` is migrated in its
materialized copy by a port of Storyforge's removed migrate script
(``migrate_scene_metadata``, an approximation: the books themselves got
``scenes.csv`` from ``extract``); one that keeps its scenes in YAML is reported as
unreplayable. Scenes renamed after the introducing commit are found through
E1's id-maps.

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
        elif case.get('level') != 'prose' and family(case) not in DATA_FAMILIES:
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


def redraft(project_dir: str, scene_id: str) -> str:
    """Run the current redraft-from-brief pass on one scene; return the new prose."""
    from storyforge.api import RefusalError, extract_text, invoke
    from storyforge.cmd_write import _build_prompt
    from storyforge.common import build_shared_context, select_model
    from storyforge.parsing import clean_scene_content, extract_single_scene

    model = select_model('creative')
    system = build_shared_context(project_dir, model=model)
    prompt = _build_prompt(scene_id, project_dir, 'full', use_briefs=True,
                           system_context=bool(system))
    if not prompt:
        raise RuntimeError(f'could not build a redraft prompt for {scene_id}')
    try:
        response = invoke(prompt, model, max_tokens=16384, label=f'e8 redraft {scene_id}',
                          system=system or None)
    except RefusalError as e:  # what write/revise do when the fallback also refuses
        raise PassHalted(f'redraft of {scene_id} refused: {e}') from e
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
    """Run one named prose pass the way ``cmd_revise.main`` does (without the
    refusal fallback); return the new prose of ``scene_id``."""
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


class PassHalted(Exception):
    """The current pass refused to write the scene (a cut-off reply, or the
    model refused the request) and halted. Nothing was written, so nothing can be reintroduced; counted as
    ``halted``, separately from the replayed cases."""


def naturalness_upstream(project_dir: str, scene_id: str) -> str:
    """Rewrite the scene's brief and redraft it, as ``revise --naturalness`` does."""
    from storyforge.cmd_revise import RedraftError, _fix_upstream_briefs, _redraft_scenes
    fixed, skipped = _fix_upstream_briefs(project_dir, [scene_id])
    if not fixed:
        # no reply, a reply missing a field, or a rewrite naming a word the
        # book never uses: revise leaves the brief and prose alone, so nothing
        # can be reintroduced. The reason goes in the halted note, so a guard
        # that rejects everything shows up there rather than as safety.
        raise PassHalted(f'upstream brief fix rewrote nothing for {scene_id}: '
                         f'{skipped.get(scene_id, "unknown")}')
    try:
        count = _redraft_scenes(project_dir, [scene_id])
    except RedraftError as e:  # revise halts and writes nothing: safe, not an error
        raise PassHalted(str(e)) from e
    if count != 1:
        raise RuntimeError(f'naturalness redraft did not rewrite {scene_id}')
    return _read(os.path.join(project_dir, 'scenes', f'{scene_id}.md'))


def _read(path: str) -> str:
    with open(path, encoding='utf-8') as f:
        return f.read()


def _snapshot(project_dir: str, *rels: str) -> dict[str, str]:
    """{relative path: text} for each file, or every file under each directory."""
    found = {}
    for rel in rels:
        root = os.path.join(project_dir, rel)
        if os.path.isfile(root):
            found[rel] = _read(root)
        for dirpath, _dirs, files in os.walk(root):
            for name in sorted(files):
                path = os.path.join(dirpath, name)
                found[os.path.relpath(path, project_dir)] = _read(path)
    return found


def _csv_rows(text: str) -> tuple[str, dict[str, dict[str, str]]] | None:
    """(header line, {id: row}) for a pipe-delimited CSV keyed by a unique
    first column; None when the text is not one (e.g. the visual-state log,
    whose rows repeat an entity)."""
    lines = [line for line in text.splitlines() if line.strip()]
    if not lines or '|' not in lines[0]:
        return None
    header = lines[0].split('|')
    rows = {}
    for line in lines[1:]:
        row = dict(zip(header, line.split('|')))
        if row[header[0]] in rows:
            return None
        rows[row[header[0]]] = row
    return lines[0], rows


def _same_row(a: dict[str, str], b: dict[str, str]) -> bool:
    # a rewrite that only adds empty columns (cmd_revise writes briefs with
    # every column of today's schema) leaves the row as it was
    return all((a.get(k) or '') == (b.get(k) or '') for k in {*a, *b})


def written(before: dict[str, str], after: dict[str, str]) -> str:
    """What a pass wrote, for the judge. Per changed file: for a CSV keyed by
    a unique id, its header and every row that is new or changed, by id, with
    removed rows marked; for any other file, its first line (a CSV's header),
    every new line, and every removed line marked ``(removed)``. A new file is
    given whole, a deleted one named. '' when nothing changed."""
    parts = []
    for path in sorted({*before, *after}):
        old, text = before.get(path), after.get(path)
        if old == text:
            continue
        if text is None:
            parts.append(f'{path} (deleted)')
            continue
        if old is None:
            parts.append(f'{path} (new file):\n{text.rstrip()}')
            continue
        old_csv, new_csv = _csv_rows(old), _csv_rows(text)
        if old_csv and new_csv:
            new_lines = text.splitlines()
            changed = [line for line in new_lines[1:] if line.strip()
                       and not _same_row(old_csv[1].get(line.split('|')[0], {}),
                                         dict(zip(new_csv[0].split('|'), line.split('|'))))]
            removed = [f'(removed) {line}' for line in old.splitlines()[1:]
                       if line.strip() and line.split('|')[0] not in new_csv[1]]
        else:
            new_lines, kept, now = text.splitlines(), set(old.splitlines()), set(text.splitlines())
            changed = [line for line in new_lines[1:] if line not in kept]
            removed = [f'(removed) {line}' for line in old.splitlines()[1:] if line not in now]
            if new_lines[:1] != old.splitlines()[:1]:
                changed.insert(0, f'(first line was) {old.splitlines()[0] if old.strip() else ""}')
        if changed or removed:
            parts.append(f'{path}:\n' + '\n'.join(new_lines[:1] + changed + removed))
    return '\n\n'.join(parts)


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


def brief_fix(project_dir: str, scene_id: str) -> str:
    """Rewrite one scene's brief as the polish/naturalness upstream fix does;
    return the brief rows that changed."""
    from storyforge.cmd_revise import _fix_upstream_briefs
    rel = os.path.join('reference', 'scene-briefs.csv')
    before = _snapshot(project_dir, rel)
    fixed, skipped = _fix_upstream_briefs(project_dir, [scene_id])
    if not fixed:  # as naturalness_upstream: nothing written, reason in the note
        raise PassHalted(f'upstream brief fix rewrote nothing for {scene_id}: '
                         f'{skipped.get(scene_id, "unknown")}')
    return written(before, _snapshot(project_dir, rel))


def hone_physical_states(project_dir: str) -> str:
    """Reconcile the physical states as ``storyforge hone`` does; return what
    it wrote to the ledger and to the briefs' state columns."""
    from storyforge import hone
    from storyforge.common import select_model
    ref_dir = os.path.join(project_dir, 'reference')
    rels = (os.path.join('reference', 'commitments.csv'),
            os.path.join('reference', 'scene-briefs.csv'))
    before = _snapshot(project_dir, *rels)
    log_dir = os.path.join(project_dir, 'working', 'logs')
    os.makedirs(log_dir, exist_ok=True)
    cut_off = []
    invoke_batch = hone._invoke_batch

    def counting(prompt, model, log_file, label):
        text = invoke_batch(prompt, model, log_file, label)
        if text is None:
            cut_off.append(label)
        return text
    hone._invoke_batch = counting
    try:
        hone.reconcile_domain('physical-states', ref_dir, select_model('synthesis'), log_dir)
    finally:
        hone._invoke_batch = invoke_batch
    if cut_off:
        # hone applies the batches that finished and leaves the rest
        # unresolved; judging that partial output would score a pass that
        # never ran on part of the book, so it halts like the other cut-offs
        raise PassHalted(f'{len(cut_off)} hone batch(es) cut off at the token limit: '
                         + '; '.join(cut_off))
    return written(before, _snapshot(project_dir, *rels))


def illustrate(project_dir: str, family_name: str, ids: set[str] | None = None) -> str:
    """Run ``illustrate --state`` or ``--prompts`` at full coaching; return
    the log rows or prompt files it wrote."""
    from storyforge import cmd_illustrate, illustrations, visual_state
    if family_name == 'illustrate-state':
        rel = visual_state.STATE_FILE
        run = lambda: cmd_illustrate.run_state(project_dir, 'full', dry_run=False)  # noqa: E731
    else:
        rel = illustrations.PROMPTS_SUBDIR
        run = lambda: cmd_illustrate.run_prompts(project_dir, 'full', ids, dry_run=False)  # noqa: E731
    before = _snapshot(project_dir, rel)
    with _cassette_key():
        status = run()
    if status != 0:
        # an unparseable or failed reply, an unknown id, a partial --prompts
        # run: the pass did not do its job, so the suite errors rather than
        # count the case as halted (safe)
        raise RuntimeError(f'{family_name} exited {status} (its log above says why); wrote: '
                           f'{written(before, _snapshot(project_dir, rel))[:300] or "nothing"}')
    return written(before, _snapshot(project_dir, rel))


def replay(case: dict, project_dir: str, scene_id: str) -> str:
    """Run today's version of the case's pass. Returns the new prose of the
    scene for a prose family, and ``written()``'s account of what the pass
    wrote for a family in ``DATA_FAMILIES`` ('' when it wrote nothing)."""
    kind = family(case)
    if kind == 'brief-fix':
        return brief_fix(project_dir, scene_id)
    if kind == 'hone-physical-states':
        return hone_physical_states(project_dir)
    if kind in ('illustrate-state', 'illustrate-prompts'):
        return illustrate(project_dir, kind, {os.path.splitext(os.path.basename(s['path']))[0]
                                              for s in case['contradicted']
                                              if 'prompts/' in s['path']} or None)
    if kind == 'redraft-from-brief':
        return redraft(project_dir, scene_id)
    if kind == 'naturalness-upstream':
        return naturalness_upstream(project_dir, scene_id)
    if kind == 'revision-plan':
        return revision_pass(project_dir, scene_id, plan_row(project_dir, case['introduced_by']['pass']))
    raise ValueError(f'{case["id"]}: no replayable pass family')


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
