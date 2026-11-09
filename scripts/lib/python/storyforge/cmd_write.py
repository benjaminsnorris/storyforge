"""storyforge write — Autonomous scene drafting.

Drafts scenes one at a time in reading order (rethink plan §3.3), each
from its brief and the ledger as of that scene, and gates each before the
next (plan §3.2, `storyforge.gate`): its facts are extracted and checked
against the book and its brief, fixed if needed (up to `gate.FIX_ROUNDS`
times), and committed to the ledger only when clean. A scene that still fails is kept, listed in
`working/gate-pending.csv`, and stops the run; with `--keep-going` (#556)
one stopped only by the check's findings is committed provisionally
(`gate.commit_provisional`) and the run goes on. A redraft that passes
re-checks the later scenes depending on what it changed (Phase 4,
`gate.recheck_pending`). Coaching levels coach and
strict write briefs or constraints, not prose, and are not gated; only they
take `--batch` (every scene at once through the Batch API). Prose is never
drafted in parallel: on E4, drafting every scene at once (no earlier prose,
no gate) gave CP10k 13.7 against 1.8 and 5.3 sequential and gated (rethink
plan Phase 3: parallel stays only if equal).

Usage:
    storyforge write                        # Draft all remaining scenes
    storyforge write act1-sc01              # Draft a single scene
    storyforge write act1-sc01 act1-sc15    # Draft a range (by position)
    storyforge write --act 2                # Draft all scenes in act 2
    storyforge write --dry-run act1-sc01    # Build prompt and forecast, no API call
    storyforge write --keep-going           # Don't stop at a gate failure: commit it provisionally
    storyforge write --coaching coach --batch --act 2   # briefs via the Batch API
"""

import argparse
import json
import os
import shutil
import subprocess
import sys
import time

from storyforge.common import (
    detect_project_root, log, set_log_file, read_yaml_field,
    rewrite_preserving_newlines, select_model, get_coaching_level,
    install_signal_handlers,
)
from storyforge.git import (
    create_branch, ensure_branch_pushed, create_draft_pr, commit_and_push,
    update_pr_task, run_review_phase,
)
from storyforge.cli import apply_coaching_override
from typing import NamedTuple
from storyforge.api import (
    invoke_to_file, extract_text, extract_text_from_file, extract_usage,
    calculate_cost_from_usage, submit_batch, poll_batch, download_batch_results,
    stop_problem, fallback_model, is_refusal, RefusalError, report_fallback_replies,
)
from storyforge.costs import (
    check_threshold, cost_threshold, exit_if_bad_threshold, log_operation,
    print_summary,
)
from storyforge.scene_filter import build_scene_list, apply_scene_filter
from storyforge.csv_cli import get_field, update_field
from storyforge.illustrations import count_prose_words, read_scene_prose


def parse_args(argv):
    parser = argparse.ArgumentParser(
        prog='storyforge write',
        description='Draft scenes autonomously using Claude.',
    )
    parser.add_argument('positional', nargs='*', default=[],
                        help='Scene ID(s) — one for single, two for range')
    parser.add_argument('--dry-run', action='store_true',
                        help='Build prompts without invoking Claude')
    parser.add_argument('--force', action='store_true',
                        help='Re-draft scenes even if already drafted')
    parser.add_argument('--direct', action='store_true',
                        help='Draft one scene at a time, each gated (the default; '
                             'kept for scripts that pass it)')
    parser.add_argument('--batch', action='store_true',
                        help='Coaching coach or strict only: write every scene\'s brief '
                             'or constraints at once through the Batch API (half price). '
                             'Prose is drafted one scene at a time, each gated')
    parser.add_argument('--coaching', choices=['full', 'coach', 'strict'],
                        help='Set coaching level')
    parser.add_argument('--prior-prose', choices=['window', 'full', 'none'],
                        help='Earlier prose each scene is drafted with: the whole manuscript '
                             'so far (full, the default; past 100,000 words, the window), the '
                             'preceding scene and the latest scene of each thread it carries '
                             '(window), or none. Default: storyforge.yaml '
                             'drafting.prior_prose, else full')
    parser.add_argument('--interactive', '-i', action='store_true',
                        help='Draft with supervision')
    parser.add_argument('--scenes', type=str, default=None,
                        help='Comma-separated scene IDs')
    parser.add_argument('--act', '--part', type=str, default=None,
                        help='Draft all scenes in act N')
    parser.add_argument('--from-seq', type=str, default=None,
                        help='Start from sequence number (N or N-M range)')
    parser.add_argument('--keep-going', action='store_true',
                        help='Full coaching: a scene the gate still stops on only for the '
                             'check\'s findings is committed provisionally (its facts less '
                             'those stating the findings), listed for the author, and the run '
                             'goes on; provisional scenes don\'t stop it either. Halts, '
                             'extraction problems and bad replies still stop it')
    return parser.parse_args(argv)


