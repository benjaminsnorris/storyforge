"""storyforge cleanup — Project structure cleanup and migration.

Fixes structural drift in Storyforge novel projects: updates gitignore,
creates missing directories, migrates storyforge.yaml, adds CSV columns,
removes junk files, deletes legacy artifacts, and reports integrity issues.

Usage:
    storyforge cleanup                  # Apply all fixes and commit
    storyforge cleanup --dry-run        # Report what would change
    storyforge cleanup --verbose        # Detailed output
    storyforge cleanup --scenes         # Also strip writing-agent artifacts
    storyforge cleanup --csv            # Run only the CSV integrity report
"""

import argparse
import glob
import os
import posixpath
import re
import shutil
import subprocess
import sys

from storyforge.canon import CANON_DIR, CanonFinding, validate_canon_directory
from storyforge.illustrations import (
    OPTIONAL_PLAN_COLUMNS, PLAN_COLUMNS, IllustrationFindingKind,
)
from dataclasses import dataclass
from typing import Callable, Final, NamedTuple, get_args

from storyforge import common
from storyforge.common import (
    csv_safe, detect_project_root, get_medium, log, read_yaml_field,
)
from storyforge.git import commit_and_push, ensure_on_branch
from storyforge.parsing import clean_scene_content, extract_single_scene
from storyforge.visual_state import STATE_COLUMNS


# ============================================================================
# Constants
# ============================================================================

#: Every entry a Storyforge project's `.gitignore` must contain, in the order
#: they are appended. `_gitignore_with_required` is driven by this list, which
#: it previously only *claimed* in a docstring — six of the seven entries were
#: hardcoded in a chain of `if`s and `.DS_Store` appeared solely in the seed
#: written for a *missing* file, so a project with a hand-written `.gitignore`
#: never got it and the constant was dead outside the test suite.
GITIGNORE_REQUIRED: Final = [
    '.DS_Store',
    'working/logs/',
    'working/scores/**/.batch-requests.jsonl',
    'working/evaluations/**/.status-*',
    'working/scores/**/.markers-*',
    'working/.autopilot',
    'working/.interactive',
]

EXPECTED_DIRS = [
    'manuscript/press-kit',
    'working/logs',
    'working/evaluations',
    'working/plans',
    'working/recommendations',
]

PIPELINE_EXPECTED = 'cycle|started|status|evaluation|scoring|plan|review|recommendations|summary'

EXPECTED_TOP_DIRS = set('scenes reference working manuscript storyforge .git'.split())
EXPECTED_TOP_FILES = set('storyforge.yaml CLAUDE.md .gitignore .DS_Store storyforge'.split())

# Expected CSV schemas — canonical column lists for all known CSV files.
# Keys are paths relative to project root.
EXPECTED_CSV_SCHEMAS: dict[str, list[str]] = {
    # Core scene data (reference/)
    'reference/scenes.csv': [
        'id', 'seq', 'title', 'part', 'pov', 'location',
        'timeline_day', 'time_of_day', 'duration', 'type', 'status',
        'word_count', 'target_words',
    ],
    'reference/scene-intent.csv': [
        'id', 'function', 'action_sequel', 'emotional_arc', 'value_at_stake',
        'value_shift', 'turning_point', 'characters', 'on_stage',
        'mice_threads',
    ],
    'reference/scene-briefs.csv': [
        'id', 'goal', 'conflict', 'outcome', 'crisis', 'decision',
        'knowledge_in', 'knowledge_out', 'key_actions', 'key_dialogue',
        'emotions', 'motifs', 'subtext', 'continuity_deps', 'has_overflow',
        'physical_state_in', 'physical_state_out',
    ],
    # Registry CSVs (reference/)
    'reference/characters.csv': ['id', 'name', 'aliases', 'role', 'death_scene'],
    'reference/locations.csv': ['id', 'name', 'aliases'],
    'reference/values.csv': ['id', 'name', 'aliases'],
    'reference/knowledge.csv': ['id', 'name', 'aliases', 'category', 'origin'],
    'reference/mice-threads.csv': ['id', 'name', 'type', 'aliases'],
    'reference/motif-taxonomy.csv': ['id', 'name', 'aliases', 'tier'],
    'reference/physical-states.csv': [
        'id', 'character', 'description', 'category', 'acquired',
        'resolves', 'action_gating',
    ],
    'reference/chapter-map.csv': [
        'chapter', 'title', 'heading', 'part', 'scenes',
    ],
    'reference/voice-profile.csv': [
        'character', 'preferred_words', 'banned_words', 'metaphor_families',
        'rhythm_preference', 'register', 'dialogue_style',
    ],
    # Working CSVs
    'working/craft-weights.csv': [
        'section', 'principle', 'weight', 'author_weight', 'notes',
    ],
    'working/pipeline.csv': [
        'cycle', 'started', 'status', 'evaluation', 'scoring',
        'plan', 'review', 'recommendations', 'summary',
    ],
    'working/costs/ledger.csv': [
        'timestamp', 'operation', 'target', 'model', 'input_tokens',
        'output_tokens', 'cache_read', 'cache_create', 'cost_usd',
        'duration_s',
    ],
    'working/scores/score-history.csv': [
        'cycle', 'scene_id', 'principle', 'score',
    ],
    # Registered so `cleanup --csv` can see a malformed header; the
    # cross-referential checks live in _check_illustrations. Listed in
    # ALWAYS_OPTIONAL_CSV_FILES — most books have no illustrations, so its
    # absence is not a finding.
    'reference/illustration-plan.csv': list(PLAN_COLUMNS),
    # The visual-state transition log. Registered so a malformed header and
    # CRLF endings are caught; the cross-referential checks (does `from_scene`
    # resolve, does `evidence` still appear in the prose) live in
    # visual_state.prepass. Also always optional — most books track no
    # changing visual state.
    'reference/visual-state.csv': list(STATE_COLUMNS),
}

#: Registered for header checking but never required to exist, in any medium.
ALWAYS_OPTIONAL_CSV_FILES: set[str] = {
    'reference/illustration-plan.csv',
    'reference/visual-state.csv',
}

#: Columns a registered CSV may legally lack — schema additions that older
#: projects predate and that the owning writer adds on its next write. Absence
#: is not a finding: `cleanup` would otherwise tell an author to hand-edit a
#: header that `storyforge illustrate` upgrades by itself, and the illustration
#: code reads an absent/empty `ingested_at` as meaningful (pre-canon), not
#: broken. Sourced from the owning module so the two cannot drift.
OPTIONAL_CSV_COLUMNS: dict[str, set[str]] = {
    'reference/illustration-plan.csv': set(OPTIONAL_PLAN_COLUMNS),
}
EXPECTED_WORKING_DIRS = set(
    'logs evaluations plans scores costs reviews recommendations coaching enrich timeline backups scenes-setup'.split()
)

# Graphic-novel schema overrides — these replace/augment the base schemas for
# projects where project.medium == 'graphic-novel'.
GN_CSV_SCHEMA_OVERRIDES: dict[str, list[str]] = {
    'reference/scenes.csv': [
        'id', 'seq', 'title', 'part', 'pov', 'location',
        'timeline_day', 'time_of_day', 'duration', 'type', 'status',
        'word_count', 'target_words', 'target_pages', 'panel_count', 'page_count',
    ],
    'reference/scene-briefs.csv': [
        'id', 'goal', 'conflict', 'outcome', 'crisis', 'decision',
        'knowledge_in', 'knowledge_out', 'key_actions', 'key_dialogue',
        'emotions', 'motifs', 'subtext', 'continuity_deps', 'has_overflow',
        'physical_state_in', 'physical_state_out',
        'page_layout', 'panel_breakdown', 'visual_keywords',
        'page_turn_beats', 'caption_strategy',
    ],
    'reference/voice-profile.csv': [
        'character', 'preferred_words', 'banned_words', 'metaphor_families',
        'rhythm', 'register', 'dialogue_style', 'caption_voice', 'lettering_style',
    ],
}

# CSV files that are optional (not required) in graphic-novel mode.
GN_OPTIONAL_CSV_FILES: set[str] = {
    'reference/characters.csv',
    'reference/locations.csv',
    'reference/values.csv',
    'reference/knowledge.csv',
    'reference/mice-threads.csv',
    'reference/motif-taxonomy.csv',
    'reference/physical-states.csv',
    'reference/chapter-map.csv',
}
EXPECTED_WORKING_FILES = set(
    'pipeline.csv craft-weights.csv overrides.csv exemplars.csv dashboard.html cleanup-report.csv'.split()
)


# ============================================================================
# The planner
# ============================================================================
#
# `--dry-run` and the real run consume ONE computation per step: each step is a
# `plan_*` returning a `StepPlan`, and `main` renders `plan.changes` or calls
# `plan.apply`. Neither mode has a branch of its own, so they cannot disagree
# by drifting apart the way a preview and a mutator did (#317).
#
# **Adding a 14th step means adding a `plan_*` function, not an
# `if args.dry_run:` branch** — see CLAUDE.md's "Cleanup's planner", which owns
# the rationale and the rules for what a new step has to do.

class PlannedChange(NamedTuple):
    """One change a step will make, phrased for both of cleanup's audiences.

    Two strings rather than one because the modes address the author
    differently — `--dry-run` says "Would create …" and a verbose real run says
    "Created …" — and deriving the second from the first means a verb table
    that is wrong for the first irregular verb. What matters is that both come
    from one list built once: a change cannot be announced by one mode and
    performed by the other, because there is nothing else to perform.
    """
    would: str
    did: str


class StepPlan(NamedTuple):
    """What one cleanup step would do, and the closure that does it.

    `changes` is empty exactly when the step has nothing to do — that
    equivalence is the property `tests/commands/test_cmd_cleanup_dry_run.py`
    asserts per step, so a planner must not list a change it will not make and
    must not make one it did not list.

    `summary` is rendered after `changes` in both modes and *whether or not*
    there are any, for the one step that reports a clean result out loud
    ("All scene files are clean."). Everything else stays silent when it has
    nothing to say.

    **`apply` returns the changes it actually made**, which is usually all of
    them and must not be assumed to be. It returned `None` for one commit, and
    `main` printed every `change.did` on the strength of having called it — so
    a `PermissionError` on the yaml temp-write logged "could not write
    storyforge.yaml … The file is unchanged." and then "Migrated
    storyforge.yaml" directly underneath. `did` was a flag asserted beside the
    branch it claimed to summarise, which is what `YamlMigrationPlan.changed`
    was made a comparison to avoid; a `-> None` thunk cannot tell the runner
    what it did.
    """
    title: str
    changes: tuple[PlannedChange, ...]
    apply: Callable[[], tuple[PlannedChange, ...]]
    summary: PlannedChange | None = None


def _no_op() -> tuple[PlannedChange, ...]:
    """The `apply` for a step that planned nothing, or could not plan at all."""
    return ()


def _warn_unwalkable(exc: OSError) -> None:
    """A directory a planner needed to read could not be read.

    `os.walk`'s default `onerror=None` *swallows* the error and skips the
    subtree, so a step reported fewer files than the run would touch and the
    short list was indistinguishable from a clean one. That is a dry-run
    under-report produced by the code that exists to end dry-run under-reports,
    which is why the callback is passed explicitly rather than left at its
    default.
    """
    log(f'WARNING: could not read {getattr(exc, "filename", "a directory")} '
        f'({type(exc).__name__}), so anything inside it was not counted and '
        f'will not be touched.')


def _warn_vanished(what: str) -> None:
    """A planned target was gone by the time `apply` reached it.

    Every applier re-checks the filesystem before acting, because a plan built
    up front describes a project something else may have touched since. That
    guard used to make the drop *silent*, so `--verbose` printed the change
    anyway; a change is now reported only if it happened, and the shortfall is
    said out loud rather than inferred from a missing line.
    """
    log(f'WARNING: {what} was gone before cleanup reached it, so that part of '
        f'the plan was skipped. Re-run to see the current state.')


def _is_empty_dir(path: str) -> bool:
    """Guarded: `os.listdir` on an unreadable directory raised out of the
    planner, and `plan_cleanup` builds every plan before the first one runs —
    so one `PermissionError` cost all nine steps *and* the report, which is
    `cleanup`'s actual product. #298's shape at a new call site."""
    try:
        return os.path.isdir(path) and not os.listdir(path)
    except OSError as exc:
        log(f'WARNING: could not read {path} ({type(exc).__name__}), so it '
            f'was left alone.')
        return False


