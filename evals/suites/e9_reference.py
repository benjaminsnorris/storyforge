"""E9 — reference completeness: extract phase 5 describes a finished book.

Runs phase 5 (5a-5g) on *A Christmas Carol* (the E2 book: 40 scenes with
prose, its registries migrated into the ledger) and checks that it leaves a
complete project, as #440 set out:

- every reference file is filled: none is still its template and no registry
  is header-only, except what decision 1 exempts (`key-decisions.md`,
  `visual-style.md`, `canon/`: an author's decisions and art direction can't
  be extracted);
- the L0-L6 floor checks pass (L0-L4, what phase 5 writes, are also gated
  alone: L5-L6 are the scene layer phases 1-3 built, and a classic failing
  them is a finding about the extraction or the rubric);
- `storyforge status` walks past the elaboration ladder;
- `validate` finds no schema problem;
- a second run, without `--force`, calls nothing and changes nothing.

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
EXEMPT = {'key-decisions.md', 'visual-style.md', 'canon'}
#: The stages past the elaboration ladder (`status.Stage`)
PAST_LADDER = {'story-power', 'draft', 'evaluate'}


def _snapshot(project_dir: str) -> dict[str, str]:
    out = {}
    for root, _, files in os.walk(project_dir):
        if '.git' in root.split(os.sep) or os.sep + 'working' in root:
            continue
        for name in files:
            path = os.path.join(root, name)
            with open(path, 'rb') as f:
                out[os.path.relpath(path, project_dir)] = hashlib.sha256(f.read()).hexdigest()
    return out


def _phase_5(project_dir: str) -> bool:
    from storyforge import cmd_extract
    # The suite's tree is a temp copy with no remote: nothing to commit to
    with mock.patch.object(cmd_extract, 'commit_and_push'):
        return cmd_extract._run_phase_5(
            project_dir, os.path.join(project_dir, 'working', 'logs'),
            os.path.join(project_dir, 'working', 'extraction-profile.json'),
            False, dry_run=False)


def run(ctx):
    from storyforge.common import get_plugin_dir, is_unfilled_template
    from storyforge.elaborate import validate_structure
    from storyforge.extract_describe import file_state
    from storyforge.scoring_levels import score_all_levels
    from storyforge.status import build_status

    project = os.path.join(ctx.work_dir, 'carol')
    shutil.copytree(BOOK, project)
    os.makedirs(os.path.join(project, 'working', 'logs'), exist_ok=True)
    migrate_tree(project, 'carol')
    notes = []

    wrote = _phase_5(project)

    ref = os.path.join(project, 'reference')
    templates = os.path.join(get_plugin_dir(), 'templates', 'reference')
    unfilled = []
    # chapter-map.csv has no template under reference/ (5g writes it when missing)
    for name in sorted(os.listdir(templates)) + ['chapter-map.csv']:
        if name in EXEMPT:
            continue
        rel = f'reference/{name}'
        state = file_state(project, rel, {})
        path = os.path.join(ref, name)
        if state in ('missing', 'empty', 'header_only') or is_unfilled_template(path):
            unfilled.append(f'{name} ({state})')
    notes += [f'unfilled: {u}' for u in unfilled]

    levels = score_all_levels(project)
    floor_failures = sum(r['failed'] for r in levels)
    # L0-L4 are what phase 5 writes; L5-L6 are the scene layer phases 1-3
    # built, so a failure there is about the extraction or the rubric
    phase_5_floor_failures = sum(r['failed'] for r in levels if r['level'] <= 4)
    notes += [f'L{r["level"]} {c["check"]}: {c["detail"]}' for r in levels
              for c in r['checks'] if not c['passed']]

    verdict = build_status(project)
    stage = verdict['next']['stage']
    notes.append(f'status next: {stage}')

    schema = [f for f in validate_structure(ref)['failures'] if f['category'] == 'schema']
    notes += [f'schema: {f["message"][:160]}' for f in schema[:10]]

    before = _snapshot(project)
    rerun_wrote = _phase_5(project)
    changed = sorted(p for p, h in _snapshot(project).items() if before.get(p) != h)
    notes += [f'rerun changed: {p}' for p in changed]

    return SuiteOutput(
        metrics={'phase_5_wrote': int(wrote), 'unfilled_files': len(unfilled),
                 'floor_failures': floor_failures,
                 'phase_5_floor_failures': phase_5_floor_failures, 'past_ladder': int(stage in PAST_LADDER),
                 'schema_failures': len(schema), 'rerun_wrote': int(rerun_wrote),
                 'rerun_changed_files': len(changed)},
        gates=[Gate('phase_5_wrote', int(wrote), '==', 1),
               Gate('unfilled_files', len(unfilled), '==', 0),
               Gate('phase_5_floor_failures', phase_5_floor_failures, '==', 0),
               Gate('floor_failures', floor_failures, '==', 0),
               Gate('past_ladder', int(stage in PAST_LADDER), '==', 1),
               Gate('schema_failures', len(schema), '==', 0),
               Gate('rerun_changed_files', len(changed), '==', 0)],
        notes=notes,
    )


SUITE = Suite('e9-reference', 'Extract phase 5 leaves a complete, floor-passing project', run)