def main(argv=None):
    args = parse_args(argv if argv is not None else sys.argv[1:])

    install_signal_handlers()
    apply_coaching_override(args)

    project_dir = detect_project_root()
    from storyforge.series import require_canon
    require_canon(project_dir)  # a bad series canon stops here, before a branch or spend
    exit_if_bad_threshold()   # a bad value crashed the forecast check with a traceback
    from storyforge.ledger import exit_if_not_migrated, exit_if_unordered
    exit_if_not_migrated(project_dir)  # the registries live in the ledger
    exit_if_unordered(project_dir)  # drafting reads the ledger as of each scene
    log(f'Project root: {project_dir}')

    scenes_dir = os.path.join(project_dir, 'scenes')
    log_dir = os.path.join(project_dir, 'working', 'logs')
    os.makedirs(scenes_dir, exist_ok=True)
    os.makedirs(log_dir, exist_ok=True)
    os.makedirs(os.path.join(project_dir, 'working', 'coaching'), exist_ok=True)

    set_log_file(os.path.join(log_dir, 'drafting-log.txt'))

    # Resolve coaching level
    coaching = args.coaching or get_coaching_level(project_dir)

    if args.batch and coaching == 'full':
        log('ERROR: --batch is for coaching coach or strict. Prose is drafted one scene at '
            'a time, each from the scenes before it and gated before the next: drafted all '
            'at once, ungated, E4 had several times the contradictions (CP10k 13.7 against '
            '1.8-5.3). Drop --batch, or pass --coaching coach|strict for briefs.')
        sys.exit(1)

    # Resolve write mode
    if args.interactive:
        write_mode = 'interactive'
    elif args.batch:
        write_mode = 'batch'
    else:
        write_mode = 'direct'

    # API key check for non-interactive modes
    if not args.dry_run and write_mode != 'interactive':
        if not os.environ.get('ANTHROPIC_API_KEY'):
            log('ERROR: ANTHROPIC_API_KEY not set. Required for batch/direct API modes.')
            log('  Set it with: export ANTHROPIC_API_KEY=your-key')
            log('  Or use --interactive to run via claude -p instead.')
            sys.exit(1)

    # The voice guide and key decisions the prompts carry (#596)
    use_briefs = _detect_briefs(project_dir)
    _check_reference_docs(project_dir, use_briefs, coaching, args.dry_run)

    # Build and filter scene list
    metadata_csv = os.path.join(project_dir, 'reference', 'scenes.csv')
    all_ids = build_scene_list(metadata_csv)

    filter_mode, filter_value, filter_value2 = _resolve_filter(args)
    filtered_ids = apply_scene_filter(metadata_csv, all_ids, filter_mode,
                                      filter_value, filter_value2)

    # Filter out already-drafted scenes (unless --force or single)
    pending_ids, skipped = _filter_pending(
        filtered_ids, project_dir, metadata_csv, args.force, filter_mode,
    )

    if not pending_ids:
        log(f'Nothing to draft — all {len(filtered_ids)} matching scenes are '
            f'already drafted ({skipped} skipped).')
        return

    # A scene that didn't pass the gate has no facts in the ledger: drafting
    # after it would draft from an incomplete ledger
    if coaching == 'full' and not args.dry_run:
        _exit_if_gate_pending(project_dir, pending_ids, keep_going=args.keep_going)
    # Cost forecasting
    # Earlier prose needs a valid mode and every scene's place in the book:
    # checked before anything is spent or set up
    from storyforge import ledger
    from storyforge.prompts import prior_prose_mode
    try:
        prior_prose = prior_prose_mode(project_dir, args.prior_prose)
        if prior_prose != 'none':
            ledger.scene_order(project_dir)
    except ValueError as e:
        log(f'ERROR: {e}')
        sys.exit(1)

    scene_forecast = 0.0   # a scene's share of the forecast: reserved from the re-checks
    draft_forecast = 0.0   # its drafting part: charged for a draft the CLI writes
    # A dry run forecasts too (G-027): it is how the author learns what a
    # draft will cost before spending anything
    forecast = _forecast(project_dir, pending_ids, metadata_csv, write_mode, coaching,
                         prior_prose)
    gated = f', ~${forecast.gate:.2f} of it the gate' if forecast.gate else ''
    log(f'Cost forecast: ~${forecast.total:.2f} for {len(pending_ids)} scenes '
        f'(mode {write_mode}{gated}; {forecast.basis})')
    if args.dry_run:
        if not check_threshold(forecast.total):
            log(f'NOTE: that is over the cost threshold (${cost_threshold():g}): a real run '
                f'would stop before drafting. Set STORYFORGE_COST_THRESHOLD higher, or '
                f'write fewer scenes.')
    else:
        draft_forecast = forecast.draft / len(pending_ids)
        scene_forecast = forecast.total / len(pending_ids)
        if not check_threshold(forecast.total):
            # Nothing was drafted: exit 1, so a script or chained command
            # doesn't read the stop as a finished run
            log(f'ERROR: the forecast (~${forecast.total:.2f}) is over the cost threshold '
                f'(${cost_threshold():g}): nothing written. Set STORYFORGE_COST_THRESHOLD higher, '
                f'or write fewer scenes.')
            sys.exit(1)

    # Session start
    from datetime import datetime
    session_start = time.time()
    session_start_iso = datetime.now().strftime('%Y-%m-%dT%H:%M:%S')

    # Branch + PR setup
    if not args.dry_run:
        create_branch('write', project_dir)

        # Advance project phase
        current_phase = read_yaml_field('phase', project_dir)
        if current_phase not in ('drafting', 'evaluation', 'revision', 'complete'):
            yaml_file = os.path.join(project_dir, 'storyforge.yaml')
            _replace_in_file(yaml_file, r'^(\s*phase:).*', r'\1 drafting')
            log('Project phase advanced to: drafting')

        ensure_branch_pushed(project_dir)

        title = (read_yaml_field('project.title', project_dir)
                 or read_yaml_field('title', project_dir) or 'Unknown')
        pr_body = f"""## Drafting Session

**Project:** {title}
**Scenes to draft:** {len(pending_ids)}

### Tasks
"""
        for sid in pending_ids:
            pr_body += f'- [ ] Draft scene {sid}\n'
        pr_body += '- [ ] Review'

        create_draft_pr(
            f'Draft: {title} ({len(pending_ids)} scenes)',
            pr_body, project_dir, 'drafting',
        )

    log('============================================')
    log('Starting Storyforge drafting session')
    title = (read_yaml_field('project.title', project_dir)
             or read_yaml_field('title', project_dir) or 'Unknown')
    log(f'Project: {title}')
    log(f'Mode: {write_mode}')
    log(f'Coaching level: {coaching}')
    log(f'Scenes to draft: {len(pending_ids)} ({skipped} already-drafted skipped)')
    log(f'Scene list: {" ".join(pending_ids)}')
    log('============================================')

    if write_mode == 'batch':
        log('Prior prose: none (batch drafts every scene at once)')
    elif write_mode == 'interactive':
        log('Prior prose: none (interactive drafting has no system prompt to carry it)')
    else:
        log(f'Prior prose: {prior_prose}')
    if write_mode == 'interactive' and not args.dry_run:
        log(f'NOTE: interactive drafting runs through the claude CLI, whose spend this run '
            f'can\'t meter: each draft counts against the cost threshold at its forecast '
            f'(~${draft_forecast:.2f}); the gate\'s calls are metered.')

    # Main drafting
    from storyforge import git as _gitmod
    pushes_failed_before = len(_gitmod.unpushed)
    if write_mode == 'batch' and not args.dry_run:
        outcome = _run_batch_mode(
            pending_ids, project_dir, scenes_dir, log_dir, metadata_csv,
            coaching, use_briefs, args.force, filter_mode,
        )
    else:
        # The threshold is one budget for the run: the re-checks get what
        # drafting actually spent (metered) and the scenes still to draft
        # leave (`costs.RunBudget`)
        from storyforge import api
        from storyforge.costs import RunBudget
        with api.metered() as meter:
            outcome = _run_direct_mode(
                pending_ids, project_dir, scenes_dir, log_dir, metadata_csv,
                coaching, use_briefs, args.force, filter_mode, write_mode,
                args.dry_run, prior_prose=prior_prose, budget=RunBudget(meter),
                scene_forecast=scene_forecast, draft_forecast=draft_forecast,
                keep_going=args.keep_going,
            )

    drafted_count, total_words = outcome.drafted, outcome.words
    failed, recheck_open, uncommitted = outcome.failed, outcome.recheck_open, outcome.uncommitted
    provisional = outcome.provisional

    # Session summary
    elapsed = int(time.time() - session_start)
    mins, secs = divmod(elapsed, 60)

    log('============================================')
    log('Drafting session complete!')
    log(f'Scenes drafted: {drafted_count}/{len(pending_ids)}')
    log(f'Total words: {total_words}')
    log(f'Total time: {mins}m{secs}s')
    log('============================================')

    if not args.dry_run and (drafted_count > 0 or uncommitted):
        print_summary(project_dir, ('draft', 'gate', 'gate-fix'), session_start=session_start_iso)
    if not args.dry_run and uncommitted:
        # The review phase commits (and is paid for), and the drift check
        # pays too: neither runs on a branch whose commits are failing
        log('Skipping the timeline drift check and the review phase: a commit failed '
            '(see below).')
    elif not args.dry_run and drafted_count > 0:
        # Does the new prose agree with the calendar? Reported, never fixed.
        from storyforge.timeline import drift_check
        drift_check(project_dir, [sid for sid in pending_ids
                                  if os.path.isfile(os.path.join(scenes_dir, f'{sid}.md'))])
        run_review_phase('drafting', project_dir)

    from storyforge.prompts import ledger_window_summary
    for note in ledger_window_summary():
        log(f'NOTE: ledger window: {note}')
    report_fallback_replies()

    if failed:
        log(f'ERROR: {len(failed)} scene(s) not drafted:')
        for entry in failed:
            log(f'  {entry}')
        log('Re-run them with `storyforge write --scenes <id>[,<id>...]` '
            '(add --force for a scene already drafted, revised or final).')
    if uncommitted:
        # Drafted and paid for: committing by hand is all they need, not a
        # redraft
        log(f'ERROR: {len(uncommitted)} written but not committed (the files are on disk; '
            f'do not redraft them):')
        for entry in uncommitted:
            log(f'  {entry}')
        log('Fix what stopped the commit (`git status`), then commit them by hand, e.g. '
            '`git add scenes/ reference/ working/ && git commit -m "Draft scenes"`, '
            'and push.')
    unpushed = _gitmod.unpushed[pushes_failed_before:]
    if unpushed:
        log(f'WARNING: the push failed for {", ".join(unpushed)}: the commits are only '
            f'local. Push by hand (`git push -u origin HEAD`).')
    if recheck_open:
        # The drafts are in, but later scenes that depend on what they
        # changed are unchecked: not a finished run (revise and check say
        # the same)
        log('ERROR: re-checks this run owed and did not finish:')
        for entry in recheck_open:
            log(f'  {entry}')
    if provisional:
        # committed and drafted past (--keep-going), but the author's to fix
        log(f'ERROR: {len(provisional)} scene(s) committed provisionally: the gate still '
            f'stops on them, and their findings are the author\'s (listed in '
            f'{gate_pending_path()}):')
        for entry in provisional:
            log(f'  {entry}')
        log('Fix the prose and run `storyforge check --pending`, or accept a verified '
            'contradiction with `storyforge check --accept <id>`.')
    if failed or recheck_open or uncommitted or provisional:
        sys.exit(1)


# ============================================================================
# Internal helpers
# ============================================================================

class DraftOutcome(NamedTuple):
    """What `_run_direct_mode` / `_run_batch_mode` did."""
    drafted: int
    words: int
    #: each scene not drafted, and why
    failed: list
    #: each re-check this run owed and didn't finish
    recheck_open: list = []
    #: each scene (or re-check) written but whose commit failed: it needs a
    #: commit by hand, not a redraft
    uncommitted: list = []
    #: each scene `--keep-going` committed provisionally, and why (#556)
    provisional: list = []

def _check_reference_docs(project_dir: str, use_briefs: bool, coaching: str,
                          dry_run: bool) -> None:
    """The voice guide and key decisions the drafting prompt carries (#596).

    One that exists but can't be read stops the run (ERROR, exit 1, naming
    it; SF-1): the prompt must not go out as if it weren't there. With no
    voice guide to follow (missing, init's template, empty, or only
    persistent-prompt.md, which the brief-based prompt doesn't read), a
    full-coaching run drafts no prose (SF-2): the drafts would have no voice.
    A dry run and coach/strict (which write briefs, not prose) say so and go
    on. Key decisions left out (missing, template, empty) are a NOTE: a book
    may have none (SF-4).
    """
    from storyforge.common import VOICE_GUIDE_REMEDY, doc_state, resolve_voice_guide
    voice = resolve_voice_guide(project_dir, briefs=use_briefs)
    for detail in voice.skipped:
        log(f'WARNING: {detail}; passed over for the next voice guide.')
    decisions = doc_state(project_dir, 'reference/key-decisions.md')
    for state in (voice, decisions):
        if state.kind == 'unreadable':
            log(f'ERROR: {state.detail}. Fix the file (permissions, or save it as '
                'UTF-8) and run again; nothing was drafted.')
            sys.exit(1)
    if decisions.kind != 'ok':
        log(f'NOTE: {decisions.detail}, so the drafting prompts carry no key decisions.')
    if voice.kind == 'ok':
        log(f'Voice guide: {voice.path}')
        return
    remedy = VOICE_GUIDE_REMEDY
    if voice.kind == 'unread':
        remedy = (f'move its text into reference/voice-guide.md, or name it in '
                  f'storyforge.yaml (artifacts.voice_guide.path), or run {VOICE_GUIDE_REMEDY}')
    if coaching == 'full' and not dry_run:
        log(f'ERROR: {voice.detail}: the drafting prompt would have no voice guide, and the '
            f'drafts no voice to follow. Fill it first: {remedy}. Nothing was drafted.')
        sys.exit(1)
    why = ('a real run stops here' if coaching == 'full'
           else f'{coaching} coaching writes no prose, so it goes on')
    log(f'WARNING: {voice.detail}: the prompts have no voice guide ({why}). '
        f'Fill it: {remedy}.')