@dataclass(frozen=True)
class DiskFacts:
    """The filesystem as the real run's *later* steps will see it.

    Gathered once, before any step runs, and deliberately including the effects
    earlier steps will have — which is the half of #317 that no sandbox could
    reproduce. Step 2 creates every missing `EXPECTED_DIRS` entry (each with a
    `.gitkeep`), so by the time step 3 resolves an artifact's `exists:` flag,
    `manuscript/` is there. A planner that asked `os.path` directly would
    answer for the project at entry and under-report.

    Both modes consult the same instance, so both get the real run's answer.
    `--dry-run` then describes a `manuscript/` that is not there yet — correct,
    because it is describing what the run would do, and it does not write.

    Paths are project-relative and `/`-separated on both sides of every
    comparison — **stored entries as well as queries**, normalized in `__new__`.
    Normalizing only the query is not a half-measure but a distinct bug: it let
    `pending_files=('working/logs',)` answer True to `isfile('working/logs')`,
    so a transposed keyword argument type-checked and misbehaved silently.
    """
    root: str
    pending_dirs: tuple[str, ...] = ()
    pending_files: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        # A frozen dataclass rather than the `NamedTuple` the rest of this
        # module uses, for one reason: `typing.NamedTuple` forbids overriding
        # `__new__`, so there is nowhere to normalize the stored entries. A
        # factory function would leave direct construction — which every test
        # uses — bypassing it, and "normalized only if you went through the
        # right door" is the bug this is fixing, not a fix for it.
        object.__setattr__(self, 'pending_dirs',
                           tuple(self._as_pending(p) for p in self.pending_dirs))
        object.__setattr__(self, 'pending_files',
                           tuple(self._as_pending(p) for p in self.pending_files))

    def exists(self, rel: str) -> bool:
        """Does `rel` exist, or will an earlier step have created it?

        A pending *descendant* makes its ancestors exist too: nothing plans
        `manuscript/` itself, only `manuscript/press-kit` inside it.
        """
        if os.path.exists(os.path.join(self.root, rel)):
            return True
        if os.path.isabs(rel):
            return False
        norm = self._norm(rel)
        if not norm:
            return True
        return any(p == norm or p.startswith(norm + '/')
                   for p in self.pending_dirs + self.pending_files)

    def isfile(self, rel: str) -> bool:
        if os.path.isfile(os.path.join(self.root, rel)):
            return True
        if os.path.isabs(rel):
            return False
        return self._norm(rel) in self.pending_files

    def list_files(self, reldir: str) -> list[str]:
        """Project-relative paths of the files directly inside `reldir`."""
        return self._files(reldir, recursive=False)

    def walk_files(self, reldir: str) -> list[str]:
        """Project-relative paths of every file under `reldir`, recursively."""
        return self._files(reldir, recursive=True)

    def abspath(self, rel: str) -> str:
        if os.path.isabs(rel):
            return rel
        norm = self._norm(rel)
        return os.path.join(self.root, *norm.split('/')) if norm else self.root

    @staticmethod
    def _as_pending(rel: str) -> str:
        """One stored pending entry, in the spelling comparisons use.

        Absolute is a programming error rather than bad author data — every
        pending path is built by `gather_disk_facts` from `EXPECTED_DIRS` — so
        it raises instead of being quietly reinterpreted, which is how the
        query side went wrong.
        """
        if os.path.isabs(rel):
            raise ValueError(f'pending paths are project-relative: {rel!r}')
        norm = DiskFacts._norm(rel)
        if not norm or norm.startswith('..'):
            raise ValueError(f'not a path inside the project: {rel!r}')
        return norm

    @staticmethod
    def _norm(rel: str) -> str:
        """`/`-separated, no `.` segments, no doubled or edge separators.

        **Only ever applied to a path already known to be relative.** Its
        `strip('/')` would turn `/manuscript` into `manuscript`, and the caller
        one line above resolves the same string absolutely through
        `os.path.join` — so an absolute artifact `path:` cell was checked
        against the real filesystem *and* against the pending set as though it
        were project-relative. On a nonexistent `/manuscript` that wrote
        `exists: true`, then flipped it to `false` on the next run: two commits
        to `storyforge.yaml`, the first recording a falsehood, where the code
        this replaced was stable. `exists`/`isfile`/`abspath` each check
        `os.path.isabs` before calling this.
        """
        norm = posixpath.normpath(rel.replace(os.sep, '/').strip('/'))
        return '' if norm == '.' else norm

    def _files(self, reldir: str, recursive: bool) -> list[str]:
        norm = self._norm(reldir)
        found: set[str] = set()
        base = os.path.join(self.root, *norm.split('/'))
        if os.path.isdir(base):
            if recursive:
                # `onerror` stated. `os.walk`'s default is to swallow the error
                # and skip the subtree, so an unreadable directory produced a
                # short list that reads exactly like a clean one — a dry-run
                # under-report out of the code written to end dry-run
                # under-reports.
                for root, _dirs, names in os.walk(base, onerror=_warn_unwalkable):
                    for name in names:
                        found.add(self._norm(
                            os.path.relpath(os.path.join(root, name), self.root)))
            else:
                try:
                    names = os.listdir(base)
                except OSError as exc:
                    _warn_unwalkable(exc)
                    names = []
                for name in names:
                    if os.path.isfile(os.path.join(base, name)):
                        found.add(f'{norm}/{name}')
        prefix = norm + '/'
        for pending in self.pending_files:
            if not pending.startswith(prefix):
                continue
            if recursive or '/' not in pending[len(prefix):]:
                found.add(pending)
        return sorted(found)


def gather_disk_facts(project_dir: str) -> tuple[DiskFacts, list[str]]:
    """Snapshot the filesystem plus the directories step 2 will create.

    Returns the facts and the missing-directory list, because the directory
    step needs the same list it seeded the facts with — deriving it twice is
    two chances to answer differently, which is the defect this whole module
    is being restructured to remove.
    """
    missing = missing_expected_dirs(project_dir)
    return DiskFacts(
        root=project_dir,
        pending_dirs=tuple(missing),
        # `create_missing_dirs` drops a `.gitkeep` in each, and step 5 then
        # deletes every file in `working/logs` — including that one. A planner
        # blind to the `.gitkeep` reports "0 log files" for a run that removes
        # a file it created a moment earlier.
        pending_files=tuple(f'{d}/.gitkeep' for d in missing),
    ), missing


# ============================================================================
# Gitignore
# ============================================================================

GITIGNORE_SEED: Final = (
    '# Storyforge — Novel Project .gitignore\n\n# macOS\n.DS_Store\n\n'
)


def plan_gitignore(project_dir: str) -> StepPlan:
    """Plan the `.gitignore` entries this project is missing."""
    path = os.path.join(project_dir, '.gitignore')
    title = 'Checking .gitignore...'

    original = ''
    if os.path.isfile(path):
        try:
            with open(path, encoding='utf-8') as f:
                original = f.read()
        except (OSError, UnicodeDecodeError) as exc:
            # Reported rather than raised, matching the yaml migration below:
            # `cleanup`'s actual product is the read-only report, and an
            # unreadable `.gitignore` must not take it down with it.
            log(f'WARNING: could not read .gitignore '
                f'({type(exc).__name__}: {exc}). Skipping the gitignore step; '
                f'the rest of cleanup still runs.')
            return StepPlan(title, (), _no_op)
        content = original
    else:
        content = GITIGNORE_SEED

    new_content = _gitignore_with_required(content)
    if new_content == original:
        return StepPlan(title, (), _no_op)

    change = PlannedChange('Would update .gitignore with missing entries',
                           'Updated .gitignore with missing entries')

    def apply() -> tuple[PlannedChange, ...]:
        with open(path, 'w', encoding='utf-8') as f:
            f.write(new_content)
        return (change,)

    return StepPlan(title, (change,), apply)


def _gitignore_with_required(content: str) -> str:
    """Return `content` with every `GITIGNORE_REQUIRED` entry present.

    Returns `content` **unchanged** when nothing is missing, which is load-
    bearing rather than an optimization: the caller decides whether to write by
    comparing, so a cosmetic edit here becomes a reported change. Appending the
    trailing newline unconditionally did exactly that — a complete `.gitignore`
    whose last line was unterminated got rewritten, under the message "missing
    entries", every single run. #314's shape on a different file.
    """
    missing = [entry for entry in GITIGNORE_REQUIRED if entry not in content]
    if not missing:
        return content

    blocks = {
        '.DS_Store': '\n# macOS\n.DS_Store\n',
        'working/logs/':
            '\n# Logs (debugging output, value extracted at write time)\n'
            'working/logs/\n',
        'working/scores/**/.batch-requests.jsonl':
            '\n# Batch API payloads (keep only latest for debugging)\n'
            'working/scores/**/.batch-requests.jsonl\n',
        'working/evaluations/**/.status-*':
            '\n# Intermediate scoring/eval state\n'
            'working/evaluations/**/.status-*\n',
        'working/scores/**/.markers-*': 'working/scores/**/.markers-*\n',
        'working/.autopilot':
            '\n# Temporary flag files (cleaned up by scripts)\n'
            'working/.autopilot\nworking/.interactive\n',
    }

    new_content = content
    if new_content and not new_content.endswith('\n'):
        new_content += '\n'

    for entry in GITIGNORE_REQUIRED:
        if entry in blocks and entry in missing:
            new_content += blocks[entry]

    # `working/.interactive` is the one entry with no block of its own: when
    # `working/.autopilot` is already present it belongs on the line after it,
    # not in a new stanza at the end of the file.
    if 'working/.interactive' not in new_content:
        new_content = new_content.replace(
            'working/.autopilot\n', 'working/.autopilot\nworking/.interactive\n')

    return new_content


def _untrack_newly_ignored(project_dir: str) -> None:
    """`git rm --cached` files the .gitignore now excludes.

    Deliberately **not** a `StepPlan`, and called from `main` rather than from
    inside one. It is an effect on the git index rather than on the project's
    files, and the count cannot be known before the write: `git ls-files -i`
    answers against the `.gitignore` on disk, so asking it beforehand reports
    against the old one. `--dry-run` therefore says nothing about untracking,
    which is a stated gap rather than a claim of no effect.

    **It lived inside `plan_gitignore`'s `apply` for one commit, and that was
    wrong twice over.** `apply` is `_no_op` when the file already has every
    required entry, so the sweep stopped running from the second cleanup
    onward — where it had always run on every real run. And it made that step
    the one place `apply` did something `changes` did not describe, which is
    precisely the invariant `StepPlan` exists to hold; the property test could
    not catch it, because a test project has no `.git`. A git-index effect is
    not a step, so it is not modelled as one.
    """
    git_dir = os.path.join(project_dir, '.git')
    if not (shutil.which('git') and os.path.isdir(git_dir)):
        return
    # `-c` is required, not decorative: `git ls-files -i` has been fatal
    # without either `-o` or `-c` since git 2.32, and the failure was silent
    # in the worst way available — `capture_output` swallowed the
    # `fatal: ls-files -i must be used with either -o or -c` and nothing
    # checked `returncode`, so `stdout` was `''` and the empty result read as
    # "nothing is ignored-but-tracked". The sweep did nothing, said nothing,
    # and exited 0 on every machine with a current git.
    r = subprocess.run(
        ['git', '-C', project_dir, 'ls-files', '-i', '-c',
         '--exclude-standard'],
        capture_output=True, text=True,
    )
    if r.returncode != 0:
        log(f'WARNING: could not list ignored-but-tracked files '
            f'({r.stderr.strip()}). Nothing was untracked; the rest of '
            f'cleanup still runs.')
        return
    tracked = r.stdout.strip()
    if not tracked:
        return
    log(f'  Untracking {len(tracked.splitlines())} newly-gitignored files')
    for f in tracked.splitlines():
        subprocess.run(['git', '-C', project_dir, 'rm', '--cached', '-q', f],
                       capture_output=True)


def update_gitignore(project_dir: str) -> None:
    """Ensure .gitignore contains all required entries.

    Delegates, where it used to be a second implementation of the same logic
    sitting beside the planner and calling itself "the applier half". Two
    implementations that agree today is the arrangement this whole module was
    restructured to remove, and the fork's stated reason — keeping the
    git-index side effect out of the unit under test — went away when
    `_untrack_newly_ignored` moved to `main`.
    """
    plan_gitignore(project_dir).apply()


# ============================================================================
# Missing directories
# ============================================================================

def missing_expected_dirs(project_dir: str) -> list[str]:
    """The `EXPECTED_DIRS` entries this project does not have.

    The one derivation of that list. `gather_disk_facts` seeds `DiskFacts` with
    it and `plan_missing_dirs` creates exactly it, so no later step can observe
    a directory the directory step will not create, or miss one it will.
    """
    return [d for d in EXPECTED_DIRS
            if not os.path.isdir(os.path.join(project_dir, d))]


def _make_dirs(project_dir: str, dirs: list[str]) -> None:
    for d in dirs:
        path = os.path.join(project_dir, d)
        os.makedirs(path, exist_ok=True)
        # The `.gitkeep` is why `gather_disk_facts` seeds `pending_files`:
        # the junk step deletes every file in `working/logs`, including this
        # one, and a planner blind to it reports one fewer removal than the
        # run performs.
        with open(os.path.join(path, '.gitkeep'), 'w'):
            pass


def plan_missing_dirs(project_dir: str, missing: list[str]) -> StepPlan:
    """Plan the expected directories this project is missing.

    Takes `missing` rather than computing it, so the plan and the `DiskFacts`
    the later steps read cannot describe different sets.
    """
    changes = tuple(PlannedChange(f'Would create {d}/', f'Created {d}/')
                    for d in missing)

    def apply() -> tuple[PlannedChange, ...]:
        _make_dirs(project_dir, missing)
        return changes

    return StepPlan('Checking directories...', changes, apply)


def create_missing_dirs(project_dir: str) -> list[str]:
    """Create expected directories that are missing. Returns list of created dirs."""
    missing = missing_expected_dirs(project_dir)
    plan_missing_dirs(project_dir, missing).apply()
    return missing


