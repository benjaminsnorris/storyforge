"""storyforge revise -- Execute revision passes from a revision plan.

Reads working/plans/revision-plan.csv (or legacy .yaml) and executes each
pass in order. Supports --polish for craft-only, --naturalness for targeted
AI pattern removal (3 passes), and --structural for CSV-only revision.

Usage:
    storyforge revise                 # Start from first pending pass
    storyforge revise 3               # Start from pass number 3 (1-indexed)
    storyforge revise --polish        # Craft-only polish plan
    storyforge revise --polish --loop # Deterministic score → polish → re-score, then full LLM score
    storyforge revise --naturalness   # 3-pass AI pattern removal
    storyforge revise --structural    # CSV-only from structural proposals
    storyforge revise --dry-run       # Print prompts only
"""

import argparse
import contextlib
import csv
import hashlib
import json
import os
import re
import subprocess
import sys
import time

from storyforge.brief_names import invented_names, read_text, reference_text
from storyforge.common import (
    detect_project_root, log, set_log_file, read_yaml_field,
    select_model, select_revision_model, get_coaching_level,
    install_signal_handlers, get_plugin_dir, csv_safe,
)
from storyforge.costs import (
    check_threshold, cost_threshold, estimate_cost, log_operation, print_summary,
)
from storyforge.git import (
    create_branch, ensure_branch_pushed, create_draft_pr,
    update_pr_task, _git, has_gh, current_branch,
    get_pr_body, set_pr_body, add_pr_comment,
)
from storyforge.api import (
    invoke_api, invoke_to_file, extract_text, extract_text_from_file,
    extract_usage, calculate_cost_from_usage, get_api_key, fallback_model,
    fallback_replies, fallback_note, report_fallback_replies,
    REVISION_TIMEOUT, max_output_tokens,
)
from storyforge.cli import apply_coaching_override


def _log_prompt_warnings(stderr: str) -> None:
    """Log the WARNING lines `revision build-prompt` wrote to stderr (its
    stdout is the prompt): the revision calendar's unreadable scenes.csv
    data, which would otherwise be captured and dropped."""
    for line in (stderr or '').splitlines():
        if line.startswith('WARNING'):
            log(line)


# ============================================================================
# Argument parsing
# ============================================================================


def parse_args(argv):
    parser = argparse.ArgumentParser(
        prog='storyforge revise',
        description='Execute revision passes from a revision plan.',
    )
    parser.add_argument('--dry-run', action='store_true',
                        help='Build and print prompts without invoking Claude')
    parser.add_argument('--interactive', '-i', action='store_true',
                        help='Supervise each pass interactively')
    parser.add_argument('--structural', action='store_true',
                        help='Auto-generate plan from structural proposals (CSV-only)')
    parser.add_argument('--naturalness', action='store_true',
                        help='Auto-generate 3-pass plan targeting AI prose patterns')
    parser.add_argument('--polish', action='store_true',
                        help='Auto-generate craft-only polish plan')
    parser.add_argument('--scores', action='store_true',
                        help='Auto-generate revision plan from scoring diagnosis (upstream + craft)')
    parser.add_argument('--coaching', choices=['full', 'coach', 'strict'],
                        help='Override coaching level')
    parser.add_argument('--loop', action='store_true',
                        help='Autonomous convergence loop: score → polish → re-score until stable (requires --polish)')
    parser.add_argument('--max-loops', type=int, default=5,
                        help='Maximum iterations in --loop mode (default: 5)')
    parser.add_argument('--skip-initial-score', action='store_true',
                        help='Skip initial scoring in --polish --loop (use existing scores)')
    parser.add_argument('--skip-final-score', action='store_true',
                        help='Skip full LLM scoring after deterministic loop converges (requires --loop)')
    parser.add_argument('--no-annotations', action='store_true',
                        help='Exclude reader annotations from revision plan')
    parser.add_argument('pass_num', nargs='?', type=int, default=0,
                        help='Start from this pass number (1-indexed; default: first pending)')
    return parser.parse_args(argv)


# ============================================================================
# CSV plan helpers
# ============================================================================

# `owed`: the scenes a prose pass's reply held but didn't write (`;`-joined).
# Written in the same commit as the scenes it did write; a re-run of the pass
# revises only these, and the pass is completed when none remain.
CSV_PLAN_FIELDS = ['pass', 'name', 'purpose', 'scope', 'targets', 'guidance',
                   'protection', 'findings', 'status', 'model_tier', 'fix_location',
                   'owed']


def _sanitize_csv_field(value: str) -> str:
    """Sanitize a value for pipe-delimited CSV: replace pipes and newlines."""
    return value.replace('|', ',').replace('\n', ' ').replace('\r', '')


def _read_csv_plan(plan_file):
    """Read the CSV revision plan. Returns list of row dicts.

    Strips ``\\r`` so CRLF line endings never propagate into field values.
    """
    if not os.path.isfile(plan_file):
        return []
    with open(plan_file, newline='', encoding='utf-8') as f:
        raw = f.read().replace('\r\n', '\n').replace('\r', '')
    rows = []
    reader = csv.DictReader(raw.splitlines(), delimiter='|')
    for row in reader:
        rows.append({k: (v if v is not None else '') for k, v in row.items()})
    return rows


def _write_csv_plan(plan_file, rows):
    """Write the CSV revision plan (in-place update to an existing file)."""
    os.makedirs(os.path.dirname(plan_file), exist_ok=True)
    with open(plan_file, 'w') as f:
        f.write('|'.join(CSV_PLAN_FIELDS) + '\n')
        for row in rows:
            f.write('|'.join(
                _sanitize_csv_field(row.get(field, ''))
                for field in CSV_PLAN_FIELDS
            ) + '\n')


def _next_plan_number(plans_dir):
    """Find the next revision plan number by scanning existing numbered files."""
    highest = 0
    if os.path.isdir(plans_dir):
        for name in os.listdir(plans_dir):
            if name.startswith('revision-plan-') and name.endswith('.csv'):
                try:
                    n = int(name[len('revision-plan-'):-len('.csv')])
                    highest = max(highest, n)
                except ValueError:
                    pass
    return highest + 1


def _save_plan(plan_file, rows, what: str) -> str:
    numbered = _create_versioned_plan(plan_file, rows)
    log(f'Generated {what} plan ({len(rows)} passes): {numbered}')
    return numbered


def _create_versioned_plan(plan_file, rows):
    """Write a new versioned revision plan and update the symlink.

    plan_file is the canonical symlink path (working/plans/revision-plan.csv).
    Creates revision-plan-N.csv and points the symlink at it.
    """
    plans_dir = os.path.dirname(plan_file)
    os.makedirs(plans_dir, exist_ok=True)
    num = _next_plan_number(plans_dir)
    numbered_name = f'revision-plan-{num}.csv'
    numbered_file = os.path.join(plans_dir, numbered_name)
    _write_csv_plan(numbered_file, rows)

    # Update symlink (handle existing symlink, regular file, or nothing)
    if os.path.islink(plan_file):
        os.remove(plan_file)
    elif os.path.exists(plan_file):
        os.remove(plan_file)
    os.symlink(numbered_name, plan_file)
    return numbered_file


# ============================================================================
# Upstream delegation helpers
# ============================================================================

def _file_hash(path):
    """SHA-256 of file contents, or empty string if file doesn't exist."""
    if not os.path.isfile(path):
        return ''
    with open(path, 'rb') as f:
        return hashlib.sha256(f.read()).hexdigest()


def _write_hone_findings(path, fix_location, targets, guidance, ref_dir=''):
    """Write a findings file for hone from revision plan pass data.

    When *targets* is empty (full scope), reads the target CSV and expands to
    all scene IDs so that ``load_external_findings`` can match them.

    When targets contain values that are not valid scene IDs (e.g. character
    names), they are resolved to the scenes where each character appears via the
    ``characters`` column in scene-intent.csv.
    """
    os.makedirs(os.path.dirname(path), exist_ok=True)
    target_file = 'scene-briefs.csv' if fix_location == 'brief' else 'scene-intent.csv'
    raw_targets = [t.strip() for t in targets.split(';') if t.strip()] if targets else []
    safe_guidance = _sanitize_csv_field(guidance)

    # Determine the set of valid scene IDs from the target CSV
    valid_scene_ids: set[str] = set()
    if ref_dir:
        csv_path = os.path.join(ref_dir, target_file)
        if os.path.isfile(csv_path):
            from storyforge.elaborate import _read_csv_as_map
            valid_scene_ids = set(_read_csv_as_map(csv_path).keys())

    if not raw_targets:
        # Full scope — expand to all scene IDs from the target CSV
        scene_ids = sorted(valid_scene_ids) if valid_scene_ids else []
    elif valid_scene_ids:
        # Resolve any non-scene-ID targets (e.g. character names) to scenes
        scene_ids = _resolve_targets_to_scene_ids(raw_targets, valid_scene_ids, ref_dir)
    else:
        scene_ids = raw_targets

    with open(path, 'w') as f:
        f.write('scene_id|target_file|fields|guidance\n')
        if not scene_ids:
            log('  WARNING: No scene IDs to write in findings file')
        for sid in scene_ids:
            f.write(f'{sid}|{target_file}||{safe_guidance}\n')


def _resolve_targets_to_scene_ids(targets, valid_scene_ids, ref_dir):
    """Resolve targets to scene IDs, expanding character names via scene-intent.csv."""
    resolved = []
    need_character_lookup = []

    for t in targets:
        if t in valid_scene_ids:
            resolved.append(t)
        else:
            need_character_lookup.append(t)

    if not need_character_lookup:
        return sorted(set(resolved))

    # Try to resolve character names via scene-intent.csv characters column
    intent_path = os.path.join(ref_dir, 'scene-intent.csv')
    if not os.path.isfile(intent_path):
        for name in need_character_lookup:
            log(f'  WARNING: Target "{name}" is not a valid scene ID and '
                f'scene-intent.csv not found for character lookup — skipping')
        return resolved

    from storyforge.elaborate import _read_csv_as_map
    intent_map = _read_csv_as_map(intent_path)

    for name in need_character_lookup:
        name_lower = name.lower()
        matching_scenes = []
        for sid, row in intent_map.items():
            chars = [c.strip().lower() for c in row.get('characters', '').split(';') if c.strip()]
            if name_lower in chars:
                matching_scenes.append(sid)
        if matching_scenes:
            log(f'  Resolved character "{name}" to {len(matching_scenes)} scenes')
            resolved.extend(matching_scenes)
        else:
            log(f'  WARNING: Target "{name}" is not a valid scene ID or character name — skipping')

    return sorted(set(resolved))


def _redraft_from_briefs(project_dir, scene_ids, model, log_dir, system=None):
    """Re-draft scenes from their updated briefs and commit those written.

    Scenes go in reading order, and each redraft is gated as ``write``
    gates a draft (``_gate_redraft``). Like ``write``, redrafting stops at
    the first scene the gate doesn't pass: the scenes after it would be
    checked against a ledger missing its facts.

    Raises RedraftError (after that commit) naming every scene whose prose
    was not re-drafted (no prompt, or a reply refused, cut off or unsafe per
    ``cmd_write._extract_scene_from_response``: its brief changed but its
    prose did not), a redraft the gate didn't pass, and the scenes not
    reached after it, so the run must not report success."""
    from storyforge.cmd_write import _build_prompt, _extract_scene_from_response
    from storyforge.api import invoke_to_file as _invoke_to_file, RefusalError

    # Build shared context for prompt caching if not provided
    if system is None:
        from storyforge.common import build_shared_context
        system = build_shared_context(project_dir, model=model)

    from storyforge.prompts import prior_prose_blocks, prior_prose_mode
    from storyforge import ledger
    try:
        prior_prose = prior_prose_mode(project_dir)
        if prior_prose != 'none':
            ledger.scene_order(project_dir)
    except ValueError as e:
        raise RedraftError(f'{len(scene_ids)} scene(s) not re-drafted: {e}') from e
    log(f'  Redrafting {len(scene_ids)} scenes from updated briefs (prior prose: '
        f'{prior_prose})...')
    served_before = len(fallback_replies())
    budget = _run_budget()
    rechecks_open: list[str] = []   # re-checks after a redraft that failed or didn't run
    scenes_dir = os.path.join(project_dir, 'scenes')
    failed: list[str] = []
    written = 0

    scene_ids = _reading_order(project_dir, scene_ids)
    from storyforge import gate
    baseline = gate.snapshot(project_dir)   # the book before this run
    for i, sid in enumerate(scene_ids, 1):
        log(f'    [{i}/{len(scene_ids)}] Redrafting: {sid}')
        stop = _leaning(project_dir, sid)
        if stop:
            failed += [stop] + _not_reached(scene_ids[i:])
            break
        try:
            prompt = _build_prompt(sid, project_dir, 'full', use_briefs=True,
                                   system_context=bool(system), rewrite=True)
        except ValueError as e:   # its prose can't be read for the voice reference
            prompt, why = '', str(e)
        else:
            why = 'no prompt'
        if not prompt:
            log(f'    ERROR: Could not build a prompt for {sid}: {why}')
            failed += [f'{sid} ({why})'] + _not_reached(scene_ids[i:])
            break
        log_file = os.path.join(log_dir, f'redraft-{sid}.json')
        scene_system = (list(system) + prior_prose_blocks(sid, project_dir, prior_prose)
                        if system else system)
        try:
            _invoke_to_file(prompt, model, log_file, max_tokens=16384,
                            label=f'redraft {sid}', system=scene_system or None,
                            fallback=True)
        except RefusalError:
            pass  # logged to log_file; the extract below names it
        scene_file = os.path.join(scenes_dir, f'{sid}.md')
        reason = _extract_scene_from_response(log_file, scene_file)
        if reason:
            reason = reason.rstrip('.')
            log(f'    ERROR: Not writing the re-draft of {sid}: {reason}')
            # the scenes after it would be drafted with its stale prose among
            # the earlier scenes, as `write` stops at a bad reply
            failed += [f'{sid} ({reason})'] + _not_reached(scene_ids[i:])
            break
        else:
            written += 1
            why = _gate_redraft(project_dir, sid, scene_file, log_dir, before=baseline)
            if why:
                failed += _stopped_at(sid, why, scene_ids[i:])
                break
            _note_recheck(rechecks_open, sid,
                          _recheck_after(project_dir, log_dir, set(scene_ids[i:]), budget))

    _commit(
        project_dir,
        f'Revision: redraft {written} scenes from corrected briefs'
        + fallback_note(served_before),
        ['scenes/', 'reference/', 'working/'])

    if failed:
        raise RedraftError(f'{len(failed)} scene(s) not re-drafted: {"; ".join(failed)}')
    _raise_if_rechecks_open(rechecks_open)


def _commit(project_dir: str, message: str, paths: list[str] | None = None) -> None:
    """Commit and push, or stop the session: a failed commit is an ERROR
    with git's reason and exit 1 (#503's review, SF-3), as in `write`.
    Carrying on would pay for more passes on a branch whose commits aren't
    landing, and the next commit would sweep these files in under its own
    message; `git.commit_and_push` unstages what it staged. Nothing to
    commit is not a failure; a failed push stays a WARNING."""
    from storyforge import git
    try:
        git.commit_or_raise(project_dir, message, paths)
    except git.CommitError as e:
        log(f'ERROR: {e}. The files are written but not committed: fix what stopped the '
            f'commit (`git status`), commit them by hand, then run revise again (a pass '
            f'already marked completed is skipped).')
        sys.exit(1)


#: The revise session's one cost budget (`costs.RunBudget`), set for a run
#: by `_budget_scope` (`main`'s, metered; the polish loop's when called on
#: its own); None outside a run (a helper called directly, as the tests do)
_RUN_BUDGET = None


def _run_budget():
    """The run's cost budget, or a fresh unmetered one when a helper is
    called outside a run (nothing it reserves outlives the call)."""
    from storyforge.costs import RunBudget
    return _RUN_BUDGET if _RUN_BUDGET is not None else RunBudget()


@contextlib.contextmanager
def _budget_scope(meter=None):
    """One budget for the run: the one already set (by `main`), or a new
    one set for the block, so every helper's `_run_budget()` in it is the
    same instance and a reservation made on it reaches their re-checks."""
    global _RUN_BUDGET
    if _RUN_BUDGET is not None:
        yield _RUN_BUDGET
        return
    from storyforge.costs import RunBudget
    _RUN_BUDGET = RunBudget(meter)
    try:
        yield _RUN_BUDGET
    finally:
        _RUN_BUDGET = None


def _pass_cost(project_dir: str, model: str) -> float:
    """One prose pass's forecast: the whole book read and revised on
    `model` (`costs.estimate_cost('revise', ...)` over the scenes' average
    word count). The plan's passes, the polish loop's and naturalness's are
    all forecast this way."""
    avg_words, scene_count = _estimate_avg_words(project_dir)
    return estimate_cost('revise', scene_count, avg_words, model)


#: The brief-rewrite and drafting prompts' own text around the scene, in
#: tokens (instructions, the scene's characters, place and plan)
_PROMPT_OVERHEAD_TOKENS = 3000


def _tokens(text: str) -> int:
    """Tokens in `text`, as `costs.estimate_cost` counts them (1.3 a word)."""
    return int(len(text.split()) * 1.3)


def _upstream_fix_cost(project_dir: str, scene_ids: list[str]) -> float:
    """The brief fixes and redrafts of `scene_ids` (`_fix_and_redraft`),
    priced from what each call sends, at the creative tier's uncached input
    price (#510's review, SF-6: a flat 1,500-token draft estimate left out
    the shared context and the earlier prose a redraft sends). Conservative:
    the context and earlier prose are often read from cache for less.

    - the brief rewrite: the scene's prose (up to `_PROSE_CONTEXT_WORDS`)
      and the prompt in, its `max_tokens` (1,024) out;
    - the redraft: the shared context (`build_shared_context`), the earlier
      prose `drafting.prior_prose` sends (`prior_prose_blocks`), the old
      prose and the prompt in, the scene again out;
    - the gate's run on the redraft (`gate.RECHECK_COST_PER_SCENE`).

    The re-checks a redraft lists are not in it: they get what is left."""
    from storyforge import gate
    from storyforge.common import build_shared_context
    from storyforge.costs import calculate_cost
    from storyforge.prompts import prior_prose_blocks, prior_prose_mode
    if not scene_ids:
        return 0.0
    model = select_model('creative')
    context = sum(_tokens(b.get('text', ''))
                  for b in build_shared_context(project_dir, model=model) or [])
    try:
        mode = prior_prose_mode(project_dir)
    except ValueError:      # `_main` stops on a bad value before this
        mode = 'none'
    avg_words, _ = _estimate_avg_words(project_dir)
    total = 0.0
    for sid in scene_ids:
        path = os.path.join(project_dir, 'scenes', f'{sid}.md')
        if os.path.isfile(path):
            with open(path, encoding='utf-8') as f:
                words = len(f.read().split())
        else:
            words = avg_words
        prose = int(words * 1.3)
        prior = 0
        if mode != 'none':
            try:
                prior = sum(_tokens(b['text'])
                            for b in prior_prose_blocks(sid, project_dir, mode))
            except (OSError, ValueError) as e:
                log(f'WARNING: the forecast of {sid}\'s redraft leaves out the earlier '
                    f'prose it would be sent: {e}')
        brief_in = int(min(words, _PROSE_CONTEXT_WORDS) * 1.3) + _PROMPT_OVERHEAD_TOKENS
        total += calculate_cost(model, brief_in, 1024)
        total += calculate_cost(model, context + prior + prose + _PROMPT_OVERHEAD_TOKENS,
                                prose)
        total += gate.RECHECK_COST_PER_SCENE
    return total


def _over_threshold(forecast: float) -> str:
    """'' when what the run has spent or reserved (`RunBudget.committed`)
    plus `forecast` is within the cost threshold, else how far over, the
    spend so far named apart from the forecast."""
    spent = _run_budget().committed()
    due = spent + forecast
    if check_threshold(due):
        return ''
    if spent < 0.005:
        return (f'the forecast (~${forecast:.2f}) is over the cost threshold '
                f'(${cost_threshold():g})')
    return (f'spent so far ~${spent:.2f} + forecast ~${forecast:.2f} = ~${due:.2f} is over '
            f'the cost threshold (${cost_threshold():g})')


def _exit_if_over_threshold(forecast: float, not_done: str, advice: str) -> None:
    """The check before a stretch of paid work (#503): what the run has
    spent or reserved plus `forecast` must be within the cost threshold,
    else an ERROR naming both, and exit 1 before anything more is spent.
    `not_done` says what that leaves undone ('nothing revised')."""
    over = _over_threshold(forecast)
    if over:
        log(f'ERROR: {over}: {not_done}. Raise STORYFORGE_COST_THRESHOLD, or {advice}.')
        sys.exit(1)