def _resolve_filter(args) -> tuple:
    """Resolve CLI args to (mode, value, value2)."""
    if args.scenes:
        return ('scenes', args.scenes, None)
    if args.act:
        return ('act', args.act, None)
    if args.from_seq:
        return ('from_seq', args.from_seq, None)
    positional = args.positional
    if len(positional) == 0:
        return ('all', None, None)
    if len(positional) == 1:
        return ('single', positional[0], None)
    if len(positional) == 2:
        return ('range', positional[0], positional[1])
    log('ERROR: Too many positional arguments')
    sys.exit(1)


def _gate_blockers(project_dir: str, scene_id: str, keep_going: bool = False,
                   narrow: bool = False) -> list[str]:
    """Scenes waiting on the gate (`gate.pending`) that come before
    `scene_id` in reading order, as `id: reason`. A pending id that is no
    longer a scene can't block; it is named in a WARNING instead. With
    `keep_going`, a scene committed provisionally (`gate.PROVISIONAL`: its
    facts are in the ledger) doesn't block either. `narrow` (revise, #633)
    keeps only the scenes `scene_id` waits on (`GateBlockers`).

    Raises:
        gate.GateError: `gate.PENDING_PATH` is malformed."""
    return GateBlockers(project_dir, keep_going=keep_going, narrow=narrow).of(scene_id)


#: The pending commands whose scene's facts may still be what its prose
#: says: a re-check or a check of the prose failed, and neither commits or
#: removes a fact (#633)
_REREAD_COMMANDS = ('recheck-failed', 'advisor')


class GateBlockers:
    """Which earlier scenes waiting on the gate stop a scene from being
    drafted or gated (`of`), read once for several scenes.

    By default (`write`) every earlier pending scene does: the ledger lacks
    what it says. With `narrow` (revise, #633) an earlier pending scene
    stops a scene only when
    - it isn't a re-check or check that failed (`recheck-failed`,
      `advisor`) on prose unchanged since its facts were read
      (`gate.gated_prose`) with those facts still in the ledger: a failed
      re-reading of the same prose doesn't make the ledger wrong; and
    - one of the scene's binding facts depends on one of its commitments
      (`ledger.dependents`, run from the waiting scene's facts), named in
      the line ("waits on it: fact F ... depends on its fact G ..."). When
      either scene has no commitments in the ledger, what depends on what
      can't be told, and it stops the scene as before.
    A ledger or registry that can't be read narrows nothing (WARNING)."""

    def __init__(self, project_dir: str, keep_going: bool = False, narrow: bool = False):
        from storyforge import gate, ledger
        self.project_dir = project_dir
        self.keep_going = keep_going
        self.waiting = gate.pending(project_dir)
        self.order = ledger.scene_order(project_dir)
        gone = sorted(s for s in self.waiting if s not in self.order)
        if gone:
            log(f'WARNING: {gate.PENDING_PATH} lists id(s) that are no longer scenes: '
                f'{", ".join(gone)}. Delete those rows.')
        self.narrow = narrow and bool(self.waiting) and self._load()
        self._through: dict[str, bool] = {}
        self._depending: dict[str, list[str]] = {}

    def _load(self) -> bool:
        from storyforge import ledger
        try:
            rows = ledger.load(self.project_dir)
            self.names, _ = ledger.subject_names(self.project_dir)
        except (ledger.LedgerError, ledger.NotMigratedError, OSError,
                UnicodeDecodeError) as e:
            log(f'WARNING: {e}; every earlier scene waiting on the gate holds back the '
                f'later ones, whatever they depend on.')
            return False
        self.rows = rows
        self.facts: dict[str, list[dict[str, str]]] = {}
        for r in rows:
            if ledger.is_commitment(r) and r.get('status') != 'planned':
                self.facts.setdefault((r.get('scene_id') or '').strip(), []).append(r)
        return True

    def of(self, scene_id: str) -> list[str]:
        """The earlier pending scenes that stop `scene_id`, in reading order,
        as `id: reason` (narrowed: with why it waits on each)."""
        from storyforge import gate
        at = self.order.get(scene_id, 0)
        earlier = sorted(
            (s for s, row in self.waiting.items()
             if s in self.order and s != scene_id and self.order[s] < at
             and not (self.keep_going and row['command'] == gate.PROVISIONAL)),
            key=self.order.get)
        out = []
        for s in earlier:
            line = f'{s}: {self.waiting[s]["reason"]}'
            if not self.narrow:
                out.append(line)
                continue
            if self._let_through(s):
                continue
            why = self._waits(scene_id, s)
            if why:
                out.append(f'{line} ({scene_id} waits on it: {why})')
        return out

    def _let_through(self, sid: str) -> bool:
        """Whether `sid`'s failed re-reading leaves its facts as its prose says."""
        if sid not in self._through:
            from storyforge import gate
            ok = False
            if self.waiting[sid]['command'] in _REREAD_COMMANDS and self.facts.get(sid):
                earlier, _ = gate.gated_prose(self.project_dir, sid)
                try:
                    with open(os.path.join(self.project_dir, 'scenes', f'{sid}.md'),
                              encoding='utf-8') as f:
                        prose = f.read()
                except (OSError, UnicodeDecodeError):
                    prose = None
                ok = earlier is not None and prose is not None \
                    and earlier.rstrip() == prose.rstrip()
            self._through[sid] = ok
        return self._through[sid]

    def _waits(self, scene_id: str, sid: str) -> str:
        """Why `scene_id` waits on the earlier `sid` ('' when it doesn't)."""
        from storyforge import ledger
        theirs = self.facts.get(sid, [])
        if not theirs:
            return (f'{sid}\'s facts are not in the ledger, so what depends on it '
                    f'can\'t be told')
        mine = [r for r in self.facts.get(scene_id, []) if r.get('status') == 'binding']
        if not mine:
            return (f'{scene_id} has no binding facts in the ledger to tell whether any '
                    f'depends on {sid}')
        if sid not in self._depending:
            self._depending[sid] = ledger.dependents(
                self.rows, [r['id'] for r in theirs], self.order, names=self.names).scenes
        if scene_id not in self._depending[sid]:
            return ''
        for f in theirs:
            if (f.get('resolves') or '').strip() == scene_id:
                return f'its fact {f["id"]} ({_said(f)}) ends in {scene_id}'
            for r in mine:
                if scene_id in ledger.dependents([f, r], [f['id']], self.order,
                                                 names=self.names).scenes:
                    return (f'fact {r["id"]} ({_said(r)}) depends on its fact '
                            f'{f["id"]} ({_said(f)})')
        return f'a fact of {scene_id} depends on its facts'


def _said(row: dict[str, str], width: int = 60) -> str:
    """A fact's statement, quoted and cut to `width` characters."""
    text = ' '.join((row.get('statement') or '').split())
    return '"' + (text if len(text) <= width else text[:width - 3] + '...') + '"'


def _exit_if_gate_pending(project_dir: str, to_draft: list[str],
                          keep_going: bool = False) -> None:
    """Exit 1, before anything is spent, when a scene waiting on the gate
    comes before the first scene to draft. One between scenes to draft
    stops the run when drafting reaches it (`_run_direct_mode`). Drafting
    the waiting scene itself is allowed: that is how it gets through."""
    from storyforge import gate, ledger
    order = ledger.scene_order(project_dir)
    try:
        blocking = _gate_blockers(project_dir, min(to_draft, key=lambda s: order.get(s, 0)),
                                  keep_going=keep_going)
    except gate.GateError as e:
        log(f'ERROR: {e}')
        sys.exit(1)
    if blocking:
        _log_blockers(blocking)
        sys.exit(1)


def _log_blockers(blocking: list[str]) -> None:
    log(f'ERROR: {len(blocking)} earlier scene(s) did not pass the gate, so the ledger '
        f'does not hold what they say:')
    for line in blocking:
        log(f'  {line}')
    log('Fix the prose and run `storyforge check <id>`, or redraft it with '
        '`storyforge write --scenes <id> --force`.')