# ============================================================================
# Junk file cleanup
# ============================================================================

#: Working subdirectories removed when they are empty. Not `EXPECTED_DIRS` —
#: those are created a step earlier and would be deleted again on the same run.
PRUNABLE_WORKING_DIRS: Final = ('enrich', 'coaching', 'backups', 'scenes-setup')


def plan_junk_files(project_dir: str, disk: DiskFacts) -> StepPlan:
    """Plan the transient files and empty directories to remove.

    Reads through `disk`, so `working/logs/.gitkeep` — which step 2 creates and
    this step then deletes — is counted. Asking `os.listdir` at entry reported
    "0 log files" for a run that removes one.
    """
    # (change, the paths it covers) rather than two parallel lists, so `apply`
    # can report per change what it actually removed. A change here stands for
    # several files, and announcing "Removed 5 log files" after removing four
    # is the same class of untruth as announcing a step that did not run.
    groups: list[tuple[PlannedChange, list[str]]] = []

    for reldir, pattern in (('working/evaluations', '.status-*'),
                            ('working/scores', '.markers-*')):
        matched = [f for f in disk.walk_files(reldir)
                   if _matches_glob(os.path.basename(f), pattern)]
        if matched:
            groups.append((PlannedChange(
                f'Would remove {len(matched)} {pattern} files',
                f'Removed {len(matched)} {pattern} files'), matched))

    # `'latest' in <absolute dir path>` is the pre-existing test, kept verbatim:
    # narrowing it to the project-relative path would be more correct and would
    # make a refactor delete files the previous release kept. Out of scope here.
    batch = [f for f in disk.walk_files('working/scores')
             if os.path.basename(f) == '.batch-requests.jsonl'
             and 'latest' not in os.path.dirname(disk.abspath(f))]
    if batch:
        groups.append((PlannedChange(
            f'Would remove {len(batch)} .batch-requests.jsonl files',
            f'Removed {len(batch)} .batch-requests.jsonl files'), batch))

    logs = disk.list_files('working/logs')
    if logs:
        groups.append((PlannedChange(
            f'Would remove {len(logs)} log files',
            f'Removed {len(logs)} log files'), logs))

    # Previously invisible to `--dry-run`, which reported nothing at all about
    # the directories the real run removed.
    for d in PRUNABLE_WORKING_DIRS:
        rel = f'working/{d}'
        if _is_empty_dir(os.path.join(project_dir, 'working', d)):
            groups.append((PlannedChange(f'Would remove empty {rel}/',
                                         f'Removed empty {rel}/'), [rel]))

    def apply() -> tuple[PlannedChange, ...]:
        done: list[PlannedChange] = []
        for change, targets in groups:
            removed = 0
            for rel in targets:
                path = disk.abspath(rel)
                if os.path.isfile(path):
                    os.remove(path)
                    removed += 1
                elif os.path.isdir(path) and not os.listdir(path):
                    os.rmdir(path)
                    removed += 1
            if removed:
                done.append(change)
            if removed != len(targets):
                _warn_vanished(f'{len(targets) - removed} of '
                               f'{len(targets)} targets of "{change.would}"')
        return tuple(done)

    return StepPlan('Cleaning junk files...',
                    tuple(c for c, _ in groups), apply)


def clean_junk_files(project_dir: str) -> None:
    """Remove transient files that should not be committed."""
    plan_junk_files(project_dir, DiskFacts(project_dir)).apply()


def _matches_glob(filename: str, pattern: str) -> bool:
    """Simple glob match for filename patterns like '.status-*'."""
    import fnmatch
    return fnmatch.fnmatch(filename, pattern)


# ============================================================================
# Legacy files and reorganization
# ============================================================================

LEGACY_FILES: Final = ('working/pipeline.yaml', 'working/assemble.py')


def plan_legacy_files(project_dir: str, disk: DiskFacts) -> StepPlan:
    """Plan the retired files to delete."""
    doomed = [(f, PlannedChange(f'Would delete {f}', f'Deleted {f}'))
              for f in LEGACY_FILES if disk.isfile(f)]

    def apply() -> tuple[PlannedChange, ...]:
        done = []
        for f, change in doomed:
            path = os.path.join(project_dir, f)
            if os.path.isfile(path):
                os.remove(path)
                done.append(change)
            else:
                _warn_vanished(f)
        return tuple(done)

    return StepPlan('Checking legacy files...',
                    tuple(c for _, c in doomed), apply)


def delete_legacy_files(project_dir: str) -> None:
    plan_legacy_files(project_dir, DiskFacts(project_dir)).apply()


def plan_loose_files(project_dir: str, disk: DiskFacts) -> StepPlan:
    """Plan the loose `working/recommendations*.md` files to file away.

    The count is of files that will actually move. `--dry-run` used to report
    every glob match, including the ones the real run skips because the
    destination is already taken — an over-report, and the mirror of the
    under-reports this restructuring is about.
    """
    recs_dir = os.path.join(project_dir, 'working', 'recommendations')
    moves: list[tuple[str, str]] = []
    for src in sorted(glob.glob(os.path.join(project_dir, 'working',
                                             'recommendations*.md'))):
        dest = os.path.join(recs_dir, os.path.basename(src))
        if os.path.isfile(src) and not os.path.exists(dest):
            moves.append((src, dest))

    changes: list[PlannedChange] = []
    # `working/recommendations/` is an `EXPECTED_DIRS` entry, so in a full run
    # step 2 has already planned it and `disk.exists` says so — no second
    # announcement. Standalone (`reorganize_loose_files`, no pending entries)
    # this step creates it, and an unannounced `makedirs` is an effect outside
    # `changes`, which is the invariant `StepPlan` exists to hold.
    creates_dest = bool(moves) and not disk.exists('working/recommendations')
    if creates_dest:
        changes.append(PlannedChange('Would create working/recommendations/',
                                     'Created working/recommendations/'))
    if moves:
        changes.append(PlannedChange(
            f'Would move {len(moves)} recommendation files to '
            f'working/recommendations/',
            f'Moved {len(moves)} recommendation files to '
            f'working/recommendations/'))

    def apply() -> tuple[PlannedChange, ...]:
        if moves:
            os.makedirs(recs_dir, exist_ok=True)
        moved = 0
        for src, dest in moves:
            if os.path.isfile(src) and not os.path.exists(dest):
                shutil.move(src, dest)
                moved += 1
            else:
                _warn_vanished(os.path.relpath(src, project_dir))
        if moved == len(moves):
            return tuple(changes)
        return tuple(changes[:1]) if creates_dest else ()

    return StepPlan('Reorganizing loose files...', tuple(changes), apply)


def reorganize_loose_files(project_dir: str) -> None:
    plan_loose_files(project_dir, DiskFacts(project_dir)).apply()


# ============================================================================
# Pipeline CSV migration
# ============================================================================

def plan_pipeline_csv(project_dir: str) -> StepPlan:
    """Plan the `working/pipeline.csv` header migration.

    One computation for both modes. `--dry-run` used to compare the header
    itself while the real run rebuilt every row from it — the same predicate
    written twice, which is how they drift.
    """
    title = 'Checking pipeline.csv...'
    csv_path = os.path.join(project_dir, 'working', 'pipeline.csv')
    if not os.path.isfile(csv_path):
        return StepPlan(title, (), _no_op)

    try:
        with open(csv_path, encoding='utf-8') as f:
            lines = f.readlines()
    except (OSError, UnicodeDecodeError) as exc:
        log(f'WARNING: could not read working/pipeline.csv '
            f'({type(exc).__name__}: {exc}). Skipping its migration; the rest '
            f'of cleanup still runs.')
        return StepPlan(title, (), _no_op)

    new_lines = _migrated_pipeline_lines(lines)
    if new_lines is None:
        return StepPlan(title, (), _no_op)

    change = PlannedChange('Would add missing columns to pipeline.csv',
                           'Added missing columns to pipeline.csv')

    def apply() -> tuple[PlannedChange, ...]:
        with open(csv_path, 'w', encoding='utf-8') as f:
            f.writelines(new_lines)
        return (change,)

    return StepPlan(title, (change,), apply)


def migrate_pipeline_csv(project_dir: str) -> None:
    plan_pipeline_csv(project_dir).apply()


def _migrated_pipeline_lines(lines: list[str]) -> list[str] | None:
    """The rewritten pipeline.csv, or None when the header is already correct."""
    if not lines:
        return None

    header = lines[0].strip()
    if header == PIPELINE_EXPECTED:
        return None

    old_cols = header.split('|')
    exp_cols = PIPELINE_EXPECTED.split('|')
    old_pos = {col: i for i, col in enumerate(old_cols)}

    new_lines = [PIPELINE_EXPECTED + '\n']
    for line in lines[1:]:
        vals = line.strip().split('|')
        new_vals = []
        for col in exp_cols:
            if col in old_pos and old_pos[col] < len(vals):
                new_vals.append(vals[old_pos[col]])
            else:
                new_vals.append('')
        new_lines.append('|'.join(new_vals) + '\n')

    return new_lines


# ============================================================================
# Pipeline review deduplication
# ============================================================================

def plan_pipeline_reviews(project_dir: str) -> StepPlan:
    """Plan the same-day pipeline reviews to drop, keeping the latest per day.

    `--dry-run` used to announce "Would deduplicate pipeline reviews" on every
    run, including on a project with no reviews at all — the over-reporting
    direction, but still a claim nothing checked.
    """
    doomed: list[str] = []
    reviews_dir = os.path.join(project_dir, 'working', 'reviews')
    if os.path.isdir(reviews_dir):
        files = sorted(glob.glob(os.path.join(reviews_dir,
                                              'pipeline-review-*.md')),
                       reverse=True)
        prev_date = ''
        for f in files:
            m = re.match(r'pipeline-review-(\d+)-', os.path.basename(f))
            if not m:
                continue
            if m.group(1) == prev_date:
                doomed.append(f)
            else:
                prev_date = m.group(1)

    def apply() -> tuple[PlannedChange, ...]:
        removed = 0
        for f in doomed:
            if os.path.isfile(f):
                os.remove(f)
                removed += 1
        if removed != len(doomed):
            _warn_vanished(f'{len(doomed) - removed} pipeline review(s)')
        return changes if removed else ()

    changes: tuple[PlannedChange, ...] = ()
    if doomed:
        changes = (PlannedChange(
            f'Would remove {len(doomed)} duplicate pipeline review(s), '
            f'keeping the latest per day',
            f'Removed {len(doomed)} duplicate pipeline review(s), '
            f'keeping the latest per day'),)
    return StepPlan('Deduplicating pipeline reviews...', changes, apply)


def dedup_pipeline_reviews(project_dir: str) -> None:
    plan_pipeline_reviews(project_dir).apply()


# ============================================================================
# storyforge.yaml migration
# ============================================================================

class YamlMigrationPlan(NamedTuple):
    """What the storyforge.yaml migration would do to one file's bytes.

    `changed` is `new_content != original` rather than a flag the branches set,
    for the reason #314 gave: a flag drifts out of step with the code above it,
    and this one did — set unconditionally, so every run rewrote the file.

    `reasons` is descriptive only. It enriches the `--dry-run` line and must
    never decide anything, or it becomes that flag again under a new name.
    """
    original: str
    new_content: str
    reasons: tuple[str, ...]

    @property
    def changed(self) -> bool:
        return self.new_content != self.original