def _log_recheck_budget() -> None:
    log(f'  The re-checks after each gated scene get what is left of the '
        f'${cost_threshold():g} threshold once the passes and the gate are paid for; '
        f'any left over stay pending for `storyforge check --pending`.')


def _note_recheck(rechecks_open: list[str], after: str, run) -> None:
    """Keep what a re-check after `after`'s redraft left undone: one that
    failed, or scenes the threshold kept from running (the latest such
    queue is what is still owed)."""
    if run is None:
        return
    rechecks_open[:] = [x for x in rechecks_open if not x.startswith('over the threshold')]
    if run.failed:
        rechecks_open.append(f'{run.failed} (re-checked after {after} and did not pass: '
                             f'{run.why})')
    if run.over_budget and run.left:
        rechecks_open.append(f'over the threshold, not run: {", ".join(run.left)}')


def _raise_if_rechecks_open(rechecks_open: list[str]) -> None:
    """A re-check a redraft owed and didn't finish fails the run, wherever
    it falls (#503's review: one after the last redraft didn't)."""
    if rechecks_open:
        raise RedraftError(f'the redrafts are in, but re-checks they owed did not finish '
                           f'(listed in working/gate-pending.csv; `storyforge check '
                           f'--pending`): {"; ".join(rechecks_open)}')


def _recheck_after(project_dir: str, log_dir: str, skip: set[str], budget):
    """After a redraft passed: re-check the later scenes it listed, except
    `skip` (this run redrafts them), as `write` does, under the session's
    one budget: what it has spent, and the gate runs `skip` still owes at
    `gate.RECHECK_COST_PER_SCENE` reserved."""
    from storyforge import cmd_write, gate
    return cmd_write.budgeted_recheck(project_dir, os.path.join(log_dir, 'gate'), skip,
                                      budget,
                                      reserved=len(skip) * gate.RECHECK_COST_PER_SCENE)


def _gate_redraft(project_dir: str, scene_id: str, scene_file: str, log_dir: str,
                  before=None) -> str:
    """Gate the redraft just written to `scene_file` as `write` gates a
    draft (`cmd_write._gate_drafted_scene`: fix and re-check up to
    `gate.FIX_ROUNDS` times; the fixed prose is written back, the scene's
    facts replace its earlier ones in the
    ledger on a pass, and the later scenes depending on what it changed are
    listed for a re-check, which the caller runs). Returns '' when it
    passed, else why not; the scene is then listed in `gate.pending` with
    its prose kept. `before` is the book before the run (`gate.snapshot`):
    a contradiction already in it is reported, not blocking."""
    from storyforge import cmd_write
    passed, why = cmd_write._gate_drafted_scene(project_dir, scene_id, scene_file,
                                                'redraft', log_dir, before=before)
    return '' if passed else why


def _restore_gate_markers(project_dir: str, scene_id: str, scene_file: str, original: str,
                          already_lost: list[str] | tuple = ()) -> None:
    """The gate's fix edits the prose with find/replace and knows nothing of
    illustration markers: restore any marker in `original` (the prose whose
    markers must survive: the scene before a redraft, or what a pass wrote)
    that the gated prose lacks, and warn about one that can't be restored
    (`already_lost`: ones the caller already warned about)."""
    from storyforge.illustrations import preserve_markers
    with open(scene_file, encoding='utf-8') as f:
        gated = f.read()
    kept = preserve_markers(project_dir, original, gated)
    if kept['text'] != gated:
        with open(scene_file, 'w', encoding='utf-8') as f:
            f.write(kept['text'])
        log(f'  restored {len(kept["restored"])} illustration marker(s) the gate\'s '
            f'fix dropped: {", ".join(kept["restored"])}')
    for lost in [m for m in kept['lost'] if m not in already_lost]:
        log(f'  WARNING: illustration marker {lost!r} was in {scene_id} and the gate\'s '
            f'fix dropped it; re-anchor the plan row and run '
            f'`storyforge illustrate --embed`')


def _pass_scene_ids(project_dir: str, targets: str) -> list[str]:
    """The scenes a prose pass may rewrite: its targets that are scenes (in
    the order named), or every scene in reading order when it names none (a
    full-scope pass, or targets that are characters or new scenes)."""
    from storyforge import ledger
    order = ledger.scene_order(project_dir)
    named = [t.removeprefix('NEW:') for t in _split_targets(targets)]
    return [s for s in named if s in order] or list(order)


def _exit_if_pass_blocked(project_dir: str, targets: str) -> None:
    """Exit 1 before a prose pass spends anything when a scene waiting on
    the gate (`working/gate-pending.csv`) would stop the gating of what it
    writes: one before its first target (`write`'s rule), or one between
    its targets that it doesn't rewrite. A scene listed only for a re-check
    doesn't count there: the re-checks after each gated scene run it."""
    from storyforge import cmd_write, gate, ledger
    targets_in_book = _pass_scene_ids(project_dir, targets)
    cmd_write._exit_if_gate_pending(project_dir, targets_in_book)
    order = ledger.scene_order(project_dir)
    try:
        waiting = gate.pending(project_dir)
    except gate.GateError as e:
        log(f'ERROR: {e}')
        sys.exit(1)
    first = min(order[s] for s in targets_in_book)
    last = max(order[s] for s in targets_in_book)
    between = sorted((s for s, row in waiting.items()
                      if s in order and s not in targets_in_book
                      and row['command'] != gate.RECHECK and first < order[s] < last),
                     key=order.get)
    if between:
        cmd_write._log_blockers([f'{s}: {waiting[s]["reason"]}' for s in between])
        log('The pass rewrites scenes after it, and they could not be gated: nothing spent.')
        sys.exit(1)


def _gate_pass_scenes(project_dir: str, scene_ids: list[str], pass_name: str,
                      log_dir: str, before=None) -> list[str]:
    """Gate each scene a prose pass rewrote, in reading order, as revise's
    redrafts are (Phase 4 §5, `docs/plans/2026-10-31-phase4-safe-revision-design.md`):
    fixed and re-checked up to `gate.FIX_ROUNDS` times, the fixed prose
    written back, the scene's facts replacing its earlier ones on a pass, then
    the re-check of the later
    scenes depending on what it changed (the rest of this pass's scenes are
    gated by this run, so they are skipped there). `before` is the book
    before the pass (`gate.snapshot`): a contradiction already there is
    reported, not blocking.

    First every rewritten scene is listed pending ("not gated yet") and the
    prose committed, so an interrupted run leaves each ungated scene listed
    (design §3: the ledger is consistent after each step); a scene that
    passes comes off the list.

    Stops at the first scene the gate doesn't pass (listed with the gate's
    reasons, its prose kept) or that waits behind an earlier pending scene
    (a re-check that failed mid-pass): the scenes after it would be gated
    against a ledger missing its facts, so they stay listed as revised but
    not gated. Returns the lines naming what didn't pass, at most three:
    that scene, the scenes left ungated, and a re-check that didn't pass or
    wasn't run (empty when all passed and every re-check did). The caller
    commits and stops the session."""
    from storyforge import cmd_write, gate
    if not scene_ids:
        return []
    ordered = _reading_order(project_dir, scene_ids)
    _pend_ungated(project_dir, ordered, pass_name, 'not gated yet', announce=False)
    from storyforge import git
    _commit(project_dir, f'Revision: {pass_name}, before the gate',
            ['scenes/', 'reference/', 'working/'])
    log(f'  Gating {len(ordered)} revised scene(s) in reading order...')
    budget = _run_budget()
    trouble = ''  # a re-check that didn't pass or wasn't run
    scenes_dir = os.path.join(project_dir, 'scenes')
    for i, sid in enumerate(ordered):
        rest = ordered[i + 1:]
        try:
            blocking = cmd_write._gate_blockers(project_dir, sid)
        except gate.GateError as e:
            log(f'  ERROR: {e}')
            return _pend_ungated(project_dir, ordered[i:], pass_name, str(e))
        if blocking:
            cmd_write._log_blockers(blocking)
            return _pend_ungated(project_dir, ordered[i:], pass_name,
                                 'an earlier scene waits on the gate: '
                                 + '; '.join(b.split(':')[0] for b in blocking))
        scene_file = os.path.join(scenes_dir, f'{sid}.md')
        with open(scene_file, encoding='utf-8') as f:
            original = f.read()
        passed, why = cmd_write._gate_drafted_scene(project_dir, sid, scene_file, 'revise',
                                                    log_dir, before=before)
        _restore_gate_markers(project_dir, sid, scene_file, original)
        if passed:
            try:   # the gate's commit cleared it; a stub or a failed update may not have
                gate.clear_pending(project_dir, sid)
            except gate.GateError as e:
                log(f'  WARNING: {sid} passed, but {gate.PENDING_PATH} still lists it as '
                    f'not gated ({e}); remove its row.')
        else:
            log(f'  ERROR: the gate did not pass the revision of {sid}: {why}')
            return ([f'{sid} (the gate did not pass it: {why})']
                    + _pend_ungated(project_dir, rest, pass_name, f'the gate stopped at {sid}'))
        # one budget for the session: the pass's spend and the gate runs
        # still owed (the rest of this pass) come first
        run = cmd_write.budgeted_recheck(project_dir, os.path.join(log_dir, 'gate'),
                                         set(rest), budget,
                                         reserved=len(rest) * gate.RECHECK_COST_PER_SCENE)
        if run is not None:
            if run.failed:
                trouble = (f'{run.failed} (re-checked after {sid} and did not pass: '
                           f'{run.why}; listed in {gate.PENDING_PATH})')
            elif run.over_budget:
                trouble = (f'{", ".join(run.left)} (listed for a re-check after {sid}, not '
                           f'run: over the cost threshold; `storyforge check --pending`)')
    return [trouble] if trouble else []


def _pend_ungated(project_dir: str, scene_ids: list[str], pass_name: str,
                  why: str, announce: bool = True) -> list[str]:
    """List scenes a pass rewrote but the gate hasn't passed as `revise`
    rows; return the line naming them (none when `announce` is off)."""
    from storyforge import cmd_write
    if not scene_ids:
        return []
    state = why if why == 'not gated yet' else f'not gated: {why}'
    for sid in scene_ids:
        cmd_write._pend(project_dir, sid, 'revise',
                        f'revised by pass {pass_name} but {state}. Its earlier version\'s '
                        f'facts are still in the ledger and may no longer match the prose.')
    if not announce:
        return []
    log(f'  Not gated ({why}): {", ".join(scene_ids)}')
    return [f'{", ".join(scene_ids)} (revised, not gated: {why})']


def pass_gate_advice(resume: str) -> str:
    """What to do after `_gate_pass_scenes` stopped; `resume` is the command
    that carries on (it differs between the plan's passes and the polish loop)."""
    return ('The revised prose is kept and committed. Each scene named above is listed in '
            'working/gate-pending.csv (an ERROR above names any that could not be): fix the '
            'first one\'s prose (or redraft it with `storyforge write --force --scenes <id>`), '
            f'run `storyforge check --pending`, then {resume}.')


def _reading_order(project_dir: str, scene_ids: list[str]) -> list[str]:
    """`scene_ids` in reading order (revise stops up front on a scene
    without a numeric seq, or scenes sharing one, `ledger.exit_if_unordered`)."""
    from storyforge import ledger
    order = ledger.scene_order(project_dir)
    return sorted(scene_ids, key=lambda s: (s not in order, order.get(s, 0), s))


def _leaning(project_dir: str, scene_id: str) -> str:
    """Why `scene_id` can't be redrafted before spending ('' when it can),
    the check `write` makes: an earlier scene waits on the gate
    (`working/gate-pending.csv`), so the ledger lacks its facts. Later facts
    leaning on its commitments are no reason: the scenes they are in are
    re-checked after its redraft passes (Phase 4)."""
    from storyforge import cmd_write, gate
    try:
        blocking = cmd_write._gate_blockers(project_dir, scene_id)
    except gate.GateError as e:
        log(f'    ERROR: {e}')
        return f'{scene_id} (not redrafted: {e})'
    if blocking:
        cmd_write._log_blockers(blocking)
        return (f'{scene_id} (not redrafted: earlier scene(s) wait on the gate: '
                + '; '.join(b.split(':')[0] for b in blocking) + ')')
    return ''


def _stopped_at(scene_id: str, why: str, rest: list[str]) -> list[str]:
    """What `RedraftError` says when the gate stops a run of redrafts."""
    log(f'    ERROR: the gate did not pass the redraft of {scene_id}: {why}')
    return [f'{scene_id} (redrafted, but the gate did not pass it and it is listed in '
            f'working/gate-pending.csv: {why})'] + _not_reached(rest)


def _not_reached(rest: list[str]) -> list[str]:
    out = []
    if rest:
        log(f'    Stopping: {len(rest)} later scene(s) not redrafted, as write stops '
            f'at a scene the gate does not pass')
        out.append(f'{", ".join(rest)} (not redrafted: redrafting stops at a scene the '
                   f'gate does not pass)')
    return out


REDRAFT_ADVICE = (
    'Their briefs were rewritten. For each scene named above: one the gate did not '
    'pass was redrafted and is listed in working/gate-pending.csv: fix its prose and run '
    '`storyforge check <id>`. A later scene whose re-check failed after a redraft is '
    'listed there too: fix it and run `storyforge check --pending`. Any other (no reply, an earlier scene waiting on the gate, '
    'or not reached) still has its old prose: once the scenes before it pass the gate, '
    'redraft it with `storyforge write --force --coaching full --scenes <id>`.')


def _report_redraft_error(e: 'RedraftError') -> None:
    """Tell the author what to do about what ``_redraft_from_briefs`` could
    not redraft or the gate did not pass. Their passes are already
    completed, so re-running revise would not."""
    log(f'ERROR: {e}')
    log(REDRAFT_ADVICE)


def _count_passes(rows):
    return len(rows)


def _collect_upstream_scenes(plan_rows: list) -> tuple:
    """Scan plan for pending upstream passes and collect all target scenes.

    Returns (scene_ids, upstream_pass_count). Used to defer redrafting
    until all upstream CSV fixes are complete.
    """
    scenes = set()
    count = 0
    for row in plan_rows:
        if row.get('fix_location') not in ('brief', 'intent'):
            continue
        if row.get('status') == 'completed':
            continue
        count += 1
        targets = row.get('targets', '')
        for sid in targets.split(';'):
            sid = sid.strip()
            if sid:
                scenes.add(sid)
    return scenes, count


def _read_pass_field(rows, pass_num, field):
    """Read a field from a pass (1-indexed)."""
    idx = pass_num - 1
    if 0 <= idx < len(rows):
        return rows[idx].get(field, '')
    return ''


def _update_pass_field(rows, pass_num, field, value, plan_file):
    """Update a field for a pass and write back."""
    idx = pass_num - 1
    if 0 <= idx < len(rows):
        rows[idx][field] = value
        _write_csv_plan(plan_file, rows)


# ============================================================================
# Auto-generated plans
# ============================================================================

def _generate_polish_plan(plan_file, project_dir='', *, write=True):
    """Generate a single-pass craft-only polish plan (`write=False`: the
    rows only, for `_save_plan` once the run's forecast is approved)."""
    # Load AI-tell vocabulary for inclusion in guidance
    from storyforge.prompts import load_ai_tell_words, load_voice_profile, merge_banned_words
    plugin_dir = get_plugin_dir()
    ai_words = load_ai_tell_words(plugin_dir)

    if project_dir:
        profile, _ = load_voice_profile(project_dir)
        banned = merge_banned_words(profile, ai_words)
    else:
        banned = [w['word'] for w in ai_words if w.get('severity') == 'high']

    banned_str = ', '.join(banned) if banned else ''

    guidance = ('Follow the voice guide strictly. Focus on: em dash overuse, '
                'antithesis framing, tricolon, hedge-stacking, sentence rhythm variety. '
                'Enter late, leave early.')
    if banned_str:
        guidance += f' Banned vocabulary (remove or replace): {banned_str}.'

    rows = [{
        'pass': '1',
        'name': 'prose-polish',
        'purpose': 'Voice consistency, prose naturalness, dialogue authenticity, AI pattern cleanup',
        'scope': 'full',
        'targets': '',
        'guidance': guidance,
        'protection': 'voice-quality',
        'findings': 'polish',
        'status': 'pending',
        'model_tier': 'opus',
        'fix_location': 'craft',
    }]
    if write:
        _save_plan(plan_file, rows, 'single-pass polish')
    return rows


def _build_naturalness_pass3_guidance(project_dir: str = '') -> str:
    """Build Pass 3 guidance, loading vocabulary from ai-tell-words.csv
    and project voice profile."""
    from storyforge.prompts import load_ai_tell_words, load_voice_profile, merge_banned_words

    plugin_dir = get_plugin_dir()
    ai_words = load_ai_tell_words(plugin_dir)

    # Merge with project-level banned words if available
    if project_dir:
        project_profile, _ = load_voice_profile(project_dir)
        all_banned = merge_banned_words(project_profile, ai_words)
    else:
        all_banned = [w['word'] for w in ai_words if w.get('severity') == 'high']

    vocab_words = [w['word'] for w in ai_words if w['category'] == 'vocabulary']
    hedging_words = [w['word'] for w in ai_words if w['category'] == 'hedging']

    if all_banned:
        vocab_str = ', '.join(all_banned)
    elif vocab_words:
        vocab_str = ', '.join(vocab_words)
    else:
        vocab_str = ('nuanced, multifaceted, tapestry, palpable, pivotal, intricate, '
                     'profound, myriad, juxtaposition, dichotomy, paradigm, visceral')

    if hedging_words:
        hedging_str = ', '.join(hedging_words)
    else:
        hedging_str = ('"something like", "something between", "almost as if", "perhaps", '
                       '"a kind of", "the particular"')

    return (
        'Four patterns to fix: '
        f'(a) AI-TELL VOCABULARY: Remove or replace these words that signal AI-generated prose: '
        f'{vocab_str}. Replace with concrete, specific words. '
        f'(b) HEDGING STACKS: {hedging_str} — remove or commit to the statement. '
        'BEFORE: "Something that tasted the way silence feels." AFTER: Name the taste. '
        '(c) SWEEPING OPENERS: Remove scene-opening sentences that set a thematic frame before anything happens. '
        '"The thing about memory is..." / "There are moments when..." — cut to the first concrete action or image. '
        '(d) SUMMARY CLOSERS: Remove paragraph-ending sentences that interpret what was just shown. '
        '"And that was the thing about X." / "It was, she realized, exactly what she needed." '
        '— let the scene end on action or image.'
    )


def _generate_naturalness_plan(plan_file, project_dir='', *, write=True):
    """Generate 3-pass plan for AI prose pattern removal (`write=False`:
    the rows only, for `_save_plan` once the run's forecast is approved).

    Targets the patterns most frequently penalized in scoring rationales:
    tricolon/parallelism, em-dash/antithesis, and AI vocabulary/hedging.
    """
    rows = [
        {
            'pass': '1',
            'name': 'tricolon-parallelism',
            'purpose': 'Break compulsive three-item structures — triple-sensation chains, three-beat lists, three-clause parallel constructions',
            'scope': 'full',
            'targets': '',
            'guidance': (
                'Find every instance of three-item parallelism and vary the count or structure. '
                'PATTERNS TO FIX: '
                '(a) Three-adjective chains: "gold deepening to persimmon deepening to red" — vary to 2 or 4, or restructure. '
                '(b) Three-clause parallelism: "too short for the counter, too narrow for the bowls, too wide for the space" — collapse to 1-2 clauses or vary rhythm. '
                '(c) Triple-sensation stacking: "Color. Taste. Sight interpretation." repeated as a template — break the template, vary which senses appear and in what order. '
                '(d) Three-item lists in narration: "the noodle shop level, the market corridor, the junction" — sometimes 2 is enough. '
                'NOT EVERY THREE-ITEM LIST IS WRONG. Only fix the ones that feel mechanical or templated. '
                'Organic tricolon in dialogue or emphatic prose is fine. The test: could a reader predict the third item? If yes, fix it.'
            ),
            'protection': 'Do not change dialogue content, plot events, or character actions. Only modify prose rhythm and structure.',
            'findings': 'naturalness',
            'status': 'pending',
            'model_tier': 'opus',
            'fix_location': 'craft',
        },
        {
            'pass': '2',
            'name': 'em-dash-antithesis',
            'purpose': 'Reduce em-dash frequency and eliminate "Not X but Y" antithesis framing',
            'scope': 'full',
            'targets': '',
            'guidance': (
                'Two patterns to fix: '
                '(a) EM-DASH OVERUSE: Count em dashes in each scene. Target: max 3-4 per 1000 words. '
                'Replace with: periods (for parenthetical asides), commas (for appositives), '
                'colons (for elaboration), or restructure the sentence. Keep em dashes only for genuine interruptions or abrupt shifts. '
                '(b) ANTITHESIS FRAMING: Find "Not X. Y." / "Not X but Y" / "Not X — Y" constructions. '
                'BEFORE: "Not reflecting-the-sky black, just black." '
                'AFTER: Describe what it IS without first saying what it ISN\'T. Negation-then-correction is a Claude tic. '
                'Also fix: "Not literally X but..." and "Less X than Y" when used as the primary description.'
            ),
            'protection': 'Do not change dialogue, plot, or character actions. Preserve em dashes in dialogue for speech interruptions.',
            'findings': 'naturalness',
            'status': 'pending',
            'model_tier': 'opus',
            'fix_location': 'craft',
        },
        {
            'pass': '3',
            'name': 'ai-vocabulary-hedging',
            'purpose': 'Remove AI-tell vocabulary, hedging stacks, sweeping openers, and summary closers',
            'scope': 'full',
            'targets': '',
            'guidance': _build_naturalness_pass3_guidance(project_dir),
            'protection': 'Do not change dialogue, plot events, or character interiority that reveals new information.',
            'findings': 'naturalness',
            'status': 'pending',
            'model_tier': 'opus',
            'fix_location': 'craft',
        },
    ]
    if write:
        _save_plan(plan_file, rows, '3-pass naturalness')
    return rows