def _gate_drafted_scene(project_dir: str, scene_id: str, scene_file: str, command: str,
                        log_dir: str, before=None, keep_going: bool = False) -> tuple[bool, str]:
    """Gate the scene just written to `scene_file` (fix and re-check, up to
    `gate.FIX_ROUNDS` times; plan §3.2), writing the fixed prose back. Returns
    (passed, why not). A scene
    that doesn't pass, or that the gate couldn't finish, is listed in
    `gate.pending` with the first problems; its prose stays. On a pass, the
    later scenes whose facts depend on what it changed are listed for a
    re-check (the caller runs `run_recheck` once the scene is committed).
    `before` is the book before this run (`gate.snapshot`, taken once per
    run; None: nothing counts as already there): a contradiction already in
    it is reported, not blocking (`gate.gate_scene`). With `keep_going`
    (#556), a scene that fails only on the check's findings is committed
    provisionally (`gate.commit_provisional`, listed `gate.PROVISIONAL`:
    `is_provisional` tells the caller); it still returns False."""
    from storyforge import gate
    with open(scene_file, encoding='utf-8') as f:
        prose = f.read()
    # a revision pass often leaves the facts alone; a redraft rarely does
    stale = {'redraft': ' Its earlier version\'s facts are still in the ledger and no '
                        'longer match the prose.',
             'revise': ' Its earlier version\'s facts are still in the ledger and may no '
                       'longer match the prose.'}.get(command, '')
    log(f'Gating scene {scene_id}...')
    try:
        out = gate.gate_and_fix(project_dir, scene_id, command=command, prose=prose,
                                log_dir=os.path.join(log_dir, 'gate'), before=before)
    except gate.GateError as e:
        if e.log_dir:
            log(f'  Gate logs: {os.path.relpath(e.log_dir, project_dir)}')
        if e.first is not None:
            for line in gate.report_lines(e.first):
                log(f'  (first check) {line}')
        return False, _pend(project_dir, scene_id, command,
                            f'the gate could not finish: {e}.{stale}')
    except (KeyboardInterrupt, SystemExit):
        raise
    except Exception as e:   # a bug or an I/O failure: the prose is on disk, unchecked
        return False, _pend(project_dir, scene_id, command,
                            f'the gate failed unexpectedly ({type(e).__name__}: {e}).{stale}')
    if out.fixed:
        from storyforge.illustrations import keep_markers
        with open(scene_file, 'w', encoding='utf-8') as f:
            f.write(keep_markers(project_dir, scene_id, prose, out.prose,
                                 "the gate's fix", log))
    if out.log_dir:
        log(f'  Gate logs: {os.path.relpath(out.log_dir, project_dir)}')
    for n, r in enumerate(out.rounds, start=1):
        log(f'  Fix round {n}: {len(r.problems)} problem(s) sent, {len(r.edits)} edit(s); '
            f're-checked.')
    for note in out.notes:
        log(f'  NOTE: {note}')
    # #598 (#602's review SF-1, SF-2): a misquote is the extractor's, said in
    # the log and in the pending reason the author reads
    regate = out.reextraction.summary() if out.reextraction else ''
    if regate:
        log(f'  NOTE: {regate}')
    lines = gate.report_lines(out.result)
    for line in lines:
        log(f'  {line}')
    if out.result.passed:
        log(f'  Gate passed: {len(out.result.proposed)} fact(s) added to the ledger.')
        report_changes(out.result)
        if out.result.recheck:
            log(f'  {scene_id} changed {len(out.result.changed)} fact(s) later scenes depend '
                f'on; listed for a re-check: {", ".join(out.result.recheck)}')
        return True, ''
    problems = gate.blocking_lines(lines)
    # plan conflicts alone aren't sent to the fix (`gate.gate_and_fix`)
    fixes = 'one fix' if len(out.rounds) <= 1 else f'{len(out.rounds)} fixes'
    left_to_author = out.result.plan_conflicts and not gate.problems_to_fix(out.result)
    tried = ('not fixed (plan conflicts: the author\'s)'
             if out.first.plan_conflicts and not gate.problems_to_fix(out.first)
             else f'after {fixes} (what is left is plan conflicts: the author\'s)'
             if left_to_author else f'after {fixes}')
    if out.discarded == 1 and not out.rounds:
        tried = ('not fixed: the fix was discarded, the scene left as written (the log '
                 'says why)')
    elif out.discarded:
        tried += f' (fix round {out.discarded} was discarded; the log says why)'
    if regate:
        tried += f' [{regate}]'
    if out.blocked_stale:   # SF-1 (#504's review): said where the author looks
        tried += (f' [{out.blocked_stale}: `check --accept` refuses this scene until '
                  f'`storyforge check {scene_id}` records it again]')
    why = (f'{len(problems)} problem(s) {tried}: '
           + ' / '.join(problems[:3]) + ('; ...' if len(problems) > 3 else '') + stale)
    if keep_going:
        cannot = gate.can_commit_provisionally(out.result)
        if cannot:
            log(f'  Not committed provisionally: {cannot}.')
        else:
            try:
                gate.commit_provisional(project_dir, out.result, f'provisional: {why}')
            except gate.GateError as e:
                log(f'  Not committed provisionally: {e}')
            else:
                for line in gate.report_lines(out.result):
                    if line.startswith(('COMMITTED', 'NOTE (not recorded: states what')):
                        log(f'  {line}')
                report_changes(out.result)
                return False, f'provisional: {why}'
    return False, _pend(project_dir, scene_id, command, why)


def is_provisional(project_dir: str, scene_id: str) -> bool:
    """Whether `scene_id` is listed as committed provisionally."""
    from storyforge import gate
    try:
        return gate.pending(project_dir).get(scene_id, {}).get('command') == gate.PROVISIONAL
    except gate.GateError:
        return False


def _already_drafted(scenes_dir: str, scene_id: str) -> str:
    """Why the run's skip rule keeps a scene ('' when it drafts it): over 200
    words of prose, or any illustration marker. The words are prose (#280),
    and a marker means the scene was illustrated, which only drafted prose
    is, so a short illustrated scene is kept rather than redrafted out from
    under its illustrations (#610's review, SF-W). `--force`, or naming the
    scene, redrafts it and keeps the markers (`_extract_scene_from_response`)."""
    from storyforge.illustrations import all_marker_ids, read_scene_raw
    text = read_scene_raw(os.path.dirname(scenes_dir), scene_id)
    if text is None:
        return ''
    words = count_prose_words(text)
    if words > 200:
        return f'already has {words} words'
    marked = all_marker_ids(text)
    if marked:
        return (f'has {words} words and {len(marked)} illustration marker(s); '
                f'--force (or naming the scene) redrafts it and keeps them')
    return ''


def _drafted(scenes_dir: str, scene_id: str) -> bool:
    """Whether the run's skip rule keeps a scene (`_already_drafted`)."""
    return bool(_already_drafted(scenes_dir, scene_id))


def report_changes(result) -> None:
    """Log, after a pass, what the scene changed that no re-check can cover:
    facts whose dependents can't all be traced, later scenes that depend on
    it but can't be re-checked, and the author's registry links to facts it
    removed (CLAUDE.md: every path that can't check something says so)."""
    for fid, why in result.unrelated.items():
        log(f'  WARNING: {result.scene_id} changed {fid}, whose dependents can\'t all be '
            f'found ({why}): check the later scenes that mention it with `storyforge check`.')
    for note in getattr(result, 'name_notes', []):
        log(f'  WARNING: the scenes depending on what {result.scene_id} changed were matched '
            f'on fewer names: {note}')
    for note in getattr(result, 'prose_notes', []):
        log(f'  NOTE: {note}')
    if result.not_rechecked:
        log(f'  NOTE: later scenes that depend on what {result.scene_id} changed but can\'t be '
            f're-checked now: {", ".join(result.not_rechecked)}')
    if result.dangling:
        log(f'  WARNING: registry facts link to commitments {result.scene_id} no longer makes; '
            f'fix the links in reference/commitments.csv: {", ".join(result.dangling)}')


def run_recheck(project_dir: str, log_dir: str, skip: set[str] | frozenset[str] = frozenset(),
                spent_before: float = 0.0):
    """Re-gate the scenes pending a re-check (`gate.recheck_pending`: reading
    order, report and stop, under the cost threshold counting `spent_before`)
    and log the outcome. Returns the `gate.Recheck`, or None when nothing was
    pending. A scene that fails stays listed, and `write`/`revise` won't
    draft past it."""
    from storyforge import gate
    if not gate.recheck_queue(project_dir, skip):
        return None
    run = gate.recheck_pending(project_dir, log_dir=log_dir, skip=skip,
                               spent_before=spent_before)
    for sid in run.passed:
        log(f'  Re-check passed: {sid}')
    for note in run.notes:   # what a passing re-check didn't record or applied (#599, #622)
        log(f'  {note}')
    if run.failed:
        log(f'  ERROR: the re-check of {run.failed} did not pass: {run.why}. It stays in '
            f'{gate_pending_path()}' + (f', and so do {", ".join(run.left)}' if run.left else '')
            + '; fix it with revise or by hand'
            + (f', or accept its contradictions (`storyforge check --accept {run.failed}`)'
               if run.result is not None
               and any(f.kind == 'contradiction' for f in run.result.findings) else '')
            + ', then `storyforge check --pending`.')
    return run


def budgeted_recheck(project_dir: str, log_dir: str, skip: set[str] | frozenset[str],
                     budget, reserved: float = 0.0):
    """`run_recheck` under the run's one cost budget (`costs.RunBudget`):
    the re-checks get what the run's spend so far and `reserved` (the
    forecast of the work it still owes) leave of the threshold. Returns
    `run_recheck`'s answer."""
    from storyforge import api
    before = budget.committed(reserved)
    with api.metered() as meter:   # told apart from the rest of the run's spend
        run = run_recheck(project_dir, log_dir, skip, spent_before=before)
    budget.record(run, actual=meter.cost())
    return run


def _interactive_problem(scene_file: str, before: str) -> str:
    """Why the CLI's scene can't be gated ('' when it can): it wrote no file,
    left it unchanged, or wrote fewer than `_MIN_SCENE_WORDS` words."""
    if not os.path.isfile(scene_file):
        return 'the CLI wrote no scene file'
    with open(scene_file, encoding='utf-8') as f:
        text = f.read()
    if text == before:
        return 'the CLI left the scene file unchanged'
    words = count_prose_words(text)   # the floor counts prose, as the API path's does
    if words < _MIN_SCENE_WORDS:
        return f'only {words} words (the floor is {_MIN_SCENE_WORDS})'
    return ''


def _keep_cli_markers(project_dir: str, scene_id: str, scene_file: str, before: str) -> None:
    """Put back the illustration markers `before` (the scene the CLI
    rewrote) carried and the CLI's prose dropped (#610's review, SF-W)."""
    from storyforge.illustrations import keep_markers
    with open(scene_file, encoding='utf-8') as f:
        written = f.read()
    kept = keep_markers(project_dir, scene_id, before, written, 'the CLI', log)
    if kept != written:
        with open(scene_file, 'w', encoding='utf-8') as f:
            f.write(kept)