def plan_yaml_migration(content: str, disk: DiskFacts) -> YamlMigrationPlan:
    """Add missing sections and correct artifact flags. Pure.

    Takes the file's bytes and a `DiskFacts`, touches neither, and returns the
    new bytes plus what changed and why. Both modes consume this one
    computation: `--dry-run` renders `plan.reasons`, the real run writes
    `plan.new_content` (#317). They cannot disagree, where a preview that
    re-ran this against a sandboxed copy of the project disagreed twice — once
    because the sandbox lacked `manuscript/`, and once because it could not
    reproduce the directory an earlier step creates.

    `disk` answers the `exists:` questions, and answers them the way the real
    run's *later* steps will see the filesystem. Pure with respect to the
    filesystem — it opens nothing and writes nothing, and every disk question
    goes through the injected object, which is what lets the tests exercise it
    with no filesystem at all. Not pure in the absolute sense: the
    `chapter_map`-with-no-`artifacts:`-anchor branch logs a WARNING, because
    that is the branch that would otherwise delete an entry silently.

    **Writes only when something changed, and leaves line endings alone**
    (#314) — both properties belong to the caller now, but they are why the
    patterns below tolerate CRLF and why inserted blocks use the file's own
    newline. `^artifacts:\\n` does not match `artifacts:\\r\\n`, and a text-mode
    read used to hide that by normalizing first, so a CRLF project would have
    silently stopped receiving migrations. Emitting LF into a CRLF file would
    leave it mixed, which is worse than either policy applied consistently.

    The standing posture is to preserve what the author has and report it
    instead: `_check_crlf` covers `storyforge.yaml`, so an author who wants LF
    is told rather than converted behind their back.
    """
    original = content
    reasons: list[str] = []
    nl = common.detect_newline(content)

    # Move misplaced chapter_map to under artifacts
    if re.search(r'^chapter_map:', content, re.MULTILINE):
        # Extract values
        block_match = re.search(
            r'^chapter_map:\r?\n((?:  .+\r?\n)*)', content, re.MULTILINE
        )
        if block_match:
            block_text = block_match.group(1)
            cm_exists = ''
            cm_path = ''
            cm_updated = ''
            for line in block_text.splitlines():
                m = re.match(r'\s+exists:\s*(.*)', line)
                if m:
                    cm_exists = m.group(1).strip()
                m = re.match(r'\s+path:\s*(.*)', line)
                if m:
                    cm_path = m.group(1).strip()
                m = re.match(r'\s+updated:\s*(.*)', line)
                if m:
                    cm_updated = m.group(1).strip()

            # The relocation is all-or-nothing, because the removal and the
            # re-insert are two independent regexes and the second can fail.
            # With a top-level `chapter_map:` and no `artifacts:` block, the
            # removal ran, the insert found no anchor, and the entry — path,
            # dates and all — was deleted and written to disk. Silent data loss
            # in `cleanup`, on a file whose silent truncation was #276, in the
            # one branch no test in the suite reached.
            relocated = re.sub(r'^chapter_map:\r?\n(?:  .+\r?\n)*', '', content,
                               flags=re.MULTILINE)
            # Remove consecutive blank lines
            relocated = re.sub(r'(?:\r?\n){3,}', nl * 2, relocated)

            # `cm_path` is author text from the file, so it must not reach
            # `re.sub` as part of a replacement *template*, where a backslash
            # reads as a group reference and either raises or corrupts. A
            # function replacement takes the string literally. (The sibling
            # insert below builds its path from a hardcoded list and could not
            # hit this; this is the site that can.)
            insert_block = nl.join([
                '  chapter_map:',
                f'    exists: {cm_exists}',
                f'    path: {cm_path}',
                f'    updated: {cm_updated}',
                '',
            ])
            relocated, inserted = re.subn(
                r'(^artifacts:\r?\n)',
                lambda m: m.group(1) + insert_block,
                relocated,
                flags=re.MULTILINE,
            )
            if inserted:
                content = relocated
                reasons.append('move chapter_map under artifacts')
            else:
                # No anchor to move it under. Leaving a misplaced top-level
                # entry in place is harmless — nothing reads it — whereas
                # deleting it destroys the only record of the path. The author is
                # told to add the block by `_artifact_span_failure`.
                log('WARNING: storyforge.yaml has a top-level `chapter_map:` '
                    'but no `artifacts:` block to move it under, so it was left '
                    'where it is. Add an `artifacts:` block and re-run.')

    # Add missing sections
    if not re.search(r'^scene_extensions:', content, re.MULTILINE):
        content += nl.join(['', 'scene_extensions: []', ''])
        reasons.append('add scene_extensions')

    if not re.search(r'^evaluation:', content, re.MULTILINE):
        content += nl.join(['', 'evaluation:', '  custom_evaluators: []', ''])
        reasons.append('add evaluation')

    if not re.search(r'^production:', content, re.MULTILINE) and not re.search(r'^# production:', content, re.MULTILINE):
        content += nl.join(['', '# production:', '#   author: ""',
                            '#   language: en', '#   scene_break: ornamental',
                            '#   default_heading: numbered-titled', ''])
        reasons.append('add production')

    if not re.search(r'^parts:', content, re.MULTILINE) and not re.search(r'^# parts:', content, re.MULTILINE):
        content += nl.join(['', '# parts:', '#   - number: 1',
                            '#     title: "Part One"', ''])
        reasons.append('add parts')

    # Add missing artifact entries for files on disk
    artifact_files = [
        ('characters', 'reference/characters.csv'),
        ('locations', 'reference/locations.csv'),
        ('threads', 'reference/threads.csv'),
        ('motif_taxonomy', 'reference/motif-taxonomy.csv'),
        ('scene_intent', 'reference/scene-intent.csv'),
        ('title_development', 'reference/title-development.md'),
    ]
    added_artifacts: list[str] = []
    for aid, apath in artifact_files:
        if disk.isfile(apath):
            if f'  {aid}:' not in content:
                insert = nl.join([
                    f'  {aid}:',
                    '    exists: true',
                    f'    path: {apath}',
                    '    updated:',
                    '',
                ])
                # A function replacement for consistency with the `cm_path` site
                # above, which is the one that can actually carry a backslash;
                # `apath` here comes from the hardcoded list.
                content, inserted = re.subn(
                    r'(^artifacts:\r?\n)',
                    lambda m, ins=insert: m.group(1) + ins,
                    content,
                    flags=re.MULTILINE,
                )
                if inserted:
                    added_artifacts.append(aid)
    if added_artifacts:
        reasons.append(f'add artifact entries for {", ".join(added_artifacts)}')

    # Fix exists flags based on disk
    def _fix_exists(match):
        block = match.group(0)
        path_match = re.search(r'path:\s*(.+)', block)
        if not path_match:
            return block
        apath = path_match.group(1).strip().strip('"')
        if disk.exists(apath):
            block = re.sub(r'exists: false', 'exists: true', block)
        else:
            block = re.sub(r'exists: true', 'exists: false', block)
        return block

    before_flags = content
    content = re.sub(
        r'^  [a-z_]+:\r?\n(?:    (?:exists|path|updated):.*\r?\n)+',
        _fix_exists,
        content,
        flags=re.MULTILINE,
    )
    if content != before_flags:
        reasons.append('correct artifact exists: flags')

    return YamlMigrationPlan(original, content, tuple(reasons))


def read_and_plan_yaml_migration(project_dir: str,
                                 disk: DiskFacts) -> YamlMigrationPlan | None:
    """Read `storyforge.yaml` and plan its migration, or None if it can't be.

    Guarded, `encoding=` stated, and reported rather than raised. Nothing above
    it handles anything — not `plan_cleanup`, not `main`, and not
    `__main__._dispatch` — so a latin-1 or unreadable storyforge.yaml took down
    the whole command — including the read-only report, which is `cleanup`'s actual
    product. Migration is optional tidying; the report is not. That inverts
    #313's call for `cmd_assemble`, where the expensive work came first.
    """
    yaml_path = os.path.join(project_dir, 'storyforge.yaml')
    if not os.path.isfile(yaml_path):
        return None

    try:
        with open(yaml_path, encoding='utf-8', newline='') as f:
            content = f.read()
    except (OSError, UnicodeDecodeError) as exc:
        log(f'WARNING: could not read storyforge.yaml to migrate it '
            f'({type(exc).__name__}: {exc}). Skipping the migration; the rest '
            f'of cleanup still runs, and `_check_yaml_scalars` reports the same '
            f'file as unreadable.')
        return None

    return plan_yaml_migration(content, disk)


def apply_yaml_migration(project_dir: str,
                         plan: YamlMigrationPlan) -> bool:
    """Write `plan.new_content` if it differs from what was read.

    Returns whether the file was written. The `bool` is what stops `main` from
    announcing "Migrated storyforge.yaml" underneath its own "could not write
    storyforge.yaml" WARNING — the write failure is swallowed here by design
    (the report matters more than the migration), so the caller has to be told.
    """
    if not plan.changed:
        return False
    yaml_path = os.path.join(project_dir, 'storyforge.yaml')
    # Temp file plus `os.replace`, matching `illustrations`' ingest: a plain
    # `open(..., 'w')` truncates before it writes, so a `PermissionError` or a
    # full disk mid-write leaves a half-written storyforge.yaml. Truncating
    # this file is #276 exactly, and a partial write is the worse version of
    # it because there is no previous content left to compare against.
    tmp_path = yaml_path + '.tmp'
    try:
        with open(tmp_path, 'w', encoding='utf-8', newline='') as f:
            f.write(plan.new_content)
        os.replace(tmp_path, yaml_path)
        return True
    except OSError as exc:
        log(f'WARNING: could not write storyforge.yaml '
            f'({type(exc).__name__}: {exc}). The file is unchanged.')
        if os.path.exists(tmp_path):
            try:
                os.remove(tmp_path)
            except OSError:
                pass
        return False


def plan_storyforge_yaml(project_dir: str, disk: DiskFacts) -> StepPlan:
    """The storyforge.yaml migration as a cleanup step."""
    title = 'Checking storyforge.yaml...'
    plan = read_and_plan_yaml_migration(project_dir, disk)
    if plan is None or not plan.changed:
        return StepPlan(title, (), _no_op)

    detail = '; '.join(plan.reasons) if plan.reasons else 'rewrite the file'
    change = PlannedChange(f'Would migrate storyforge.yaml ({detail})',
                           f'Migrated storyforge.yaml ({detail})')

    def apply() -> tuple[PlannedChange, ...]:
        return (change,) if apply_yaml_migration(project_dir, plan) else ()

    return StepPlan(title, (change,), apply)


def migrate_storyforge_yaml(project_dir: str) -> None:
    """Add missing sections and correct artifact flags, in place.

    The read-plan-write composition, kept as one entry point for callers that
    just want the migration performed. `disk_root` is gone with the sandbox
    that needed it: no production function should take a parameter that exists
    only to let a caller misrepresent the filesystem (#317).
    """
    plan = read_and_plan_yaml_migration(project_dir, DiskFacts(project_dir))
    if plan is not None:
        apply_yaml_migration(project_dir, plan)


# ============================================================================
# CSV Schema Report
# ============================================================================

def report_csv_schema(project_dir: str) -> list[str]:
    """Check all expected CSV files for existence and column completeness.

    Detects project medium (novel vs graphic-novel) and applies the appropriate
    column schemas. GN-specific columns are not flagged as extra; optional GN
    registry files that are absent are not flagged as missing.

    Returns a list of issue strings (MISSING_CSV, MISSING_COLUMN, EXTRA_COLUMN).
    """
    medium = get_medium(project_dir)
    is_gn = (medium == 'graphic-novel')

    # Build the effective schema for this project: start with base, apply GN overrides
    effective_schemas = dict(EXPECTED_CSV_SCHEMAS)
    optional_files: set[str] = set(ALWAYS_OPTIONAL_CSV_FILES)
    if is_gn:
        effective_schemas.update(GN_CSV_SCHEMA_OVERRIDES)
        optional_files |= GN_OPTIONAL_CSV_FILES

    issues = []

    for rel_path, expected_cols in effective_schemas.items():
        # Skip files that are optional for this medium and not present on disk
        if rel_path in optional_files and not os.path.isfile(os.path.join(project_dir, rel_path)):
            continue

        csv_path = os.path.join(project_dir, rel_path)

        if not os.path.isfile(csv_path):
            issues.append(f'MISSING_CSV:{rel_path}')
            continue

        # Guarded, `encoding=` stated. This read was unguarded and killed
        # `build_cleanup_report` — the single finding collector — on a latin-1
        # or unreadable CSV, so no `working/cleanup-report.csv` was written and
        # `skills/forge/SKILL.md`'s `status=pending` scan read the project as
        # clean. `plan_pipeline_csv`'s handler promised "the rest of cleanup
        # still runs" over exactly that crash, because `working/pipeline.csv`
        # is a registered schema and lands here two steps later. Same shape as
        # the `ill.sha256_of` regression (#298): `UnicodeDecodeError` is a
        # `ValueError`, not an `OSError`, so both are named.
        try:
            with open(csv_path, encoding='utf-8') as f:
                first_line = f.readline().strip()
        except (OSError, UnicodeDecodeError) as exc:
            issues.append(f'UNREADABLE_CSV:{rel_path}:{type(exc).__name__}')
            continue

        if not first_line:
            issues.append(f'EMPTY_CSV:{rel_path}')
            continue

        actual_cols = [c.strip() for c in first_line.split('|')]
        expected_set = set(expected_cols)
        actual_set = set(actual_cols)

        optional_cols = OPTIONAL_CSV_COLUMNS.get(rel_path, set())
        for col in expected_cols:
            if col not in actual_set and col not in optional_cols:
                issues.append(f'MISSING_COLUMN:{rel_path}:{col}')

        for col in actual_cols:
            if col not in expected_set:
                issues.append(f'EXTRA_COLUMN:{rel_path}:{col}')

    return issues


# ============================================================================
# CSV Integrity Report
# ============================================================================

def _read_csv_column(csv_path: str, column: str) -> list[str]:
    """Read a single column from a pipe-delimited CSV by name.

    Returns a list of non-empty stripped values. Returns [] if the file
    doesn't exist or the column isn't found.
    """
    if not os.path.isfile(csv_path):
        return []
    # Guarded for the reason `report_csv_schema`'s read is, and silent for a
    # reason that one is not: every file this is called on is a registered
    # schema, so the unreadable finding is already emitted there. Returning []
    # here keeps `report_csv_integrity` from crashing the collector without
    # adding a second finding about one file.
    try:
        with open(csv_path, encoding='utf-8') as f:
            lines = f.readlines()
    except (OSError, UnicodeDecodeError):
        return []
    if not lines:
        return []
    header = [h.strip() for h in lines[0].strip().split('|')]
    if column not in header:
        return []
    idx = header.index(column)
    values = []
    for line in lines[1:]:
        parts = line.strip().split('|')
        if idx < len(parts) and parts[idx].strip():
            values.append(parts[idx].strip())
    return values