def _generate_structural_plan(project_dir, plan_file, *, write=True):
    """Generate CSV-only plan from structural proposals."""
    proposals_file = os.path.join(project_dir, 'working', 'scores', 'structural-proposals.csv')
    if not os.path.isfile(proposals_file):
        log(f'ERROR: No structural proposals found at {proposals_file}')
        log('Run: storyforge-validate --structural')
        sys.exit(1)

    # Read proposals (strip \r for CRLF safety)
    proposals = []
    with open(proposals_file, newline='', encoding='utf-8') as f:
        raw = f.read().replace('\r\n', '\n').replace('\r', '')
    reader = csv.DictReader(raw.splitlines(), delimiter='|')
    for row in reader:
        row = {k: (v if v is not None else '') for k, v in row.items()}
        if row.get('status', '').strip() == 'pending':
            proposals.append(row)

    if not proposals:
        log(f'ERROR: No pending proposals in {proposals_file}')
        sys.exit(1)

    # Save pre-revision scores, re-scored first when the saved ones are
    # older than the CSVs: a stale "before" skews the delta (#600)
    from storyforge.structural import refresh_structural_scores
    stale = refresh_structural_scores(project_dir)
    if stale:
        log(f'Structural scores re-computed before revising: {stale}')
    pre_scores = os.path.join(project_dir, 'working', 'scores', 'structural-latest.csv')
    if os.path.isfile(pre_scores):
        import shutil
        shutil.copy2(pre_scores, os.path.join(project_dir, 'working', 'scores', 'structural-pre-revision.csv'))

    log(f'Structural mode -- generating plan from {len(proposals)} proposals...')

    # Group by dimension
    from collections import OrderedDict
    groups = OrderedDict()
    for row in proposals:
        dim = row['dimension']
        if dim not in groups:
            groups[dim] = {'fix_location': row['fix_location'], 'targets': [], 'rationales': [], 'changes': []}
        target = row.get('target', 'global').strip()
        if target and target != 'global':
            groups[dim]['targets'].append(target)
        groups[dim]['rationales'].append(row.get('rationale', row.get('change', '')))
        change = row.get('change', '').strip()
        if change:
            groups[dim]['changes'].append(change)

    # Sort by fix_location priority
    priority = {'structural': 0, 'intent': 1, 'registry': 2, 'brief': 3}
    sorted_dims = sorted(groups.items(), key=lambda x: priority.get(x[1]['fix_location'], 9))

    from storyforge.structural import _PRESCRIPTIONS_FULL

    rows = []
    for i, (dim, info) in enumerate(sorted_dims, 1):
        # Build guidance from prescription text + proposal change directives
        guidance_parts = []
        prescription = _PRESCRIPTIONS_FULL.get(dim, '')
        if prescription:
            guidance_parts.append(prescription)
        if info['changes']:
            guidance_parts.append('Proposed changes: ' + '; '.join(info['changes']))
        guidance_text = ' '.join(guidance_parts)

        rows.append({
            'pass': str(i),
            'name': f'structural-{dim.replace("_", "-")}',
            'purpose': '; '.join(info['rationales']),
            'scope': 'full',
            'targets': ';'.join(info['targets']) if info['targets'] else '',
            'guidance': guidance_text,
            'protection': 'all-strengths',
            'findings': '',
            'status': 'pending',
            'model_tier': 'sonnet',
            'fix_location': info['fix_location'],
        })

    if write:
        _create_versioned_plan(plan_file, rows)

    for i, (dim, info) in enumerate(sorted_dims, 1):
        log(f'  Pass {i}: {dim} (fix_location: {info["fix_location"]})')

    return rows


def _generate_scores_plan(plan_file: str, diag_rows: list,
                          findings_dir: str = '', *, write: bool = True) -> list:
    """Generate a revision plan from scoring diagnosis data.

    Creates upstream (brief) passes for brief-root-cause items and
    targeted craft passes for craft-root-cause items. Returns empty list
    if no actionable items.
    """
    from collections import Counter

    # Filter to actionable scene-level items
    actionable = [r for r in diag_rows
                  if r.get('scale') == 'scene'
                  and r.get('priority') in ('high', 'medium')
                  and r.get('worst_items')]

    if not actionable:
        return []

    # Load deterministic findings for enhanced guidance
    findings_guidance = ''
    if findings_dir:
        findings = _load_findings(findings_dir)
        target_scenes = set()
        for item in actionable:
            for sid in item['worst_items'].split(';'):
                sid = sid.strip()
                if sid:
                    target_scenes.add(sid)
        findings_guidance = _build_findings_guidance(findings, sorted(target_scenes))

    # Separate by root cause
    brief_items = [r for r in actionable if r.get('root_cause') == 'brief']
    craft_items = [r for r in actionable if r.get('root_cause') != 'brief']

    rows = []
    pass_num = 0

    # Brief passes: rank scenes by frequency across principles
    if brief_items:
        scene_freq = Counter()
        scene_principles = {}
        for item in brief_items:
            for sid in item['worst_items'].split(';'):
                sid = sid.strip()
                if sid:
                    scene_freq[sid] += 1
                    scene_principles.setdefault(sid, []).append(
                        item['principle'].replace('_', ' '))

        ranked = [sid for sid, _ in scene_freq.most_common()]

        principle_names = sorted(set(
            item['principle'].replace('_', ' ') for item in brief_items))
        guidance = (
            'Score-driven upstream fixes. Weak principles: '
            + ', '.join(principle_names)
            + '. Scenes ranked by frequency of appearance across weak principles.'
            + ' Fix abstract, overspecified, or verbose brief fields.'
        )
        if findings_guidance:
            guidance += '\n\n' + findings_guidance

        pass_num += 1
        rows.append({
            'pass': str(pass_num),
            'name': 'score-driven-briefs',
            'purpose': f'Fix briefs for {len(ranked)} scenes with brief-root-cause issues across {len(brief_items)} principles',
            'scope': 'scene-level',
            'targets': ';'.join(ranked),
            'guidance': guidance,
            'protection': 'voice-quality',
            'findings': 'scores',
            'status': 'pending',
            'model_tier': 'sonnet',
            'fix_location': 'brief',
        })

    # Craft pass: targeted polish for craft-root-cause items
    if craft_items:
        craft_scenes = set()
        craft_principles = []
        for item in craft_items:
            craft_principles.append(
                f'{item["principle"].replace("_", " ")} (avg {item.get("avg_score", "?")})')
            for sid in item['worst_items'].split(';'):
                sid = sid.strip()
                if sid:
                    craft_scenes.add(sid)

        guidance = (
            'Score-driven craft polish. Target principles:\n'
            + '\n'.join(f'  - {p}' for p in craft_principles)
            + '\nFollow the voice guide strictly. Preserve plot, character, and continuity.'
        )
        if findings_guidance:
            guidance += '\n\n' + findings_guidance

        pass_num += 1
        rows.append({
            'pass': str(pass_num),
            'name': 'score-driven-craft',
            'purpose': f'Craft polish targeting {len(craft_items)} weak principles',
            'scope': 'scene-level',
            'targets': ';'.join(sorted(craft_scenes)),
            'guidance': guidance,
            'protection': 'voice-quality',
            'findings': 'scores',
            'status': 'pending',
            'model_tier': 'opus',
            'fix_location': 'craft',
        })

    if rows and write:
        _save_plan(plan_file, rows, 'score-driven')

    return rows


# ============================================================================
# Polish convergence loop
# ============================================================================

def _read_diagnosis(cycle_dir: str) -> list[dict]:
    """Read diagnosis.csv from a scoring cycle dir. Returns list of row dicts."""
    diag_file = os.path.join(cycle_dir, 'diagnosis.csv')
    if not os.path.isfile(diag_file):
        return []
    with open(diag_file, newline='', encoding='utf-8') as f:
        raw = f.read().replace('\r\n', '\n').replace('\r', '')
    rows = []
    reader = csv.DictReader(raw.splitlines(), delimiter='|')
    for row in reader:
        rows.append({k: (v if v is not None else '') for k, v in row.items()})
    return rows


def _summarize_diagnosis(diag_rows: list[dict]) -> dict:
    """Summarize diagnosis into counts and key metrics."""
    high = [r for r in diag_rows if r.get('priority') == 'high' and r.get('scale') == 'scene']
    medium = [r for r in diag_rows if r.get('priority') == 'medium' and r.get('scale') == 'scene']
    scene_rows = [r for r in diag_rows if r.get('scale') == 'scene']

    avg_scores = []
    for r in scene_rows:
        try:
            avg_scores.append(float(r.get('avg_score', '0')))
        except ValueError:
            pass

    overall_avg = sum(avg_scores) / len(avg_scores) if avg_scores else 0.0

    return {
        'high_count': len(high),
        'medium_count': len(medium),
        'high_principles': [r['principle'] for r in high],
        'medium_principles': [r['principle'] for r in medium],
        'overall_avg': overall_avg,
        'scene_principle_count': len(scene_rows),
    }


def _format_scores_table(diag_rows: list[dict]) -> str:
    """Format diagnosis rows as a markdown table for PR display."""
    scene_rows = [r for r in diag_rows if r.get('scale') == 'scene']
    if not scene_rows:
        return 'No issues detected.'

    lines = ['| Principle | Avg Score | Priority | Weakest Scenes |',
             '|-----------|-----------|----------|----------------|']
    for r in sorted(scene_rows, key=lambda x: x.get('priority', 'low') != 'high'):
        principle = r.get('principle', '').replace('_', ' ')
        avg = f'{float(r.get("avg_score", 0)):.2f}'
        priority = r.get('priority', '')
        worst = r.get('worst_items', '').replace(';', ', ')
        lines.append(f'| {principle} | {avg} | {priority} | {worst} |')
    return '\n'.join(lines)


def _load_findings(cycle_dir: str) -> dict:
    """Load deterministic scorer findings from a scoring cycle directory.

    Returns dict with 'repetition' (list of finding dicts) and
    'scenes' (dict mapping scene_id to list of finding dicts).
    """
    result = {'repetition': [], 'scenes': {}}

    # Load repetition findings (manuscript-wide)
    rep_path = os.path.join(cycle_dir, 'repetition-findings.csv')
    if os.path.isfile(rep_path):
        with open(rep_path, newline='', encoding='utf-8') as f:
            raw = f.read().replace('\r\n', '\n').replace('\r', '')
        reader = csv.DictReader(raw.splitlines(), delimiter='|')
        for row in reader:
            result['repetition'].append({
                'phrase': row.get('phrase', ''),
                'category': row.get('category', ''),
                'severity': row.get('severity', ''),
                'count': int(row.get('count', '0')),
                'scene_ids': row.get('scene_ids', '').split(';'),
            })

    # Load per-scene findings
    scene_path = os.path.join(cycle_dir, 'scene-findings.csv')
    if os.path.isfile(scene_path):
        with open(scene_path, newline='', encoding='utf-8') as f:
            raw = f.read().replace('\r\n', '\n').replace('\r', '')
        reader = csv.DictReader(raw.splitlines(), delimiter='|')
        for row in reader:
            sid = row.get('scene_id', '').strip()
            if sid:
                result['scenes'].setdefault(sid, []).append({
                    'principle': row.get('principle', ''),
                    'finding': row.get('finding', ''),
                    'detail': row.get('detail', ''),
                })

    return result


