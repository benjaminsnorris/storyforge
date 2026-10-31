"""E9 — reference completeness: extract phase 5 describes a finished book.

Runs phase 5 (5a-5g) on *A Christmas Carol* (the E2 book: 40 scenes with
prose, its registries migrated into the ledger) and checks that it leaves a
complete project, as #440 set out:

- every file init's reference templates provide, plus `chapter-map.csv` and
  `voice-profile.csv` (which have none), is filled: none is missing, empty,
  header-only or still its template, except what decision 1 exempts
  (`key-decisions.md`, `visual-style.md`, `canon/`: an author's decisions and
  art direction can't be extracted);
- every file phase 5 changed is in what it commits (`WRITTEN_PATHS`);
- the L0-L6 floor checks pass, and L0-L4 (what phase 5 writes) alone. L5-L6
  check the scene layer (phases 1-3; phase 5 only marks status and fills
  blank summaries), so a classic failing them is a finding about the
  extraction or the rubric;
- `storyforge status` finds every ladder rung solid;
- `validate` finds no schema problem;
- a second run, without `--force`, calls no model, writes nothing and
  changes no file outside `working/`.

This measures completeness and the floors, not truth: whether the bibles
describe Carol well is for storyforge-evals to judge against the text.
"""

import hashlib
import os
import shutil
from unittest import mock

from harness import EVALS_DIR, Gate, Suite, SuiteOutput, migrate_tree

BOOK = os.path.join(EVALS_DIR, 'fixtures', 'e2-carol', 'book')
#: Decision 1: never extracted
EXEMPT = frozenset({'key-decisions.md', 'visual-style.md', 'canon'})
#: Files phase 5 writes that have no template under templates/reference/
NO_TEMPLATE = ('chapter-map.csv', 'voice-profile.csv')


def _snapshot(project_dir: str) -> dict[str, str]:
    """Every file's hash, keyed by its path in the project, leaving out
    `.git/` and the project's own `working/` (logs, costs, provenance)."""
    out = {}
    for root, dirs, files in os.walk(project_dir):
        if os.path.relpath(root, project_dir) == '.':
            dirs[:] = [d for d in dirs if d not in ('.git', 'working')]
        for name in files:
            path = os.path.join(root, name)
            with open(path, 'rb') as f:
                out[os.path.relpath(path, project_dir)] = hashlib.sha256(f.read()).hexdigest()
    return out


def _phase_5(project_dir: str) -> tuple[bool, list[str], int]:
    """Run phase 5. Returns whether it wrote, the paths it would commit, and
    how many model calls it made. The suite's tree is a temp copy with no
    remote, so the commit is captured rather than made."""
    from storyforge import api, cmd_extract
    calls = []
    real = api.invoke_to_file

    def counted(*args, **kwargs):
        calls.append(1)
        return real(*args, **kwargs)
    with mock.patch.object(cmd_extract, 'commit_and_push') as commit, \
            mock.patch.object(api, 'invoke_to_file', counted):
        wrote = cmd_extract._run_phase_5(
            project_dir, os.path.join(project_dir, 'working', 'logs'),
            os.path.join(project_dir, 'working', 'extraction-profile.json'),
            False, dry_run=False)
    paths = [p for c in commit.call_args_list for p in c.args[2]]
    return wrote, paths, len(calls)


def run(ctx):
    from storyforge.common import get_plugin_dir, is_unfilled_template
    from storyforge.elaborate import validate_structure
    from storyforge.extract_describe import file_state, read_provenance
    from storyforge.scoring_levels import score_all_levels
    from storyforge.status import build_status

    project = os.path.join(ctx.work_dir, 'carol')
    shutil.copytree(BOOK, project)
    os.makedirs(os.path.join(project, 'working', 'logs'), exist_ok=True)
    migrate_tree(project, 'carol')
    notes = []

    before = _snapshot(project)
    wrote, committed, _ = _phase_5(project)
    changed = sorted(p for p, h in _snapshot(project).items() if before.get(p) != h)
    uncommitted = [p for p in changed
                   if not any(p == c or p.startswith(c.rstrip('/') + '/') for c in committed)]
    notes += [f'changed but not committed: {p}' for p in uncommitted]

    ref = os.path.join(project, 'reference')
    templates = os.path.join(get_plugin_dir(), 'templates', 'reference')
    provenance = read_provenance(project) or {}
    unfilled, extracted = [], 0
    for name in sorted(os.listdir(templates)) + list(NO_TEMPLATE):
        if name in EXEMPT:
            continue
        state = file_state(project, f'reference/{name}', provenance)
        extracted += state == 'extracted'
        if state in ('missing', 'empty', 'header_only', 'template') or \
                is_unfilled_template(os.path.join(ref, name)):
            unfilled.append(f'{name} ({state})')
    notes += [f'unfilled: {u}' for u in unfilled]

    levels = score_all_levels(project)
    floor_failures = sum(r['failed'] for r in levels)
    phase_5_floor_failures = sum(r['failed'] for r in levels if r['level'] <= 4)
    notes += [f'L{r["level"]} {c["check"]}: {c["detail"]}' for r in levels
              for c in r['checks'] if not c['passed']]

    verdict = build_status(project)
    thin = [r for r in verdict['ladder'] if r['state'] != 'solid']
    past_ladder = int(not thin)
    notes.append(f'status next: {verdict["next"]["stage"]}')
    notes += [f'ladder rung not solid: {r}' for r in thin]

    schema = [f for f in validate_structure(ref)['failures'] if f['category'] == 'schema']
    notes += [f'schema: {f["message"][:160]}' for f in schema[:10]]

    before = _snapshot(project)
    rerun_wrote, _, rerun_calls = _phase_5(project)
    rerun_changed = sorted(p for p, h in _snapshot(project).items() if before.get(p) != h)
    notes += [f'rerun changed: {p}' for p in rerun_changed]

    return SuiteOutput(
        metrics={'phase_5_wrote': int(wrote), 'extracted_files': extracted,
                 'unfilled_files': len(unfilled), 'uncommitted_files': len(uncommitted),
                 'floor_failures': floor_failures,
                 'phase_5_floor_failures': phase_5_floor_failures, 'past_ladder': past_ladder,
                 'schema_failures': len(schema), 'rerun_calls': rerun_calls,
                 'rerun_wrote': int(rerun_wrote), 'rerun_changed_files': len(rerun_changed)},
        gates=[Gate('phase_5_wrote', int(wrote), '==', 1),
               Gate('unfilled_files', len(unfilled), '==', 0),
               Gate('uncommitted_files', len(uncommitted), '==', 0),
               Gate('phase_5_floor_failures', phase_5_floor_failures, '==', 0),
               Gate('floor_failures', floor_failures, '==', 0),
               Gate('past_ladder', past_ladder, '==', 1),
               Gate('schema_failures', len(schema), '==', 0),
               Gate('rerun_calls', rerun_calls, '==', 0),
               Gate('rerun_wrote', int(rerun_wrote), '==', 0),
               Gate('rerun_changed_files', len(rerun_changed), '==', 0)],
        notes=notes,
    )


SUITE = Suite('e9-reference', 'Extract phase 5 leaves a complete, floor-passing project', run)