def _pend(project_dir: str, scene_id: str, command: str, why: str) -> str:
    """List the scene in `gate.pending` (saying so if that fails) and return `why`."""
    from storyforge import gate
    try:
        gate.mark_pending(project_dir, scene_id, command, why)
    except (gate.GateError, OSError) as e:
        log(f'ERROR: could not list {scene_id} in {gate.PENDING_PATH}: {e}. Add it by '
            f'hand, or check it before drafting anything after it.')
    return why


def _filter_pending(filtered_ids, project_dir, metadata_csv, force, filter_mode):
    """Filter out already-drafted scenes. Returns (pending_ids, skipped_count)."""
    from storyforge.prompts import get_scene_status

    pending = []
    skipped = 0

    for sid in filtered_ids:
        status = get_scene_status(sid, project_dir)
        if status == 'unreadable':
            log(f'WARNING: scenes/{sid}.md can\'t be read (no permission, or not UTF-8), '
                f'so it is not drafted over. Fix or remove the file, then run write again.')
            skipped += 1
        elif status in ('drafted', 'revised', 'final'):
            if force or filter_mode == 'single':
                pending.append(sid)
                if force:
                    log(f"NOTE: Scene {sid} has status '{status}' — re-drafting (--force)")
                if filter_mode == 'single':
                    log(f"NOTE: Scene {sid} has status '{status}' but was explicitly requested")
            else:
                skipped += 1
        else:
            pending.append(sid)

    return pending, skipped


def _forecast(project_dir: str, pending_ids: list[str], metadata_csv: str,
              write_mode: str, coaching: str, prior_prose: str):
    """`costs.forecast_write` for this run (#563). Every drafted scene is
    gated at `full` coaching, and the gate (extraction, the persistence
    check, the check's readings, a fix) costs several times the draft
    (F-151): a gate run is priced as a re-check. A direct draft is sent
    the shared context and, by `prior_prose`, the earlier prose, both read
    from cache: the token model counts them (on Gawain, about 133k
    cache-read tokens a draft)."""
    from storyforge import costs, gate
    try:
        model = select_model('drafting')
    except RuntimeError as e:
        # a dry run without an API key can't ask the Models API for the
        # newest model (a real run has stopped on the key already): price
        # at the tier's newest listed one
        from storyforge.common import _TASK_TIER
        model = costs._TIER_FALLBACK[_TASK_TIER['drafting']]
        log(f'NOTE: the forecast prices drafts at {model} ({e})')
    avg_words = _avg_word_count(metadata_csv)
    earlier: dict[str, int] = {}
    shared = 0
    if write_mode == 'direct':
        earlier = _forecast_earlier_words(project_dir, pending_ids, prior_prose, avg_words)
        from storyforge.common import build_shared_context
        from storyforge.series import SeriesError
        from storyforge.source import SourceError
        try:
            shared = sum(len(b.get('text', '')) for b in
                         build_shared_context(project_dir, model)) // 4
        except SeriesError:
            raise   # never a forecast without the canon (main checks it first)
        except (OSError, SourceError) as e:   # a source not imported, ...
            log(f'WARNING: the forecast leaves out the shared context ({e})')
    return costs.forecast_write(
        project_dir, pending_ids, avg_words, model,
        gate_per_scene=(gate.WRITE_GATE_COST_PER_SCENE + _source_check_cost(project_dir)
                        if coaching == 'full' else 0.0),
        earlier_words=earlier, shared_tokens=shared, batch=write_mode == 'batch')


def _source_check_cost(project_dir: str) -> float:
    """The gate's source check per scene in a faithful adaptation (#557),
    else 0."""
    from storyforge import gate_source
    ctx = gate_source.setup(project_dir)
    return gate_source.COST_PER_SCENE if ctx is not None and ctx.active() else 0.0


def _forecast_earlier_words(project_dir: str, pending_ids: list[str], prior_prose: str,
                            avg_words: int) -> dict[str, int]:
    """The words of earlier prose each pending scene will be drafted with,
    for the forecast: in `full` mode the manuscript before it (a scene
    still to draft at `avg_words`), up to `prompts.FULL_MAX_WORDS`; in
    `window` mode about two scenes."""
    if prior_prose == 'none':
        return {}
    if prior_prose == 'window':
        return {s: 2 * avg_words for s in pending_ids}
    from storyforge import ledger
    from storyforge.prompts import FULL_MAX_WORDS
    order = ledger.scene_order(project_dir)
    pending = set(pending_ids)
    out, words = {}, 0
    for sid in sorted(order, key=order.get):
        if sid in pending:
            out[sid] = min(words, FULL_MAX_WORDS)
        path = os.path.join(project_dir, 'scenes', f'{sid}.md')
        if sid in pending or not os.path.isfile(path):
            words += avg_words if sid in pending else 0
        else:
            words += len(read_scene_prose(path).split())
    return out


def _avg_word_count(metadata_csv: str) -> int:
    """Calculate average target word count from metadata CSV."""
    from storyforge.csv_cli import get_column
    values = get_column(metadata_csv, 'target_words')
    nums = []
    for v in values:
        try:
            n = int(v)
            if n > 0:
                nums.append(n)
        except (ValueError, TypeError):
            pass
    return int(sum(nums) / len(nums)) if nums else 2000


def _detect_briefs(project_dir: str) -> bool:
    """Check if scene briefs exist for brief-aware drafting."""
    briefs_csv = os.path.join(project_dir, 'reference', 'scene-briefs.csv')
    if not os.path.isfile(briefs_csv):
        return False
    with open(briefs_csv) as f:
        lines = [l.strip() for l in f if l.strip()]
    # At least one non-empty data row
    for line in lines[1:]:
        fields = line.split('|')
        if len(fields) > 1 and any(f.strip() for f in fields[1:]):
            log(f'Detected scene briefs — using brief-aware drafting')
            return True
    return False


def _build_prompt(scene_id: str, project_dir: str, coaching: str,
                  use_briefs: bool, system_context: bool = False,
                  rewrite: bool = False) -> str:
    """Build the drafting prompt for a scene.

    Args:
        scene_id: Scene identifier.
        project_dir: Project root directory.
        coaching: Coaching level (full/coach/strict).
        use_briefs: Whether to use brief-aware prompts.
        system_context: When True, shared reference material is provided via
            the API system parameter and should not be inlined in the prompt.
        rewrite: Treat a scene that has prose as a rewrite (rethink plan
            §3.4): at `full` coaching with briefs, its prose on disk
            (`current_prose`) goes in the prompt as a voice reference only.
            A scene with no prose, other coaching levels, and the prompt
            without briefs are unchanged.

    Raises:
        ValueError: with `rewrite`, the scene's file can't be read.
    """
    from storyforge.common import get_plugin_dir
    plugin_dir = get_plugin_dir()

    if use_briefs:
        from storyforge.prompts import build_scene_prompt_from_briefs
        from storyforge.elaborate import get_scene
        scene = get_scene(scene_id, os.path.join(project_dir, 'reference'))
        deps = scene.get('continuity_deps', '') if scene else ''
        dep_scenes = [d.strip() for d in deps.split(';') if d.strip()] if deps else None
        voice = current_prose(project_dir, scene_id) if rewrite and coaching == 'full' else ''
        return build_scene_prompt_from_briefs(scene_id, project_dir, plugin_dir,
                                              coaching, dep_scenes=dep_scenes,
                                              system_context=system_context,
                                              voice_reference=voice)
    else:
        from storyforge.prompts import build_scene_prompt
        return build_scene_prompt(scene_id, project_dir, coaching,
                                  api_mode=True,
                                  system_context=system_context)


def current_prose(project_dir: str, scene_id: str) -> str:
    """The scene's prose on disk without illustration markers (they are
    never prose), '' when it has none (no file, or an empty one).

    Raises:
        ValueError: the file is there but can't be read (not UTF-8, no
            permission), naming it: a rewrite must not lose its voice
            reference unnoticed.
    """
    path = os.path.join(project_dir, 'scenes', f'{scene_id}.md')
    if not os.path.isfile(path):
        return ''
    try:
        return read_scene_prose(path).strip()
    except (OSError, UnicodeDecodeError) as e:
        raise ValueError(f'could not read {path} for the rewrite\'s voice reference: {e}') from e


def _output_file(project_dir: str, scene_id: str, coaching: str) -> str:
    """Where a reply for ``scene_id`` is saved: the scene file at coaching
    ``full``; the brief or constraint list in working/coaching/ otherwise
    (the coach and strict prompts ask for that, not prose)."""
    if coaching == 'coach':
        return os.path.join(project_dir, 'working', 'coaching', f'brief-{scene_id}.md')
    if coaching == 'strict':
        return os.path.join(project_dir, 'working', 'coaching', f'constraints-{scene_id}.md')
    return os.path.join(project_dir, 'scenes', f'{scene_id}.md')