def report_csv_integrity(project_dir: str) -> list[str]:
    """Check CSV integrity. Returns list of issue strings."""
    issues = []
    meta_csv = os.path.join(project_dir, 'reference', 'scenes.csv')
    intent_csv = os.path.join(project_dir, 'reference', 'scene-intent.csv')
    chapter_csv = os.path.join(project_dir, 'reference', 'chapter-map.csv')
    chars_csv = os.path.join(project_dir, 'reference', 'characters.csv')
    scenes_dir = os.path.join(project_dir, 'scenes')

    # Scene files vs metadata
    if os.path.isfile(meta_csv) and os.path.isdir(scenes_dir):
        meta_ids = set(_read_csv_column(meta_csv, 'id'))
        file_ids = set()
        for f in os.listdir(scenes_dir):
            if f.endswith('.md'):
                file_ids.add(f[:-3])
        for fid in sorted(file_ids - meta_ids):
            issues.append(f'ORPHAN_FILE:{fid}')
        for mid in sorted(meta_ids - file_ids):
            issues.append(f'ORPHAN_META:{mid}')

    # Metadata vs intent
    if os.path.isfile(meta_csv) and os.path.isfile(intent_csv):
        meta_ids = set(_read_csv_column(meta_csv, 'id'))
        intent_ids = set(_read_csv_column(intent_csv, 'id'))
        for mid in sorted(meta_ids - intent_ids):
            issues.append(f'MISSING_INTENT:{mid}')
        for iid in sorted(intent_ids - meta_ids):
            issues.append(f'EXTRA_INTENT:{iid}')

    # Chapter map references
    if os.path.isfile(chapter_csv) and os.path.isfile(meta_csv):
        meta_ids = set(_read_csv_column(meta_csv, 'id'))
        for scenes_cell in _read_csv_column(chapter_csv, 'scenes'):
            for sid in scenes_cell.split(';'):
                sid = sid.strip()
                if sid and sid not in meta_ids:
                    issues.append(f'BAD_CHAPTER_REF:{sid}')

    # Sequence gaps
    if os.path.isfile(meta_csv):
        seqs = _read_csv_column(meta_csv, 'seq')
        needs_renumber = False
        prev = 0
        for s in sorted(seqs, key=lambda x: float(x) if re.match(r'^[\d.]+$', x) else 0):
            if '.' in s:
                needs_renumber = True
            elif s.isdigit():
                val = int(s)
                if val > prev + 1:
                    needs_renumber = True
                prev = val
        if needs_renumber:
            issues.append('SEQ_NEEDS_RENUMBER:gaps or non-integer seq values found')

    # Unknown characters — build known set from id + aliases columns
    if os.path.isfile(intent_csv) and os.path.isfile(chars_csv):
        known = set()
        for col in ('id', 'aliases'):
            for val in _read_csv_column(chars_csv, col):
                for name in val.split(';'):
                    name = name.strip()
                    if name:
                        known.add(name)

        used = set()
        for val in _read_csv_column(intent_csv, 'characters'):
            for name in val.split(';'):
                name = name.strip()
                if name:
                    used.add(name)
        for name in sorted(used - known):
            issues.append(f'UNKNOWN_CHARACTER:{name}')

    return issues


# ============================================================================
# Unexpected Files Report
# ============================================================================

def report_unexpected_files(project_dir: str) -> list[str]:
    """Report unexpected files and directories. Returns list of issue strings."""
    issues = []
    allowed_top_dirs = set(EXPECTED_TOP_DIRS)
    if get_medium(project_dir) == 'graphic-novel':
        allowed_top_dirs.add('pages')

    # Top-level dirs
    for entry in sorted(os.listdir(project_dir)):
        path = os.path.join(project_dir, entry)
        if os.path.isdir(path) and entry not in allowed_top_dirs:
            issues.append(f'UNEXPECTED_DIR:{entry}')
        elif os.path.isfile(path) and entry not in EXPECTED_TOP_FILES:
            issues.append(f'UNEXPECTED_FILE:{entry}')

    # Working subdirs
    working = os.path.join(project_dir, 'working')
    if os.path.isdir(working):
        for entry in sorted(os.listdir(working)):
            path = os.path.join(working, entry)
            if os.path.isdir(path) and entry not in EXPECTED_WORKING_DIRS:
                issues.append(f'UNEXPECTED_DIR:working/{entry}')
            elif os.path.isfile(path) and entry not in EXPECTED_WORKING_FILES:
                issues.append(f'UNEXPECTED_FILE:working/{entry}')

    return issues


# ============================================================================
# Scene file cleanup
# ============================================================================

def _scene_files_to_clean(project_dir: str) -> list[tuple[str, str]]:
    """(filename, cleaned text) for every scene file carrying artifacts.

    Removes scene markers (=== SCENE: id ===), leading H1/H2 title headers,
    and trailing Continuity Tracker Update blocks.
    """
    scenes_dir = os.path.join(project_dir, 'scenes')
    if not os.path.isdir(scenes_dir):
        return []

    dirty: list[tuple[str, str]] = []
    for filename in sorted(os.listdir(scenes_dir)):
        if not filename.endswith('.md'):
            continue
        # The one planner without this guard, while three siblings had it and
        # cited #298. It matters more here than there: `plan_cleanup` builds
        # every plan up front, so one latin-1 scene file under `--scenes` cost
        # all nine steps and the report — where before the planner the run
        # still created directories and migrated the yaml before dying.
        try:
            with open(os.path.join(scenes_dir, filename),
                      encoding='utf-8') as f:
                original = f.read()
        except (OSError, UnicodeDecodeError) as exc:
            log(f'WARNING: could not read scenes/{filename} '
                f'({type(exc).__name__}: {exc}), so it was not checked for '
                f'writing-agent artifacts.')
            continue

        cleaned = original
        extracted = extract_single_scene(cleaned)
        if extracted is not None:
            cleaned = extracted
        cleaned = clean_scene_content(cleaned)

        if cleaned != original:
            dirty.append((filename, cleaned))
    return dirty


def plan_scene_files(project_dir: str) -> StepPlan:
    """Plan the writing-agent artifacts to strip from scene files.

    The one step that reports a clean result out loud, hence the `summary`:
    it runs only under `--scenes`, so an author who asked for it is owed an
    answer either way.
    """
    dirty = _scene_files_to_clean(project_dir)
    changes = tuple(PlannedChange(f'Would clean: {name}', f'Cleaned: {name}')
                    for name, _ in dirty)

    def apply() -> tuple[PlannedChange, ...]:
        for filename, cleaned in dirty:
            with open(os.path.join(project_dir, 'scenes', filename), 'w',
                      encoding='utf-8') as f:
                f.write(cleaned)
        return changes

    if dirty:
        summary = PlannedChange(
            f'Would clean {len(dirty)} scene file(s)',
            f'Cleaned {len(dirty)} scene file(s)')
    else:
        summary = PlannedChange('All scene files are clean.',
                                'All scene files are clean.')

    return StepPlan('Cleaning scene files...', changes, apply, summary)


def clean_scene_files(project_dir: str, dry_run: bool = False,
                      verbose: bool = False) -> int:
    """Strip writing-agent artifacts from scene files.

    Returns the number of files that were (or would be) modified.
    """
    plan = plan_scene_files(project_dir)
    for change in plan.changes:
        if verbose or dry_run:
            log(f'  {change.would if dry_run else change.did}')
    if not dry_run:
        plan.apply()
    return len(plan.changes)


# ============================================================================
# Argument parsing
# ============================================================================

def parse_args(argv):
    parser = argparse.ArgumentParser(
        prog='storyforge cleanup',
        description='Clean up and migrate a Storyforge novel project.',
    )
    parser.add_argument('--dry-run', action='store_true',
                        help='Report what would change without modifying anything')
    parser.add_argument('--verbose', action='store_true',
                        help='Detailed output for each step')
    parser.add_argument('--scenes', action='store_true',
                        help='Strip writing-agent artifacts (title headers, '
                             'continuity blocks, scene markers) from scene files')
    parser.add_argument('--csv', action='store_true',
                        help='Run only the CSV integrity report (schema '
                             'validation, row checks, unexpected files)')
    return parser.parse_args(argv)


# ============================================================================
# Main
# ============================================================================

def _classify_issue(issue: str, rename_pairs: dict[str, list[tuple[str, str]]]) -> dict | None:
    """Convert a raw issue string into a structured finding dict.

    Returns None for issues that should be suppressed (e.g. the EXTRA_COLUMN
    side of a rename pair).

    Each dict has: type, file, detail, action, command (optional), severity.
    - severity: 'error' (breaks pipeline), 'warning' (should fix),
                'info' (informational only)
    """
    if issue.startswith('MISSING_CSV:'):
        path = issue.split(':', 1)[1]
        if path.startswith('working/'):
            return {
                'type': 'missing_csv', 'file': path,
                'detail': f'{path} does not exist',
                'action': 'Will be created automatically on first use',
                'severity': 'info',
            }
        return {
            'type': 'missing_csv', 'file': path,
            'detail': f'{path} does not exist',
            'action': f'Copy from templates/ or run storyforge elaborate',
            'command': f'cp templates/{path.removeprefix("reference/")} {path}',
            'severity': 'warning',
        }

    if issue.startswith('UNREADABLE_CSV:'):
        _, path, exc_name = issue.split(':', 2)
        return {
            'type': 'unreadable_csv', 'file': path,
            'detail': csv_safe(f'{path} could not be read ({exc_name}), so '
                               f'its schema was not checked'),
            'action': 'Check the file\'s permissions and encoding — Storyforge '
                      'reads CSVs as UTF-8',
            'severity': 'error',
        }

    if issue.startswith('EMPTY_CSV:'):
        path = issue.split(':', 1)[1]
        return {
            'type': 'empty_csv', 'file': path,
            'detail': f'{path} is empty (no header row)',
            'action': 'Restore header from templates/',
            'severity': 'error',
        }

    if issue.startswith('MISSING_COLUMN:'):
        _, path, col = issue.split(':', 2)
        pairs = rename_pairs.get(path, [])
        for missing, extra in pairs:
            if col == missing:
                return {
                    'type': 'rename_column', 'file': path,
                    'detail': f'Column "{extra}" should be "{missing}"',
                    'action': f'Rename column "{extra}" to "{missing}" in header',
                    'rename_from': extra, 'rename_to': missing,
                    'severity': 'warning',
                }
        return {
            'type': 'missing_column', 'file': path, 'column': col,
            'detail': f'{path} is missing column "{col}"',
            'action': f'Add "{col}" to header and empty values to existing rows',
            'severity': 'warning',
        }

    if issue.startswith('EXTRA_COLUMN:'):
        _, path, col = issue.split(':', 2)
        pairs = rename_pairs.get(path, [])
        for missing, extra in pairs:
            if col == extra:
                return None  # Covered by the rename_column finding
        return {
            'type': 'extra_column', 'file': path, 'column': col,
            'detail': f'{path} has unexpected column "{col}"',
            'action': f'Verify if "{col}" should be removed or added to schema',
            'severity': 'info',
        }

    if issue.startswith('ORPHAN_FILE:'):
        sid = issue.split(':', 1)[1]
        return {
            'type': 'orphan_file', 'file': f'scenes/{sid}.md', 'scene_id': sid,
            'detail': f'scenes/{sid}.md has no metadata row',
            'action': 'Extract metadata or remove scene file',
            'command': f'storyforge extract --scenes {sid}',
            'severity': 'warning',
        }

    if issue.startswith('ORPHAN_META:'):
        sid = issue.split(':', 1)[1]
        return {
            'type': 'orphan_meta', 'file': 'reference/scenes.csv',
            'scene_id': sid,
            'detail': f'"{sid}" has metadata but no scene file',
            'action': f'Remove rows for "{sid}" from CSVs or create scenes/{sid}.md',
            'severity': 'warning',
        }

    if issue.startswith('MISSING_INTENT:'):
        sid = issue.split(':', 1)[1]
        return {
            'type': 'missing_intent', 'file': 'reference/scene-intent.csv',
            'scene_id': sid,
            'detail': f'"{sid}" is in scenes.csv but not scene-intent.csv',
            'action': 'Fill intent gaps',
            'command': 'storyforge hone --domain gaps',
            'severity': 'warning',
        }

    if issue.startswith('EXTRA_INTENT:'):
        sid = issue.split(':', 1)[1]
        return {
            'type': 'extra_intent', 'file': 'reference/scene-intent.csv',
            'scene_id': sid,
            'detail': f'"{sid}" is in scene-intent.csv but not scenes.csv',
            'action': f'Remove the row from scene-intent.csv or add "{sid}" to scenes.csv',
            'severity': 'warning',
        }

    if issue.startswith('BAD_CHAPTER_REF:'):
        sid = issue.split(':', 1)[1]
        return {
            'type': 'bad_chapter_ref', 'file': 'reference/chapter-map.csv',
            'scene_id': sid,
            'detail': f'chapter-map.csv references "{sid}" which doesn\'t exist',
            'action': 'Update the chapter map to remove or replace the reference',
            'severity': 'error',
        }

    if issue.startswith('SEQ_NEEDS_RENUMBER:'):
        return {
            'type': 'seq_needs_renumber', 'file': 'reference/scenes.csv',
            'detail': 'Sequence has gaps or non-integer values',
            'action': 'Renumber scene sequences',
            'command': 'storyforge scenes-setup --renumber',
            'severity': 'warning',
        }

    if issue.startswith('UNKNOWN_CHARACTER:'):
        name = issue.split(':', 1)[1]
        return {
            'type': 'unknown_character', 'file': 'reference/characters.csv',
            'character': name,
            'detail': f'"{name}" appears in scene-intent.csv but not characters.csv',
            'action': 'Normalize character registries',
            'command': 'storyforge hone --domain registries',
            'severity': 'warning',
        }

    if issue.startswith('UNEXPECTED_DIR:'):
        path = issue.split(':', 1)[1]
        return {
            'type': 'unexpected_dir', 'file': path,
            'detail': f'{path}/ is not expected',
            'action': 'Review manually; may be leftover from an old version',
            'severity': 'info',
        }

    if issue.startswith('UNEXPECTED_FILE:'):
        path = issue.split(':', 1)[1]
        return {
            'type': 'unexpected_file', 'file': path,
            'detail': f'{path} is not expected',
            'action': 'Review manually; may be leftover from an old version',
            'severity': 'info',
        }

    return {'type': 'unknown', 'detail': issue, 'action': issue, 'severity': 'info'}