def _build_findings_guidance(findings: dict, target_scenes: list[str]) -> str:
    """Build two-layer guidance from deterministic scorer findings.

    Layer 1: Manuscript-wide repetition patterns (top 10, frequency-aware).
    Layer 2: Per-scene specifics for target scenes (top 5 per scene).
    """
    parts = []

    # Layer 1: Manuscript-wide repetition preamble
    rep = findings.get('repetition', [])
    if rep:
        top_rep = sorted(rep, key=lambda r: -r['count'])[:10]
        lines = ['Cross-scene repetition patterns (reduce frequency — keep some occurrences):']
        for r in top_rep:
            target = max(2, r['count'] // 5)
            lines.append(f'  - "{r["phrase"]}" ({r["count"]}x, {r["category"]}) '
                         f'— reduce to {target} occurrences')
        parts.append('\n'.join(lines))

    # Layer 2: Per-scene specifics
    scene_findings = findings.get('scenes', {})
    scene_lines = []
    for sid in target_scenes:
        if sid not in scene_findings:
            continue
        scene_hits = scene_findings[sid][:5]
        if not scene_hits:
            continue
        details = '; '.join(f'{h["principle"]}: {h["detail"]}' for h in scene_hits)
        scene_lines.append(f'  {sid}: {details}')

    if scene_lines:
        parts.append('Scene-specific findings:\n' + '\n'.join(scene_lines))

    return '\n\n'.join(parts)


def _build_polish_pr_body(title: str, scene_count: int, max_loops: int,
                          diag_rows: list[dict]) -> str:
    """Build the initial PR body for a polish loop run."""
    scores_table = _format_scores_table(diag_rows)
    summary = _summarize_diagnosis(diag_rows)

    return f"""## Polish Loop — {title}

{scene_count} scenes | {max_loops} max iterations

## Initial Deterministic Scores

Overall avg: **{summary['overall_avg']:.2f}** | {summary['high_count']} high | {summary['medium_count']} medium priority

{scores_table}

## Progress

- [x] Initial deterministic scoring
"""


def _update_pr_body_iteration(project_dir: str, pr_number: str,
                              iteration: int, summary: dict, *,
                              converged: bool = False) -> None:
    """Append an iteration result line to the PR body's Progress section."""
    if not pr_number:
        return

    body = get_pr_body(project_dir, pr_number)
    if not body:
        return

    status = (f'avg {summary["overall_avg"]:.2f}, '
              f'{summary["high_count"]} high / {summary["medium_count"]} medium')
    if converged:
        status += ' — converged'
    _note_pr_progress(project_dir, pr_number, f'- [x] Iteration {iteration} — {status}',
                      body=body)


def _note_pr_progress(project_dir: str, pr_number: str, line: str, body: str = '') -> None:
    """Append `line` to the polish loop's PR body (its Progress list)."""
    if not pr_number:
        return
    body = body or get_pr_body(project_dir, pr_number)
    if not body:
        return
    set_pr_body(project_dir, pr_number, body.rstrip('\n') + '\n' + line + '\n\n')


def _post_polish_summary_comment(project_dir: str, pr_number: str,
                                 baseline_diag: list[dict],
                                 final_det_diag: list[dict], *,
                                 final_llm_diag: list[dict] | None = None,
                                 stopped: str = '') -> None:
    """Post a summary comment comparing baseline and final scores
    (`stopped`: why the loop stopped short, put first)."""
    if not pr_number:
        return

    # Build before/after comparison table for deterministic scores
    baseline_by_p = {r['principle']: r for r in baseline_diag if r.get('scale') == 'scene'}
    final_by_p = {r['principle']: r for r in final_det_diag if r.get('scale') == 'scene'}
    all_principles = sorted(set(baseline_by_p) | set(final_by_p))

    lines = ['## Deterministic Score Changes', '',
             '| Principle | Baseline | Final | Delta |',
             '|-----------|----------|-------|-------|']
    for p in all_principles:
        name = p.replace('_', ' ')
        b_score = float(baseline_by_p[p]['avg_score']) if p in baseline_by_p else 0.0
        f_score = float(final_by_p[p]['avg_score']) if p in final_by_p else 0.0
        delta = f_score - b_score
        sign = '+' if delta >= 0 else ''
        lines.append(f'| {name} | {b_score:.2f} | {f_score:.2f} | {sign}{delta:.2f} |')

    baseline_summary = _summarize_diagnosis(baseline_diag)
    final_summary = _summarize_diagnosis(final_det_diag)
    overall_delta = final_summary['overall_avg'] - baseline_summary['overall_avg']
    sign = '+' if overall_delta >= 0 else ''
    lines.append('')
    lines.append(f'**Overall avg: {baseline_summary["overall_avg"]:.2f} → '
                 f'{final_summary["overall_avg"]:.2f} ({sign}{overall_delta:.2f})**')

    # Full LLM scores section
    if final_llm_diag is not None:
        llm_table = _format_scores_table(final_llm_diag)
        llm_summary = _summarize_diagnosis(final_llm_diag)
        lines.extend(['', '## Full LLM Scores', '',
                      f'Overall avg: **{llm_summary["overall_avg"]:.2f}** | '
                      f'{llm_summary["high_count"]} high | '
                      f'{llm_summary["medium_count"]} medium priority', '',
                      llm_table])

    if stopped:
        lines[:0] = [f'**{stopped}**', '']
    add_pr_comment(project_dir, pr_number, '\n'.join(lines))


def _generate_targeted_polish_plan(plan_file: str, diag_rows: list[dict],
                                   findings_dir: str = '') -> list[dict]:
    """Generate a polish plan targeted at high/medium priority principles from diagnosis."""
    high = [r for r in diag_rows if r.get('priority') == 'high' and r.get('scale') == 'scene']
    medium = [r for r in diag_rows if r.get('priority') == 'medium' and r.get('scale') == 'scene']

    targets = high + medium
    if not targets:
        # Nothing specific to target — fall back to general polish
        return _generate_polish_plan(plan_file)

    # Build guidance from diagnosis findings
    guidance_parts = []
    for row in targets:
        principle = row['principle'].replace('_', ' ')
        avg = row.get('avg_score', '?')
        worst = row.get('worst_items', '')
        prio = row.get('priority', 'medium')
        part = f'{principle} (avg {avg}, {prio})'
        if worst:
            scenes = worst.split(';')[:3]
            part += f' — weakest in: {", ".join(scenes)}'
        guidance_parts.append(part)

    guidance = (
        'Diagnosis-driven polish. Priority principles to improve:\n'
        + '\n'.join(f'  - {g}' for g in guidance_parts)
        + '\nFollow the voice guide strictly. Preserve all plot, character, and continuity.'
    )

    worst_scenes = set()
    for row in targets:
        for sid in row.get('worst_items', '').split(';'):
            if sid.strip():
                worst_scenes.add(sid.strip())

    # Append deterministic findings to guidance
    if findings_dir:
        findings = _load_findings(findings_dir)
        target_scenes = sorted(worst_scenes) if worst_scenes else []
        findings_extra = _build_findings_guidance(findings, target_scenes)
        if findings_extra:
            guidance += '\n\n' + findings_extra

    rows = [{
        'pass': '1',
        'name': 'targeted-polish',
        'purpose': f'Address {len(high)} high and {len(medium)} medium priority craft principles',
        'scope': 'full',
        'targets': ';'.join(sorted(worst_scenes)) if worst_scenes else '',
        'guidance': guidance,
        'protection': 'voice-quality',
        'findings': 'polish',
        'status': 'pending',
        'model_tier': 'opus',
        'fix_location': 'craft',
    }]
    _create_versioned_plan(plan_file, rows)
    return rows


def _run_deterministic_score(project_dir: str,
                             scene_ids: list[str]) -> tuple[str, list[dict]]:
    """Run deterministic-only scoring (no API calls, $0 cost).

    Scores the 6 deterministic principles (prose_repetition, avoid_passive,
    avoid_adverbs, no_weather_dreams, sentence_as_thought, economy_clarity),
    generates diagnosis, and returns (cycle_dir, diag_rows).

    Same return signature as _run_lightweight_score for drop-in use.
    """
    from storyforge.scoring import merge_score_files, generate_diagnosis
    from storyforge.cmd_score import (
        DETERMINISTIC_PRINCIPLES,
        _score_repetition, _score_passive, _score_adverbs,
        _score_weather, _score_rhythm, _score_economy,
    )

    scores_base = os.path.join(project_dir, 'working', 'scores')

    # Determine cycle number
    highest = 0
    if os.path.isdir(scores_base):
        for name in os.listdir(scores_base):
            if name.startswith('cycle-'):
                try:
                    highest = max(highest, int(name.removeprefix('cycle-')))
                except ValueError:
                    pass
    cycle = highest + 1
    cycle_dir = os.path.join(scores_base, f'cycle-{cycle}')
    os.makedirs(cycle_dir, exist_ok=True)

    log(f'  Deterministic scoring {len(scene_ids)} scenes (cycle {cycle}, $0)...')

    scores_path = os.path.join(cycle_dir, 'scene-scores.csv')

    # Run each deterministic scorer and merge results
    scorers = [
        ('prose_repetition', _score_repetition),
        ('avoid_passive', _score_passive),
        ('avoid_adverbs', _score_adverbs),
        ('no_weather_dreams', _score_weather),
        ('sentence_as_thought', _score_rhythm),
        ('economy_clarity', _score_economy),
    ]
    for principle, scorer_fn in scorers:
        path = scorer_fn(scene_ids, project_dir, cycle_dir)
        merge_score_files(scores_path, path)

    # Generate diagnosis
    plugin_dir = get_plugin_dir()
    weights_file = os.path.join(project_dir, 'working', 'craft-weights.csv')

    # Initialize weights if not yet present
    from storyforge.scoring import init_craft_weights
    init_craft_weights(project_dir, plugin_dir)

    prev_dir = os.path.join(scores_base, f'cycle-{highest}') if highest > 0 else '-'
    if prev_dir != '-' and not os.path.isdir(prev_dir):
        prev_dir = '-'
    generate_diagnosis(cycle_dir, prev_dir, weights_file)

    # Update latest symlink
    latest_link = os.path.join(scores_base, 'latest')
    if os.path.islink(latest_link):
        os.remove(latest_link)
    os.symlink(f'cycle-{cycle}', latest_link)

    diag_rows = _read_diagnosis(cycle_dir)
    return cycle_dir, diag_rows


def _run_lightweight_score(project_dir: str, scene_ids: list[str],
                           parallel: int = 6) -> tuple[str, list[dict]]:
    """Run scene-level scoring only (no branch/PR) and return (cycle_dir, diagnosis_rows).

    This is a lightweight path for the polish loop — scores scenes, generates
    diagnosis, but skips branch creation, PR, act/character/genre scoring.
    """
    from storyforge.scoring import (
        build_evaluation_criteria, build_weighted_text,
        init_craft_weights, generate_diagnosis, merge_score_files,
    )

    plugin_dir = get_plugin_dir()
    scores_base = os.path.join(project_dir, 'working', 'scores')
    log_dir = os.path.join(project_dir, 'working', 'logs')

    # Determine cycle
    highest = 0
    if os.path.isdir(scores_base):
        for name in os.listdir(scores_base):
            if name.startswith('cycle-'):
                try:
                    highest = max(highest, int(name.removeprefix('cycle-')))
                except ValueError:
                    pass
    cycle = highest + 1
    cycle_dir = os.path.join(scores_base, f'cycle-{cycle}')
    os.makedirs(cycle_dir, exist_ok=True)
    os.makedirs(log_dir, exist_ok=True)

    # Initialize weights
    init_craft_weights(project_dir, plugin_dir)
    weights_file = os.path.join(project_dir, 'working', 'craft-weights.csv')

    # Load scoring templates
    prompts_dir = os.path.join(plugin_dir, 'scripts', 'prompts', 'scoring')
    diagnostics_csv = os.path.join(plugin_dir, 'references', 'diagnostics.csv')
    guide_file = os.path.join(plugin_dir, 'references', 'principle-guide.md')
    eval_template_file = os.path.join(prompts_dir, 'scene-evaluation.md')

    with open(eval_template_file) as f:
        eval_template = f.read()

    evaluation_criteria = build_evaluation_criteria(diagnostics_csv, guide_file)
    weighted_text_str = build_weighted_text(weights_file, exclude_section='narrative')

    # Use sonnet for speed in loop scoring
    eval_model = select_model('evaluation')

    metadata_csv = os.path.join(project_dir, 'reference', 'scenes.csv')
    intent_csv = os.path.join(project_dir, 'reference', 'scene-intent.csv')
    scenes_dir = os.path.join(project_dir, 'scenes')

    log(f'  Scoring {len(scene_ids)} scenes (cycle {cycle}, model: {eval_model})...')

    # Import scoring internals
    from storyforge.cmd_score import _score_direct, _build_scene_prompt, _parse_scene_evaluation

    import time as _time
    scored, failed = _score_direct(
        scene_ids, eval_model, eval_template, evaluation_criteria,
        weighted_text_str, metadata_csv, intent_csv, scenes_dir,
        cycle_dir, log_dir, diagnostics_csv, plugin_dir,
        parallel, _time.time(), project_dir,
    )

    log(f'  Scored: {scored}, failed: {len(failed)}' + (f' ({", ".join(failed)})' if failed else ''))

    # Generate diagnosis
    prev_dir = ''
    if highest > 0:
        prev_dir = os.path.join(scores_base, f'cycle-{highest}')

    generate_diagnosis(cycle_dir, prev_dir or '-', weights_file)

    # latest stays on the last complete cycle (as in cmd_score)
    from storyforge.project import mark_cycle_incomplete
    mark_cycle_incomplete(cycle_dir, [f'scene scores: {", ".join(failed)}']
                          if failed else [])
    if failed:
        log(f'  latest not moved: cycle-{cycle} has no scores for '
            f'{", ".join(failed)}')
    else:
        latest_link = os.path.join(scores_base, 'latest')
        if os.path.islink(latest_link):
            os.remove(latest_link)
        os.symlink(f'cycle-{cycle}', latest_link)

    diag_rows = _read_diagnosis(cycle_dir)
    return cycle_dir, diag_rows


def _detect_upstream_scenes(project_dir: str, diag_rows: list[dict]) -> list[str]:
    """Identify scenes needing upstream fixes based on diagnosis root_cause.

    Returns sorted list of scene IDs where root_cause is 'brief' and score is low.
    Scene IDs are drawn from the worst_items field of matching diagnosis rows.
    An adaptation's scenes with source drift are upstream too (#477; see
    `_source_drift_scenes`); without a `source:` block there are none.
    """
    upstream = set(_source_drift_scenes(project_dir))
    for row in diag_rows:
        if row.get('root_cause') != 'brief':
            continue
        worst = row.get('worst_items', '')
        if not worst:
            continue
        for sid in worst.split(';'):
            sid = sid.strip()
            if sid:
                upstream.add(sid)
    return sorted(upstream)


def _source_drift_scenes(project_dir: str, quiet: bool = False) -> dict[str, list[str]]:
    """An adaptation's scenes to fix toward the source: drift
    (`source_fidelity.drift_state`) on a brief or prose unchanged since it was
    scored. Says what it can't see: no results yet, and results scored on a
    brief or prose since changed. In `free` mode drift is listed for the
    author and nothing is returned: free mode doesn't undo departures."""
    from storyforge import source
    from storyforge.source_fidelity import drift_state
    cfg = source.read_config(project_dir)
    if cfg is None:
        return {}
    state = drift_state(project_dir)
    if quiet:
        return {} if cfg.mode == 'free' else state.drift
    if not state.checked:
        log('  Source fidelity: no results yet, so source drift is not checked; run '
            '`storyforge score --source-fidelity briefs` (or a full score for the prose)')
    elif state.stale:
        log(f'  Source fidelity: {len(state.stale)} result(s) scored on a brief or prose '
            f'changed since, not used: {", ".join(state.stale[:10])}'
            + (' ...' if len(state.stale) > 10 else '') + '; re-run score --source-fidelity')
    if state.drift and cfg.mode == 'free':
        log(f'  Source drift in {len(state.drift)} scene(s), left as it is (mode: free): '
            f'{", ".join(sorted(state.drift))}')
        return {}
    return state.drift


_PROSE_CONTEXT_WORDS = 6000  # of the scene's prose shown to the brief fix


# The fields the brief fix rewrites; their current text does not vouch for a
# name (an earlier fix may have invented it).
_BRIEF_FIX_FIELDS = ('goal', 'conflict', 'crisis', 'decision')
# What a source-drift fix rewrites (#477): drift is in events, outcomes and
# lines as well as in the dramatic four. Drift in on_stage or knowledge_out
# is shown to the fix but those are not rewritten here (they belong to the
# intent and the ledger); the fix can only bring the events back.
_SOURCE_FIX_FIELDS = ('goal', 'conflict', 'outcome', 'crisis', 'decision',
                      'key_actions', 'key_dialogue')


def _book_text(known_text: str, prose: str, brief: dict,
               fixed: tuple[str, ...] = _BRIEF_FIX_FIELDS) -> str:
    """What a rewrite of one scene's brief may name: the reference text, the
    scene's prose, and the brief fields the fix leaves alone."""
    kept = ' '.join(str(v) for k, v in brief.items() if k not in fixed)
    return '\n'.join((known_text, prose, kept))


def _scene_prose_excerpt(scene_id: str, prose: str | None) -> str:
    if prose is None:
        return '(not drafted yet)'
    words = prose.split()
    if len(words) <= _PROSE_CONTEXT_WORDS:
        return ' '.join(words)
    log(f'  Note: the brief fix for {scene_id} sees the first {_PROSE_CONTEXT_WORDS} '
        f'of its {len(words)} words')
    return ' '.join(words[:_PROSE_CONTEXT_WORDS]) + ' [...]'


def _brief_field_re(names: tuple[str, ...]) -> re.Pattern:
    alternation = '|'.join(n.upper() for n in names)
    return re.compile(rf'^[\s*_#>-]*({alternation})[*_]*\s*:[*_]*\s*(.*?)\s*$')


_BRIEF_FIELD_RE = _brief_field_re(_BRIEF_FIX_FIELDS)


def _parse_brief_fix(response: str,
                     names: tuple[str, ...] = _BRIEF_FIX_FIELDS) -> dict[str, str]:
    """The fields of a brief-fix reply, tolerating markdown bold."""
    pattern = _BRIEF_FIELD_RE if names == _BRIEF_FIX_FIELDS else _brief_field_re(names)
    fields = {}
    for line in response.splitlines():
        m = pattern.match(line)
        if m and m.group(2):
            fields[m.group(1).lower()] = m.group(2)
    return fields


class _SourceFixContext:
    """What every drift fix of one run needs, read once before the loop."""

    def __init__(self, project_dir: str):
        from storyforge import source
        from storyforge.prompts_source import _Tables
        self.cfg = source.read_config(project_dir)
        source.require_imported(project_dir, self.cfg)
        self.rows = source.map_rows_by_scene(source.read_source_map(project_dir) or [])
        self.cat = source.catalogue(project_dir, self.cfg)
        self.spans = source.spans(project_dir, self.cfg)
        self.rules = source.read_rules(project_dir, self.cfg) or '(none)'
        self.tables = _Tables(project_dir)


def _source_drift_fix(project_dir: str, scene_id: str, scene: dict, intent: dict,
                      brief: dict, prose: str | None, drift: list[str],
                      ctx: _SourceFixContext) -> tuple[str, str] | str:
    """The brief fix for a scene that drifted from its source (#477): the
    prompt and the source text the rewrite may also draw names from, or why
    there is none (its map row or source scenes are gone)."""
    from storyforge import source
    from storyforge.prompts_source import source_scene_block

    row = ctx.rows.get(scene_id)
    if row is None:
        return 'no row in the source map any more (run validate, then score)'
    refs = [source.resolve_source_id(r, ctx.cat)
            for r in source.split_ids(row.get('source_scenes', ''))]
    if not refs or None in refs:
        return 'its source scenes are not in the imported source (run validate)'
    outside = [f'{slug}:{sid}' for slug, sid in refs
               if source.outside_range((slug, sid), ctx.spans)]
    if outside:
        # Only the range is adapted: a fix toward a scene outside it would
        # pull the book past its span
        return (f'its source scenes {", ".join(outside)} are outside the adapted range '
                f'(run validate)')
    source_text = '\n\n'.join(source_scene_block(project_dir, slug, sid, prose=False,
                                                  tables=ctx.tables)
                               for slug, sid in refs)
    rules = ctx.rules
    current = '\n'.join(f'{k.upper()}: {brief.get(k, "")}' for k in _SOURCE_FIX_FIELDS)
    drift_lines = '\n'.join(f'- {d}' for d in drift)
    reply_format = '\n'.join(f'{k.upper()}: [rewritten {k}]' for k in _SOURCE_FIX_FIELDS)
    prompt = f"""You are a story editor bringing a scene's brief back to the source it adapts.

This novel adapts a source. A source-fidelity check found departures from the source that nothing authorized: not the scene's treatment, its note, or the version rules.

Scene: {scene.get('title', scene_id)}
POV: {scene.get('pov', '')}
On stage: {intent.get('on_stage', '')}
Treatment: {row.get('treatment', '')}
Note: {row.get('note', '') or '(none)'}

The source scene(s) it adapts:
{source_text}

Version rules:
{rules}

Current brief:
{current}

The scene as written:
<scene>
{_scene_prose_excerpt(scene_id, prose)}
</scene>

Drift found:
{drift_lines}

Rewrite the brief so it adapts the source again: undo each drift listed, keep every departure the treatment, its note or the version rules allow, and keep what isn't drift as it is. Use this novel's names, never the source prose's. OUTCOME is one of yes, no, yes-but, no-and, no-but. KEY_ACTIONS and KEY_DIALOGUE are semicolon-separated. Do not introduce any person, place or event that is in neither the source scenes nor this scene.

Respond ONLY with the {len(_SOURCE_FIX_FIELDS)} fields in this exact format (no preamble, no explanation):
{reply_format}"""
    return prompt, source_text


def _fix_upstream_briefs(project_dir: str,
                         scene_ids: list[str]) -> tuple[list[str], dict[str, str]]:
    """Rewrite goal/conflict/crisis/decision for scenes with upstream issues.

    Uses API to generate briefs with genuine dramatic opposition, from the
    scene's own characters, place, plan and prose. A rewrite is rejected with
    a WARNING, and the brief left as it was, when it lacks one of the four
    fields or names a capitalized word found nowhere in the reference files,
    this scene's prose or the brief fields the fix keeps. An adaptation's
    scene with source drift (`_source_drift_scenes`) gets the source-drift fix
    instead: shown the drift, its source scenes and the version rules, it
    rewrites `_SOURCE_FIX_FIELDS`, may also name what its source scenes name,
    and is refused on an outcome outside `schema.VALID_OUTCOMES` or when its
    map row or source scenes are gone. Returns the ids of
    the scenes whose briefs were rewritten (only those need a redraft) and,
    for each scene left unchanged, why.
    """
    from storyforge.elaborate import _read_csv_as_map, _write_csv, _FILE_MAP, _read_csv

    ref_dir = os.path.join(project_dir, 'reference')
    briefs_path = os.path.join(ref_dir, 'scene-briefs.csv')
    scenes_path = os.path.join(ref_dir, 'scenes.csv')
    intent_path = os.path.join(ref_dir, 'scene-intent.csv')

    briefs_map = _read_csv_as_map(briefs_path)
    scenes_map = _read_csv_as_map(scenes_path)
    intent_map = _read_csv_as_map(intent_path)

    known_text = reference_text(project_dir)
    rewritten: list[str] = []
    skipped: dict[str, str] = {}
    drift = _source_drift_scenes(project_dir)   # {} without a source block
    ctx = _SourceFixContext(project_dir) if drift else None

    for scene_id in scene_ids:
        brief = briefs_map.get(scene_id, {})
        prose_path = os.path.join(project_dir, 'scenes', f'{scene_id}.md')
        prose = read_text(prose_path) if os.path.isfile(prose_path) else None
        scene = scenes_map.get(scene_id, {})
        intent = intent_map.get(scene_id, {})

        title = scene.get('title', scene_id)
        pov = scene.get('pov', '')
        outcome = brief.get('outcome', '')
        value_at_stake = intent.get('value_at_stake', '')
        emotional_arc = intent.get('emotional_arc', '')
        current_goal = brief.get('goal', '')
        current_conflict = brief.get('conflict', '')
        current_crisis = brief.get('crisis', '')
        current_decision = brief.get('decision', '')

        prompt = f"""You are a story editor rewriting scene briefs to introduce genuine dramatic opposition.

Scene: {title}
POV: {pov}
Location: {scene.get('location', '')}
Characters: {intent.get('characters', '')}
On stage: {intent.get('on_stage', '')}
Function: {intent.get('function', '')}
Outcome: {outcome}
Value at stake: {value_at_stake}
Emotional arc: {emotional_arc}
Key actions: {brief.get('key_actions', '')}

Current brief:
GOAL: {current_goal}
CONFLICT: {current_conflict}
CRISIS: {current_crisis}
DECISION: {current_decision}

The scene as written:
<scene>
{_scene_prose_excerpt(scene_id, prose)}
</scene>

The current brief lacks genuine opposition — the conflict is abstract or the goal/crisis/decision don't create real dramatic tension.

Rewrite all four fields to introduce genuine opposition while:
- Preserving the existing emotional arc and value at stake
- Making the conflict a concrete, specific obstacle with a clear opposing force
- Making the goal something the POV character actively wants and must fight for
- Making the crisis a specific moment where the worst happens or the hardest choice appears
- Making the decision a concrete choice with real cost on both sides

Find the opposition inside this scene: its characters, its place, and what already happens in it. Do not introduce any person, place, organization or event that is not named above; the brief must still describe this book's scene.

Respond ONLY with the four fields in this exact format (no preamble, no explanation):
GOAL: [rewritten goal]
CONFLICT: [rewritten conflict]
CRISIS: [rewritten crisis]
DECISION: [rewritten decision]"""
        fix_fields = _BRIEF_FIX_FIELDS
        extra_known = ''
        if scene_id in drift:
            fix = _source_drift_fix(project_dir, scene_id, scene, intent, brief, prose,
                                    drift[scene_id], ctx)
            if isinstance(fix, str):
                skipped[scene_id] = fix
                log(f'  WARNING: Not fixing the source drift of {scene_id}: {fix}. '
                    f'Its brief is unchanged.')
                continue
            prompt, extra_known = fix
            fix_fields = _SOURCE_FIX_FIELDS
            log(f'  {scene_id}: fixing its source drift (this replaces the '
                f'dramatic-opposition fix: the source sets the opposition)')

        model = select_model('creative')
        log(f'  Fixing upstream brief: {scene_id}')
        response = invoke_api(prompt, model, max_tokens=1024)

        if not response:
            skipped[scene_id] = 'no reply'
            log(f'  WARNING: No response for {scene_id} upstream fix. Its brief is unchanged.')
            continue

        fields = _parse_brief_fix(response, fix_fields)
        missing = [k.upper() for k in fix_fields if k not in fields]
        if missing:
            skipped[scene_id] = f'reply lacked {", ".join(missing)}'
            log(f'  WARNING: Not rewriting the brief of {scene_id}: the reply has no '
                f'{", ".join(missing)}. Its brief is unchanged.')
            continue

        if fix_fields is _SOURCE_FIX_FIELDS:
            fields = {k: csv_safe(v) for k, v in fields.items()}
            from storyforge.schema import VALID_OUTCOMES
            if fields['outcome'] not in VALID_OUTCOMES:
                skipped[scene_id] = f'outcome {fields["outcome"]!r}'
                log(f'  WARNING: Not rewriting the brief of {scene_id}: the outcome '
                    f'{fields["outcome"]!r} is not one of {", ".join(sorted(VALID_OUTCOMES))}. '
                    f'Its brief is unchanged.')
                continue

        invented = invented_names(list(fields.values()),
                                   _book_text(known_text + '\n' + extra_known, prose or '',
                                              brief, fix_fields))
        if invented:
            skipped[scene_id] = f'named {", ".join(invented)}'
            log(f'  WARNING: Not rewriting the brief of {scene_id}: the rewrite names '
                f'{", ".join(invented)}, which appear nowhere in the reference files '
                f'or this scene. Its brief is unchanged.')
            continue

        briefs_map.setdefault(scene_id, {'id': scene_id})
        briefs_map[scene_id].update(fields)
        rewritten.append(scene_id)
        log(f'  Updated {len(fields)} fields for {scene_id}')

    # Write back updated briefs
    if rewritten:
        all_briefs = list(briefs_map.values())
        _write_csv(briefs_path, all_briefs, _FILE_MAP['scene-briefs.csv'])

    return rewritten, skipped


def _fix_and_redraft(project_dir: str,
                     scene_ids: list[str]) -> tuple[list[str], dict[str, str]]:
    """Rewrite the scenes' briefs, then redraft only the scenes whose brief
    changed (a rejected or failed rewrite leaves its prose alone), and say
    which scenes were left unchanged and why. Returns what
    ``_fix_upstream_briefs`` returns."""
    fixed, skipped = _fix_upstream_briefs(project_dir, scene_ids)
    if skipped:
        log(f'  Brief fix left {len(skipped)} of {len(scene_ids)} scenes unchanged:')
        for sid, why in skipped.items():
            log(f'    {sid}: {why}')
    if fixed:
        _redraft_or_halt(project_dir, fixed)
    return fixed, skipped


def _redraft_or_halt(project_dir: str, scene_ids: list[str]) -> int:
    try:
        return _redraft_scenes(project_dir, scene_ids)
    except RedraftError as e:
        log(f'ERROR: {e}')
        log(REDRAFT_ADVICE)
        log('Nothing is committed: a scene the gate passed has its facts in '
            'reference/commitments.csv, and one it did not pass is listed in '
            'working/gate-pending.csv. To undo the whole run instead, restore with '
            '`git checkout -- reference/ scenes/` and delete those scenes\' rows from '
            'working/gate-pending.csv.')
        sys.exit(1)


class RedraftError(Exception):
    """Scenes whose briefs were rewritten but whose prose could not be re-drafted."""


def _redraft_scenes(project_dir: str, scene_ids: list[str]) -> int:
    """Re-draft scenes after brief rewrites using brief-aware drafting:
    `write`'s prompt (`cmd_write._build_prompt`) as a rewrite, the old prose
    its voice reference only (plan §3.4), with the earlier prose in the
    system prompt as `_redraft_from_briefs` sends it. Only at `full`
    coaching and with briefs: otherwise RedraftError before anything is
    spent.

    Only re-drafts scenes that already have a scene file. A reply that fails
    ``parsing.unsafe_scene_reason`` (truncated, or a collapsed word count) is
    never written. Scenes go in reading order and each redraft is gated
    (``_gate_redraft``); redrafting stops at the first scene it couldn't
    redraft (no prompt, no reply, an unsafe reply) or the gate doesn't pass,
    and RedraftError names it with the scenes not reached, since its
    rewritten brief and its prose now disagree. Returns number of scenes
    re-drafted.
    """
    from storyforge.cmd_write import _build_prompt, _detect_briefs
    from storyforge.common import get_coaching_level, build_shared_context
    from storyforge.parsing import extract_single_scene, unsafe_scene_reason
    from storyforge.prompts import prior_prose_blocks, prior_prose_mode
    from storyforge import ledger
    # Checked before anything is spent: a reply at coach or strict is a
    # guide, not prose, and would be written over the scene; without briefs
    # there is no plan to rewrite from
    coaching_level = get_coaching_level(project_dir)
    if coaching_level != 'full':
        raise RedraftError(f'{len(scene_ids)} scene(s) not re-drafted: coaching is '
                           f'{coaching_level}, which writes no prose: '
                           f'{", ".join(scene_ids)}')
    if not _detect_briefs(project_dir):
        raise RedraftError(f'{len(scene_ids)} scene(s) not re-drafted: '
                           f'reference/scene-briefs.csv has no briefs to rewrite from')
    try:
        prior_prose = prior_prose_mode(project_dir)
        if prior_prose != 'none':
            ledger.scene_order(project_dir)
    except ValueError as e:
        raise RedraftError(f'{len(scene_ids)} scene(s) not re-drafted: {e}') from e
    log(f'  Redrafting {len(scene_ids)} scene(s) as rewrites (prior prose: {prior_prose})')

    scenes_dir = os.path.join(project_dir, 'scenes')
    model = select_model('creative')
    count = 0
    failed: list[str] = []

    # Build shared context for prompt caching across all re-drafts
    system = build_shared_context(project_dir, model=model)

    log_dir = os.path.join(project_dir, 'working', 'logs')
    budget = _run_budget()
    rechecks_open: list[str] = []   # re-checks after a redraft that failed or didn't run
    scene_ids = _reading_order(project_dir, scene_ids)
    from storyforge import gate
    baseline = gate.snapshot(project_dir)   # the book before this run
    for i, scene_id in enumerate(scene_ids, 1):
        scene_file = os.path.join(scenes_dir, f'{scene_id}.md')
        if not os.path.isfile(scene_file):
            log(f'  Skipping re-draft of {scene_id} (not yet drafted)')
            continue

        stop = _leaning(project_dir, scene_id)
        if stop:
            failed += [stop] + _not_reached(scene_ids[i:])
            break
        log(f'  Re-drafting scene: {scene_id}')
        with open(scene_file, encoding='utf-8') as f:
            original_prose = f.read()
        try:
            # a rewrite from the fixed brief and the binding ledger, the old
            # prose its voice reference (plan §3.4), as `_redraft_from_briefs`
            # and `write --force` draft it, with the earlier prose before it
            prompt = _build_prompt(scene_id, project_dir, coaching_level, use_briefs=True,
                                   system_context=bool(system), rewrite=True)
        except ValueError as e:   # a brief or its prose that can't be read
            prompt, why = '', f'no prompt: {e}'
        else:
            why = 'no prompt'
        try:
            scene_system = (list(system) + prior_prose_blocks(scene_id, project_dir,
                                                              prior_prose)
                            if system else system)
        except (OSError, UnicodeDecodeError, ValueError) as e:
            prompt, why = '', f'could not read the earlier prose: {e}'
        # Each failure stops the run: the scenes after it would be drafted
        # with its stale prose among the earlier scenes, as `write` stops
        if not prompt:
            log(f'  ERROR: Could not build a prompt for {scene_id}: {why}')
            failed += [f'{scene_id} ({why})'] + _not_reached(scene_ids[i:])
            break

        response = invoke_api(prompt, model, max_tokens=16384,
                              label=f'redraft {scene_id}', system=scene_system or None,
                              fallback=True)
        if not response:
            log(f'  ERROR: No response for {scene_id} re-draft')
            failed += [f'{scene_id} (no response)'] + _not_reached(scene_ids[i:])
            break

        extracted = extract_single_scene(response)
        revised = extracted if extracted else response
        reason = unsafe_scene_reason(revised, original_prose)
        if reason:
            log(f'  ERROR: Not writing the re-draft of {scene_id}: {reason}')
            failed += [f'{scene_id} ({reason})'] + _not_reached(scene_ids[i:])
            break

        # A model has no reason to reproduce an illustration marker, and losing
        # one silently costs the author an illustration that nothing downstream
        # would flag (#278). Restore what the rewrite dropped.
        from storyforge.illustrations import preserve_markers
        preserved = preserve_markers(project_dir, original_prose, revised)
        if preserved['restored']:
            log(f'  restored {len(preserved["restored"])} illustration '
                f'marker(s) the rewrite dropped: '
                f'{", ".join(preserved["restored"])}')
        for lost in preserved['lost']:
            log(f'  WARNING: illustration marker {lost!r} was in {scene_id} '
                f'and the rewrite dropped it; its anchor no longer matches the '
                f'revised prose, so it could not be restored. Re-anchor the '
                f'plan row and run `storyforge illustrate --embed`')

        with open(scene_file, 'w', encoding='utf-8') as f:
            f.write(preserved['text'])
        count += 1
        log(f'  Re-drafted {scene_id}')
        why = _gate_redraft(project_dir, scene_id, scene_file, log_dir, before=baseline)
        _restore_gate_markers(project_dir, scene_id, scene_file, original_prose,
                              preserved['lost'])
        if why:
            failed += _stopped_at(scene_id, why, scene_ids[i:])
            break
        _note_recheck(rechecks_open, scene_id,
                      _recheck_after(project_dir, log_dir, set(scene_ids[i:]), budget))

    if failed:
        raise RedraftError(f'{len(failed)} scene(s) not re-drafted: {"; ".join(failed)}')
    _raise_if_rechecks_open(rechecks_open)
    return count


def _stop_loop_if_over(project_dir: str, next_cost: float, *, after: float,
                       what: str, resume: str = '', pr_number: str = '',
                       baseline_diag: list[dict] | None = None,
                       latest_diag: list[dict] | None = None) -> None:
    """Stop the polish loop (exit 1) before `what` when the run's spend so
    far plus its forecast `next_cost` and `after` (the full score still
    owed) would pass the cost threshold. Everything the loop did before is
    committed (each iteration commits its pass; the scores since are
    committed here), and the draft PR gets the stop in its progress list
    and the summary comment a finished loop posts. `resume` says how to
    carry on."""
    over = _over_threshold(next_cost + after)
    if not over:
        return
    log(f'ERROR: {what} (~${next_cost:.2f})'
        + (f' and the full score after the loop (~${after:.2f})' if after else '')
        + f': {over}. Stopping before {what}; the work before it is committed. '
          f'Raise STORYFORGE_COST_THRESHOLD and {resume or POLISH_RESUME}.')
    _commit(project_dir, 'Polish: stopped at the cost threshold', ['working/'])
    note = f'Stopped before {what} at the cost threshold: {over}'
    _note_pr_progress(project_dir, pr_number, f'- [ ] {note}')
    _post_polish_summary_comment(project_dir, pr_number, baseline_diag or [],
                                 latest_diag or [], stopped=note)
    sys.exit(1)


def _undo_scores(project_dir: str, cycle_dir: str, latest_before: str | None) -> str:
    """Take back what a deterministic score wrote (`cycle_dir`, and
    working/scores/latest repointed at it) for a loop refused before it
    started; says what was done."""
    import shutil
    if not cycle_dir:
        return ''
    latest = os.path.join(project_dir, 'working', 'scores', 'latest')
    if os.path.isdir(cycle_dir):
        shutil.rmtree(cycle_dir)
    if os.path.islink(latest):
        os.remove(latest)
    if latest_before is not None:
        os.symlink(latest_before, latest)
    return (f' (the deterministic scores it wrote, {os.path.basename(cycle_dir)}, '
            f'are removed, and working/scores/latest is as it was)')


def _run_polish_loop(project_dir: str, max_loops: int,
                     coaching_override: str | None, *,
                     skip_initial_score: bool = False,
                     skip_final_score: bool = False) -> None:
    """`_polish_loop` under one budget for the run (`_budget_scope`: `main`'s
    when it runs there)."""
    with _budget_scope():
        _polish_loop(project_dir, max_loops, coaching_override,
                     skip_initial_score=skip_initial_score,
                     skip_final_score=skip_final_score)


def _polish_loop(project_dir: str, max_loops: int,
                 coaching_override: str | None, *,
                 skip_initial_score: bool = False,
                 skip_final_score: bool = False) -> None:
    """Two-phase polish loop: deterministic scoring → full LLM scoring.

    Phase 1: Score only deterministic principles (free, instant), polish with
    Sonnet (mechanical fixes), repeat until converged or max_loops reached.

    Phase 2: Run one full LLM scoring pass for the complete picture (unless
    --skip-final-score is set).
    """
    from storyforge.scene_filter import build_scene_list

    if coaching_override:
        os.environ['STORYFORGE_COACHING'] = coaching_override

    title = read_yaml_field('project.title', project_dir) or '(untitled)'
    metadata_csv = os.path.join(project_dir, 'reference', 'scenes.csv')
    scenes_dir = os.path.join(project_dir, 'scenes')

    # Build scene list (only drafted scenes)
    all_ids = build_scene_list(metadata_csv)
    scene_ids = [sid for sid in all_ids
                 if os.path.isfile(os.path.join(scenes_dir, f'{sid}.md'))]

    if not scene_ids:
        log('ERROR: No drafted scenes found.')
        sys.exit(1)

    log('============================================')
    log(f'Storyforge Polish Loop — {title}')
    log(f'Scenes: {len(scene_ids)}')
    log(f'Max iterations: {max_loops}')
    log('============================================')

    csv_plan_file = os.path.join(project_dir, 'working', 'plans', 'revision-plan.csv')
    sonnet_model = select_model('evaluation')

    # ------------------------------------------------------------------
    # Initial scoring (before the loop)
    # ------------------------------------------------------------------
    if skip_initial_score:
        latest_dir = os.path.join(project_dir, 'working', 'scores', 'latest')
        if not os.path.isdir(latest_dir):
            log('ERROR: --skip-initial-score but no existing scores in working/scores/latest')
            sys.exit(1)
        baseline_diag = _read_diagnosis(latest_dir)
        if not baseline_diag:
            log('ERROR: --skip-initial-score but no diagnosis.csv in existing scores')
            log('  Run a scoring cycle first, or remove --skip-initial-score')
            sys.exit(1)
        log('  Skipped initial scoring (--skip-initial-score) — using existing scores')
    else:
        log(f'\n=== Initial Deterministic Score ===')
        latest = os.path.join(project_dir, 'working', 'scores', 'latest')
        latest_before = os.readlink(latest) if os.path.islink(latest) else None
        scored_dir, baseline_diag = _run_deterministic_score(project_dir, scene_ids)

    baseline_summary = _summarize_diagnosis(baseline_diag)
    log(f'  Overall avg: {baseline_summary["overall_avg"]:.2f}')
    log(f'  High priority: {baseline_summary["high_count"]} principles')
    log(f'  Medium priority: {baseline_summary["medium_count"]} principles')
    if baseline_summary['high_principles']:
        log(f'    High: {", ".join(p.replace("_", " ") for p in baseline_summary["high_principles"])}')

    # The up-front forecast (#503), before anything is spent, a branch made
    # or the scores committed: the scoring above is free. How long the loop
    # runs isn't known, so every iteration is forecast; the brief fixes of
    # the scenes known now are in it, later ones are checked before their
    # iteration
    budget = _run_budget()
    per_pass = _pass_cost(project_dir, sonnet_model)
    final_cost = 0.0
    if not skip_final_score:
        avg_words, _ = _estimate_avg_words(project_dir)
        final_cost = estimate_cost('score', len(scene_ids), avg_words,
                                   select_model('evaluation'))
    upstream_next = _detect_upstream_scenes(project_dir, baseline_diag)
    fix_cost = _upstream_fix_cost(project_dir, upstream_next)
    forecast = max_loops * per_pass + fix_cost + final_cost
    from storyforge import gate
    log(f'Cost forecast: ~${forecast:.2f} for up to {max_loops} iterations @ '
        f'~${per_pass:.2f} (it stops sooner when it converges)'
        + (f', brief fixes and redrafts for {len(upstream_next)} scene(s) '
           f'~${fix_cost:.2f} (the gate on each redraft included)' if upstream_next else '')
        + (f', the full score ~${final_cost:.2f}' if final_cost else ''))
    log(f'  Not in it: the gate on each scene a pass rewrites (about '
        f'${gate.RECHECK_COST_PER_SCENE:.2f} each), brief fixes later iterations find, '
        f'and the re-checks. Before each iteration, and before its pass, what the run '
        f'has spent plus what comes next must fit the threshold.')
    over = _over_threshold(forecast)
    if over:
        undone = (_undo_scores(project_dir, scored_dir, latest_before)
                  if not skip_initial_score else '')
        # advice that can work: each part of the forecast that can go
        ways = []
        if max_loops > 1:
            ways.append(f'lower `--max-loops` (~${per_pass:.2f} an iteration)')
        if final_cost:
            ways.append(f'add `--skip-final-score` (~${final_cost:.2f})')
        if upstream_next:
            ways.append(f'fix the briefs of {", ".join(upstream_next)} first '
                        f'(`storyforge hone`, ~${fix_cost:.2f})')
        log(f'ERROR: {over}: nothing revised{undone}. Raise STORYFORGE_COST_THRESHOLD'
            + ''.join(f', or {w}' for w in ways) + '.')
        sys.exit(1)
    _log_recheck_budget()

    # Create branch once for the whole loop
    create_branch('revise', project_dir)
    ensure_branch_pushed(project_dir)

    # Commit initial scores and create PR
    _commit(project_dir, 'Polish: initial deterministic scores', ['working/'])
    pr_body = _build_polish_pr_body(title, len(scene_ids), max_loops, baseline_diag)
    pr_number = create_draft_pr(f'Polish: {title}', pr_body, project_dir,
                                work_type='polish')

    # ------------------------------------------------------------------
    # Phase 1: Deterministic scoring loop (free, instant)
    # ------------------------------------------------------------------
    log(f'\n=== Phase 1: Deterministic Polish (free) ===')

    prev_avg = baseline_summary['overall_avg']
    summary = baseline_summary
    latest_diag = baseline_diag
    brief_fix_skipped: dict[str, str] = {}

    for iteration in range(1, max_loops + 1):
        # Check for upstream causes before craft polish, and before the
        # convergence check: an adaptation's source drift is no craft score
        # (#477). A scene whose brief fix was turned down is not sent again:
        # the same request would cost the same and likely meet the same fate.
        found = (upstream_next if upstream_next is not None
                 else _detect_upstream_scenes(project_dir, latest_diag))
        upstream_next = None
        upstream_scenes = [s for s in found if s not in brief_fix_skipped]

        # Convergence check: no actionable issues. With no craft issues left,
        # only source drift is still fixed (as before, a diagnosis' brief
        # root cause alone doesn't hold the loop open)
        craft_converged = summary['high_count'] == 0 and summary['medium_count'] == 0
        if craft_converged:
            drift = _source_drift_scenes(project_dir, quiet=True)
            upstream_scenes = [s for s in upstream_scenes if s in drift]
            if not upstream_scenes:
                log('  No high or medium priority issues — converged')
                _update_pr_body_iteration(project_dir, pr_number, iteration, summary,
                                          converged=True)
                break

        # Before each iteration: what the run has spent, this iteration's
        # forecast and the full score after the loop must fit the threshold
        this_pass = 0.0 if craft_converged else per_pass
        stop_report = dict(pr_number=pr_number, baseline_diag=baseline_diag,
                           latest_diag=latest_diag)
        _stop_loop_if_over(project_dir,
                           _upstream_fix_cost(project_dir, upstream_scenes) + this_pass,
                           after=final_cost, what=f'iteration {iteration}', **stop_report)
        if upstream_scenes:
            log(f'  Upstream issues in {len(upstream_scenes)} scenes — fixing briefs first')
            # while they run, the rest of the loop's forecast is kept from
            # the re-checks their redrafts owe (with the craft converged, the
            # loop ends after them: only the full score is left)
            rest = 0.0 if craft_converged else this_pass + (max_loops - iteration) * per_pass
            with budget.reserving(rest + final_cost):
                fixed, skipped = _fix_and_redraft(project_dir, upstream_scenes)
            brief_fix_skipped.update(skipped)
            if fixed:
                _commit(project_dir,
                                f'Polish: upstream brief fixes for {len(fixed)} scenes',
                                ['reference/', 'scenes/', 'working/'])

        if craft_converged:
            log('  No high or medium priority issues; source drift fixed — converged')
            _update_pr_body_iteration(project_dir, pr_number, iteration, summary,
                                      converged=True)
            break

        if upstream_scenes:
            # the fixes may have cost more than their forecast (CR-M1)
            _stop_loop_if_over(project_dir, per_pass, after=final_cost,
                               what=f"iteration {iteration}'s pass", **stop_report)

        # Generate targeted plan from diagnosis and execute
        log(f'\n=== Iteration {iteration}/{max_loops}: Polish (Sonnet) ===')
        latest_cycle = os.path.join(project_dir, 'working', 'scores', 'latest')
        plan_rows = _generate_targeted_polish_plan(csv_plan_file, latest_diag,
                                                    findings_dir=latest_cycle)
        with budget.reserving((max_loops - iteration) * per_pass + final_cost):
            _execute_single_pass(project_dir, csv_plan_file, plan_rows, iteration,
                                 model_override=sonnet_model)

        # Re-score
        log(f'\n=== Iteration {iteration}/{max_loops}: Re-score ===')
        _, latest_diag = _run_deterministic_score(project_dir, scene_ids)
        summary = _summarize_diagnosis(latest_diag)

        log(f'  Overall avg: {summary["overall_avg"]:.2f}')
        log(f'  High priority: {summary["high_count"]} principles')

        # Update PR with iteration results
        converged = (summary['high_count'] == 0 and summary['medium_count'] == 0)
        if not converged and iteration > 1 and summary['overall_avg'] <= prev_avg:
            converged = True
            log(f'  Overall avg did not improve ({summary["overall_avg"]:.2f} <= '
                f'{prev_avg:.2f}) — converged')
        _update_pr_body_iteration(project_dir, pr_number, iteration, summary,
                                  converged=converged)

        if converged:
            break

        prev_avg = summary['overall_avg']

    else:
        log(f'\n  Reached max iterations ({max_loops})')

    # Commit deterministic phase results
    _commit(project_dir, 'Polish: deterministic phase complete', ['working/'])

    # ------------------------------------------------------------------
    # Phase 2: Full LLM scoring (one run for the complete picture)
    # ------------------------------------------------------------------
    final_llm_diag = None
    if skip_final_score:
        log(f'\n=== Skipping Phase 2: Full Score (--skip-final-score) ===')
        final_summary = summary
    else:
        _stop_loop_if_over(project_dir, final_cost, after=0.0,
                           what='the full score', resume='run `storyforge score` for it',
                           pr_number=pr_number, baseline_diag=baseline_diag,
                           latest_diag=latest_diag)
        log(f'\n=== Phase 2: Full Score ===')
        _, final_llm_diag = _run_lightweight_score(project_dir, scene_ids)
        final_summary = _summarize_diagnosis(final_llm_diag)
        _commit(project_dir, 'Polish: full score after deterministic loop',
                        ['working/'])

    # Post summary comment
    _post_polish_summary_comment(project_dir, pr_number,
                                 baseline_diag, latest_diag,
                                 final_llm_diag=final_llm_diag)

    log('\n============================================')
    report_fallback_replies()
    log('Polish loop complete')
    log(f'  Deterministic baseline: avg {baseline_summary["overall_avg"]:.2f}, '
        f'{baseline_summary["high_count"]} high / {baseline_summary["medium_count"]} medium priority')
    log(f'  Final: avg {final_summary["overall_avg"]:.2f}, '
        f'{final_summary["high_count"]} high / {final_summary["medium_count"]} medium priority')
    if baseline_summary['overall_avg'] > 0:
        delta = final_summary['overall_avg'] - baseline_summary['overall_avg']
        log(f'  Deterministic improvement: {delta:+.2f} avg score')
    log('============================================')


def _extract_scene_rationales(project_dir: str, scene_ids: list,
                              principles: list = None) -> dict:
    """Extract scoring rationales for specific scenes from the latest scoring cycle.

    Args:
        project_dir: Project root.
        scene_ids: Scenes to extract rationales for.
        principles: Principles to include (default: all *_rationale columns).

    Returns:
        {scene_id: {principle: rationale_text}}
    """
    from storyforge.elaborate import _read_csv_as_map

    latest_dir = os.path.join(project_dir, 'working', 'scores', 'latest')
    scores_file = os.path.join(latest_dir, 'scene-scores.csv')
    if not os.path.isfile(scores_file):
        return {}

    scores_map = _read_csv_as_map(scores_file)
    result = {}

    for sid in scene_ids:
        row = scores_map.get(sid)
        if not row:
            continue
        rationales = {}
        for col, val in row.items():
            if not col or not col.endswith('_rationale') or not val:
                continue
            principle = col[:-len('_rationale')]
            if principles and principle not in principles:
                continue
            rationales[principle] = val
        if rationales:
            result[sid] = rationales

    return result


def _build_revision_config(plan_row: dict, extra: dict | None = None) -> str:
    """Build a YAML config string from plan row fields for passing to revision.py.

    Only includes non-empty values for the known config fields: guidance,
    protection, findings, targets.  Additional optional data (e.g. rationale
    from Task 9) can be supplied via *extra*.

    Args:
        plan_row: A single plan CSV row dict.
        extra: Optional dict of additional key→value pairs to append.

    Returns:
        A YAML string, or empty string if no config fields are present.
    """
    config_fields = ['guidance', 'protection', 'findings', 'targets']
    lines = []
    for field in config_fields:
        value = plan_row.get(field, '')
        if value:
            # Indent multi-line values as a YAML block scalar
            if '\n' in value:
                indented = value.replace('\n', '\n  ')
                lines.append(f'{field}: |-\n  {indented}')
            else:
                lines.append(f'{field}: {value}')
    if extra:
        for key, value in extra.items():
            if value:
                if '\n' in str(value):
                    indented = str(value).replace('\n', '\n  ')
                    lines.append(f'{key}: |-\n  {indented}')
                else:
                    lines.append(f'{key}: {value}')
    return '\n'.join(lines)


def _execute_single_pass(project_dir: str, csv_plan_file: str,
                         plan_rows: list[dict], iteration: int,
                         model_override: str | None = None) -> None:
    """Execute a single revision pass from a plan. Subset of main pass loop."""
    from storyforge.common import select_revision_model, get_coaching_level, build_shared_context
    from storyforge.api import invoke_to_file, extract_text, fallback_replies, fallback_note

    pass_name = plan_rows[0].get('name', 'polish')
    served_before = len(fallback_replies())
    pass_purpose = plan_rows[0].get('purpose', '')
    pass_scope = plan_rows[0].get('scope', 'full')
    guidance = plan_rows[0].get('guidance', '')
    fix_location = plan_rows[0].get('fix_location', 'craft')

    log(f'  Pass: {pass_name}')
    log(f'  Purpose: {pass_purpose[:120]}...' if len(pass_purpose) > 120 else f'  Purpose: {pass_purpose}')

    # Mark in_progress
    _update_pass_field(plan_rows, 1, 'status', 'in_progress', csv_plan_file)

    # Build shared context for prompt caching
    pass_model_early = model_override or select_revision_model(pass_name, pass_purpose)
    system = build_shared_context(project_dir, model=pass_model_early)

    # Build prompt via the revision module (subprocess)
    plugin_dir = get_plugin_dir()
    revision_module = os.path.join(plugin_dir, 'scripts', 'lib', 'python', 'storyforge', 'revision.py')

    import subprocess
    # Extract per-scene rationales for targeted revision
    rationales = None
    targets_field = plan_rows[0].get('targets', '')
    if targets_field:
        target_ids = [s.strip() for s in targets_field.split(';') if s.strip()]
        rationales = _extract_scene_rationales(project_dir, target_ids)
    elif plan_rows[0].get('findings') == 'naturalness':
        # For naturalness passes, get rationales for all scenes
        from storyforge.scene_filter import build_scene_list
        metadata_csv = os.path.join(project_dir, 'reference', 'scenes.csv')
        all_ids = build_scene_list(metadata_csv)
        rationales = _extract_scene_rationales(project_dir, all_ids,
                                                principles=['prose_naturalness'])

    # Build config with rationales as extra data
    extra = {}
    if rationales:
        scene_findings = []
        for sid, rats in rationales.items():
            for principle, text in rats.items():
                # Truncate long rationales to keep prompt manageable
                scene_findings.append(f'Scene {sid} ({principle}): {text[:500]}')
        if scene_findings:
            extra['per_scene_findings'] = '\n'.join(scene_findings)

    config_yaml = _build_revision_config(plan_rows[0], extra=extra)
    cmd = [
        sys.executable, revision_module, 'build-prompt',
        pass_name, pass_purpose, pass_scope, project_dir,
        '--api-mode',
    ]
    if config_yaml:
        cmd.extend(['--config', config_yaml])
    # the loop's coaching level (`--coaching` sets it in the environment):
    # without it the prompt asks for prose at every level
    cmd.extend(['--coaching', get_coaching_level(project_dir)])
    if system:
        cmd.append('--system-context')

    log(f'  Building revision prompt...')
    result = subprocess.run(cmd, capture_output=True, text=True)
    if result.returncode != 0:
        log(f'  ERROR building prompt: {result.stderr[:500]}')
        return

    prompt = result.stdout
    _log_prompt_warnings(result.stderr)

    # Select model and invoke API
    pass_model = model_override or select_revision_model(pass_name, pass_purpose)
    log_dir = os.path.join(project_dir, 'working', 'logs')
    step_log = os.path.join(log_dir, f'loop-{iteration}-{pass_name}.json')

    gated = get_coaching_level(project_dir) == 'full'
    if gated:
        _exit_if_pass_blocked(project_dir, targets_field)

    from storyforge import gate
    gate_baseline = gate.snapshot(project_dir)   # prose written at any level is gated
    log(f'  Invoking API (model: {pass_model})...')
    try:
        invoke_to_file(prompt, pass_model, step_log,
                       max_tokens=max_output_tokens(pass_model),
                       label=f'polish loop {iteration} ({pass_name})',
                       timeout=REVISION_TIMEOUT,
                       system=system or None, fallback=True)
    except Exception as e:
        log(f'ERROR: Polish pass \'{pass_name}\' failed: {e}. The pass is not marked completed.')
        sys.exit(1)

    # Extract scenes from response. This once passed --project-dir/--log-file
    # flags extract-scenes does not take, so nothing was ever written and the
    # pass was still marked completed.
    log(f'  Extracting revised scenes...')
    python_lib = os.path.join(plugin_dir, 'scripts', 'lib', 'python')
    try:
        _written, skipped = _extract_scenes(step_log, project_dir, python_lib)
    except ExtractError as e:
        log(f'ERROR: Could not extract scenes from polish pass \'{pass_name}\': {e}')
        log(f'The pass is not marked completed. See {step_log}')
        sys.exit(1)

    # Phase 4 §5: each scene it wrote goes through the gate, in reading order
    # (at any coaching level: prose written is prose gated)
    gate_failures = _gate_pass_scenes(project_dir, _written, pass_name, log_dir,
                                      before=gate_baseline)

    # Update word counts
    _update_word_counts_from_dir(project_dir)

    # The scenes it did write are committed either way; a pass that skipped
    # some is not marked completed
    if not skipped:
        _update_pass_field(plan_rows, 1, 'status', 'completed', csv_plan_file)
    _commit(
        project_dir,
        f'Polish: loop iteration {iteration} — {pass_name}' + fallback_note(served_before),
        ['scenes/', 'reference/', 'working/'],
    )
    if skipped:
        _log_gate_failures(gate_failures)
        _fail_skipped_scenes(pass_name, skipped, step_log)
    if gate_failures:
        _fail_gated_pass(pass_name, gate_failures, POLISH_RESUME)


#: How each caller of `_fail_gated_pass` carries on once the gate passes
PLAN_RESUME = 're-run `storyforge revise` for the plan\'s passes left'
POLISH_RESUME = 're-run `storyforge revise --polish --loop`'


def _log_gate_failures(failures: list[str]) -> None:
    """Name what the gate didn't pass before another error stops the pass."""
    if failures:
        log('ERROR: the gate did not pass everything this pass changed:')
        for line in failures:
            log(f'  {line}')
        log(pass_gate_advice('re-run the pass'))


def _fail_gated_pass(pass_name: str, failures: list[str], resume: str,
                     redraft_needed: set[str] | frozenset[str] = frozenset()) -> None:
    """Stop the session after a pass whose revised scenes the gate did not
    all pass, or whose re-checks did not (`_gate_pass_scenes`): its scenes
    are committed, but the next pass would revise prose the ledger doesn't
    hold. `redraft_needed`: scenes whose briefs earlier passes rewrote and
    that the session would have redrafted at its end; they are named, since
    a re-run won't remember them."""
    log(f'ERROR: Pass \'{pass_name}\' wrote its scenes, but not everything it changed '
        f'passed the gate:')
    for line in failures:
        log(f'  {line}')
    log(pass_gate_advice(resume))
    if redraft_needed:
        log(f'Not redrafted: {len(redraft_needed)} scene(s) whose briefs this session '
            f'rewrote still have their old prose: {", ".join(sorted(redraft_needed))}. '
            f'Once the scenes before them pass the gate, redraft them with '
            f'`storyforge write --force --coaching full --scenes <ids>`.')
    sys.exit(1)


class ExtractError(Exception):
    """``parsing extract-scenes`` failed outright (no reply content)."""


def _extract_scenes(step_log: str, project_dir: str,
                    python_lib: str) -> tuple[list[str], dict[str, str]]:
    """Write the scenes a revision reply holds (``parsing extract-scenes``)
    and log what it says. Returns the scenes written and those the reply
    held but that were not written (cut off, ending mid-sentence, collapsed),
    with why. Raises ExtractError when the reply has no content at all."""
    result = subprocess.run(
        [sys.executable, '-m', 'storyforge.parsing', 'extract-scenes',
         step_log, os.path.join(project_dir, 'scenes')],
        capture_output=True, text=True,
        env={**os.environ, 'PYTHONPATH': python_lib},
    )
    if result.returncode != 0:
        raise ExtractError(result.stderr.strip()[:500] or f'exit {result.returncode}')
    written, skipped = [], {}
    for line in result.stdout.strip().splitlines():
        log(f'  {line}')
        if line.startswith('Wrote: '):
            written.append(line[len('Wrote: '):].strip())
        elif line.startswith('Skipped: '):
            sid, _, reason = line[len('Skipped: '):].partition(' -- ')
            skipped[sid.strip()] = reason.strip()
    return written, skipped


def _split_targets(targets: str) -> list[str]:
    return [t.strip() for t in (targets or '').split(';') if t.strip()]


def _owed_scenes(targets: str, written: list[str], skipped: dict[str, str],
                 cut_off: bool) -> str:
    """The `owed` value after a reply: the scenes it held but didn't write,
    and, when it was cut off, every target it didn't write (it never reached
    the scenes after the cut). A reply that ended normally may leave a target
    alone on purpose. A target keeps its `NEW:` prefix, so a re-run still
    registers the scene. With no targets (a full-scope pass), only the skipped
    scenes are known to be owed."""
    written_ids = set(written)
    entries = {t.removeprefix('NEW:'): t for t in _split_targets(targets)}
    owed = [entries.get(sid, sid) for sid in skipped]
    if cut_off:
        owed += [t for sid, t in entries.items()
                 if sid not in written_ids and sid not in skipped]
    return ';'.join(sorted(set(owed), key=lambda t: t.removeprefix('NEW:')))


def _fail_skipped_scenes(pass_name: str, skipped: dict[str, str], step_log: str,
                         owed_saved: bool = False) -> None:
    """Stop a pass whose reply held scenes that were not written: what it
    did write is committed, but the pass did not do its job for these.
    ``owed_saved``: the plan's `owed` column names them, so a re-run of the
    pass revises only these."""
    log(f'ERROR: Pass \'{pass_name}\' did not write {len(skipped)} scene(s); '
        f'their prose is unchanged:')
    for sid, reason in skipped.items():
        log(f'  {sid}: {reason}')
    if owed_saved:
        log(f'The scenes it did write are committed. The pass is not marked completed; '
            f're-run `storyforge revise` and it revises only these scenes. '
            f'See the reply: {step_log}')
    else:
        log(f'The scenes it did write are committed. The pass is not marked completed; '
            f're-run it for these scenes. See the reply: {step_log}')
    sys.exit(1)


def _update_word_counts_from_dir(project_dir: str) -> None:
    """Update word counts in scenes.csv from scene files."""
    from storyforge.elaborate import _read_csv, _write_csv, _FILE_MAP
    metadata_csv = os.path.join(project_dir, 'reference', 'scenes.csv')
    scenes_dir = os.path.join(project_dir, 'scenes')

    rows = _read_csv(metadata_csv)
    for row in rows:
        scene_file = os.path.join(scenes_dir, f'{row["id"]}.md')
        if os.path.isfile(scene_file):
            with open(scene_file) as f:
                wc = len(f.read().split())
            row['word_count'] = str(wc)

    _write_csv(metadata_csv, rows, _FILE_MAP['scenes.csv'])


# ============================================================================
# Usage logging helper
# ============================================================================

def _log_usage(project_dir, log_file, operation, target, model, duration_s=0):
    """Log API usage from a response file; a reply the refusal fallback
    wrote is priced and logged as that model's."""
    if not os.path.isfile(log_file):
        return
    try:
        with open(log_file) as f:
            response = json.load(f)
        model = fallback_model(response) or model
        usage = extract_usage(response)
        cost = calculate_cost_from_usage(usage, model)
        log_operation(
            project_dir, operation, model,
            usage['input_tokens'], usage['output_tokens'], cost,
            duration_s=duration_s, target=target,
            cache_read=usage.get('cache_read', 0),
            cache_create=usage.get('cache_create', 0),
        )
    except Exception as e:
        log(f'WARNING: could not log the cost of {operation} {target}: {e}')


# ============================================================================
# Word count estimation
# ============================================================================

def _estimate_avg_words(project_dir):
    """(Average words, scene count) over the book's drafted scenes:
    scenes.csv's `word_count`, or, for a scene whose count is blank, 0 or
    not a number, its file's own word count. (#510's review, SF-5: such
    scenes were left out of the count, pricing every pass as if the book
    were that much shorter.) A scene with neither isn't drafted, so no pass
    revises it. With no scene at all: 3000 words, 1 scene, and a WARNING."""
    counts: dict[str, int] = {}
    metadata_csv = os.path.join(project_dir, 'reference', 'scenes.csv')
    if os.path.isfile(metadata_csv):
        from storyforge.csv_cli import get_column
        for sid, wc in zip(get_column(metadata_csv, 'id'),
                           get_column(metadata_csv, 'word_count')):
            if wc.strip().isdigit() and int(wc) > 0:
                counts[sid] = int(wc)
    scenes_dir = os.path.join(project_dir, 'scenes')
    if os.path.isdir(scenes_dir):
        for f in os.listdir(scenes_dir):
            if f.endswith('.md') and f[:-3] not in counts:
                with open(os.path.join(scenes_dir, f), encoding='utf-8') as fh:
                    counts[f[:-3]] = len(fh.read().split())
    if counts:
        return sum(counts.values()) // len(counts), len(counts)
    log('WARNING: no scene has a word count or a scene file; the cost forecast '
        'assumes one scene of 3000 words')
    return 3000, 1


# ============================================================================
# Scene registration for new scenes created during revision
# ============================================================================

def _scene_texts(project_dir: str) -> dict[str, str]:
    scenes_dir = os.path.join(project_dir, 'scenes')
    texts = {}
    if os.path.isdir(scenes_dir):
        for name in os.listdir(scenes_dir):
            if name.endswith('.md'):
                with open(os.path.join(scenes_dir, name), encoding='utf-8') as f:
                    texts[name[:-3]] = f.read()
    return texts


def _unsafe_scene_writes(project_dir: str, before: dict[str, str]) -> list[str]:
    """Scenes changed since ``before`` whose new text fails
    ``parsing.unsafe_scene_reason``, one line each."""
    from storyforge.parsing import unsafe_scene_reason
    problems = []
    for sid, text in sorted(_scene_texts(project_dir).items()):
        if before.get(sid) == text:
            continue
        reason = unsafe_scene_reason(text, before.get(sid))
        if reason:
            problems.append(f'scene {sid} was rewritten unsafely: {reason}')
    return problems


def _content_snapshot(project_dir: str) -> dict[str, str]:
    """Hash of every file a revision pass may change, by relative path."""
    import hashlib
    snapshot = {}
    for sub in ('scenes', 'reference', os.path.join('working', 'coaching')):
        root = os.path.join(project_dir, sub)
        for dirpath, _, files in os.walk(root):
            for name in files:
                path = os.path.join(dirpath, name)
                with open(path, 'rb') as f:
                    snapshot[os.path.relpath(path, project_dir)] = hashlib.sha1(f.read()).hexdigest()
    return snapshot


class UpstreamApplyError(Exception):
    """A structural/registry pass reply that cannot be applied as written."""


def _seq_key(row: dict) -> float:
    try:
        return float(row.get('seq') or 0)
    except ValueError:
        return 0.0


def _apply_upstream_blocks(project_dir: str, response_text: str) -> tuple[list[str], set]:
    """Apply a structural/registry pass's CSV blocks to the reference CSVs.

    Every block is merged and checked before anything is written, so a reply
    that fails a check changes nothing. Raises UpstreamApplyError when the
    reply has no usable CSV block, when a new scenes.csv row has no ``seq`` or
    ``pov``, or when a scene the reply touches would share its ``seq`` in the
    merged scenes.csv. A blank
    value in the reply leaves the existing field as it is (models omit what
    they don't change). Returns (files written, scene ids touched).
    """
    from storyforge.prompts_elaborate import parse_stage_response, csv_block_to_rows
    from storyforge.elaborate import _read_csv_as_map, _write_csv, _FILE_MAP

    csv_file_map = {
        'scenes-csv': 'scenes.csv',
        'scenes-csv-update': 'scenes.csv',
        'intent-csv': 'scene-intent.csv',
        'briefs-csv': 'scene-briefs.csv',
    }
    ref_dir = os.path.join(project_dir, 'reference')
    merged: dict[str, dict] = {}
    affected = set()
    for label, content in parse_stage_response(response_text).items():
        fname = csv_file_map.get(label)
        if not fname:
            continue
        rows = [r for r in csv_block_to_rows(content) if r.get('id', '')]
        if not rows:
            continue
        existing = merged.setdefault(fname, _read_csv_as_map(os.path.join(ref_dir, fname)))
        for row in rows:
            sid = row['id']
            affected.add(sid)
            if sid in existing:
                existing[sid].update({k: v for k, v in row.items() if v and k != 'id'})
            else:
                if fname == 'scenes.csv':
                    missing = [c for c in ('seq', 'pov') if not (row.get(c) or '').strip()]
                    if missing:
                        raise UpstreamApplyError(
                            f'new scene {sid} has no {" or ".join(missing)}')
                new = {c: '' for c in _FILE_MAP[fname]}
                new.update(row)
                existing[sid] = new
    if not merged:
        raise UpstreamApplyError('the reply has no CSV block to apply')

    scenes = merged.get('scenes.csv')
    if scenes:
        by_seq: dict[str, list[str]] = {}
        for sid, row in scenes.items():
            seq = (row.get('seq') or '').strip()
            if seq:
                by_seq.setdefault(seq, []).append(sid)
        for seq, ids in by_seq.items():
            if len(ids) > 1 and affected.intersection(ids):
                raise UpstreamApplyError(f'scenes {", ".join(ids)} would share seq {seq}')

    for fname, rows in merged.items():
        if fname == 'scenes.csv':
            ordered = sorted(rows.values(), key=_seq_key)
        else:
            ordered = sorted(rows.values(), key=lambda r: r.get('id', ''))
        _write_csv(os.path.join(ref_dir, fname), ordered, _FILE_MAP[fname])
    return sorted(merged), affected


def _register_new_scenes(project_dir, targets, pass_name):
    """Register new scenes (NEW: prefix in targets) in metadata CSVs."""
    meta_csv = os.path.join(project_dir, 'reference', 'scenes.csv')
    intent_csv = os.path.join(project_dir, 'reference', 'scene-intent.csv')

    new_ids = []
    for t in targets.split(';'):
        t = t.strip()
        if t.startswith('NEW:'):
            new_ids.append(t[4:])

    if not new_ids:
        return

    # Find max seq
    max_seq = 0
    if os.path.isfile(meta_csv):
        with open(meta_csv) as f:
            lines = f.readlines()
        if lines:
            m_header = lines[0].strip().split('|')
            seq_idx = m_header.index('seq') if 'seq' in m_header else 1
            for line in lines[1:]:
                parts = line.strip().split('|')
                if len(parts) > seq_idx:
                    try:
                        seq = int(parts[seq_idx])
                        if seq > max_seq:
                            max_seq = seq
                    except ValueError:
                        pass

    registered = 0
    for sid in new_ids:
        scene_file = os.path.join(project_dir, 'scenes', f'{sid}.md')
        if not os.path.isfile(scene_file):
            continue

        # Check if already registered
        if os.path.isfile(meta_csv):
            with open(meta_csv) as f:
                if any(line.startswith(f'{sid}|') for line in f):
                    continue

        max_seq += 1
        wc = len(open(scene_file).read().split())

        # Generate title from slug
        title = ' '.join(w.capitalize() for w in sid.split('-'))

        if os.path.isfile(meta_csv):
            from storyforge.csv_cli import append_row
            append_row(meta_csv, f'{sid}|{max_seq}|{title}|||||||drafted|{wc}|')
            log(f'  Registered new scene in metadata: {sid} (seq {max_seq})')

        if os.path.isfile(intent_csv):
            from storyforge.csv_cli import append_row
            append_row(intent_csv, f'{sid}|Created by revision pass: {pass_name}|||||')
            log(f'  Registered new scene in intent: {sid}')

        registered += 1

    if registered > 0:
        log(f'  Registered {registered} new scene(s) in metadata and intent CSVs')


# ============================================================================
# Main
# ============================================================================

def _fix_upstream_before_passes(project_dir: str, scene_ids: list[str],
                                pass_forecast: float) -> None:
    """`--naturalness`'s brief fixes and redrafts, on the run's branch,
    after the forecast of them and the passes was approved. While they run
    the passes' forecast is kept from the re-checks the redrafts owe; then
    the passes are checked again with what the fixes actually spent."""
    with _run_budget().reserving(pass_forecast):
        fixed, _ = _fix_and_redraft(project_dir, scene_ids)
    if fixed:
        _commit(project_dir, f'Naturalness: upstream brief fixes for {len(fixed)} scenes',
                ['reference/', 'scenes/', 'working/'])
        done = (f'no pass run; the brief fixes and redrafts of {", ".join(fixed)} '
                f'are committed')
    else:
        done = 'no pass run; the brief fixes changed nothing'
    _exit_if_over_threshold(pass_forecast, done,
                            'start from a later pass (`storyforge revise N`)')


def main(argv=None):
    """`_main`, metered: the cost threshold is one budget for the session
    (`costs.RunBudget`), so the re-checks after each gated scene get only
    what the passes, redrafts and gate runs before them left."""
    from storyforge import api
    with api.metered() as meter, _budget_scope(meter):
        return _main(argv)


def _main(argv=None):
    from datetime import datetime
    args = parse_args(argv or [])
    install_signal_handlers()
    session_start = datetime.now().strftime('%Y-%m-%dT%H:%M:%S')

    project_dir = detect_project_root()
    # the re-checks after each gated scene check the threshold: a bad value
    # stops the run here, not after the passes were paid for
    from storyforge.costs import exit_if_bad_threshold
    exit_if_bad_threshold()
    from storyforge.ledger import exit_if_not_migrated, exit_if_unordered
    exit_if_not_migrated(project_dir)  # the registries live in the ledger
    exit_if_unordered(project_dir)  # drafting reads the ledger as of each scene
    # A redraft reads drafting.prior_prose; a bad value found there would
    # stop it after the brief rewrites before it were paid for and saved
    from storyforge.prompts import prior_prose_mode
    try:
        prior_prose_mode(project_dir)
    except ValueError as e:
        log(f'ERROR: {e}')
        sys.exit(1)

    log_dir = os.path.join(project_dir, 'working', 'logs')
    os.makedirs(log_dir, exist_ok=True)
    set_log_file(os.path.join(log_dir, 'revision-log.txt'))

    python_lib = os.path.join(os.path.dirname(os.path.dirname(__file__)))

    # Resolve plan file
    csv_plan_file = os.path.join(project_dir, 'working', 'plans', 'revision-plan.csv')
    yaml_plan_file = os.path.join(project_dir, 'working', 'plans', 'revision-plan.yaml')

    # Check mutually exclusive modes
    mode_count = sum([args.structural, args.polish, args.naturalness, args.scores])
    if mode_count > 1:
        print('ERROR: --structural, --polish, --naturalness, and --scores are mutually exclusive.', file=sys.stderr)
        sys.exit(1)

    # Validate --loop
    if args.loop:
        if not args.polish:
            print('ERROR: --loop requires --polish', file=sys.stderr)
            sys.exit(1)
        if args.dry_run:
            print('ERROR: --loop and --dry-run are incompatible', file=sys.stderr)
            sys.exit(1)
        if args.interactive:
            print('ERROR: --loop and --interactive are incompatible', file=sys.stderr)
            sys.exit(1)

    # Validate --skip-initial-score / --skip-final-score
    if args.skip_initial_score and not args.loop:
        print('ERROR: --skip-initial-score requires --loop', file=sys.stderr)
        sys.exit(1)
    if args.skip_final_score and not args.loop:
        print('ERROR: --skip-final-score requires --loop', file=sys.stderr)
        sys.exit(1)

    # Loop mode — takes over execution entirely
    if args.loop:
        _run_polish_loop(project_dir, args.max_loops, args.coaching,
                         skip_initial_score=args.skip_initial_score,
                         skip_final_score=args.skip_final_score)
        return

    # Auto-generate plans. A generated plan is written (and revision-plan.csv
    # pointed at it) only once the forecast is approved: a refused run
    # leaves the plan it would have replaced (#510's review, SF-3)
    new_plan = ''            # what kind of plan was generated, for `_save_plan`
    upstream_scenes: list[str] = []   # naturalness: briefs to fix before the passes
    if args.polish:
        log('Polish mode -- generating craft-only revision plan...')
        plan_rows = _generate_polish_plan(csv_plan_file, project_dir, write=False)
        new_plan = 'single-pass polish'
    elif args.naturalness:
        log('Naturalness mode -- generating 3-pass plan for AI pattern removal...')
        plan_rows = _generate_naturalness_plan(csv_plan_file, project_dir, write=False)
        new_plan = '3-pass naturalness'
        # Check for upstream causes first (load latest diagnosis if available)
        _naturalness_diag_rows = []
        _latest_diag = os.path.join(project_dir, 'working', 'scores', 'latest', 'diagnosis.csv')
        if os.path.isfile(_latest_diag):
            _naturalness_diag_rows = _read_diagnosis(os.path.dirname(_latest_diag))
        # (with no diagnosis, an adaptation's source drift still counts)
        upstream_scenes = _detect_upstream_scenes(project_dir, _naturalness_diag_rows)
    elif args.scores:
        log('Scores mode -- generating revision plan from diagnosis data...')
        diag_file = os.path.join(project_dir, 'working', 'scores', 'latest', 'diagnosis.csv')
        if not os.path.isfile(diag_file):
            log(f'ERROR: No diagnosis found at {diag_file}')
            log('Run: storyforge score first')
            sys.exit(1)
        diag_rows = _read_diagnosis(os.path.dirname(diag_file))
        findings_dir = os.path.dirname(diag_file)
        plan_rows = _generate_scores_plan(csv_plan_file, diag_rows,
                                          findings_dir=findings_dir, write=False)
        if not plan_rows:
            log('No actionable items in diagnosis -- nothing to revise')
            sys.exit(0)
        new_plan = 'score-driven'
    elif args.structural:
        plan_rows = _generate_structural_plan(project_dir, csv_plan_file, write=False)
        new_plan = 'structural'
    elif os.path.isfile(csv_plan_file):
        log(f'Using CSV revision plan: {csv_plan_file}')
        plan_rows = _read_csv_plan(csv_plan_file)
    elif os.path.isfile(yaml_plan_file):
        log('DEPRECATION: Using YAML revision plan. Migrate to working/plans/revision-plan.csv.')
        # For YAML fallback, we just read it via the original bash approach.
        # The Python migration handles CSV-first plans.
        log('ERROR: YAML plan support not available in Python migration. Convert to CSV.')
        sys.exit(1)
    else:
        log(f'ERROR: Revision plan not found at {csv_plan_file}')
        log("Run the storyforge-plan-revision skill first to create a revision plan.")
        sys.exit(1)

    total_passes = _count_passes(plan_rows)
    if total_passes == 0:
        log('ERROR: No passes found in revision plan')
        sys.exit(1)

    # Coaching level
    if args.coaching:
        apply_coaching_override(args)
    effective_coaching = get_coaching_level(project_dir)

    # API key check
    if not args.dry_run and not args.interactive:
        try:
            get_api_key()
        except RuntimeError:
            log('ERROR: ANTHROPIC_API_KEY not set. Required for direct API mode.')
            log('  Set it with: export ANTHROPIC_API_KEY=your-key')
            log('  Or use --interactive to run via claude -p instead.')
            sys.exit(1)

    os.makedirs(os.path.join(project_dir, 'working', 'coaching'), exist_ok=True)

    # Build shared context once for prompt caching (direct API mode only)
    system = None
    if not args.dry_run and not args.interactive:
        from storyforge.common import build_shared_context
        revise_model = select_revision_model('prose', 'prose revision')
        system = build_shared_context(project_dir, model=revise_model)

    # Determine start point
    start_pass = args.pass_num
    if start_pass == 0:
        for i in range(1, total_passes + 1):
            status = _read_pass_field(plan_rows, i, 'status')
            if status == 'planned':
                log(f"WARNING: Pass {i} has status 'planned' -- normalizing to 'pending'")
                _update_pass_field(plan_rows, i, 'status', 'pending', csv_plan_file)
                status = 'pending'
            if status in ('pending', 'in_progress'):
                start_pass = i
                break
        if start_pass == 0:
            log('All passes are already completed. Nothing to do.')
            return

    if start_pass < 1 or start_pass > total_passes:
        log(f'ERROR: Pass number {start_pass} is out of range (1-{total_passes})')
        sys.exit(1)

    # Cost forecast, before a branch, a PR, a plan written or anything spent
    # (#503; #510's review: --naturalness's brief fixes and their redrafts
    # come first, and a dry run runs neither them nor the passes)
    per_pass = 0.0
    pass_forecast = 0.0
    fix_forecast = _upstream_fix_cost(project_dir, upstream_scenes) if upstream_scenes else 0.0
    if upstream_scenes:
        log(f'Upstream issues in {len(upstream_scenes)} scene(s): '
            f'{", ".join(upstream_scenes)}')
    if args.dry_run and upstream_scenes:
        log(f'  DRY RUN: their brief fixes and redrafts (~${fix_forecast:.2f}) are '
            f'skipped; a run fixes them before the passes')
    if not args.dry_run:
        pending = sum(
            1 for i in range(start_pass, total_passes + 1)
            if _read_pass_field(plan_rows, i, 'status') != 'completed'
        )
        revise_model = select_revision_model('prose', 'prose revision')
        per_pass = _pass_cost(project_dir, revise_model)
        pass_forecast = per_pass * pending
        from storyforge import gate
        # the gate's run on each scene a pass rewrites is extra, and how many
        # scenes a pass rewrites isn't known here (F-151)
        log(f'Cost forecast: ~${fix_forecast + pass_forecast:.2f}: '
            + (f'brief fixes and redrafts for {len(upstream_scenes)} scene(s) '
               f'~${fix_forecast:.2f} (the gate on each redraft included), then '
               if upstream_scenes else '')
            + f'{pending} passes @ ~${per_pass:.2f}, plus about '
              f'${gate.RECHECK_COST_PER_SCENE:.2f} for the gate on each rewritten scene')
        # One budget for the session (#503's review, CR-1): the gate on what
        # the passes rewrite always runs, and the re-checks get what the
        # actual spend, the gate and the work still to come leave
        _exit_if_over_threshold(
            fix_forecast + pass_forecast, 'nothing revised',
            (f'fix the briefs of {", ".join(upstream_scenes)} first (`storyforge hone`), '
             f'or ' if upstream_scenes else '')
            + 'start from a later pass (`storyforge revise N`)')
        _log_recheck_budget()

    # Project title
    project_title = read_yaml_field('project.title', project_dir) or '(untitled project)'

    # Pipeline manifest
    manifest = os.path.join(project_dir, 'working', 'pipeline.csv')
    cycle_id = '0'
    if os.path.isfile(manifest):
        with open(manifest) as f:
            lines = f.readlines()
        if len(lines) > 1:
            p_header = lines[0].strip().split('|')
            cycle_col = p_header.index('cycle') if 'cycle' in p_header else 0
            last_parts = lines[-1].strip().split('|')
            cycle_id = last_parts[cycle_col] if len(last_parts) > cycle_col else '0'

    # Branch + PR setup
    if not args.dry_run:
        create_branch('revise', project_dir)
        ensure_branch_pushed(project_dir)

        task_lines = ['### Progress']
        for i in range(1, total_passes + 1):
            pname = _read_pass_field(plan_rows, i, 'name')
            task_lines.append(f'- [ ] Pass: {pname}')
        task_lines.append('- [ ] Review')

        pr_body = (
            f'## Revision\n\n'
            f'**Project:** {project_title}\n'
            f'**Passes:** {total_passes}\n\n'
            + '\n'.join(task_lines)
        )

        create_draft_pr(f'Revise: {project_title}', pr_body, project_dir, 'revision')

    if not args.dry_run and cycle_id != '0':
        # Update pipeline cycle
        if os.path.isfile(manifest):
            with open(manifest) as f:
                lines = f.readlines()
            header = lines[0].strip().split('|')
            if 'status' in header and 'cycle' in header:
                status_idx = header.index('status')
                cycle_idx = header.index('cycle')
                for i in range(1, len(lines)):
                    parts = lines[i].strip().split('|')
                    if len(parts) > cycle_idx and parts[cycle_idx] == cycle_id:
                        while len(parts) <= status_idx:
                            parts.append('')
                        parts[status_idx] = 'revising'
                        lines[i] = '|'.join(parts) + '\n'
                with open(manifest, 'w') as f:
                    f.writelines(lines)

    if upstream_scenes and not args.dry_run:
        _fix_upstream_before_passes(project_dir, upstream_scenes, pass_forecast)
    if new_plan:
        _save_plan(csv_plan_file, plan_rows, new_plan)

    # ---- Load reader annotations if available ----
    annotations_csv = os.path.join(project_dir, 'working', 'annotations.csv')
    annotation_findings = []
    annotation_protection = []
    if os.path.isfile(annotations_csv) and not args.no_annotations:
        from storyforge.annotations import load_annotations_csv, generate_revision_findings
        ann_data = load_annotations_csv(project_dir)
        craft_findings, struct_findings, prot_passages = generate_revision_findings(ann_data)
        annotation_findings = craft_findings + struct_findings
        annotation_protection = prot_passages
        if annotation_findings:
            log(f'Reader annotations: {len(annotation_findings)} finding(s) from unaddressed annotations')
        if annotation_protection:
            log(f'Reader annotations: {len(annotation_protection)} passage(s) to protect')

    log('============================================')
    log(f'Storyforge Revision -- {project_title}')
    log(f'Plan: {csv_plan_file}')
    log(f'Cycle: {cycle_id}')
    log(f'Coaching level: {effective_coaching}')
    log(f'Starting from pass: {start_pass} of {total_passes}')
    log('============================================')

    # Check for deferred redrafting (multiple upstream passes)
    deferred_scenes, upstream_count = _collect_upstream_scenes(plan_rows)
    defer_redraft = upstream_count >= 1 and len(deferred_scenes) > 0
    if defer_redraft:
        log(f'Deferred redrafting enabled: {upstream_count} upstream passes, '
            f'{len(deferred_scenes)} scenes will be redrafted after all CSV fixes')
    redraft_needed = set()
    redraft_error = None  # RedraftError from a redraft; exit 1 after the summary

    # ---- MAIN PASS LOOP ----
    for pass_num in range(start_pass, total_passes + 1):
        pass_name = _read_pass_field(plan_rows, pass_num, 'name')
        pass_scope = _read_pass_field(plan_rows, pass_num, 'scope')
        pass_purpose = _read_pass_field(plan_rows, pass_num, 'purpose')
        pass_status = _read_pass_field(plan_rows, pass_num, 'status')

        if pass_status == 'planned':
            _update_pass_field(plan_rows, pass_num, 'status', 'pending', csv_plan_file)
            pass_status = 'pending'

        if pass_status == 'completed':
            log(f'Pass {pass_num}/{total_passes}: {pass_name} -- already completed, skipping.')
            continue

        log(f'--- Pass {pass_num}/{total_passes}: {pass_name} ---')
        if _RUN_BUDGET is not None and not args.dry_run:
            # the passes after this one are forecast-approved: the re-checks
            # in this one may not take their share
            _RUN_BUDGET.owed = per_pass * sum(
                1 for i in range(pass_num + 1, total_passes + 1)
                if _read_pass_field(plan_rows, i, 'status') != 'completed')
        log(f'  Purpose: {pass_purpose}')
        log(f'  Scope: {pass_scope}')

        # Build CSV config block for prompt
        targets = _read_pass_field(plan_rows, pass_num, 'targets')
        guidance = _read_pass_field(plan_rows, pass_num, 'guidance')
        protection = _read_pass_field(plan_rows, pass_num, 'protection')
        findings = _read_pass_field(plan_rows, pass_num, 'findings')
        fix_location = _read_pass_field(plan_rows, pass_num, 'fix_location')

        # Inject reader annotation findings for this pass
        if annotation_findings:
            relevant = [f for f in annotation_findings]
            if relevant:
                guidance += '\n\n## Reader Annotations\n'
                guidance += 'The following passages were flagged by readers:\n\n'
                for finding in relevant:
                    guidance += finding['guidance'] + '\n\n'

        # Inject reader protection constraints
        if annotation_protection:
            prot_texts = [p['text'][:80] for p in annotation_protection]
            prot_block = 'Reader-validated passages (do not rewrite): ' + '; '.join(f'"{t}"' for t in prot_texts)
            if protection:
                protection += '\n' + prot_block
            else:
                protection = prot_block

        # Resolve effective scope
        effective_scope = pass_scope
        if pass_scope in ('scene-level', 'targeted') and targets:
            effective_scope = targets.replace(';', ',')
        elif pass_scope in ('scene-level', 'targeted'):
            effective_scope = 'full'

        # A prose pass that stopped over unwritten scenes re-runs only those
        owed = _read_pass_field(plan_rows, pass_num, 'owed')
        if owed and fix_location not in ('brief', 'intent', 'structural', 'registry'):
            log(f'  Re-running for the scenes this pass still owes: '
                f'{owed.replace(";", ", ")}')
            targets = owed
            effective_scope = owed.replace(';', ',')

        # Build config block for prompt builder
        pass_block = f'- name: {pass_name}\n    purpose: {pass_purpose}\n    scope: {pass_scope}'
        if targets:
            pass_block += f'\n    targets: {targets}'
        if guidance:
            pass_block += f'\n    guidance: {guidance}'
        if protection:
            pass_block += f'\n    protection: {protection}'
        if findings:
            pass_block += f'\n    findings: {findings}'

        # Determine API mode flags
        api_flag = ''
        if not args.dry_run and not args.interactive and os.environ.get('ANTHROPIC_API_KEY'):
            api_flag = '--api-mode'

        # Build prompt
        log('  Building revision prompt...')

        if fix_location in ('brief', 'intent'):
            # ---- DELEGATE TO HONE ----
            # Mark as in_progress
            _update_pass_field(plan_rows, pass_num, 'status', 'in_progress', csv_plan_file)
            start_time = time.time()
            pass_model = select_revision_model(pass_name, pass_purpose)

            ref_dir = os.path.join(project_dir, 'reference')

            findings_path = os.path.join(
                project_dir, 'working', 'plans',
                f'hone-findings-{pass_name}.csv')
            _write_hone_findings(findings_path, fix_location, targets, guidance, ref_dir=ref_dir)

            target_csv = os.path.join(
                project_dir, 'reference',
                'scene-briefs.csv' if fix_location == 'brief' else 'scene-intent.csv')
            old_hash = _file_hash(target_csv)

            # Resolve targets to valid scene IDs (handles character names, full scope)
            if targets:
                from storyforge.elaborate import _read_csv_as_map
                valid_ids = set(_read_csv_as_map(target_csv).keys())
                raw_targets = [t.strip() for t in targets.split(';') if t.strip()]
                target_scenes = _resolve_targets_to_scene_ids(raw_targets, valid_ids, ref_dir)
                if not target_scenes:
                    log(f'  WARNING: No valid scene IDs resolved from targets "{targets}" — skipping pass')
                    _update_pass_field(plan_rows, pass_num, 'status', 'failed', csv_plan_file)
                    continue
            else:
                target_scenes = None

            log(f'  Delegating to hone ({fix_location}) for {len(target_scenes) if target_scenes else "all"} scenes...')

            from storyforge.hone import hone_briefs, hone_intent
            hone_fn = hone_briefs if fix_location == 'brief' else hone_intent
            hone_result = hone_fn(
                ref_dir=ref_dir,
                project_dir=project_dir,
                scene_ids=target_scenes,
                model=pass_model,
                log_dir=log_dir,
                coaching_level=effective_coaching,
                findings_file=findings_path,
            )

            new_hash = _file_hash(target_csv)
            end_time = time.time()
            duration = int(end_time - start_time)
            minutes, secs = duration // 60, duration % 60

            if old_hash == new_hash:
                log(f'  FAILED: Pass "{pass_name}" produced no changes to {os.path.basename(target_csv)}')
                log(f'  Time: {minutes}m{secs}s')
                _update_pass_field(plan_rows, pass_num, 'status', 'failed', csv_plan_file)
                continue

            fields_changed = hone_result.get('fields_rewritten', 0)
            scenes_changed = hone_result.get('scenes_rewritten', 0)
            log(f'  Upstream: {scenes_changed} scenes, {fields_changed} fields rewritten')
            for sid, reasons in (hone_result.get('rejected') or {}).items():
                log(f'  Rewrite refused for {sid}: {"; ".join(reasons)}')

            # Track or execute redraft: only scenes whose brief or intent
            # changed (a refused rewrite leaves its prose alone)
            if effective_coaching == 'full' and targets:
                changed_ids = set(hone_result.get('changed') or [])
                affected = [s for s in (target_scenes or []) if s in changed_ids]
                if defer_redraft:
                    redraft_needed.update(affected)
                    log(f'  Deferred redraft for {len(affected)} scenes (will batch after all upstream passes)')
                elif affected:
                    try:
                        _redraft_from_briefs(project_dir, affected, pass_model,
                                             log_dir, system=system)
                    except RedraftError as e:
                        _report_redraft_error(e)
                        _update_pass_field(plan_rows, pass_num, 'status', 'failed',
                                           csv_plan_file)
                        redraft_error = e
                        continue

            # Log usage (hone handles its own API logging; pass empty string)
            _log_usage(project_dir, '', 'revise', pass_name, pass_model, duration)

            # Git commit if needed
            _commit(project_dir, f'Revision: {pass_name}', ['.'])
            _git(project_dir, 'push', check=False)

            # Mark completed
            _update_pass_field(plan_rows, pass_num, 'status', 'completed', csv_plan_file)
            log(f'SUCCESS: Pass {pass_num}/{total_passes} ({pass_name}) -- {minutes}m{secs}s')
            update_pr_task(f'Pass: {pass_name}', project_dir)

            # Pause between passes
            if pass_num < total_passes and not args.interactive:
                next_status = _read_pass_field(plan_rows, pass_num + 1, 'status')
                if next_status != 'completed':
                    log('Pausing 10s before next pass...')
                    time.sleep(10)
            continue
            # ---- END HONE DELEGATION ----

        elif fix_location in ('structural', 'registry'):
            # Inline prompt for structural/registry
            from storyforge.elaborate import get_scenes
            ref_dir = os.path.join(project_dir, 'reference')
            scenes = get_scenes(ref_dir)

            target_ids = [t.strip() for t in targets.split(';') if t.strip()] if targets else [s['id'] for s in scenes]
            scene_data = [s for s in scenes if s['id'] in target_ids]

            data_block = []
            for s in scene_data:
                data_block.append(f"Scene: {s.get('id', '')} (seq {s.get('seq', '')}, POV: {s.get('pov', '')})")
                for k, v in s.items():
                    if k not in ('id', 'seq', 'pov') and v:
                        data_block.append(f'  {k}: {str(v)[:120]}')
                data_block.append('')

            prompt = f'''You are performing an upstream revision on scene data for a novel.

## Pass: {pass_name}
## Purpose: {pass_purpose}
## Fix Location: {fix_location}

## Guidance
{guidance or 'No specific guidance provided.'}

## Protection
{protection or 'No protection constraints.'}

## Current Scene Data

{chr(10).join(data_block)}

## Instructions

Revise the scenes.csv data to address the purpose above.

Output your changes as pipe-delimited CSV rows in a fenced block:

```scenes-csv
(header row — first column MUST be 'id', not 'scene_id')
(one row per scene that needs changes)
```

Rules:
- The first column must be named 'id' (not 'scene_id')
- Only modify scenes listed in the targets
- Preserve all values you are not changing
- Output the full row for each modified scene
'''
        else:
            # Standard prose revision -- use revision module
            try:
                cmd_args = [sys.executable, '-m', 'storyforge.revision', 'build-prompt',
                     pass_name, pass_purpose, effective_scope or pass_scope, project_dir,
                     '--config', pass_block, '--coaching', effective_coaching]
                if api_flag:
                    cmd_args.append(api_flag)
                if system:
                    cmd_args.append('--system-context')
                result = subprocess.run(
                    cmd_args,
                    capture_output=True, text=True, check=True,
                    env={**os.environ, 'PYTHONPATH': python_lib},
                )
                prompt = result.stdout
                _log_prompt_warnings(result.stderr)
            except subprocess.CalledProcessError as e:
                log(f'ERROR: Failed to build prompt for pass \'{pass_name}\'')
                log(f'  {e.stderr}')
                sys.exit(1)

        # Dry-run: print and continue
        if args.dry_run:
            print(f'===== DRY RUN: {pass_name} (pass {pass_num}/{total_passes}) =====')
            print(prompt)
            print(f'===== END DRY RUN: {pass_name} =====')
            print()
            continue

        # Mark as in_progress
        _update_pass_field(plan_rows, pass_num, 'status', 'in_progress', csv_plan_file)

        # Record git HEAD before invocation
        head_before = _git(project_dir, 'rev-parse', 'HEAD', check=False).stdout.strip()
        served_before = len(fallback_replies())

        step_log = os.path.join(log_dir, f'revision-pass-{pass_num}-{pass_name}.log')
        snapshot_before = _content_snapshot(project_dir)
        # Direct prose passes: the scenes the reply wrote, and those it held
        # but that were not written (cut off, unsafe), with why
        written_scenes: list[str] | None = None
        skipped_scenes: dict[str, str] = {}
        start_time = time.time()

        # Select model
        pass_model = select_revision_model(pass_name, pass_purpose)

        # Phase 4 §5: a prose pass's scenes go through the gate, so at full
        # coaching (the level that writes prose) it may not start behind a
        # scene waiting on it. Prose written at any level is gated.
        gated = fix_location not in ('structural', 'registry')
        if gated and effective_coaching == 'full':
            _exit_if_pass_blocked(project_dir, targets)
        # the book before the pass: what its gate counts as already there
        from storyforge import gate as _gate
        gate_baseline = _gate.snapshot(project_dir) if gated else None
        rewritten: list[str] = []   # the scenes this pass rewrote, for the gate

        if args.interactive:
            # Interactive mode: claude writes scene files itself, so check
            # what it wrote the way extracted replies are checked
            scenes_before = _scene_texts(project_dir)
            subprocess.run(
                ['claude', prompt,
                 '--model', pass_model,
                 '--dangerously-skip-permissions'],
                cwd=project_dir,
            )
            # no meter sees the CLI's spend: counted at the pass's forecast
            _run_budget().charge(per_pass)
            unsafe = _unsafe_scene_writes(project_dir, scenes_before)
            if unsafe:
                for problem in unsafe:
                    log(f'ERROR: {problem}')
                log(f'Pass \'{pass_name}\' is not marked completed. Inspect with `git diff` '
                    f'(and `git log`, if the session committed) and restore what is wrong.')
                sys.exit(1)
            rewritten = [sid for sid, text in _scene_texts(project_dir).items()
                         if scenes_before.get(sid) != text]
            exit_code = 0
        else:
            # Direct API mode
            log(f'  Invoking API for revision (model: {pass_model})...')
            try:
                response = invoke_to_file(prompt, pass_model, step_log,
                                         max_tokens=max_output_tokens(pass_model),
                                         label=f'pass {pass_num}/{total_passes} ({pass_name})',
                                         timeout=REVISION_TIMEOUT,
                                         system=system or None,
                                         # prose passes only; upstream ones write CSV
                                         fallback=fix_location not in ('structural', 'registry'))
                exit_code = 0
            except Exception as e:
                log(f'  API call failed: {e}')
                exit_code = 1

            # Check for truncation
            if exit_code == 0:
                stop = response.get('stop_reason', 'end_turn')
                if stop == 'max_tokens':
                    log(f'  WARNING: Pass "{pass_name}" was truncated (hit max_tokens). '
                        f'The last scene in the output will be discarded to prevent data loss.')

            # Process response
            if exit_code == 0:
                if fix_location in ('structural', 'registry'):
                    # Upstream revision -- apply CSV updates
                    log(f'  Upstream revision (fix_location: {fix_location}) -- applying CSV updates...')
                    try:
                        updated_files, affected_scenes = _apply_upstream_blocks(
                            project_dir, extract_text(response))
                    except UpstreamApplyError as e:
                        log(f'ERROR: Pass \'{pass_name}\' could not be applied: {e}')
                        log(f'Nothing was written; the pass is not marked completed. See {step_log}')
                        sys.exit(1)
                    log(f'  Updated: {", ".join(updated_files)}')
                    log(f'  Affected scenes: {", ".join(sorted(affected_scenes))}')
                else:
                    # Standard prose revision -- extract scenes from response
                    try:
                        written_scenes, skipped_scenes = _extract_scenes(
                            step_log, project_dir, python_lib)
                        # Saved before the commit below, so the plan names
                        # what's still owed in the same commit as the scenes.
                        # A reply with no scene in it leaves owed as it was
                        # (the unchanged-content check stops the pass)
                        if written_scenes or skipped_scenes:
                            owed_now = _owed_scenes(
                                targets, written_scenes, skipped_scenes,
                                cut_off=response.get('stop_reason') == 'max_tokens')
                            _update_pass_field(plan_rows, pass_num, 'owed',
                                               owed_now, csv_plan_file)
                            for entry in _split_targets(owed_now):
                                sid = entry.removeprefix('NEW:')
                                if sid not in skipped_scenes:
                                    skipped_scenes[sid] = 'the reply was cut off before it'
                        rewritten = list(written_scenes)
                    except ExtractError as e:
                        # No scene was written: the unchanged-content check below stops the pass
                        log(f'  API response received, but no scene could be read from it: {e}')
                        written_scenes = []
                    if not written_scenes and not skipped_scenes:
                        log('  API response received (analytical pass, no scene markers)')

                    # Register new scenes
                    if targets:
                        _register_new_scenes(project_dir, targets, pass_name)

        end_time = time.time()
        duration = int(end_time - start_time)
        minutes = duration // 60
        secs = duration % 60

        # Log usage
        _log_usage(project_dir, step_log, 'revise', pass_name, pass_model, duration)

        if exit_code != 0:
            log(f'ERROR: API call failed for pass \'{pass_name}\' after {minutes}m{secs}s')
            log(f'See full output: {step_log}')
            log(f'Fix the issue and re-run: storyforge revise {pass_num}')
            sys.exit(1)

        # A pass that changed nothing did not do its job: never mark it completed
        if _content_snapshot(project_dir) == snapshot_before:
            log(f'ERROR: Pass \'{pass_name}\' changed no scene, reference or coaching file.')
            log(f'The pass is not marked completed. See the reply: {step_log}')
            sys.exit(1)

        # Phase 4 §5: each scene it rewrote goes through the gate, in reading
        # order, then the re-check of the later scenes depending on it
        gate_failures = (_gate_pass_scenes(project_dir, rewritten, pass_name, log_dir,
                                           before=gate_baseline)
                         if gated else [])

        # Update word counts
        metadata_csv = os.path.join(project_dir, 'reference', 'scenes.csv')
        if os.path.isfile(metadata_csv) and effective_coaching == 'full':
            from storyforge.csv_cli import list_ids, update_field
            for scene_id in list_ids(metadata_csv):
                scene_file = os.path.join(project_dir, 'scenes', f'{scene_id}.md')
                if os.path.isfile(scene_file):
                    from storyforge.illustrations import count_prose_words
                    with open(scene_file, encoding='utf-8') as f:
                        new_wc = str(count_prose_words(f.read()))
                    update_field(metadata_csv, scene_id, 'word_count', new_wc)

        # Update annotation status for revised scenes
        if annotation_findings and os.path.isfile(annotations_csv):
            from storyforge.annotations import load_annotations_csv as _load_ann, save_annotations_csv as _save_ann
            ann_data = _load_ann(project_dir)
            pass_targets_raw = _read_pass_field(plan_rows, pass_num, 'targets')
            revised_scenes = set()
            if pass_scope == 'full':
                scenes_dir_path = os.path.join(project_dir, 'scenes')
                if os.path.isdir(scenes_dir_path):
                    revised_scenes = {f[:-3] for f in os.listdir(scenes_dir_path) if f.endswith('.md')}
            elif pass_targets_raw:
                revised_scenes = set(t.strip() for t in pass_targets_raw.split(';') if t.strip())
            if written_scenes is not None:  # only what this reply actually rewrote
                revised_scenes &= set(written_scenes)

            updated_count = 0
            for ann_id, ann in ann_data.items():
                if (ann.get('status') == 'new'
                        and ann.get('scene_id') in revised_scenes
                        and ann.get('fix_location') in ('craft', 'structural')):
                    ann['status'] = 'addressed'
                    updated_count += 1

            if updated_count:
                _save_ann(project_dir, ann_data)
                log(f'  Updated {updated_count} annotation(s) to "addressed"')

        # Git commit if Claude didn't
        head_after = _git(project_dir, 'rev-parse', 'HEAD', check=False).stdout.strip()
        if head_before == head_after:
            log('  No commit from Claude. Creating manual commit...')
            if effective_coaching in ('coach', 'strict') and not rewritten:
                _commit(
                    project_dir,
                    f'{effective_coaching.capitalize()}: {pass_name}',
                    ['working/coaching/', 'working/logs/', 'working/costs/', 'working/pipeline.csv'],
                )
            else:
                _commit(project_dir,
                                f'Revision: {pass_name}' + fallback_note(served_before), ['.'])
        elif rewritten:
            # the session committed its own prose; the gate's fixes and
            # ledger came after
            _commit(project_dir, f'Revision: gate the scenes of {pass_name}',
                            ['scenes/', 'reference/', 'working/'])

        # Does the revised prose still agree with the calendar? Reported in
        # the log, never fixed: the prose or the calendar may be wrong.
        changed = _git(project_dir, 'diff', '--name-only', head_before, 'HEAD',
                       '--', 'scenes/', check=False).stdout.split()
        if changed:
            from storyforge.timeline import drift_check
            drift_check(project_dir, [os.path.splitext(os.path.basename(p))[0]
                                      for p in changed if p.endswith('.md')])

        # Push
        _git(project_dir, 'push', check=False)

        if skipped_scenes:
            _log_gate_failures(gate_failures)
            _fail_skipped_scenes(pass_name, skipped_scenes, step_log, owed_saved=True)

        # Mark completed (an interactive session writes the scenes itself,
        # so nothing it was owed is tracked past it)
        _update_pass_field(plan_rows, pass_num, 'owed', '', csv_plan_file)
        _update_pass_field(plan_rows, pass_num, 'status', 'completed', csv_plan_file)
        if gate_failures:
            _commit(project_dir, f'Revision: {pass_name} done, stopped at the gate',
                            [csv_plan_file])
            _fail_gated_pass(pass_name, gate_failures, PLAN_RESUME,
                             redraft_needed if defer_redraft else frozenset())

        commit_short = _git(project_dir, 'rev-parse', '--short', 'HEAD', check=False).stdout.strip()
        log(f'SUCCESS: Pass {pass_num}/{total_passes} ({pass_name}) -- {minutes}m{secs}s, commit {commit_short}')
        update_pr_task(f'Pass: {pass_name}', project_dir)

        # Pause between passes (headless only)
        if pass_num < total_passes and not args.interactive:
            next_status = _read_pass_field(plan_rows, pass_num + 1, 'status')
            if next_status != 'completed':
                log('Pausing 10s before next pass...')
                time.sleep(10)

    # Batch redraft deferred scenes
    if defer_redraft and redraft_needed:
        log(f'\n=== Batch Redraft: {len(redraft_needed)} scenes ===')
        pass_model = select_revision_model('redraft', 'redraft from corrected briefs')
        try:
            _redraft_from_briefs(project_dir, sorted(redraft_needed), pass_model,
                                 log_dir, system=system)
        except RedraftError as e:
            redraft_error = e

    # ---- SESSION SUMMARY ----
    completed = sum(
        1 for i in range(1, total_passes + 1)
        if _read_pass_field(plan_rows, i, 'status') == 'completed'
    )

    log('')
    log('============================================')
    log(f'Revision session complete. {completed}/{total_passes} passes finished.')

    # Structural mode: re-validate
    if args.structural and not args.dry_run:
        log('Re-running structural validation...')
        try:
            from storyforge.structural import (
                structural_score, save_structural_scores,
                load_scores_as_dict, print_score_delta,
            )
            ref_dir = os.path.join(project_dir, 'reference')
            report = structural_score(ref_dir)
            save_structural_scores(report, project_dir)

            pre_path = os.path.join(project_dir, 'working', 'scores', 'structural-pre-revision.csv')
            post_path = os.path.join(project_dir, 'working', 'scores', 'structural-latest.csv')
            pre = load_scores_as_dict(pre_path)
            post = load_scores_as_dict(post_path)

            print('\n=== Structural Score Delta ===')
            print(print_score_delta(pre, post))
            print(f'\nOverall: {report.get("overall", 0):.2f}')

            # Mark proposals as completed
            proposals_file = os.path.join(project_dir, 'working', 'scores', 'structural-proposals.csv')
            if os.path.isfile(proposals_file):
                content = open(proposals_file).read()
                content = content.replace('|pending', '|completed')
                with open(proposals_file, 'w') as f:
                    f.write(content)
                log('Marked all proposals as completed')
        except Exception as e:
            log(f'WARNING: Structural re-validation failed: {e}')

    # Cost summary
    if not args.dry_run:
        print_summary(project_dir, ('revise', 'gate', 'gate-fix'), session_start=session_start)
    report_fallback_replies()

    if redraft_error:
        _report_redraft_error(redraft_error)
        log('============================================')
        sys.exit(1)

    if completed == total_passes:
        log('All revision passes are done!')
        os.makedirs(os.path.join(project_dir, 'working', 'reviews'), exist_ok=True)
        _commit(
            project_dir,
            'Revision complete: advance phase to review',
            ['storyforge.yaml', 'working/pipeline.csv'],
        )
        log('')
        log('Next step: run /storyforge:revise to review results, or /storyforge:score to measure improvement')

    log('============================================')