def _extract_scene_from_response(log_file: str, out_file: str,
                                 prose: bool = True) -> str:
    """Write the reply in API response ``log_file`` to ``out_file``.

    Returns '' when written, otherwise why the reply must not be written, and
    ``out_file`` is left as it was: the log could not be read, the model
    refused or was cut off (``api.stop_problem``), or the reply is empty. With
    ``prose`` (a scene, not a coaching brief) the reply must also pass
    ``parsing.unsafe_scene_reason`` and have at least ``_MIN_SCENE_WORDS``.

    Before this a reply cut off mid-sentence passed the 100-word floor and was
    committed as a drafted scene, and batch mode could not tell: its saved
    response had no ``stop_reason``. Coach and strict replies were written
    over the scene's prose.
    """
    from storyforge.parsing import (
        extract_single_scene, clean_scene_content, unsafe_scene_reason,
    )
    try:
        with open(log_file) as f:
            response = json.load(f)
    except (OSError, ValueError) as e:
        return f'could not read the response log ({e})'
    problem = stop_problem(response)
    if problem:
        return problem

    text = extract_text_from_file(log_file)
    if not text.strip():
        return 'the API response is empty'

    if prose:
        extracted = extract_single_scene(text)
        content = extracted if extracted else text
        # Strip writing-agent artifacts (scene title headers, continuity blocks)
        content = clean_scene_content(content)

        old_text = None
        if os.path.isfile(out_file):
            with open(out_file) as f:
                old_text = f.read()
        reason = unsafe_scene_reason(content, old_text)
        if reason:
            return reason
        words = count_prose_words(content)
        if words < _MIN_SCENE_WORDS:
            return f'only {words} words (the floor is {_MIN_SCENE_WORDS})'
        if old_text:
            # a redraft of an illustrated scene keeps its illustrations
            # (#610's review, SF-W): the model has no reason to copy a marker
            from storyforge.illustrations import keep_markers
            content = keep_markers(os.path.dirname(os.path.dirname(os.path.abspath(out_file))),
                                   os.path.basename(out_file)[:-len('.md')],
                                   old_text, content, 'the redraft', log)
    else:
        content = text

    os.makedirs(os.path.dirname(out_file), exist_ok=True)
    with open(out_file, 'w') as f:
        f.write(content)
    return ''


_MIN_SCENE_WORDS = 100


def gate_prose_path() -> str:
    from storyforge import gate
    return gate.PROSE_PATH


def gate_source_fix_path() -> str:
    from storyforge import gate
    return gate.SOURCE_FIX_PATH


def gate_pending_path() -> str:
    from storyforge.gate import PENDING_PATH
    return PENDING_PATH


from storyforge.git import CommitError  # noqa: E402  (raised by `_commit`)


def _commit(project_dir: str, message: str, paths: list[str]) -> None:
    """`git.commit_or_raise`: a failed commit raises `CommitError` with
    git's reason (and leaves nothing staged), and the caller stops
    committing, since the next commit's paths (`reference/`,
    `working/logs/`, `working/coaching/`) would sweep these files in under
    the wrong message. Nothing to commit is not a failure; a failed push
    stays a WARNING (the commit is made) and goes in the closing summary."""
    from storyforge import git
    git.commit_or_raise(project_dir, message, paths)


def _verify_and_commit_scene(scene_id: str, project_dir: str, scenes_dir: str,
                             metadata_csv: str, coaching: str,
                             head_before: str, written_by: str = '',
                             gate_failed: bool = False, commit: bool = True) -> tuple:
    """Verify and commit a drafted scene. Returns (word_count, success).
    ``written_by`` names the model the refusal fallback used, for the commit
    message. ``gate_failed``: the scene didn't pass the gate, which the
    commit message says, and its PR task stays unticked. When something else
    already committed (the interactive CLI), the gate's files are committed
    on their own. A commit that fails raises `CommitError` (the scene is
    verified and its files written); ``commit=False`` (batch mode after a
    failed commit) verifies and writes without committing."""
    scene_file = os.path.join(scenes_dir, f'{scene_id}.md')
    word_count = 0

    if coaching in ('coach', 'strict'):
        coaching_file = _output_file(project_dir, scene_id, coaching)
        if not os.path.isfile(coaching_file):
            log(f'ERROR: Coaching output not created: {coaching_file}')
            return 0, False
        with open(coaching_file) as f:
            word_count = len(f.read().split())
    else:
        if not os.path.isfile(scene_file):
            log(f'ERROR: Scene file not created: {scene_file}')
            return 0, False
        word_count = len(read_scene_prose(scene_file).split())
        if word_count < _MIN_SCENE_WORDS:
            log(f'ERROR: Scene file suspiciously short ({word_count} words): {scene_file}')
            return 0, False
        update_field(metadata_csv, scene_id, 'word_count', str(word_count))
        update_field(metadata_csv, scene_id, 'status', 'drafted')
        log(f'Updated metadata.csv: {scene_id} word_count={word_count} status=drafted')

    # Check if commit already happened
    from storyforge.git import _git
    r = _git(project_dir, 'rev-parse', 'HEAD', check=False)
    head_after = r.stdout.strip() if r.returncode == 0 else 'none'

    if head_before == head_after:
        log(f'Creating commit for scene {scene_id}...')
        if coaching in ('coach', 'strict'):
            paths = ['working/coaching/', 'working/logs/']
            msg = f'{coaching.capitalize()}: {scene_id}'
        else:
            paths = [f'scenes/{scene_id}.md', 'reference/', 'working/logs/',
                     'working/audit-log.csv', 'working/.audit-snapshot.csv',
                     gate_pending_path(), gate_prose_path(), gate_source_fix_path()]
            msg = f'Draft scene {scene_id}'
        if written_by:
            msg += f' (refusal fallback: written by {written_by})'
        if gate_failed:
            msg += f' (did not pass the gate; listed in {gate_pending_path()})'

        if not commit:
            return word_count, True
        _commit(project_dir, msg, paths)
    elif coaching == 'full':
        if not commit:
            return word_count, True
        _commit(project_dir, f'Gate scene {scene_id}',
                [f'scenes/{scene_id}.md', 'reference/', 'working/audit-log.csv',
                 'working/.audit-snapshot.csv', gate_pending_path(), gate_prose_path(),
                 gate_source_fix_path()])

    # Push
    from storyforge.git import _push
    _push(project_dir)   # checked: a failed push is a WARNING

    r = _git(project_dir, 'rev-parse', '--short', 'HEAD', check=False)
    commit_short = r.stdout.strip() if r.returncode == 0 else 'unknown'
    log(f'SUCCESS: Scene {scene_id} — {word_count} words, commit {commit_short}')

    if not gate_failed:
        update_pr_task(f'Draft scene {scene_id}', project_dir)

    return word_count, True


def _run_batch_mode(pending_ids, project_dir, scenes_dir, log_dir,
                    metadata_csv, coaching, use_briefs, force, filter_mode):
    """Run batch API mode. Returns a `DraftOutcome`: ``failed`` names each
    scene not drafted and why, ``uncommitted`` each written but not
    committed. A bad reply skips only
    its scene; its response is kept in ``log_dir``. A refused scene is
    retried once directly with the refusal fallback, which the Batches API
    does not accept."""
    log('Building prompts for batch submission...')

    batch_file = os.path.join(log_dir, f'drafting-batch-{os.getpid()}.jsonl')
    model = select_model('drafting')
    batch_scene_ids = []
    prompts: dict[str, str] = {}

    # Build shared context once for prompt caching across all scenes
    from storyforge.common import build_shared_context
    from storyforge.api import build_batch_request
    system = build_shared_context(project_dir, model=model)

    for scene_id in pending_ids:
        scene_file = os.path.join(scenes_dir, f'{scene_id}.md')

        # Skip already-drafted unless --force
        if not force and filter_mode != 'single':
            kept = _already_drafted(scenes_dir, scene_id)
            if kept:
                log(f'Scene {scene_id} {kept}, skipping')
                continue

        try:   # as direct mode: prose on disk makes it a rewrite
            prompt = _build_prompt(scene_id, project_dir, coaching, use_briefs,
                                   system_context=bool(system), rewrite=True)
        except ValueError as e:
            log(f'ERROR: {e}')
            sys.exit(1)
        if not prompt:
            log(f'ERROR: Failed to build prompt for scene {scene_id}')
            sys.exit(1)

        # Build JSONL line using batch request helper (includes system blocks)
        request = build_batch_request(scene_id, prompt, model, 8192,
                                      system=system or None)
        prompts[scene_id] = prompt
        with open(batch_file, 'a') as f:
            f.write(json.dumps(request) + '\n')
        batch_scene_ids.append(scene_id)

    if not batch_scene_ids:
        log('No scenes to submit in batch.')
        return DraftOutcome(0, 0, [])

    log(f'Submitting batch with {len(batch_scene_ids)} scenes...')

    batch_id = submit_batch(batch_file)
    if not batch_id:
        log('ERROR: Failed to submit batch.')
        sys.exit(1)
    log(f'Batch submitted: {batch_id}')

    log('Polling batch for completion...')
    results_url = poll_batch(batch_id, log_fn=log)
    log('Batch complete. Downloading results...')

    batch_output_dir = os.path.join(log_dir, f'batch-{os.getpid()}')
    os.makedirs(batch_output_dir, exist_ok=True)
    # Refused and cut-off replies are kept: each is retried or refused below.
    download_batch_results(results_url, batch_output_dir, batch_output_dir,
                           keep_incomplete=True)

    # Process each scene result
    drafted_count = 0
    total_words = 0
    failed: list[str] = []
    uncommitted: list[str] = []
    commit_failed = ''   # the scene whose commit failed: later ones are written, not committed
    from storyforge.git import _git

    for scene_id in batch_scene_ids:
        scene_json = os.path.join(batch_output_dir, f'{scene_id}.json')

        r = _git(project_dir, 'rev-parse', 'HEAD', check=False)
        head_before = r.stdout.strip() if r.returncode == 0 else 'none'

        # Check batch status
        status_file = os.path.join(batch_output_dir, f'.status-{scene_id}')
        batch_status = 'fail'
        if os.path.isfile(status_file):
            with open(status_file) as f:
                batch_status = f.read().strip()

        if batch_status != 'ok':
            log(f'ERROR: Batch failed for scene {scene_id}. Skipping.')
            failed.append(f'{scene_id} (batch request failed)')
            continue

        if not os.path.isfile(scene_json):
            log(f'ERROR: No batch response for scene {scene_id}. Skipping.')
            failed.append(f'{scene_id} (no response)')
            continue

        # Log usage (batch=True for 50% discount pricing) — paid either way
        _log_api_usage(scene_json, 'draft', scene_id, model, project_dir,
                       batch=True)

        if _is_refusal(scene_json) and commit_failed:
            # a retry is paid for, and its reply couldn't be committed
            log(f'ERROR: Scene {scene_id} was refused in the batch; not retried, since the '
                f'commit of {commit_failed} failed.')
            failed.append(f'{scene_id} (refused in the batch; not retried after the commit '
                          f'of {commit_failed} failed)')
            continue
        if _is_refusal(scene_json):
            retry_log = os.path.join(log_dir, f'drafting-{scene_id}.json')
            log(f'Scene {scene_id} was refused in the batch; retrying it directly '
                f'with the refusal fallback...')
            try:
                invoke_to_file(prompts[scene_id], model, retry_log, 8192,
                               label=f'drafting {scene_id}', system=system or None,
                               fallback=True)
            except RefusalError:
                pass  # logged to retry_log; the extract below names it
            except Exception as e:
                log(f'ERROR: The retry of scene {scene_id} failed: {e}. Skipping.')
                failed.append(f'{scene_id} (refused in the batch; the retry failed: {e})')
                continue
            _log_api_usage(retry_log, 'draft', scene_id, model, project_dir)
            scene_json = retry_log

        reason = _extract_scene_from_response(
            scene_json, _output_file(project_dir, scene_id, coaching),
            prose=False)  # batch writes briefs and constraints only
        if reason:
            # Keep the paid reply: the batch directory is removed below.
            kept = os.path.join(log_dir, f'drafting-{scene_id}.json')
            if scene_json != kept:
                shutil.copyfile(scene_json, kept)
            log(f'ERROR: Not writing scene {scene_id}: {reason.rstrip(".")}. Skipping.')
            log(f'See full output: {kept}')
            failed.append(f'{scene_id} ({reason.rstrip(".")})')
            continue

        # Verify and commit. Every reply is already paid for, so after a
        # failed commit the rest are still written, but not committed: their
        # commits would sweep in the earlier scene's files
        try:
            wc, ok = _verify_and_commit_scene(
                scene_id, project_dir, scenes_dir, metadata_csv, coaching,
                head_before, written_by=_written_by(scene_json), commit=not commit_failed,
            )
        except CommitError as e:
            log(f'ERROR: {scene_id} is written, but {e}. The rest of the batch is written '
                f'without committing.')
            commit_failed = scene_id
            uncommitted.append(f'{scene_id} ({e})')
            continue
        if ok and commit_failed:
            uncommitted.append(f'{scene_id} (not committed: the commit of {commit_failed} '
                               f'failed first)')
        elif ok:
            drafted_count += 1
            total_words += wc
        else:
            failed.append(f'{scene_id} (failed verification; see the ERROR above)')

    # Cleanup
    _safe_remove(batch_file)
    _safe_rmdir(batch_output_dir)

    return DraftOutcome(drafted_count, total_words, failed, uncommitted=uncommitted)