def _detect_rename_pairs(issues: list[str]) -> dict[str, list[tuple[str, str]]]:
    """Detect MISSING_COLUMN + EXTRA_COLUMN on the same file as rename candidates.

    Returns {path: [(missing_col, extra_col), ...]} for files where the count
    of missing and extra columns match (suggesting renames rather than
    additions/deletions).
    """
    from collections import defaultdict
    missing: dict[str, list[str]] = defaultdict(list)
    extra: dict[str, list[str]] = defaultdict(list)

    for issue in issues:
        if issue.startswith('MISSING_COLUMN:'):
            _, path, col = issue.split(':', 2)
            missing[path].append(col)
        elif issue.startswith('EXTRA_COLUMN:'):
            _, path, col = issue.split(':', 2)
            extra[path].append(col)

    pairs: dict[str, list[tuple[str, str]]] = {}
    for path in missing:
        if path in extra and len(missing[path]) == len(extra[path]):
            pairs[path] = list(zip(missing[path], extra[path]))
    return pairs


def _check_scene_artifacts(project_dir: str) -> list[dict]:
    """Check scene files for writing-agent artifacts without modifying them.

    Returns a list of finding dicts for scenes that need cleaning.
    """
    scenes_dir = os.path.join(project_dir, 'scenes')
    if not os.path.isdir(scenes_dir):
        return []

    findings: list[dict] = []
    unreadable: list[str] = []
    dirty_count = 0
    for filename in sorted(os.listdir(scenes_dir)):
        if not filename.endswith('.md'):
            continue
        filepath = os.path.join(scenes_dir, filename)
        try:
            with open(filepath, encoding='utf-8') as f:
                original = f.read()
        except (OSError, UnicodeDecodeError) as exc:
            # Reported, not skipped: this runs inside `build_cleanup_report`,
            # the single finding collector, so an unguarded read here took the
            # whole report down — and a silent `continue` would say the scene
            # was checked and clean.
            unreadable.append(f'{filename} ({type(exc).__name__}: {exc})')
            continue

        cleaned = original
        extracted = extract_single_scene(cleaned)
        if extracted is not None:
            cleaned = extracted
        cleaned = clean_scene_content(cleaned)

        if cleaned != original:
            dirty_count += 1

    if dirty_count > 0:
        findings.append({
            'type': 'scene_artifacts', 'file': 'scenes/',
            'category': 'scenes',
            'detail': f'{dirty_count} scene file(s) contain writing-agent artifacts '
                      f'(title headers, continuity blocks, or scene markers)',
            'action': 'Strip artifacts from scene files',
            'command': 'storyforge cleanup --scenes',
            'severity': 'warning',
        })
    if unreadable:
        findings.append({
            'type': 'unreadable_scene', 'file': 'scenes/',
            'category': 'scenes',
            'detail': csv_safe(
                f'{len(unreadable)} scene file(s) could not be read, so they '
                f'were not checked for writing-agent artifacts: '
                f'{", ".join(unreadable[:5])}'
                f'{"..." if len(unreadable) > 5 else ""}'),
            'action': 'Check the files\' permissions and encoding — '
                      'Storyforge reads scenes as UTF-8',
            'severity': 'warning',
        })
    return findings


def _check_stale_ledger(project_dir: str) -> list[dict]:
    """Detect the #205 stale ledger at working/working/costs/ledger.csv.

    Pre-fix score runs silently wrote cost entries to a path one
    directory level too deep. After the fix lands, `print_summary`
    only reads the correct path — historical cost data is invisible
    unless surfaced. Cleanup flags the stale file so the author can
    merge / archive / delete it deliberately. The detection has zero
    impact on the corrected ledger; it's a one-time post-fix
    reconciliation prompt.
    """
    stale = os.path.join(project_dir, 'working', 'working',
                          'costs', 'ledger.csv')
    if not os.path.isfile(stale):
        return []
    correct = os.path.join(project_dir, 'working', 'costs', 'ledger.csv')
    correct_exists = os.path.isfile(correct)
    if correct_exists:
        detail = (
            'Stale cost ledger at working/working/costs/ledger.csv from '
            'pre-#205 score runs. The correct ledger at '
            'working/costs/ledger.csv is in use. Historical cost data '
            'in the stale file is invisible to `costs.print_summary` '
            'until merged.'
        )
        action = (
            'Merge rows from working/working/costs/ledger.csv into '
            'working/costs/ledger.csv (skip the duplicate header row), '
            'then remove the stale file and the empty parent directory.'
        )
    else:
        detail = (
            'Stale cost ledger at working/working/costs/ledger.csv from '
            'pre-#205 score runs, with no current ledger present. The '
            'historical cost data is intact but mis-located.'
        )
        action = (
            'Move working/working/costs/ledger.csv to '
            'working/costs/ledger.csv, then remove the empty parent '
            'directory.'
        )
    return [{
        'type': 'stale_ledger',
        'file': 'working/working/costs/ledger.csv',
        'category': 'costs',
        'detail': detail,
        'action': action,
        'severity': 'warning',
    }]


def _check_page_files(project_dir: str) -> list[dict]:
    """Validate page files under pages/ for GN projects. Returns finding dicts
    in cleanup-report shape. Returns [] for non-GN projects. For GN projects
    it can still return findings when pages/ is empty — e.g. an orphan render
    in manuscript/pages/ with no matching page file (issue #261)."""
    if get_medium(project_dir) != 'graphic-novel':
        return []
    from storyforge.pages import list_page_files, validate_page_file

    findings: list[dict] = []
    for page_path in list_page_files(project_dir):
        for issue in validate_page_file(page_path):
            rel_path = os.path.relpath(page_path, project_dir)
            kind = issue['kind']
            if kind == 'missing_file':
                # Defensive: list_page_files only returns existing files,
                # so this is a TOCTOU race (file deleted mid-scan).
                findings.append({
                    'type': 'page_missing_file', 'file': rel_path,
                    'detail': f'{rel_path} disappeared during validation',
                    'action': 'Re-run cleanup',
                    'severity': 'warning',
                })
            elif kind == 'no_frontmatter':
                findings.append({
                    'type': 'page_no_frontmatter', 'file': rel_path,
                    'detail': f'{rel_path} has no YAML frontmatter',
                    'action': 'Add the page-file frontmatter '
                              '(page_id, scene_id, page_within_scene, '
                              'total_pages_in_scene, panel_count)',
                    'severity': 'warning',
                })
            elif kind == 'missing_field':
                findings.append({
                    'type': 'page_missing_field', 'file': rel_path,
                    'detail': f'{rel_path} is missing required field '
                              f'{issue["field"]!r}',
                    'action': f'Add `{issue["field"]}: ...` to the frontmatter',
                    'severity': 'warning',
                })
            elif kind == 'bad_integer_field':
                findings.append({
                    'type': 'page_bad_integer_field', 'file': rel_path,
                    'detail': f'{rel_path} field {issue["field"]!r} is '
                              f'not an integer',
                    'action': f'Replace the {issue["field"]} value with '
                              f'an integer',
                    'severity': 'warning',
                })
            elif kind == 'filename_page_id_mismatch':
                findings.append({
                    'type': 'page_filename_mismatch', 'file': rel_path,
                    'detail': issue['detail'],
                    'action': 'Rename the file to match page_id, '
                              'or fix the page_id in frontmatter',
                    'severity': 'warning',
                })
            elif kind == 'page_within_scene_out_of_range':
                findings.append({
                    'type': 'page_out_of_range', 'file': rel_path,
                    'detail': issue['detail'],
                    'action': 'Correct page_within_scene or '
                              'total_pages_in_scene to be consistent',
                    'severity': 'warning',
                })
            elif kind == 'missing_page_architecture':
                findings.append({
                    'type': 'page_missing_page_architecture', 'file': rel_path,
                    'detail': issue['detail'],
                    'action': 'Run `storyforge elaborate --stage '
                              'page-architecture --page '
                              f'{os.path.splitext(os.path.basename(page_path))[0]}` '
                              'to populate (or write the section by hand)',
                    'severity': 'warning',
                })
            elif kind == 'missing_image_workflow':
                findings.append({
                    'type': 'page_missing_image_workflow', 'file': rel_path,
                    'detail': issue['detail'],
                    'action': 'Run `storyforge elaborate --stage '
                              'prompts --page '
                              f'{os.path.splitext(os.path.basename(page_path))[0]}` '
                              'to author the whole-page image prompt (or write '
                              'the section by hand)',
                    'severity': 'warning',
                })
            elif kind == 'invalid_page_aspect':
                findings.append({
                    'type': 'page_invalid_aspect', 'file': rel_path,
                    'detail': issue['detail'],
                    'action': 'Set page_aspect to one of portrait | landscape '
                              '| square (default portrait)',
                    'severity': 'warning',
                })
            elif kind == 'non_portrait_page_aspect':
                findings.append({
                    'type': 'page_non_portrait_aspect', 'file': rel_path,
                    'detail': issue['detail'],
                    'action': 'Confirm the non-portrait orientation is '
                              'intentional; add a trailing `# justification` '
                              'comment on the page_aspect line to silence',
                    'severity': 'warning',
                })
            elif kind == 'undifferentiated_closeups':
                findings.append({
                    'type': 'page_undifferentiated_closeups', 'file': rel_path,
                    'detail': issue['detail'],
                    'action': 'Re-run `storyforge elaborate --stage prompts '
                              '--force --page '
                              f'{os.path.splitext(os.path.basename(page_path))[0]}` '
                              'to regenerate with differentiated framing, or '
                              'vary each close-up\'s framing by hand',
                    'severity': 'warning',
                })
            else:
                # Catches future PageFindingKind values that nobody wires
                # up here — silent drop would re-introduce SF-6.
                findings.append({
                    'type': 'page_unknown_finding', 'file': rel_path,
                    'detail': f'{rel_path}: unhandled validator kind '
                              f'{kind!r} ({issue.get("detail", "")})',
                    'action': 'File a bug — cmd_cleanup needs a branch '
                              'for this PageFindingKind',
                    'severity': 'warning',
                })

    # Rendered-page correspondence (issue #261): a PNG in manuscript/pages/
    # with no matching page file is an orphan. A page file without a PNG is
    # valid in-flight state (unrendered), so it is NOT a finding here.
    # Function-local import: pages is otherwise only needed on the GN path,
    # and keeping it here mirrors the deferred-import style used for the
    # per-page-file validators above.
    from storyforge.pages import page_render_report, RENDERED_PAGES_SUBDIR
    orphans = page_render_report(project_dir)['orphans']
    for png in orphans:
        rel = os.path.join(RENDERED_PAGES_SUBDIR, png)
        findings.append({
            'type': 'page_render_orphan', 'file': rel,
            'detail': f'{rel} has no matching page file in pages/ '
                      f'(expected pages/{os.path.splitext(png)[0]}.md)',
            'action': 'Remove the orphan render, or add/rename the page file '
                      'so its page_id matches the PNG stem',
            'severity': 'warning',
        })
    return findings


#: Per-finding remediation text for the illustration plan (#278). Keyed by the
#: `kind` illustrations.validate_plan emits.
_ILLUSTRATION_ACTIONS: dict[IllustrationFindingKind, str] = {
    'duplicate_id': 'Give each illustration a unique id in '
                    'reference/illustration-plan.csv',
    'invalid_id': 'Rename the id to start with a letter or digit, using '
                  'only letters, digits, hyphens, and underscores',
    'unpublishable_id': 'Rename the id and its scene marker using hyphens '
                        'instead of underscores — Bookshelf asset keys allow '
                        'only lowercase letters, digits, and hyphens',
    'invalid_status': 'Set status to planned, prompted, rendered, ingested, '
                      'or superseded',
    'invalid_placement': 'Set placement to before_anchor, after_anchor, '
                         'scene_open, or scene_close',
    'invalid_layout': 'Set layout to full_page, half_page, double_page, '
                      'or inline',
    'canon_anchor_truncated': 'Demote the `##` heading inside that canon '
                              'file\'s Embeddable block to `###` so it stays '
                              'inside the anchor; if it was meant to be its '
                              'own section, move it below the four required '
                              'sections. Re-render any art already generated '
                              'from the short anchor',
    'missing_scene': 'Set scene_id to the scene this illustration belongs to',
    'unknown_scene': 'Fix scene_id, or add the missing scene file',
    'missing_file': 'Run storyforge illustrate --ingest <path>, or set the '
                    'row back to status=planned',
    'missing_digest': 'Re-ingest the file so its sha256 is recorded — '
                      'publishing is content-addressed and needs it',
    'duplicate_marker': 'Remove the repeated ![[illus:…]] line from the scene',
    'orphan_marker': 'Add the plan row, or remove the marker from the scene',
    'anchor_drift': 'Update the anchor to a phrase that appears in the '
                    'revised prose, then re-run '
                    'storyforge illustrate --embed',
    'anchor_ambiguous': 'Lengthen the anchor until it is unique within '
                        'the scene',
    'orphan_file': 'Reference the file from a plan row, or delete it',
    'inline_marker': 'Move the marker to its own line — run '
                     'storyforge illustrate --embed rather than placing it '
                     'by hand',
    'marker_lost': 'A rewrite dropped the marker. Re-anchor the plan row if '
                   'the prose changed, then run '
                   'storyforge illustrate --embed',
    'unembedded_ingested': 'Run storyforge illustrate --embed — the art exists '
                           'but nothing in the prose points at it',
    'shattered_row': 'Replace the "|" in the offending cell with "/" — the '
                     'plan is pipe-delimited and unquoted',
    'direction_anchor_mismatch':
        'Confirm which text is correct. If the canon file is right, delete '
        'reference/illustration-direction.md. If the old text is right, '
        'restore it into the canon file and re-render nothing — the existing '
        'art already matches it',
    'state_unknown_scene':
        'In reference/visual-state.csv, point from_scene at an active scene in '
        'scenes.csv, or delete the row — a transition keyed to a cut scene never '
        'applies, so every scene after it resolves to the wrong state',
    'state_unmapped_scene':
        'Add the scene to reference/chapter-map.csv — the transition row is '
        'fine, but it cannot be positioned until the map lists the scene',
    'evidence_not_found':
        'Re-quote evidence from the current prose of from_scene, or move the '
        'transition to the scene that now establishes it',
    'state_unspecified':
        'Add a transition for the entity in reference/visual-state.csv, or set '
        'state_override on the plan row if the state is true in this image only',
    'prose_changed':
        'The scene was revised after this illustration was rendered. Confirm '
        'the art still matches, then re-run storyforge illustrate --ingest to '
        'record the new scene_digest — or re-render',
    'audit_stale':
        'Re-run storyforge illustrate --audit — the prose has changed since the '
        'last contradiction pass',
    'packet_stale':
        'Re-run storyforge illustrate --package — the packet is a render, so '
        'regenerating it is the whole fix; a generating session working from a '
        'stale packet spends real money on last week\'s plan',
    'anchor_copy_drift':
        'Re-run storyforge illustrate --package rather than editing the packet '
        '— the anchor copy must be byte-identical to the canon file, because '
        'likeness continuity across separately generated images is the string. '
        'If the packet text is the one you want, put it in the canon file '
        'first (and do not revise an anchor a rendered illustration used)',
    'canon_stale_render':
        'Re-render it from the current canon and run storyforge illustrate '
        '--ingest, which stamps a fresh ingested_at. Do NOT demote status to '
        'get the warning to stop — the row would drop out of the Bookshelf '
        'publish manifest while the epub, the PDF, and the web book kept '
        'shipping it, so the editions would disagree about a book you had '
        'not re-rendered yet',
    'state_mid_scene_change':
        'Set state_override on the plan row to state what is true in this image. '
        'It sits at the open or close of a scene the entity changes during, and '
        'reference/visual-state.csv holds one value for the whole scene, so it '
        'cannot say which side of that change the image is on',
    'state_override_unparsed':
        'Rewrite the state_override cell as entity:state, separated by '
        'semicolons. The dropped clause is a state you believe is in the prompt '
        'and is not — prose in this cell splits on its own punctuation',
    'state_override_prose_key':
        'Replace the sentence with an entity id (nora-clothing, village-lights). '
        'As written it reaches the image model as an authoritative state line '
        'labelled with your sentence',
    'state_override_unmatched_entity':
        'Check the spelling against reference/visual-state.csv and the row\'s '
        'canon_refs. Intentional for a one-off entity the matrix does not '
        'track — but a typo is applied silently, so confirm which it is',
    'prompt_spoils_unread':
        'Re-run storyforge illustrate --prompts --ids <id>, which sends the '
        'scene split at the illustration\'s position. Then check the render: if '
        'the art already shows the next page, it needs re-rendering, not just a '
        'new prompt',
    'prompt_spoiler_unchecked':
        'Fix the named cause, then re-run storyforge validate — the row is '
        'unverified, not clean. The spoiler check is the only thing that catches '
        'a render that shows the next page, so a row it could not read is a row '
        'nothing has checked',
    'missing_anchor':
        'Quote a short verbatim phrase from the scene into the anchor cell, or '
        'set placement to scene_open / scene_close. Without an anchor the marker '
        'cannot be placed, so the illustration never appears in the book',
    'canon_staleness_unchecked':
        'Set canon_updated: YYYY-MM-DD in the canon files you have edited — '
        'until one carries a parseable date, no ingested illustration can be '
        'shown to predate the canon that governs it, so every render reads as '
        'current whether or not it is',
}


def _check_illustrations(project_dir: str) -> list[dict]:
    """Check the illustration plan against markers and files (#278).

    An unrendered plan row is valid in-flight state, not a finding — the same
    posture as unrendered GN pages. What is reported is genuine incoherence
    between the plan, the scene markers, and the files on disk.
    """
    from storyforge import illustrations as ill

    findings: list[dict] = []
    for finding in ill.validate_plan(project_dir):
        kind = finding['kind']
        target = finding.get('file') or (
            f'scenes/{finding["scene_id"]}.md' if finding.get('scene_id')
            else f'reference/{ill.PLAN_FILENAME}'
        )
        findings.append({
            'type': f'illus_{kind}',
            'file': target,
            'detail': finding['detail'],
            'action': _ILLUSTRATION_ACTIONS.get(
                kind, 'Review the illustration plan'),
            'severity': ill.severity_of(kind),
        })
    return findings


def _check_unreadable_inputs(project_dir: str) -> list[dict]:
    """Report files a cleanup step reads that no other check covers.

    `.gitignore` is the whole list. When `plan_gitignore` cannot read it, it
    logs a WARNING and plans nothing — and an empty `StepPlan` is
    indistinguishable from "nothing to do", so without a finding the durable
    artifact says the project is clean. `storyforge.yaml` is covered by
    `_check_yaml_scalars`, every registered CSV by `report_csv_schema`'s
    `UNREADABLE_CSV`; this closes the third.

    Same doctrine as `illustrations.staleness_unchecked_finding` and `--audit`'s
    "Not assessed": **could not check must never render as checked and clean.**
    The log line is not the artifact — `working/cleanup-report.csv` is, and it
    is what `skills/forge/SKILL.md` scans.
    """
    path = os.path.join(project_dir, '.gitignore')
    if not os.path.isfile(path):
        return []
    try:
        with open(path, encoding='utf-8') as f:
            f.read()
    except (OSError, UnicodeDecodeError) as exc:
        return [{
            'type': 'unreadable_file', 'file': '.gitignore',
            'category': 'structure',
            # `csv_safe` because the exception message carries a path, and the
            # report is unquoted pipe-delimited — a `|` shifts every later
            # field and empties the `status` cell forge scans for.
            'detail': csv_safe(f'.gitignore could not be read '
                               f'({type(exc).__name__}: {exc}), so its '
                               f'required entries were not checked or added'),
            'action': 'Check the file\'s permissions and encoding — '
                      'Storyforge reads it as UTF-8',
            'severity': 'warning',
        }]
    return []


def _check_crlf(project_dir: str) -> list[dict]:
    """Report CRLF line endings in the CSVs and in `storyforge.yaml`.

    `storyforge.yaml` was added in #314. It matters because all **three** commands
    that write that file now preserve whatever endings they find —
    `common.update_artifact_entry` (#276), this module's
    `migrate_storyforge_yaml`, and `cmd_write._replace_in_file`, which advances
    `phase` and was the one this fix nearly missed. So nothing converts the file
    any more, and an author who wants LF has to be told.

    Before #314 `cleanup` normalized it on every run, which is why no finding was
    needed then and why the fix has to add one: removing a silent conversion
    without reporting what it used to hide just moves the silence.
    """
    findings: list[dict] = []
    dirty_files: list[str] = []
    unreadable: list[str] = []
    for rel_path in list(EXPECTED_CSV_SCHEMAS) + ['storyforge.yaml']:
        path = os.path.join(project_dir, rel_path)
        if not os.path.isfile(path):
            continue
        # Guarded, and this is the guard that actually matters: this check runs
        # *before* `_check_yaml_scalars` in `build_cleanup_report`, so an
        # unreadable file here killed the whole collector and no
        # `working/cleanup-report.csv` was written at all — leaving
        # `skills/forge/SKILL.md`'s `status=pending` scan to read the project as
        # clean. The guard 40 lines below was dead on its own input.
        try:
            with open(path, 'rb') as f:
                data = f.read()
        except OSError as exc:
            unreadable.append(f'{rel_path} ({type(exc).__name__})')
            continue
        if b'\r\n' in data:
            dirty_files.append(rel_path)

    if unreadable:
        findings.append({
            'type': 'unreadable_file', 'file': '; '.join(
                p.split(' (')[0] for p in unreadable),
            'category': 'structure',
            'detail': csv_safe(f'{len(unreadable)} file(s) could not be read, '
                               f'so their line endings and contents were not '
                               f'checked: {", ".join(unreadable[:5])}'
                               f'{"..." if len(unreadable) > 5 else ""}'),
            'action': 'Check file permissions',
            'severity': 'warning',
        })

    if dirty_files:
        findings.append({
            'type': 'crlf_line_endings', 'file': '; '.join(dirty_files),
            'category': 'structure',
            'detail': f'{len(dirty_files)} file(s) have CRLF line endings: '
                      f'{", ".join(dirty_files[:5])}'
                      f'{"..." if len(dirty_files) > 5 else ""}',
            'action': 'Normalize line endings to LF',
            'command': "find reference working -name '*.csv' -exec sed -i '' $'s/\\r$//' {} + "
                       "&& sed -i '' $'s/\\r$//' storyforge.yaml",
            'severity': 'warning',
        })
    return findings


class YamlScalarFinding(NamedTuple):
    """How one `common.YamlScalarIssue` is reported.

    A NamedTuple rather than a 3-tuple: three same-typed strings whose meaning
    lives only in a comment is the ordering mix-up `canon.BlockTruncation` and
    `common.ArtifactBlock` both exist to prevent — and swapping `detail` with
    `action` here would tell an author with an unterminated quote to "remove the
    text after the closing quote", which is a mutation a reviewer demonstrated
    surviving the whole suite.
    """
    kind: str
    detail: str
    action: str


#: One entry per `common.YamlScalarIssue`. Separate messages rather than one
#: shared, because the three fixes genuinely differ — add a quote, remove trailing
#: text, quote the whole value — and a shared remedy that fits one is the
#: inert-advice problem `_artifact_span_failure` was split to avoid.
#:
#: Keyed by the Literal, not `str`, and asserted total below: the subscript at the
#: bottom of `_check_yaml_scalars` is unguarded, so a member added to
#: `YamlScalarIssue` and not to this dict is a `KeyError` out of
#: `build_cleanup_report` — the single finding collector, which #298 is the
#: standing reminder must never raise.
_YAML_SCALAR_FINDINGS: Final[dict[common.YamlScalarIssue,
                                  YamlScalarFinding]] = {
    'unterminated_quote': YamlScalarFinding(
        'yaml_unterminated_quote',
        'the opening quote is never closed, so the value is read as plain text '
        'with the quote character included',
        'Close the quote, or remove it',
    ),
    'trailing_after_quote': YamlScalarFinding(
        'yaml_trailing_after_quote',
        'text follows the closing quote, so the whole line is read as plain '
        'text rather than as the quoted value',
        'Remove the text after the closing quote, or quote the whole value',
    ),
    'comment_truncated': YamlScalarFinding(
        'yaml_value_truncated_by_comment',
        'YAML reads " #" as the start of a comment, so everything from the '
        '"#" onward is dropped from the value',
        'Wrap the value in double quotes to keep the "#"',
    ),
}

#: Totality, asserted at import. The subscript that reads this dict is unguarded
#: and lives inside the single finding collector, so a member added to one
#: declaration and not the other must fail loudly and immediately rather than as a
#: `KeyError` mid-report. Same convention as `packet.BATCH_SLOTS`' `get_args` test.
assert set(_YAML_SCALAR_FINDINGS) == set(get_args(common.YamlScalarIssue)), (
    'every common.YamlScalarIssue needs an entry in _YAML_SCALAR_FINDINGS: '
    f'{set(get_args(common.YamlScalarIssue)) ^ set(_YAML_SCALAR_FINDINGS)}')