def _run_direct_mode(pending_ids, project_dir, scenes_dir, log_dir,
                     metadata_csv, coaching, use_briefs, force, filter_mode,
                     write_mode, dry_run, prior_prose='none', budget=None,
                     scene_forecast: float = 0.0, draft_forecast: float = 0.0,
                     keep_going: bool = False):
    """Run direct/interactive mode. Returns a `DraftOutcome`: ``failed``
    names each scene not drafted and why, ``recheck_open`` each re-check
    that didn't pass or wasn't run (over the cost threshold) and is still in
    ``gate.pending``, ``uncommitted`` what was written but whose commit
    failed. An API failure
    ends the loop, and that scene and every later one go into ``failed``.
    Interactive replies are written by the CLI and are not checked for
    safety.

    At coaching ``full`` the run is gated (plan §3.2-3.3; Ben, 2026-10-30):
    each scene is gated after it is written (fix and re-check, up to
    `gate.FIX_ROUNDS` times), and the loop stops, listing the rest as not
    attempted, at anything that would
    leave a later scene drafted from a ledger missing an earlier one's facts:
    a bad reply (refused, cut off, unsafe, too short), a scene that doesn't
    pass the gate (committed for the author and listed in ``gate.pending``),
    or an earlier scene still in ``gate.pending`` (a failed re-check
    included). After a scene passes and is committed, the later scenes that
    depend on what it changed are re-checked (``budgeted_recheck``; Phase
    4), not those this run redrafts anyway, under the run's one cost budget:
    ``budget`` (``costs.RunBudget``) is what the run has spent, and each
    scene still to draft reserves ``scene_forecast``. A draft the CLI writes
    (interactive) is charged at ``draft_forecast``, since no meter sees it.
    Before each scene, the run's spend plus the scenes left at
    ``scene_forecast`` must be within the threshold, or the run stops there
    (the up-front forecast was too low). At other coaching levels a bad reply
    skips only its scene. At every level a failed commit (the scene's, or
    the re-checks' after it) stops the run: the next scene's commit would
    sweep its files in under the wrong message.

    With `keep_going` (#556), a scene the gate still stops on only for the
    check's findings is committed provisionally (`_gate_drafted_scene`),
    listed in ``provisional``, and the run goes on (its re-checks too); an
    earlier provisional scene doesn't stop it."""
    drafted_count = 0
    total_words = 0
    failed: list[str] = []
    uncommitted: list[str] = []
    provisional: list[str] = []
    recheck_failed: list[str] = []   # each re-check that didn't pass
    recheck_deferred: list[str] = []   # the latest re-check's queue left over budget
    from storyforge import gate
    from storyforge.git import _git
    gated = coaching == 'full' and not dry_run

    def stop(i, scene_id, entry):
        if entry:
            failed.append(entry)
        failed.extend(f'{sid} (not attempted: the run stopped at {scene_id})'
                      for sid in pending_ids[i + 1:])

    # Build shared context once for prompt caching across all scenes
    # (only used in direct API mode, not interactive/dry-run)
    system = None
    if write_mode == 'direct' and not dry_run:
        from storyforge.common import build_shared_context
        model = select_model('drafting')
        system = build_shared_context(project_dir, model=model)

    if budget is None:
        from storyforge.costs import RunBudget
        budget = RunBudget()
    # the book before this run, once: what the gate counts as already there
    baseline = gate.snapshot(project_dir) if gated else None
    for i, scene_id in enumerate(pending_ids):
        scene_file = os.path.join(scenes_dir, f'{scene_id}.md')
        scene_num = i + 1

        log(f'--- Scene {scene_id} ({scene_num}/{len(pending_ids)}) ---')

        # Skip already-drafted
        if not force and filter_mode != 'single':
            kept = _already_drafted(scenes_dir, scene_id)
            if kept:
                log(f'Scene {scene_id} {kept}, skipping')
                continue

        if not dry_run and scene_forecast:
            left = [s for s in pending_ids[i:] if force or not _drafted(scenes_dir, s)]
            due = budget.committed(len(left) * scene_forecast)
            if not check_threshold(due):
                log(f'ERROR: drafting {scene_id} and the {len(left) - 1} scene(s) after it '
                    f'would bring this run to about ${due:.2f}, over the cost threshold '
                    f'(${cost_threshold():g}): it has cost more than its forecast. Stopping.')
                stop(i, scene_id, f'{scene_id} (not attempted: the run reached the cost '
                                  f'threshold)')
                break

        if gated:
            blocking = _gate_blockers(project_dir, scene_id, keep_going=keep_going)
            if blocking:
                _log_blockers(blocking)
                stop(i, scene_id, f'{scene_id} (not attempted: an earlier scene did not '
                                  f'pass the gate)')
                break

        # Any prose already on disk (`--force`, a scene named alone, or a
        # stub of 200 words or fewer) makes this a rewrite, that prose its
        # voice reference; a scene with no prose gets the fresh-draft prompt
        try:
            prompt = _build_prompt(scene_id, project_dir, coaching, use_briefs,
                                   system_context=bool(system), rewrite=True)
        except ValueError as e:
            log(f'ERROR: {e}')
            log('Stopping — prompt generation failed.')
            sys.exit(1)
        if not prompt:
            log(f'ERROR: Failed to build prompt for scene {scene_id}')
            log('Stopping — prompt generation failed.')
            sys.exit(1)

        # Earlier prose follows the shared context in the system prompt (direct
        # API mode, which is the only mode with a system prompt)
        from storyforge.prompts import prior_prose_blocks, prior_scenes
        scene_system = system
        if system:
            prior = prior_prose_blocks(scene_id, project_dir, prior_prose)
            scene_system = list(system) + prior
            if prior:
                log(f'Prior prose: {len(prior) - 1} earlier scene(s)')

        # Dry-run mode
        if dry_run:
            print(f'===== DRY RUN: {scene_id} =====')
            earlier = prior_scenes(scene_id, project_dir, prior_prose)
            if earlier:
                print(f'(A direct run also sends the prose of {len(earlier)} earlier '
                      f'scene(s) in the system prompt, {prior_prose}: {", ".join(earlier)})')
            print(prompt)
            print(f'===== END DRY RUN: {scene_id} =====')
            print()
            drafted_count += 1
            continue

        r = _git(project_dir, 'rev-parse', 'HEAD', check=False)
        head_before = r.stdout.strip() if r.returncode == 0 else 'none'
        # The gate records which command wrote the prose
        before = ''
        if os.path.isfile(scene_file):
            with open(scene_file, encoding='utf-8') as f:
                before = f.read()
        command = 'redraft' if (before.strip() or (gated and gate.has_commitments(
            project_dir, scene_id))) else 'draft'

        scene_log = os.path.join(log_dir, f'drafting-{scene_id}.json')
        model = select_model('drafting')
        start_time = time.time()

        log(f'Invoking API for scene {scene_id} (model: {model})...')
        log(f'  Per-scene log: {scene_log}')

        reason = ''
        if write_mode == 'interactive':
            # Interactive mode — invoke claude CLI. It writes the file itself,
            # so no reply passes through the guard below.
            exit_code = _invoke_interactive(prompt, model, project_dir)
            budget.charge(draft_forecast)   # no meter sees the CLI's spend
            if exit_code == 0 and coaching == 'full':
                reason = _interactive_problem(scene_file, before)
                if not reason and before:
                    _keep_cli_markers(project_dir, scene_id, scene_file, before)
        else:
            # Direct API mode
            max_tokens = 16384 if write_mode != 'direct' else 8192
            try:
                invoke_to_file(prompt, model, scene_log, max_tokens,
                               label=f'drafting {scene_id}',
                               system=scene_system or None, fallback=True)
                exit_code = 0
            except RefusalError:
                exit_code = 0  # logged to scene_log; the extract below names it
            except Exception as e:
                log(f'ERROR: API call failed: {e}')
                exit_code = 1
            if exit_code == 0:
                _log_api_usage(scene_log, 'draft', scene_id, model, project_dir)
                reason = _extract_scene_from_response(
                    scene_log, _output_file(project_dir, scene_id, coaching),
                    prose=coaching == 'full')

        elapsed = int(time.time() - start_time)
        mins, secs = divmod(elapsed, 60)

        if exit_code != 0:
            log(f'ERROR: API call failed with code {exit_code} for scene {scene_id} '
                f'after {mins}m{secs}s')
            log(f'See full output: {scene_log}')
            log('Stopping — continuity may be broken.')
            failed.append(f'{scene_id} (API call failed; see {scene_log})')
            failed.extend(f'{sid} (not attempted: the run stopped at {scene_id})'
                          for sid in pending_ids[i + 1:])
            break

        if reason:
            log(f'ERROR: Not writing scene {scene_id}: {reason.rstrip(".")}.')
            log(f'See full output: {scene_log}')
            if gated:
                log('Stopping: later scenes would be drafted without its facts in the ledger.')
                stop(i, scene_id, f'{scene_id} ({reason.rstrip(".")})')
                break
            failed.append(f'{scene_id} ({reason.rstrip(".")})')
            continue

        gate_problem = ''
        if gated:
            _, gate_problem = _gate_drafted_scene(project_dir, scene_id, scene_file,
                                                  command, log_dir, before=baseline,
                                                  keep_going=keep_going)

        # The prose is committed either way: a scene the gate stopped is kept
        # for the author and listed in gate.pending
        try:
            wc, ok = _verify_and_commit_scene(
                scene_id, project_dir, scenes_dir, metadata_csv, coaching,
                head_before, written_by=_written_by(scene_log),
                gate_failed=bool(gate_problem),
            )
        except CommitError as e:
            # The next scene's commit would sweep this one's ledger and
            # metadata changes in under its own message, and a run whose
            # commits fail shouldn't keep paying: stop here
            log(f'ERROR: Scene {scene_id} is written, but {e}.')
            log('Stopping: commit it by hand, then run again.')
            uncommitted.append(f'{scene_id} ({e}'
                               + (f'; it also did not pass the gate and is listed in '
                                  f'{gate_pending_path()}: {gate_problem}'
                                  if gate_problem else '') + ')')
            stop(i, scene_id, None)
            break
        if gate_problem and keep_going and is_provisional(project_dir, scene_id):
            log(f'WARNING: Scene {scene_id} did not pass the gate and is committed '
                f'provisionally; going on (--keep-going): {gate_problem}')
            provisional.append(f'{scene_id} ({gate_problem})')
            gate_problem = ''
        if gate_problem:
            log(f'ERROR: Scene {scene_id} did not pass the gate: {gate_problem}')
            log('Stopping: later scenes would be drafted without its facts in the ledger.')
            stop(i, scene_id, f'{scene_id} (did not pass the gate; its prose is kept and '
                              f'listed in {gate_pending_path()})')
            break
        if ok:
            drafted_count += 1
            total_words += wc
        else:
            failed.append(f'{scene_id} (failed verification; see the ERROR above)')
        if gated and ok:
            # The scene is committed; now the later scenes that depend on
            # what it changed (not those this run redrafts anyway)
            later = {s for s in pending_ids[i + 1:] if force or not _drafted(scenes_dir, s)}
            run = budgeted_recheck(project_dir, os.path.join(log_dir, 'gate'), later,
                                   budget, reserved=len(later) * scene_forecast)
            # The latest run's queue is what's still owed: an earlier
            # deferral is either in it again or was re-checked since
            recheck_deferred = list(run.left) if run is not None and run.over_budget else []
            if run is not None and run.failed:
                recheck_failed.append(f'{run.failed} (re-checked after {scene_id} and did not '
                                      f'pass: {run.why})')
            if run is not None:
                try:
                    _commit(project_dir, f'Re-check after {scene_id}: '
                            f'{len(run.passed)} passed'
                            + (f', {run.failed} did not' if run.failed else ''),
                            ['reference/', 'working/logs/', 'working/audit-log.csv',
                             'working/.audit-snapshot.csv', gate_pending_path(),
                             gate_prose_path(), gate_source_fix_path()])
                except CommitError as e:
                    log(f'ERROR: the re-checks after {scene_id} ran, but {e}.')
                    log('Stopping: commit them by hand, then run again.')
                    uncommitted.append(f'the re-checks after {scene_id} ({e})')
                    stop(i, scene_id, None)
                    break

        log(f'  Time: {mins}m{secs}s')

        # Pause between scenes in headless mode
        if i < len(pending_ids) - 1 and write_mode != 'interactive':
            log('Pausing 10s before next scene...')
            time.sleep(10)

    recheck_open = list(recheck_failed)
    if recheck_deferred:
        recheck_open.append(
            f'{len(recheck_deferred)} scene(s) listed for a re-check, not run: over the cost '
            f'threshold ({", ".join(recheck_deferred)}). They stay in {gate_pending_path()}; '
            f'run `storyforge check --pending`, with STORYFORGE_COST_THRESHOLD raised if needed.')
    return DraftOutcome(drafted_count, total_words, failed, recheck_open, uncommitted,
                        provisional)