def _check_yaml_scalars(project_dir: str) -> list[dict]:
    """Report `storyforge.yaml` values that were probably misread (#315).

    Both conditions are *correct* parser behaviour that is nonetheless silent:
    malformed quoting degrades leniently, and ` #` opens a comment. Neither can
    change without reintroducing #277, so the fix is to say so — the same posture
    as `canon_staleness_unchecked` and `--audit`'s "Not assessed": a value we may
    not have read the way the author meant must not render identically to one we
    did.

    Warnings, not errors, and deliberately not a `validate` gate: the project
    builds, and the affected key may be one nothing reads.

    **Scope, stated precisely because the first version of this docstring was
    wrong in both directions.** A `key: value` line indented 0–4 spaces is
    examined, which is up to *two* levels of the file's 2-space nesting, not one.
    The `- key: value` line that opens a list item is skipped, but a list item's
    *continuation* keys are indented like any other and are examined — which is
    right, since `parts[].title` reaches the epub through `read_part_field`.

    Block scalars (`key: |`, `key: >`) are skipped along with their bodies. A body
    line is not a `key: value` pair, and scanning one produced a finding naming a
    key the author never wrote — a false claim about their file, which is worse
    than the silence this check exists to remove.
    """
    yaml_path = os.path.join(project_dir, 'storyforge.yaml')
    if not os.path.isfile(yaml_path):
        return []

    try:
        with open(yaml_path, encoding='utf-8') as f:
            lines = f.readlines()
    except (OSError, UnicodeDecodeError) as exc:
        # Reported rather than raised: this is one check inside the single
        # finding collector, and an unreadable file must not take down every
        # other check in the report. The `ill.sha256_of` regression (#298).
        return [{
            'type': 'yaml_unreadable', 'file': 'storyforge.yaml',
            'category': 'structure',
            'detail': csv_safe(f'could not read storyforge.yaml to check its '
                               f'values ({type(exc).__name__}: {exc})'),
            'action': 'Check the file is readable and valid UTF-8',
            'severity': 'warning',
        }]

    findings: list[dict] = []
    block_indent: int | None = None
    for number, line in enumerate(lines, start=1):
        text = line.rstrip('\r\n')

        # Inside a block scalar, every line is content until the indentation
        # returns to the owning key's level or shallower.
        if block_indent is not None:
            if not text.strip():
                continue
            if len(text) - len(text.lstrip()) > block_indent:
                continue
            block_indent = None

        m = re.match(r'^(\s{0,4})([A-Za-z_][\w-]*):(?:[ \t]+(\S.*?))?\s*$', text)
        if not m:
            continue
        raw = m.group(3)
        if not raw:
            continue
        if re.match(r'^[|>][-+]?\d*\s*$', raw):
            block_indent = len(m.group(1))
            continue
        issue = common.yaml_scalar_issue(raw)
        if issue is None:
            continue
        kind, detail, action = _YAML_SCALAR_FINDINGS[issue]
        key = m.group(2)
        findings.append({
            'type': kind, 'file': 'storyforge.yaml',
            'category': 'structure',
            # csv_safe on the interpolated author text: the report is unquoted
            # pipe-delimited, and a `|` in a value would shift every later column
            # and empty the trailing `status` cell that forge scans for.
            'detail': csv_safe(f'line {number}, `{key}`: {detail} — '
                               f'read as `{common.parse_yaml_scalar(raw)}` '
                               f'from `{raw}`'),
            'action': action,
            'severity': 'warning',
        })
    return findings


def report_canon_files(project_dir: str) -> list[CanonFinding]:
    """Validate reference/canon/ for any medium.

    Both mediums use canon as their reference tier: graphic novels for
    page prompts, prose books for illustration continuity anchors. A
    project with no canon directory yet is valid in-flight state, not
    a finding.
    """
    canon_dir_present = os.path.isdir(os.path.join(project_dir, CANON_DIR))
    if not canon_dir_present:
        return []
    findings = validate_canon_directory(project_dir)
    for f in findings:
        f['category'] = 'canon'
    return findings


def build_cleanup_report(project_dir: str) -> dict:
    """Build a full structured cleanup report covering all checks.

    Returns a dict with:
        findings: list of finding dicts (type, file, detail, action, severity, category, ...)
        action_items: list of actionable finding dicts (severity != 'info')
        summary: dict with counts by severity and category
    """
    all_findings: list[dict] = []

    # --- Structure checks ---
    # Missing directories
    for d in EXPECTED_DIRS:
        if not os.path.isdir(os.path.join(project_dir, d)):
            all_findings.append({
                'type': 'missing_dir', 'file': d,
                'category': 'structure',
                'detail': f'{d}/ does not exist',
                'action': f'Created by storyforge cleanup',
                'severity': 'info',
            })

    # storyforge.yaml
    yaml_path = os.path.join(project_dir, 'storyforge.yaml')
    if not os.path.isfile(yaml_path):
        all_findings.append({
            'type': 'missing_yaml', 'file': 'storyforge.yaml',
            'category': 'structure',
            'detail': 'storyforge.yaml not found',
            'action': 'Initialize with storyforge init or create manually',
            'command': 'storyforge init',
            'severity': 'error',
        })

    # Files a cleanup step needs but no other check reads
    all_findings.extend(_check_unreadable_inputs(project_dir))

    # CRLF check
    all_findings.extend(_check_crlf(project_dir))

    # storyforge.yaml values that were probably misread (#315)
    all_findings.extend(_check_yaml_scalars(project_dir))

    # Stale ledger from #205 (pre-fix score runs)
    all_findings.extend(_check_stale_ledger(project_dir))

    # --- Scene artifacts ---
    all_findings.extend(_check_scene_artifacts(project_dir))

    # --- Page files (GN-only) ---
    for finding in _check_page_files(project_dir):
        finding['category'] = 'pages'
        all_findings.append(finding)

    # --- Interior illustrations (prose-only) ---
    for finding in _check_illustrations(project_dir):
        finding['category'] = 'illustrations'
        all_findings.append(finding)

    # --- CSV schema ---
    schema_issues = report_csv_schema(project_dir)
    rename_pairs = _detect_rename_pairs(schema_issues)
    for issue in schema_issues:
        finding = _classify_issue(issue, rename_pairs)
        if finding:
            finding['category'] = 'schema'
            all_findings.append(finding)

    # --- CSV row integrity ---
    for issue in report_csv_integrity(project_dir):
        finding = _classify_issue(issue, {})
        if finding:
            finding['category'] = 'integrity'
            all_findings.append(finding)

    # --- Unexpected files ---
    for issue in report_unexpected_files(project_dir):
        finding = _classify_issue(issue, {})
        if finding:
            finding['category'] = 'unexpected'
            all_findings.append(finding)

    # --- Canon files (graphic-novel projects only) ---
    all_findings.extend(report_canon_files(project_dir))

    # Set default status on all findings
    for f in all_findings:
        if 'status' not in f:
            f['status'] = 'pending' if f['severity'] != 'info' else ''

    action_items = [f for f in all_findings if f['severity'] != 'info']

    return {
        'findings': all_findings,
        'action_items': action_items,
        'summary': {
            'total': len(all_findings),
            'errors': sum(1 for f in all_findings if f['severity'] == 'error'),
            'warnings': sum(1 for f in all_findings if f['severity'] == 'warning'),
            'info': sum(1 for f in all_findings if f['severity'] == 'info'),
        },
    }


def _print_report(report: dict) -> None:
    """Print a human-readable report to stdout via log()."""
    findings = report['findings']
    action_items = report['action_items']
    summary = report['summary']

    # Group by category for display
    categories = [
        ('structure', 'Project Structure'),
        ('scenes', 'Scene Files'),
        ('pages', 'Page Files'),
        ('illustrations', 'Interior Illustrations'),
        ('schema', 'CSV Schema'),
        ('integrity', 'CSV Integrity'),
        ('unexpected', 'Unexpected Files'),
        ('canon', 'Canon Files'),
    ]
    for category, heading in categories:
        group = [f for f in findings if f.get('category') == category]
        if not group:
            continue
        log(f'=== {heading} ===')
        for f in group:
            severity_tag = f'[{f["severity"].upper()}]'
            log(f'  {severity_tag} {f["detail"]}')
            log(f'         → {f["action"]}')
            if 'command' in f:
                log(f'           $ {f["command"]}')
        log('')

    # Action items summary
    if action_items:
        log(f'=== Action Items ({len(action_items)}) ===')
        for i, item in enumerate(action_items, 1):
            if 'command' in item:
                log(f'  {i}. {item["action"]}  →  {item["command"]}')
            else:
                log(f'  {i}. {item["detail"]}: {item["action"]}')
    else:
        log('=== No action items — project is clean ===')

    log('')
    log(f'Summary: {summary["errors"]} error(s), '
        f'{summary["warnings"]} warning(s), {summary["info"]} info')


REPORT_COLUMNS = ['category', 'type', 'severity', 'file', 'detail', 'action', 'command', 'status']


def _write_report(report: dict, project_dir: str) -> str:
    """Write the report as pipe-delimited CSV to working/cleanup-report.csv.

    Returns the path to the written file.
    """
    working_dir = os.path.join(project_dir, 'working')
    os.makedirs(working_dir, exist_ok=True)
    report_path = os.path.join(working_dir, 'cleanup-report.csv')
    with open(report_path, 'w') as f:
        f.write('|'.join(REPORT_COLUMNS) + '\n')
        for finding in report['findings']:
            row = [finding.get(col, '') for col in REPORT_COLUMNS]
            f.write('|'.join(row) + '\n')
    return report_path


def _run_and_write_report(project_dir: str) -> None:
    """Build the full cleanup report, print it, and write JSON."""
    report = build_cleanup_report(project_dir)
    _print_report(report)
    report_path = _write_report(report, project_dir)
    log(f'Report written to {report_path}')


def plan_cleanup(project_dir: str, scenes: bool = False) -> list[StepPlan]:
    """Every mutating step, in the order the real run performs them.

    The one place the step list lives, so `--dry-run` cannot preview a
    different set of steps from the one that runs, and the seam the per-step
    property test hangs off. Every step here needs a row in that test's
    `ARRANGEMENTS`; `test_every_step_has_an_arrangement` enforces it.

    **Order is load-bearing.** `DiskFacts` is built from the directory step's
    own list, so every step after it observes the directories it will create.
    Moving the directory step later would make those facts a lie; a new step
    that creates or deletes anything a later step reads has to be reflected in
    `gather_disk_facts` the same way.
    """
    disk, missing_dirs = gather_disk_facts(project_dir)
    plans = [
        plan_gitignore(project_dir),
        plan_missing_dirs(project_dir, missing_dirs),
        plan_storyforge_yaml(project_dir, disk),
        plan_pipeline_csv(project_dir),
        plan_junk_files(project_dir, disk),
        plan_legacy_files(project_dir, disk),
        plan_loose_files(project_dir, disk),
        plan_pipeline_reviews(project_dir),
    ]
    if scenes:
        plans.append(plan_scene_files(project_dir))
    return plans


def main(argv=None):
    args = parse_args(argv or [])
    project_dir = detect_project_root()
    log(f'Project root: {project_dir}')

    # --csv: run only the report and exit (no modifications)
    if args.csv:
        _run_and_write_report(project_dir)
        log('')
        log('Check complete.')
        return

    def vlog(msg):
        if args.verbose:
            log(msg)

    if args.dry_run:
        log('=== DRY RUN — no changes will be made ===')
    else:
        ensure_on_branch('cleanup', project_dir)

    for plan in plan_cleanup(project_dir, scenes=args.scenes):
        log(plan.title)
        if args.dry_run:
            for change in plan.changes:
                log(f'  {change.would}')
        else:
            # `plan.apply()`'s return, not `plan.changes` — a step reports what
            # it did, not what it meant to do.
            for change in plan.apply():
                vlog(f'  {change.did}')
        if plan.summary is not None:
            log(f'  {plan.summary.would if args.dry_run else plan.summary.did}')

    # Outside the plan loop on purpose: an effect on the git index, not on the
    # project's files, so it is neither planned nor previewed (see the
    # docstring). Unconditional in a real run, which is what it was before the
    # planner and what living inside step 1's `apply` silently took away.
    if not args.dry_run:
        _untrack_newly_ignored(project_dir)

    # The report — cleanup's actual product, and the reason every step above
    # reports its failures rather than raising them.
    log('')
    _run_and_write_report(project_dir)

    # Commit (unless dry-run)
    if not args.dry_run:
        git_dir = os.path.join(project_dir, '.git')
        if shutil.which('git') and os.path.isdir(git_dir):
            r = subprocess.run(
                ['git', '-C', project_dir, 'status', '--porcelain'],
                capture_output=True, text=True,
            )
            if r.stdout.strip():
                log('')
                log('Committing changes...')
                committed = commit_and_push(
                    project_dir,
                    'Cleanup: project structure and working files',
                )
                if not committed:
                    log('WARNING: git commit or push may have failed')
            else:
                log('No changes to commit.')

    log('')
    log('Cleanup complete.')