def _invoke_interactive(prompt: str, model: str, project_dir: str) -> int:
    """Invoke Claude CLI in interactive mode. Returns exit code."""
    try:
        result = subprocess.run(
            ['claude', prompt, '--model', model,
             '--dangerously-skip-permissions'],
            cwd=project_dir,
        )
        return result.returncode
    except FileNotFoundError:
        log('ERROR: claude CLI not found — install Claude Code first')
        return 1


def _written_by(log_file: str) -> str:
    """The model the refusal fallback used for this reply, else ''."""
    try:
        with open(log_file) as f:
            return fallback_model(json.load(f))
    except (OSError, ValueError):
        return ''  # the reply was already read and written; nothing to name


def _is_refusal(log_file: str) -> bool:
    try:
        with open(log_file) as f:
            return is_refusal(json.load(f))
    except (OSError, ValueError):
        return False  # the extract step reports an unreadable log


def _log_api_usage(log_file: str, operation: str, target: str, model: str,
                   project_dir: str, batch: bool = False) -> None:
    """Log API usage/cost from a JSON response file.

    If batch=True, applies the Anthropic Batch API 50% discount to cost.
    A reply the refusal fallback wrote is priced and logged as that model's.
    """
    try:
        with open(log_file) as f:
            response = json.load(f)
        model = fallback_model(response) or model
        usage = extract_usage(response)
        cost = calculate_cost_from_usage(usage, model, batch=batch)
        log_operation(
            project_dir, operation, model,
            usage['input_tokens'], usage['output_tokens'], cost,
            target=target,
            cache_read=usage.get('cache_read', 0),
            cache_create=usage.get('cache_create', 0),
        )
    except Exception as e:
        log(f'WARNING: could not log the cost of {operation} {target}: {e}')


def _replace_in_file(filepath: str, pattern: str, replacement: str) -> None:
    """Regex-replace in a file (like sed -i), leaving line endings alone.

    `newline=''` on both ends because the only caller edits `storyforge.yaml`
    (advancing `phase`), and this was the **third** writer of that file — the
    other two preserve endings deliberately (#276, #314), so a text-mode
    read/write here normalized CRLF to LF for the whole file as a side effect of
    changing one word. That is #314 in a different command, and it silently
    falsified the claim that nothing converts this file any more.

    Delegates to `common.rewrite_preserving_newlines`, shared with the two other
    shallow editors of this file (`cmd_elaborate`'s phase advance and
    `cmd_migrate_medium`'s medium swap). All three were text-mode read/write, so
    each converted the whole file as a side effect of changing one word; sharing
    one implementation is what stops a fourth from getting it wrong again.
    """
    import re
    rewrite_preserving_newlines(
        filepath,
        lambda text: re.sub(pattern, replacement, text, flags=re.MULTILINE))


def _safe_remove(path: str) -> None:
    try:
        os.remove(path)
    except OSError:
        pass


def _safe_rmdir(path: str) -> None:
    try:
        shutil.rmtree(path)
    except OSError:
        pass


if __name__ == '__main__':
    main()
